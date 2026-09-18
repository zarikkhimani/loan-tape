"""Native editor for one saved Excel data-set column definition."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, ttk

from loan_tape.column_definitions import (
    ColumnDefinition,
    ColumnRules,
    FieldSnapshot,
    definition_for_column,
    remove_column_definition,
    save_column_definition,
    snapshot_field,
)
from loan_tape.packs import Catalog, CatalogField, PackStore
from loan_tape.ranges import column_label
from loan_tape.selection import SavedTable
from loan_tape.theme_ui import ERROR, MUTED

FORMAT_PRESETS = {
    "YYYY-MM-DD": ("YYYY-MM-DD",),
    "M/D/YYYY": ("M/D/YYYY",),
    "D/M/YYYY": ("D/M/YYYY",),
    "M/D/YY": ("M/D/YY",),
    "D/M/YY": ("D/M/YY",),
    "YYYY-MM-DD + M/D/YYYY": ("YYYY-MM-DD", "M/D/YYYY"),
    "YYYY-MM-DD + D/M/YYYY": ("YYYY-MM-DD", "D/M/YYYY"),
    "M/D/YYYY + M/D/YY": ("M/D/YYYY", "M/D/YY"),
    "D/M/YYYY + D/M/YY": ("D/M/YYYY", "D/M/YY"),
}
REQUIRED_CHOICES = {
    "Use dictionary setting": None,
    "Require a value": True,
    "Not required": False,
}
BLANK_CHOICES = {
    "Use dictionary setting": None,
    "Allow blank values": True,
    "Do not allow blanks": False,
}
UNIQUE_CHOICES = {
    "Not specified": None,
    "Require unique values": True,
    "Allow duplicates": False,
}


def _choice_for(value: bool | None, choices: dict[str, bool | None]) -> str:
    return next(label for label, item in choices.items() if item is value)


def _format_choice(formats: tuple[str, ...]) -> str:
    return next((label for label, value in FORMAT_PRESETS.items() if value == formats), "")


class ColumnDefinitionWindow:
    def __init__(
        self,
        parent: tk.Misc,
        table: SavedTable,
        column: int,
        source_header: str,
        pack_store: PackStore,
        on_change: Callable[[], None] | None = None,
    ) -> None:
        self.window = tk.Toplevel(parent)
        self.window.title(f"Column definition — {column_label(column)}")
        self.window.geometry("820x760")
        self.window.minsize(720, 660)
        self.window.transient(parent.winfo_toplevel())
        self.table = table
        self.column = column
        self.source_header = source_header
        self.on_change = on_change
        self.closed = False
        self.existing: ColumnDefinition | None = None
        self.catalog: Catalog | None = None
        self.catalog_error: str | None = None
        self.fields_by_choice: dict[str, CatalogField | None] = {}

        self.meaning = tk.StringVar(master=self.window)
        self.type_summary = tk.StringVar(master=self.window)
        self.dictionary_rules = tk.StringVar(master=self.window)
        self.currency = tk.StringVar(master=self.window)
        self.source_unit = tk.StringVar(master=self.window)
        self.date_format = tk.StringVar(master=self.window)
        self.short_year = tk.StringVar(master=self.window)
        self.required = tk.StringVar(master=self.window, value="Use dictionary setting")
        self.blank_allowed = tk.StringVar(master=self.window, value="Use dictionary setting")
        self.unique = tk.StringVar(master=self.window, value="Not specified")
        self.minimum = tk.StringVar(master=self.window)
        self.maximum = tk.StringVar(master=self.window)
        self.status = tk.StringVar(master=self.window)

        try:
            self.existing = definition_for_column(table, column)
            self.catalog = pack_store.catalog("default")
            for item in sorted(
                self.catalog.fields,
                key=lambda value: (value.field.label.casefold(), value.id),
            ):
                label = f"{item.field.label} — {item.id} ({item.pack_version})"
                self.fields_by_choice[label] = item
        except (OSError, ValueError) as error:
            self.catalog_error = str(error)

        self._build()
        self._load()
        self.window.protocol("WM_DELETE_WINDOW", self.close)

    def _build(self) -> None:
        page = ttk.Frame(self.window, padding=16)
        page.pack(fill="both", expand=True)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(3, weight=1)
        ttk.Label(page, text="Save column definition", font=("Segoe UI", 17, "bold")).grid(
            row=0, sticky="w"
        )
        header = self.source_header.strip() or "No saved header"
        ttk.Label(
            page,
            text=(
                f"{self.table.name} · {self.table.selection.sheet}!{column_label(self.column)} · "
                f"Header: {header}"
            ),
            wraplength=770,
        ).grid(row=1, sticky="ew", pady=(4, 10))
        ttk.Label(
            page,
            text=(
                "This records what the source column means. Excel cell types and number formats "
                "remain source evidence; they do not choose the business meaning."
            ),
            foreground=MUTED,
            wraplength=770,
        ).grid(row=2, sticky="ew", pady=(0, 10))

        body = ttk.Frame(page)
        body.grid(row=3, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        canvas = tk.Canvas(body, highlightthickness=0)
        scroll = ttk.Scrollbar(body, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        form = ttk.Frame(canvas)
        form.columnconfigure(0, weight=1)
        item = canvas.create_window(0, 0, window=form, anchor="nw")
        form.bind("<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(item, width=event.width))

        meaning_group = ttk.LabelFrame(form, text="Meaning from the active dictionary", padding=10)
        meaning_group.grid(row=0, sticky="ew", pady=(0, 10))
        meaning_group.columnconfigure(0, weight=1)
        self.meaning_selector = ttk.Combobox(
            meaning_group,
            textvariable=self.meaning,
            values=tuple(self.fields_by_choice),
            state="readonly" if self.fields_by_choice else "disabled",
        )
        self.meaning_selector.grid(row=0, sticky="ew")
        self.meaning_selector.bind("<<ComboboxSelected>>", self._select_field)
        self.definition_text = tk.Text(
            meaning_group,
            height=4,
            wrap="word",
            state="disabled",
            relief="flat",
            padx=7,
            pady=6,
        )
        self.definition_text.grid(row=1, sticky="ew", pady=(8, 4))
        ttk.Label(meaning_group, textvariable=self.type_summary, foreground=MUTED).grid(
            row=2, sticky="w"
        )
        ttk.Label(
            meaning_group,
            textvariable=self.dictionary_rules,
            foreground=MUTED,
            wraplength=740,
        ).grid(row=3, sticky="ew", pady=(2, 0))

        representation = ttk.LabelFrame(form, text="Source representation", padding=10)
        representation.grid(row=1, sticky="ew", pady=(0, 10))
        representation.columnconfigure(1, weight=1)
        ttk.Label(representation, text="Currency").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.currency_entry = ttk.Entry(representation, textvariable=self.currency, width=16)
        self.currency_entry.grid(row=0, column=1, sticky="w")
        ttk.Label(
            representation,
            text="Three-letter code such as USD; required for a monetary field.",
            foreground=MUTED,
        ).grid(row=0, column=2, sticky="w", padx=(8, 0))
        ttk.Label(representation, text="Source units").grid(
            row=1, column=0, sticky="w", padx=(0, 8), pady=(7, 0)
        )
        self.unit_entry = ttk.Entry(representation, textvariable=self.source_unit)
        self.unit_entry.grid(row=1, column=1, columnspan=2, sticky="ew", pady=(7, 0))
        ttk.Label(representation, text="Accepted text date format").grid(
            row=2, column=0, sticky="w", padx=(0, 8), pady=(7, 0)
        )
        self.date_selector = ttk.Combobox(
            representation,
            textvariable=self.date_format,
            values=tuple(FORMAT_PRESETS),
            state="disabled",
        )
        self.date_selector.grid(row=2, column=1, columnspan=2, sticky="ew", pady=(7, 0))
        ttk.Label(representation, text="Two-digit year window starts").grid(
            row=3, column=0, sticky="w", padx=(0, 8), pady=(7, 0)
        )
        self.short_year_entry = ttk.Entry(
            representation, textvariable=self.short_year, width=16, state="disabled"
        )
        self.short_year_entry.grid(row=3, column=1, sticky="w", pady=(7, 0))
        ttk.Label(
            representation,
            text="Required for M/D/YY or D/M/YY; for example, 1970 means 1970–2069.",
            foreground=MUTED,
        ).grid(row=3, column=2, sticky="w", padx=(8, 0), pady=(7, 0))
        ttk.Label(
            representation,
            text=(
                "Excel numeric dates are interpreted with the workbook's 1900/1904 date system; "
                "this choice governs literal text dates."
            ),
            foreground=MUTED,
            wraplength=730,
        ).grid(row=4, column=0, columnspan=3, sticky="ew", pady=(6, 0))

        rules = ttk.LabelFrame(form, text="Rules to record", padding=10)
        rules.grid(row=2, sticky="ew", pady=(0, 8))
        rules.columnconfigure(1, weight=1)
        for row, (label, variable, values) in enumerate(
            (
                ("Value requirement", self.required, tuple(REQUIRED_CHOICES)),
                ("Blank values", self.blank_allowed, tuple(BLANK_CHOICES)),
                ("Duplicates", self.unique, tuple(UNIQUE_CHOICES)),
            )
        ):
            ttk.Label(rules, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=3)
            ttk.Combobox(rules, textvariable=variable, values=values, state="readonly").grid(
                row=row, column=1, sticky="ew", pady=3
            )
        ttk.Label(rules, text="Minimum / maximum").grid(
            row=3, column=0, sticky="w", padx=(0, 8), pady=3
        )
        bounds = ttk.Frame(rules)
        bounds.grid(row=3, column=1, sticky="ew", pady=3)
        bounds.columnconfigure((0, 1), weight=1)
        self.minimum_entry = ttk.Entry(bounds, textvariable=self.minimum)
        self.minimum_entry.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.maximum_entry = ttk.Entry(bounds, textvariable=self.maximum)
        self.maximum_entry.grid(row=0, column=1, sticky="ew", padx=(4, 0))
        ttk.Label(rules, text="Missing tokens\n(one per line)").grid(
            row=4, column=0, sticky="nw", padx=(0, 8), pady=3
        )
        self.missing_text = tk.Text(rules, height=3, wrap="none")
        self.missing_text.grid(row=4, column=1, sticky="ew", pady=3)
        ttk.Label(rules, text="Rule notes").grid(row=5, column=0, sticky="nw", padx=(0, 8), pady=3)
        self.notes_text = tk.Text(rules, height=3, wrap="word")
        self.notes_text.grid(row=5, column=1, sticky="ew", pady=3)
        ttk.Label(
            rules,
            text="Saving records these rules; it does not run validation or change source values.",
            foreground=MUTED,
        ).grid(row=6, column=0, columnspan=2, sticky="w", pady=(5, 0))

        footer = ttk.Frame(page)
        footer.grid(row=4, sticky="ew", pady=(10, 0))
        footer.columnconfigure(0, weight=1)
        self.status_label = ttk.Label(footer, textvariable=self.status, wraplength=470)
        self.status_label.grid(row=0, column=0, sticky="ew")
        self.remove_button = ttk.Button(
            footer,
            text="Remove definition",
            command=self.remove,
            state="normal" if self.existing else "disabled",
        )
        self.remove_button.grid(row=0, column=1, padx=(8, 0))
        ttk.Button(footer, text="Close", command=self.close).grid(row=0, column=2, padx=(8, 0))
        self.save_button = ttk.Button(
            footer,
            text="Save definition",
            command=self.save,
            state="normal" if self.fields_by_choice else "disabled",
        )
        self.save_button.grid(row=0, column=3, padx=(8, 0))

    def _field_choice(self, definition: ColumnDefinition) -> str | None:
        for label, item in self.fields_by_choice.items():
            if item is None:
                continue
            pack = (
                next((value for value in self.catalog.packs if value.id == item.pack_id), None)
                if self.catalog
                else None
            )
            if (
                item.id == definition.field.id
                and pack is not None
                and pack.fingerprint == definition.field.pack_fingerprint
            ):
                return label
        return None

    def _load(self) -> None:
        if self.catalog_error:
            self.status.set(self.catalog_error)
            self.status_label.configure(foreground=ERROR)
            return
        if not self.fields_by_choice:
            self.status.set(
                "No dictionary fields are active. Activate a pack in Dictionary packs, then reopen this window."
            )
            self.status_label.configure(foreground=ERROR)
        if self.existing is None:
            return
        choice = self._field_choice(self.existing)
        if choice is None:
            choice = (
                f"Saved: {self.existing.field.label} — {self.existing.field.id} "
                f"({self.existing.field.pack_version}; not active)"
            )
            self.fields_by_choice = {choice: None, **self.fields_by_choice}
            self.meaning_selector.configure(values=tuple(self.fields_by_choice))
            self.status.set(
                "The exact saved dictionary version is not active. Choose an active meaning to update it, or remove it."
            )
        self.meaning.set(choice)
        self._show_snapshot(self.existing.field)
        self.currency.set(self.existing.currency or "")
        self.source_unit.set(self.existing.source_unit or "")
        self.date_format.set(_format_choice(self.existing.date_formats))
        self.short_year.set(
            str(self.existing.two_digit_year_start)
            if self.existing.two_digit_year_start is not None
            else ""
        )
        self.required.set(_choice_for(self.existing.rules.required, REQUIRED_CHOICES))
        self.blank_allowed.set(_choice_for(self.existing.rules.blank_allowed, BLANK_CHOICES))
        self.unique.set(_choice_for(self.existing.rules.unique, UNIQUE_CHOICES))
        self.minimum.set(self.existing.rules.minimum or "")
        self.maximum.set(self.existing.rules.maximum or "")
        self.missing_text.insert("1.0", "\n".join(self.existing.rules.missing_tokens))
        self.notes_text.insert("1.0", self.existing.rules.notes or "")
        self._set_type_controls(self.existing.field.data_type)

    def _selected_field(self) -> CatalogField | None:
        return self.fields_by_choice.get(self.meaning.get())

    def _select_field(self, event: tk.Event[tk.Misc] | None = None) -> None:
        selected = self._selected_field()
        if selected is None or self.catalog is None:
            return
        snapshot = snapshot_field(self.catalog, selected)
        self._show_snapshot(snapshot)
        self._set_type_controls(snapshot.data_type)
        self.currency.set("")
        self.source_unit.set(snapshot.canonical_unit or "")
        self.date_format.set("YYYY-MM-DD" if snapshot.data_type == "date" else "")
        self.short_year.set("")
        self.minimum.set("")
        self.maximum.set("")
        self.required.set("Use dictionary setting")
        self.blank_allowed.set("Use dictionary setting")
        self.unique.set("Not specified")
        self.status.set("")
        self.status_label.configure(foreground="")

    def _show_snapshot(self, snapshot: FieldSnapshot) -> None:
        self.definition_text.configure(state="normal")
        self.definition_text.delete("1.0", "end")
        self.definition_text.insert("1.0", snapshot.definition)
        self.definition_text.configure(state="disabled")
        unit = snapshot.canonical_unit or "not specified"
        self.type_summary.set(
            f"Expected type: {snapshot.data_type} · Canonical unit: {unit} · "
            f"Dictionary: {snapshot.pack_id} {snapshot.pack_version}"
        )
        required = (
            "required"
            if snapshot.dictionary_required is True
            else "not required"
            if snapshot.dictionary_required is False
            else "required not specified"
        )
        blanks = (
            "blanks allowed"
            if snapshot.dictionary_blank_allowed is True
            else "blanks not allowed"
            if snapshot.dictionary_blank_allowed is False
            else "blank rule not specified"
        )
        codes = (
            f" · {len(snapshot.allowed_values):,} allowed values" if snapshot.allowed_values else ""
        )
        self.dictionary_rules.set(f"Dictionary defaults: {required}; {blanks}{codes}.")

    def _set_type_controls(self, data_type: str) -> None:
        numeric = data_type in {"integer", "decimal"}
        self.currency_entry.configure(state="normal" if numeric else "disabled")
        self.unit_entry.configure(state="normal" if numeric else "disabled")
        self.minimum_entry.configure(state="normal" if numeric else "disabled")
        self.maximum_entry.configure(state="normal" if numeric else "disabled")
        self.date_selector.configure(state="readonly" if data_type == "date" else "disabled")
        self.short_year_entry.configure(state="normal" if data_type == "date" else "disabled")

    def _text_lines(self, widget: tk.Text) -> tuple[str, ...]:
        return tuple(line for line in widget.get("1.0", "end-1c").splitlines() if line)

    def save(self) -> None:
        selected = self._selected_field()
        if selected is None or self.catalog is None:
            self.status.set("Choose a meaning from an active dictionary pack.")
            self.status_label.configure(foreground=ERROR)
            return
        try:
            snapshot = snapshot_field(self.catalog, selected)
            formats = FORMAT_PRESETS.get(self.date_format.get(), ())
            short_year_text = self.short_year.get().strip()
            short_year = int(short_year_text) if short_year_text else None
            definition = ColumnDefinition(
                column=self.column,
                source_header=self.source_header,
                field=snapshot,
                currency=self.currency.get().strip().upper() or None,
                source_unit=self.source_unit.get().strip() or None,
                date_formats=formats,
                two_digit_year_start=short_year,
                rules=ColumnRules(
                    REQUIRED_CHOICES[self.required.get()],
                    BLANK_CHOICES[self.blank_allowed.get()],
                    UNIQUE_CHOICES[self.unique.get()],
                    self.minimum.get().strip() or None,
                    self.maximum.get().strip() or None,
                    self._text_lines(self.missing_text),
                    self.notes_text.get("1.0", "end-1c").strip() or None,
                ),
            )
            save_column_definition(self.table, definition)
        except (KeyError, OSError, ValueError) as error:
            self.status.set(str(error))
            self.status_label.configure(foreground=ERROR)
            return
        self.existing = definition
        self.remove_button.configure(state="normal")
        self.status.set(
            f"Saved {column_label(self.column)} as {definition.field.label}. The source workbook was not changed."
        )
        self.status_label.configure(foreground="")
        if self.on_change is not None:
            self.on_change()

    def remove(self) -> None:
        if self.existing is None:
            return
        if not messagebox.askyesno(
            "Remove column definition?",
            f"Remove the saved definition for column {column_label(self.column)}?",
            parent=self.window,
        ):
            return
        try:
            removed = remove_column_definition(self.table, self.column)
        except (OSError, ValueError) as error:
            self.status.set(str(error))
            self.status_label.configure(foreground=ERROR)
            return
        if removed:
            self.existing = None
            self.remove_button.configure(state="disabled")
            self.status.set("Column definition removed. The source workbook was not changed.")
            self.status_label.configure(foreground="")
            if self.on_change is not None:
                self.on_change()

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self.window.winfo_exists():
            self.window.destroy()
