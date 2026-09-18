"""Native dictionary manager. Pack selections are not consumed by file checks."""

from __future__ import annotations

import queue
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from threading import Event
from tkinter import ttk
from typing import Literal

from loan_tape.pack_authoring import SavedPack
from loan_tape.pack_editor_ui import PackEditor
from loan_tape.pack_format import Pack
from loan_tape.pack_manager import (
    ManagedPack,
    PackInventory,
    field_text,
    inspect_packs,
    overview_text,
)
from loan_tape.packs import PackStore
from loan_tape.workers import WorkerGroup


@dataclass(frozen=True)
class _Result:
    inventory: PackInventory | None
    message: str
    error: str | None = None


class PackManager:
    def __init__(self, parent: tk.Tk, store: PackStore, workers: WorkerGroup) -> None:
        self.store, self.workers = store, workers
        self.window = tk.Toplevel(parent)
        self.window.title("Dictionary packs — Loan Tape")
        self.window.geometry(
            f"{min(1180, parent.winfo_screenwidth() - 60)}x"
            f"{min(780, parent.winfo_screenheight() - 80)}"
        )
        self.window.minsize(900, 600)
        self.window.transient(parent)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.bind("<Control-w>", lambda event: self.close())
        self.closed = self.closing = self.busy = False
        self.ready = False
        self.editor: PackEditor | None = None
        self.select_pack_id: str | None = None
        self.profile = "default"
        self.rows: dict[str, ManagedPack] = {}
        self.shown_pack: Pack | None = None
        self.results: queue.Queue[_Result] = queue.Queue()
        self.cancelled: Event | None = None
        self.profile_input = tk.StringVar(self.window, "default")
        self.status = tk.StringVar(self.window)
        self.version = tk.StringVar(self.window, "Editable files")
        self.search = tk.StringVar(self.window)
        self._build()
        self.profile_input.trace_add("write", lambda *args: self._buttons())
        self.search.trace_add("write", lambda *args: self._fields())
        self.poll_id = self.window.after(60, self._poll)
        self.refresh()

    def _build(self) -> None:
        page = ttk.Frame(self.window, padding=18)
        page.pack(fill="both", expand=True)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(3, weight=1)
        ttk.Label(page, text="Dictionary packs", font=("Segoe UI", 18, "bold")).grid(sticky="w")
        ttk.Label(
            page,
            text="Browse definitions and expected data types. File checks do not use packs yet.",
            style="Muted.TLabel",
        ).grid(row=1, sticky="w", pady=(4, 12))
        controls = ttk.Frame(page)
        controls.grid(row=2, sticky="ew", pady=(0, 12))
        ttk.Label(controls, text="Profile").pack(side="left")
        self.profile_box = ttk.Combobox(
            controls, textvariable=self.profile_input, values=("default",), width=22
        )
        self.profile_box.pack(side="left", padx=(8, 8))
        self.profile_box.bind("<Return>", lambda event: self.refresh())
        self.load_button = ttk.Button(controls, text="Load / refresh", command=self.refresh)
        self.load_button.pack(side="left")
        ttk.Label(
            controls,
            text="Type a new profile name to keep a separate selection.",
            style="Muted.TLabel",
        ).pack(side="left", padx=12)

        panes = ttk.Panedwindow(page, orient="horizontal")
        panes.grid(row=3, sticky="nsew")
        listing = ttk.Frame(panes)
        listing.columnconfigure(0, weight=1)
        listing.rowconfigure(0, weight=1)
        panes.add(listing, weight=2)
        self.tree = ttk.Treeview(
            listing, columns=("pack", "status"), show="headings", selectmode="browse", height=9
        )
        for column, label, width in (("pack", "Pack", 180), ("status", "Status", 220)):
            self.tree.heading(column, text=label, anchor="w")
            self.tree.column(column, width=width, minwidth=110)
        self.tree.grid(sticky="nsew")
        scroll = ttk.Scrollbar(listing, command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<<TreeviewSelect>>", lambda event: self._select())
        actions = ttk.Frame(listing)
        actions.grid(row=1, columnspan=2, sticky="ew", pady=(10, 0))
        self.activate_button = ttk.Button(
            actions, text="Activate pack", style="Accent.TButton", command=self.activate
        )
        self.activate_button.pack(side="left")
        self.deactivate_button = ttk.Button(actions, text="Deactivate", command=self.deactivate)
        self.deactivate_button.pack(side="left", padx=8)
        editing = ttk.Frame(listing)
        editing.grid(row=2, columnspan=2, sticky="ew", pady=(8, 0))
        self.new_button = ttk.Button(
            editing, text="New pack", command=lambda: self.open_editor("new")
        )
        self.copy_button = ttk.Button(
            editing, text="Make a copy", command=lambda: self.open_editor("copy")
        )
        self.edit_button = ttk.Button(
            editing, text="Edit pack", command=lambda: self.open_editor("edit")
        )
        for button in (self.new_button, self.copy_button, self.edit_button):
            button.pack(side="left", padx=(0, 6))

        details = ttk.Frame(panes, padding=(12, 0, 0, 0))
        details.columnconfigure(0, weight=1)
        details.rowconfigure(1, weight=1)
        panes.add(details, weight=3)
        view = ttk.Frame(details)
        view.grid(sticky="ew", pady=(0, 8))
        ttk.Label(view, text="Viewing").pack(side="left")
        self.version_box = ttk.Combobox(
            view,
            textvariable=self.version,
            state="readonly",
            width=21,
            values=("Editable files", "Active version"),
        )
        self.version_box.pack(side="left", padx=8)
        self.version_box.bind("<<ComboboxSelected>>", lambda event: self._details())
        self.details_tabs = ttk.Notebook(details)
        self.details_tabs.grid(row=1, sticky="nsew")
        fields_page = ttk.Frame(self.details_tabs, padding=8)
        fields_page.columnconfigure(0, weight=1)
        fields_page.rowconfigure(2, weight=1)
        self.details_tabs.add(fields_page, text="Fields and types")
        search_row = ttk.Frame(fields_page)
        search_row.grid(sticky="ew", pady=(0, 6))
        ttk.Label(search_row, text="Find a field").pack(side="left")
        ttk.Entry(search_row, textvariable=self.search).pack(
            side="left", fill="x", expand=True, padx=8
        )
        field_list = ttk.Frame(fields_page)
        field_list.grid(row=1, sticky="ew")
        field_list.columnconfigure(0, weight=1)
        self.fields = ttk.Treeview(
            field_list, columns=("label", "type"), show="headings", selectmode="browse", height=4
        )
        self.fields.heading("label", text="Field", anchor="w")
        self.fields.heading("type", text="Expected type", anchor="w")
        self.fields.column("label", width=280, minwidth=150)
        self.fields.column("type", width=110, minwidth=80, stretch=False)
        self.fields.grid(sticky="ew")
        field_scroll = ttk.Scrollbar(field_list, command=self.fields.yview)
        field_scroll.grid(row=0, column=1, sticky="ns")
        self.fields.configure(yscrollcommand=field_scroll.set)
        self.fields.bind("<<TreeviewSelect>>", lambda event: self._field_details())
        self.field_detail = self._text_box(fields_page, 2)
        fields_page.bind("<Configure>", self._size_fields)
        overview_page = ttk.Frame(self.details_tabs, padding=8)
        overview_page.columnconfigure(0, weight=1)
        overview_page.rowconfigure(0, weight=1)
        self.details_tabs.add(overview_page, text="Pack and sources")
        self.overview = self._text_box(overview_page, 0)

        self.status_label = ttk.Label(page, textvariable=self.status, wraplength=850)
        self.status_label.grid(row=4, sticky="ew", pady=(12, 6))
        folder = ttk.Frame(page)
        folder.grid(row=5, sticky="ew")
        ttk.Label(folder, text="Packs folder").pack(side="left")
        self.folder_path = tk.StringVar(self.window, str(self.store.packs_dir.absolute()))
        ttk.Entry(folder, textvariable=self.folder_path, state="readonly").pack(
            side="left", fill="x", expand=True, padx=8
        )
        ttk.Button(folder, text="Close", command=self.close).pack(side="right")
        ttk.Label(
            page,
            text="Add or edit pack folders here, then refresh. Activate to use an edited version.",
            style="Muted.TLabel",
        ).grid(row=6, sticky="w", pady=(6, 0))

    def _size_fields(self, event: tk.Event[tk.Misc]) -> None:
        # Keep room to read the definition when the dialog is short.
        height = 2 if event.height < 380 else 4
        if int(self.fields.cget("height")) != height:
            self.fields.configure(height=height)

    @staticmethod
    def _text_box(parent: ttk.Frame, row: int) -> tk.Text:
        frame = ttk.Frame(parent)
        frame.grid(row=row, sticky="nsew", pady=(8, 0))
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        text = tk.Text(
            frame,
            wrap="word",
            height=8,
            width=30,
            state="disabled",
            relief="flat",
            font=("Segoe UI", 10),
            padx=10,
            pady=10,
            background="white",
            foreground="#26352f",
        )
        text.grid(sticky="nsew")
        scroll = ttk.Scrollbar(frame, command=text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        text.configure(yscrollcommand=scroll.set)
        return text

    @staticmethod
    def _text(widget: tk.Text, value: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.configure(state="disabled")

    def _selected(self) -> ManagedPack | None:
        selected = self.tree.selection()
        return self.rows.get(selected[0]) if selected else None

    def _buttons(self) -> None:
        row = self._selected()
        editing = self.editor is not None and not self.editor.closed
        idle = not self.busy and not self.closing and not editing
        self.new_button.state(["!disabled" if idle else "disabled"])
        self.copy_button.state(["!disabled" if idle and self.shown_pack else "disabled"])
        self.edit_button.state(
            ["!disabled" if idle and row and row.editable and not row.source_error else "disabled"]
        )
        enabled = (
            self.ready
            and not editing
            and not self.busy
            and not self.closing
            and self.profile_input.get() == self.profile
        )
        self.activate_button.configure(
            text="Update active version" if row and row.pin else "Activate pack"
        )
        self.activate_button.state(
            ["!disabled" if enabled and row and row.can_activate else "disabled"]
        )
        self.deactivate_button.state(["!disabled" if enabled and row and row.pin else "disabled"])
        self.load_button.state(["disabled" if not idle else "!disabled"])
        self.profile_box.configure(state="disabled" if not idle else "normal")

    def _select(self) -> None:
        row = self._selected()
        self.version.set("Active version" if row and row.pin else "Editable files")
        self._details()
        self._buttons()

    def _details(self) -> None:
        row = self._selected()
        self.shown_pack = (
            (row.active if self.version.get() == "Active version" else row.editable)
            if row
            else None
        )
        self._text(
            self.overview,
            overview_text(row, self.shown_pack, self.version.get()) if row else "Select a pack.",
        )
        self._fields()
        self._buttons()

    def _fields(self) -> None:
        previous = self.fields.selection()
        self.fields.delete(*self.fields.get_children())
        if self.shown_pack:
            term = self.search.get().casefold().strip()
            for field in self.shown_pack.fields:
                if (
                    term
                    in " ".join(
                        (field.id, field.label, field.definition, field.data_type, *field.aliases)
                    ).casefold()
                ):
                    self.fields.insert(
                        "", "end", iid=field.id, values=(field.label, field.data_type)
                    )
        children = self.fields.get_children()
        if children:
            self.fields.selection_set(
                previous[0] if previous and previous[0] in children else children[0]
            )
        self._field_details()

    def _field_details(self) -> None:
        selected = self.fields.selection()
        value = (
            "No matching fields."
            if self.shown_pack
            else "This version is unavailable. See Pack and sources for details."
        )
        if self.shown_pack and selected:
            field = next(item for item in self.shown_pack.fields if item.id == selected[0])
            value = field_text(self.shown_pack, field)
        self._text(self.field_detail, value)

    def open_editor(self, mode: Literal["new", "copy", "edit"]) -> None:
        if self.busy or self.closing:
            return
        if self.editor is not None and not self.editor.closed:
            self.editor.window.lift()
            return
        row = self._selected()
        pack, path = None, None
        if mode == "copy":
            pack = self.shown_pack
            if pack is None:
                return
        elif mode == "edit":
            if row is None or row.editable is None or row.source_error:
                return
            pack, path = row.editable, row.path
        self.editor = PackEditor(
            self.window,
            self.store,
            self.workers,
            self._saved_edit,
            self._buttons,
            pack=pack,
            path=path,
        )
        self._buttons()

    def _saved_edit(self, saved: SavedPack) -> None:
        self.select_pack_id = saved.pack.id
        self._start(
            None, f"Saved {saved.pack.name}. Review Editable files, then activate when ready."
        )

    def refresh(self) -> None:
        if self.busy or self.closing or self.closed:
            return
        self.profile = self.profile_input.get()
        self._start(None, "")

    def activate(self) -> None:
        row = self._selected()
        if not self.ready or self.busy or self.closing or self.profile_input.get() != self.profile:
            return
        if row is None or not row.can_activate or row.editable is None:
            return
        pack, store, profile = row.editable, self.store, self.profile
        self._start(
            lambda: store.activate(pack.id, profile, expected_fingerprint=pack.fingerprint),
            f"Activated {pack.name} in profile '{profile}'.",
        )

    def deactivate(self) -> None:
        row = self._selected()
        if not self.ready or self.busy or self.closing or self.profile_input.get() != self.profile:
            return
        if row is None or row.pin is None:
            return
        pack_id, store, profile = row.pin.id, self.store, self.profile
        self._start(
            lambda: store.deactivate(pack_id, profile),
            f"Deactivated {row.name} in profile '{profile}'.",
        )

    def _start(self, action: Callable[[], object] | None, success: str) -> None:
        cancelled = Event()
        self.cancelled = cancelled
        self.busy = True
        self.status.set(
            "Saving pack selection…" if action else f"Loading profile '{self.profile}'…"
        )
        self.status_label.configure(foreground="#26352f")
        self._buttons()
        store, profile, results = self.store, self.profile, self.results

        def work() -> None:
            message = success if action is None else ""
            try:
                if action:
                    action()
                    message = success
                result = _Result(inspect_packs(store, profile, cancelled), message)
            except Exception as error:
                operation = "update pack selection" if action and not message else "load packs"
                result = _Result(None, message, f"Could not {operation}: {error}")
            results.put(result)

        self.workers.start(work, "dictionary-packs", cancelled)

    def _poll(self) -> None:
        if self.closed:
            return
        try:
            result = self.results.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            self.cancelled = None
            if self.closing:
                self._destroy()
                return
            previous = self._selected()
            self.tree.delete(*self.tree.get_children())
            self.rows.clear()
            self.ready = result.inventory is not None
            if result.inventory:
                for row in result.inventory.rows:
                    self.rows[row.key] = row
                    self.tree.insert("", "end", iid=row.key, values=(row.name, row.status))
                self.profile_box.configure(values=result.inventory.profiles)
                keys = tuple(self.rows)
                if keys:
                    preferred = next(
                        (
                            row.key
                            for row in self.rows.values()
                            if row.pack_id == self.select_pack_id
                        ),
                        None,
                    )
                    self.tree.selection_set(
                        preferred
                        or (previous.key if previous and previous.key in self.rows else keys[0])
                    )
                self.select_pack_id = None
                count = len({row.pin.id for row in self.rows.values() if row.pin})
                message = result.message or f"Profile '{self.profile}': {count} active packs."
                if not keys:
                    message += " No packs found. Add a pack folder, then refresh."
                if result.inventory.source_error:
                    message += f" Could not read pack folders: {result.inventory.source_error}"
                has_errors = result.inventory.source_error or any(
                    row.source_error or row.active_error for row in self.rows.values()
                )
                if has_errors:
                    message += " Some definitions are unavailable; select a pack to review details."
                self.status_label.configure(foreground="#a1342d" if has_errors else "#23634c")
            else:
                message = (
                    f"{result.message} {result.error} Refresh after resolving the error.".strip()
                )
                self.status_label.configure(foreground="#a1342d")
            self.status.set(message)
            self._select()
        self.poll_id = self.window.after(60, self._poll)

    def close(self) -> bool:
        if self.closed:
            return True
        if self.editor is not None and not self.editor.request_close():
            return False
        self.closing = True
        if self.busy:
            if self.cancelled is not None:
                self.cancelled.set()
            self.status.set("Closing after the current pack operation finishes…")
            self._buttons()
        else:
            self._destroy()
        return True

    def _destroy(self) -> None:
        self.closed = True
        self.window.after_cancel(self.poll_id)
        self.window.destroy()
