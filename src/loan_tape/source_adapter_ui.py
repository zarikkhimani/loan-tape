"""Native complete-scope mapping and reviewed text workflow for CSV and XML."""

from __future__ import annotations

import json
import queue
import threading
import tkinter as tk
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Any

from loan_tape.column_definition_ui import ColumnDefinitionWindow, DefinitionEditorContext
from loan_tape.column_definitions import ColumnDefinition, snapshot_field
from loan_tape.flow_ui import FlowBar
from loan_tape.packs import PackStore
from loan_tape.source_adapters import (
    AdapterReview,
    AdapterScope,
    apply_review,
    create_csv_scope,
    create_xml_scope,
    export_audit,
    load_scopes,
    read_scope_records,
    review_source,
    save_mapping,
)
from loan_tape.source_records import CSV_ENCODINGS, SourceRecords
from loan_tape.text_cleanup import TextCleanupSettings
from loan_tape.text_rule_types import ExactRule, ExactRulesSettings
from loan_tape.transformations import TransformationApproval, TransformationRevision
from loan_tape.workbook_index import _digest
from loan_tape.workers import WorkerGroup
from loan_tape.xml_selection import SavedXmlTable

PAGE_SIZE = 50
SEPARATORS = {"Comma": ",", "Semicolon": ";", "Tab": "\t", "Pipe": "|"}


class SourceAdapterWindow:
    def __init__(
        self,
        owner: tk.Misc,
        source: Path,
        store: PackStore,
        workers: WorkerGroup,
        *,
        xml_table: SavedXmlTable | None = None,
        current_xml: Callable[[], SavedXmlTable] | None = None,
        jump_xml: Callable[[SavedXmlTable, int, int], None] | None = None,
    ) -> None:
        self.source, self.store, self.workers = source, store, workers
        self.xml_table, self.current_xml, self.jump_xml = xml_table, current_xml, jump_xml
        self.window = tk.Toplevel(owner)
        self.window.title("CSV / XML text review")
        self.window.geometry("1120x820")
        self.window.minsize(860, 700)
        self.window.transient(owner.winfo_toplevel())
        self.scope: AdapterScope | None = None
        self.scopes: dict[str, AdapterScope] = {}
        self.records: SourceRecords | None = None
        self.review: AdapterReview | None = None
        self.parent: TransformationRevision | None = None
        self.editor: ColumnDefinitionWindow | None = None
        self.chosen: set[tuple[int, int]] = set()
        self.closed = self.busy = self.invalid = False
        self.offset = self.generation = 0
        self.cancelled = threading.Event()
        self.results: queue.Queue[tuple[int, Any, Callable[[Any], None]]] = queue.Queue()
        self.name = tk.StringVar(self.window, "CSV data set")
        self.encoding = tk.StringVar(self.window, "utf-8-sig")
        self.separator = tk.StringVar(self.window, "Comma")
        self.header = tk.BooleanVar(self.window, False)
        self.saved = tk.StringVar(self.window)
        self.field = tk.StringVar(self.window)
        self.mode = tk.StringVar(self.window, "Repair text")
        self.normalize = tk.BooleanVar(self.window, False)
        self.exact_from = tk.StringVar(self.window)
        self.exact_to = tk.StringVar(self.window)
        self.reviewer = tk.StringVar(self.window)
        self.reason = tk.StringVar(self.window)
        self.view = tk.StringVar(self.window, "Source records")
        self.summary = tk.StringVar(self.window)
        self.status = tk.StringVar(
            self.window, "Choose and save an explicit complete source scope."
        )
        self.page = tk.StringVar(self.window)
        self._build()
        self.traces = [
            (variable, variable.trace_add("write", self._settings_changed))
            for variable in (self.field, self.mode, self.normalize, self.exact_from, self.exact_to)
        ]
        self.view.trace_add("write", lambda *_: self.change_page(0))
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.poll_id = self.window.after(100, self._poll)
        self._load()

    def _build(self) -> None:
        page = ttk.Frame(self.window, padding=14)
        page.pack(fill="both", expand=True)
        ttk.Label(page, text="Review CSV / XML text", font=("Segoe UI", 17, "bold")).pack(
            anchor="w"
        )
        ttk.Label(
            page,
            text="Complete saved scope → explicit field meaning → proposals → chosen changes",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(0, 8))
        self.setup = FlowBar(page)
        self.setup.pack(fill="x")
        self.setup_controls: list[ttk.Entry | ttk.Combobox | ttk.Checkbutton] = []
        if self.xml_table is None:
            for label, variable, values in (
                ("New name", self.name, None),
                ("Encoding", self.encoding, CSV_ENCODINGS),
                ("Separator", self.separator, tuple(SEPARATORS)),
            ):
                group = ttk.Frame(self.setup)
                ttk.Label(group, text=label).pack(side="left", padx=(0, 5))
                control = (
                    ttk.Entry(group, textvariable=variable, width=21)
                    if values is None
                    else ttk.Combobox(
                        group, textvariable=variable, values=values, state="readonly", width=13
                    )
                )
                control.pack(side="left")
                self.setup_controls.append(control)
                self.setup.add(group)
            box = ttk.Checkbutton(self.setup, text="First record is headers", variable=self.header)
            self.setup_controls.append(box)
            self.setup.add(box)
        self.save_button = ttk.Button(
            self.setup,
            text="Save complete data set" if self.xml_table is None else "Reload saved XML group",
            command=self.save_data_set,
        )
        self.setup.add(self.save_button)
        scope_row = FlowBar(page)
        scope_row.pack(fill="x", pady=6)
        self.scope_box = ttk.Combobox(
            scope_row, textvariable=self.saved, state="readonly", width=38
        )
        self.scope_box.bind("<<ComboboxSelected>>", lambda _: self.load_selected())
        scope_row.add(self.scope_box)
        self.reload_button = ttk.Button(scope_row, text="Reload scopes", command=self._load)
        scope_row.add(self.reload_button)
        self.field_box = ttk.Combobox(
            scope_row, textvariable=self.field, state="readonly", width=35
        )
        scope_row.add(self.field_box)
        self.map_button = ttk.Button(scope_row, text="Define field", command=self.define_field)
        scope_row.add(self.map_button)
        ttk.Label(page, textvariable=self.summary, wraplength=1000).pack(anchor="w")
        settings = FlowBar(page)
        settings.pack(fill="x", pady=6)
        self.mode_box = ttk.Combobox(
            settings,
            textvariable=self.mode,
            values=("Repair text", "Exact replacement"),
            state="readonly",
            width=19,
        )
        settings.add(self.mode_box)
        self.normalize_box = ttk.Checkbutton(
            settings, text="Also normalize Unicode to NFC", variable=self.normalize
        )
        settings.add(self.normalize_box)
        self.preview_button = ttk.Button(
            settings, text="Preview whole scope", command=self.preview_changes
        )
        settings.add(self.preview_button)
        self.reset_button = ttk.Button(settings, text="Start from source", command=self.reset)
        settings.add(self.reset_button)
        exact = ttk.Frame(page)
        exact.pack(fill="x")
        ttk.Label(exact, text="Exact source").pack(side="left")
        self.from_entry = ttk.Entry(exact, textvariable=self.exact_from, width=35)
        self.from_entry.pack(side="left", fill="x", expand=True, padx=6)
        ttk.Label(exact, text="Replace with").pack(side="left")
        self.to_entry = ttk.Entry(exact, textvariable=self.exact_to, width=35)
        self.to_entry.pack(side="left", fill="x", expand=True, padx=6)
        views = FlowBar(page)
        views.pack(fill="x", pady=6)
        self.view_box = ttk.Combobox(
            views,
            textvariable=self.view,
            values=("Source records", "Proposed changes", "All outcomes"),
            state="readonly",
            width=20,
        )
        views.add(self.view_box)
        self.previous = ttk.Button(views, text="Previous", command=lambda: self.change_page(-1))
        self.next = ttk.Button(views, text="Next", command=lambda: self.change_page(1))
        views.add(self.previous)
        views.add(self.next)
        views.add(ttk.Label(views, textvariable=self.page))
        self.include = ttk.Button(
            views, text="Include selected changes", command=self.include_selected
        )
        self.remove = ttk.Button(
            views, text="Remove selected changes", command=self.remove_selected
        )
        views.add(self.include)
        views.add(self.remove)
        self.jump_button = ttk.Button(views, text="Show source record", command=self.show_source)
        views.add(self.jump_button)
        grid_frame = ttk.Frame(page)
        grid_frame.pack(fill="both", expand=True)
        self.grid = ttk.Treeview(
            grid_frame,
            columns=("record", "field", "state", "original", "proposed", "choice"),
            show="headings",
            height=9,
            selectmode="extended",
        )
        for key, title, width in (
            ("record", "Record", 65),
            ("field", "Field", 60),
            ("state", "State / outcome", 140),
            ("original", "Literal source / current text", 270),
            ("proposed", "Proposed text", 260),
            ("choice", "Included", 65),
        ):
            self.grid.heading(key, text=title)
            self.grid.column(key, width=width, minwidth=45)
        scroll = ttk.Scrollbar(grid_frame, orient="vertical", command=self.grid.yview)
        self.grid.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.grid.pack(fill="both", expand=True)
        self.grid.bind("<<TreeviewSelect>>", lambda _: self.show_details())
        self.details = tk.Text(page, height=5, wrap="word", state="disabled")
        self.details.pack(fill="x", pady=5)
        review_row = FlowBar(page)
        review_row.pack(fill="x")
        for label, variable in (("Reviewer", self.reviewer), ("Reason", self.reason)):
            group = ttk.Frame(review_row)
            ttk.Label(group, text=label).pack(side="left")
            ttk.Entry(group, textvariable=variable, width=26).pack(side="left", padx=6)
            review_row.add(group)
        self.apply_button = ttk.Button(
            review_row, text="Apply chosen changes", command=self.apply_changes
        )
        review_row.add(self.apply_button)
        self.audit_button = ttk.Button(
            review_row, text="Save JSON audit...", command=self.save_audit
        )
        review_row.add(self.audit_button)
        self.cancel_button = ttk.Button(review_row, text="Cancel work", command=self.cancel)
        review_row.add(self.cancel_button)
        ttk.Label(page, textvariable=self.status, wraplength=1000).pack(anchor="w", pady=5)
        ttk.Label(
            page,
            text="Originals stay unchanged. Recipes, borrower matching and workbook/date exports remain Excel-only.",
            style="Muted.TLabel",
            wraplength=1000,
        ).pack(anchor="w")
        self._buttons()

    def _start(self, action: Callable[[], Any], done: Callable[[Any], None]) -> None:
        if self.busy or self.closed:
            return
        self.busy = True
        self.cancelled = threading.Event()
        generation = self.generation
        self._buttons()

        def work() -> None:
            try:
                result = action()
            except Exception as error:
                result = error
            self.results.put((generation, result, done))

        self.workers.start(work, "source-adapter", self.cancelled)

    def _load(self) -> None:
        if self.xml_table is not None:
            self.save_data_set()
        else:
            self._start(
                lambda: load_scopes(_digest(self.source, self.cancelled)), self._loaded_scopes
            )

    def _loaded_scopes(
        self, scopes: tuple[AdapterScope, ...], selected_id: str | None = None
    ) -> None:
        scopes = tuple(
            item
            for item in scopes
            if (
                item.id == self.xml_table.id if self.xml_table else item.metadata["format"] == "csv"
            )
        )
        self.scopes = {f"{item.name} ({item.id[:8]})": item for item in scopes}
        self.scope_box.configure(values=tuple(self.scopes))
        if self.scopes:
            self.saved.set(
                next(
                    (key for key, value in self.scopes.items() if value.id == selected_id),
                    next(iter(self.scopes)),
                )
            )
            self.load_selected()
        else:
            self.status.set(
                "Choose explicit CSV conventions, then Save complete data set. No header or field meaning is inferred."
            )

    def save_data_set(self) -> None:
        if self.busy:
            return
        name, encoding, delimiter, header = (
            self.name.get(),
            self.encoding.get(),
            SEPARATORS[self.separator.get()],
            self.header.get(),
        )
        table = self.xml_table
        self.status.set("Reading the entire source before saving its scope...")
        self._start(
            lambda: (
                create_xml_scope(self.source, table, cancelled=self.cancelled)
                if table
                else create_csv_scope(
                    self.source, name, encoding, delimiter, header, cancelled=self.cancelled
                )
            ),
            self._saved_scope,
        )

    def _saved_scope(self, scope: AdapterScope) -> None:
        self._loaded_scopes(load_scopes(scope.source_sha256), scope.id)

    def load_selected(self) -> None:
        if self.busy:
            return
        scope = self.scopes.get(self.saved.get())
        if scope is None:
            return
        self.reset()
        self.scope = scope
        self.records = None
        self.invalid = False
        self.field_box.configure(
            values=tuple(
                f"{i}: {label or '(no header)'}"
                for i, label in enumerate(scope.metadata["headers"], 1)
            )
        )
        self.field.set(str(self.field_box["values"][0]))
        self._start(
            lambda: read_scope_records(self.source, scope, cancelled=self.cancelled),
            self._received_records,
        )

    def _received_records(self, records: SourceRecords) -> None:
        self.records = records
        data = json.loads(records.metadata_json)
        self.summary.set(
            f"{data['format'].upper()}: {data['record_count']:,} source records; {data['field_count']:,} fields. "
            f"Data starts at record {data['first_data_record']}. Scope covers the entire file / saved group."
        )
        self.status.set(
            "Choose a source field and Define field before cleanup. Every record is available below."
        )
        self.view.set("Source records")
        self._render()

    def column(self) -> int:
        return int(self.field.get().split(":", 1)[0])

    def define_field(self) -> None:
        if self.busy or self.scope is None or self.invalid:
            return
        if self.editor is not None and not self.editor.closed:
            self.editor.window.lift()
            return
        scope, column = self.scope, self.column()

        def save(definition: ColumnDefinition | None) -> None:
            nonlocal scope
            scope = save_mapping(self.source, scope, definition, column, self.store)
            self.scope = scope
            self.scopes[self.saved.get()] = scope
            self.reset()
            self.status.set(
                "Mapping saved. Preview a new complete population; prior approvals were cleared."
            )

        def remove() -> bool:
            save(None)
            return True

        context = DefinitionEditorContext(
            f"{scope.name} | {scope.metadata['format'].upper()} field {column}",
            next((item for item in scope.definitions if item.column == column), None),
            save,
            remove,
        )
        self.editor = ColumnDefinitionWindow(
            self.window,
            None,
            column,
            scope.metadata["headers"][column - 1],
            self.store,
            context=context,
        )
        self._buttons()

    def settings(self) -> TextCleanupSettings | ExactRulesSettings:
        if self.mode.get() == "Exact replacement":
            return ExactRulesSettings((ExactRule(self.exact_from.get(), self.exact_to.get()),))
        return TextCleanupSettings(normalization="NFC" if self.normalize.get() else None)

    def preview_changes(self) -> None:
        if self.busy or self.scope is None or self.invalid:
            return
        try:
            settings, column = self.settings(), self.column()
        except ValueError as error:
            self.status.set(str(error))
            return
        scope, parent = self.scope, self.parent
        self._settings_changed()
        self.status.set("Reading all mapped records and generating proposals...")
        self._start(
            lambda: review_source(
                self.source,
                scope,
                column,
                settings,
                self.store,
                parent=parent,
                cancelled=self.cancelled,
            ),
            self._received_review,
        )

    def _received_review(self, review: AdapterReview) -> None:
        self.review = review
        self.chosen.clear()
        totals = review.preview.to_dict()["reconciliation"]
        self.summary.set(
            f"{totals['row_count']:,} data records; {totals['mapped_cell_count']:,} mapped cells; "
            f"{totals['changed']:,} proposed; {totals['ineligible']:,} excluded; "
            f"{totals['unresolved']:,} unresolved; {totals['failed']:,} failed."
        )
        self.view.set("Proposed changes")
        self.status.set(
            "Review original evidence, select rows and Include selected changes. Nothing is selected automatically."
        )
        self._render()

    def _rows(self) -> list[dict[str, Any]]:
        if self.view.get() != "Source records":
            decisions = self.review.preview.to_dict()["decisions"] if self.review else []
            return [
                item
                for item in decisions
                if self.view.get() == "All outcomes" or item["outcome"] == "changed"
            ]
        if self.records is None or not self.field.get():
            return []
        column = self.column()
        return [
            {
                "row": row,
                "column": column,
                "outcome": item[column - 1]["state"],
                "input_text": item[column - 1]["evidence"]["raw"],
                "proposed_text": None,
            }
            for row, item in enumerate(self.records.rows, 1)
        ]

    def _render(self) -> None:
        rows = self._rows()
        self.offset = min(self.offset, max(0, (len(rows) - 1) // PAGE_SIZE * PAGE_SIZE))
        self.grid.delete(*self.grid.get_children())
        for item in rows[self.offset : self.offset + PAGE_SIZE]:
            key = item["row"], item["column"]
            self.grid.insert(
                "",
                "end",
                iid=f"{key[0]}:{key[1]}",
                values=(
                    key[0],
                    key[1],
                    item["outcome"],
                    repr(item["input_text"])[:180],
                    repr(item["proposed_text"])[:180],
                    "Yes" if key in self.chosen else "",
                ),
            )
        self.page.set(
            f"{self.offset + 1 if rows else 0}-{min(len(rows), self.offset + PAGE_SIZE)} of {len(rows):,}; {len(self.chosen):,} included"
        )
        self.previous.configure(state="normal" if self.offset else "disabled")
        self.next.configure(state="normal" if self.offset + PAGE_SIZE < len(rows) else "disabled")
        self.show_details()
        self._buttons()

    def change_page(self, direction: int) -> None:
        self.offset = max(0, self.offset + direction * PAGE_SIZE) if direction else 0
        self._render()

    def _keys(self) -> set[tuple[int, int]]:
        result = set()
        for key in self.grid.selection():
            row, column = map(int, key.split(":"))
            result.add((row, column))
        return result

    def show_source(self) -> None:
        keys = self._keys()
        if self.busy or len(keys) != 1 or self.invalid:
            return
        row, column = next(iter(keys))
        if self.xml_table and self.jump_xml:
            try:
                self.jump_xml(self.xml_table, column, row)
            except (ValueError, OSError) as error:
                self.status.set(str(error))
        else:
            if self.column() != column:
                self.field.set(str(self.field_box["values"][column - 1]))
            self.view.set("Source records")
            self.offset = (row - 1) // PAGE_SIZE * PAGE_SIZE
            self._render()
            self.grid.selection_set(f"{row}:{column}")
            self.grid.see(f"{row}:{column}")

    def include_selected(self) -> None:
        if self.review and not self.busy:
            changed = {
                (item["row"], item["column"])
                for item in self.review.preview.to_dict()["decisions"]
                if item["outcome"] == "changed"
            }
            self.chosen.update(self._keys() & changed)
            self._render()

    def remove_selected(self) -> None:
        if not self.busy:
            self.chosen.difference_update(self._keys())
            self._render()

    def show_details(self) -> None:
        text = "Select a record to inspect its full literal evidence and native source location."
        keys = self._keys()
        if len(keys) == 1 and self.records:
            row, column = next(iter(keys))
            text = json.dumps(self.records.rows[row - 1][column - 1], ensure_ascii=False, indent=2)
            if self.review:
                decision = next(
                    (
                        item
                        for item in self.review.preview.to_dict()["decisions"]
                        if (item["row"], item["column"]) == (row, column)
                    ),
                    None,
                )
                text += "\n" + json.dumps(decision, ensure_ascii=False, indent=2)
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", text)
        self.details.configure(state="disabled")

    def apply_changes(self) -> None:
        if self.busy or self.invalid or self.review is None or not self.chosen:
            return
        try:
            settings, column = self.settings(), self.column()
            approval = TransformationApproval(
                self.review.preview.id,
                tuple(sorted(self.chosen)),
                self.reviewer.get(),
                self.reason.get(),
                datetime.now(UTC).isoformat(),
            )
        except ValueError as error:
            self.status.set(str(error))
            return
        review, parent = self.review, self.parent
        self._start(
            lambda: apply_review(
                self.source,
                review,
                column,
                settings,
                approval,
                self.store,
                parent=parent,
                cancelled=self.cancelled,
            ),
            self._applied,
        )

    def _applied(self, result: tuple[TransformationRevision, Path]) -> None:
        self.parent = result[0]
        self._settings_changed()
        self.status.set(
            f"Saved {len(self.parent.to_dict()['steps'])} reviewed step(s). Original source unchanged. Save JSON audit to retain evidence after Exit."
        )

    def save_audit(self) -> None:
        if self.busy or self.invalid or self.scope is None or self.parent is None:
            return
        selected = filedialog.asksaveasfilename(
            parent=self.window, defaultextension=".json", filetypes=(("JSON audit", "*.json"),)
        )
        if selected:
            scope, parent = self.scope, self.parent
            self._start(
                lambda: export_audit(
                    self.source, scope, self.store, parent, Path(selected), cancelled=self.cancelled
                ),
                lambda path: self.status.set(f"Verified audit saved: {path}"),
            )

    def _settings_changed(self, *_: str) -> None:
        self.review = None
        self.chosen.clear()
        self.offset = 0
        self._render()

    def reset(self) -> None:
        if self.busy:
            return
        self.parent = None
        self._settings_changed()

    def _buttons(self) -> None:
        editing = self.editor is not None and not self.editor.closed
        idle = not self.busy and not editing
        ready = idle and self.scope is not None and self.records is not None and not self.invalid
        for control in self.setup_controls:
            control.configure(
                state=("readonly" if isinstance(control, ttk.Combobox) else "normal")
                if idle
                else "disabled"
            )
        self.save_button.configure(state="normal" if idle else "disabled")
        self.reload_button.configure(state="normal" if idle else "disabled")
        self.scope_box.configure(state="readonly" if idle else "disabled")
        self.field_box.configure(state="readonly" if ready else "disabled")
        self.mode_box.configure(state="readonly" if ready else "disabled")
        self.map_button.configure(state="normal" if ready else "disabled")
        self.preview_button.configure(state="normal" if ready else "disabled")
        exact = self.mode.get() == "Exact replacement"
        self.normalize_box.configure(state="normal" if ready and not exact else "disabled")
        for control in (self.from_entry, self.to_entry):
            control.configure(state="normal" if ready and exact else "disabled")
        for button in (self.include, self.remove):
            button.configure(state="normal" if ready and self.review else "disabled")
        self.apply_button.configure(
            state="normal" if ready and self.review and self.chosen else "disabled"
        )
        for button in (self.audit_button, self.reset_button):
            button.configure(state="normal" if ready and self.parent else "disabled")
        self.cancel_button.configure(state="normal" if self.busy else "disabled")
        self.jump_button.configure(state="normal" if ready else "disabled")

    def cancel(self) -> None:
        self.generation += 1
        self.cancelled.set()
        self._settings_changed()
        self.status.set("Cancellation requested; waiting for owned work to finish.")

    def _poll(self) -> None:
        if self.closed:
            return
        try:
            while True:
                generation, result, done = self.results.get_nowait()
                self.busy = False
                if generation != self.generation:
                    continue
                if isinstance(result, Exception):
                    self.status.set(str(result))
                    self.review = None
                    self.chosen.clear()
                else:
                    try:
                        done(result)
                    except (ValueError, OSError) as error:
                        self.invalid = True
                        self.review = None
                        self.chosen.clear()
                        self.status.set(str(error))
        except queue.Empty:
            pass
        if self.scope is not None and not self.invalid:
            try:
                if self.current_xml and self.current_xml() != self.xml_table:
                    raise ValueError(
                        "XML group changed. Reopen text review for the current saved group."
                    )
                if self.scope not in load_scopes(self.scope.source_sha256):
                    raise ValueError("Saved mappings changed. Reload the saved scope.")
                catalog = self.store.catalog()
                if self.review is not None and any(
                    snapshot_field(catalog, catalog.get_field(item.field.id)) != item.field
                    for item in self.scope.definitions
                ):
                    raise ValueError(
                        "Active dictionary changed. Review mappings and preview again."
                    )
            except (ValueError, OSError) as error:
                self.invalid = True
                self.cancel()
                self.status.set(str(error))
        self._buttons()
        self.poll_id = self.window.after(200, self._poll)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.cancelled.set()
        if self.editor is not None:
            self.editor.close()
        self.window.after_cancel(self.poll_id)
        for variable, command in self.traces:
            variable.trace_remove("write", command)
        self.window.destroy()
