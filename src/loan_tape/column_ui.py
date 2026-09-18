"""A small, read-only summary of one complete table column."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import ttk

from loan_tape.column_profile import (
    EXAMPLES_PER_TYPE,
    REPEATED_LIMIT,
    ColumnExample,
    ColumnProfile,
    ColumnTable,
    column_scope,
    inspect_column,
)
from loan_tape.inspection import InspectionError
from loan_tape.ranges import column_label
from loan_tape.session import AnalysisSession
from loan_tape.workers import WorkerGroup
from loan_tape.xml_selection import SavedXmlTable


class ColumnWindow:
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
        self.workers = workers if workers is not None else WorkerGroup()
        self.window = tk.Toplevel(parent)
        self.window.title(f"Inspect column {column_label(column)} — {table.name}")
        self.window.geometry("860x650")
        self.window.minsize(720, 560)
        self.window.transient(parent.winfo_toplevel())
        self.window.grab_set()
        self.closed = False
        self.busy = True
        self.profile: ColumnProfile | None = None
        self.column = column
        self.is_xml = isinstance(table, SavedXmlTable)
        self.jump = jump
        self.cancelled = threading.Event()
        self.results: queue.Queue[ColumnProfile | str | Exception] = queue.Queue()
        self.status = tk.StringVar(
            master=self.window, value="Reading the complete data set column…"
        )
        self.summary = tk.StringVar(master=self.window)
        self.types = tk.StringVar(master=self.window)
        self.repeat_summary = tk.StringVar(master=self.window)
        self.entries: dict[str, ColumnExample] = {}
        page = ttk.Frame(self.window, padding=16)
        page.pack(fill="both", expand=True)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(6, weight=1)
        self.heading = ttk.Label(
            page, text=f"Column {column_label(column)}", font=("Segoe UI", 16, "bold")
        )
        self.heading.grid(row=0, sticky="w")
        self.scope_label = ttk.Label(
            page,
            text=column_scope(table, session),
            wraplength=800,
        )
        self.scope_label.grid(row=1, sticky="ew", pady=(5, 8))
        ttk.Label(page, textvariable=self.status, wraplength=800).grid(
            row=2, sticky="ew", pady=(0, 8)
        )
        ttk.Label(page, textvariable=self.summary, wraplength=800).grid(row=3, sticky="ew")
        ttk.Label(page, textvariable=self.types, wraplength=800).grid(
            row=4, sticky="ew", pady=(4, 4)
        )
        ttk.Label(page, textvariable=self.repeat_summary, wraplength=800).grid(
            row=5, sticky="ew", pady=(0, 8)
        )
        self.tabs = ttk.Notebook(page)
        self.tabs.grid(row=6, sticky="nsew")
        self.examples = self._grid("Examples", False)
        self.repeated = self._grid("Repeated values", True)
        self.tabs.bind("<<NotebookTabChanged>>", self._selected)
        self.detail = tk.Text(
            page, height=3, wrap="word", state="disabled", relief="flat", padx=8, pady=6
        )
        self.detail.grid(row=7, sticky="ew", pady=(8, 6))
        actions = ttk.Frame(page)
        actions.grid(row=8, sticky="ew")
        self.jump_button = ttk.Button(
            actions,
            text="Jump to record" if self.is_xml else "Jump to cell",
            command=self.jump_selected,
            state="disabled",
        )
        self.jump_button.pack(side="left")
        self.close_button = ttk.Button(actions, text="Cancel", command=self.close)
        self.close_button.pack(side="right")
        ttk.Label(
            page,
            text=(
                "Decoded XML text and presence states; values stay unchanged. No schema or financial interpretation."
                if self.is_xml
                else "Stored cell types; text is not converted. Formulas are counted separately and never calculated."
            ),
            style="Muted.TLabel",
            wraplength=800,
        ).grid(row=9, sticky="ew", pady=(8, 0))

        def wrap(event: tk.Event[tk.Misc]) -> None:
            for child in page.winfo_children():
                if isinstance(child, ttk.Label):
                    child.configure(wraplength=max(250, event.width - 12))

        page.bind("<Configure>", wrap)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.poll_id = self.window.after(80, self._poll)

        def read() -> None:
            try:
                self.results.put(
                    inspect_column(
                        path,
                        table,
                        column,
                        session,
                        cancelled=self.cancelled,
                        progress=self.results.put,
                    )
                )
            except Exception as error:
                self.results.put(error)

        # Normal app shutdown must let the cancelled reader remove its temporary data.
        # Closing the window never joins this worker on the Tk thread.
        self.worker = self.workers.start(read, "column-inspection", self.cancelled)

    def _grid(self, title: str, repeated: bool) -> ttk.Treeview:
        frame = ttk.Frame(self.tabs)
        frame.rowconfigure(1, weight=1)
        frame.columnconfigure(0, weight=1)
        self.tabs.add(frame, text=title)
        text = (
            f"Up to {REPEATED_LIMIT} most repeated values. Count covers all data rows; cell is the first occurrence."
            if repeated
            else f"Up to {EXAMPLES_PER_TYPE} examples of each stored type. Summary counts cover every data row."
        )
        ttk.Label(frame, text=text, style="Muted.TLabel", wraplength=650).grid(
            row=0, sticky="w", pady=(5, 5)
        )
        grid = ttk.Treeview(
            frame,
            columns=("value", "kind", "count", "cell"),
            show="headings",
            selectmode="browse",
            height=5,
        )
        for column, heading, width in [
            ("value", "Value", 340),
            ("kind", "Type", 95),
            ("count", "Count" if repeated else "", 65),
            ("cell", "Source record" if self.is_xml else "Source cell", 105),
        ]:
            grid.heading(column, text=heading, anchor="w")
            grid.column(column, width=width, minwidth=50, stretch=column == "value")
        grid.grid(row=1, sticky="nsew")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=grid.yview)
        scroll.grid(row=1, column=1, sticky="ns")
        grid.configure(yscrollcommand=scroll.set)
        grid.bind("<<TreeviewSelect>>", self._selected)
        grid.bind("<Double-1>", lambda event: self.jump_selected())
        return grid

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
            self.close_button.configure(text="Close")
            if isinstance(result, Exception):
                message = (
                    str(result)
                    if isinstance(result, (InspectionError, OSError))
                    else "The source could not be read completely. Check its values and file format."
                )
                self.status.set("No complete column summary. " + message)
            else:
                self._show(result)
            break
        self.poll_id = self.window.after(80, self._poll)

    def _show(self, profile: ColumnProfile) -> None:
        self.profile = profile
        counts = dict(profile.counts)
        header = "No header set" if profile.header is None else (profile.header or "[blank header]")
        header_label = header.replace("\r", "\\r").replace("\n", "\\n").replace("\t", "\\t")
        self.heading.configure(text=f"{column_label(self.column)} · {header_label[:70]}")
        source = (
            profile.table.group_label
            if isinstance(profile.table, SavedXmlTable)
            else profile.table.selection.sheet
        )
        self.status.set(
            f"Complete: inspected all {profile.total_rows:,} {'records' if self.is_xml else 'data rows'} · {source} · {profile.data_address}"
        )
        if self.is_xml:
            self.summary.set(
                f"Filled: {profile.filled_cells:,} · Absent: {counts['Absent']:,} · Empty element: {counts['Empty element']:,} · Explicit nil: {counts['Explicit nil']:,}"
                f"\nEmpty text: {counts['Empty text']:,} · Literal text '0': {profile.text_zeroes:,} · Whitespace-only text: {profile.whitespace_text:,}"
            )
        else:
            self.summary.set(
                f"Filled: {profile.filled_cells:,} · Blank: {counts['Blank']:,} · Empty text: {counts['Empty text']:,}"
                f"\nNumeric zeroes: {profile.numeric_zeroes:,} · Whitespace-only text: {profile.whitespace_text:,}"
            )
        self.types.set(
            " · ".join(
                f"{kind}: {count:,}"
                for kind, count in profile.counts
                if count and kind not in {"Blank", "Empty text"}
            )
            or "No filled values."
        )
        self.repeat_summary.set(
            f"Distinct filled values: {profile.distinct_values:,} · Values repeated: {profile.repeated_values:,} · Extra occurrences: {profile.extra_occurrences:,}"
        )
        for prefix, grid, examples in [
            ("example", self.examples, profile.examples),
            ("repeat", self.repeated, profile.repeated),
        ]:
            for index, example in enumerate(examples):
                identity = f"{prefix}-{index}"
                text = self._display(example)
                grid.insert(
                    "",
                    "end",
                    iid=identity,
                    values=(
                        text[:180],
                        example.kind,
                        f"{example.count:,}" if prefix == "repeat" else "",
                        self.location(example, self.column),
                    ),
                )
                self.entries[identity] = example

    @staticmethod
    def location(example: ColumnExample, column: int) -> str:
        return (
            f"Record {example.row}"
            if example.source_path is not None
            else f"{column_label(column)}{example.row}"
        )

    @staticmethod
    def _display(example: ColumnExample) -> str:
        if example.kind in {"Absent", "Empty element", "Explicit nil"}:
            return f"[{example.kind.lower()}]"
        if example.kind == "Blank":
            return "[blank]"
        if example.kind == "Empty text":
            return "[empty text]"
        return repr(example.text) if example.kind == "Text" else example.text

    def _current_example(self) -> ColumnExample | None:
        active_tab = self.tabs.select()  # type: ignore[no-untyped-call]
        grid = self.examples if active_tab == str(self.examples.master) else self.repeated
        selected = grid.selection()
        return self.entries.get(selected[0]) if selected else None

    def _selected(self, event: tk.Event[tk.Misc] | None = None) -> None:
        if not hasattr(self, "jump_button"):
            return
        example = self._current_example()
        self.jump_button.configure(state="normal" if example else "disabled")
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        if example:
            if example.source_path is not None:
                text = (
                    f"{self.location(example, self.column)} · {example.kind} · State: {example.presence}\n"
                    f"Source: {example.source_path}\n{self._display(example)}"
                )
            else:
                text = f"{self.location(example, self.column)} · {example.kind}\n{self._display(example)}"
            if example.number_format != "General":
                text += f"\nExcel number format: {example.number_format}"
            self.detail.insert("1.0", text)
        self.detail.configure(state="disabled")

    def jump_selected(self) -> None:
        example = self._current_example()
        if example is None:
            return
        try:
            self.jump(example.row)
        except InspectionError as error:
            self.status.set(str(error))
            return
        self.close()

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.cancelled.set()
        self.window.after_cancel(self.poll_id)
        self.window.grab_release()
        self.window.destroy()
