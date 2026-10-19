"""Explicit export of the current approved revision, with optional date composition."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk
from typing import TYPE_CHECKING
from weakref import proxy

from loan_tape.date_runs import SavedDateRun, load_date_run
from loan_tape.excel_process import open_in_excel
from loan_tape.recipe_execution import recipe_scope
from loan_tape.text_export import TextExport, export_text_revision

if TYPE_CHECKING:
    from loan_tape.text_cleanup_ui import TextCleanupWindow


class TextExportWindow:
    def __init__(self, owner: TextCleanupWindow) -> None:
        self.owner = proxy(owner)
        assert owner.parent is not None
        self.revision = owner.parent
        self.scope, self.catalog = recipe_scope(owner.table), owner.store.catalog()
        self.window = tk.Toplevel(owner.window)
        self.window.title("Export reviewed loan tape")
        self.window.geometry("820x450")
        self.window.minsize(760, 430)
        self.window.transient(owner.window)
        self.closed = self.busy = self.invalid = False
        self.cancelled = threading.Event()
        self.results: queue.Queue[SavedDateRun | TextExport | Exception] = queue.Queue()
        self.date_run: SavedDateRun | None = None
        self.output: TextExport | None = None
        self.include_dates = tk.BooleanVar(self.window, False)
        self.date_label = tk.StringVar(
            self.window, "No date run selected. Export contains approved text changes only."
        )
        self.status = tk.StringVar(
            self.window, "Choose a new output file after reviewing the export contents."
        )
        page = ttk.Frame(self.window, padding=18)
        page.pack(fill="both", expand=True)
        ttk.Label(page, text="Export reviewed loan tape", font=("Segoe UI", 16, "bold")).pack(
            anchor="w"
        )
        ttk.Label(
            page,
            text=f"{owner.table.name} | {self.revision.id[:16]} | {len(self.revision.to_dict()['steps'])} reviewed steps",
            wraplength=720,
        ).pack(anchor="w", pady=8)
        ttk.Label(
            page,
            text="Creates a separate workbook containing the full selected data set, approved text changes, original cell evidence, decisions and audit history. Originals remain unchanged.",
            wraplength=720,
        ).pack(anchor="w", pady=4)
        ttk.Label(
            page,
            text="Source tokens, numeric tokens and standardized ISO dates are written as literal text to preserve exact values. This is a new values-only workbook; source styles, formulas, hidden rows, links and macros are not copied. Formulas are retained as literal expressions and in the audit.",
            wraplength=720,
        ).pack(anchor="w", pady=4)
        self.choose_button = ttk.Button(
            page, text="Choose saved date run...", command=self.choose_date
        )
        self.choose_button.pack(anchor="w", pady=(12, 4))
        ttk.Label(page, textvariable=self.date_label, wraplength=720).pack(anchor="w")
        self.date_check = ttk.Checkbutton(
            page,
            text="Include this date run after source, mapping and evidence checks",
            variable=self.include_dates,
        )
        self.date_check.pack(anchor="w", pady=6)
        actions = ttk.Frame(page)
        actions.pack(fill="x", pady=8)
        self.export_button = ttk.Button(actions, text="Export workbook...", command=self.export)
        self.export_button.pack(side="left")
        self.open_button = ttk.Button(
            actions, text="Open output in Excel", command=self.open_output
        )
        self.open_button.pack(side="left", padx=8)
        self.cancel_button = ttk.Button(actions, text="Cancel", command=self.cancel)
        self.cancel_button.pack(side="left")
        ttk.Button(actions, text="Close", command=self.close).pack(side="right")
        ttk.Label(
            page,
            text="Requires Windows and desktop Excel. Explicit exports remain after Exit.",
            wraplength=720,
        ).pack(anchor="w")
        self.status_label = ttk.Label(page, textvariable=self.status, wraplength=720)
        self.status_label.pack(anchor="w", pady=5)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self._buttons()
        self.poll_id = self.window.after(100, self._poll)

    def _buttons(self) -> None:
        idle = not self.busy and not self.invalid
        self.choose_button.configure(state="normal" if idle else "disabled")
        self.date_check.configure(
            state="normal" if idle and self.date_run is not None else "disabled"
        )
        self.export_button.configure(state="normal" if idle else "disabled")
        self.open_button.configure(state="normal" if not self.busy and self.output else "disabled")
        self.cancel_button.configure(state="normal" if self.busy else "disabled")

    def choose_date(self) -> None:
        if self.busy or self.invalid:
            return
        selected = filedialog.askopenfilename(
            parent=self.window,
            title="Choose a reviewed date run",
            initialdir=str(Path.cwd() / ".artifacts/date-runs"),
            filetypes=(("Saved date run", "*.json"),),
        )
        if not selected:
            return
        self.date_run = None
        self.include_dates.set(False)
        self.busy = True
        self.cancelled = threading.Event()
        event, results, path = self.cancelled, self.results, Path(selected)
        self.status.set("Loading and verifying the selected date run...")
        self._buttons()

        def load() -> None:
            try:
                results.put(load_date_run(path, cancelled=event))
            except Exception as error:
                results.put(error)

        self.owner.workers.start(load, "text-export-date-load", event)

    def export(self) -> None:
        if self.busy or self.invalid:
            return
        if not self._current():
            return
        selected = filedialog.asksaveasfilename(
            parent=self.window,
            title="Save reviewed loan tape",
            initialfile=f"{self.owner.table.name} - reviewed text.xlsx",
            defaultextension=".xlsx",
            filetypes=(("Excel workbook", "*.xlsx"),),
        )
        if not selected:
            return
        self.busy = True
        self.output = None
        self.cancelled = threading.Event()
        source, table, store = self.owner.source, self.owner.table, self.owner.store
        revision, date_run = self.revision, self.date_run if self.include_dates.get() else None
        target, event, results = Path(selected), self.cancelled, self.results
        self.status.set(
            "Creating and validating the complete workbook with owned Excel processes..."
        )
        self._buttons()

        def write() -> None:
            try:
                results.put(
                    export_text_revision(
                        source, table, store, revision, target, date_run=date_run, cancelled=event
                    )
                )
            except Exception as error:
                results.put(error)

        self.owner.workers.start(write, "text-export", event)

    def _current(self) -> bool:
        try:
            if (
                self.owner.current_table() != self.owner.table
                or self.owner.parent != self.revision
                or recipe_scope(self.owner.table) != self.scope
                or self.owner.store.catalog() != self.catalog
            ):
                raise ValueError(
                    "Data set, approved result, mappings or dictionary changed. Reopen export after review."
                )
        except (ValueError, OSError) as error:
            self.invalid = True
            self.cancelled.set()
            self.status.set(str(error))
            self._buttons()
        return not self.invalid

    def open_output(self) -> None:
        if self.output is not None and not self.busy:
            try:
                open_in_excel(self.output.path)
            except (ValueError, OSError) as error:
                self.status.set(str(error))

    def cancel(self) -> None:
        self.cancelled.set()
        self.status.set("Cancellation requested. Waiting for owned Excel processes to stop...")

    def _poll(self) -> None:
        if self.closed:
            return
        self._current()
        try:
            result = self.results.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            if isinstance(result, TextExport):
                self.output = result
                self.status.set(
                    f"Validated export saved: {result.path.name} | writer {result.writer} {result.writer_version}"
                )
            elif isinstance(result, Exception):
                self.status.set(f"Export work stopped: {result}")
            elif not self.invalid and not self.cancelled.is_set():
                self.date_run = result
                dataset = result.analysis.to_dict()["inputs"]["dataset"]
                self.date_label.set(
                    f"Date run {result.id}: {dataset['name']} | {dataset['sheet']}!{dataset['range']}. Select Include to compose it."
                )
                self.status.set(
                    "Date run loaded. Inclusion remains unchecked; final export verifies compatibility."
                )
            self._buttons()
        self.poll_id = self.window.after(100, self._poll)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.cancelled.set()
        self.window.after_cancel(self.poll_id)
        self.window.destroy()
        if not self.owner.closed:
            self.owner._buttons()
