"""Top-level, read-only ordering view for a complete saved data set."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from tkinter import ttk

from loan_tape.column_order import (
    ORDER_COLUMN_PAGE_SIZE,
    ORDER_MODES,
    ORDER_PAGE_SIZE,
    OrderedDataSet,
    OrderedPage,
    OrderedRow,
    order_data_set,
)
from loan_tape.column_profile import ColumnExample, ColumnTable
from loan_tape.inspection import InspectionError, PreviewCell
from loan_tape.ranges import column_label
from loan_tape.session import AnalysisSession
from loan_tape.theme_ui import ACCENT, BORDER, CHROME, FOREGROUND, MUTED, SURFACE
from loan_tape.workers import WorkerGroup
from loan_tape.xml_selection import SavedXmlTable


@dataclass(frozen=True)
class OrderScope:
    table: ColumnTable
    column: int
    label: str


class OrderPanel:
    """Order complete source rows by one selected column without changing the source."""

    def __init__(
        self,
        parent: ttk.Notebook,
        path: Path,
        session: AnalysisSession,
        scope_provider: Callable[[], OrderScope],
        jump: Callable[[ColumnTable, int, int], None],
        activate_analysis: Callable[[], None],
        workers: WorkerGroup,
    ) -> None:
        self.frame = ttk.Frame(parent)
        self.path = path
        self.session = session
        self.scope_provider = scope_provider
        self.jump = jump
        self.activate_analysis = activate_analysis
        self.workers = workers
        self.closed = False
        self.busy = False
        self.scope: OrderScope | None = None
        self.result: OrderedDataSet | None = None
        self.page: OrderedPage | None = None
        self.offset = 0
        self.column_offset = 0
        self.entries: dict[str, OrderedRow] = {}
        self.token = 0
        self.cancelled = threading.Event()
        self.delivery_lock = threading.Lock()
        self.results: queue.Queue[tuple[int, OrderedDataSet | str | Exception]] = queue.Queue()
        self.mode = tk.StringVar(master=self.frame, value=ORDER_MODES[0])
        self.status = tk.StringVar(
            master=self.frame,
            value="On the analysis tab, select a column in a saved data set, then return here.",
        )
        self.scope_text = tk.StringVar(master=self.frame, value=path.name)
        self.page_text = tk.StringVar(master=self.frame)
        self._build()
        self.poll_id = self.frame.after(80, self._poll)

    def _build(self) -> None:
        style = ttk.Style(self.frame)
        style.configure(
            "Order.Treeview",
            background=SURFACE,
            fieldbackground=SURFACE,
            foreground=FOREGROUND,
            bordercolor=BORDER,
            rowheight=24,
        )
        style.configure(
            "Order.Treeview.Heading",
            background=CHROME,
            foreground=FOREGROUND,
            relief="flat",
            padding=(6, 5),
        )
        style.map("Order.Treeview.Heading", background=[("active", "#e7eee4")])

        page = ttk.Frame(self.frame, padding=(20, 14, 20, 12))
        page.pack(fill="both", expand=True)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(4, weight=1)
        ttk.Label(page, text="Order data", font=("Segoe UI", 15)).grid(row=0, sticky="w")
        ttk.Label(
            page,
            textvariable=self.scope_text,
            wraplength=900,
            style="Muted.TLabel",
        ).grid(row=1, sticky="ew", pady=(3, 10))

        controls = ttk.Frame(page)
        controls.grid(row=2, sticky="ew", pady=(0, 8))
        controls.columnconfigure(4, weight=1)
        ttk.Label(controls, text="Order", style="Muted.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 6)
        )
        self.mode_selector = ttk.Combobox(
            controls,
            textvariable=self.mode,
            values=ORDER_MODES,
            state="readonly",
            width=14,
        )
        self.mode_selector.grid(row=0, column=1, sticky="w")
        self.mode_selector.bind("<<ComboboxSelected>>", self._mode_changed)
        self.use_button = ttk.Button(
            controls, text="Refresh from analysis", command=lambda: self.activate(force=True)
        )
        self.use_button.grid(row=0, column=2, padx=(10, 0))
        ttk.Button(controls, text="Back to analysis", command=self.activate_analysis).grid(
            row=0, column=5, sticky="e"
        )

        self.status_label = ttk.Label(
            page, textvariable=self.status, wraplength=900, foreground=MUTED
        )
        self.status_label.grid(row=3, sticky="ew", pady=(0, 8))

        grid_frame = ttk.Frame(page)
        grid_frame.grid(row=4, sticky="nsew")
        grid_frame.columnconfigure(0, weight=1)
        grid_frame.rowconfigure(0, weight=1)
        self.grid = ttk.Treeview(
            grid_frame,
            columns=(),
            show="tree headings",
            selectmode="browse",
            style="Order.Treeview",
        )
        self.grid.heading("#0", text="Source row", anchor="w")
        self.grid.column("#0", width=105, minwidth=90, stretch=False)
        self.grid.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(grid_frame, orient="vertical", command=self.grid.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(grid_frame, orient="horizontal", command=self.grid.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self.grid.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.grid.bind("<<TreeviewSelect>>", self._selected)
        self.grid.bind("<Double-1>", lambda event: self.jump_selected())

        self.detail = tk.Text(
            page, height=4, wrap="word", state="disabled", relief="flat", padx=8, pady=6
        )
        self.detail.grid(row=5, sticky="ew", pady=(8, 6))

        actions = ttk.Frame(page)
        actions.grid(row=6, sticky="ew")
        self.previous = ttk.Button(
            actions,
            text="Previous rows",
            command=lambda: self.show_page(self.offset - ORDER_PAGE_SIZE),
            state="disabled",
        )
        self.previous.pack(side="left")
        self.next = ttk.Button(
            actions,
            text="Next rows",
            command=lambda: self.show_page(self.offset + ORDER_PAGE_SIZE),
            state="disabled",
        )
        self.next.pack(side="left", padx=5)
        self.previous_columns = ttk.Button(
            actions,
            text="Previous columns",
            command=lambda: self.show_columns(self.column_offset - ORDER_COLUMN_PAGE_SIZE),
            state="disabled",
        )
        self.previous_columns.pack(side="left", padx=(12, 0))
        self.next_columns = ttk.Button(
            actions,
            text="Next columns",
            command=lambda: self.show_columns(self.column_offset + ORDER_COLUMN_PAGE_SIZE),
            state="disabled",
        )
        self.next_columns.pack(side="left", padx=5)
        ttk.Label(actions, textvariable=self.page_text, style="Muted.TLabel").pack(
            side="left", padx=6
        )
        self.jump_button = ttk.Button(
            actions, text="Jump to source", command=self.jump_selected, state="disabled"
        )
        self.jump_button.pack(side="right")
        ttk.Label(
            page,
            text=(
                "Every row and column comes from the same saved data set shown in Analysis. "
                "The selected column is only the order key (↕). A–Z and Z–A use source text; "
                "Ascending and Descending put stored numbers first. Missing values stay last, "
                "and the source is never rearranged."
            ),
            style="Muted.TLabel",
            wraplength=900,
        ).grid(row=7, sticky="ew", pady=(8, 0))

        page.bind(
            "<Configure>",
            lambda event: (self.status_label.configure(wraplength=max(240, event.width - 20)),),
        )

    def activate(self, *, force: bool = False) -> None:
        if self.closed:
            return
        try:
            scope = self.scope_provider()
        except InspectionError as error:
            self.cancelled.set()
            self.token += 1
            self.busy = False
            if self.result is not None:
                self.result.close()
                self.result = None
            self.scope = None
            self.page = None
            self._clear_grid()
            self.page_text.set("")
            self._detail("")
            self.status.set(str(error))
            self.status_label.configure(foreground=MUTED)
            self.mode_selector.configure(state="readonly")
            self.use_button.configure(state="normal")
            self._set_navigation(0, 0)
            return
        if not force and scope == self.scope and (self.busy or self.result is not None):
            return
        self._start(scope)

    def _start(self, scope: OrderScope) -> None:
        self.cancelled.set()
        self.cancelled = threading.Event()
        self.token += 1
        token = self.token
        if self.result is not None:
            self.result.close()
            self.result = None
        self.scope = scope
        self.page = None
        self.busy = True
        self.offset = 0
        self.column_offset = 0
        self._clear_grid()
        self.page_text.set("")
        self._detail("")
        self._set_navigation(0, 0)
        self.mode_selector.configure(state="disabled")
        self.use_button.configure(state="disabled")
        self.scope_text.set(f"{self.path.name} · {scope.table.name} · Ordered by {scope.label}")
        self.status.set("Reading and indexing the complete saved data set…")
        self.status_label.configure(foreground=ACCENT)
        cancelled = self.cancelled

        def deliver(value: OrderedDataSet | str | Exception) -> None:
            with self.delivery_lock:
                if self.closed or token != self.token:
                    if isinstance(value, OrderedDataSet):
                        value.close()
                    return
                self.results.put((token, value))

        def read() -> None:
            try:
                value: OrderedDataSet | Exception = order_data_set(
                    self.path,
                    scope.table,
                    scope.column,
                    self.session,
                    cancelled=cancelled,
                    progress=deliver,
                )
            except Exception as error:
                value = error
            deliver(value)

        self.workers.start(read, "data-set-order", cancelled)

    def _poll(self) -> None:
        if self.closed:
            return
        while True:
            try:
                token, value = self.results.get_nowait()
            except queue.Empty:
                break
            if token != self.token:
                if isinstance(value, OrderedDataSet):
                    value.close()
                continue
            if isinstance(value, str):
                self.status.set(value)
                continue
            self.busy = False
            self.mode_selector.configure(state="readonly")
            self.use_button.configure(state="normal")
            if isinstance(value, Exception):
                message = (
                    str(value)
                    if isinstance(value, (InspectionError, OSError))
                    else "The complete saved data set could not be ordered."
                )
                self.status.set("No complete ordered view. " + message)
                self.status_label.configure(foreground=MUTED)
            else:
                self.result = value
                relative = value.sort_column - value.first_column
                self.column_offset = (relative // ORDER_COLUMN_PAGE_SIZE) * ORDER_COLUMN_PAGE_SIZE
                self.grid.heading(
                    "#0",
                    text="Source record"
                    if isinstance(value.table, SavedXmlTable)
                    else "Source row",
                )
                self.status.set(
                    f"Complete: {value.total_rows:,} rows × {value.total_columns:,} columns · "
                    f"{value.filled_rows:,} filled order values · "
                    f"{value.numeric_rows:,} stored numbers."
                )
                self.status_label.configure(foreground=ACCENT)
                self.show_page(0)
            break
        self.poll_id = self.frame.after(80, self._poll)

    def _mode_changed(self, event: tk.Event[tk.Misc] | None = None) -> None:
        if self.result is not None and not self.busy:
            self.show_page(0)

    def show_columns(self, column_offset: int) -> None:
        if self.result is None or column_offset < 0 or column_offset >= self.result.total_columns:
            return
        self.column_offset = column_offset
        self.show_page(self.offset)

    def show_page(self, offset: int) -> None:
        if self.result is None or self.busy or offset < 0:
            return
        total = self.result.total_rows
        if offset >= total and offset != 0:
            return
        try:
            page = self.result.page(
                self.mode.get(),
                offset,
                ORDER_PAGE_SIZE,
                column_offset=self.column_offset,
                column_limit=ORDER_COLUMN_PAGE_SIZE,
            )
        except InspectionError as error:
            self.status.set(str(error))
            return
        self.offset = offset
        self.page = page
        self.entries.clear()
        self.grid.delete(*self.grid.get_children())
        self._configure_columns(page)
        self._detail("")
        self.jump_button.configure(state="disabled")
        for row in page.rows:
            key = str(row.source_row)
            self.entries[key] = row
            self.grid.insert(
                "",
                "end",
                iid=key,
                text=(
                    f"Record {row.source_row:,}"
                    if isinstance(self.result.table, SavedXmlTable)
                    else f"Row {row.source_row:,}"
                ),
                values=tuple(self._grid_value(cell) for cell in row.cells),
            )
        row_text = (
            f"Rows {offset + 1:,}–{offset + len(page.rows):,} of {total:,}"
            if total
            else "No data rows"
        )
        column_end = page.start_column + len(page.column_labels) - 1
        self.page_text.set(
            f"{row_text} · columns {column_label(page.start_column)}–{column_label(column_end)}"
        )
        self._set_navigation(len(page.rows), len(page.column_labels))

    def _configure_columns(self, page: OrderedPage) -> None:
        assert self.result is not None
        columns = tuple(
            column_label(column)
            for column in range(page.start_column, page.start_column + len(page.column_labels))
        )
        self.grid.configure(columns=columns)
        for offset, identifier in enumerate(columns):
            source_column = page.start_column + offset
            label = identifier
            if self.result.has_headers:
                value = page.column_labels[offset]
                value = value.replace("\r", "\\r").replace("\n", "\\n").replace("\t", "\\t")
                label += " · " + (
                    (value[:80] + "…" if len(value) > 80 else value) or "[blank header]"
                )
            if source_column == self.result.sort_column:
                label = "↕ " + label
            self.grid.heading(identifier, text=label, anchor="w")
            self.grid.column(identifier, width=150, minwidth=80, stretch=True)

    def _clear_grid(self) -> None:
        self.entries.clear()
        self.grid.delete(*self.grid.get_children())
        self.grid.configure(columns=())

    def _set_navigation(self, page_count: int, column_count: int) -> None:
        total = self.result.total_rows if self.result is not None else 0
        total_columns = self.result.total_columns if self.result is not None else 0
        self.previous.configure(state="normal" if self.offset else "disabled")
        self.next.configure(state="normal" if self.offset + page_count < total else "disabled")
        self.previous_columns.configure(
            state="normal" if self.result is not None and self.column_offset else "disabled"
        )
        self.next_columns.configure(
            state=(
                "normal"
                if self.result is not None and self.column_offset + column_count < total_columns
                else "disabled"
            )
        )
        if self.result is None:
            self.previous.configure(state="disabled")
            self.next.configure(state="disabled")
        self.jump_button.configure(state="disabled")

    @staticmethod
    def _grid_value(cell: PreviewCell) -> str:
        value = cell.text.replace("\r", "\\r").replace("\n", "\\n").replace("\t", "\\t")
        return value[:200] + "…" if len(value) > 200 else value

    def _location(self, cell: ColumnExample) -> str:
        assert self.scope is not None
        if cell.source_path is not None:
            return f"Record {cell.row} · field {self.scope.column}"
        return f"{column_label(self.scope.column)}{cell.row}"

    @staticmethod
    def _display(cell: ColumnExample) -> str:
        if cell.kind in {"Absent", "Empty element", "Explicit nil"}:
            return f"[{cell.kind.lower()}]"
        if cell.kind == "Blank":
            return "[blank]"
        if cell.kind == "Empty text":
            return "[empty text]"
        return repr(cell.text) if cell.kind == "Text" else cell.text

    def _selected(self, event: tk.Event[tk.Misc] | None = None) -> None:
        selected = self.grid.selection()
        row = self.entries.get(selected[0]) if selected else None
        self.jump_button.configure(state="normal" if row else "disabled")
        if row is None:
            self._detail("")
            return
        cell = row.sort_cell
        evidence = (
            f"State: {cell.presence}\nSource: {cell.source_path}"
            if cell.source_path is not None
            else f"Excel number format: {cell.number_format}"
        )
        self._detail(
            f"Ordered by {self._location(cell)} · {cell.kind}\n{evidence}\n"
            f"Original: {self._display(cell)}"
        )

    def _detail(self, text: str) -> None:
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", text)
        self.detail.configure(state="disabled")

    def jump_selected(self) -> None:
        selected = self.grid.selection()
        row = self.entries.get(selected[0]) if selected else None
        if row is None or self.scope is None:
            return
        try:
            self.jump(self.scope.table, self.scope.column, row.source_row)
        except InspectionError as error:
            self.status.set(str(error))

    def close(self) -> None:
        if self.closed:
            return
        with self.delivery_lock:
            self.closed = True
            self.cancelled.set()
            while not self.results.empty():
                _, value = self.results.get_nowait()
                if isinstance(value, OrderedDataSet):
                    value.close()
        if self.result is not None:
            self.result.close()
            self.result = None
        self.frame.after_cancel(self.poll_id)
        self.frame.destroy()
