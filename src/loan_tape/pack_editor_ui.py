"""Form-based pack and field authoring; saving never changes activation profiles."""

from __future__ import annotations

import queue
import tkinter as tk
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any

from loan_tape.pack_authoring import SavedPack, documents_for, record_copy, save_draft, update_field
from loan_tape.pack_content_ui import ContentDialog, ContentPages
from loan_tape.pack_format import DATA_TYPES, ENTITIES, Pack, PackError
from loan_tape.packs import PackStore
from loan_tape.workers import WorkerGroup

Input = tk.StringVar | tk.Text
CHOICES = {"Not specified / conditional": None, "Yes": True, "No": False}


class PackEditor:
    def __init__(
        self,
        parent: tk.Toplevel,
        store: PackStore,
        workers: WorkerGroup,
        on_saved: Callable[[SavedPack], None],
        on_closed: Callable[[], None],
        *,
        pack: Pack | None = None,
        path: Path | None = None,
    ) -> None:
        self.store, self.workers = store, workers
        self.on_saved, self.on_closed = on_saved, on_closed
        self.base, self.path = pack, path
        self.documents = documents_for(pack, custom_copy=pack is not None and path is None)
        self.original = deepcopy(self.documents)
        self.busy = self.closed = self.switching = False
        self.index: int | None = None
        self.field_baseline: dict[str, Any] = {}
        self.loaded_field: dict[str, Any] = {}
        self.results: queue.Queue[SavedPack | Exception] = queue.Queue()
        self.window = tk.Toplevel(parent)
        self.window.title("Edit dictionary pack" if path else "New dictionary pack")
        self.window.transient(parent)
        self.window.geometry(
            f"{min(1000, parent.winfo_screenwidth() - 60)}x"
            f"{min(730, parent.winfo_screenheight() - 90)}"
        )
        self.window.minsize(820, 580)
        self.window.protocol("WM_DELETE_WINDOW", self.request_close)
        self.window.bind("<Control-w>", lambda event: self.request_close())
        self.status = tk.StringVar(
            self.window, "Save changes here, then activate them in the manager."
        )
        self.metadata: dict[str, Input] = {}
        self.inputs: dict[str, Input] = {}
        self.disabled: list[tuple[tk.Misc, str]] = []
        self.content_dialog: ContentDialog | None = None
        self.code_choices: list[ttk.Combobox] = []
        self._build()
        self._set(self.metadata, self.documents["pack.json"])
        self._list_fields(0 if self.documents["fields.json"] else None)
        self._sources()
        self.poll_id = self.window.after(60, self._poll)

    @staticmethod
    def _scroll_form(parent: ttk.Frame) -> ttk.Frame:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        canvas = tk.Canvas(parent, highlightthickness=0, background="#f7f8f6", width=300)
        canvas.grid(sticky="nsew")
        scroll = ttk.Scrollbar(parent, command=canvas.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        canvas.configure(yscrollcommand=scroll.set)
        form = ttk.Frame(canvas, padding=12)
        form.columnconfigure(1, weight=1)
        item = canvas.create_window((0, 0), window=form, anchor="nw")
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(item, width=event.width))
        form.bind("<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind(
            "<MouseWheel>", lambda event: canvas.yview_scroll(-int(event.delta / 120), "units")
        )
        return form

    def _input(
        self,
        form: ttk.Frame,
        mapping: dict[str, Input],
        key: str,
        label: str,
        *,
        options: tuple[str, ...] | None = None,
        lines: int = 0,
        readonly: bool = False,
    ) -> None:
        row = form.grid_size()[1]
        ttk.Label(form, text=label).grid(row=row, column=0, sticky="nw", padx=(0, 12), pady=6)
        if lines:
            text = tk.Text(
                form,
                height=lines,
                width=25,
                wrap="word",
                font=("Segoe UI", 10),
                relief="solid",
                borderwidth=1,
            )
            text.grid(row=row, column=1, sticky="ew", pady=6)
            mapping[key] = text
        else:
            variable = tk.StringVar(self.window)
            mapping[key] = variable
            if options is not None:
                widget: ttk.Widget = ttk.Combobox(
                    form, textvariable=variable, values=options, state="readonly"
                )
            else:
                widget = ttk.Entry(
                    form, textvariable=variable, state="readonly" if readonly else "normal"
                )
            widget.grid(row=row, column=1, sticky="ew", pady=6)
            if mapping is self.inputs and key in {"code_list", "missing_code_list"}:
                assert isinstance(widget, ttk.Combobox)
                self.code_choices.append(widget)
            if mapping is self.metadata and key == "id":
                self.id_entry = widget

    def _build(self) -> None:
        page = ttk.Frame(self.window, padding=16)
        page.pack(fill="both", expand=True)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(1, weight=1)
        ttk.Label(page, text="Edit dictionary definitions", font=("Segoe UI", 17, "bold")).grid(
            sticky="w", pady=(0, 10)
        )
        self.tabs = ttk.Notebook(page)
        self.tabs.grid(row=1, sticky="nsew")
        metadata_page = ttk.Frame(self.tabs)
        self.tabs.add(metadata_page, text="Pack details")
        form = self._scroll_form(metadata_page)
        self._input(form, self.metadata, "id", "Pack ID", readonly=self.path is not None)
        self._input(form, self.metadata, "name", "Name")
        self._input(form, self.metadata, "version", "Version (e.g. 1.0.0)")
        self._input(form, self.metadata, "description", "Description", lines=5)
        self._input(form, self.metadata, "asset_classes", "Asset classes\nOne per line", lines=3)
        ttk.Label(
            form,
            text="Use a unique lowercase ID, such as custom.clo.\nAn existing pack keeps its ID; use Make a copy for a new identity.",
            wraplength=450,
            style="Muted.TLabel",
        ).grid(columnspan=2, sticky="w", pady=12)

        fields_page = ttk.Frame(self.tabs, padding=8)
        fields_page.columnconfigure(1, weight=1)
        fields_page.rowconfigure(0, weight=1)
        self.tabs.add(fields_page, text="Fields")
        listing = ttk.Frame(fields_page)
        listing.grid(sticky="nsew", padx=(0, 12))
        listing.columnconfigure(0, weight=1)
        listing.rowconfigure(0, weight=1)
        self.fields = ttk.Treeview(
            listing, columns=("name",), show="headings", selectmode="browse", height=8
        )
        self.fields.heading("name", text="Field", anchor="w")
        self.fields.column("name", width=220, minwidth=150)
        self.fields.grid(sticky="nsew")
        scroll = ttk.Scrollbar(listing, command=self.fields.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.fields.configure(yscrollcommand=scroll.set)
        self.fields.bind("<<TreeviewSelect>>", self._select)
        buttons = ttk.Frame(listing)
        buttons.grid(row=1, columnspan=2, sticky="ew", pady=8)
        self.add_button = ttk.Button(buttons, text="Add field", command=self.add_field)
        self.add_button.pack(side="left")
        self.remove_button = ttk.Button(buttons, text="Remove", command=self.remove_field)
        self.remove_button.pack(side="left", padx=6)
        details = ttk.Frame(fields_page)
        details.grid(row=0, column=1, sticky="nsew")
        details.columnconfigure(0, weight=1)
        details.rowconfigure(0, weight=1)
        tabs = ttk.Notebook(details)
        tabs.grid(sticky="nsew")
        basic_page, context_page = ttk.Frame(tabs), ttk.Frame(tabs)
        tabs.add(basic_page, text="Definition")
        tabs.add(context_page, text="Context and codes")
        basic, context = self._scroll_form(basic_page), self._scroll_form(context_page)
        for key, label in (("id", "Field ID"), ("label", "Name")):
            self._input(basic, self.inputs, key, label)
        self._input(
            basic, self.inputs, "data_type", "Expected type", options=tuple(sorted(DATA_TYPES))
        )
        self._input(basic, self.inputs, "entity", "Applies to", options=tuple(sorted(ENTITIES)))
        self._input(basic, self.inputs, "definition", "Meaning", lines=4)
        self._input(basic, self.inputs, "unit", "Unit")
        self._input(basic, self.inputs, "required", "Required", options=tuple(CHOICES))
        self._input(basic, self.inputs, "blank_allowed", "Blank allowed", options=tuple(CHOICES))
        for key, label, lines in (
            ("aliases", "Other names\nOne per line", 2),
            ("context", "Context needed\nOne per line", 2),
            ("notes", "Notes", 3),
        ):
            self._input(context, self.inputs, key, label, lines=lines)
        options = ("None", *(item["id"] for item in self.documents["code_lists.json"]))
        self._input(context, self.inputs, "code_list", "Allowed code list", options=options)
        self._input(
            context, self.inputs, "missing_code_list", "Missing-reason list", options=options
        )
        self._input(
            context, self.inputs, "missing_codes", "Permitted missing codes\nOne per line", lines=2
        )
        ttk.Label(
            context,
            text="Create or edit lists on the Allowed values tab, then select them here.",
            wraplength=400,
            style="Muted.TLabel",
        ).grid(columnspan=2, sticky="w", pady=8)
        self.apply_button = ttk.Button(
            details, text="Apply field to draft", command=self.apply_field
        )
        self.apply_button.grid(row=1, sticky="w", pady=(8, 0))

        citations_page = ttk.Frame(tabs, padding=12)
        citations_page.columnconfigure(0, weight=1)
        citations_page.rowconfigure(0, weight=1)
        tabs.add(citations_page, text="Citations")
        self.citations_text = tk.Text(
            citations_page, wrap="word", width=30, height=8, font=("Segoe UI", 10)
        )
        self.citations_text.grid(sticky="nsew")
        citation_scroll = ttk.Scrollbar(citations_page, command=self.citations_text.yview)
        citation_scroll.grid(row=0, column=1, sticky="ns")
        self.citations_text.configure(yscrollcommand=citation_scroll.set)
        self.citations_button = ttk.Button(
            citations_page, text="Edit citations", command=self.edit_citations
        )
        self.citations_button.grid(row=1, sticky="w", pady=8)
        self.content_pages = ContentPages(self)
        self.status_label = ttk.Label(page, textvariable=self.status, wraplength=760)
        self.status_label.grid(row=2, sticky="ew", pady=10)
        footer = ttk.Frame(page)
        footer.grid(row=3, sticky="ew")
        self.save_button = ttk.Button(
            footer, text="Save pack", style="Accent.TButton", command=self.save
        )
        self.save_button.pack(side="right")
        self.copy_button = ttk.Button(footer, text="Save as a copy…", command=self.save_as_copy)
        self.copy_button.pack(side="right", padx=8)
        ttk.Button(footer, text="Cancel", command=self.request_close).pack(side="left")

    @staticmethod
    def _get(inputs: dict[str, Input]) -> dict[str, str]:
        return {
            key: value.get("1.0", "end-1c") if isinstance(value, tk.Text) else value.get()
            for key, value in inputs.items()
        }

    @staticmethod
    def _set(inputs: dict[str, Input], values: dict[str, Any]) -> None:
        for key, widget in inputs.items():
            value = values.get(key)
            if key in {"required", "blank_allowed"}:
                text = next(label for label, choice in CHOICES.items() if choice is value)
            elif key in {"code_list", "missing_code_list"}:
                text = value or "None"
            else:
                text = "\n".join(value) if isinstance(value, list) else value or ""
            if isinstance(widget, tk.Text):
                widget.delete("1.0", "end")
                widget.insert("1.0", text)
            else:
                widget.set(text)

    def _metadata(self) -> dict[str, Any]:
        values: dict[str, Any] = self._get(self.metadata)
        original = self.original["pack.json"]["asset_classes"]
        values["asset_classes"] = (
            deepcopy(original)
            if values["asset_classes"] == "\n".join(original)
            else values["asset_classes"].splitlines()
        )
        values["format_version"] = 1
        return values

    def _field(self) -> dict[str, Any]:
        values: dict[str, Any] = self._get(self.inputs)
        for key in ("aliases", "context", "missing_codes"):
            original = self.loaded_field.get(key, [])
            values[key] = (
                deepcopy(original)
                if values[key] == "\n".join(original)
                else values[key].splitlines()
            )
        for key in ("required", "blank_allowed"):
            values[key] = CHOICES[values[key]]
        for key in ("unit", "notes"):
            values[key] = values[key] or None
        for key in ("code_list", "missing_code_list"):
            values[key] = None if values[key] == "None" else values[key]
        return values

    def _list_fields(self, index: int | None) -> None:
        self.switching = True
        self.fields.delete(*self.fields.get_children())
        for position, field in enumerate(self.documents["fields.json"]):
            self.fields.insert("", "end", iid=str(position), values=(field["label"],))
        self.index = index
        if index is not None:
            self.fields.selection_set(str(index))
            self.fields.see(str(index))
        self.loaded_field = deepcopy(
            self.documents["fields.json"][index]
            if index is not None
            else {"data_type": "text", "entity": "loan"}
        )
        self._set(self.inputs, self.loaded_field)
        self.field_baseline = self._field()
        self._citations()
        self.switching = False

    def apply_field(self) -> bool:
        if self.busy:
            return False
        try:
            values = self._field()
            if values != self.field_baseline:
                self.documents = update_field(self.documents, self.index, values, self.base)
                index = (
                    self.index if self.index is not None else len(self.documents["fields.json"]) - 1
                )
                self._list_fields(index)
                self._sources()
                self.status.set("Field applied to this draft. Save pack to keep it.")
            return True
        except (PackError, KeyError) as error:
            self._error(str(error))
            return False

    def _select(self, event: tk.Event[tk.Misc]) -> None:
        selected = self.fields.selection()
        if self.switching or self.busy or not selected or int(selected[0]) == self.index:
            return
        index = int(selected[0])
        if self.apply_field():
            self._list_fields(index)
        elif self.index is not None:
            self.fields.selection_set(str(self.index))
        else:
            self.fields.selection_remove(*self.fields.selection())

    def add_field(self) -> None:
        if not self.busy and self.apply_field():
            self._list_fields(None)
            self.tabs.select(1)  # type: ignore[no-untyped-call]

    def remove_field(self) -> None:
        if self.busy:
            return
        if self.index is not None:
            self.documents["fields.json"].pop(self.index)
        self._list_fields(0 if self.documents["fields.json"] else None)
        self.status.set("Field removed from the draft. Save pack to keep this change.")

    def _sources(self) -> None:
        self.content_pages.refresh()
        options = ("None", *(item["id"] for item in self.documents["code_lists.json"]))
        for widget in self.code_choices:
            widget.configure(values=options)
        self._citations()

    def _citations(self) -> None:
        self.citations_text.configure(state="normal")
        self.citations_text.delete("1.0", "end")
        text = "Apply a field to the draft before adding citations."
        if self.index is not None:
            refs = self.documents["fields.json"][self.index]["references"]
            text = "\n\n".join(f"{ref['source']}: {ref['locator']}" for ref in refs)
        self.citations_text.insert("1.0", text)
        self.citations_text.configure(state="disabled")

    def edit_citations(self) -> None:
        if self.busy or self.content_dialog is not None or not self.apply_field():
            return
        if self.index is None:
            self._error("Add and apply a field before editing its citations.")
            return
        self.content_dialog = ContentDialog(self, "citations", self.index)

    def dirty(self) -> bool:
        return (
            self.documents != self.original
            or self._metadata() != self.original["pack.json"]
            or self._field() != self.field_baseline
            or (self.content_dialog is not None and self.content_dialog.dirty())
        )

    def _error(self, message: str) -> None:
        self.status.set(message)
        self.status_label.configure(foreground="#a1342d")

    def save_as_copy(self) -> None:
        if self.busy or self.content_dialog is not None or not self.apply_field():
            return
        self.path = None
        if self.base is not None:
            record_copy(self.documents, self.base)
            self._sources()
        variable = self.metadata["id"]
        assert isinstance(variable, tk.StringVar)
        variable.set("")
        self.id_entry.configure({"state": "normal"})
        self.tabs.select(0)  # type: ignore[no-untyped-call]
        self.status.set(
            "Choose a new pack ID and name, then Save pack. The original stays unchanged."
        )

    def save(self) -> None:
        if self.busy or self.content_dialog is not None:
            return
        self.documents["pack.json"] = self._metadata()
        if not self.apply_field():
            return
        documents, store, path = deepcopy(self.documents), self.store, self.path
        expected = self.base.fingerprint if self.base is not None and path is not None else None
        results = self.results
        self.busy = True
        self.status.set("Saving dictionary files. Activation stays unchanged…")
        self.status_label.configure(foreground="#26352f")
        self._disable(self.window)

        def work() -> None:
            try:
                result: SavedPack | Exception = save_draft(
                    store, documents, path=path, expected_fingerprint=expected
                )
            except Exception as error:
                result = error
            results.put(result)

        self.workers.start(work, "save-dictionary-pack")

    def _disable(self, parent: tk.Misc) -> None:
        for child in parent.winfo_children():
            if "state" in child.keys():
                self.disabled.append((child, str(child.cget("state"))))
                child.configure({"state": "disabled"})
            self._disable(child)

    def _poll(self) -> None:
        if self.closed:
            return
        try:
            result = self.results.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            for widget, state in self.disabled:
                widget.configure({"state": state})
            self.disabled.clear()
            if isinstance(result, Exception):
                self._error(f"Could not save. Your draft is still open. {result}")
            else:
                self._destroy()
                self.on_saved(result)
                return
        self.poll_id = self.window.after(60, self._poll)

    def request_close(self) -> bool:
        if self.closed:
            return True
        if self.busy:
            self.status.set("A pack save is in progress. Please close again when it finishes.")
            self.window.lift()
            return False
        if self.dirty() and not messagebox.askokcancel(
            "Discard pack edits?",
            "This pack has unsaved edits. Close and discard this draft?",
            parent=self.window,
            default=messagebox.CANCEL,
        ):
            self.window.lift()
            return False
        self._destroy()
        return True

    def _destroy(self) -> None:
        if self.content_dialog is not None:
            self.content_dialog.destroy()
        self.closed = True
        self.window.after_cancel(self.poll_id)
        self.window.destroy()
        self.on_closed()
