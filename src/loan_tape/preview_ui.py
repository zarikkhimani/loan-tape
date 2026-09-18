"""Simple read-only data grid for a saved file."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from tkinter import filedialog, font, messagebox, ttk

from loan_tape.column_check_ui import ColumnCheckWindow
from loan_tape.column_definition_ui import ColumnDefinitionWindow
from loan_tape.column_profile import ColumnTable
from loan_tape.column_ui import ColumnWindow
from loan_tape.date_workflow_ui import DateWorkflowWindow
from loan_tape.excel_compare import ComparedPreview, read_parallel_preview
from loan_tape.excel_process import open_in_excel
from loan_tape.flow_ui import FlowBar
from loan_tape.grid_selection import ColumnHighlight
from loan_tape.inspection import (
    DELIMITERS,
    ENCODINGS,
    FilePreview,
    InspectionError,
    PreviewCell,
    read_preview,
)
from loan_tape.mapping_profiles import MappingProfileMatch, match_builtin_table_profile
from loan_tape.navigation_ui import WorkbookNavigator
from loan_tape.order_ui import OrderScope
from loan_tape.packs import PackStore
from loan_tape.ranges import CellRange, column_label
from loan_tape.selection import SavedTable
from loan_tape.session import AnalysisSession
from loan_tape.theme_ui import (
    ACCENT,
    ACCENT_HOVER,
    BORDER,
    CHROME,
    ERROR,
    FOREGROUND,
    MUTED,
    SURFACE,
)
from loan_tape.workbook_index import WorkbookIndex, scan_workbook
from loan_tape.workers import WorkerGroup
from loan_tape.xml_navigation_ui import XmlNavigator
from loan_tape.xml_schema_ui import XsdValidationWindow
from loan_tape.xml_selection import SavedXmlTable


@dataclass(frozen=True)
class LoadedPreview:
    data: FilePreview | ComparedPreview
    headers: tuple[PreviewCell, ...] = ()
    profile_match: MappingProfileMatch | None = None


class PreviewPanel:
    def __init__(
        self,
        parent: ttk.Notebook,
        path: Path,
        session: AnalysisSession,
        workers: WorkerGroup,
        activate: Callable[[], None],
        on_close: Callable[[], None],
        pack_store: PackStore | None = None,
    ) -> None:
        self.workers = workers
        self.activate = activate
        self.on_close = on_close
        self.owner = parent.winfo_toplevel()
        self.wheel_binding: str | None = None
        self.details_were_visible = False
        self.path = path
        self.session = session
        self.pack_store = pack_store or PackStore(Path("packs"), Path(".artifacts/packs"))
        self.frame = ttk.Frame(parent)
        self.closed = False
        self.busy = False
        self.preview: FilePreview | None = None
        self.navigator: WorkbookNavigator | None = None
        self.comparison: ComparedPreview | None = None
        self.headers: tuple[PreviewCell, ...] = ()
        self.header_button: ttk.Button | None = None
        self.cancelled = threading.Event()
        self.reader_name = tk.StringVar(master=self.frame, value="openpyxl")
        self.comparison_note = tk.StringVar(master=self.frame)
        self.reader_selector: ttk.Combobox | None = None
        self.active_column = 0
        self.column_selected = False
        self.whole_column: tuple[str, CellRange | None, int] | None = None
        self.definition_button: ttk.Button | None = None
        self.column_definition: ColumnDefinitionWindow | None = None
        self.column_button: ttk.Button | None = None
        self.column_inspector: ColumnWindow | None = None
        self.check_button: ttk.Button | None = None
        self.column_checker: ColumnCheckWindow | None = None
        self.date_workflow: DateWorkflowWindow | None = None
        self.date_button: ttk.Button | None = None
        self.date_actions: ttk.Frame | None = None
        self.xsd_button: ttk.Button | None = None
        self.xsd_validator: XsdValidationWindow | None = None
        self.last_xsd_path: Path | None = None
        self.pending_cell: tuple[int, int] | None = None
        self.results: queue.Queue[LoadedPreview | WorkbookIndex | str | Exception] = queue.Queue()
        self.status = tk.StringVar(master=self.frame)
        self.workflow_hint = tk.StringVar(
            master=self.frame,
            value="Next: save the data set.",
        )
        self.note = tk.StringVar(master=self.frame)
        self.sheet_name = tk.StringVar(master=self.frame)
        self.zoom = tk.StringVar(master=self.frame, value="80%")
        self.column_width = 116
        self.sidebar_collapsed = False
        self.wheel_remainder = {"rows": 0.0, "columns": 0.0, "sidebar": 0.0}
        self.encoding = tk.StringVar(master=self.frame, value="Automatic")
        self.delimiter = tk.StringVar(master=self.frame, value="Automatic")
        self.xml_group = tk.StringVar(master=self.frame)
        self.xml_group_selector: ttk.Combobox | None = None
        self.xml_navigation: XmlNavigator | None = None
        self._build()
        # A hidden tab can receive reader results before its grid is mapped.
        self.frame.bind("<Map>", lambda event: self.column_highlight.refresh())
        self.poll_id = self.frame.after(80, self._poll)
        if self.navigator:
            self._discover()
        else:
            self.load()

    def _build(self) -> None:
        excel = self.path.suffix.lower() in {".xlsx", ".xlsm"}
        style = ttk.Style(self.frame)
        style.configure("Primary.Navigator.TButton", background=ACCENT, foreground="white")
        style.map(
            "Primary.Navigator.TButton",
            background=[("disabled", "#829b8d"), ("active", ACCENT_HOVER)],
        )
        for orientation in ("Vertical", "Horizontal"):
            style.configure(f"Slim.{orientation}.TScrollbar", arrowsize=10, width=10)
        style.configure(
            "Sidebar.TButton",
            font=("Segoe UI", 9, "bold"),
            padding=(5, 3),
            background=ACCENT,
            foreground="white",
            borderwidth=0,
        )
        style.map("Sidebar.TButton", background=[("active", ACCENT_HOVER)])
        self.grid_style = f"Preview{self.frame.winfo_id()}.Treeview"
        family = font.nametofont("TkDefaultFont").actual("family")
        self.grid_font = font.Font(self.frame, family=family, size=9)
        self.heading_font = font.Font(self.frame, family=family, size=9, weight="bold")
        style.configure(
            self.grid_style, font=self.grid_font, rowheight=self.grid_font.metrics("linespace") + 4
        )
        style.configure(
            self.grid_style,
            background=SURFACE,
            fieldbackground=SURFACE,
            foreground=FOREGROUND,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
        )
        style.configure(
            self.grid_style + ".Heading",
            font=self.heading_font,
            padding=(6, 5),
            background=CHROME,
            foreground=FOREGROUND,
            relief="flat",
            bordercolor=CHROME,
            lightcolor=CHROME,
            darkcolor=CHROME,
        )
        style.map(
            self.grid_style + ".Heading",
            background=[("active", "#e7eee4")],
            relief=[("pressed", "flat")],
        )
        page = ttk.Frame(self.frame, padding=(20, 6))
        page.pack(fill="both", expand=True)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(2, weight=1)
        title = ttk.Frame(page)
        title.grid(row=0, sticky="ew", pady=(0, 6))
        title.columnconfigure(0, weight=1)
        self.title_font = font.Font(self.frame, family=family, size=15)
        self.filename_label = ttk.Label(title, text=self.path.name, font=self.title_font)
        self.filename_label.grid(row=0, column=0, sticky="ew")
        title_actions = ttk.Frame(title)
        title_actions.grid(row=0, column=1, sticky="e", padx=(12, 0))
        self.open_excel_button = ttk.Button(
            title_actions,
            text="Open in Excel",
            command=self._open_in_excel,
            style="Navigator.TButton",
        )
        if self.path.suffix.lower() != ".xml":
            self.open_excel_button.pack(side="right", padx=(10, 0))
        else:
            self.open_excel_button.configure(state="disabled")
            self.xsd_button = ttk.Button(
                title_actions,
                text="Validate XSD…",
                command=self.validate_xsd,
                state="disabled",
                style="Navigator.TButton",
            )
            self.xsd_button.pack(side="right")
        title.bind(
            "<Configure>",
            lambda event: self._fit_filename(event.width - title_actions.winfo_reqwidth() - 20),
        )
        self.context_bar = FlowBar(page)
        self.context_bar.grid(row=1, sticky="ew", pady=(0, 8))
        body = ttk.Frame(page)
        body.grid(row=2, sticky="nsew")
        body.rowconfigure(0, weight=1)
        body.columnconfigure(2, weight=1)
        self.workspace = ttk.Frame(body)
        self.workspace.grid(row=0, column=2, sticky="nsew")
        self.workspace.columnconfigure(0, weight=1)
        self.workspace.rowconfigure(2, weight=1)
        self.selectors: list[ttk.Combobox] = []
        self.cell_summary = tk.StringVar(master=self.frame, value="Click a cell to see its value.")
        self.reader_status = tk.StringVar(
            master=self.frame, value="Read-only · Original file preserved"
        )

        if excel:
            # A scrollable setup rail keeps controls reachable at large Windows text sizes.
            self.rail = rail = ttk.Frame(body)
            rail.grid(row=0, column=0, sticky="ns")
            rail.rowconfigure(0, weight=1)
            self.sidebar = tk.Canvas(
                rail,
                width=240,
                highlightthickness=0,
                yscrollincrement=1,
                background=style.lookup("TFrame", "background"),
            )
            self.sidebar.grid(row=0, column=0, sticky="ns")
            scroll = ttk.Scrollbar(
                rail,
                orient="vertical",
                command=self.sidebar.yview,
                style="Slim.Vertical.TScrollbar",
            )
            self.sidebar.configure(yscrollcommand=scroll.set)
            self._bind_scroll_jump(scroll, self.sidebar.yview, vertical=True)
            rail_content = ttk.Frame(self.sidebar)
            rail_item = self.sidebar.create_window(
                0, 0, window=rail_content, anchor="nw", width=240
            )

            def size_rail(event: tk.Event[tk.Misc]) -> None:
                self.sidebar.configure(scrollregion=self.sidebar.bbox("all"))
                if rail_content.winfo_reqheight() > self.sidebar.winfo_height():
                    scroll.grid(row=0, column=1, sticky="ns")
                else:
                    scroll.grid_remove()
                    self.sidebar.yview_moveto(0)

            rail_content.bind("<Configure>", size_rail)

            def resize_rail(event: tk.Event[tk.Misc]) -> None:
                self.sidebar.itemconfigure(rail_item, width=event.width)
                size_rail(event)

            self.sidebar.bind("<Configure>", resize_rail)

            def scroll_rail(event: tk.Event[tk.Misc]) -> str | None:
                inside = str(event.widget).startswith(str(self.sidebar))
                if isinstance(event.widget, (ttk.Treeview, ttk.Combobox, tk.Text)):
                    return None
                if inside and self.sidebar.yview() != (0.0, 1.0) and event.delta:
                    self.sidebar.yview_scroll(
                        self._wheel_units(event.delta, "sidebar", 32), "units"
                    )
                    return "break"
                return None

            self.wheel_binding = self.owner.bind("<MouseWheel>", scroll_rail, add="+")
            # The toggle belongs to the sidebar edge but never hides with its content.
            self.rail_edge = ttk.Frame(body)
            self.rail_edge.grid(row=0, column=1, sticky="ns", padx=(4, 8))
            self.rail_edge.rowconfigure(1, weight=1)
            self.sidebar_toggle = ttk.Button(
                self.rail_edge,
                text="◀",
                width=2,
                style="Sidebar.TButton",
                command=self._toggle_sidebar,
            )
            self.sidebar_toggle.grid(row=0, column=0, sticky="n")
            self.rail_separator = ttk.Separator(self.rail_edge, orient="vertical")
            self.rail_separator.grid(row=1, column=0, sticky="ns", pady=(6, 0))
            self.navigator = WorkbookNavigator(rail_content, self.sheet_name, self.load)
            self.navigator.frame.pack(fill="x")
            self.navigator.setup_changed = self._setup_changed
            self.navigator.sheet_controls.grid_remove()
            self.navigator.review.grid_remove()
            # Sheet and saved-set switching remain visible when setup folds away.
            sheet_group = ttk.Frame(self.context_bar)
            ttk.Label(sheet_group, text="Sheet", style="Muted.TLabel").pack(
                side="left", padx=(0, 6)
            )
            self.sheet_selector = ttk.Combobox(
                sheet_group,
                textvariable=self.sheet_name,
                state="readonly",
                width=20,
                font=("Segoe UI", 9),
                style="Navigator.TCombobox",
            )
            self.sheet_selector.pack(side="left")
            self.context_bar.add(sheet_group)
            data_group = ttk.Frame(self.context_bar)
            ttk.Label(data_group, text="Data set", style="Muted.TLabel").pack(
                side="left", padx=(0, 6)
            )
            self.data_selector = ttk.Combobox(
                data_group,
                state="disabled",
                width=22,
                style="Navigator.TCombobox",
                font=(family, 9),
            )
            self.data_selector.pack(side="left")
            self.data_selector.bind("<<ComboboxSelected>>", self._choose_data_set)
            self.context_bar.add(data_group)
            self.setup_button = ttk.Button(
                self.context_bar,
                text="Setup",
                command=self._toggle_sidebar,
                style="Navigator.TButton",
            )
            self.context_bar.add(self.setup_button)
            zoom_group = ttk.Frame(self.context_bar)
            self._build_zoom(zoom_group)
            self.context_bar.add(zoom_group)
            self.sheet_selector.bind("<<ComboboxSelected>>", self._choose_sheet)
            self.selectors.append(self.sheet_selector)
            self.header_button = ttk.Button(
                self.navigator.header_actions,
                text="Use selected row as headers",
                command=self._use_header,
                state="disabled",
                style="Navigator.TButton",
            )
            self.header_button.pack(fill="x")
            self.toolbar = FlowBar(self.workspace)
            self.toolbar.grid(row=0, sticky="ew", pady=(0, 4))
            self._build_column_actions(self.toolbar)
            jump = ttk.Frame(self.toolbar)
            self.navigator.build_jump(jump)
            self.toolbar.add(jump)
            self.navigator.build_paging(self.workspace)
            self.navigator.paging.grid(row=3, sticky="ew", pady=(6, 0))
            self.navigator.set_busy(True)
            self.details_button = ttk.Button(
                title_actions,
                text="Reading details",
                command=self.navigator.show_details,
                style="Navigator.TButton",
            )
            self.details_button.pack(side="left")
            ttk.Label(self.navigator.details, text="Preview reader").pack(anchor="w")
            self.reader_selector = ttk.Combobox(
                self.navigator.details,
                textvariable=self.reader_name,
                values=("openpyxl", "Excel (xlwings)"),
                state="disabled",
                width=22,
            )
            self.reader_selector.pack(anchor="w", pady=(4, 12))
            self.reader_selector.bind("<<ComboboxSelected>>", self._change_reader)
            ttk.Label(
                self.navigator.details, textvariable=self.comparison_note, wraplength=710
            ).pack(anchor="w", pady=(0, 12))
            ttk.Label(self.navigator.details, textvariable=self.note, wraplength=710).pack(
                anchor="w"
            )
            for variable in (
                self.navigator.range_text,
                self.navigator.header_text,
                self.navigator.table_name,
            ):
                variable.trace_add("write", lambda *_: self._update_column_actions())
            self.comparison_note.trace_add("write", lambda *_: self._reader_summary())
            self._update_column_actions()
        else:
            options = ttk.Frame(self.workspace)
            options.grid(row=0, sticky="ew", pady=(0, 8))
            self.context_bar.grid_remove()
            options_row = options
            csv_controls = FlowBar(options)
            if self.path.suffix.lower() != ".xml":
                csv_controls.pack(fill="x")
            if self.path.suffix.lower() == ".xml":
                options_row = ttk.Frame(options)
                options_row.pack(fill="x")
                ttk.Label(options_row, text="Record group").pack(side="left", padx=(0, 6))
                self.xml_group_selector = ttk.Combobox(
                    options_row, textvariable=self.xml_group, state="readonly", width=20
                )
                self.xml_group_selector.pack(side="left", padx=(0, 16), fill="x", expand=True)
                self.selectors.append(self.xml_group_selector)
            for label, variable, values in (
                ("Separator", self.delimiter, tuple(DELIMITERS)),
                ("Encoding", self.encoding, tuple(ENCODINGS)),
            ):
                if self.path.suffix.lower() == ".xml":
                    continue
                group = ttk.Frame(csv_controls)
                ttk.Label(group, text=label, style="Muted.TLabel").pack(side="left", padx=(0, 6))
                selector = ttk.Combobox(
                    group, textvariable=variable, values=values, state="readonly", width=17
                )
                selector.pack(side="left")
                csv_controls.add(group)
                selector.bind("<<ComboboxSelected>>", self.load)
                self.selectors.append(selector)
            if self.path.suffix.lower() == ".xml":
                self._build_zoom(options_row)
            else:
                zoom_group = ttk.Frame(csv_controls)
                self._build_zoom(zoom_group)
                csv_controls.add(zoom_group)
            if self.xml_group_selector is not None:
                self.xml_navigation = XmlNavigator(
                    options, self.xml_group, self.load, self._update_column_actions
                )
                self.xml_navigation.build_paging(self.workspace)
                self.xml_group_selector.bind(
                    "<<ComboboxSelected>>", self.xml_navigation.choose_group
                )
                self.toolbar = FlowBar(self.xml_navigation.frame)
                self.toolbar.pack(fill="x", pady=(4, 0))
                self._build_column_actions(self.toolbar)
                self.xml_navigation.name.trace_add(
                    "write", lambda *_: self._update_column_actions()
                )
            reading_note = ttk.Label(
                self.workspace, textvariable=self.note, wraplength=850, style="Muted.TLabel"
            )
            reading_note.grid(row=5, sticky="ew", pady=(6, 0))
            reading_note.bind(
                "<Configure>",
                lambda event: reading_note.configure(wraplength=max(160, event.width - 8)),
            )

        self.status_label = ttk.Label(
            self.workspace, textvariable=self.status, wraplength=700, style="Muted.TLabel"
        )
        self.status_label.grid(row=1, sticky="ew", pady=(0, 8))
        grid = ttk.Frame(self.workspace)
        grid.grid(row=2, sticky="nsew")
        grid.columnconfigure(1, weight=1)
        grid.rowconfigure(0, weight=1)
        self.row_numbers = ttk.Treeview(
            grid, show="tree headings", selectmode="browse", style=self.grid_style
        )
        self.row_numbers.heading("#0", text="Row", anchor="w")
        self.row_numbers.column(
            "#0", width=max(55, self.grid_font.measure("1048576") + 12), minwidth=55, stretch=False
        )
        self.row_numbers.grid(row=0, column=0, sticky="ns")
        self.row_numbers.bind("<<TreeviewSelect>>", self._row_selection)
        self.row_numbers.bind("<MouseWheel>", self._row_wheel)
        self.table = ttk.Treeview(grid, show="headings", selectmode="browse", style=self.grid_style)
        self.table.tag_configure("boundary", background="#edf3f1")
        self.table.tag_configure("header", background="#dceee7")
        self.table.tag_configure("difference", background="#fff0c2")
        self.table.heading("#0", text="Row", anchor="w")
        self.table.column("#0", width=55, minwidth=55, stretch=False)
        self.table.grid(row=0, column=1, sticky="nsew")
        vertical = ttk.Scrollbar(
            grid, orient="vertical", command=self._scroll_rows, style="Slim.Vertical.TScrollbar"
        )
        vertical.grid(row=0, column=2, sticky="ns")
        self.vertical_scroll = vertical
        self._bind_scroll_jump(vertical, self._scroll_rows, vertical=True)
        horizontal = ttk.Scrollbar(
            grid,
            orient="horizontal",
            command=self._scroll_columns,
            style="Slim.Horizontal.TScrollbar",
        )
        horizontal.grid(row=1, column=1, sticky="ew")
        self.horizontal_scroll = horizontal
        self._bind_scroll_jump(horizontal, self._scroll_columns, vertical=False)
        self.table.bind("<MouseWheel>", self._row_wheel)
        for widget in (self.table, self.row_numbers):
            widget.bind("<Shift-MouseWheel>", self._column_wheel)

        def sync_rows(first: float, last: float) -> None:
            vertical.set(first, last)
            self.row_numbers.yview_moveto(float(first))
            self.column_highlight.refresh()

        self.grid_state = ttk.Frame(grid, padding=20)
        self.grid_state.columnconfigure(0, weight=1)
        self.state_title = ttk.Label(self.grid_state, text="Reading file…", font=(family, 14))
        self.state_title.grid(row=0, sticky="w")
        self.state_message = ttk.Label(self.grid_state, style="Muted.TLabel", wraplength=350)
        self.state_message.grid(row=1, sticky="w", pady=(8, 12))
        self.retry_button = ttk.Button(self.grid_state, text="Try again", command=self._retry)
        self.retry_button.grid(row=2, sticky="w")
        self.read_progress = ttk.Progressbar(self.grid_state, mode="indeterminate", length=150)
        self.read_progress.grid(row=3, sticky="w")
        grid.bind(
            "<Configure>",
            lambda event: self.state_message.configure(wraplength=max(120, event.width - 80)),
        )
        self.column_highlight = ColumnHighlight(self.table, self.grid_font, self.heading_font)

        def sync_columns(first: float, last: float) -> None:
            horizontal.set(first, last)
            self.column_highlight.refresh()

        self.table.configure(yscrollcommand=sync_rows, xscrollcommand=sync_columns)
        self.table.bind("<ButtonRelease-1>", self._cell_click)
        self.table.bind("<<TreeviewSelect>>", self._selection)
        self.table.bind("<Left>", lambda event: self._move_column(-1))
        self.table.bind("<Right>", lambda event: self._move_column(1))
        if self.navigator:
            self.cell_menu = tk.Menu(self.frame, tearoff=False)
            self.cell_menu.add_command(
                label="Set data set start here", command=lambda: self._set_corner(False)
            )
            self.cell_menu.add_command(
                label="Set data set end here", command=lambda: self._set_corner(True)
            )
            self.table.bind("<Button-3>", self._cell_menu)
        cell_bar = ttk.Frame(self.workspace)
        cell_bar.grid(row=4, sticky="ew", pady=(6, 0))
        cell_bar.columnconfigure(0, weight=1)
        self.value_label = ttk.Label(cell_bar, textvariable=self.cell_summary, wraplength=500)
        self.value_label.grid(row=0, column=0, sticky="ew")
        self.detail_button = ttk.Button(
            cell_bar, text="Cell details", command=self._toggle_detail, style="Navigator.TButton"
        )
        self.detail_button.grid(row=0, column=1, sticky="e", padx=(8, 0))
        self.detail_frame = ttk.Frame(self.workspace)
        self.detail_frame.columnconfigure(0, weight=1)
        self.cell_text = tk.Text(
            self.detail_frame,
            height=4,
            wrap="word",
            state="disabled",
            relief="flat",
            padx=8,
            pady=6,
        )
        self.cell_text.grid(row=0, column=0, sticky="ew")
        detail_scroll = ttk.Scrollbar(
            self.detail_frame,
            orient="vertical",
            command=self.cell_text.yview,
            style="Slim.Vertical.TScrollbar",
        )
        detail_scroll.grid(row=0, column=1, sticky="ns")
        self.cell_text.configure(yscrollcommand=detail_scroll.set)
        footer = ttk.Frame(page)
        footer.grid(row=3, sticky="ew", pady=(8, 0))
        self.session_label = ttk.Label(footer, text=self.session.date_label, style="Muted.TLabel")
        footer.columnconfigure(0, weight=1)
        self.session_label.grid(row=0, column=1, sticky="e", padx=(12, 0))
        self.reader_status_label = ttk.Label(
            footer, textvariable=self.reader_status, style="Muted.TLabel"
        )
        self.reader_status_label.grid(row=0, column=0, sticky="w")
        footer.bind(
            "<Configure>",
            lambda event: self.reader_status_label.configure(
                wraplength=max(160, event.width - self.session_label.winfo_reqwidth() - 20)
            ),
        )
        self.workspace.bind(
            "<Configure>",
            lambda event: (
                self.status_label.configure(wraplength=max(200, event.width - 20)),
                self.value_label.configure(wraplength=max(160, event.width - 125)),
            ),
        )

    def _fit_filename(self, width: int) -> None:
        full = self.path.name
        width = max(80, width)
        if self.title_font.measure(full) <= width:
            self.filename_label.configure(text=full)
            return
        stem, suffix = self.path.stem, "…" + self.path.suffix
        while stem and self.title_font.measure(stem + suffix) > width:
            stem = stem[:-1]
        self.filename_label.configure(text=stem + suffix)

    def _build_column_actions(self, toolbar: FlowBar) -> None:
        self.workflow_hint_group = ttk.Frame(toolbar)
        ttk.Label(
            self.workflow_hint_group,
            textvariable=self.workflow_hint,
            style="Muted.TLabel",
        ).pack(side="left")
        toolbar.add(self.workflow_hint_group)
        self.column_actions = ttk.Frame(toolbar)
        actions = []
        if self.path.suffix.lower() in {".xlsx", ".xlsm"}:
            actions.append(("definition_button", "Define column", self.define_column))
        actions.extend(
            (
                ("column_button", "Inspect column", self.inspect_column),
                ("check_button", "Check column", self.check_column),
            )
        )
        for attr, label, command in actions:
            button = ttk.Button(
                self.column_actions,
                text=label,
                command=command,
                state="disabled",
                style="Navigator.TButton",
            )
            button.pack(side="left", padx=(0, 6))
            setattr(self, attr, button)
        toolbar.add(self.column_actions)
        if self.path.suffix.lower() in {".xlsx", ".xlsm"}:
            self.date_actions = ttk.Frame(toolbar)
            self.date_button = ttk.Button(
                self.date_actions,
                text="Date workflow",
                command=self.open_date_workflow,
                state="disabled",
                style="Navigator.TButton",
            )
            self.date_button.pack(side="left")
            toolbar.add(self.date_actions)

    def _sync_context(self) -> None:
        if not self.navigator:
            return
        nav = self.navigator
        self.data_selector.configure(
            values=tuple(table.name for table in nav.tables),
            state="readonly" if nav.tables and not self.busy else "disabled",
        )
        self.data_selector.set(
            next(
                (table.name for table in nav.tables if table.id == nav.editing_id),
                "Unsaved data set",
            )
        )
        self.setup_button.configure(
            text=("Unsaved setup" if nav.has_unsaved_setup() else "Setup")
            if self.sidebar_collapsed
            else "Hide setup"
        )

    def _allow_context_switch(self) -> bool:
        return (
            not self.navigator
            or not self.navigator.has_unsaved_setup()
            or messagebox.askokcancel(
                "Discard unsaved setup?",
                "Discard the edited data set setup? Use Save data set to keep it.",
                parent=self.frame,
            )
        )

    def _choose_sheet(self, event: tk.Event[tk.Misc]) -> None:
        if not self.navigator or self.busy:
            return
        chosen = self.sheet_name.get()
        if self.navigator.current:
            self.sheet_name.set(self.navigator.current.name)
        if self._allow_context_switch():
            self.sheet_name.set(chosen)
            self.load(event)

    def _choose_data_set(self, event: tk.Event[tk.Misc] | None = None) -> None:
        if self.navigator and not self.busy and self.data_selector.current() >= 0:
            if not self._allow_context_switch():
                self._sync_context()
                return
            self.navigator.table_selector.current(self.data_selector.current())
            self.navigator.choose_table()

    def _setup_changed(self, editing: bool) -> None:
        self._set_sidebar(not editing)

    def _set_sidebar(self, collapsed: bool) -> None:
        self.sidebar_collapsed = collapsed
        if collapsed:
            self.rail.grid_remove()
            self.sidebar_toggle.configure(text="▶")
        else:
            self.rail.grid()
            self.sidebar_toggle.configure(text="◀")
        self._sync_context()

    def _toggle_sidebar(self) -> None:
        self._set_sidebar(not self.sidebar_collapsed)

    def _show_grid_state(
        self, title: str = "", message: str = "", *, busy: bool = False, retry: bool = False
    ) -> None:
        self.read_progress.stop()
        if not title:
            self.grid_state.place_forget()
            return
        self.state_title.configure(text=title, foreground=ERROR if retry else ACCENT)
        self.state_message.configure(text=message)
        self.retry_button.grid() if retry else self.retry_button.grid_remove()
        if busy:
            self.read_progress.grid()
            self.read_progress.start(15)
        else:
            self.read_progress.grid_remove()
        self.grid_state.place(relx=0.5, rely=0.45, anchor="center", relwidth=0.9)
        self.grid_state.lift()

    def _retry(self) -> None:
        if self.busy or self.closed:
            return
        if self.navigator and self.navigator.index is None:
            self._discover()
        else:
            self.load()

    def _scroll_rows(self, *args: str) -> None:
        self.table.yview(*args)
        self.row_numbers.yview(*args)

    @staticmethod
    def _bind_scroll_jump(
        scrollbar: ttk.Scrollbar, command: Callable[..., object], *, vertical: bool
    ) -> None:
        def jump(event: tk.Event[tk.Misc]) -> str | None:
            if "trough" not in scrollbar.identify(event.x, event.y):
                return None  # Keep native dragging and arrow behavior.
            coordinate = event.y if vertical else event.x
            length = scrollbar.winfo_height() if vertical else scrollbar.winfo_width()
            view = scrollbar.get()
            first, last = view[0], view[1]
            # Center the visible region on the clicked track location.
            fraction = (coordinate - 10) / max(1, length - 20) - (last - first) / 2
            command("moveto", str(max(0.0, min(1.0, fraction))))
            return "break"

        scrollbar.bind("<Button-1>", jump)

    def _wheel_units(self, delta: int, axis: str, speed: int) -> int:
        amount = self.wheel_remainder[axis] - delta / 120 * speed
        whole = int(amount)
        self.wheel_remainder[axis] = amount - whole
        return whole

    def _scroll_columns(self, *args: str) -> None:
        if args[0] == "scroll" and args[2] == "units":
            self.table.xview_scroll(int(args[1]) * 3, "units")
        else:
            self.table.xview(*args)

    def _row_wheel(self, event: tk.Event[tk.Misc]) -> str:
        steps = self._wheel_units(event.delta, "rows", 3)
        if steps:
            self._scroll_rows("scroll", str(steps), "units")
        return "break"

    def _column_wheel(self, event: tk.Event[tk.Misc]) -> str:
        steps = self._wheel_units(event.delta, "columns", 3)
        if steps:
            self.table.xview_scroll(steps, "units")
        return "break"

    def _row_selection(self, event: tk.Event[tk.Misc]) -> None:
        selected = self.row_numbers.selection()
        if selected and selected != self.table.selection():
            self.table.selection_set(selected)
            self.table.see(selected[0])

    def _build_zoom(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="Zoom").pack(side="left", padx=(14, 5))
        self.zoom_selector = ttk.Combobox(
            parent,
            textvariable=self.zoom,
            values=("15%", "20%", "25%", "35%", "50%", "65%", "80%", "100%", "125%"),
            width=5,
            state="readonly",
        )
        self.zoom_selector.pack(side="left")
        self.zoom_selector.bind("<<ComboboxSelected>>", self._apply_zoom)

    def _apply_zoom(self, event: tk.Event[tk.Misc] | None = None) -> None:
        ratio = int(self.zoom.get().rstrip("%")) / 100
        self.grid_font.configure(size=max(1, round(11 * ratio)))
        self.heading_font.configure(size=max(1, round(11 * ratio)))
        self.row_numbers.column("#0", width=max(55, self.grid_font.measure("1048576") + 12))
        style = ttk.Style(self.frame)
        style.configure(
            self.grid_style,
            rowheight=self.grid_font.metrics("linespace") + max(1, round(4 * ratio)),
        )
        style.configure(
            self.grid_style + ".Heading",
            padding=(max(1, round(4 * ratio)), max(1, round(3 * ratio))),
        )
        self.column_width = max(1, round(145 * ratio))
        for column in self.table["columns"]:
            self.table.column(column, width=self.column_width)
        self.column_highlight.refresh()

    def _cell_menu(self, event: tk.Event[tk.Misc]) -> None:
        if self.busy or self.preview is None:
            return
        row = self.table.identify_row(event.y)
        column = self.table.identify_column(event.x)
        if not row or not column or column == "#0":
            return
        self.table.selection_set(row)
        self._select_column(int(column[1:]) - 1)
        try:
            self.cell_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.cell_menu.grab_release()

    def _set_corner(self, end: bool) -> None:
        selected = self.table.selection()
        if self.navigator and self.preview and selected and not self.busy:
            self.navigator.set_corner(
                int(selected[0]), self.preview.start_column + self.active_column, end=end
            )

    def _open_in_excel(self) -> None:
        if self.closed or self.path.suffix.lower() == ".xml":
            return
        try:
            open_in_excel(self.path)
        except (OSError, InspectionError) as error:
            messagebox.showerror("Could not open Excel", str(error), parent=self.frame)

    def _reader_summary(self) -> None:
        message = self.comparison_note.get()
        if not message:
            self.reader_status.set("Read-only · Original file preserved")
        elif "Reading with" in message:
            self.reader_status.set("Comparing readers...")
        elif self.comparison and self.comparison.secondary is not None:
            self.reader_status.set(
                "Reader differences - see Reading details"
                if self.comparison.differences
                else "Readers agree on this preview"
            )
        else:
            self.reader_status.set("Excel comparison skipped or unavailable - see Reading details")

    def _toggle_detail(self) -> None:
        if self.detail_frame.winfo_manager():
            self.detail_frame.grid_remove()
            self.detail_button.configure(text="Cell details")
        else:
            self.detail_frame.grid(row=6, sticky="ew", pady=(6, 0))
            self.detail_button.configure(text="Hide details")

    def _update_column_actions(self) -> None:
        controller = self.navigator or self.xml_navigation
        if controller is None:
            return
        try:
            controller.table_for_inspection()
            saved = True
        except InspectionError:
            saved = False
        self.toolbar.show(self.column_actions, True)
        if self.date_actions is not None:
            self.toolbar.show(self.date_actions, saved and not self.busy)
        if self.date_button is not None:
            state = "normal" if saved and not self.busy else "disabled"
            self.date_button.configure(state=state)
        if self.busy:
            hint = "Loading review tools…"
        elif not saved:
            hint = "Next: save the data set."
        elif not self.column_selected:
            hint = "Next: select a column heading."
        else:
            hint = "Ready: choose a review action."
        self.workflow_hint.set(hint)
        self._sync_context()
        for button in (self.definition_button, self.column_button, self.check_button):
            if button:
                button.configure(
                    state="normal"
                    if saved and self.column_selected and not self.busy
                    else "disabled"
                )

    def _discover(self) -> None:
        self.busy = True
        self._update_column_actions()
        self.status.set("Scanning the complete workbook…")
        self._show_grid_state(
            "Finding your data…",
            "Reading every worksheet, including hidden rows and columns.",
            busy=True,
        )
        for selector in self.selectors:
            selector.configure(state="disabled")

        def discover() -> None:
            try:
                self.results.put(
                    scan_workbook(self.path, cancelled=self.cancelled, progress=self.results.put)
                )
            except Exception as error:
                self.results.put(error)

        self.workers.start(discover, "workbook-discovery", self.cancelled)

    def load(self, event: tk.Event[tk.Misc] | None = None) -> None:
        if self.busy or self.closed:
            return
        mapping_table: SavedTable | None = None
        if self.navigator:
            self.navigator.set_profile_match(None)
            if self.navigator.index is None:
                return
            if event is not None:
                self.navigator.select_sheet(self.sheet_name.get())
            if self.navigator.current and self.navigator.current.error:
                self.comparison = None
                if self.reader_selector is not None:
                    self.reader_selector.configure(state="disabled")
                self.preview = None
                self.table.delete(*self.table.get_children())
                self.row_numbers.delete(*self.row_numbers.get_children())
                self._detail("")
                self.note.set("")
                self.comparison_note.set("")
                self.status.set(self.navigator.current.error)
                self.status_label.configure(foreground=ERROR)
                self._show_grid_state("This sheet could not be read", self.navigator.current.error)
                self._update_column_actions()
                return
            self.navigator.set_busy(True)
            try:
                mapping_table = self.navigator.table_for_inspection()
            except InspectionError:
                pass
        self.busy = True
        if self.xml_navigation:
            self.xml_navigation.set_busy(True)
        self._sync_context()
        self.column_highlight.select(None)
        self.preview = None
        self.column_selected = False
        if self.column_button:
            self.column_button.configure(state="disabled", text="Inspect column")
        if self.check_button:
            self.check_button.configure(state="disabled", text="Check column")
        if self.xsd_button:
            self.xsd_button.configure(state="disabled")
        self.headers = ()
        if self.header_button:
            self.header_button.configure(state="disabled", text="Use selected row as headers")
        self.comparison = None
        self.reader_name.set("openpyxl")
        self.comparison_note.set("")
        if self.reader_selector is not None:
            self.reader_selector.configure(state="disabled")
            self.comparison_note.set("Reading with openpyxl and checking the Excel comparison…")
        self.table.delete(*self.table.get_children())
        self.row_numbers.delete(*self.row_numbers.get_children())
        self.table.configure(columns=())
        self._detail("")
        self.note.set("")
        self.status.set("Reading file…")
        self.status_label.configure(foreground=MUTED)
        self._show_grid_state("Reading your data…", "Your saved copy stays unchanged.", busy=True)
        if self.navigator or self.xml_navigation:
            self._update_column_actions()
        for selector in self.selectors:
            selector.configure(state="disabled")
        path, results = self.path, self.results
        sheet = self.sheet_name.get() or None
        encoding, delimiter = self.encoding.get(), self.delimiter.get()
        xml_group = self.xml_group.get() or None
        xml_row = self.xml_navigation.row if self.xml_navigation else 1
        xml_column = self.xml_navigation.column if self.xml_navigation else 1
        xml_group_path = self.xml_navigation.group_path if self.xml_navigation else None
        xml_sha256 = self.xml_navigation.source_sha256 if self.xml_navigation else None
        area = self.navigator.page_area if self.navigator else None
        header_row = self.navigator.header_row if self.navigator else None

        def read() -> None:
            try:
                data: FilePreview | ComparedPreview
                if path.suffix.lower() == ".xml":
                    data = read_preview(
                        path,
                        xml_group=xml_group,
                        cancelled=self.cancelled,
                        xml_start_row=xml_row,
                        xml_start_column=xml_column,
                        xml_group_path=xml_group_path,
                        xml_source_sha256=xml_sha256,
                    )
                else:
                    data = read_parallel_preview(
                        path,
                        sheet=sheet,
                        encoding=encoding,
                        delimiter=delimiter,
                        cancelled=self.cancelled,
                        area=area,
                    )
                headers: tuple[PreviewCell, ...] = ()
                if header_row is not None and area is not None and not self.cancelled.is_set():
                    primary = data.primary if isinstance(data, ComparedPreview) else data
                    offset = header_row - primary.start_row
                    if 0 <= offset < len(primary.rows):
                        headers = primary.rows[offset]
                    else:
                        header_preview = read_preview(
                            path,
                            sheet=sheet,
                            cancelled=self.cancelled,
                            area=CellRange(
                                header_row, area.min_column, header_row, area.max_column
                            ),
                        )
                        headers = header_preview.rows[0]
                profile_match = (
                    match_builtin_table_profile(path, mapping_table, cancelled=self.cancelled)
                    if mapping_table is not None and not self.cancelled.is_set()
                    else None
                )
                results.put(LoadedPreview(data, headers, profile_match))
            except Exception as error:
                results.put(error)

        # Keep cleanup tracked even after this preview tab has been closed.
        self.workers.start(read, "file-preview", self.cancelled)

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
            for selector in self.selectors:
                selector.configure(state="readonly")
            if self.navigator:
                self.navigator.set_busy(False)
            if isinstance(result, WorkbookIndex):
                assert self.navigator is not None
                self.navigator.set_index(result)
                self.sheet_selector.configure(values=tuple(sheet.name for sheet in result.sheets))
                self.load()
            elif isinstance(result, Exception):
                if self.xml_navigation:
                    self.xml_navigation.read_failed()
                self.pending_cell = None
                if isinstance(result, InspectionError):
                    message = str(result)
                elif isinstance(result, FileNotFoundError):
                    message = "The saved copy could not be found. Add the file again."
                elif isinstance(result, PermissionError):
                    message = "The saved copy could not be opened. Check file access."
                else:
                    message = "Could not read this file. It may be damaged, password-protected, or saved in a different format."
                if self.navigator and self.navigator.index is None:
                    self.navigator.coverage.set(
                        "Scan incomplete. No workbook coverage has been established."
                    )
                self.comparison_note.set("")
                self.status.set(message)
                self.status_label.configure(foreground=ERROR)
                self._show_grid_state("Could not open this preview", message, retry=True)
                self._sync_context()
            else:
                self.headers = result.headers
                if self.navigator:
                    self.navigator.set_profile_match(result.profile_match)
                if isinstance(result.data, ComparedPreview):
                    self.comparison = result.data
                    self.comparison_note.set(result.data.message)
                    if self.reader_selector is not None and result.data.secondary is not None:
                        self.reader_selector.configure(state="readonly")
                    self._show(result.data.primary)
                else:
                    self._show(result.data)
            break
        self._update_xsd_action()
        self.poll_id = self.frame.after(80, self._poll)

    def _change_reader(self, event: tk.Event[tk.Misc] | None = None) -> None:
        if self.comparison is None:
            return
        preview = (
            self.comparison.secondary
            if self.reader_name.get() == "Excel (xlwings)"
            else self.comparison.primary
        )
        if preview is not None:
            self._show(preview)

    def _show(self, preview: FilePreview) -> None:
        self.column_highlight.select(None)
        self.table.delete(*self.table.get_children())
        self.row_numbers.delete(*self.row_numbers.get_children())
        self._detail("")
        self.preview = preview
        self._show_grid_state()
        self.status_label.configure(foreground=MUTED)
        if self.xml_group_selector is not None:
            self.xml_group_selector.configure(values=preview.record_groups)
            self.xml_group.set(preview.selected_record_group or "")
            self.headers = tuple(PreviewCell(label) for label in preview.column_labels)
            if self.xml_navigation and self.xml_navigation.accept(preview):
                return
            self.sheet_name.set(preview.selected_record_group or "")
        self.active_column = 0
        self.column_selected = False
        if self.column_button:
            self.column_button.configure(state="disabled", text="Inspect column")
        if self.check_button:
            self.check_button.configure(state="disabled", text="Check column")
        if preview.sheets:
            if not self.navigator:
                self.sheet_selector.configure(values=preview.sheets)
            self.sheet_name.set(preview.selected_sheet or "")
        columns = tuple(
            column_label(i)
            for i in range(preview.start_column, preview.start_column + preview.column_count)
        )
        self.table.configure(columns=columns)
        for offset, column in enumerate(columns):
            label = column
            if self.headers:
                value = self.headers[offset].text if offset < len(self.headers) else ""
                value = value.replace("\r", "\\r").replace("\n", "\\n").replace("\t", "\\t")
                label += " · " + (
                    (value[:80] + "…" if len(value) > 80 else value) or "[blank header]"
                )
            self.table.heading(
                column,
                text=label,
                anchor="w",
                command=partial(self._select_column, offset, entire=True),
            )
            self.table.column(column, width=self.column_width, minwidth=1, stretch=False)
        changed_rows = {row for row, _ in self.comparison.differences} if self.comparison else set()
        for number, row in enumerate(preview.rows, preview.start_row):
            self.row_numbers.insert("", "end", iid=str(number), text=str(number))
            values = [
                cell.text.replace("\r", "\\r").replace("\n", "\\n").replace("\t", "\\t")
                for cell in row
            ]
            # Keep the grid compact; the detail panel retains the complete cell value.
            values = [value[:200] + "…" if len(value) > 200 else value for value in values]
            self.table.insert(
                "",
                "end",
                iid=str(number),
                text=str(number),
                values=values,
                tags=(
                    *(
                        ("header",)
                        if self.navigator and number == self.navigator.header_row
                        else ()
                    ),
                    *(
                        ("boundary",)
                        if self.navigator
                        and self.navigator.area
                        and number in {self.navigator.area.min_row, self.navigator.area.max_row}
                        else ()
                    ),
                    *(("difference",) if number - preview.start_row in changed_rows else ()),
                ),
            )
        count = len(preview.rows)
        text = f"Showing {count} rows × {preview.column_count} columns."
        if preview.more_rows or preview.more_columns:
            text += " More data exists beyond this preview."
        elif count == 0:
            text = "No rows to display."
        if preview.record_groups:
            if preview.record_group_error:
                text = "Cannot preview this record group. " + preview.record_group_error
                self.status_label.configure(foreground="#a1342d")
            elif preview.selected_record_group is None:
                text = "Choose a record group above to display its rows and columns."
            else:
                text = (
                    f"Selected group: {preview.record_count:,} records × {preview.field_count:,} fields. "
                    f"Viewing records {preview.start_row:,}–{preview.start_row + count - 1:,}, "
                    f"fields {preview.start_column:,}–{preview.start_column + preview.column_count - 1:,}."
                )
        if self.navigator and self.navigator.page_area and self.navigator.area:
            page, area = self.navigator.page_area, self.navigator.area
            below = "More rows below" if page.max_row < area.max_row else "Bottom reached"
            right = (
                "More columns right" if page.max_column < area.max_column else "Right edge reached"
            )
            text = f"{self.navigator.boundary_text.get()}\nViewing {page.address}  |  {below}  |  {right}"
            if self.navigator.index and not self.navigator.index.complete:
                text += "  |  INCOMPLETE SCAN - see Find data areas"
        self.status.set(text)
        if not preview.rows:
            self._show_grid_state(
                "Choose a record group"
                if preview.record_groups and not preview.selected_record_group
                else "No data to display",
                text,
            )
        self.note.set(preview.reading_note)
        self._update_column_actions()
        if self.navigator and self.navigator.edge_view:
            edge = 1.0 if self.navigator.edge_view == "end" else 0.0
            self.table.yview_moveto(edge)
            self.table.xview_moveto(edge)
        if self.whole_column:
            sheet, scope, selected_source_column = self.whole_column
            current_scope = self.navigator.area if self.navigator else None
            if sheet != self.sheet_name.get() or scope != current_scope:
                self.whole_column = None
            elif (
                preview.start_column
                <= selected_source_column
                < preview.start_column + preview.column_count
            ):
                self._select_column(selected_source_column - preview.start_column, entire=True)
        if self.pending_cell:
            target_row, target_column = self.pending_cell
            self.pending_cell = None
            if self.table.exists(str(target_row)):
                self.table.selection_set(str(target_row))
                self.table.see(str(target_row))
                self._select_column(target_column - preview.start_column)

    def _select_column(self, index: int, *, entire: bool = False) -> None:
        if self.busy or self.preview is None or not 0 <= index < self.preview.column_count:
            return
        self.active_column = index
        self.column_selected = True
        column = self.preview.start_column + index
        if entire:
            self.whole_column = (
                self.sheet_name.get(),
                self.navigator.area if self.navigator else None,
                column,
            )
            self.table.selection_remove(*self.table.selection())
            self.row_numbers.selection_remove(*self.row_numbers.selection())
            self.column_highlight.select(column_label(column))
        else:
            self.whole_column = None
            self.column_highlight.select(None)
        if self.column_button:
            self.column_button.configure(
                state="normal",
                text=f"Inspect column {column_label(self.preview.start_column + index)}",
            )
        if self.check_button:
            self.check_button.configure(
                state="normal",
                text=f"Check column {column_label(self.preview.start_column + index)}",
            )
        if self.definition_button:
            self.definition_button.configure(
                state="normal",
                text=f"Define column {column_label(self.preview.start_column + index)}",
            )
        self._update_column_actions()
        if self.table.selection():
            self._selection()
        else:
            header = self.table.heading(column_label(self.preview.start_column + index), "text")
            action = "Click a cell for its full value."
            if self.navigator and self.navigator.area:
                area = self.navigator.area
                letter = column_label(column)
                action = (
                    f"Entire data set column: {letter}{area.min_row}:{letter}{area.max_row}. "
                    "Inspect and Check use all data rows after saving."
                )
            elif self.xml_navigation and self.preview:
                action = f"Entire XML field: records 1–{self.preview.record_count:,}. Inspect and Check use every record after saving."
            self._detail(f"Selected column: {header}. {action}")

    def define_column(self) -> None:
        if self.busy or self.preview is None or not self.column_selected or self.navigator is None:
            return
        try:
            table = self.navigator.table_for_inspection()
        except InspectionError as error:
            self.navigator.message.set(str(error))
            return
        if self.column_definition is not None and not self.column_definition.closed:
            self.column_definition.window.lift()
            self.column_definition.window.focus_set()
            return
        column = self.preview.start_column + self.active_column
        header = (
            self.headers[self.active_column].text if self.active_column < len(self.headers) else ""
        )
        self.column_definition = ColumnDefinitionWindow(
            self.frame,
            table,
            column,
            header,
            self.pack_store,
            self._update_column_actions,
        )

    def inspect_column(self) -> None:
        controller = self.navigator or self.xml_navigation
        if self.busy or self.preview is None or not self.column_selected or controller is None:
            return
        try:
            table = controller.table_for_inspection()
        except InspectionError as error:
            controller.message.set(str(error))
            return
        column = self.preview.start_column + self.active_column
        if self.column_inspector and not self.column_inspector.closed:
            self.column_inspector.window.lift()
            return
        self.column_inspector = ColumnWindow(
            self.frame,
            self.path,
            table,
            column,
            self.session,
            lambda row: self._jump_to_column_row(table, column, row),
            self.workers,
        )

    def order_scope(self) -> OrderScope:
        """Return the saved data set and currently selected ordering column."""
        if self.path.suffix.lower() == ".csv":
            raise InspectionError(
                "Ordering currently requires a saved Excel or XML data set. "
                "CSV data-set setup is not available yet."
            )
        controller = self.navigator or self.xml_navigation
        if self.busy or self.preview is None:
            raise InspectionError("Wait for the analysis preview to finish loading.")
        if not self.column_selected or controller is None:
            raise InspectionError(
                "On the analysis tab, select a column in a saved data set, then return here."
            )
        table = controller.table_for_inspection()
        column = self.preview.start_column + self.active_column
        identifier = column_label(column)
        heading = str(self.table.heading(identifier, "text"))
        return OrderScope(table, column, heading or f"Column {identifier}")

    def open_date_workflow(self) -> None:
        if self.busy or self.navigator is None or self.preview is None:
            return
        try:
            table = self.navigator.table_for_inspection()
        except InspectionError as error:
            self.navigator.message.set(str(error))
            return
        if self.date_workflow is not None and not self.date_workflow.closed:
            self.date_workflow.window.lift()
            self.date_workflow.window.focus_set()
            return
        header_by_column = {
            self.preview.start_column + index: cell.text for index, cell in enumerate(self.headers)
        }
        columns = tuple(
            (
                column,
                f"{column_label(column)} | "
                + (header_by_column.get(column, "").strip() or "No saved header"),
            )
            for column in range(
                table.selection.area.min_column, table.selection.area.max_column + 1
            )
        )
        self.date_workflow = DateWorkflowWindow(
            self.frame,
            self.path,
            table,
            columns,
            self.session,
            self.pack_store,
            self._jump_to_column_row,
            self.workers,
        )

    def _update_xsd_action(self) -> None:
        if self.xsd_button is not None:
            self.xsd_button.configure(
                state=(
                    "normal"
                    if self.preview is not None
                    and self.preview.source_sha256 is not None
                    and not self.busy
                    and not self.closed
                    else "disabled"
                )
            )

    def validate_xsd(self) -> None:
        if (
            self.busy
            or self.closed
            or self.preview is None
            or self.preview.source_sha256 is None
            or self.xsd_button is None
        ):
            return
        if self.xsd_validator is not None and not self.xsd_validator.closed:
            self.xsd_validator.window.lift()
            self.xsd_validator.window.focus_set()
            return
        selected = filedialog.askopenfilename(
            parent=self.owner,
            title="Choose the XSD for this XML file",
            initialdir=str(
                self.last_xsd_path.parent if self.last_xsd_path is not None else self.path.parent
            ),
            filetypes=(("XML Schema", "*.xsd"), ("All files", "*.*")),
        )
        if not selected:
            return
        self.last_xsd_path = Path(selected)
        self.xsd_validator = XsdValidationWindow(
            self.frame,
            self.path,
            self.last_xsd_path,
            self.preview.source_sha256,
            self.workers,
        )

    def check_column(self) -> None:
        controller = self.navigator or self.xml_navigation
        if self.busy or self.preview is None or not self.column_selected or controller is None:
            return
        try:
            table = controller.table_for_inspection()
        except InspectionError as error:
            controller.message.set(str(error))
            return
        column = self.preview.start_column + self.active_column
        if self.column_checker and not self.column_checker.closed:
            self.column_checker.window.lift()
            return
        self.column_checker = ColumnCheckWindow(
            self.frame,
            self.path,
            table,
            column,
            self.session,
            lambda row: self._jump_to_column_row(table, column, row),
            self.workers,
        )

    def _jump_to_column_row(self, table: ColumnTable, column: int, row: int) -> None:
        controller = self.navigator or self.xml_navigation
        if self.closed or self.busy or controller is None:
            raise InspectionError("Wait for the file preview to finish before jumping to a cell.")
        if controller.table_for_inspection() != table:
            raise InspectionError("The data set changed. Inspect the column again before jumping.")
        if isinstance(table, SavedXmlTable):
            assert self.xml_navigation is not None
            if not 1 <= row <= table.record_count or not 1 <= column <= table.field_count:
                raise InspectionError("Choose a record and field inside the XML group.")
            self.xml_navigation.row, self.xml_navigation.column = row, column
        else:
            assert self.navigator is not None
            self.navigator.page_area = table.selection.area.page(row, column)
        self.pending_cell = (row, column)
        self.load()
        self.activate()

    def _use_header(self) -> None:
        selected = self.table.selection()
        if self.navigator and not self.busy and self.preview and selected:
            self.navigator.set_header_row(int(selected[0]))

    def _cell_click(self, event: tk.Event[tk.Misc]) -> None:
        column = self.table.identify_column(event.x)
        row = self.table.identify_row(event.y)
        if row and column and column != "#0":
            self.table.selection_set(row)
            self._select_column(int(column[1:]) - 1)

    def _move_column(self, direction: int) -> str:
        if self.preview:
            self._select_column(
                max(0, min(self.preview.column_count - 1, self.active_column + direction)),
                entire=self.whole_column is not None,
            )
        return "break"

    def _selection(self, event: tk.Event[tk.Misc] | None = None) -> None:
        selection = self.table.selection()
        if selection and self.whole_column is not None:
            self.whole_column = None
            self.column_highlight.select(None)
        if selection != self.row_numbers.selection():
            self.row_numbers.selection_set(selection)
        if self.header_button:
            self.header_button.configure(
                text=f"Use row {selection[0]} as headers"
                if selection
                else "Use selected row as headers",
                state="normal" if self.preview and selection and not self.busy else "disabled",
            )
        if not self.preview or not selection:
            return
        number = int(selection[0])
        row_index = number - self.preview.start_row
        row = self.preview.rows[row_index]
        label = f"{column_label(self.preview.start_column + self.active_column)}{number}"
        if self.active_column >= len(row):
            self._detail(f"{label} · No field at this position in this record.")
            return
        cell = row[self.active_column]
        text = f"{label}\n{cell.text}" if cell.text else f"{label} · Empty cell"
        if self.headers and self.active_column < len(self.headers) and self.navigator:
            header = self.headers[self.active_column]
            address = f"{column_label(self.preview.start_column + self.active_column)}{self.navigator.header_row}"
            text += f"\nColumn header ({address}): {header.text or '[blank header]'}"
        if cell.source_path is not None:
            field = self.preview.column_labels[self.active_column]
            text = f"Record {number} · {field}\n{cell.text}\nState: {cell.presence}\nSource: {cell.source_path}"
        if cell.formula:
            text += f"\nFormula: {cell.formula}\nSaved results may be out of date."
        if cell.number_format and cell.number_format != "General":
            text += f"\nExcel number format: {cell.number_format}"
        if self.comparison and (row_index, self.active_column) in self.comparison.differences:
            for name, preview in (
                ("openpyxl", self.comparison.primary),
                ("Excel (xlwings)", self.comparison.secondary),
            ):
                if preview is None or row_index >= len(preview.rows):
                    value = "[no field]"
                elif self.active_column >= len(preview.rows[row_index]):
                    value = "[no field]"
                else:
                    value = preview.rows[row_index][self.active_column].text or "[empty]"
                text += f"\n{name}: {value}"
        self._detail(text)

    def _detail(self, text: str) -> None:
        summary = " | ".join(text.splitlines()[:2])
        self.cell_summary.set(
            (summary[:140] + "..." if len(summary) > 140 else summary)
            or "Click a cell to see its value."
        )
        self.cell_text.configure(state="normal")
        self.cell_text.delete("1.0", "end")
        self.cell_text.insert("1.0", text)
        self.cell_text.configure(state="disabled")

    def set_active(self, active: bool) -> None:
        # The optional workbook-details window belongs to this tab.
        if self.navigator is None:
            return
        details = self.navigator.overview_window
        if not active and details.state() != "withdrawn":
            self.details_were_visible = True
            details.withdraw()
        elif active and self.details_were_visible:
            self.details_were_visible = False
            details.deiconify()

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.read_progress.stop()
        self.cancelled.set()
        if self.column_inspector is not None:
            self.column_inspector.close()
        if self.column_checker is not None:
            self.column_checker.close()
        if self.column_definition is not None:
            self.column_definition.close()
        if self.date_workflow is not None:
            self.date_workflow.close()
        if self.xsd_validator is not None:
            self.xsd_validator.close()
        self.frame.after_cancel(self.poll_id)
        self.column_highlight.close()
        if self.wheel_binding is not None:
            self.owner.unbind("<MouseWheel>", self.wheel_binding)
        self.frame.destroy()
        self.on_close()
