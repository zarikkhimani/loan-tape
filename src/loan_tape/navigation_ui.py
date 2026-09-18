"""Workbook coverage, range selection, and page navigation for the native preview."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from functools import partial
from tkinter import ttk
from uuid import uuid4

from loan_tape.flow_ui import FlowBar
from loan_tape.inspection import MAX_COLUMNS, MAX_ROWS, InspectionError
from loan_tape.mapping_profiles import MappingProfileMatch
from loan_tape.ranges import CellRange, column_label, parse_range
from loan_tape.selection import (
    SavedTable,
    SourceSelection,
    TableSelections,
    load_tables,
    save_tables,
)
from loan_tape.table_structure import overlaps
from loan_tape.theme_ui import BORDER, CHROME, FOREGROUND, MUTED, SURFACE
from loan_tape.workbook_index import SheetIndex, WorkbookIndex


class WorkbookNavigator:
    up: ttk.Button
    down: ttk.Button
    left: ttk.Button
    right: ttk.Button

    def __init__(
        self, parent: ttk.Frame, sheet_name: tk.StringVar, changed: Callable[[], None]
    ) -> None:
        style = ttk.Style(parent)
        style.configure("Navigator.TButton", font=("Segoe UI", 9), padding=(4, 2))
        style.configure("Navigator.TEntry", padding=(3, 2))
        style.configure("Navigator.TLabel", font=("Segoe UI", 9))
        style.configure("Muted.Navigator.TLabel", foreground=MUTED)
        style.configure("Navigator.TCombobox", padding=(2, 1))
        style.configure(
            "Navigator.Treeview",
            font=("Segoe UI", 9),
            rowheight=26,
            background=SURFACE,
            fieldbackground=SURFACE,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
        )
        style.configure(
            "Navigator.Treeview.Heading",
            background=CHROME,
            foreground=FOREGROUND,
            relief="flat",
            bordercolor=CHROME,
            lightcolor=CHROME,
            darkcolor=CHROME,
        )
        style.map(
            "Navigator.Treeview.Heading",
            background=[("active", CHROME)],
            relief=[("pressed", "flat")],
        )
        style.configure("Navigator.Treeview.Heading", font=("Segoe UI", 9, "bold"), padding=(3, 2))
        self.frame = ttk.Frame(parent)
        self.sheet_name = sheet_name
        self.changed = changed
        self.setup_changed: Callable[[bool], None] = lambda editing: None
        self.index: WorkbookIndex | None = None
        self.current: SheetIndex | None = None
        self.area: CellRange | None = None
        self.page_area: CellRange | None = None
        self.saved: SourceSelection | None = None
        self.tables: tuple[SavedTable, ...] = ()
        self.editing_id: str | None = None
        self.header_row: int | None = None
        self.table_name = tk.StringVar(master=parent, value="Data set 1")
        self.busy = True
        self.items: dict[str, tuple[SheetIndex, CellRange | None]] = {}
        self.coverage = tk.StringVar(master=parent, value="Scanning every worksheet…")
        self.range_text = tk.StringVar(master=parent)
        self.start_text = tk.StringVar(master=parent)
        self.end_text = tk.StringVar(master=parent)
        self.suggestion_note = tk.StringVar(master=parent)
        self.boundary_text = tk.StringVar(master=parent)
        self.table_count = tk.StringVar(master=parent, value="Scanning for data sets...")
        self.selected_suggestion = ""
        self._syncing_range = False
        self.edge_view = ""
        self.range_text.trace_add("write", self._sync_corners)
        self.start_text.trace_add("write", self._corners_changed)
        self.end_text.trace_add("write", self._corners_changed)
        self.header_text = tk.StringVar(master=parent)
        self.jump_text = tk.StringVar(master=parent)
        self.scope = tk.StringVar(master=parent, value="No range selected for later analysis.")
        self.profile_match: MappingProfileMatch | None = None
        self.profile_text = tk.StringVar(master=parent)
        self.message = tk.StringVar(master=parent)
        self.controls: list[ttk.Button | ttk.Entry] = []
        self.editing = True
        self._clean_setup: tuple[str, ...] = ()
        self.frame.columnconfigure(0, weight=1)
        self.sheet_controls = ttk.Frame(self.frame)
        self.sheet_controls.grid(row=0, sticky="ew")
        self._heading(self.sheet_controls, "1  Choose a sheet")
        # The preview owns the sheet selector and inserts it in this slot.
        self.sheet_slot = ttk.Frame(self.sheet_controls)
        self.sheet_slot.pack(fill="x", pady=(5, 4))
        self.find_button = self._button(self.sheet_controls, "Find data areas...", self.show_areas)
        self.find_button.pack_configure(fill="x")
        # Sheet switching lives above the grid in the preview workspace.

        setup = ttk.Frame(self.frame)
        setup.grid(row=2, sticky="ew")
        self._heading(setup, "Data set setup")
        self.find_button = self._button(setup, "Find data areas…", self.show_areas)
        self.find_button.pack_configure(pady=(6, 0))
        ttk.Label(
            setup, textvariable=self.table_count, wraplength=230, style="Navigator.TLabel"
        ).pack(anchor="w", pady=(6, 4))
        groups = ttk.Frame(setup)
        groups.pack(fill="x")
        self.table_list = ttk.Treeview(
            groups,
            columns=("range",),
            show="tree headings",
            height=4,
            selectmode="browse",
            style="Navigator.Treeview",
        )
        self.table_list.heading("#0", text="Data set", anchor="w")
        self.table_list.heading("range", text="Cells", anchor="w")
        self.table_list.column("#0", width=85, minwidth=60, stretch=True)
        self.table_list.column("range", width=125, minwidth=90, stretch=True)
        self.table_list.pack(side="left", fill="both", expand=True)
        group_scroll = ttk.Scrollbar(
            groups,
            orient="vertical",
            command=self.table_list.yview,
            style="Slim.Vertical.TScrollbar",
        )
        group_scroll.pack(side="right", fill="y")
        self.table_list.configure(yscrollcommand=group_scroll.set)
        self.table_list.bind("<<TreeviewSelect>>", self.choose_suggestion)

        self.saved_bar = ttk.Frame(setup)
        self.saved_bar.pack(fill="x", pady=(6, 0))
        self.table_selector = ttk.Combobox(
            self.saved_bar,
            state="disabled",
            width=20,
            font=("Segoe UI", 9),
            style="Navigator.TCombobox",
        )
        # Its value is mirrored by the always-visible selector above the worksheet.
        self.table_selector.bind("<<ComboboxSelected>>", self.choose_table)
        self.manage_bar = ttk.Frame(self.saved_bar)
        self.manage_bar.pack(fill="x", pady=(5, 0))
        self.edit_button = self._button(self.manage_bar, "Edit setup", self.show_editor)
        self.new_button = self._button(self.manage_bar, "Add another", self.new_table)
        for button in (self.edit_button, self.new_button):
            button.pack_configure(side="left", fill="x", expand=True)

        self.editor = ttk.Frame(self.frame)
        self.editor.grid(row=3, sticky="ew", pady=(6, 0))
        ttk.Label(
            self.editor,
            textvariable=self.suggestion_note,
            style="Muted.Navigator.TLabel",
            wraplength=260,
        ).pack(anchor="w", pady=(3, 6))
        self._label(self.editor, "Data set name")
        self._entry(self.editor, self.table_name, 22)
        corners = ttk.Frame(self.editor)
        corners.pack(fill="x", pady=(8, 0))
        for label, variable in (("Start cell", self.start_text), ("End cell", self.end_text)):
            group = ttk.Frame(corners)
            group.pack(side="left", fill="x", expand=True, padx=(0, 5))
            self._label(group, label)
            entry = self._entry(group, variable, 10)
            entry.bind("<Return>", lambda event: self.apply_range())
        self.preview_button = self._button(self.editor, "Show these boundaries", self.apply_range)
        self.preview_button.pack_configure(pady=(5, 0))
        self._label(self.editor, "Or right-click a cell to set an edge.", muted=True)
        self._label(self.editor, "Header row number (optional)", pady=(8, 2))
        self._entry(self.editor, self.header_text, 8)
        self.header_actions = ttk.Frame(self.editor)
        self.header_actions.pack(fill="x", pady=(4, 0))
        self._label(
            self.editor, "The row containing column names.\nBlank means no headers.", muted=True
        )
        self.use_button = self._button(self.editor, "Save data set", self.use_range)
        self.use_button.configure(style="Primary.Navigator.TButton")
        self.use_button.pack_configure(fill="x", pady=(10, 0))
        self.remove_button = self._button(self.editor, "Remove data set setup", self.remove_table)
        self.remove_button.pack_configure(fill="x", pady=(4, 0))

        self.summary = ttk.Label(
            self.frame, textvariable=self.scope, wraplength=230, style="Navigator.TLabel"
        )
        self.summary.grid(row=4, sticky="ew", pady=(8, 0))
        self.profile_label = ttk.Label(
            self.frame,
            textvariable=self.profile_text,
            wraplength=230,
            style="Muted.Navigator.TLabel",
        )
        self.profile_label.grid(row=5, sticky="ew", pady=(5, 0))
        self.profile_label.grid_remove()
        ttk.Label(
            self.frame,
            textvariable=self.message,
            wraplength=230,
            style="Navigator.TLabel",
            foreground="#80531e",
        ).grid(row=6, sticky="ew", pady=(5, 0))
        # Column actions live beside the worksheet selection.
        self.review = ttk.Frame(self.frame)
        self.review.grid(row=7, sticky="ew")
        self._heading(self.review, "3  Review a column")

        # Secondary information must not compete with the worksheet for height.
        self.overview_window = tk.Toplevel(parent)
        self.overview_window.withdraw()
        self.overview_window.title("Workbook details")
        self.overview_window.geometry("860x540")
        self.overview_window.minsize(650, 420)
        self.overview_window.transient(parent.winfo_toplevel())
        self.overview_window.protocol("WM_DELETE_WINDOW", self.overview_window.withdraw)
        self.details_tabs = ttk.Notebook(self.overview_window)
        self.details_tabs.pack(fill="both", expand=True, padx=14, pady=14)
        self.areas = ttk.Frame(self.details_tabs, padding=12)
        self.details = ttk.Frame(self.details_tabs, padding=12)
        self.details_tabs.add(self.areas, text="Find data areas")
        self.details_tabs.add(self.details, text="Reading details")
        ttk.Label(self.areas, textvariable=self.coverage, wraplength=710).pack(anchor="w")
        ttk.Label(
            self.areas,
            text="Expand a sheet, choose an area, then click View selected area. You choose the data set boundaries.",
            wraplength=710,
        ).pack(anchor="w", pady=(6, 12))
        overview = ttk.Frame(self.areas)
        overview.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(
            overview,
            columns=("visibility", "range", "size", "cells"),
            height=8,
            selectmode="browse",
            style="Navigator.Treeview",
        )
        for column, label, width in (
            ("#0", "Sheet / area", 190),
            ("visibility", "Visibility", 75),
            ("range", "Cells", 140),
            ("size", "Rows x columns", 115),
            ("cells", "Stored cells", 85),
        ):
            self.tree.heading(column, text=label)
            self.tree.column(column, width=width, minwidth=45)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(
            overview, orient="vertical", command=self.tree.yview, style="Slim.Vertical.TScrollbar"
        )
        scroll.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<Double-1>", self._choose)
        self.open_area_button = self._button(self.areas, "View selected area", self._choose)
        self.open_area_button.pack_configure(pady=(8, 0))
        self.all_data_button = self._button(self.areas, "View entire sheet", self._entire_sheet)
        self.all_data_button.pack_configure(pady=(8, 0))
        self.sheet_details = tk.StringVar(master=parent)
        ttk.Label(self.details, textvariable=self.sheet_details, wraplength=710).pack(
            anchor="w", pady=(0, 12)
        )

        def wrap_labels(event: tk.Event[tk.Misc]) -> None:
            def wrap(widget: tk.Misc) -> None:
                for child in widget.winfo_children():
                    if isinstance(child, ttk.Label):
                        child.configure(wraplength=max(160, event.width - 4))
                    if isinstance(child, ttk.Frame):
                        wrap(child)

            wrap(self.frame)

        self.frame.bind("<Configure>", wrap_labels)

    @staticmethod
    def _heading(parent: ttk.Frame, text: str) -> None:
        ttk.Label(parent, text=text, font=("Segoe UI", 10, "bold")).pack(anchor="w")

    @staticmethod
    def _label(
        parent: ttk.Frame, text: str, *, muted: bool = False, pady: tuple[int, int] = (2, 2)
    ) -> None:
        ttk.Label(
            parent,
            text=text,
            style="Muted.Navigator.TLabel" if muted else "Navigator.TLabel",
            wraplength=260,
        ).pack(anchor="w", pady=pady)

    def _button(self, parent: ttk.Frame, text: str, command: Callable[[], None]) -> ttk.Button:
        button = ttk.Button(parent, text=text, command=command, style="Navigator.TButton")
        button.pack(fill="x")
        self.controls.append(button)
        return button

    def _entry(self, parent: ttk.Frame, variable: tk.StringVar, width: int) -> ttk.Entry:
        entry = ttk.Entry(
            parent,
            textvariable=variable,
            width=width,
            style="Navigator.TEntry",
            font=("Segoe UI", 9),
        )
        entry.pack(fill="x")
        self.controls.append(entry)
        return entry

    def build_paging(self, parent: ttk.Frame) -> None:
        self.paging = FlowBar(parent)
        for label, actions in (
            ("Rows", (("up", -MAX_ROWS, 0), ("down", MAX_ROWS, 0))),
            ("Columns", (("left", 0, -MAX_COLUMNS), ("right", 0, MAX_COLUMNS))),
        ):
            group = ttk.Frame(self.paging)
            self.paging.add(group)
            ttk.Label(group, text=label).pack(side="left", padx=(0, 6))
            for text, (name, rows, columns) in zip(("◀", "▶"), actions, strict=True):
                button = self._button(group, text, partial(self.move, rows, columns))
                button.configure(width=3)
                button.pack_configure(side="left", padx=(0, 4))
                setattr(self, name, button)
        edges = ttk.Frame(self.paging)
        self.paging.add(edges)
        self.start_button = self._button(edges, "Start", partial(self.view_edge, False))
        self.start_button.configure(width=5)
        self.start_button.pack_configure(side="left", padx=(0, 4))
        self.end_button = self._button(edges, "End", partial(self.view_edge, True))
        self.end_button.configure(width=5)
        self.end_button.pack_configure(side="left")
        self.set_busy(True)

    def build_jump(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="Go to cell").pack(side="left", padx=(0, 6))
        entry = self._entry(parent, self.jump_text, 9)
        entry.pack_configure(side="left")
        entry.bind("<Return>", lambda event: self.jump())
        button = self._button(parent, "Go", self.jump)
        button.configure(width=3)
        button.pack_configure(side="left", padx=(4, 0))

    def show_areas(self) -> None:
        self.details_tabs.select(self.areas)  # type: ignore[no-untyped-call]
        self.overview_window.deiconify()
        self.overview_window.lift()

    def show_details(self) -> None:
        self.details_tabs.select(self.details)  # type: ignore[no-untyped-call]
        self.overview_window.deiconify()
        self.overview_window.lift()

    def show_editor(self) -> None:
        self.editing = True
        self.set_profile_match(None)
        self.editor.grid()
        self.summary.grid_remove()
        self.setup_changed(True)

    def _finish_setup(self) -> None:
        self.editing = False
        self.editor.grid_remove()
        self.summary.grid()
        self.message.set("")
        self._clean_setup = self._setup_values()
        self.setup_changed(False)

    def _setup_values(self) -> tuple[str, ...]:
        return tuple(
            variable.get()
            for variable in (self.sheet_name, self.table_name, self.range_text, self.header_text)
        )

    def has_unsaved_setup(self) -> bool:
        return self.index is not None and self._setup_values() != self._clean_setup

    def set_profile_match(self, match: MappingProfileMatch | None) -> None:
        """Show only an exact, complete match for the active saved data set."""
        self.profile_match = match
        self.profile_text.set(match.description if match is not None else "")
        if match is None:
            self.profile_label.grid_remove()
        else:
            self.profile_label.grid()

    def set_index(self, index: WorkbookIndex) -> None:
        self.index = index
        total = sum(sheet.stored_cells for sheet in index.sheets)
        scanned = sum(sheet.error is None for sheet in index.sheets)
        prefix = "Scan complete" if index.complete else "INCOMPLETE SCAN"
        self.coverage.set(
            f"{prefix}: {scanned} of {len(index.sheets)} tabs scanned · {total:,} cells with stored content. Hidden rows and columns included."
        )
        for number, sheet in enumerate(index.sheets):
            bounds = sheet.bounds
            item = self.tree.insert(
                "",
                "end",
                iid=f"sheet-{number}",
                text=sheet.name,
                values=(
                    sheet.visibility,
                    bounds.address if bounds else ("Not scanned" if sheet.error else "Empty"),
                    f"{bounds.row_count:,} × {bounds.column_count:,}" if bounds else "",
                    f"{sheet.stored_cells:,}" if not sheet.error else "Unknown",
                ),
            )
            self.items[item] = (sheet, bounds)
            for area_number, area in enumerate(sheet.areas):
                child = self.tree.insert(
                    item,
                    "end",
                    text=f"Area {area_number + 1}" if not sheet.condensed else "Combined areas",
                    values=("", area.address, f"{area.row_count:,} × {area.column_count:,}", ""),
                )
                self.items[child] = (sheet, area)
        restore_error = ""
        try:
            settings = load_tables(index.sha256)
            self.tables = settings.tables
            self.saved = settings.active.selection if settings.active else None
            self.editing_id = settings.active_id
        except (OSError, ValueError) as error:
            restore_error = str(error)
        available = [sheet for sheet in index.sheets if not sheet.error]
        first = next(
            (sheet for sheet in available if sheet.bounds),
            available[0] if available else index.sheets[0],
        )
        if self.saved:
            restored = next((sheet for sheet in available if sheet.name == self.saved.sheet), None)
            if restored:
                first = restored
            else:
                self.saved = None
                restore_error = "Saved worksheet is unavailable. Choose a new range."
        restore_id = self.editing_id
        self.select_sheet(first.name)
        self._refresh_tables()
        if restore_id and any(table.id == restore_id for table in self.tables):
            self._open_table(restore_id)
        self._scope()
        if restore_error:
            self.message.set(restore_error)

    def select_sheet(self, name: str, *, suggest: bool = True) -> None:
        if self.index is None:
            return
        self.current = next(sheet for sheet in self.index.sheets if sheet.name == name)
        self.sheet_name.set(name)
        self._new_draft()
        suggestions = self.current.tables
        if suggest and suggestions:
            best = max(
                range(len(suggestions)),
                key=lambda i: suggestions[i].area.row_count * suggestions[i].area.column_count,
            )
            self._apply_suggestion(best)
        else:
            self._set_area(self.current.bounds)
        extra = f"{self.current.hidden_rows:,} hidden rows · {self.current.hidden_columns:,} hidden columns · {self.current.merged_ranges:,} merged ranges."
        note = "Area suggestions are geometric; adjust boundaries as needed."
        if self.current.condensed:
            note = "Many separate areas: suggestions combined; all stored cells remain covered."
        self.sheet_details.set(extra + " " + note)
        self.message.set(self.current.error or "")
        self._clean_setup = self._setup_values()

    def _sync_corners(self, *args: str) -> None:
        if self._syncing_range:
            return
        if not self.range_text.get():
            self._syncing_range = True
            self.start_text.set("")
            self.end_text.set("")
            self._syncing_range = False
            return
        try:
            area = parse_range(self.range_text.get())
        except ValueError:
            return
        self._syncing_range = True
        try:
            self.start_text.set(f"{column_label(area.min_column)}{area.min_row}")
            self.end_text.set(f"{column_label(area.max_column)}{area.max_row}")
        finally:
            self._syncing_range = False

    def _corners_changed(self, *args: str) -> None:
        if self._syncing_range:
            return
        self._syncing_range = True
        try:
            self.range_text.set(f"{self.start_text.get().strip()}:{self.end_text.get().strip()}")
        finally:
            self._syncing_range = False

    def _saved_for_suggestion(self, position: int) -> SavedTable | None:
        if self.current is None or position >= len(self.current.tables):
            return None
        area = self.current.tables[position].area
        matches = [
            table
            for table in self.tables
            if table.selection.sheet == self.current.name and overlaps(table.selection.area, area)
        ]
        # Never infer a mapping if one user range covers several suggestions,
        # or several saved definitions intersect this suggestion.
        if (
            len(matches) == 1
            and sum(overlaps(matches[0].selection.area, item.area) for item in self.current.tables)
            == 1
        ):
            return matches[0]
        return None

    def _refresh_suggestions(self) -> None:
        self.table_list.delete(*self.table_list.get_children())
        self.selected_suggestion = ""
        if self.current is None:
            return
        if self.current.error:
            self.table_count.set("Data set scan unavailable for this sheet.")
            return
        count = len(self.current.tables)
        self.table_count.set(
            f"{count} {'data set' if count == 1 else 'data sets'} found across this sheet."
            if count
            else "No data set identified. Choose boundaries in the whole sheet."
        )
        for i, item in enumerate(self.current.tables):
            saved = self._saved_for_suggestion(i)
            self.table_list.insert(
                "",
                "end",
                iid=str(i),
                text=saved.name if saved else f"Data set {i + 1}",
                values=((saved.selection.area if saved else item.area).address,),
            )
        if self.current.bounds:
            self.table_list.insert(
                "",
                "end",
                iid=str(count),
                text="Whole sheet",
                values=(self.current.bounds.address,),
            )

        self._mark_suggestion(self._suggestion_position(self.area))

    def _suggestion_position(self, area: CellRange | None) -> int | None:
        if self.current is None:
            return None
        for i, item in enumerate(self.current.tables):
            saved = self._saved_for_suggestion(i)
            if (self.editing_id and saved and saved.id == self.editing_id) or item.area == area:
                return i
        return len(self.current.tables) if area and area == self.current.bounds else None

    def _mark_suggestion(self, position: int | None) -> None:
        item = str(position) if position is not None else ""
        self.selected_suggestion = item
        if item and self.table_list.exists(item):
            self.table_list.selection_set(item)
            # Scroll only when needed; see() before layout can hide earlier rows.
            height = int(self.table_list["height"])
            total = len(self.table_list.get_children())
            self.table_list.yview_moveto(max(0, (int(item) - height + 1) / total))
        else:
            self.table_list.selection_remove(*self.table_list.selection())

    def _apply_suggestion(self, position: int) -> None:
        if self.current is None:
            return
        if position == len(self.current.tables):
            self.header_row = None
            self.header_text.set("")
            self._set_area(self.current.bounds)
            self._mark_suggestion(position)
            return
        item = self.current.tables[position]
        name = (item.name or f"Data set {position + 1}")[:80]
        names = {table.name.casefold() for table in self.tables}
        if name.casefold() not in names:
            self.table_name.set(name)
        self.header_row = item.header_row
        self.header_text.set(str(item.header_row) if item.header_row else "")
        self._set_area(item.area)
        self._mark_suggestion(position)
        self.suggestion_note.set(
            "Workbook-defined boundaries. Adjust if needed."
            if item.basis == "excel_table"
            else "Suggested boundaries and headers. Adjust if needed."
        )

    def choose_suggestion(self, event: tk.Event[tk.Misc] | None = None) -> None:
        selected = self.table_list.selection()
        if not selected or selected[0] == self.selected_suggestion or self.current is None:
            return
        if self.busy:
            self._mark_suggestion(
                int(self.selected_suggestion) if self.selected_suggestion else None
            )
            return
        position = int(selected[0])
        saved = self._saved_for_suggestion(position)
        if saved:
            self._open_table(saved.id)
        else:
            self._new_draft()
            self._apply_suggestion(position)
            self._clean_setup = self._setup_values()
        self.message.set("")
        self.changed()

    def _set_area(self, area: CellRange | None) -> None:
        self.area = area
        self.edge_view = ""
        if self.current:
            position = self._suggestion_position(area)
            if position is not None and position < len(self.current.tables):
                self._mark_suggestion(position)
                self.suggestion_note.set("Suggested structure; you can edit every boundary.")
            elif area == self.current.bounds:
                self._mark_suggestion(len(self.current.tables))
                self.suggestion_note.set("Showing all data on this sheet.")
            else:
                self._mark_suggestion(None)
                self.suggestion_note.set("Your selected start and end cells.")
        self.page_area = area.page(area.min_row, area.min_column) if area else None
        self.range_text.set(area.address if area else "")
        self.jump_text.set("")
        self._scope()

    def _scope(self) -> None:
        if not self.area:
            self.boundary_text.set("This sheet has no stored data.")
            self.scope.set("This sheet has no stored data.")
            return
        self.boundary_text.set(
            f"Start {column_label(self.area.min_column)}{self.area.min_row}  |  "
            f"End {column_label(self.area.max_column)}{self.area.max_row}  |  "
            f"{self.area.row_count:,} rows x {self.area.column_count:,} columns"
        )
        header = f"Column names: row {self.header_row}" if self.header_row else "No header row"
        self.scope.set(
            f"{self.sheet_name.get()}!{self.area.address}\n"
            f"{self.area.row_count:,} rows, {self.area.column_count:,} columns\n{header}"
        )

    def _refresh_tables(self) -> None:
        self._refresh_suggestions()
        if self.tables:
            self.saved_bar.pack(fill="x", pady=(6, 0))
        else:
            self.saved_bar.pack_forget()
        if self.editing_id:
            self.remove_button.pack(fill="x", pady=(4, 0))
        else:
            self.remove_button.pack_forget()
        self.table_selector.configure(values=tuple(table.name for table in self.tables))
        position = next(
            (i for i, table in enumerate(self.tables) if table.id == self.editing_id), None
        )
        if position is None:
            self.table_selector.set("")
        else:
            self.table_selector.current(position)

    def _new_draft(self) -> None:
        self.editing_id = None
        self.header_row = None
        self.header_text.set("")
        names = {table.name.casefold() for table in self.tables}
        number = 1
        while f"data set {number}" in names:
            number += 1
        self.table_name.set(f"Data set {number}")
        self._refresh_tables()
        self.show_editor()

    def new_table(self) -> None:
        if self.busy:
            return
        self._new_draft()
        unused = (
            [
                i
                for i, item in enumerate(self.current.tables)
                if not any(
                    saved.selection.sheet == self.current.name
                    and overlaps(saved.selection.area, item.area)
                    for saved in self.tables
                )
            ]
            if self.current
            else []
        )
        if unused:
            self._apply_suggestion(unused[0])
        else:
            self._set_area(self.current.bounds if self.current else None)
        self._clean_setup = self._setup_values()
        self.message.set("Review the next data set's boundaries, then save.")
        self.changed()

    def _open_table(self, table_id: str) -> bool:
        table = next(table for table in self.tables if table.id == table_id)
        if self.index is None:
            return False
        sheet = next(
            (sheet for sheet in self.index.sheets if sheet.name == table.selection.sheet), None
        )
        if sheet is None or sheet.error:
            self.message.set(
                "This saved data set's worksheet is unavailable. Its settings are retained."
            )
            self._refresh_tables()
            return False
        self.select_sheet(sheet.name, suggest=False)
        self.editing_id = table.id
        self.table_name.set(table.name)
        self.header_row = table.selection.header_row
        self.header_text.set(str(self.header_row) if self.header_row else "")
        self._set_area(table.selection.area)
        self._refresh_tables()
        self._finish_setup()
        return True

    def choose_table(self, event: tk.Event[tk.Misc] | None = None) -> None:
        if self.busy or self.table_selector.current() < 0:
            return
        table = self.tables[self.table_selector.current()]
        if self._open_table(table.id):
            self.changed()

    def remove_table(self) -> None:
        if self.busy or self.editing_id is None or self.index is None:
            return
        tables = tuple(table for table in self.tables if table.id != self.editing_id)
        active = tables[0] if tables else None
        try:
            save_tables(TableSelections(self.index.sha256, tables, active.id if active else None))
        except (ValueError, OSError) as error:
            self.message.set(str(error))
            return
        self.tables = tables
        self.saved = active.selection if active else None
        self._new_draft()
        if active:
            self._open_table(active.id)
        self._scope()
        self.message.set("Data set settings removed. The workbook and its data are unchanged.")
        self.changed()

    def set_header_row(self, row: int) -> None:
        if self.busy or self.area is None or self.index is None or self.current is None:
            return
        try:
            SourceSelection(self.index.sha256, self.current.name, self.area, row)
        except ValueError as error:
            self.message.set(str(error))
            return
        self.show_editor()
        self.header_row = row
        self.header_text.set(str(row))
        self._scope()
        self.message.set(f"Row {row} selected. Save data set to continue.")
        self.changed()

    def _choose(self, event: tk.Event[tk.Misc] | None = None) -> None:
        if self.busy or not self.tree.selection():
            return
        sheet, area = self.items[self.tree.selection()[0]]
        self.select_sheet(sheet.name, suggest=False)
        self._set_area(area)
        self.overview_window.withdraw()
        self.changed()

    def _entire_sheet(self) -> None:
        if self.busy:
            return
        if self.tree.selection():
            sheet, _ = self.items[self.tree.selection()[0]]
            self.select_sheet(sheet.name, suggest=False)
        self.all_data()

    def all_data(self) -> None:
        if not self.busy and self.current:
            self._new_draft()
            self._set_area(self.current.bounds)
            self.overview_window.withdraw()
            self.changed()

    def apply_range(self) -> None:
        if self.busy:
            return
        try:
            area = parse_range(self.range_text.get())
            header = int(self.header_text.get()) if self.header_text.get().strip() else None
            if self.index is None or self.current is None:
                return
            SourceSelection(self.index.sha256, self.current.name, area, header)
        except ValueError as error:
            self.message.set(str(error))
            return
        self.header_row = header
        self._set_area(area)
        self.changed()

    def use_range(self) -> None:
        if self.busy or self.index is None or self.current is None or self.current.error:
            return
        try:
            area = parse_range(self.range_text.get())
            header = int(self.header_text.get()) if self.header_text.get().strip() else None
            selection = SourceSelection(self.index.sha256, self.current.name, area, header)
            table = SavedTable(
                self.editing_id or uuid4().hex, self.table_name.get().strip(), selection
            )
            tables = tuple(table if item.id == table.id else item for item in self.tables)
            if self.editing_id is None:
                tables = (*tables, table)
            save_tables(TableSelections(self.index.sha256, tables, table.id))
        except (ValueError, OSError) as error:
            self.message.set(str(error))
            return
        self.tables = tables
        self.editing_id = table.id
        self.saved = selection
        self.header_row = header
        self.table_name.set(table.name)
        self._refresh_tables()
        self._set_area(area)
        self._finish_setup()
        self.changed()

    def table_for_inspection(self) -> SavedTable:
        table = next((table for table in self.tables if table.id == self.editing_id), None)
        if table is None:
            raise InspectionError("Save this data set, then select a column to inspect.")
        try:
            area = parse_range(self.range_text.get())
            header = int(self.header_text.get()) if self.header_text.get().strip() else None
        except ValueError as error:
            raise InspectionError(
                "Correct and save the data set range/header before inspecting a column."
            ) from error
        selected = table.selection
        if (
            selected.sheet != self.sheet_name.get()
            or selected.area != area
            or selected.area != self.area
            or selected.header_row != header
            or selected.header_row != self.header_row
            or table.name != self.table_name.get().strip()
        ):
            raise InspectionError("Save your data set changes before inspecting a column.")
        return table

    def view_edge(self, end: bool) -> None:
        if self.busy or self.area is None:
            return
        row = max(self.area.min_row, self.area.max_row - MAX_ROWS + 1) if end else self.area.min_row
        column = (
            max(self.area.min_column, self.area.max_column - MAX_COLUMNS + 1)
            if end
            else self.area.min_column
        )
        self.page_area = self.area.page(row, column)
        self.edge_view = "end" if end else "start"
        self.changed()

    def set_corner(self, row: int, column: int, *, end: bool) -> None:
        if self.busy or self.area is None:
            return
        self.show_editor()
        (self.end_text if end else self.start_text).set(f"{column_label(column)}{row}")
        self.apply_range()

    def move(self, rows: int, columns: int) -> None:
        if self.busy or self.area is None or self.page_area is None:
            return
        row = max(self.area.min_row, self.page_area.min_row + rows)
        column = max(self.area.min_column, self.page_area.min_column + columns)
        if not self.area.contains(row, column):
            return
        self.page_area = self.area.page(row, column)
        self.edge_view = ""
        self.changed()

    def jump(self) -> None:
        if self.busy or self.area is None:
            return
        try:
            cell = parse_range(self.jump_text.get())
            if cell.row_count != 1 or cell.column_count != 1:
                raise ValueError("Enter one cell to jump to.")
            self.page_area = self.area.page(cell.min_row, cell.min_column)
            self.edge_view = ""
        except ValueError as error:
            self.message.set(str(error))
            return
        self.changed()

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        for control in self.controls:
            control.configure(state="disabled" if busy else "normal")
        self.table_selector.configure(state="readonly" if not busy and self.tables else "disabled")
        self.table_list.state(["disabled"] if busy else ["!disabled"])
        self.start_button.configure(state="normal" if not busy and self.area else "disabled")
        self.end_button.configure(state="normal" if not busy and self.area else "disabled")
        if not busy:
            self.remove_button.configure(state="normal" if self.editing_id else "disabled")
            self.use_button.configure(
                state="normal"
                if self.current is not None and not self.current.error
                else "disabled"
            )
            for button, enabled in (
                (
                    self.up,
                    self.page_area is not None
                    and self.area is not None
                    and self.page_area.min_row > self.area.min_row,
                ),
                (
                    self.down,
                    self.page_area is not None
                    and self.area is not None
                    and self.page_area.max_row < self.area.max_row,
                ),
                (
                    self.left,
                    self.page_area is not None
                    and self.area is not None
                    and self.page_area.min_column > self.area.min_column,
                ),
                (
                    self.right,
                    self.page_area is not None
                    and self.area is not None
                    and self.page_area.max_column < self.area.max_column,
                ),
            ):
                button.configure(state="normal" if enabled else "disabled")
