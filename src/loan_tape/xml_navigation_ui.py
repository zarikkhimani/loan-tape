"""Compact XML group, saved-setup, and page controls for the shared preview."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from dataclasses import replace
from functools import partial
from tkinter import messagebox, ttk
from uuid import uuid4

from loan_tape.flow_ui import FlowBar
from loan_tape.inspection import MAX_COLUMNS, MAX_ROWS, FilePreview, InspectionError
from loan_tape.xml_selection import (
    SavedXmlTable,
    XmlDataSet,
    XmlSelections,
    load_xml_selections,
    save_xml_selections,
)


class XmlNavigator:
    def __init__(
        self,
        parent: ttk.Frame,
        group: tk.StringVar,
        reload: Callable[[], None],
        changed: Callable[[], None] = lambda: None,
    ) -> None:
        self.changed = changed
        ttk.Style(parent).configure("Xml.Navigator.TButton", font=("Segoe UI", 9), padding=(4, 2))
        self.group = group
        self.reload = reload
        self.frame = ttk.Frame(parent)
        self.frame.pack(fill="x", pady=(6, 0))
        self.preview: FilePreview | None = None
        self.settings: XmlSelections | None = None
        self.settings_loaded = False
        self.settings_error = ""
        self.source_sha256: str | None = None
        self.group_path: tuple[str, ...] | None = None
        self.active_id: str | None = None
        self.row = self.column = 1
        self.busy = False
        self.last_group = ""
        self.name = tk.StringVar(master=parent, value="Data set 1")
        self.saved_name = tk.StringVar(master=parent)
        self.message = tk.StringVar(master=parent)
        self.jump_row = tk.StringVar(master=parent, value="1")
        self.jump_column = tk.StringVar(master=parent, value="1")
        self.clean_name = self.name.get()
        controls = FlowBar(self.frame)
        controls.pack(fill="x")
        saved = ttk.Frame(controls)
        controls.add(saved)
        ttk.Label(saved, text="Data set", style="Muted.TLabel").pack(side="left", padx=(0, 6))
        self.saved_selector = ttk.Combobox(
            saved, textvariable=self.saved_name, state="readonly", width=22
        )
        self.saved_selector.pack(side="left")
        self.saved_selector.bind("<<ComboboxSelected>>", self.choose_saved)
        actions = ttk.Frame(controls)
        controls.add(actions)
        self.edit_button = ttk.Button(
            actions, text="Edit setup", command=lambda: self._set_editing(True)
        )
        self.new_button = ttk.Button(actions, text="New", width=5, command=self.new)
        self.remove_button = ttk.Button(actions, text="Remove", width=7, command=self.remove)
        for button in (self.edit_button, self.new_button, self.remove_button):
            button.configure(style="Xml.Navigator.TButton")
            button.pack(side="left", padx=(0, 6))
        self.editor = FlowBar(self.frame)
        self.editor.pack(fill="x", pady=(3, 0))
        name_group = ttk.Frame(self.editor)
        ttk.Label(name_group, text="Name", style="Muted.TLabel").pack(side="left", padx=(0, 6))
        self.name_entry = ttk.Entry(name_group, textvariable=self.name, width=25)
        self.name_entry.pack(side="left")
        self.editor.add(name_group)
        self.save_button = ttk.Button(
            self.editor, text="Save data set", command=self.save, style="Primary.Navigator.TButton"
        )
        self.editor.add(self.save_button)
        note = ttk.Label(self.frame, textvariable=self.message, style="Muted.TLabel")
        note.pack(fill="x", pady=(3, 0))
        self.message_label = note
        note.bind("<Configure>", lambda event: note.configure(wraplength=max(160, event.width - 8)))
        self.buttons: dict[str, ttk.Button] = {}
        self.entries: list[ttk.Entry] = [self.name_entry]

    def _set_editing(self, editing: bool) -> None:
        if editing:
            self.editor.pack(fill="x", pady=(3, 0), before=self.message_label)
        else:
            self.editor.pack_forget()

    def build_paging(self, parent: ttk.Frame) -> None:
        self.paging = FlowBar(parent)
        self.paging.grid(row=3, sticky="ew", pady=(6, 0))
        edges = ttk.Frame(self.paging)
        self.paging.add(edges)
        self._button(edges, "Start", lambda: self.edge(False))
        self._button(edges, "End", lambda: self.edge(True))
        for label, axis in (("Records", "row"), ("Fields", "column")):
            group = ttk.Frame(self.paging)
            self.paging.add(group)
            ttk.Label(group, text=label).pack(side="left", padx=(0, 3))
            for arrow, delta in (("<", -1), (">", 1)):
                self._button(group, axis + arrow, partial(self.move, axis, delta), arrow, 3)
        jump = ttk.Frame(self.paging)
        self.paging.add(jump)
        ttk.Label(jump, text="Go to record").pack(side="left", padx=(0, 3))
        for variable, width in ((self.jump_row, 7), (self.jump_column, 5)):
            if variable is self.jump_column:
                ttk.Label(jump, text="field").pack(side="left", padx=(5, 3))
            entry = ttk.Entry(jump, textvariable=variable, width=width)
            entry.pack(side="left")
            entry.bind("<Return>", lambda event: self.jump())
            self.entries.append(entry)
        self._button(jump, "Go", self.jump, width=4)

    def _button(
        self,
        parent: ttk.Frame,
        key: str,
        command: Callable[[], None],
        text: str | None = None,
        width: int = 5,
    ) -> None:
        button = ttk.Button(
            parent, text=text or key, width=width, command=command, style="Xml.Navigator.TButton"
        )
        button.pack(side="left", padx=(2, 0))
        self.buttons[key] = button

    def has_unsaved_setup(self) -> bool:
        return self.name.get() != self.clean_name

    def _allow_switch(self) -> bool:
        return not self.has_unsaved_setup() or messagebox.askokcancel(
            "Discard unsaved setup?",
            "Discard the edited XML data set name? Use Save data set to keep it.",
            parent=self.frame.winfo_toplevel(),
        )

    def _new_name(self) -> str:
        names = (
            {item.name.strip().casefold() for item in self.settings.data_sets}
            if self.settings
            else set()
        )
        number = 1
        while f"data set {number}" in names:
            number += 1
        return f"Data set {number}"

    def _set_name(self, name: str) -> None:
        self.name.set(name)
        self.clean_name = name

    def _refresh_saved(self) -> None:
        if self.settings:
            self.saved_selector.configure(
                values=tuple(item.name for item in self.settings.data_sets)
            )
            current = next(
                (item for item in self.settings.data_sets if item.id == self.active_id), None
            )
            self.saved_name.set(current.name if current else "")

    def choose_group(self, event: tk.Event[tk.Misc] | None = None) -> None:
        if self.busy or not self._allow_switch():
            self.group.set(self.last_group)
            return
        self.active_id = None
        self.group_path = None
        self.row = self.column = 1
        self._set_name(self._new_name())
        self.saved_name.set("")
        self._set_editing(True)
        self.reload()

    def choose_saved(self, event: tk.Event[tk.Misc] | None = None) -> None:
        if self.busy or not self.settings:
            return
        if not self._allow_switch():
            self._refresh_saved()
            return
        item = next(
            (item for item in self.settings.data_sets if item.name == self.saved_name.get()), None
        )
        if item is not None:
            self._restore(item)
            self.reload()

    def _restore(self, item: XmlDataSet) -> None:
        self.active_id = item.id
        self.group_path = item.group_path
        self.row, self.column = item.row, item.column
        self._set_name(item.name)
        self.saved_name.set(item.name)
        self._set_editing(False)

    def accept(self, preview: FilePreview) -> bool:
        """Return True when a saved group/page needs a new background read."""
        self.preview = preview
        self.source_sha256 = preview.source_sha256
        assert self.source_sha256 is not None
        if not self.settings_loaded:
            self.settings_loaded = True
            try:
                self.settings = load_xml_selections(self.source_sha256)
            except (OSError, ValueError) as error:
                self.settings_error = str(error)
            if self.settings and self.settings.active:
                item = self.settings.active
                self._restore(item)
                self._refresh_saved()
                self.reload()
                return True
        self.row, self.column = preview.start_row, preview.start_column
        self.last_group = preview.selected_record_group or ""
        self.group.set(self.last_group)
        self.group_path = (
            preview.record_group_paths[preview.record_groups.index(self.last_group)]
            if self.last_group
            else None
        )
        self.jump_row.set(str(self.row))
        self.jump_column.set(str(self.column))
        self.message.set(
            self.settings_error or "Save the entire record group; paging changes only the view."
        )
        if self.ready and self.settings and self.active_id:
            items = tuple(
                replace(item, row=self.row, column=self.column)
                if item.id == self.active_id
                else item
                for item in self.settings.data_sets
            )
            updated = XmlSelections(self.source_sha256, items, self.active_id)
            if updated != self.settings:
                self._write(updated)
        self._refresh_saved()
        self.set_busy(False)
        return False

    @property
    def ready(self) -> bool:
        return (
            self.preview is not None
            and bool(self.preview.rows)
            and not self.preview.record_group_error
        )

    def _write(self, settings: XmlSelections) -> bool:
        try:
            if (
                self.settings is not None
                and load_xml_selections(settings.source_sha256) != self.settings
            ):
                raise ValueError(
                    "XML data sets changed in another window. Reopen this preview before saving."
                )
            save_xml_selections(settings)
        except (OSError, ValueError) as error:
            self.message.set(f"XML setup was not saved: {error}")
            return False
        self.settings = settings
        return True

    def save(self) -> None:
        if (
            self.busy
            or not self.ready
            or self.settings_error
            or not self.settings
            or not self.group_path
        ):
            return
        try:
            item = XmlDataSet(
                self.active_id or uuid4().hex,
                self.name.get().strip(),
                self.group_path,
                self.row,
                self.column,
            )
            items = tuple(current for current in self.settings.data_sets if current.id != item.id)
            settings = XmlSelections(self.settings.source_sha256, (*items, item), item.id)
        except ValueError as error:
            self.message.set(str(error))
            return
        if self._write(settings):
            self.active_id = item.id
            self._set_name(item.name)
            self._refresh_saved()
            self._set_editing(False)
            self.message.set(
                "Saved the entire record group. Its last viewed page will reopen with it."
            )
            self.set_busy(False)

    def new(self) -> None:
        if self.busy or not self._allow_switch():
            return
        self.active_id = None
        self.saved_name.set("")
        self._set_name(self._new_name())
        self._set_editing(True)
        self.message.set(
            self.settings_error or "Choose a record group and name, then Save data set."
        )
        self.set_busy(False)

    def remove(self) -> None:
        if self.busy or not self.settings or not self.active_id or not self._allow_switch():
            return
        items = tuple(item for item in self.settings.data_sets if item.id != self.active_id)
        settings = XmlSelections(self.settings.source_sha256, items)
        if self._write(settings):
            self.active_id = None
            self._set_name(self._new_name())
            self._refresh_saved()
            self._set_editing(True)
            self.message.set("Removed the saved setup. The XML file is unchanged.")
            self.set_busy(False)

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        ready = not busy and self.ready
        self.saved_selector.configure(
            state="disabled"
            if busy or not self.settings or not self.settings.data_sets
            else "readonly"
        )
        for entry in self.entries:
            entry.configure(state="normal" if ready else "disabled")
        for button in self.buttons.values():
            button.configure(state="normal" if ready else "disabled")
        self.save_button.configure(
            state="normal" if ready and not self.settings_error else "disabled"
        )
        self.edit_button.configure(state="disabled" if busy else "normal")
        self.new_button.configure(state="disabled" if busy else "normal")
        self.remove_button.configure(
            state="normal"
            if not busy and self.active_id and not self.settings_error
            else "disabled"
        )
        if ready:
            assert self.preview is not None
            for key, available in {
                "row<": self.row > 1,
                "row>": self.preview.more_rows,
                "column<": self.column > 1,
                "column>": self.preview.more_columns,
            }.items():
                self.buttons[key].configure(state="normal" if available else "disabled")

        self.changed()

    def table_for_inspection(self) -> SavedXmlTable:
        if (
            self.busy
            or not self.ready
            or self.has_unsaved_setup()
            or not self.settings
            or self.settings_error
        ):
            raise InspectionError(
                "Save the XML data set and finish reading before reviewing a column."
            )
        item = next((item for item in self.settings.data_sets if item.id == self.active_id), None)
        if item is None or item.group_path != self.group_path:
            raise InspectionError("Save this XML record group as a data set first.")
        assert self.preview is not None and self.source_sha256 is not None
        return SavedXmlTable(
            item.id,
            item.name,
            self.source_sha256,
            item.group_path,
            self.last_group,
            self.preview.record_count or 0,
            self.preview.field_count or 0,
        )

    def read_failed(self) -> None:
        self.preview = None
        self.set_busy(False)

    def go(self, row: int, column: int) -> None:
        if self.busy or not self.ready:
            return
        assert self.preview is not None
        if not 1 <= row <= (self.preview.record_count or 0) or not 1 <= column <= (
            self.preview.field_count or 0
        ):
            self.message.set("Choose a record and field inside the selected group.")
            return
        self.row, self.column = row, column
        self.reload()

    def move(self, axis: str, direction: int) -> None:
        self.go(
            max(1, self.row + direction * MAX_ROWS) if axis == "row" else self.row,
            max(1, self.column + direction * MAX_COLUMNS) if axis == "column" else self.column,
        )

    def edge(self, end: bool) -> None:
        if not self.ready:
            return
        assert self.preview is not None
        row = ((self.preview.record_count or 1) - 1) // MAX_ROWS * MAX_ROWS + 1 if end else 1
        column = (
            ((self.preview.field_count or 1) - 1) // MAX_COLUMNS * MAX_COLUMNS + 1 if end else 1
        )
        self.go(row, column)

    def jump(self) -> None:
        try:
            row, column = int(self.jump_row.get()), int(self.jump_column.get())
        except ValueError:
            self.message.set("Enter whole record and field numbers.")
            return
        self.go(row, column)
