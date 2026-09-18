"""Read-only column checks with explicit settings and all findings available in pages."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import ttk

from loan_tape.column_check import (
    DATE_FORMATS,
    EXPECTED_TYPES,
    FINDINGS_PAGE_SIZE,
    ColumnCheck,
    ColumnFinding,
    ColumnRules,
    check_column,
)
from loan_tape.column_profile import ColumnTable, column_scope
from loan_tape.column_ui import ColumnWindow
from loan_tape.inspection import InspectionError
from loan_tape.ranges import column_label
from loan_tape.session import AnalysisSession
from loan_tape.workers import WorkerGroup
from loan_tape.xml_selection import SavedXmlTable


class ColumnCheckWindow:
    def __init__(
        self,
        parent: tk.Misc,
        path: Path,
        table: ColumnTable,
        column: int,
        session: AnalysisSession,
        jump: Callable[[int], None],
        workers: WorkerGroup | None = None,
    ) -> None:
        self.path, self.table, self.column, self.session, self.jump = (
            path,
            table,
            column,
            session,
            jump,
        )
        self.is_xml = isinstance(table, SavedXmlTable)
        self.workers = workers if workers is not None else WorkerGroup()
        self.window = tk.Toplevel(parent)
        self.window.title(f"Check column {column_label(column)} — {table.name}")
        self.window.geometry("900x700")
        self.window.minsize(800, 660)
        self.window.transient(parent.winfo_toplevel())
        self.window.grab_set()
        self.closed = self.busy = False
        self.report: ColumnCheck | None = None
        self.worker: threading.Thread | None = None
        self.cancelled = threading.Event()
        self.delivery_lock = threading.Lock()
        self.results: queue.Queue[ColumnCheck | str | Exception] = queue.Queue()
        self.entries: dict[str, ColumnFinding] = {}
        self.offset = 0
        self.expected = tk.StringVar(master=self.window)
        self.required = tk.BooleanVar(master=self.window, value=True)
        self.date_format = tk.StringVar(
            master=self.window, value="YYYY-MM-DD" if self.is_xml else "Excel dates only"
        )
        self.min_year = tk.StringVar(master=self.window)
        self.max_year = tk.StringVar(master=self.window)
        self.before_reference = tk.BooleanVar(master=self.window, value=False)
        self.status = tk.StringVar(
            master=self.window, value="Choose an expected type, then Run check."
        )
        self.applied = tk.StringVar(master=self.window)
        self.page_label = tk.StringVar(master=self.window)
        page = ttk.Frame(self.window, padding=16)
        page.pack(fill="both", expand=True)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(5, weight=1)
        ttk.Label(
            page, text=f"Check column {column_label(column)}", font=("Segoe UI", 16, "bold")
        ).grid(row=0, sticky="w")
        self.scope_label = ttk.Label(
            page,
            text=column_scope(table, session),
            wraplength=850,
        )
        self.scope_label.grid(row=1, sticky="ew", pady=(5, 10))
        controls = ttk.Frame(page)
        controls.grid(row=2, sticky="ew")
        controls.columnconfigure(3, weight=1)
        ttk.Label(controls, text="Expected type").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.type_selector = ttk.Combobox(
            controls, textvariable=self.expected, values=EXPECTED_TYPES, state="readonly", width=14
        )
        self.type_selector.grid(row=0, column=1, sticky="w")
        self.required_toggle = ttk.Checkbutton(
            controls,
            text="Flag absent / empty / nil values" if self.is_xml else "Flag blank / empty values",
            variable=self.required,
        )
        self.required_toggle.grid(row=0, column=2, sticky="w", padx=14)
        self.run_button = ttk.Button(controls, text="Run check", command=self.run)
        self.run_button.grid(row=0, column=3, sticky="e")
        self.date_options = ttk.Frame(controls)
        self.date_options.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        ttk.Label(self.date_options, text="Text dates").grid(row=0, column=0, sticky="w")
        self.date_selector = ttk.Combobox(
            self.date_options,
            textvariable=self.date_format,
            values=tuple(
                name for name in DATE_FORMATS if not self.is_xml or name != "Excel dates only"
            ),
            state="readonly",
            width=17,
        )
        self.date_selector.grid(row=0, column=1, padx=(8, 14))
        ttk.Label(self.date_options, text="Earliest year").grid(row=0, column=2)
        self.min_entry = ttk.Entry(self.date_options, textvariable=self.min_year, width=7)
        self.min_entry.grid(row=0, column=3, padx=(8, 14))
        ttk.Label(self.date_options, text="Latest year").grid(row=0, column=4)
        self.max_entry = ttk.Entry(self.date_options, textvariable=self.max_year, width=7)
        self.max_entry.grid(row=0, column=5, padx=(8, 0))
        self.before_toggle = ttk.Checkbutton(
            self.date_options,
            text=f"Flag dates before {session.reference_date.isoformat()} (session reference)",
            variable=self.before_reference,
        )
        self.before_toggle.grid(row=1, column=0, columnspan=6, sticky="w", pady=(6, 0))
        ttk.Label(
            self.date_options,
            text="Year limits are optional. Text dates must match the selected format exactly.",
            style="Muted.TLabel",
        ).grid(row=2, column=0, columnspan=6, sticky="w")
        self.date_options.grid_remove()
        ttk.Label(page, textvariable=self.status, wraplength=850).grid(
            row=3, sticky="ew", pady=(10, 5)
        )
        ttk.Label(page, textvariable=self.applied, wraplength=850).grid(
            row=4, sticky="ew", pady=(0, 8)
        )
        results_frame = ttk.Frame(page)
        results_frame.grid(row=5, sticky="nsew")
        results_frame.columnconfigure(0, weight=1)
        results_frame.rowconfigure(0, weight=1)
        self.grid = ttk.Treeview(
            results_frame,
            columns=("cell", "value", "reason"),
            show="headings",
            selectmode="browse",
            height=6,
        )
        for name, title, width in (
            ("cell", "Source record" if self.is_xml else "Source cell", 95),
            ("value", "Original value", 230),
            ("reason", "Why review", 460),
        ):
            self.grid.heading(name, text=title, anchor="w")
            self.grid.column(name, width=width, minwidth=70, stretch=name != "cell")
        self.grid.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(results_frame, orient="vertical", command=self.grid.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.grid.configure(yscrollcommand=scroll.set)
        self.grid.bind("<<TreeviewSelect>>", self._selected)
        self.grid.bind("<Double-1>", lambda event: self.jump_selected())
        self.detail = tk.Text(
            page, height=4, wrap="word", state="disabled", relief="flat", padx=8, pady=6
        )
        self.detail.grid(row=6, sticky="ew", pady=(8, 6))
        actions = ttk.Frame(page)
        actions.grid(row=7, sticky="ew")
        self.previous = ttk.Button(
            actions,
            text="Previous",
            command=lambda: self.show_page(self.offset - FINDINGS_PAGE_SIZE),
            state="disabled",
        )
        self.previous.pack(side="left")
        self.next = ttk.Button(
            actions,
            text="Next",
            command=lambda: self.show_page(self.offset + FINDINGS_PAGE_SIZE),
            state="disabled",
        )
        self.next.pack(side="left", padx=5)
        ttk.Label(actions, textvariable=self.page_label).pack(side="left", padx=6)
        self.close_button = ttk.Button(actions, text="Close", command=self.close)
        self.close_button.pack(side="right")
        self.jump_button = ttk.Button(
            actions,
            text="Jump to record" if self.is_xml else "Jump to cell",
            command=self.jump_selected,
            state="disabled",
        )
        self.jump_button.pack(side="right", padx=8)
        self.hint = ttk.Label(
            page,
            text=(
                "Read-only XML checks. Every flagged record is available, 20 per page; source text stays unchanged."
                if self.is_xml
                else "Read-only. Every flagged row is available, 20 per page. Formulas are flagged without evaluation."
            ),
            wraplength=850,
            style="Muted.TLabel",
        )
        self.hint.grid(row=8, sticky="ew", pady=(8, 0))
        for variable in (
            self.expected,
            self.required,
            self.date_format,
            self.min_year,
            self.max_year,
            self.before_reference,
        ):
            variable.trace_add("write", self._settings_changed)

        def wrap(event: tk.Event[tk.Misc]) -> None:
            for child in page.winfo_children():
                if isinstance(child, ttk.Label):
                    child.configure(wraplength=max(250, event.width - 12))

        page.bind("<Configure>", wrap)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.poll_id = self.window.after(80, self._poll)

    def _settings_changed(self, *args: str) -> None:
        if self.busy or self.closed:
            return
        if self.expected.get() == "Date":
            self.date_options.grid()
        else:
            self.date_options.grid_remove()
        self._clear_report()
        self.status.set("Settings changed. Run check to review this entire column.")
        hints = {
            "Identifier": "Identifiers are expected as text. Numeric cells and surrounding whitespace are flagged; digits are never inferred.",
            "Text": "Non-text values and surrounding whitespace are flagged. Missing-value tokens such as N/A remain text.",
            "Number": "Checks stored numbers. Text numbers, currencies, percentages, and separators are not converted.",
            "Date": "Checks calendar dates using your settings. A past date is a review flag, not an automatic maturity decision.",
        }
        if self.is_xml:
            hints["Number"] = (
                "Checks plain decimal text: optional sign and decimal point. No grouping, currency, percent, or exponent. Text and precision stay unchanged."
            )
            hints["Identifier"] = (
                "XML identifiers stay text, including leading zeros. Surrounding whitespace is flagged; no digits are guessed."
            )
        self.hint.configure(
            text=hints.get(self.expected.get(), "Choose an expected type.")
            + " Original data stays unchanged."
        )

    def _clear_report(self) -> None:
        if self.report is not None:
            self.report.close()
            self.report = None
        self.entries.clear()
        self.grid.delete(*self.grid.get_children())
        self.applied.set("")
        self.page_label.set("")
        self.previous.configure(state="disabled")
        self.next.configure(state="disabled")
        self.jump_button.configure(state="disabled")
        self._detail("")

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        for widget in (
            self.required_toggle,
            self.min_entry,
            self.max_entry,
            self.before_toggle,
            self.run_button,
        ):
            widget.configure(state="disabled" if busy else "normal")
        for widget in (self.type_selector, self.date_selector):
            widget.configure(state="disabled" if busy else "readonly")
        self.close_button.configure(text="Cancel" if busy else "Close")

    def run(self) -> None:
        if self.busy or self.closed:
            return
        self._clear_report()
        try:
            is_date = self.expected.get() == "Date"
            rules = ColumnRules(
                self.expected.get(),
                self.required.get(),
                self.date_format.get() if is_date else "Excel dates only",
                int(self.min_year.get()) if is_date and self.min_year.get().strip() else None,
                int(self.max_year.get()) if is_date and self.max_year.get().strip() else None,
                self.before_reference.get() if is_date else False,
                number_format="Plain decimal text"
                if self.is_xml and self.expected.get() == "Number"
                else "Stored numbers only",
            )
        except (InspectionError, ValueError) as error:
            self.status.set(
                str(error)
                if isinstance(error, InspectionError)
                else "Enter a whole number for each year limit, or leave it empty."
            )
            return
        self._set_busy(True)
        self.status.set("Checking the complete saved column…")

        def read() -> None:
            try:
                result: ColumnCheck | Exception = check_column(
                    self.path,
                    self.table,
                    self.column,
                    self.session,
                    rules,
                    cancelled=self.cancelled,
                    progress=self.results.put,
                )
            except Exception as error:
                result = error
            # Coordinate delivery and close so a result completed during window
            # shutdown cannot leave its temporary findings behind.
            with self.delivery_lock:
                if self.cancelled.is_set():
                    if isinstance(result, ColumnCheck):
                        result.close()
                else:
                    self.results.put(result)

        self.worker = self.workers.start(read, "column-check", self.cancelled)

    def _poll(self) -> None:
        if self.closed:
            return
        while True:
            try:
                result = self.results.get_nowait()
            except queue.Empty:
                break
            if isinstance(result, str):
                self.status.set(result)
                continue
            self._set_busy(False)
            if isinstance(result, Exception):
                reason = (
                    str(result)
                    if isinstance(result, (InspectionError, OSError))
                    else "The source could not be read completely. Check its values and file format."
                )
                self.status.set("No complete column check. " + reason)
            else:
                self.report = result
                self.applied.set("Applied settings: " + result.rules.description)
                self.status.set(
                    f"Complete: checked all {result.profile.total_rows:,} data rows · Rows for review: {result.finding_count:,} · Allowed blank/empty rows: {result.allowed_blanks:,}"
                )
                self.show_page(0)
            break
        self.poll_id = self.window.after(80, self._poll)

    def show_page(self, offset: int) -> None:
        if self.report is None or self.busy:
            return
        if offset < 0 or (offset >= self.report.finding_count and offset != 0):
            return
        try:
            findings = self.report.page(offset)
        except Exception as error:
            self._clear_report()
            self.status.set(f"Results could not be read. Run the check again. {error}")
            return
        self.offset = offset
        self.grid.delete(*self.grid.get_children())
        self.entries.clear()
        self._detail("")
        self.jump_button.configure(state="disabled")
        for finding in findings:
            cell = finding.cell
            key = str(cell.row)
            self.entries[key] = finding
            self.grid.insert(
                "",
                "end",
                iid=key,
                values=(
                    ColumnWindow.location(cell, self.column),
                    ColumnWindow._display(cell)[:180],
                    finding.reason.replace("\n", " ")[:240],
                ),
            )
        total = self.report.finding_count
        self.page_label.set(
            f"{offset + 1:,}–{offset + len(findings):,} of {total:,}"
            if total
            else "No findings under these settings."
        )
        self.previous.configure(state="normal" if offset else "disabled")
        self.next.configure(state="normal" if offset + len(findings) < total else "disabled")

    def _selected(self, event: tk.Event[tk.Misc] | None = None) -> None:
        selected = self.grid.selection()
        finding = self.entries.get(selected[0]) if selected else None
        self.jump_button.configure(state="normal" if finding else "disabled")
        if finding:
            cell = finding.cell
            context = (
                f"State: {cell.presence}\nSource: {cell.source_path}"
                if cell.source_path is not None
                else f"Format: {cell.number_format}"
            )
            self._detail(
                f"{ColumnWindow.location(cell, self.column)} · {cell.kind}\n{context}\nOriginal: {ColumnWindow._display(cell)}\n{finding.reason}"
            )

    def _detail(self, text: str) -> None:
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", text)
        self.detail.configure(state="disabled")

    def jump_selected(self) -> None:
        selected = self.grid.selection()
        finding = self.entries.get(selected[0]) if selected else None
        if finding is None:
            return
        try:
            self.jump(finding.cell.row)
        except InspectionError as error:
            self.status.set(str(error))
            return
        self.close()

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        with self.delivery_lock:
            self.cancelled.set()
            while not self.results.empty():
                result = self.results.get_nowait()
                if isinstance(result, ColumnCheck):
                    result.close()
        if self.report is not None:
            self.report.close()
            self.report = None
        self.window.after_cancel(self.poll_id)
        self.window.grab_release()
        self.window.destroy()
