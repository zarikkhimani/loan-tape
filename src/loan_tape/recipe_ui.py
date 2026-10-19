"""Explicit local recipe saving/loading, compatibility review and staged execution."""

from __future__ import annotations

import json
import queue
import threading
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import ttk
from typing import TYPE_CHECKING, Any
from uuid import uuid4
from weakref import proxy

from loan_tape._date_json import canonical
from loan_tape.recipe_execution import RecipeBinding, bind_excel_recipe, recipe_scope
from loan_tape.recipe_run_ui import RecipeStepWindow
from loan_tape.recipes import (
    Recipe,
    list_recipes,
    load_recipe,
    operation_settings,
    recipe_from_revision,
    save_recipe,
)
from loan_tape.transformations import TransformationRevision

if TYPE_CHECKING:
    from loan_tape.text_cleanup_ui import TextCleanupWindow


class RecipeWindow:
    def __init__(self, owner: TextCleanupWindow) -> None:
        self.owner = proxy(owner)
        self.window = tk.Toplevel(owner.window)
        self.window.title("Local cleanup recipes")
        self.window.geometry("1060x860")
        self.window.minsize(900, 790)
        self.window.transient(owner.window)
        self.closed = self.busy = False
        self.generation = 0
        self.cancelled = threading.Event()
        self.results: queue.Queue[tuple[int, str, Any]] = queue.Queue()
        self.recipe: Recipe | None = None
        self.running_recipe: Recipe | None = None
        self.binding: RecipeBinding | None = None
        self.staged: TransformationRevision | None = None
        self.child: RecipeStepWindow | None = None
        self.run_scope = recipe_scope(owner.table)
        self.run_catalog = owner.store.catalog()
        self.entries: tuple[tuple[Path, str], ...] = ()
        self.name = tk.StringVar(self.window)
        self.profile = tk.StringVar(self.window)
        self.version = tk.StringVar(self.window, "1.0.0")
        self.applicability = tk.StringVar(self.window)
        self.context = tk.StringVar(self.window)
        self.reviewer = tk.StringVar(self.window)
        self.confirmed = tk.BooleanVar(self.window, False)
        self.status = tk.StringVar(
            self.window,
            "Load a saved recipe, or name a recipe and capture the current working result's steps.",
        )
        self.identity = tk.StringVar(self.window, "No recipe selected")
        self._build()
        self.traces = tuple(
            (v, v.trace_add("write", self._edited))
            for v in (
                self.name,
                self.version,
                self.profile,
                self.applicability,
                self.context,
                self.reviewer,
            )
        )
        self.confirm_trace = self.confirmed.trace_add("write", self._buttons)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.poll_id = self.window.after(100, self._poll)
        self.refresh()

    def _build(self) -> None:
        page = ttk.Frame(self.window, padding=14)
        page.pack(fill="both", expand=True)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(5, weight=1)
        page.rowconfigure(7, weight=1)
        ttk.Label(page, text="Reusable cleanup recipes", font=("Segoe UI", 16, "bold")).grid(
            row=0, sticky="w"
        )
        library = ttk.Frame(page)
        library.grid(row=1, sticky="ew", pady=6)
        library.columnconfigure(0, weight=1)
        self.library = tk.Listbox(library, height=3, exportselection=False)
        self.library.grid(row=0, column=0, rowspan=2, sticky="ew")
        scroll = ttk.Scrollbar(library, command=self.library.yview)
        scroll.grid(row=0, column=1, rowspan=2, sticky="ns")
        self.library.configure(yscrollcommand=scroll.set)
        self.load_button = ttk.Button(library, text="Load selected", command=self.load)
        self.load_button.grid(row=0, column=2, padx=8)
        self.refresh_button = ttk.Button(library, text="Refresh library", command=self.refresh)
        self.refresh_button.grid(row=1, column=2, padx=8)
        fields = ttk.Frame(page)
        fields.grid(row=2, sticky="ew")
        fields.columnconfigure(1, weight=1)
        self.editors = []
        for row, (label, variable) in enumerate(
            (
                ("Recipe name", self.name),
                ("Version (major.minor.patch)", self.version),
                ("Source / template profile", self.profile),
                ("Applicability / reporting context", self.applicability),
            )
        ):
            ttk.Label(fields, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=2)
            entry = ttk.Entry(fields, textvariable=variable)
            entry.grid(row=row, column=1, sticky="ew", pady=2)
            self.editors.append(entry)
        actions = ttk.Frame(page)
        actions.grid(row=3, sticky="ew", pady=6)
        self.capture_button = ttk.Button(
            actions, text="Capture working steps", command=self.capture
        )
        self.capture_button.pack(side="left")
        self.save_button = ttk.Button(actions, text="Save recipe", command=self.save)
        self.save_button.pack(side="left", padx=8)
        self.copy_button = ttk.Button(actions, text="New copy ID", command=self.new_id)
        self.copy_button.pack(side="left")
        ttk.Label(page, textvariable=self.identity, wraplength=850).grid(row=4, sticky="w")
        self.steps = ttk.Treeview(
            page,
            columns=("step", "field", "operation"),
            show="headings",
            height=4,
            selectmode="browse",
        )
        for key, text, width in (
            ("step", "Order", 70),
            ("field", "Mapped source field", 380),
            ("operation", "Operation", 280),
        ):
            self.steps.heading(key, text=text)
            self.steps.column(key, width=width, minwidth=60)
        self.steps.grid(row=5, sticky="nsew", pady=5)
        self.steps.bind("<<TreeviewSelect>>", self._detail)
        order = ttk.Frame(page)
        order.grid(row=6, sticky="ew")
        self.up_button = ttk.Button(order, text="Move up", command=lambda: self.move(-1))
        self.up_button.pack(side="left")
        self.down_button = ttk.Button(order, text="Move down", command=lambda: self.move(1))
        self.down_button.pack(side="left", padx=6)
        self.remove_button = ttk.Button(order, text="Remove step", command=self.remove)
        self.remove_button.pack(side="left")
        self.detail = tk.Text(page, height=5, wrap="word", state="disabled")
        self.detail.grid(row=7, sticky="nsew", pady=6)
        run = ttk.Frame(page)
        run.grid(row=8, sticky="ew")
        run.columnconfigure(1, weight=1)
        for row, (label, variable) in enumerate(
            (("Current run context", self.context), ("Reviewer", self.reviewer))
        ):
            ttk.Label(run, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8))
            entry = ttk.Entry(run, textvariable=variable)
            entry.grid(row=row, column=1, sticky="ew", pady=2)
            self.editors.append(entry)
        self.confirm = ttk.Checkbutton(
            page,
            text="I reviewed the template, field mappings and reporting context for this source.",
            variable=self.confirmed,
        )
        self.confirm.grid(row=9, sticky="w", pady=5)
        footer = ttk.Frame(page)
        footer.grid(row=10, sticky="ew")
        self.review_button = ttk.Button(
            footer, text="Bind source and review recipe", command=self.begin
        )
        self.review_button.pack(side="left")
        self.cancel_button = ttk.Button(footer, text="Cancel work", command=self.cancel_work)
        self.cancel_button.pack(side="left", padx=8)
        ttk.Button(footer, text="Close", command=self.close).pack(side="right")
        self.retention_label = ttk.Label(
            page,
            wraplength=850,
            text="Save recipe keeps literal rules and field meanings locally after Exit. Loading does not run changes. Runs start from source; only a complete approved run replaces the current working result.",
        )
        self.retention_label.grid(row=11, sticky="ew", pady=6)
        self.status_label = ttk.Label(page, textvariable=self.status, wraplength=850)
        self.status_label.grid(row=12, sticky="ew")

    def _buttons(self, *_: str) -> None:
        idle = not self.busy and self.binding is None
        for widget in (
            *self.editors,
            self.library,
            self.refresh_button,
            self.load_button,
            self.confirm,
        ):
            widget.configure({"state": "normal" if idle else "disabled"})
        self.capture_button.configure(
            state="normal" if idle and self.owner.parent is not None else "disabled"
        )
        for widget in (
            self.save_button,
            self.copy_button,
            self.up_button,
            self.down_button,
            self.remove_button,
        ):
            widget.configure(state="normal" if idle and self.recipe is not None else "disabled")
        self.review_button.configure(
            state="normal"
            if idle and self.recipe is not None and self.confirmed.get()
            else "disabled"
        )
        self.cancel_button.configure(
            state="normal" if self.busy or self.binding is not None else "disabled"
        )

    def _edited(self, *_: str) -> None:
        self.confirmed.set(False)
        self._buttons()

    def _start(self, kind: str, action: Callable[[threading.Event], Any]) -> None:
        if self.busy or self.binding is not None:
            return
        self.busy = True
        self.cancelled = threading.Event()
        generation, results, cancelled = self.generation, self.results, self.cancelled
        self._buttons()

        def work() -> None:
            try:
                result = action(cancelled)
            except Exception as error:
                result = error
            results.put((generation, kind, result))

        self.owner.workers.start(work, "recipe-" + kind, cancelled)

    def refresh(self) -> None:
        self._start("library", lambda cancelled: list_recipes(cancelled=cancelled))

    def load(self) -> None:
        selected = self.library.curselection()  # type: ignore[no-untyped-call]
        if selected:
            path = self.entries[selected[0]][0]
            self._start("draft", lambda cancelled: load_recipe(path, cancelled=cancelled))

    def _draft(self) -> Recipe:
        if self.recipe is None:
            raise ValueError("Load or capture a recipe first.")
        return Recipe(
            canonical(
                {
                    **self.recipe.to_dict(),
                    "name": self.name.get(),
                    "version": self.version.get(),
                    "profile": self.profile.get(),
                    "applicability": self.applicability.get(),
                }
            )
        )

    def capture(self) -> None:
        revision = self.owner.parent
        if revision is None:
            self.status.set(
                "First review and apply cleanup steps in Clean text, then capture that working result."
            )
            return
        name, profile, applicability, recipe_version = (
            self.name.get(),
            self.profile.get(),
            self.applicability.get(),
            self.version.get(),
        )
        self._start(
            "draft",
            lambda cancelled: recipe_from_revision(
                revision,
                name=name,
                profile=profile,
                applicability=applicability,
                recipe_version=recipe_version,
                cancelled=cancelled,
            ),
        )

    def save(self) -> None:
        try:
            recipe = self._draft()
        except ValueError as error:
            self.status.set(str(error))
            return
        self._start("save", lambda cancelled: save_recipe(recipe, cancelled=cancelled))

    def new_id(self) -> None:
        if self.recipe is not None and not self.busy and self.binding is None:
            self.recipe = Recipe(
                canonical({**self.recipe.to_dict(), "id": uuid4().hex, "version": "1.0.0"})
            )
            self.version.set("1.0.0")
            self._render()

    def move(self, direction: int) -> None:
        if (
            self.busy
            or self.binding is not None
            or self.recipe is None
            or not self.steps.selection()
        ):
            return
        index = int(self.steps.selection()[0])
        data = self.recipe.to_dict()
        target = index + direction
        if 0 <= target < len(data["steps"]):
            data["steps"][index], data["steps"][target] = (
                data["steps"][target],
                data["steps"][index],
            )
            self.recipe = Recipe(canonical(data))
            self._edited()
            self._render()
            self.steps.selection_set(str(target))

    def remove(self) -> None:
        if (
            self.busy
            or self.binding is not None
            or self.recipe is None
            or not self.steps.selection()
        ):
            return
        data = self.recipe.to_dict()
        if len(data["steps"]) == 1:
            self.status.set("A recipe must retain at least one step.")
            return
        del data["steps"][int(self.steps.selection()[0])]
        self.recipe = Recipe(canonical(data))
        self._edited()
        self._render()

    def _render(self) -> None:
        self.steps.delete(*self.steps.get_children())
        if self.recipe is None:
            return
        data = self.recipe.to_dict()
        self.identity.set(f"Recipe {data['id']} | fingerprint {self.recipe.fingerprint[:16]}...")
        fields = {
            item["definition"]["column"]: item["definition"] for item in data["schema"]["fields"]
        }
        for index, operation in enumerate(self.recipe.steps):
            column, _ = operation_settings(operation)
            definition = fields[column]
            self.steps.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    index + 1,
                    f"{column}: {definition['source_header']!r} | {definition['field']['label']}",
                    operation.id,
                ),
            )
        self._set_detail(json.dumps(data["schema"], indent=2, ensure_ascii=True))
        self._buttons()

    def _set_detail(self, text: str) -> None:
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", text)
        self.detail.configure(state="disabled")

    def _detail(self, event: tk.Event[tk.Misc]) -> None:
        if self.recipe is not None and self.steps.selection():
            operation = self.recipe.steps[int(self.steps.selection()[0])]
            self._set_detail(
                f"{operation.id} {operation.version} | {operation.engine} {operation.engine_version}\n"
                + json.dumps(json.loads(operation.parameters_json), indent=2, ensure_ascii=True)
            )

    def begin(self) -> None:
        try:
            if self.owner.current_table() != self.owner.table:
                raise ValueError("Return to the unchanged saved data set before binding a recipe.")
            recipe = self._draft()
            self.run_scope, self.run_catalog = (
                recipe_scope(self.owner.table),
                self.owner.store.catalog(),
            )
        except (ValueError, OSError) as error:
            self.status.set(str(error))
            return
        source, table, store = self.owner.source, self.owner.table, self.owner.store
        context, reviewer, confirmed = self.context.get(), self.reviewer.get(), self.confirmed.get()
        self.running_recipe = recipe
        self._start(
            "bind",
            lambda cancelled: bind_excel_recipe(
                source,
                table,
                store,
                recipe,
                profile=recipe.to_dict()["profile"],
                context=context,
                reviewer=reviewer,
                confirmed=confirmed,
                cancelled=cancelled,
            ),
        )

    def _run_is_current(self) -> bool:
        return (
            self.owner.current_table() == self.owner.table
            and recipe_scope(self.owner.table) == self.run_scope
            and self.owner.store.catalog() == self.run_catalog
        )

    def step_approved(self, revision: TransformationRevision, path: Path | None) -> None:
        if self.child is not None:
            self.child.close(discard=False)
        if path is None:
            self.staged = revision
            self.child = RecipeStepWindow(self)
            self.status.set(
                f"{len(revision.to_dict()['steps'])} step(s) staged in memory. Nothing has been published."
            )
        else:
            self.owner.parent = revision
            self.owner.parent_steps = len(revision.to_dict()["steps"])
            self.owner.on_applied(revision)
            self.owner._invalidate(
                "Complete recipe applied to the session result. Original workbook unchanged."
            )
            self.staged = None
            self.binding = None
            self.running_recipe = None
            self.confirmed.set(False)
            self.status.set(
                "Complete recipe published to the session result. Saved recipe files remain separate and unchanged."
            )
        self._buttons()

    def discard_run(self, message: str) -> None:
        if self.child is not None:
            self.child.close(discard=False)
        self.binding = self.staged = self.running_recipe = None
        self.confirmed.set(False)
        self.status.set(message)
        self._buttons()

    def cancel_work(self) -> None:
        self.generation += 1
        self.cancelled.set()
        self.discard_run(
            "Recipe work cancelled; staged approvals discarded. A saved recipe is retained if its atomic save already completed."
        )

    def _poll(self) -> None:
        if self.closed:
            return
        if self.binding is not None:
            try:
                if not self._run_is_current():
                    raise ValueError("Source selection, mappings or active dictionary changed.")
            except (ValueError, OSError) as error:
                self.discard_run(f"Recipe discarded: {error}")
        try:
            generation, kind, result = self.results.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            if generation == self.generation:
                if isinstance(result, Exception):
                    self.status.set(f"Recipe work stopped: {result}")
                elif kind == "library":
                    self.entries = result
                    self.library.configure(state="normal")
                    self.library.delete(0, "end")
                    for _, label in self.entries:
                        self.library.insert("end", label)
                elif kind == "draft":
                    self.recipe = result
                    data = result.to_dict()
                    self.name.set(data["name"])
                    self.version.set(data["version"])
                    self.profile.set(data["profile"])
                    self.applicability.set(data["applicability"])
                    self._render()
                    self.status.set(
                        "Draft loaded. Review its scope and steps. Loading has not run any transformation."
                    )
                elif kind == "save":
                    self.status.set(f"Recipe saved locally and retained after Exit: {result.name}")
                    self.refresh()
                elif kind == "bind":
                    try:
                        if not self._run_is_current():
                            raise ValueError("Mappings or dictionary changed while binding.")
                        self.binding, self.staged = result, None
                        self.child = RecipeStepWindow(self)
                        self.status.set(
                            "Source bound. Each step requires a fresh preview and cell approval. Nothing is applied on load."
                        )
                    except (ValueError, OSError) as error:
                        self.discard_run(str(error))
        self._buttons()
        self.poll_id = self.window.after(100, self._poll)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.cancelled.set()
        if self.child is not None:
            self.child.close(discard=False)
        self.window.after_cancel(self.poll_id)
        for variable, command in self.traces:
            variable.trace_remove("write", command)
        self.confirmed.trace_remove("write", self.confirm_trace)
        self.window.destroy()
        if not self.owner.closed:
            self.owner._buttons()
