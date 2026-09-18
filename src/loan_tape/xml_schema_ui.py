"""Native, read-only XSD validation results for one XML preview."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from loan_tape.inspection import InspectionError
from loan_tape.workers import WorkerGroup
from loan_tape.xml_schema import (
    FINDINGS_PAGE_SIZE,
    XsdFinding,
    XsdValidation,
    validate_xml_schema,
)


class XsdValidationWindow:
    def __init__(
        self,
        parent: tk.Misc,
        xml_path: Path,
        xsd_path: Path,
        source_sha256: str,
        workers: WorkerGroup,
    ) -> None:
        self.xml_path, self.xsd_path = xml_path, xsd_path
        self.workers = workers
        self.window = tk.Toplevel(parent)
        self.window.title(f"Validate XSD — {xml_path.name}")
        self.window.geometry("900x700")
        self.window.minsize(760, 620)
        self.window.transient(parent.winfo_toplevel())
        self.window.grab_set()
        self.closed = False
        self.busy = True
        self.report: XsdValidation | None = None
        self.offset = 0
        self.cancelled = threading.Event()
        self.delivery_lock = threading.Lock()
        self.results: queue.Queue[XsdValidation | str | Exception] = queue.Queue()
        self.entries: dict[str, XsdFinding] = {}
        self.status = tk.StringVar(master=self.window, value="Preparing XSD validation…")
        self.summary = tk.StringVar(master=self.window)
        self.page_label = tk.StringVar(master=self.window)

        page = ttk.Frame(self.window, padding=16)
        page.pack(fill="both", expand=True)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(5, weight=1)
        ttk.Label(page, text="Validate XML with XSD", font=("Segoe UI", 16, "bold")).grid(
            row=0, sticky="w"
        )
        self.scope = ttk.Label(
            page,
            text=f"XML: {xml_path.name}\nSelected schema: {xsd_path}",
            wraplength=850,
        )
        self.scope.grid(row=1, sticky="ew", pady=(5, 8))
        ttk.Label(page, textvariable=self.status, wraplength=850).grid(
            row=2, sticky="ew", pady=(0, 5)
        )
        ttk.Label(page, textvariable=self.summary, wraplength=850).grid(
            row=3, sticky="ew", pady=(0, 8)
        )
        self.progress = ttk.Progressbar(page, mode="indeterminate", length=180)
        self.progress.grid(row=4, sticky="w", pady=(0, 8))
        self.progress.start(15)

        results = ttk.Frame(page)
        results.grid(row=5, sticky="nsew")
        results.columnconfigure(0, weight=1)
        results.rowconfigure(0, weight=1)
        self.grid = ttk.Treeview(
            results,
            columns=("path", "line", "category", "reason"),
            show="headings",
            selectmode="browse",
            height=7,
        )
        for name, title, width, stretch in (
            ("path", "XML path", 260, True),
            ("line", "Line", 60, False),
            ("category", "Finding", 125, False),
            ("reason", "Why it does not match", 390, True),
        ):
            self.grid.heading(name, text=title, anchor="w")
            self.grid.column(name, width=width, minwidth=50, stretch=stretch)
        self.grid.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(results, orient="vertical", command=self.grid.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.grid.configure(yscrollcommand=scroll.set)
        self.grid.bind("<<TreeviewSelect>>", self._selected)

        self.detail = tk.Text(
            page, height=5, wrap="word", state="disabled", relief="flat", padx=8, pady=6
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
        self.close_button = ttk.Button(actions, text="Cancel", command=self.close)
        self.close_button.pack(side="right")
        ttk.Label(
            page,
            text=(
                "Read-only full-document validation. Only the selected XSD and local files "
                "inside its folder can be loaded; schema hints and network locations are ignored."
            ),
            style="Muted.TLabel",
            wraplength=850,
        ).grid(row=8, sticky="ew", pady=(8, 0))

        def wrap(event: tk.Event[tk.Misc]) -> None:
            for child in page.winfo_children():
                if isinstance(child, ttk.Label):
                    child.configure(wraplength=max(250, event.width - 12))

        page.bind("<Configure>", wrap)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.poll_id = self.window.after(80, self._poll)

        def read() -> None:
            try:
                result: XsdValidation | Exception = validate_xml_schema(
                    xml_path,
                    xsd_path,
                    source_sha256,
                    cancelled=self.cancelled,
                    progress=self.results.put,
                )
            except Exception as error:
                result = error
            with self.delivery_lock:
                if self.cancelled.is_set():
                    if isinstance(result, XsdValidation):
                        result.close()
                else:
                    self.results.put(result)

        self.worker = self.workers.start(read, "xsd-validation", self.cancelled)

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
            self.busy = False
            self.progress.stop()
            self.progress.grid_remove()
            self.close_button.configure(text="Close")
            if isinstance(result, Exception):
                message = (
                    str(result)
                    if isinstance(result, (InspectionError, OSError))
                    else "The XML or selected XSD could not be validated completely."
                )
                self.status.set("No complete XSD result. " + message)
            else:
                self.report = result
                count = result.finding_count
                self.status.set(
                    "Valid: the complete XML document matches the selected XSD."
                    if count == 0
                    else f"Does not match: {count:,} schema finding{'s' if count != 1 else ''}."
                )
                self.summary.set(
                    f"{result.schema_version} · {len(result.resources):,} local schema "
                    f"file{'s' if len(result.resources) != 1 else ''} · "
                    f"XML {result.source_sha256[:12]}… · XSD {result.schema.sha256[:12]}…"
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
            self.report.close()
            self.report = None
            self.status.set(f"Results could not be read. Run validation again. {error}")
            return
        self.offset = offset
        self.grid.delete(*self.grid.get_children())
        self.entries.clear()
        self._detail("")
        for finding in findings:
            key = str(finding.number)
            self.entries[key] = finding
            self.grid.insert(
                "",
                "end",
                iid=key,
                values=(
                    finding.source_path[:240],
                    finding.line or "—",
                    finding.category,
                    finding.reason.replace("\n", " ")[:300],
                ),
            )
        total = self.report.finding_count
        self.page_label.set(
            f"{offset + 1:,}–{offset + len(findings):,} of {total:,}"
            if total
            else "No schema findings."
        )
        self.previous.configure(state="normal" if offset else "disabled")
        self.next.configure(state="normal" if offset + len(findings) < total else "disabled")

    def _selected(self, event: tk.Event[tk.Misc] | None = None) -> None:
        selected = self.grid.selection()
        finding = self.entries.get(selected[0]) if selected else None
        if finding is None:
            self._detail("")
            return
        location = finding.source_path
        if finding.line is not None:
            location += f" · line {finding.line:,}"
        self._detail(f"{location}\n{finding.category}\n{finding.reason}")

    def _detail(self, text: str) -> None:
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", text)
        self.detail.configure(state="disabled")

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        with self.delivery_lock:
            self.cancelled.set()
            while not self.results.empty():
                result = self.results.get_nowait()
                if isinstance(result, XsdValidation):
                    result.close()
        if self.report is not None:
            self.report.close()
            self.report = None
        self.progress.stop()
        self.window.after_cancel(self.poll_id)
        self.window.grab_release()
        self.window.destroy()
