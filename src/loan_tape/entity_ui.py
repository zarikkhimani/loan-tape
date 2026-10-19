"""Native borrower pair labeling, candidate review and explicit JSON audit export."""

from __future__ import annotations

import json
import queue
import threading
import tkinter as tk
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Any

from loan_tape.entities import (
    EntityPopulation,
    EntityRun,
    PairLabel,
    eligible_field,
    review_relationships,
)
from loan_tape.entity_matching import (
    entity_scope,
    population_guard,
    publish_bytes,
    read_population,
    runtime_python,
    train_entities,
)
from loan_tape.packs import PackStore
from loan_tape.ranges import column_label
from loan_tape.selection import SavedTable
from loan_tape.transformations import TransformationRevision
from loan_tape.workers import WorkerGroup

PAGE = 50


class EntityWindow:
    def __init__(
        self,
        owner: tk.Misc,
        source: Path,
        table: SavedTable,
        store: PackStore,
        current_table: Callable[[], SavedTable],
        jump: Callable[[SavedTable, int, int], None],
        workers: WorkerGroup,
        parent: TransformationRevision | None = None,
    ) -> None:
        self.window = tk.Toplevel(owner)
        self.window.title(f"Match borrowers - {table.name}")
        self.window.geometry("1120x820")
        self.window.minsize(940, 720)
        self.window.transient(owner.winfo_toplevel())
        self.source, self.table, self.store = source, table, store
        self.current_table, self.jump, self.workers = current_table, jump, workers
        self.parent = parent
        self.population: EntityPopulation | None = None
        self.run: EntityRun | None = None
        self.columns: tuple[int, ...] = ()
        self.labels: dict[tuple[int, int], PairLabel] = {}
        self.decisions: dict[str, str] = {}
        self.rows: dict[int, dict[str, Any]] = {}
        self.pairs: list[tuple[int, int]] = []
        self.items: dict[str, Any] = {}
        self.offset = 0
        self.closed = self.busy = self.invalid = False
        self.cancelled = threading.Event()
        self.results: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.scope = entity_scope(table)
        self.catalog = store.catalog()
        self.features = [d for d in self.scope.definitions if eligible_field(asdict(d.field))]
        self.use_parent = tk.BooleanVar(self.window, False)
        self.representative = tk.BooleanVar(self.window, False)
        self.threshold = tk.StringVar(self.window, "0.5")
        self.reviewer = tk.StringVar(self.window)
        self.reason = tk.StringVar(self.window)
        self.view = tk.StringVar(self.window, "Label pairs")
        self.status = tk.StringVar(
            self.window, "Select borrower features, then prepare the full population."
        )
        self.summary = tk.StringVar(self.window)
        self.page = tk.StringVar(self.window)
        self.jump_row = tk.StringVar(self.window)
        self._build()
        if not self.features:
            self.status.set(
                "Use Define column to map a borrower text field, then reopen Match borrowers."
            )
        self.feature_list.bind("<<ListboxSelect>>", self.features_changed)
        self.parent_trace = self.use_parent.trace_add("write", self.features_changed)
        self.threshold_trace = self.threshold.trace_add("write", self.threshold_changed)
        self._buttons()
        self.poll_id = self.window.after(150, self._poll)
        self.window.protocol("WM_DELETE_WINDOW", self.close)

    def _build(self) -> None:
        body = ttk.Frame(self.window, padding=14)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(5, weight=1)
        ttk.Label(body, text="Review borrower relationships", font=("Segoe UI", 17, "bold")).grid(
            row=0, sticky="w"
        )
        ttk.Label(
            body,
            text="Loan rows, facilities, tranches, positions and reporting dates stay separate. Scores are model outputs; accuracy is unvalidated.",
            wraplength=1030,
        ).grid(row=1, sticky="w", pady=5)
        options = ttk.Frame(body)
        options.grid(row=2, sticky="ew")
        ttk.Label(options, text="Borrower fields\nCtrl+click to select").pack(
            side="left", padx=(0, 8)
        )
        self.feature_list = tk.Listbox(
            options, height=3, width=45, selectmode="extended", exportselection=False
        )
        self.feature_list.pack(side="left")
        for definition in self.features:
            self.feature_list.insert(
                "end",
                f"{column_label(definition.column)}: {definition.source_header} ({definition.field.data_type})",
            )
        actions = ttk.Frame(options)
        actions.pack(side="left", padx=10)
        self.parent_check = ttk.Checkbutton(
            actions, text="Use current reviewed text result", variable=self.use_parent
        )
        self.parent_check.pack(anchor="w")
        self.prepare_button = ttk.Button(
            actions, text="Prepare / restart labels", command=self.prepare
        )
        self.prepare_button.pack(anchor="w", pady=4)
        self.cancel_button = ttk.Button(options, text="Cancel work", command=self.cancel)
        self.cancel_button.pack(side="right")
        metadata = ttk.Frame(body)
        metadata.grid(row=3, sticky="ew", pady=8)
        ttk.Label(metadata, text="Reviewer").pack(side="left")
        self.reviewer_entry = ttk.Entry(metadata, textvariable=self.reviewer, width=20)
        self.reviewer_entry.pack(side="left", padx=6)
        ttk.Label(metadata, text="Reason / evidence").pack(side="left")
        self.reason_entry = ttk.Entry(metadata, textvariable=self.reason, width=65)
        self.reason_entry.pack(side="left", fill="x", expand=True, padx=6)
        bar = ttk.Frame(body)
        bar.grid(row=4, sticky="ew")
        box = ttk.Combobox(
            bar,
            textvariable=self.view,
            values=("Label pairs", "Review groups", "Excluded rows", "Unclustered rows"),
            state="readonly",
            width=18,
        )
        box.pack(side="left")
        box.bind("<<ComboboxSelected>>", lambda _: self.change_page(0))
        self.same_button = ttk.Button(
            bar, text="Same borrower", command=lambda: self.label("match")
        )
        self.different_button = ttk.Button(
            bar, text="Different borrowers", command=lambda: self.label("distinct")
        )
        self.approve_button = ttk.Button(
            bar, text="Approve group", command=lambda: self.decide("approve")
        )
        self.reject_button = ttk.Button(
            bar, text="Reject group", command=lambda: self.decide("reject")
        )
        for button in (
            self.same_button,
            self.different_button,
            self.approve_button,
            self.reject_button,
        ):
            button.pack(side="left", padx=3)
        grid_frame = ttk.Frame(body)
        grid_frame.grid(row=5, sticky="nsew", pady=6)
        grid_frame.columnconfigure(0, weight=1)
        grid_frame.rowconfigure(0, weight=1)
        self.grid = ttk.Treeview(
            grid_frame, columns=("rows", "decision", "values"), show="headings", selectmode="browse"
        )
        for key, title, width in (
            ("rows", "Source rows", 100),
            ("decision", "Review", 130),
            ("values", "Selected feature values", 650),
        ):
            self.grid.heading(key, text=title)
            self.grid.column(key, width=width, minwidth=60)
        self.grid.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(grid_frame, command=self.grid.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.grid.configure(yscrollcommand=scroll.set)
        horizontal = ttk.Scrollbar(grid_frame, orient="horizontal", command=self.grid.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self.grid.configure(xscrollcommand=horizontal.set)
        self.grid.bind("<<TreeviewSelect>>", self.detail_selected)
        nav = ttk.Frame(body)
        nav.grid(row=6, sticky="ew")
        self.previous = ttk.Button(nav, text="Previous", command=lambda: self.change_page(-1))
        self.previous.pack(side="left")
        self.next = ttk.Button(nav, text="Next", command=lambda: self.change_page(1))
        self.next.pack(side="left", padx=4)
        ttk.Label(nav, textvariable=self.page).pack(side="left", padx=8)
        ttk.Label(nav, text="Source row").pack(side="left", padx=(12, 4))
        ttk.Entry(nav, textvariable=self.jump_row, width=7).pack(side="left")
        ttk.Button(nav, text="Jump to source", command=self.jump_selected).pack(side="left", padx=4)
        self.detail = tk.Text(body, height=5, wrap="word", state="disabled")
        self.detail.grid(row=7, sticky="ew", pady=6)
        training = ttk.Frame(body)
        training.grid(row=8, sticky="ew")
        self.attest_check = ttk.Checkbutton(
            training,
            text="My labels represent this borrower population",
            variable=self.representative,
        )
        self.attest_check.pack(side="left")
        ttk.Label(training, text="Grouping threshold").pack(side="left", padx=(12, 4))
        self.threshold_entry = ttk.Entry(training, textvariable=self.threshold, width=6)
        self.threshold_entry.pack(side="left")
        self.train_button = ttk.Button(
            training, text="Train and propose groups", command=self.train
        )
        self.train_button.pack(side="left", padx=8)
        self.save_button = ttk.Button(
            body, text="Save reviewed relationships and audit...", command=self.save
        )
        self.save_button.grid(row=9, sticky="w", pady=6)
        ttk.Label(body, textvariable=self.summary, wraplength=1030).grid(row=10, sticky="w")
        ttk.Label(body, textvariable=self.status, wraplength=1030).grid(
            row=11, sticky="w", pady=(6, 0)
        )

    def _buttons(self) -> None:
        idle = not self.busy and not self.invalid
        self.prepare_button.configure(state="normal" if idle and self.features else "disabled")
        self.feature_list.configure(state="normal" if idle else "disabled")
        self.parent_check.configure(state="normal" if idle and self.parent else "disabled")
        for widget in (
            self.threshold_entry,
            self.attest_check,
            self.reviewer_entry,
            self.reason_entry,
        ):
            widget.configure(state="normal" if idle else "disabled")
        self.cancel_button.configure(state="normal" if self.busy else "disabled")
        for button in (self.same_button, self.different_button):
            button.configure(
                state="normal"
                if idle
                and self.population
                and self.run is None
                and self.view.get() == "Label pairs"
                else "disabled"
            )
        for button in (self.approve_button, self.reject_button):
            button.configure(
                state="normal"
                if idle and self.run and self.view.get() == "Review groups"
                else "disabled"
            )
        self.train_button.configure(state="normal" if idle and self.population else "disabled")
        self.save_button.configure(state="normal" if idle and self.run else "disabled")

    def features_changed(self, *_: Any) -> None:
        if self.busy or self.population is None:
            return
        selected = self._selected_columns()
        parent = self.parent if self.use_parent.get() else None
        if selected != self.columns or parent != self.selected_parent:
            self.population = self.run = None
            self.labels.clear()
            self.decisions.clear()
            self.rows.clear()
            self.pairs.clear()
            self.representative.set(False)
            self.render()
            self.status.set("Features changed. Prepare again and supply fresh labels.")

    def _start(self, kind: str, action: Callable[[], Any]) -> None:
        self.busy = True
        self._buttons()
        results = self.results

        def work() -> None:
            try:
                results.put((kind, action()))
            except Exception as error:
                results.put((kind, error))

        self.workers.start(work, "entity-" + kind, self.cancelled)

    def threshold_changed(self, *_: str) -> None:
        if not self.busy and self.run is not None:
            self.run = None
            self.decisions.clear()
            self.render()
            self.status.set("Threshold changed. Train again and review fresh groups.")

    def _current(self) -> bool:
        try:
            if (
                self.current_table() != self.table
                or entity_scope(self.table) != self.scope
                or self.store.catalog() != self.catalog
            ):
                raise ValueError("Data set or mappings changed. Close and reopen Match borrowers.")
        except (OSError, ValueError) as error:
            self.invalid = True
            self.cancelled.set()
            self.status.set(str(error))
            self._buttons()
        return not self.invalid

    def _selected_columns(self) -> tuple[int, ...]:
        indices = self.feature_list.curselection()  # type: ignore[no-untyped-call]
        return tuple(self.features[int(i)].column for i in indices)

    def prepare(self) -> None:
        if self.busy or not self._current():
            return
        columns = self._selected_columns()
        if not columns:
            self.status.set(
                "Select borrower features first. Use Define column for unmapped fields."
            )
            return
        self.columns = columns
        self.selected_parent = self.parent if self.use_parent.get() else None
        self.population = self.run = None
        self.labels.clear()
        self.decisions.clear()
        self.rows.clear()
        self.pairs.clear()
        self.representative.set(False)
        self.cancelled = threading.Event()
        self.change_page(0)
        self.status.set(
            "Reading complete source evidence and checking selected borrower meanings..."
        )
        self._start(
            "prepare",
            lambda: read_population(
                self.source,
                self.table,
                self.scope,
                self.catalog,
                columns,
                self.selected_parent,
                cancelled=self.cancelled,
            ),
        )

    def _guard(self) -> Callable[[], None]:
        assert self.population is not None
        return population_guard(
            self.source,
            self.table,
            self.store,
            self.population,
            self.columns,
            self.selected_parent,
            self.cancelled,
        )

    def label(self, kind: str) -> None:
        if self.busy or self.run is not None or self.view.get() != "Label pairs":
            return
        selected = self.grid.selection()
        if not selected:
            return
        pair = self.items[selected[0]]
        try:
            if pair in self.labels:
                raise ValueError("This pair is already labeled. Restart labeling to revise it.")
            self.labels[pair] = PairLabel(
                pair[0],
                pair[1],
                kind,
                self.reviewer.get(),
                self.reason.get(),
                datetime.now(UTC).isoformat(),
            )
            self.status.set(
                "Pair label recorded. Labels train the model; group approval is a separate decision."
            )
            self.render()
        except ValueError as error:
            self.status.set(str(error))

    def train(self) -> None:
        if self.busy or self.population is None or not self._current():
            return
        try:
            runtime_python()
            threshold = float(self.threshold.get())
        except (ValueError, OSError) as error:
            self.status.set(str(error))
            return
        population, labels = self.population, tuple(self.labels.values())
        representative = self.representative.get()
        self.cancelled = threading.Event()
        guard = self._guard()
        self.run = None
        self.decisions.clear()
        self.status.set(
            "Training from reviewed labels and proposing groups. Every group needs a separate decision..."
        )
        self._start(
            "train",
            lambda: train_entities(
                population, labels, threshold, representative, guard, cancelled=self.cancelled
            ),
        )

    def decide(self, decision: str) -> None:
        if self.busy or self.run is None or self.view.get() != "Review groups":
            return
        selected = self.grid.selection()
        if selected:
            self.decisions[self.items[selected[0]]["id"]] = decision
            self.render()

    def save(self) -> None:
        if self.busy or self.run is None or not self._current():
            return
        try:
            document = review_relationships(
                self.run,
                self.decisions,
                self.reviewer.get(),
                self.reason.get(),
                datetime.now(UTC).isoformat(),
            )
        except ValueError as error:
            self.status.set(str(error))
            return
        chosen = filedialog.asksaveasfilename(
            parent=self.window,
            title="Save borrower relationships and audit",
            defaultextension=".json",
            filetypes=(("Relationship audit", "*.json"),),
            initialfile="borrower-relationships.json",
        )
        if not chosen:
            return
        target = Path(chosen)
        if target.suffix.lower() != ".json":
            self.status.set("Choose a new .json audit file.")
            return
        self.cancelled = threading.Event()
        guard = self._guard()
        self.status.set("Rechecking source evidence and saving reviewed relationships...")
        self._start("save", lambda: publish_bytes(target, document.encode("utf-8"), guard))

    def change_page(self, direction: int) -> None:
        self.offset = max(0, self.offset + direction * PAGE) if direction else 0
        self.render()

    def render(self) -> None:
        self.grid.delete(*self.grid.get_children())
        self.items.clear()
        mode = self.view.get()
        values: list[Any] = (
            self.pairs
            if mode == "Label pairs"
            else (
                self.run.to_dict()["engine"]["groups"]
                if mode == "Review groups" and self.run
                else [self.rows[row] for row in self.run.to_dict()["engine"]["unclustered_rows"]]
                if mode == "Unclustered rows" and self.run
                else [row for row in self.rows.values() if row["exclusions"]]
                if mode == "Excluded rows"
                else []
            )
        )
        self.offset = min(self.offset, max(0, ((len(values) - 1) // PAGE) * PAGE))
        for index, item in enumerate(values[self.offset : self.offset + PAGE], self.offset):
            key = str(index)
            self.items[key] = item
            if mode == "Label pairs":
                rows = item
                decision = self.labels[item].label if item in self.labels else "Unreviewed"
                display = " | ".join(f"{row}: {self.rows[row]['values']}" for row in rows)
            elif mode == "Review groups":
                rows = item["rows"]
                decision = self.decisions.get(item["id"], "Unreviewed")
                display = " | ".join(f"{row}: {self.rows[row]['values']}" for row in rows)
            else:
                rows = [item["row"]]
                decision = "Excluded" if mode == "Excluded rows" else "Unclustered"
                display = str(item["exclusions"] if mode == "Excluded rows" else item["values"])
            self.grid.insert(
                "", "end", iid=key, values=(", ".join(map(str, rows)), decision, display[:800])
            )
        self.page.set(
            f"{self.offset + 1 if values else 0}–{min(self.offset + PAGE, len(values))} of {len(values):,}"
        )
        self.previous.configure(state="normal" if self.offset else "disabled")
        self.next.configure(state="normal" if self.offset + PAGE < len(values) else "disabled")
        counts = self.population.to_dict()["population"] if self.population else {}
        self.summary.set(
            f"Population: {counts} | Labels: {sum(x.label == 'match' for x in self.labels.values())} same / {sum(x.label == 'distinct' for x in self.labels.values())} different (10 each required) | Groups reviewed: {len(self.decisions)}"
        )
        self._buttons()

    def detail_selected(self, event: tk.Event[tk.Misc] | None = None) -> None:
        selected = self.grid.selection()
        if not selected or self.population is None:
            return
        item = self.items[selected[0]]
        rows = list(item) if isinstance(item, tuple) else item.get("rows", [item.get("row")])
        self.jump_row.set(str(rows[0]))
        data = self.population.to_dict()
        evidence = [cell for cell in data["snapshot"]["cells"] if cell["row"] in rows]
        detail = {
            "selected": item,
            "current_feature_values": [self.rows[r] for r in rows],
            "source_evidence": evidence,
        }
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", json.dumps(detail, indent=2, ensure_ascii=True))
        self.detail.configure(state="disabled")

    def jump_selected(self) -> None:
        try:
            row = int(self.jump_row.get())
            if self.busy or row not in self.rows:
                raise ValueError("Choose a source row in this reviewed population.")
            self.jump(self.table, self.columns[0], row)
        except (OSError, ValueError) as error:
            self.status.set(str(error))

    def cancel(self) -> None:
        self.cancelled.set()
        self.status.set("Cancellation requested. Waiting for the owned matching worker to stop...")

    def _poll(self) -> None:
        if self.closed:
            return
        self._current()
        try:
            kind, result = self.results.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            if isinstance(result, Exception):
                self.status.set(f"Entity work stopped: {result}")
            elif not self.invalid and not self.cancelled.is_set():
                if kind == "prepare":
                    self.population = result
                    self.rows = {row["row"]: row for row in result.to_dict()["rows"]}
                    self.pairs = list(
                        combinations(
                            [row for row in self.rows if not self.rows[row]["exclusions"]], 2
                        )
                    )
                    self.view.set("Label pairs")
                    self.status.set(
                        "Review representative pairs, including difficult cases. No labels are preselected."
                    )
                elif kind == "train":
                    self.run = result[0]
                    self.view.set("Review groups")
                    self.status.set(
                        "Review every proposed group. Unclustered rows are not confirmed different borrowers. No independent accuracy claim is made."
                    )
                else:
                    self.status.set(f"Reviewed relationships and complete audit saved: {result}")
                self.change_page(0)
            self._buttons()
        self.poll_id = self.window.after(150, self._poll)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.cancelled.set()
        self.window.after_cancel(self.poll_id)
        self.use_parent.trace_remove("write", self.parent_trace)
        self.threshold.trace_remove("write", self.threshold_trace)
        self.window.destroy()
