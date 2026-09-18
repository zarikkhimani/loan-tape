"""Guided desktop workflow with separate date standardization and red-flag phases."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from datetime import date
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Any

from loan_tape.date_analysis import DateBinding, DatePair, analyze_standardized_dates
from loan_tape.date_calendar import CalendarSnapshot
from loan_tape.date_export import DateExport, export_date_run
from loan_tape.date_runs import SavedDateRun, save_date_run
from loan_tape.date_standardization import DateMapping, DateStandardization, standardize_excel_dates
from loan_tape.date_workflow import (
    LOAN_DATE_FIELDS,
    CalendarSetting,
    MappingSetting,
    PairSetting,
    ReviewSetting,
    build_red_flag_inputs,
    build_standardization_inputs,
)
from loan_tape.excel_process import open_in_excel
from loan_tape.packs import Catalog, PackPin, PackStore
from loan_tape.selection import SavedTable
from loan_tape.session import AnalysisSession
from loan_tape.workers import WorkerGroup

FORMAT_PRESETS = (
    "YYYY-MM-DD",
    "M/D/YYYY",
    "D/M/YYYY",
    "M/D/YY",
    "D/M/YY",
    "YYYY-MM-DD + M/D/YYYY",
    "YYYY-MM-DD + M/D/YY",
    "M/D/YYYY + M/D/YY",
)
CALENDAR_LABELS = {
    "No calendar screen": "",
    "SIFMA U.S. fixed-income market": "us.sifma_fixed_income",
}
ACTIVITY_LABELS = {
    "Reference screening": "reference_screening",
    "Closing": "closing",
    "Maturity": "maturity",
}
REQUIREMENT_LABELS = {
    "Use dictionary setting": None,
    "Require a value": True,
    "Allow blank": False,
}
REFERENCE_LABELS = {
    "No comparison": "none",
    "Flag dates before reference date": "flag_before",
    "Flag dates after reference date": "flag_after",
}
PAGE_SIZE = 50
DATE_PACK_ID = "loan.dates"


def _optional_date(value: str, label: str) -> date | None:
    text = value.strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError as error:
        raise ValueError(f"{label} must use YYYY-MM-DD.") from error


def _optional_int(value: str, label: str) -> int | None:
    text = value.strip()
    if not text:
        return None
    try:
        result = int(text)
    except ValueError as error:
        raise ValueError(f"{label} must be a whole number.") from error
    if result < 0:
        raise ValueError(f"{label} cannot be negative.")
    return result


class DateWorkflowWindow:
    def __init__(
        self,
        parent: tk.Misc,
        path: Path,
        table: SavedTable,
        columns: tuple[tuple[int, str], ...],
        session: AnalysisSession,
        pack_store: PackStore,
        jump: Any,
        workers: WorkerGroup,
    ) -> None:
        self.window = tk.Toplevel(parent)
        self.window.title(f"Date workflow — {table.name}")
        self.window.geometry("1240x820")
        self.window.minsize(1000, 700)
        self.window.transient(parent.winfo_toplevel())
        self.path, self.table, self.session = path, table, session
        self.pack_store, self.jump, self.workers = pack_store, jump, workers
        self.columns = columns
        self.column_lookup = {label: column for column, label in columns}
        self.closed = False
        self.busy = False
        self.ready = False
        self.activating_pack = False
        self.date_pack_fingerprint: str | None = None
        self.enable_dates_button: ttk.Button | None = None
        self.cancelled = threading.Event()
        self.results: queue.Queue[
            DateStandardization | SavedDateRun | DateExport | PackPin | Exception | str
        ] = queue.Queue()
        self.standardization: DateStandardization | None = None
        self.run: SavedDateRun | None = None
        self.export: DateExport | None = None
        self.findings: list[dict[str, Any]] = []
        self.page = 0
        self.status = tk.StringVar(master=self.window, value="Map the source columns explicitly.")
        self.standardization_summary = tk.StringVar(
            master=self.window,
            value="No standardized date snapshot is ready. Red flags remain unavailable.",
        )
        self.summary = tk.StringVar(master=self.window)
        self.page_label = tk.StringVar(master=self.window)
        self.reporting_date = tk.StringVar(master=self.window)
        self.short_year = tk.StringVar(master=self.window)
        self.missing_tokens = tk.StringVar(master=self.window)
        self.strip_whitespace = tk.BooleanVar(master=self.window)
        self.accept_timestamps = tk.BooleanVar(master=self.window)
        self.pair_enabled = tk.BooleanVar(master=self.window)
        self.pair_start = tk.StringVar(master=self.window)
        self.pair_end = tk.StringVar(master=self.window)
        self.pair_allow_equal = tk.BooleanVar(master=self.window, value=True)
        self.pair_minimum = tk.StringVar(master=self.window)
        self.pair_maximum = tk.StringVar(master=self.window)
        self.mapping_vars: dict[str, tuple[tk.StringVar, tk.StringVar]] = {}
        self.review_vars: dict[
            str, tuple[tk.StringVar, tk.StringVar, tk.StringVar, tk.StringVar]
        ] = {}
        self.calendar_vars: dict[
            str, tuple[tk.StringVar, tk.StringVar, tk.BooleanVar, tk.StringVar]
        ] = {}
        self.field_labels: dict[str, str] = {}
        self.label_fields: dict[str, str] = {}
        self._build()
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.poll_id = self.window.after(80, self._poll)

    def _catalog(self) -> Catalog:
        catalog = self.pack_store.catalog("default")
        for field_id in LOAN_DATE_FIELDS:
            field = catalog.get_field(field_id)
            self.field_labels[field_id] = field.field.label
            self.label_fields[field.field.label] = field_id
        return catalog

    def _build(self) -> None:
        self.ready = False
        self.date_pack_fingerprint = None
        self.enable_dates_button = None
        try:
            self._catalog()
        except Exception as error:
            self._build_unavailable(error)
            return

        self.ready = True
        outer = ttk.Frame(self.window, padding=14)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)
        ttk.Label(
            outer, text="Date standardization and red flags", font=("Segoe UI", 17, "bold")
        ).grid(row=0, sticky="w")
        ttk.Label(
            outer,
            text=(
                f"{self.table.name} · {self.table.selection.sheet}!{self.table.selection.area.address} · "
                f"{self.session.date_label}. Source values remain unchanged."
            ),
            wraplength=1160,
        ).grid(row=1, sticky="ew", pady=(4, 10))
        tabs = ttk.Notebook(outer)
        tabs.grid(row=2, sticky="nsew")
        setup = ttk.Frame(tabs, padding=12)
        rules = ttk.Frame(tabs, padding=12)
        results = ttk.Frame(tabs, padding=12)
        tabs.add(setup, text="1  Import & standardize")
        tabs.add(rules, text="2  Red flags")
        tabs.add(results, text="3  Findings")
        self.tabs = tabs
        self.rules_tab, self.results_tab = rules, results
        tabs.tab(rules, state="disabled")  # type: ignore[no-untyped-call]
        tabs.tab(results, state="disabled")  # type: ignore[no-untyped-call]
        self._build_setup(setup)
        self._build_red_flags(rules)
        self._build_results(results)
        footer = ttk.Frame(outer)
        footer.grid(row=3, sticky="ew", pady=(10, 0))
        ttk.Label(footer, textvariable=self.status, wraplength=850).pack(
            side="left", fill="x", expand=True
        )
        self.red_flag_button = ttk.Button(
            footer, text="Run red flags", command=self.run_red_flags, state="disabled"
        )
        self.red_flag_button.pack(side="right", padx=(8, 0))
        self.standardize_button = ttk.Button(
            footer, text="Import & standardize", command=self.run_standardization
        )
        self.standardize_button.pack(side="right", padx=(8, 0))
        self.close_button = ttk.Button(footer, text="Close", command=self.close)
        self.close_button.pack(side="right")

    def _build_unavailable(self, catalog_error: Exception) -> None:
        page = ttk.Frame(self.window, padding=24)
        page.pack(fill="both", expand=True)
        ttk.Label(page, text="Date analysis is not ready", font=("Segoe UI", 16, "bold")).pack(
            anchor="w"
        )
        ttk.Label(page, text=str(catalog_error), wraplength=800).pack(anchor="w", pady=(12, 16))
        try:
            pack = self.pack_store.available_pack(DATE_PACK_ID)
        except Exception as pack_error:
            self.status.set(f"The local loan date definitions cannot be enabled: {pack_error}")
            ttk.Label(page, textvariable=self.status, wraplength=800).pack(anchor="w")
        else:
            self.date_pack_fingerprint = pack.fingerprint
            ttk.Label(
                page,
                text=(
                    f"Enable the available {pack.name} {pack.version} in the default profile. "
                    "This records a versioned dictionary snapshot and does not change the workbook."
                ),
                wraplength=800,
            ).pack(anchor="w")
            self.status.set("Choose Enable to continue in this window.")
            ttk.Label(page, textvariable=self.status, wraplength=800, style="Muted.TLabel").pack(
                anchor="w", pady=(8, 0)
            )
        actions = ttk.Frame(page)
        actions.pack(fill="x", pady=(24, 0))
        if self.date_pack_fingerprint is not None:
            self.enable_dates_button = ttk.Button(
                actions,
                text="Enable loan date definitions",
                command=self.enable_date_definitions,
            )
            self.enable_dates_button.pack(side="right", padx=(8, 0))
        ttk.Button(actions, text="Close", command=self.close).pack(side="right")

    def enable_date_definitions(self) -> None:
        if self.closed or self.busy or self.date_pack_fingerprint is None:
            return
        fingerprint = self.date_pack_fingerprint
        self.busy = True
        self.activating_pack = True
        self.cancelled.clear()
        if self.enable_dates_button is not None:
            self.enable_dates_button.configure(state="disabled")
        self.status.set("Enabling the versioned loan date definitions…")

        def activate() -> None:
            try:
                self.results.put(
                    self.pack_store.activate(
                        DATE_PACK_ID,
                        "default",
                        expected_fingerprint=fingerprint,
                    )
                )
            except Exception as error:
                self.results.put(error)

        self.workers.start(activate, "date-pack-activation", self.cancelled)

    def _show_pack_activation(self, pin: PackPin) -> None:
        self.busy = False
        self.activating_pack = False
        self.field_labels.clear()
        self.label_fields.clear()
        for child in self.window.winfo_children():
            child.destroy()
        self._build()
        if self.ready:
            self.status.set(
                f"Enabled loan date definitions {pin.version}. Map the source columns explicitly."
            )

    def _group(self, parent: tk.Misc, title: str, row: int) -> ttk.LabelFrame:
        group = ttk.LabelFrame(parent, text=title, padding=10)
        group.grid(row=row, sticky="ew", pady=(0, 10))
        return group

    def _scroll_body(self, parent: ttk.Frame) -> ttk.Frame:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        canvas = tk.Canvas(parent, highlightthickness=0)
        scroll = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        body = ttk.Frame(canvas)
        item = canvas.create_window(0, 0, window=body, anchor="nw")
        body.columnconfigure(0, weight=1)
        body.bind("<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(item, width=event.width))
        return body

    def _build_setup(self, parent: ttk.Frame) -> None:
        body = self._scroll_body(parent)

        mapping = self._group(body, "Source mapping and interpretation", 0)
        headings = ("Loan date meaning", "Source column", "Accepted text format")
        for column, heading in enumerate(headings):
            ttk.Label(mapping, text=heading, style="Muted.TLabel").grid(
                row=0, column=column, sticky="w", padx=(0, 8)
            )
        mapping.columnconfigure(1, weight=1)
        for row, field_id in enumerate(LOAN_DATE_FIELDS, start=1):
            source = tk.StringVar(master=self.window)
            text_format = tk.StringVar(master=self.window)
            self.mapping_vars[field_id] = source, text_format
            ttk.Label(mapping, text=self.field_labels[field_id]).grid(
                row=row, column=0, sticky="w", padx=(0, 8), pady=3
            )
            ttk.Combobox(
                mapping,
                textvariable=source,
                values=tuple(self.column_lookup),
                state="readonly",
                width=34,
            ).grid(row=row, column=1, sticky="ew", padx=(0, 8), pady=3)
            ttk.Combobox(mapping, textvariable=text_format, values=FORMAT_PRESETS, width=27).grid(
                row=row, column=2, sticky="ew", padx=(0, 8), pady=3
            )
        ttk.Label(
            mapping,
            text="Excel date cells are accepted as stored serials. Text formats are explicit; mappings are never guessed from headers. This phase does not run review rules.",
            style="Muted.TLabel",
            wraplength=1080,
        ).grid(row=5, column=0, columnspan=3, sticky="w", pady=(7, 0))

        interpretation = self._group(body, "Shared interpretation choices", 1)
        ttk.Label(interpretation, text="Two-digit year window starts").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Entry(interpretation, textvariable=self.short_year, width=12).grid(
            row=0, column=1, sticky="w", padx=(8, 24)
        )
        ttk.Label(interpretation, text="Exact missing tokens (comma separated)").grid(
            row=0, column=2, sticky="w"
        )
        ttk.Entry(interpretation, textvariable=self.missing_tokens, width=34).grid(
            row=0, column=3, sticky="ew", padx=(8, 0)
        )
        interpretation.columnconfigure(3, weight=1)
        ttk.Checkbutton(
            interpretation,
            text="Strip surrounding whitespace before parsing",
            variable=self.strip_whitespace,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Checkbutton(
            interpretation,
            text="Use the written date component of timestamps",
            variable=self.accept_timestamps,
        ).grid(row=1, column=2, columnspan=2, sticky="w", pady=(8, 0))

        handoff = self._group(body, "Standardized handoff", 2)
        ttk.Label(
            handoff,
            textvariable=self.standardization_summary,
            wraplength=1080,
        ).grid(row=0, sticky="w")

    def _build_red_flags(self, parent: ttk.Frame) -> None:
        body = self._scroll_body(parent)

        review = self._group(body, "Required values and review bounds", 0)
        for column, heading in enumerate(
            (
                "Field",
                "Blank policy",
                "Earliest YYYY-MM-DD",
                "Latest YYYY-MM-DD",
                "Reference-date review",
            )
        ):
            ttk.Label(review, text=heading, style="Muted.TLabel").grid(
                row=0, column=column, sticky="w", padx=(0, 8)
            )
        review.columnconfigure(4, weight=1)
        for row, field_id in enumerate(LOAN_DATE_FIELDS, start=1):
            requirement = tk.StringVar(master=self.window, value="Use dictionary setting")
            earliest = tk.StringVar(master=self.window)
            latest = tk.StringVar(master=self.window)
            reference = tk.StringVar(master=self.window, value="No comparison")
            self.review_vars[field_id] = requirement, earliest, latest, reference
            ttk.Label(review, text=self.field_labels[field_id]).grid(
                row=row, column=0, sticky="w", padx=(0, 8), pady=3
            )
            ttk.Combobox(
                review,
                textvariable=requirement,
                values=tuple(REQUIREMENT_LABELS),
                state="readonly",
                width=22,
            ).grid(row=row, column=1, sticky="ew", padx=(0, 8), pady=3)
            ttk.Entry(review, textvariable=earliest, width=20).grid(
                row=row, column=2, sticky="ew", padx=(0, 8), pady=3
            )
            ttk.Entry(review, textvariable=latest, width=20).grid(
                row=row, column=3, sticky="ew", padx=(0, 8), pady=3
            )
            ttk.Combobox(
                review,
                textvariable=reference,
                values=tuple(REFERENCE_LABELS),
                state="readonly",
                width=35,
            ).grid(row=row, column=4, sticky="ew", pady=3)

        pair = self._group(body, "Optional start/end comparison", 1)
        ttk.Checkbutton(
            pair, text="Compare two mapped date fields", variable=self.pair_enabled
        ).grid(row=0, column=0, columnspan=2, sticky="w")
        labels = tuple(self.label_fields)
        ttk.Label(pair, text="Start").grid(row=1, column=0, sticky="w", pady=(7, 0))
        ttk.Combobox(
            pair, textvariable=self.pair_start, values=labels, state="readonly", width=26
        ).grid(row=1, column=1, sticky="w", padx=(8, 18), pady=(7, 0))
        ttk.Label(pair, text="End").grid(row=1, column=2, sticky="w", pady=(7, 0))
        ttk.Combobox(
            pair, textvariable=self.pair_end, values=labels, state="readonly", width=26
        ).grid(row=1, column=3, sticky="w", padx=(8, 18), pady=(7, 0))
        ttk.Checkbutton(pair, text="Allow the same date", variable=self.pair_allow_equal).grid(
            row=1, column=4, sticky="w", pady=(7, 0)
        )
        ttk.Label(pair, text="Minimum days").grid(row=2, column=0, sticky="w", pady=(7, 0))
        ttk.Entry(pair, textvariable=self.pair_minimum, width=12).grid(
            row=2, column=1, sticky="w", padx=(8, 18), pady=(7, 0)
        )
        ttk.Label(pair, text="Maximum days").grid(row=2, column=2, sticky="w", pady=(7, 0))
        ttk.Entry(pair, textvariable=self.pair_maximum, width=12).grid(
            row=2, column=3, sticky="w", padx=(8, 18), pady=(7, 0)
        )

        calendars = self._group(body, "Optional business-calendar screens", 2)
        calendar_headings = (
            "Field",
            "Calendar",
            "Activity",
            "Required",
            "Agreement reference",
        )
        for column, heading in enumerate(calendar_headings):
            ttk.Label(calendars, text=heading, style="Muted.TLabel").grid(
                row=0, column=column, sticky="w", padx=(0, 8)
            )
        calendars.columnconfigure(4, weight=1)
        for row, field_id in enumerate(LOAN_DATE_FIELDS, start=1):
            calendar = tk.StringVar(master=self.window, value="No calendar screen")
            activity = tk.StringVar(master=self.window, value="Reference screening")
            required = tk.BooleanVar(master=self.window)
            agreement = tk.StringVar(master=self.window)
            self.calendar_vars[field_id] = calendar, activity, required, agreement
            ttk.Label(calendars, text=self.field_labels[field_id]).grid(
                row=row, column=0, sticky="w", padx=(0, 8), pady=3
            )
            ttk.Combobox(
                calendars,
                textvariable=calendar,
                values=tuple(CALENDAR_LABELS),
                state="readonly",
                width=31,
            ).grid(row=row, column=1, sticky="ew", padx=(0, 8), pady=3)
            ttk.Combobox(
                calendars,
                textvariable=activity,
                values=tuple(ACTIVITY_LABELS),
                state="readonly",
                width=28,
            ).grid(row=row, column=2, sticky="ew", padx=(0, 8), pady=3)
            ttk.Checkbutton(calendars, variable=required).grid(
                row=row, column=3, sticky="w", padx=(0, 8), pady=3
            )
            ttk.Entry(calendars, textvariable=agreement, width=30).grid(
                row=row, column=4, sticky="ew", pady=3
            )
        ttk.Label(
            calendars,
            text="SIFMA published schedules are used for 2019–2027. Other weekdays remain unknown until a credible schedule is added; weekends are always calculated. A governing agreement is required before treating a date as an error.",
            style="Muted.TLabel",
            wraplength=1080,
        ).grid(row=5, column=0, columnspan=5, sticky="w", pady=(7, 0))

        context = self._group(body, "Red-flag context", 3)
        ttk.Label(context, text=self.session.startup_label).grid(
            row=0, column=0, columnspan=2, sticky="w"
        )
        ttk.Label(context, text="Reporting date, if stated by the source (YYYY-MM-DD)").grid(
            row=1, column=0, sticky="w", pady=(8, 0)
        )
        ttk.Entry(context, textvariable=self.reporting_date, width=18).grid(
            row=1, column=1, sticky="w", padx=(8, 0), pady=(8, 0)
        )

    def _build_results(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(2, weight=1)
        ttk.Label(parent, textvariable=self.summary, wraplength=1120).grid(row=0, sticky="ew")
        controls = ttk.Frame(parent)
        controls.grid(row=1, sticky="ew", pady=(8, 6))
        self.previous_button = ttk.Button(
            controls, text="Previous", command=lambda: self._change_page(-1), state="disabled"
        )
        self.previous_button.pack(side="left")
        self.next_button = ttk.Button(
            controls, text="Next", command=lambda: self._change_page(1), state="disabled"
        )
        self.next_button.pack(side="left", padx=(6, 0))
        ttk.Label(controls, textvariable=self.page_label).pack(side="left", padx=(10, 0))
        self.export_button = ttk.Button(
            controls, text="Export refined loan tape…", command=self.export_review, state="disabled"
        )
        self.export_button.pack(side="right")
        self.open_button = ttk.Button(
            controls, text="Open export in Excel", command=self.open_export, state="disabled"
        )
        self.open_button.pack(side="right", padx=(0, 6))
        self.finding_grid = ttk.Treeview(
            parent,
            columns=("severity", "rule", "columns", "rows", "message"),
            show="headings",
            selectmode="browse",
        )
        for name, label, width in (
            ("severity", "Severity", 80),
            ("rule", "Rule", 190),
            ("columns", "Columns", 90),
            ("rows", "Rows", 120),
            ("message", "Finding", 620),
        ):
            self.finding_grid.heading(name, text=label)
            self.finding_grid.column(name, width=width, stretch=name == "message")
        self.finding_grid.grid(row=2, sticky="nsew")
        self.finding_grid.bind("<<TreeviewSelect>>", self._selected)
        self.detail = tk.Text(parent, height=5, wrap="word", state="disabled", padx=8, pady=6)
        self.detail.grid(row=3, sticky="ew", pady=(8, 6))
        self.jump_button = ttk.Button(
            parent,
            text="Jump to first affected cell",
            command=self.jump_to_finding,
            state="disabled",
        )
        self.jump_button.grid(row=4, sticky="w")

    def _standardization_inputs(self) -> tuple[Catalog, tuple[DateMapping, ...]]:
        catalog = self._catalog()
        mappings = []
        for field_id in LOAN_DATE_FIELDS:
            source, text_format = self.mapping_vars[field_id]
            chosen = source.get().strip()
            if not chosen:
                continue
            if chosen not in self.column_lookup:
                raise ValueError("A selected source column is no longer available.")
            formats = tuple(part.strip() for part in text_format.get().split("+") if part.strip())
            mappings.append(
                MappingSetting(
                    field_id,
                    self.column_lookup[chosen],
                    formats,
                )
            )
        year = _optional_int(self.short_year.get(), "Two-digit year window")
        missing = tuple(
            part.strip() for part in self.missing_tokens.get().split(",") if part.strip()
        )
        return catalog, build_standardization_inputs(
            catalog,
            tuple(mappings),
            two_digit_year_start=year,
            missing_tokens=missing,
            strip_whitespace=self.strip_whitespace.get(),
            accept_timestamp_date=self.accept_timestamps.get(),
        )

    def _red_flag_inputs(
        self,
    ) -> tuple[tuple[DateBinding, ...], tuple[DatePair, ...], tuple[CalendarSnapshot, ...]]:
        if self.standardization is None:
            raise ValueError("Import and standardize the mapped dates before running red flags.")
        catalog, mappings = self._standardization_inputs()
        if catalog != self.standardization.catalog or mappings != self.standardization.mappings:
            raise ValueError(
                "Mapping or interpretation choices changed. Import and standardize again before running red flags."
            )

        mapped_fields = {item.field_id for item in mappings}
        reviews = []
        calendar_settings = []
        for field_id in LOAN_DATE_FIELDS:
            requirement, earliest, latest, reference = self.review_vars[field_id]
            calendar = self.calendar_vars[field_id]
            has_review = (
                requirement.get() != "Use dictionary setting"
                or bool(earliest.get().strip())
                or bool(latest.get().strip())
                or reference.get() != "No comparison"
            )
            has_calendar = (
                calendar[0].get() != "No calendar screen"
                or calendar[2].get()
                or bool(calendar[3].get().strip())
            )
            if field_id not in mapped_fields:
                if has_review or has_calendar:
                    raise ValueError(
                        f"Standardize {self.field_labels[field_id]} before assigning red flags to it."
                    )
                continue
            reviews.append(
                ReviewSetting(
                    field_id,
                    REQUIREMENT_LABELS[requirement.get()],
                    _optional_date(earliest.get(), f"{self.field_labels[field_id]} earliest date"),
                    _optional_date(latest.get(), f"{self.field_labels[field_id]} latest date"),
                    REFERENCE_LABELS[reference.get()],
                )
            )
            calendar_id = CALENDAR_LABELS[calendar[0].get()]
            if calendar_id:
                calendar_settings.append(
                    CalendarSetting(
                        field_id,
                        calendar_id,
                        ACTIVITY_LABELS[calendar[1].get()],
                        calendar[2].get(),
                        calendar[3].get().strip() or None,
                    )
                )
        pair = None
        if self.pair_enabled.get():
            if (
                self.pair_start.get() not in self.label_fields
                or self.pair_end.get() not in self.label_fields
            ):
                raise ValueError("Choose mapped start and end fields for the comparison.")
            pair = PairSetting(
                self.label_fields[self.pair_start.get()],
                self.label_fields[self.pair_end.get()],
                self.pair_allow_equal.get(),
                _optional_int(self.pair_minimum.get(), "Minimum days"),
                _optional_int(self.pair_maximum.get(), "Maximum days"),
            )
        return build_red_flag_inputs(
            mappings,
            reviews=tuple(reviews),
            calendars=tuple(calendar_settings),
            pair=pair,
        )

    def run_standardization(self) -> None:
        if self.busy or self.closed:
            return
        try:
            catalog, mappings = self._standardization_inputs()
        except Exception as error:
            self.status.set(str(error))
            return
        self.busy = True
        self.standardization = None
        self.run, self.export = None, None
        self.findings = []
        self.summary.set("")
        self.tabs.select(0)  # type: ignore[no-untyped-call]
        self.tabs.tab(self.rules_tab, state="disabled")  # type: ignore[no-untyped-call]
        self.tabs.tab(self.results_tab, state="disabled")  # type: ignore[no-untyped-call]
        self.cancelled.clear()
        self.standardize_button.configure(state="disabled")
        self.red_flag_button.configure(state="disabled")
        self.export_button.configure(state="disabled")
        self.open_button.configure(state="disabled")
        self.standardization_summary.set(
            "Importing complete mapped columns and interpreting dates. No red-flag rules are running."
        )
        self.status.set("Importing and standardizing every mapped date cell…")

        def standardize() -> None:
            try:
                self.results.put(
                    standardize_excel_dates(
                        self.path,
                        self.table,
                        mappings,
                        catalog,
                        cancelled=self.cancelled,
                    )
                )
            except Exception as error:
                self.results.put(error)

        self.workers.start(standardize, "date-standardization", self.cancelled)

    def _show_standardization(self, result: DateStandardization) -> None:
        self.standardization = result
        valid = sum(column.valid_count for column in result.columns)
        unresolved = result.cell_count - valid
        self.standardization_summary.set(
            f"Ready: {result.row_count:,} rows · {result.cell_count:,} mapped cells · "
            f"{valid:,} interpreted · {unresolved:,} unresolved. No red flags have been run."
        )
        self.standardize_button.configure(state="normal")
        self.red_flag_button.configure(state="normal")
        self.tabs.tab(self.rules_tab, state="normal")  # type: ignore[no-untyped-call]
        self.tabs.select(1)  # type: ignore[no-untyped-call]
        self.status.set(
            "Date standardization is complete. Configure the separate red-flag phase when ready."
        )

    def run_red_flags(self) -> None:
        if self.busy or self.closed:
            return
        try:
            bindings, pairs, calendars = self._red_flag_inputs()
            reporting = _optional_date(self.reporting_date.get(), "Reporting date")
        except Exception as error:
            self.status.set(str(error))
            return
        assert self.standardization is not None
        standardization = self.standardization
        self.busy = True
        self.cancelled.clear()
        self.standardize_button.configure(state="disabled")
        self.red_flag_button.configure(state="disabled")
        self.export_button.configure(state="disabled")
        self.status.set("Running red flags against the completed standardized snapshot…")

        def analyze() -> None:
            try:
                analysis = analyze_standardized_dates(
                    standardization,
                    bindings,
                    reference_date=self.session.reference_date,
                    reporting_date=reporting,
                    pairs=pairs,
                    calendars=calendars,
                    cancelled=self.cancelled,
                )
                self.results.put(
                    save_date_run(
                        analysis,
                        Path(".artifacts/date-runs"),
                        cancelled=self.cancelled,
                    )
                )
            except Exception as error:
                self.results.put(error)

        self.workers.start(analyze, "date-red-flags", self.cancelled)

    def _show_run(self, run: SavedDateRun) -> None:
        self.run, self.export = run, None
        document = run.analysis.to_dict()
        result = document["results"]
        self.findings = list(result["findings"])
        counts = result["finding_counts"]
        self.summary.set(
            f"{result['row_count']:,} rows · {result['cell_count']:,} mapped cells · "
            f"{counts['error']:,} errors · {counts['review']:,} review items · {counts['info']:,} information items. "
            f"Saved run {run.id}."
        )
        self.page = 0
        self._render_page()
        self.tabs.tab(self.results_tab, state="normal")  # type: ignore[no-untyped-call]
        self.tabs.select(2)  # type: ignore[no-untyped-call]
        self.standardize_button.configure(state="normal")
        self.red_flag_button.configure(state="normal")
        self.export_button.configure(state="normal")
        self.open_button.configure(state="disabled")
        self.status.set(
            "Red-flag review completed and saved. Review findings or export the immutable result."
        )

    def _render_page(self) -> None:
        for item in self.finding_grid.get_children():
            self.finding_grid.delete(item)
        pages = max(1, (len(self.findings) + PAGE_SIZE - 1) // PAGE_SIZE)
        self.page = max(0, min(self.page, pages - 1))
        start = self.page * PAGE_SIZE
        for index, finding in enumerate(self.findings[start : start + PAGE_SIZE], start=start):
            self.finding_grid.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    finding["severity"].upper(),
                    finding["rule_id"],
                    ", ".join(map(str, finding["columns"])),
                    ", ".join(map(str, finding["rows"])),
                    finding["message"],
                ),
            )
        self.page_label.set(f"Page {self.page + 1} of {pages} · {len(self.findings):,} findings")
        self.previous_button.configure(state="normal" if self.page else "disabled")
        self.next_button.configure(state="normal" if self.page + 1 < pages else "disabled")
        self.jump_button.configure(state="disabled")
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert(
            "1.0", "No findings." if not self.findings else "Select a finding for its details."
        )
        self.detail.configure(state="disabled")

    def _change_page(self, amount: int) -> None:
        self.page += amount
        self._render_page()

    def _selected(self, event: tk.Event[tk.Misc] | None = None) -> None:
        selection = self.finding_grid.selection()
        finding = self.findings[int(selection[0])] if selection else None
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        if finding:
            self.detail.insert(
                "1.0",
                f"{finding['message']}\n\nRule: {finding['rule_id']}\nDetails: {finding['details']}",
            )
        self.detail.configure(state="disabled")
        self.jump_button.configure(
            state="normal" if finding and finding["rows"] and finding["columns"] else "disabled"
        )

    def jump_to_finding(self) -> None:
        selection = self.finding_grid.selection()
        if not selection:
            return
        finding = self.findings[int(selection[0])]
        if finding["rows"] and finding["columns"]:
            try:
                self.jump(self.table, finding["columns"][0], finding["rows"][0])
            except Exception as error:
                self.status.set(str(error))

    def export_review(self) -> None:
        if self.busy or self.run is None:
            return
        selected = filedialog.asksaveasfilename(
            parent=self.window,
            title="Save refined loan tape",
            initialfile=f"{self.table.name} - refined loan tape.xlsx",
            defaultextension=".xlsx",
            filetypes=(("Excel workbook", "*.xlsx"),),
        )
        if not selected:
            return
        target = Path(selected)
        self.busy = True
        self.cancelled.clear()
        self.standardize_button.configure(state="disabled")
        self.red_flag_button.configure(state="disabled")
        self.export_button.configure(state="disabled")
        self.status.set("Creating and validating the complete refined loan tape…")

        def export() -> None:
            try:
                assert self.run is not None
                self.results.put(
                    export_date_run(
                        self.run,
                        target,
                        source_path=self.path,
                        cancelled=self.cancelled,
                    )
                )
            except Exception as error:
                self.results.put(error)

        self.workers.start(export, "date-export", self.cancelled)

    def open_export(self) -> None:
        if self.export is None:
            return
        try:
            open_in_excel(self.export.path)
        except Exception as error:
            self.status.set(str(error))

    def _poll(self) -> None:
        if self.closed:
            return
        try:
            while True:
                result = self.results.get_nowait()
                if isinstance(result, str):
                    self.status.set(result)
                elif isinstance(result, PackPin):
                    self._show_pack_activation(result)
                elif isinstance(result, DateStandardization):
                    self.busy = False
                    self._show_standardization(result)
                elif isinstance(result, SavedDateRun):
                    self.busy = False
                    self._show_run(result)
                elif isinstance(result, DateExport):
                    self.busy, self.export = False, result
                    self.standardize_button.configure(state="normal")
                    self.red_flag_button.configure(
                        state="normal" if self.standardization else "disabled"
                    )
                    self.export_button.configure(state="normal")
                    self.open_button.configure(state="normal")
                    self.status.set(f"Refined loan tape saved and validated: {result.path}")
                else:
                    self.busy = False
                    if self.activating_pack:
                        self.activating_pack = False
                        if self.enable_dates_button is not None:
                            self.enable_dates_button.configure(state="normal")
                        self.status.set(f"Could not enable loan date definitions: {result}")
                    else:
                        self.standardize_button.configure(state="normal")
                        self.red_flag_button.configure(
                            state="normal" if self.standardization else "disabled"
                        )
                        self.export_button.configure(state="normal" if self.run else "disabled")
                        self.status.set(str(result))
        except queue.Empty:
            pass
        self.poll_id = self.window.after(80, self._poll)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.cancelled.set()
        if hasattr(self, "poll_id"):
            self.window.after_cancel(self.poll_id)
        self.window.destroy()
