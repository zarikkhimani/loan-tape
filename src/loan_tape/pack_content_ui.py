"""Native draft dialogs for sources, literal allowed values, and citations."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from copy import deepcopy
from functools import partial
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING, Any, Literal

from loan_tape.pack_content import (
    managed_ids,
    managed_source,
    remove_code_list,
    remove_source,
    source_uses,
    update_citations,
    update_code_list,
    update_source,
)
from loan_tape.pack_format import PackError

if TYPE_CHECKING:
    from loan_tape.pack_editor_ui import Input, PackEditor

Mode = Literal["source", "codes", "citations"]


class RowForm:
    """Edit one literal row at a time without delimiter-based data conversion."""

    def __init__(
        self,
        parent: ttk.Frame,
        editor: PackEditor,
        rows: list[dict[str, str]],
        *,
        citations: bool,
        error: Callable[[str], None],
    ) -> None:
        self.editor, self.error = editor, error
        self.rows = deepcopy(rows)
        self.original = deepcopy(rows)
        self.citations = citations
        self.key = "source" if citations else "value"
        self.protected = managed_ids(editor.documents) if citations else set()
        self.index: int | None = None
        self.switching = False
        self.inputs: dict[str, Input] = {}
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)
        self.tree = ttk.Treeview(
            parent, columns=("name", "detail"), show="headings", height=4, selectmode="browse"
        )
        self.tree.heading("name", text="Source ID" if citations else "Exact value")
        self.tree.heading("detail", text="Location / page / section" if citations else "Name")
        self.tree.column("name", width=170, minwidth=100)
        self.tree.column("detail", width=340, minwidth=150)
        self.tree.grid(row=0, sticky="ew")
        scroll = ttk.Scrollbar(parent, command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<<TreeviewSelect>>", self.select)
        container = ttk.Frame(parent)
        container.grid(row=1, columnspan=2, sticky="nsew")
        form = editor._scroll_form(container)
        self.form = form
        if citations:
            options = tuple(
                source["id"]
                for source in editor.documents["sources.json"]
                if source["id"] not in self.protected
            )
            editor._input(form, self.inputs, "source", "Source ID", options=options)
            editor._input(form, self.inputs, "locator", "Page, cell or section", lines=3)
            hint = "Add source records on the Sources tab first. Automatic authorship citations are kept unchanged."
        else:
            # Text widgets preserve even multiline values; no splitting, trimming or numeric cast.
            editor._input(form, self.inputs, "value", "Exact value", lines=2)
            editor._input(form, self.inputs, "label", "Name", lines=2)
            editor._input(form, self.inputs, "definition", "Meaning", lines=3)
            hint = "Values are exact text: 001 and 1 remain different. Spaces and line breaks are preserved."
        ttk.Label(form, text=hint, wraplength=470, style="Muted.TLabel").grid(
            columnspan=2, sticky="w", pady=6
        )
        buttons = ttk.Frame(parent)
        buttons.grid(row=2, columnspan=2, sticky="ew", pady=8)
        self.add_button = ttk.Button(
            buttons, text="Add citation" if citations else "Add value", command=self.add
        )
        self.add_button.pack(side="left")
        self.apply_button = ttk.Button(buttons, text="Apply row", command=self.apply)
        self.apply_button.pack(side="left", padx=8)
        self.remove_button = ttk.Button(buttons, text="Remove row", command=self.remove)
        self.remove_button.pack(side="left")
        self.load(0 if rows else None)

    def load(self, index: int | None) -> None:
        self.switching = True
        self.tree.delete(*self.tree.get_children())
        for position, row in enumerate(self.rows):
            self.tree.insert(
                "",
                "end",
                iid=str(position),
                values=(row[self.key], row["locator" if self.citations else "label"]),
            )
        self.index = index
        values = self.rows[index] if index is not None else {}
        # Re-enable inputs while loading previously locked automatic citations.
        for widget in self.controls():
            widget.configure(
                {"state": "readonly" if isinstance(widget, ttk.Combobox) else "normal"}
            )
        self.editor._set(self.inputs, values)
        self.baseline = self.editor._get(self.inputs)
        locked = values.get(self.key) in self.protected
        if locked:
            for widget in self.controls():
                widget.configure({"state": "disabled"})
        self.apply_button.configure(state="disabled" if locked else "normal")
        self.remove_button.configure(state="disabled" if locked or index is None else "normal")
        if index is not None:
            self.tree.selection_set(str(index))
            self.tree.see(str(index))
        self.switching = False

    def controls(self) -> list[tk.Misc]:
        return [
            widget
            for widget in self.form.winfo_children()
            if isinstance(widget, (tk.Text, ttk.Entry, ttk.Combobox))
        ]

    def dirty(self) -> bool:
        return self.rows != self.original or self.editor._get(self.inputs) != self.baseline

    def apply(self) -> bool:
        values = self.editor._get(self.inputs)
        if values == self.baseline:
            return True
        if self.index is not None and self.rows[self.index][self.key] in self.protected:
            self.error("Automatic authorship citations cannot be changed.")
            return False
        if any(not text.strip() for text in values.values()):
            self.error("Complete every row box before applying this row.")
            return False
        if self.citations and values["source"] in self.protected:
            self.error("Choose a source you added; automatic citations are managed by Loan Tape.")
            return False
        duplicate = any(
            position != self.index
            and (row == values if self.citations else row["value"] == values["value"])
            for position, row in enumerate(self.rows)
        )
        if duplicate:
            self.error(
                "This citation already exists."
                if self.citations
                else "This exact value already exists in the list."
            )
            return False
        if self.index is None:
            self.rows.append(values)
            index = len(self.rows) - 1
        else:
            self.rows[self.index] = values
            index = self.index
        self.load(index)
        return True

    def select(self, event: tk.Event[tk.Misc]) -> None:
        selected = self.tree.selection()
        if self.switching or not selected or int(selected[0]) == self.index:
            return
        index = int(selected[0])
        if self.apply():
            self.load(index)
        elif self.index is not None:
            self.tree.selection_set(str(self.index))
        else:
            self.tree.selection_remove(*self.tree.selection())

    def add(self) -> None:
        if self.apply():
            self.load(None)

    def remove(self) -> None:
        if self.index is not None and self.rows[self.index][self.key] not in self.protected:
            self.rows.pop(self.index)
        self.load(0 if self.rows else None)


class ContentDialog:
    def __init__(self, editor: PackEditor, mode: Mode, index: int | None) -> None:
        self.editor, self.mode, self.index = editor, mode, index
        self.inputs: dict[str, Input] = {}
        self.rows: RowForm | None = None
        self.references: RowForm | None = None
        self.closed = False
        self.window = tk.Toplevel(editor.window)
        self.window.title(
            {
                "source": "Source record",
                "codes": "Allowed-value list",
                "citations": "Field citations",
            }[mode]
        )
        self.window.transient(editor.window)
        self.window.geometry("760x680")
        self.window.minsize(660, 580)
        self.window.protocol("WM_DELETE_WINDOW", self.cancel)
        self.window.bind("<Control-w>", lambda event: self.cancel())
        page = ttk.Frame(self.window, padding=16)
        page.pack(fill="both", expand=True)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(1, weight=1)
        ttk.Label(page, text=self.window.title(), font=("Segoe UI", 17, "bold")).grid(
            sticky="w", pady=(0, 10)
        )
        body = ttk.Frame(page)
        body.grid(row=1, sticky="nsew")
        body.columnconfigure(0, weight=1)
        self.status = tk.StringVar(
            self.window, "Apply to pack draft, then Save pack to keep your changes."
        )
        self.status_label = ttk.Label(page, textvariable=self.status, wraplength=620)
        self.status_label.grid(row=2, sticky="ew", pady=10)
        if mode == "source":
            form = editor._scroll_form(body)
            for key, label in (
                ("id", "Source ID"),
                ("title", "Title"),
                ("version", "Source version"),
                ("uri", "Location / URL"),
                ("sha256", "SHA-256 (optional)"),
            ):
                editor._input(
                    form, self.inputs, key, label, readonly=key == "id" and index is not None
                )
            ttk.Label(
                form,
                text="This records a citation. The application does not open the location or verify the source file's hash.",
                wraplength=440,
                style="Muted.TLabel",
            ).grid(columnspan=2, sticky="w", pady=12)
            values = editor.documents["sources.json"][index] if index is not None else {}
            editor._set(self.inputs, values)
        elif mode == "codes":
            body.rowconfigure(1, weight=1)
            values = editor.documents["code_lists.json"][index] if index is not None else {}
            heading = ttk.Frame(body)
            heading.grid(sticky="ew")
            heading.columnconfigure(1, weight=1)
            editor._input(heading, self.inputs, "id", "List ID", readonly=index is not None)
            editor._set(self.inputs, values)
            self.tabs = ttk.Notebook(body)
            self.tabs.grid(row=1, sticky="nsew")
            codes_page, refs_page = ttk.Frame(self.tabs, padding=8), ttk.Frame(self.tabs, padding=8)
            self.tabs.add(codes_page, text="Allowed values")
            self.tabs.add(refs_page, text="Citations")
            self.rows = RowForm(
                codes_page, editor, values.get("codes", []), citations=False, error=self.error
            )
            self.references = RowForm(
                refs_page, editor, values.get("references", []), citations=True, error=self.error
            )
        else:
            assert index is not None
            values = editor.documents["fields.json"][index]
            self.references = RowForm(
                body, editor, values["references"], citations=True, error=self.error
            )
        self.baseline = editor._get(self.inputs)
        footer = ttk.Frame(page)
        footer.grid(row=3, sticky="ew")
        self.apply_button = ttk.Button(
            footer, text="Apply to pack draft", style="Accent.TButton", command=self.apply
        )
        self.apply_button.pack(side="right")
        self.cancel_button = ttk.Button(footer, text="Cancel", command=self.cancel)
        self.cancel_button.pack(side="left")
        self.window.grab_set()

    def dirty(self) -> bool:
        return self.editor._get(self.inputs) != self.baseline or any(
            form is not None and form.dirty() for form in (self.rows, self.references)
        )

    def error(self, message: str) -> None:
        self.status.set(message)
        self.status_label.configure(foreground="#a1342d")

    def apply(self) -> None:
        for form in (self.rows, self.references):
            if form is not None and not form.apply():
                return
        values: dict[str, Any] = self.editor._get(self.inputs)
        try:
            if self.mode == "source":
                if not values["sha256"]:
                    if (
                        self.index is not None
                        and "sha256" in self.editor.documents["sources.json"][self.index]
                    ):
                        values["sha256"] = None
                    else:
                        values.pop("sha256")
                result = update_source(self.editor.documents, self.index, values)
            elif self.mode == "codes":
                assert self.rows is not None and self.references is not None
                values.update(codes=self.rows.rows, references=self.references.rows)
                result = update_code_list(
                    self.editor.documents, self.index, values, self.editor.base
                )
            else:
                assert self.references is not None and self.index is not None
                result = update_citations(
                    self.editor.documents, "fields.json", self.index, self.references.rows
                )
        except PackError as error:
            self.error(str(error))
            return
        self.editor.documents = result
        self.editor._sources()
        self.editor.status.set("Changes applied to the pack draft. Save pack to keep them.")
        self.destroy()

    def cancel(self) -> None:
        if not self.dirty() or messagebox.askokcancel(
            "Discard these edits?",
            "Close and discard the edits in this dialog?",
            parent=self.window,
            default=messagebox.CANCEL,
        ):
            self.destroy()

    def destroy(self) -> None:
        self.closed = True
        self.window.grab_release()
        self.window.destroy()
        self.editor.content_dialog = None


class ContentPages:
    def __init__(self, editor: PackEditor) -> None:
        self.editor = editor
        self.trees: dict[str, ttk.Treeview] = {}
        self.details: dict[str, tk.Text] = {}
        self.buttons: dict[str, tuple[ttk.Button, ttk.Button, ttk.Button]] = {}
        for mode, title, label in (
            ("source", "Sources", "Source"),
            ("codes", "Allowed values", "List"),
        ):
            page = ttk.Frame(editor.tabs, padding=12)
            editor.tabs.add(page, text=title)
            page.columnconfigure(0, weight=1)
            page.rowconfigure(2, weight=1)
            tree = ttk.Treeview(
                page, columns=("name", "detail"), show="headings", selectmode="browse", height=5
            )
            tree.heading("name", text=label)
            tree.heading("detail", text="Source ID" if mode == "source" else "Values")
            tree.column("name", width=400, minwidth=200)
            tree.column("detail", width=160, minwidth=100)
            tree.grid(sticky="ew")
            scroll = ttk.Scrollbar(page, command=tree.yview)
            scroll.grid(row=0, column=1, sticky="ns")
            tree.configure(yscrollcommand=scroll.set)
            tree.bind("<<TreeviewSelect>>", partial(self.show, mode))
            self.trees[mode] = tree
            bar = ttk.Frame(page)
            bar.grid(row=1, columnspan=2, sticky="ew", pady=8)
            add = ttk.Button(
                bar,
                text="Add source" if mode == "source" else "Add list",
                command=partial(self.open, mode, new=True),
            )
            edit = ttk.Button(bar, text="Edit", command=partial(self.open, mode))
            remove = ttk.Button(bar, text="Remove", command=partial(self.remove, mode))
            for button in (add, edit, remove):
                button.pack(side="left", padx=(0, 8))
            self.buttons[mode] = (add, edit, remove)
            detail = tk.Text(
                page, wrap="word", width=50, height=8, font=("Segoe UI", 10), state="disabled"
            )
            detail.grid(row=2, sticky="nsew")
            detail_scroll = ttk.Scrollbar(page, command=detail.yview)
            detail_scroll.grid(row=2, column=1, sticky="ns")
            detail.configure(yscrollcommand=detail_scroll.set)
            self.details[mode] = detail

    def records(self, mode: str) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = self.editor.documents[
            "sources.json" if mode == "source" else "code_lists.json"
        ]
        return records

    def refresh(self) -> None:
        for mode, tree in self.trees.items():
            selected = tree.selection()
            tree.delete(*tree.get_children())
            for index, item in enumerate(self.records(mode)):
                tree.insert(
                    "",
                    "end",
                    iid=str(index),
                    values=(
                        item["title"] if mode == "source" else item["id"],
                        item["id"] if mode == "source" else len(item["codes"]),
                    ),
                )
            key = selected[0] if selected and tree.exists(selected[0]) else "0"
            if tree.exists(key):
                tree.selection_set(key)
            self.show(mode)

    def show(self, mode: str, event: tk.Event[tk.Misc] | None = None) -> None:
        selected = self.trees[mode].selection()
        locked = False
        text = (
            "Add a source record, then cite it from a field or allowed-value list."
            if mode == "source"
            else "Add a list, then select it in a field's Context and codes tab."
        )
        if selected:
            item = self.records(mode)[int(selected[0])]
            if mode == "source":
                locked = managed_source(item)
                uses = source_uses(self.editor.documents, item["id"])
                text = f"{item['title']}\nID: {item['id']}\nVersion: {item['version']}\nLocation: {item['uri']}\nSHA-256: {item.get('sha256') or 'Not recorded'}\n\nUsed by: {', '.join(uses) or 'No citations yet'}"
                if locked:
                    text += "\n\nAutomatic authorship / copy record. Kept unchanged for provenance."
            else:
                text = "\n\n".join(
                    f"{code['value']!r} — {code['label']}\n{code['definition']}"
                    for code in item["codes"]
                )
                text += "\n\nCitations:\n" + "\n".join(
                    f"{ref['source']}: {ref['locator']}" for ref in item["references"]
                )
        detail = self.details[mode]
        detail.configure(state="normal")
        detail.delete("1.0", "end")
        detail.insert("1.0", text)
        detail.configure(state="disabled")
        for button in self.buttons[mode][1:]:
            button.configure(state="normal" if selected and not locked else "disabled")

    def open(self, mode: str, *, new: bool = False) -> None:
        if self.editor.busy or self.editor.content_dialog is not None:
            return
        selected = self.trees[mode].selection()
        if not new and not selected:
            return
        self.editor.content_dialog = ContentDialog(
            self.editor,
            "source" if mode == "source" else "codes",
            None if new else int(selected[0]),
        )

    def remove(self, mode: str) -> None:
        if self.editor.busy or self.editor.content_dialog is not None:
            return
        selected = self.trees[mode].selection()
        if not selected:
            return
        try:
            operation = remove_source if mode == "source" else remove_code_list
            self.editor.documents = operation(self.editor.documents, int(selected[0]))
        except PackError as error:
            self.editor._error(str(error))
            return
        self.editor._sources()
        self.editor.status.set("Removed from the draft. Save pack to keep this change.")
