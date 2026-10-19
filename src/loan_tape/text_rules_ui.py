"""Session-only literal rule drafts and explicit, bounded spelling suggestions."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from dataclasses import asdict
from tkinter import ttk
from typing import TYPE_CHECKING
from weakref import proxy

from loan_tape.text_cleanup import cleanup_scope, suggest_excel_text
from loan_tape.text_rule_types import ExactRule, ExactRulesSettings, free_text, validate_rule_field
from loan_tape.text_rules import SpellingSettings, SpellingSuggestions
from loan_tape.transformations import MAX_PAGE_SIZE

if TYPE_CHECKING:
    from loan_tape.text_cleanup_ui import TextCleanupWindow


class TextRulesWindow:
    def __init__(self, owner: TextCleanupWindow, initial: str = "") -> None:
        self.owner = proxy(owner)
        self.scope = cleanup_scope(owner.table, owner.column, exact=True)
        self.definition = next(d for d in self.scope.definitions if d.column == owner.column)
        self.parent_id = owner.parent.id if owner.parent else None
        self.rules = owner.exact_settings
        self.window = tk.Toplevel(owner.window)
        self.window.title("Spelling suggestions and exact rules")
        self.window.geometry("1000x820")
        self.window.minsize(860, 740)
        self.window.transient(owner.window)
        self.closed = self.busy = self.stale = False
        self.generation = self.offset = 0
        self.cancelled = threading.Event()
        self.results: queue.Queue[tuple[int, SpellingSuggestions | Exception]] = queue.Queue()
        self.suggestions: SpellingSuggestions | None = None
        self.threshold = tk.StringVar(self.window, "85")
        self.comparison = tk.StringVar(self.window, "literal")
        self.status = tk.StringVar(
            self.window,
            "Type exact source/replacement text, or find similar values for a source spelling.",
        )
        self.page_label = tk.StringVar(self.window)
        self._build(initial)
        self.traces = (
            (self.threshold, self.threshold.trace_add("write", self._invalidate)),
            (self.comparison, self.comparison.trace_add("write", self._invalidate)),
        )
        self.source_text.bind("<<Modified>>", self._source_changed)
        self.source_text.edit_modified(False)
        self._render_rules()
        self._render_candidates()
        self._buttons()
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.poll_id = self.window.after(100, self._poll)

    def _build(self, initial: str) -> None:
        page = ttk.Frame(self.window, padding=14)
        page.pack(fill="both", expand=True)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(3, weight=1)
        page.rowconfigure(7, weight=1)
        ttk.Label(
            page,
            text=f"{self.owner.table.name} | {self.definition.field.label}",
            font=("Segoe UI", 14, "bold"),
        ).grid(sticky="w")
        literals = ttk.Frame(page)
        literals.grid(row=1, sticky="ew", pady=6)
        literals.columnconfigure(0, weight=1)
        literals.columnconfigure(1, weight=1)
        ttk.Label(literals, text="Exact source text (spaces and line breaks count)").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(literals, text="Exact replacement text").grid(row=0, column=1, sticky="w")
        self.source_text = tk.Text(literals, height=2, width=30, wrap="none")
        self.target_text = tk.Text(literals, height=2, width=30, wrap="none")
        self.source_text.grid(row=1, column=0, sticky="ew", padx=(0, 8))
        self.target_text.grid(row=1, column=1, sticky="ew")
        self.source_text.insert("1.0", initial)
        actions = ttk.Frame(page)
        actions.grid(row=2, sticky="ew")
        self.add_button = ttk.Button(actions, text="Add exact rule", command=self.add_manual)
        self.add_button.pack(side="left")
        self.remove_button = ttk.Button(
            actions, text="Remove selected rules", command=self.remove_rules
        )
        self.remove_button.pack(side="left", padx=6)
        ttk.Label(actions, text="Rules are simultaneous within one step. Maximum 200.").pack(
            side="left", padx=8
        )
        self.rule_grid = ttk.Treeview(
            page, columns=("source", "target", "origin"), show="headings", height=5
        )
        for key, label, width in (
            ("source", "Exact source", 310),
            ("target", "Exact replacement", 310),
            ("origin", "Origin", 130),
        ):
            self.rule_grid.heading(key, text=label)
            self.rule_grid.column(key, width=width, minwidth=65)
        self.rule_grid.grid(row=3, sticky="nsew", pady=6)
        rule_scroll = ttk.Scrollbar(page, command=self.rule_grid.yview)
        rule_scroll.grid(row=3, column=1, sticky="ns")
        self.rule_grid.configure(yscrollcommand=rule_scroll.set)
        self.rule_grid.bind("<<TreeviewSelect>>", self._rule_detail)
        compare = ttk.Frame(page)
        compare.grid(row=4, sticky="ew", pady=6)
        ttk.Label(compare, text="Minimum similarity").pack(side="left")
        self.threshold_entry = ttk.Entry(compare, textvariable=self.threshold, width=5)
        self.threshold_entry.pack(side="left", padx=6)
        self.comparison_box = ttk.Combobox(
            compare,
            textvariable=self.comparison,
            values=("literal", "nfc-casefold"),
            width=15,
            state="readonly",
        )
        self.comparison_box.pack(side="left")
        self.find_button = ttk.Button(compare, text="Find similar spellings", command=self.find)
        self.find_button.pack(side="left", padx=8)
        self.cancel_button = ttk.Button(compare, text="Cancel search", command=self.cancel)
        self.cancel_button.pack(side="left")
        ttk.Label(
            page,
            text="Scores compare spelling, not borrower identity. Comparison settings never change the exact rule text.",
            wraplength=810,
        ).grid(row=5, sticky="w")
        navigation = ttk.Frame(page)
        navigation.grid(row=6, sticky="ew", pady=5)
        self.previous = ttk.Button(
            navigation, text="Previous", command=lambda: self.change_page(-1)
        )
        self.previous.pack(side="left")
        ttk.Label(navigation, textvariable=self.page_label).pack(side="left", padx=8)
        self.next = ttk.Button(navigation, text="Next", command=lambda: self.change_page(1))
        self.next.pack(side="left")
        self.candidate_button = ttk.Button(
            navigation, text="Use selected as replacement", command=self.add_candidate
        )
        self.candidate_button.pack(side="right")
        self.candidates = ttk.Treeview(
            page,
            columns=("text", "score", "count", "row"),
            show="headings",
            height=6,
            selectmode="browse",
        )
        for key, title, width in (
            ("text", "Candidate spelling", 460),
            ("score", "Similarity", 90),
            ("count", "Occurrences", 90),
            ("row", "First source row", 110),
        ):
            self.candidates.heading(key, text=title)
            self.candidates.column(key, width=width, minwidth=65)
        self.candidates.grid(row=7, sticky="nsew")
        scroll = ttk.Scrollbar(page, command=self.candidates.yview)
        scroll.grid(row=7, column=1, sticky="ns")
        self.candidates.configure(yscrollcommand=scroll.set)
        self.candidates.bind("<<TreeviewSelect>>", self._candidate_detail)
        self.detail = tk.Text(page, height=4, wrap="word", state="disabled")
        self.detail.grid(row=8, sticky="ew", pady=6)
        self.allowed_label = ttk.Label(
            page,
            text=(
                "Free text: spelling candidates come only from this column's current eligible values."
                if free_text(asdict(self.definition.field))
                else "Category: exact replacements must be in the frozen allowed-value list. Spelling search is disabled."
            ),
            wraplength=810,
        )
        self.allowed_label.grid(row=9, sticky="w")
        footer = ttk.Frame(page)
        footer.grid(row=10, sticky="ew", pady=6)
        self.use_button = ttk.Button(footer, text="Use rules for preview", command=self.use_rules)
        self.use_button.pack(side="left")
        ttk.Button(footer, text="Show allowed values", command=self.show_allowed).pack(
            side="left", padx=8
        )
        ttk.Button(footer, text="Cancel", command=self.close).pack(side="right")
        self.status_label = ttk.Label(page, textvariable=self.status, wraplength=810)
        self.status_label.grid(row=11, sticky="ew")

    def _query(self) -> str:
        return self.source_text.get("1.0", "end-1c")

    def _settings(self) -> SpellingSettings:
        return SpellingSettings(int(self.threshold.get()), self.comparison.get())

    def _buttons(self) -> None:
        editable = not self.busy and not self.stale
        for widget in (
            self.source_text,
            self.target_text,
            self.threshold_entry,
            self.add_button,
            self.remove_button,
            self.use_button,
        ):
            widget.configure(state="normal" if editable else "disabled")
        self.comparison_box.configure(state="readonly" if editable else "disabled")
        self.find_button.configure(
            state="normal" if editable and free_text(asdict(self.definition.field)) else "disabled"
        )
        self.cancel_button.configure(state="normal" if self.busy else "disabled")
        self.candidate_button.configure(
            state="normal"
            if editable and self.suggestions and self.candidates.selection()
            else "disabled"
        )

    def _invalidate(self, *_: str) -> None:
        self.generation += 1
        self.cancelled.set()
        self.suggestions = None
        self.offset = 0
        self._render_candidates()
        self._buttons()

    def _source_changed(self, event: tk.Event[tk.Misc]) -> None:
        if self.source_text.edit_modified():
            self.source_text.edit_modified(False)
            self._invalidate()

    def _context(self) -> bool:
        try:
            if (
                self.owner.closed
                or self.owner.current_table() != self.owner.table
                or cleanup_scope(self.owner.table, self.owner.column, exact=True) != self.scope
                or (self.owner.parent.id if self.owner.parent else None) != self.parent_id
                or not self.owner.allowed
            ):
                raise ValueError(
                    "Data set, mappings, dictionary or working result changed. Close this editor and reopen it."
                )
        except (ValueError, OSError) as error:
            if not self.stale:
                self.stale = True
                self._invalidate()
            self.status.set(str(error))
        return not self.stale

    def _add(self, rule: ExactRule) -> None:
        if self.busy or not self._context():
            return
        rules = ExactRulesSettings((*self.rules.rules, rule))
        validate_rule_field(asdict(self.definition), rules)
        self.rules = rules
        self._render_rules()
        self.status.set(
            f"{len(rules.rules)} rule(s) drafted. Use rules for preview, then choose individual changes to apply."
        )

    def add_manual(self) -> None:
        try:
            self._add(ExactRule(self._query(), self.target_text.get("1.0", "end-1c")))
        except ValueError as error:
            self.status.set(str(error))

    def add_candidate(self) -> None:
        if self.suggestions is None or not self.candidates.selection():
            return
        try:
            if (
                self._query() != self.suggestions.query
                or self._settings() != self.suggestions.settings
            ):
                raise ValueError("Spelling settings changed; search again.")
            self._add(self.suggestions.rule(int(self.candidates.selection()[0])))
        except ValueError as error:
            self.status.set(str(error))

    def remove_rules(self) -> None:
        if self.busy or self.stale:
            return
        chosen = {int(key) for key in self.rule_grid.selection()}
        self.rules = ExactRulesSettings(
            tuple(rule for index, rule in enumerate(self.rules.rules) if index not in chosen)
        )
        self._render_rules()

    def _render_rules(self) -> None:
        self.rule_grid.delete(*self.rule_grid.get_children())
        for index, rule in enumerate(self.rules.rules):
            self.rule_grid.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    self.owner._display(rule.source),
                    self.owner._display(rule.target),
                    "Reviewed suggestion" if rule.suggestion else "Manual",
                ),
            )

    def _detail(self, value: str) -> None:
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", value)
        self.detail.configure(state="disabled")

    def _rule_detail(self, event: tk.Event[tk.Misc]) -> None:
        selected = self.rule_grid.selection()
        if len(selected) == 1:
            rule = self.rules.rules[int(selected[0])]
            self._detail(
                f"Exact source: {rule.source!r}\nExact replacement: {rule.target!r}\nRule: {rule.id}\nSuggestion evidence: {rule.suggestion!r}"
            )

    def _candidate_detail(self, event: tk.Event[tk.Misc]) -> None:
        if self.suggestions is not None and self.candidates.selection():
            candidate = self.suggestions.candidates[int(self.candidates.selection()[0])]
            self._detail(
                f"Source spelling: {self.suggestions.query!r}\nCandidate: {candidate.text!r}\nSimilarity: {candidate.score!r}; occurrences: {candidate.count}; first source row: {candidate.first_row}.\nNo rule is chosen automatically."
            )
        self._buttons()

    def show_allowed(self) -> None:
        values = self.definition.field.allowed_values
        self._detail(
            "\n".join(f"{value.value!r}: {value.label} | {value.definition}" for value in values)
            if values
            else "This free-text field has no allowed-value list."
        )

    def _render_candidates(self) -> None:
        self.candidates.delete(*self.candidates.get_children())
        total = len(self.suggestions.candidates) if self.suggestions else 0
        if self.suggestions:
            for index, item in enumerate(self.suggestions.page(self.offset), self.offset):
                self.candidates.insert(
                    "",
                    "end",
                    iid=str(index),
                    values=(
                        self.owner._display(item.text),
                        f"{item.score:.2f}",
                        item.count,
                        item.first_row,
                    ),
                )
        end = min(total, self.offset + MAX_PAGE_SIZE)
        self.page_label.set(f"{self.offset + 1 if total else 0}-{end} of {total:,}")
        self.previous.configure(state="normal" if self.offset else "disabled")
        self.next.configure(state="normal" if end < total else "disabled")
        self._detail("")

    def change_page(self, direction: int) -> None:
        if self.suggestions:
            last = max(0, (len(self.suggestions.candidates) - 1) // MAX_PAGE_SIZE * MAX_PAGE_SIZE)
            self.offset = min(last, max(0, self.offset + direction * MAX_PAGE_SIZE))
            self._render_candidates()
            self._buttons()

    def find(self) -> None:
        if self.busy or not self._context():
            return
        try:
            query, settings = self._query(), self._settings()
        except ValueError as error:
            self.status.set(str(error))
            return
        self._invalidate()
        self.cancelled = threading.Event()
        cancelled, results, generation = self.cancelled, self.results, self.generation
        owner = self.owner
        source, table, column, store, parent = (
            owner.source,
            owner.table,
            owner.column,
            owner.store,
            owner.parent,
        )
        self.busy = True
        self._buttons()
        self.status.set("Reading the complete column and comparing eligible spellings...")

        def work() -> None:
            try:
                result: SpellingSuggestions | Exception = suggest_excel_text(
                    source,
                    table,
                    column,
                    query,
                    settings,
                    store,
                    parent=parent,
                    cancelled=cancelled,
                )
            except Exception as error:
                result = error
            results.put((generation, result))

        owner.workers.start(work, "spelling-suggestions", cancelled)

    def cancel(self) -> None:
        if self.busy:
            self._invalidate()
            self.status.set("Cancellation requested; waiting for the owned worker.")

    def _poll(self) -> None:
        if self.closed:
            return
        self.owner._refresh_context()
        self._context()
        try:
            generation, result = self.results.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            if generation == self.generation and not self.stale:
                if isinstance(result, Exception):
                    self.status.set(f"Spelling search stopped: {result}")
                else:
                    self.suggestions = result
                    self._render_candidates()
                    self.status.set(
                        f"{result.eligible_count:,} eligible cells, {result.distinct_count:,} distinct values, {len(result.candidates):,} candidates. Select a candidate explicitly to draft a rule."
                    )
        self._buttons()
        self.poll_id = self.window.after(100, self._poll)

    def use_rules(self) -> None:
        if self.busy or not self._context():
            return
        self.owner.accept_rules(self.rules, self.scope)
        self.close()

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.cancelled.set()
        self.window.after_cancel(self.poll_id)
        for variable, command in self.traces:
            variable.trace_remove("write", command)
        self.window.destroy()
        if not self.owner.closed:
            self.owner._buttons()
