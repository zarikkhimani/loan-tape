"""Native review of complete-column text cleanup with explicit per-cell choices."""

from __future__ import annotations

import json
import queue
import threading
import tkinter as tk
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from tkinter import ttk
from typing import TYPE_CHECKING, Any

from loan_tape.column_definitions import DefinitionScope, snapshot_field
from loan_tape.packs import PackStore
from loan_tape.ranges import column_label
from loan_tape.selection import SavedTable
from loan_tape.text_cleanup import (
    TextCleanupReview,
    TextCleanupSettings,
    apply_excel_text,
    cleanup_scope,
    review_excel_text,
)
from loan_tape.text_rule_types import ExactRulesSettings
from loan_tape.text_rules_ui import TextRulesWindow
from loan_tape.transformations import MAX_PAGE_SIZE, TransformationApproval, TransformationRevision
from loan_tape.workers import WorkerGroup

if TYPE_CHECKING:
    from loan_tape.recipe_ui import RecipeWindow
    from loan_tape.text_export_ui import TextExportWindow


class TextCleanupWindow:
    def __init__(
        self,
        owner: tk.Misc,
        source: Path,
        table: SavedTable,
        column: int,
        store: PackStore,
        current_table: Callable[[], SavedTable],
        jump: Callable[[SavedTable, int, int], None],
        workers: WorkerGroup,
        on_applied: Callable[[TransformationRevision | None], None],
        parent: TransformationRevision | None = None,
    ) -> None:
        # A recipe result can destroy this window inside its polling callback.
        # Keep the callback registered on the surviving owner until Tk retires it.
        self.poll_owner = owner
        self.window = tk.Toplevel(owner)
        self.window.title(f"Clean text - {table.name}")
        self.window.geometry("1120x780")
        self.window.minsize(860, 680)
        self.window.transient(owner.winfo_toplevel())
        self.source, self.table, self.column, self.store = source, table, column, store
        self.current_table, self.jump, self.workers, self.on_applied = (
            current_table,
            jump,
            workers,
            on_applied,
        )
        self.parent = parent
        self.parent_steps = len(parent.to_dict()["steps"]) if parent else 0
        self.review: TextCleanupReview | None = None
        self.request_scope: DefinitionScope | None = None
        self.records: list[dict[str, Any]] = []
        self.selected: set[tuple[int, int]] = set()
        self.results: queue.Queue[
            tuple[int, TextCleanupReview | tuple[TransformationRevision, Path | None] | Exception]
        ] = queue.Queue()
        self.closed = self.busy = self.applied = False
        self.allowed = False
        self.generation = self.offset = 0
        self.cancelled = threading.Event()
        self.mode = tk.StringVar(self.window, "Repair text")
        self.exact_settings = ExactRulesSettings()
        self.rule_scope: DefinitionScope | None = None
        self.rule_editor: TextRulesWindow | None = None
        self.recipe_window: RecipeWindow | None = None
        self.export_window: TextExportWindow | None = None
        self.rule_summary = tk.StringVar(self.window, "0 exact rules")
        self.repair = tk.BooleanVar(self.window, True)
        self.normalize = tk.BooleanVar(self.window, False)
        self.filter = tk.StringVar(self.window, "Proposed changes")
        self.reviewer = tk.StringVar(self.window)
        self.justification = tk.StringVar(self.window)
        self.status = tk.StringVar(
            self.window, "Choose settings, then preview the complete data set."
        )
        self.summary = tk.StringVar(self.window)
        self.page_label = tk.StringVar(self.window)
        self.chosen = tk.StringVar(self.window, "0 changes chosen")
        self.result_label = tk.StringVar(self.window)
        self._build()
        self.traces = (
            (self.mode, self.mode.trace_add("write", self._mode_changed)),
            (self.repair, self.repair.trace_add("write", self._settings_changed)),
            (self.normalize, self.normalize.trace_add("write", self._settings_changed)),
            (self.filter, self.filter.trace_add("write", self._filter_changed)),
        )
        self._refresh_context()
        self._buttons()
        self.poll_id = self.poll_owner.after(100, self._poll)
        self.window.protocol("WM_DELETE_WINDOW", self.close)

    def _build(self) -> None:
        page = ttk.Frame(self.window, padding=16)
        page.pack(fill="both", expand=True)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(4, weight=1)
        ttk.Label(page, text="Review text cleanup", font=("Segoe UI", 17, "bold")).grid(
            row=0, sticky="w"
        )
        ttk.Label(
            page,
            text=f"{self.table.name} | {self.table.selection.sheet}!{column_label(self.column)} | {self.table.selection.area.address}",
        ).grid(row=1, sticky="w", pady=(4, 8))
        settings = ttk.Frame(page)
        settings.grid(row=2, sticky="ew")
        operation = ttk.Frame(settings)
        operation.pack(fill="x", pady=(0, 4))
        self.mode_box = ttk.Combobox(
            operation,
            textvariable=self.mode,
            values=("Repair text", "Exact replacements"),
            width=20,
            state="readonly",
        )
        self.mode_box.pack(side="left", padx=(0, 8))
        self.rule_button = ttk.Button(
            operation, text="Edit rules / spelling", command=self.open_rules
        )
        self.rule_button.pack(side="left")
        ttk.Label(operation, textvariable=self.rule_summary).pack(side="left", padx=8)
        self.recipe_button = ttk.Button(operation, text="Recipes", command=self.open_recipes)
        self.recipe_button.pack(side="left", padx=6)
        options = ttk.Frame(settings)
        options.pack(fill="x")
        self.repair_check = ttk.Checkbutton(
            options, text="Repair garbled characters", variable=self.repair
        )
        self.repair_check.pack(side="left")
        self.normalize_check = ttk.Checkbutton(
            options, text="Combine equivalent Unicode characters (NFC)", variable=self.normalize
        )
        self.normalize_check.pack(side="left", padx=12)
        self.preview_button = ttk.Button(options, text="Preview cleanup", command=self.run_preview)
        self.preview_button.pack(side="left")
        self.cancel_button = ttk.Button(options, text="Cancel", command=self.cancel)
        self.cancel_button.pack(side="left", padx=6)
        info = ttk.Frame(page)
        info.grid(row=3, sticky="ew", pady=8)
        ttk.Label(
            info,
            text="Repair text preserves conventions. Exact rules change only literal matches. Review every proposed change.",
            wraplength=1020,
        ).pack(anchor="w")
        ttk.Label(info, textvariable=self.summary, wraplength=1020).pack(anchor="w", pady=(4, 0))
        grid_frame = ttk.Frame(page)
        grid_frame.grid(row=4, sticky="nsew")
        grid_frame.columnconfigure(0, weight=1)
        grid_frame.rowconfigure(1, weight=1)
        bar = ttk.Frame(grid_frame)
        bar.grid(row=0, columnspan=2, sticky="ew", pady=(0, 6))
        ttk.Combobox(
            bar,
            textvariable=self.filter,
            values=("Proposed changes", "All mapped cells"),
            state="readonly",
            width=20,
        ).pack(side="left")
        self.include_button = ttk.Button(
            bar, text="Include selected changes", command=self.include_selected
        )
        self.include_button.pack(side="left", padx=(8, 4))
        self.remove_button = ttk.Button(bar, text="Remove selected", command=self.remove_selected)
        self.remove_button.pack(side="left")
        self.clear_button = ttk.Button(bar, text="Clear choices", command=self.clear_choices)
        self.clear_button.pack(side="left", padx=4)
        ttk.Label(bar, textvariable=self.chosen).pack(side="right")
        names = ("apply", "cell", "outcome", "before", "after")
        self.grid = ttk.Treeview(
            grid_frame, columns=names, show="headings", selectmode="extended", height=9
        )
        for key, title, width in zip(
            names,
            ("Apply", "Source cell", "Outcome", "Current text", "Proposed text"),
            (55, 90, 105, 320, 320),
            strict=True,
        ):
            self.grid.heading(key, text=title)
            self.grid.column(key, width=width, minwidth=45, stretch=key in {"before", "after"})
        self.grid.grid(row=1, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(grid_frame, command=self.grid.yview)
        vertical.grid(row=1, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(grid_frame, orient="horizontal", command=self.grid.xview)
        horizontal.grid(row=2, column=0, sticky="ew")
        self.grid.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.grid.bind("<<TreeviewSelect>>", self._show_detail)
        nav = ttk.Frame(page)
        nav.grid(row=5, sticky="ew", pady=6)
        self.previous = ttk.Button(nav, text="Previous", command=lambda: self.change_page(-1))
        self.previous.pack(side="left")
        ttk.Label(nav, textvariable=self.page_label).pack(side="left", padx=10)
        self.next = ttk.Button(nav, text="Next", command=lambda: self.change_page(1))
        self.next.pack(side="left")
        self.jump_button = ttk.Button(nav, text="Jump to source cell", command=self.jump_selected)
        self.jump_button.pack(side="right")
        self.detail = tk.Text(page, height=7, wrap="word", state="disabled")
        self.detail.grid(row=6, sticky="ew")
        attribution = ttk.Frame(page)
        attribution.grid(row=7, sticky="ew", pady=8)
        attribution.columnconfigure(3, weight=1)
        ttk.Label(attribution, text="Reviewer").grid(row=0, column=0, padx=(0, 6))
        self.reviewer_entry = ttk.Entry(attribution, textvariable=self.reviewer, width=20)
        self.reviewer_entry.grid(row=0, column=1, padx=(0, 12))
        ttk.Label(attribution, text="Reason for changes").grid(row=0, column=2, padx=(0, 6))
        self.reason_entry = ttk.Entry(attribution, textvariable=self.justification)
        self.reason_entry.grid(row=0, column=3, sticky="ew")
        footer = ttk.Frame(page)
        footer.grid(row=8, sticky="ew")
        self.apply_button = ttk.Button(
            footer, text="Apply selected changes", command=self.apply_selected
        )
        self.apply_button.pack(side="left")
        self.reset_button = ttk.Button(
            footer, text="Start from source", command=self.start_from_source
        )
        self.reset_button.pack(side="left", padx=8)
        self.export_button = ttk.Button(
            footer, text="Export reviewed result...", command=self.open_export
        )
        self.export_button.pack(side="left", padx=4)
        ttk.Button(footer, text="Close", command=self.close).pack(side="right")
        ttk.Label(page, textvariable=self.result_label, wraplength=1020).grid(
            row=9, sticky="ew", pady=(6, 0)
        )
        ttk.Label(
            page,
            text="Original workbook unchanged. Session results clear on Exit; explicit workbook exports are retained.",
            wraplength=1020,
        ).grid(row=10, sticky="ew", pady=4)
        ttk.Label(page, textvariable=self.status, wraplength=1020).grid(row=11, sticky="ew")

    def _settings(self) -> TextCleanupSettings | ExactRulesSettings:
        if self.mode.get() == "Exact replacements":
            return self.exact_settings
        return TextCleanupSettings(self.repair.get(), "NFC" if self.normalize.get() else None)

    def _buttons(self) -> None:
        editing = (
            (self.rule_editor is not None and not self.rule_editor.closed)
            or (self.recipe_window is not None and not self.recipe_window.closed)
            or (self.export_window is not None and not self.export_window.closed)
        )
        idle = not self.busy and not editing
        for control in (
            self.repair_check,
            self.normalize_check,
            self.reviewer_entry,
            self.reason_entry,
        ):
            control.configure(state="normal" if idle else "disabled")
        exact = self.mode.get() == "Exact replacements"
        self.mode_box.configure(state="readonly" if idle else "disabled")
        self.recipe_button.configure(state="normal" if idle else "disabled")
        self.rule_button.configure(
            state="normal" if idle and exact and self.allowed else "disabled"
        )
        self.repair_check.configure(state="normal" if idle and not exact else "disabled")
        self.normalize_check.configure(state="normal" if idle and not exact else "disabled")
        self.rule_summary.set(f"{len(self.exact_settings.rules)} exact rules")
        self.preview_button.configure(state="normal" if self.allowed and idle else "disabled")
        self.cancel_button.configure(state="normal" if self.busy else "disabled")
        ready = self.review is not None and idle and not self.applied
        for button in (self.include_button, self.remove_button, self.clear_button):
            button.configure(state="normal" if ready else "disabled")
        self.apply_button.configure(state="normal" if ready and self.selected else "disabled")
        self.reset_button.configure(
            state="normal" if self.parent is not None and idle else "disabled"
        )
        self.export_button.configure(
            state="normal" if self.parent is not None and idle else "disabled"
        )
        self.chosen.set(f"{len(self.selected):,} changes chosen")
        steps = self.parent_steps
        self.result_label.set(
            f"Working result: {steps} reviewed step(s)."
            if steps
            else "Working from original source evidence."
        )

    def _invalidate(self, message: str) -> None:
        self.generation += 1
        if self.busy:
            self.cancelled.set()
        self.review = None
        self.records.clear()
        self.selected.clear()
        self.applied = False
        self.summary.set("")
        self.status.set(message)
        self._render()
        self._buttons()

    def _settings_changed(self, *_: str) -> None:
        self._invalidate("Settings changed. Preview again; no changes are selected.")

    def _mode_changed(self, *_: str) -> None:
        self._settings_changed()
        self._refresh_context()
        self._buttons()

    def open_rules(self) -> None:
        if self.busy:
            return
        self._refresh_context()
        if not self.allowed or self.mode.get() != "Exact replacements":
            return
        if self.rule_editor is not None and not self.rule_editor.closed:
            self.rule_editor.window.lift()
            return
        keys = self._keys()
        initial = next(
            (
                item["input_text"]
                for item in self.records
                if (item["row"], item["column"]) in keys
                and item["column"] == self.column
                and item["outcome"] in {"changed", "unchanged"}
            ),
            "",
        )
        self.rule_editor = TextRulesWindow(self, initial)
        self._buttons()

    def open_recipes(self) -> None:
        if self.busy:
            return
        if self.recipe_window is not None and not self.recipe_window.closed:
            self.recipe_window.window.lift()
            return
        from loan_tape.recipe_ui import RecipeWindow

        self.recipe_window = RecipeWindow(self)
        self._buttons()

    def accept_rules(self, settings: ExactRulesSettings, scope: DefinitionScope) -> None:
        self.exact_settings, self.rule_scope = settings, scope
        self._invalidate(
            "Rules changed. Preview the complete data set and choose changes explicitly."
        )

    def open_export(self) -> None:
        if self.busy or self.parent is None:
            return
        if self.export_window is not None and not self.export_window.closed:
            self.export_window.window.lift()
            return
        from loan_tape.text_export_ui import TextExportWindow

        self.export_window = TextExportWindow(self)
        self._buttons()

    def _filter_changed(self, *_: str) -> None:
        self.offset = 0
        self._render()

    def _refresh_context(self) -> None:
        try:
            if self.current_table() != self.table:
                raise ValueError(
                    "Data set changed. Return to this saved data set or reopen Clean text."
                )
            scope = cleanup_scope(
                self.table, self.column, exact=self.mode.get() == "Exact replacements"
            )
            if self.rule_scope is not None and scope != self.rule_scope:
                self.exact_settings, self.rule_scope = ExactRulesSettings(), None
                self._invalidate(
                    "Column mappings changed. Exact rules and approval choices were cleared."
                )
            catalog = self.store.catalog()
            for definition in scope.definitions:
                if (
                    snapshot_field(catalog, catalog.get_field(definition.field.id))
                    != definition.field
                ):
                    raise ValueError(
                        "Active dictionary changed. Review column definitions and preview again."
                    )
            if self.review is not None and scope != self.review.scope:
                self._invalidate(
                    "Column mappings changed. Preview again; use Start from source if a prior result no longer matches."
                )
            if self.busy and self.request_scope is not None and scope != self.request_scope:
                self._invalidate("Column mappings changed during processing. Preview again.")
            self.allowed = True
        except (ValueError, OSError) as error:
            if self.allowed or self.review is not None:
                self._invalidate(str(error))
            self.allowed = False
            self.status.set(str(error))

    def _start(
        self,
        action: Callable[[], TextCleanupReview | tuple[TransformationRevision, Path | None]],
        name: str,
    ) -> None:
        self.busy = True
        generation = self.generation
        self._buttons()

        def work() -> None:
            try:
                result: (
                    TextCleanupReview | tuple[TransformationRevision, Path | None] | Exception
                ) = action()
            except Exception as error:
                result = error
            self.results.put((generation, result))

        self.workers.start(work, name, self.cancelled)

    def run_preview(self) -> None:
        if self.busy:
            return
        self._refresh_context()
        if not self.allowed:
            return
        try:
            settings = self._settings()
            self.request_scope = cleanup_scope(
                self.table, self.column, exact=isinstance(settings, ExactRulesSettings)
            )
        except ValueError as error:
            self.status.set(str(error))
            return
        self._invalidate("Reading the complete data set and preparing proposals...")
        self.cancelled = threading.Event()
        parent, cancelled = self.parent, self.cancelled
        self._start(
            lambda: self._review_current(settings, parent, cancelled),
            "text-cleanup-preview",
        )

    def _review_current(
        self,
        settings: TextCleanupSettings | ExactRulesSettings,
        parent: TransformationRevision | None,
        cancelled: threading.Event,
    ) -> TextCleanupReview:
        return review_excel_text(
            self.source,
            self.table,
            self.column,
            settings,
            self.store,
            parent=parent,
            cancelled=cancelled,
        )

    def _apply_current(
        self,
        settings: TextCleanupSettings | ExactRulesSettings,
        review: TextCleanupReview,
        approval: TransformationApproval,
        parent: TransformationRevision | None,
        cancelled: threading.Event,
    ) -> tuple[TransformationRevision, Path | None]:
        return apply_excel_text(
            self.source,
            self.table,
            self.column,
            settings,
            self.store,
            review,
            approval,
            parent=parent,
            cancelled=cancelled,
        )

    def _filtered(self) -> list[dict[str, Any]]:
        return [
            item
            for item in self.records
            if self.filter.get() == "All mapped cells" or item["outcome"] == "changed"
        ]

    def _render(self) -> None:
        self.grid.delete(*self.grid.get_children())
        filtered = self._filtered()
        self.offset = min(self.offset, max(0, (len(filtered) - 1) // MAX_PAGE_SIZE * MAX_PAGE_SIZE))
        for item in filtered[self.offset : self.offset + MAX_PAGE_SIZE]:
            key = item["row"], item["column"]
            self.grid.insert(
                "",
                "end",
                iid=f"{key[0]}:{key[1]}",
                values=(
                    "Yes" if key in self.selected else "",
                    f"{column_label(key[1])}{key[0]}",
                    item["outcome"],
                    self._display(item["input_text"]),
                    self._display(item["proposed_text"]),
                ),
            )
        end = min(len(filtered), self.offset + MAX_PAGE_SIZE)
        self.page_label.set(f"{self.offset + 1 if filtered else 0}-{end} of {len(filtered):,}")
        self.previous.configure(state="normal" if self.offset else "disabled")
        self.next.configure(state="normal" if end < len(filtered) else "disabled")
        self.jump_button.configure(state="disabled")
        self._detail("")

    @staticmethod
    def _display(value: str | None) -> str:
        # Grid excerpts are display-only; Details retains complete escaped literals.
        if value is None:
            return ""
        text = repr(value)
        return text if len(text) <= 180 else text[:177] + "..."

    def change_page(self, direction: int) -> None:
        self.offset = max(0, self.offset + direction * MAX_PAGE_SIZE)
        self._render()

    def _keys(self) -> set[tuple[int, int]]:
        return {tuple(map(int, item.split(":"))) for item in self.grid.selection()}  # type: ignore[misc]

    def include_selected(self) -> None:
        if self.busy or self.applied or self.review is None:
            return
        choices = self._keys()
        self.selected.update(
            (item["row"], item["column"])
            for item in self.records
            if item["outcome"] == "changed" and (item["row"], item["column"]) in choices
        )
        self._render()
        self._buttons()

    def remove_selected(self) -> None:
        if self.busy or self.applied:
            return
        self.selected.difference_update(self._keys())
        self._render()
        self._buttons()

    def clear_choices(self) -> None:
        if self.busy or self.applied:
            return
        self.selected.clear()
        self._render()
        self._buttons()

    def _detail(self, text: str) -> None:
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", text)
        self.detail.configure(state="disabled")

    def _show_detail(self, event: tk.Event[tk.Misc] | None = None) -> None:
        keys = self._keys()
        if len(keys) != 1 or self.review is None:
            self.jump_button.configure(state="disabled")
            return
        row, column = next(iter(keys))
        decision = next(
            item for item in self.records if (item["row"], item["column"]) == (row, column)
        )
        cell = next(
            item
            for item in self.review.snapshot.to_dict()["cells"]
            if (item["row"], item["column"]) == (row, column)
        )
        self._detail(
            f"Source: {self.table.selection.sheet}!{column_label(column)}{row}\n"
            f"Current: {decision['input_text']!r}\nProposed: {decision['proposed_text']!r}\n"
            f"Outcome: {decision['outcome']} | {decision['reason']}\n"
            f"Original evidence: {json.dumps(cell['evidence'], ensure_ascii=True)}"
        )
        self.jump_button.configure(state="normal" if not self.busy else "disabled")

    def jump_selected(self) -> None:
        keys = self._keys()
        if len(keys) == 1 and not self.busy:
            row, column = next(iter(keys))
            try:
                self.jump(self.table, column, row)
            except (ValueError, OSError) as error:
                self.status.set(str(error))

    def apply_selected(self) -> None:
        if self.busy or self.applied:
            return
        self._refresh_context()
        if (
            not self.allowed
            or self.review is None
            or not self._can_approve_empty()
            and not self.selected
        ):
            self._buttons()
            return
        try:
            settings = self._settings()
            approval = TransformationApproval(
                self.review.preview.id,
                tuple(sorted(self.selected)),
                self.reviewer.get(),
                self.justification.get(),
                datetime.now(UTC).isoformat(),
            )
        except ValueError as error:
            self.status.set(str(error))
            return
        review, parent = self.review, self.parent
        self.cancelled = threading.Event()
        cancelled = self.cancelled
        self.request_scope = review.scope
        self.status.set(
            "Rechecking source, settings and mappings before applying chosen changes..."
        )
        self._start(
            lambda: self._apply_current(settings, review, approval, parent, cancelled),
            "text-cleanup-apply",
        )

    def _can_approve_empty(self) -> bool:
        return False

    def _received_application(self, revision: TransformationRevision, path: Path | None) -> None:
        self.parent = revision
        self.parent_steps = len(revision.to_dict()["steps"])
        self.applied = True
        self.on_applied(self.parent)
        self.status.set(
            f"Applied {len(self.selected):,} chosen changes to a separate session result. The workbook is unchanged."
        )

    def _received_error(self, error: Exception) -> None:
        self._invalidate(f"Cleanup stopped: {error}")

    def start_from_source(self) -> None:
        if not self.busy:
            self.parent = None
            self.parent_steps = 0
            self.on_applied(None)
            self._invalidate(
                "Working from the original source. Previous session evidence is retained; preview again."
            )

    def cancel(self) -> None:
        if self.busy:
            self._invalidate("Cancellation requested. Waiting for the owned worker to finish...")

    def _poll(self) -> None:
        if self.closed:
            return
        self._refresh_context()
        try:
            while True:
                generation, result = self.results.get_nowait()
                self.busy = False
                if generation != self.generation:
                    continue
                if isinstance(result, TextCleanupReview):
                    self.review = result
                    self.records = result.preview.to_dict()["decisions"]
                    totals = result.preview.to_dict()["reconciliation"]
                    self.summary.set(
                        f"{totals['row_count']:,} rows | {totals['mapped_cell_count']:,} mapped cells | "
                        f"{totals['changed']:,} changes proposed | {totals['unchanged']:,} unchanged | "
                        f"{totals['ineligible']:,} excluded | {totals['unresolved']:,} unresolved | {totals['failed']:,} failed"
                    )
                    self.selected.clear()
                    self.offset = 0
                    self.status.set(
                        "No changes selected. Highlight rows and use Include selected changes after reviewing them."
                    )
                    self._render()
                elif isinstance(result, Exception):
                    self._received_error(result)
                else:
                    self._received_application(*result)
                if self.closed:
                    return
        except queue.Empty:
            pass
        self._buttons()
        self.poll_id = self.poll_owner.after(100, self._poll)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self.recipe_window is not None:
            self.recipe_window.close()
        if self.export_window is not None:
            self.export_window.close()
        if self.rule_editor is not None:
            self.rule_editor.close()
        self.cancelled.set()
        self.poll_owner.after_cancel(self.poll_id)
        for variable, command in self.traces:
            variable.trace_remove("write", command)
        self.window.destroy()
