"""Native desktop file intake; all file operations remain in the application service."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Literal, Protocol, cast

from tkinterdnd2 import DND_FILES, TkinterDnD  # type: ignore[import-untyped]

from loan_tape.intake import IntakeError, IntakeStore, SavedFile
from loan_tape.order_ui import OrderPanel
from loan_tape.pack_ui import PackManager
from loan_tape.packs import PackStore
from loan_tape.preview_ui import PreviewPanel
from loan_tape.session import start_session
from loan_tape.tabs_ui import WorkspaceTabs
from loan_tape.theme_ui import ACCENT, BACKGROUND, ERROR, configure_theme
from loan_tape.workers import WorkerGroup
from loan_tape.workspace_reset import reset_file_session

PREVIEW_EXTENSIONS = frozenset({".csv", ".xml", ".xlsx", ".xlsm"})
FORMAT_CAPABILITIES = {
    ".xlsx": "Full workbook review available",
    ".xlsm": "Full workbook review available",
    ".xml": "XML review and XSD validation available",
    ".csv": "Preview only · Complete-column review unavailable",
    ".xls": "Preserved only · In-app preview unavailable",
    ".xlsb": "Preserved only · In-app preview unavailable",
}


class DropEvent(Protocol):
    @property
    def data(self) -> str: ...


class DropTarget(Protocol):
    def drop_target_register(self, *types: str) -> None: ...
    def dnd_bind(self, sequence: str, func: Callable[[DropEvent], str]) -> str: ...


def create_root() -> tk.Tk:
    """Load the native drag-and-drop extension; failure must be visible."""
    return cast(tk.Tk, TkinterDnD.Tk())


def display_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def format_capability(name: str) -> tuple[str, bool]:
    extension = Path(name).suffix.lower()
    return (
        FORMAT_CAPABILITIES.get(extension, "In-app preview availability unknown"),
        extension in PREVIEW_EXTENSIONS,
    )


class LoanTapeApp:
    def __init__(self, root: tk.Tk, store: IntakeStore) -> None:
        self.session = start_session()
        self.root = root
        self.store = store
        self.pack_store = PackStore(Path("packs"), Path(".artifacts/packs"))
        self.records: dict[str, SavedFile] = {}
        self.workers = WorkerGroup()
        self.inspector: PreviewPanel | None = None
        self.order_panel: OrderPanel | None = None
        self.pack_manager: PackManager | None = None
        self.results: queue.Queue[SavedFile | Exception] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.closing = False
        self.closed = False
        self.status = tk.StringVar(master=root, value="Add a file to get started.")
        self.capability = tk.StringVar(master=root)
        self.original_path = tk.StringVar(master=root)
        self.saved_path = tk.StringVar(master=root)
        self.root.title("Loan Tape")
        self.root.geometry(f"960x{min(800, self.root.winfo_screenheight() - 70)}")
        self.root.minsize(760, 720)
        self.root.configure(background=BACKGROUND)
        self._build()
        self._register_drops()
        self.root.protocol("WM_DELETE_WINDOW", self.request_exit)
        self.root.bind("<Control-w>", self._close_active_tab)
        self.refresh()
        self.poll_id = self.root.after(80, self._poll)

    def _build(self) -> None:
        self.theme = configure_theme(self.root)
        self.font_family = self.theme.family
        self.tabs = WorkspaceTabs(self.root, self.close_preview)
        self.tabs.pack(fill="both", expand=True)
        self.files_page = page = ttk.Frame(self.tabs, padding=(36, 30, 36, 18))
        self.tabs.add(page, text="Files")
        self.tabs.bind("<<NotebookTabChanged>>", self._tab_changed)
        page.columnconfigure(0, weight=1)
        page.rowconfigure(2, weight=1)

        heading = ttk.Frame(page)
        heading.grid(row=0, sticky="ew", pady=(0, 26))
        heading.columnconfigure(0, weight=1)
        ttk.Label(heading, text="Files", style="FilesTitle.TLabel").grid(row=0, sticky="w")
        self.saved_heading = ttk.Label(heading, text="No session files", style="FilesCount.TLabel")
        self.saved_heading.grid(row=1, sticky="w", pady=(5, 0))
        self.browse_button = ttk.Button(
            heading, text="+  Add file", style="AddFile.Accent.TButton", command=self.browse
        )
        self.browse_button.grid(row=0, column=1, rowspan=2, sticky="e")

        self.drop_zone = page
        self.drop_title = ttk.Label(
            page,
            text="CSV, XML or Excel · Drop a file anywhere · Up to 100 MB",
            style="Small.TLabel",
        )
        self.drop_title.grid(row=1, sticky="w", pady=(0, 12))

        history = ttk.Frame(page)
        history.grid(row=2, sticky="nsew")
        history.columnconfigure(0, weight=1)
        history.rowconfigure(0, weight=1)
        self.history = ttk.Treeview(
            history,
            columns=("name", "size", "saved"),
            displaycolumns=("name", "saved", "size"),
            show="headings",
            selectmode="browse",
            height=5,
            style="Files.Treeview",
        )
        for column, title, width in (
            ("name", "Name", 360),
            ("saved", "Added", 165),
            ("size", "Size", 85),
        ):
            anchor: Literal["w", "e"] = "e" if column == "size" else "w"
            self.history.heading(column, text=title, anchor=anchor)
            self.history.column(
                column, width=width, minwidth=65, stretch=column == "name", anchor=anchor
            )
        self.history.grid(sticky="nsew")
        scrollbar = ttk.Scrollbar(
            history,
            orient="vertical",
            command=self.history.yview,
            style="Files.Vertical.TScrollbar",
        )

        def scroll_state(first: float, last: float) -> None:
            scrollbar.set(first, last)
            if float(first) <= 0 and float(last) >= 1:
                scrollbar.grid_remove()
            else:
                scrollbar.grid(row=0, column=1, sticky="ns")

        self.history.configure(yscrollcommand=scroll_state)
        self.history.bind("<<TreeviewSelect>>", self._select)
        self.history.bind("<Double-1>", self._open_row)
        self.history.bind("<Return>", self._open_selected)
        self.empty_state = ttk.Frame(history)
        ttk.Label(
            self.empty_state, text="Your files will appear here", font=(self.font_family, 15)
        ).pack()
        ttk.Label(
            self.empty_state, text="Add a file or drop one into this window.", style="Muted.TLabel"
        ).pack(pady=(9, 0))

        actions = ttk.Frame(page)
        actions.grid(row=3, sticky="ew", pady=(12, 8))
        actions.columnconfigure(1, weight=1)
        self.refresh_button = ttk.Button(
            actions, text="Refresh", style="Quiet.TButton", command=self.refresh
        )
        self.refresh_button.grid(row=0, column=0, sticky="w")
        self.capability_label = ttk.Label(
            actions,
            textvariable=self.capability,
            style="Small.TLabel",
            anchor="e",
            justify="right",
        )
        self.capability_label.grid(row=0, column=1, sticky="e", padx=(12, 14))
        self.details_button = ttk.Button(
            actions, text="Details", style="Quiet.TButton", command=self._toggle_details
        )
        self.details_button.grid(row=0, column=2, padx=(0, 6))
        self.inspect_button = ttk.Button(actions, text="Open file", command=self.inspect_file)
        self.inspect_button.grid(row=0, column=3)

        self.file_details = details = ttk.Frame(page, padding=(0, 12, 0, 6))
        details.grid(row=4, sticky="ew")
        details.columnconfigure(1, weight=1)
        ttk.Separator(details).grid(row=0, columnspan=3, sticky="ew", pady=(0, 12))
        self.original_button = self._path_row(
            details, 1, "Original location", self.original_path, "Copy original"
        )
        self.saved_button = self._path_row(details, 2, "Saved copy", self.saved_path, "Copy saved")
        self.folder_label = ttk.Label(
            details,
            text=f"Save folder: {self.store.directory}",
            style="Small.TLabel",
            wraplength=600,
        )
        self.folder_label.grid(row=3, columnspan=3, sticky="w", pady=(9, 0))
        details.grid_remove()

        feedback = ttk.Frame(page)
        feedback.grid(row=5, sticky="ew", pady=(3, 12))
        feedback.columnconfigure(0, weight=1)
        self.status_label = ttk.Label(
            feedback,
            textvariable=self.status,
            wraplength=600,
            foreground=ACCENT,
            style="Small.TLabel",
        )
        self.status_label.grid(sticky="ew")
        self.progress = ttk.Progressbar(feedback, mode="indeterminate", length=80)
        self.progress.grid(row=0, column=1, padx=(12, 0))
        self.progress.grid_remove()

        ttk.Separator(page).grid(row=6, sticky="ew")
        footer = ttk.Frame(page)
        footer.grid(row=7, sticky="ew", pady=(12, 0))
        footer.columnconfigure(0, weight=1)
        ttk.Label(
            footer,
            text="Originals stay untouched · Working files reset on Exit",
            style="Small.TLabel",
        ).grid(row=0, sticky="w")
        self.packs_button = ttk.Button(
            footer, text="Dictionary packs", style="Quiet.TButton", command=self.open_packs
        )
        self.packs_button.grid(row=0, column=1)
        self.exit_button = ttk.Button(
            footer, text="Exit", style="Quiet.TButton", command=self.request_exit
        )
        self.exit_button.grid(row=0, column=2, padx=(6, 0))
        self.session_label = ttk.Label(page, text=self.session.startup_label, style="Small.TLabel")
        self.session_label.grid(row=8, sticky="w", pady=(8, 0))
        page.bind("<Configure>", self._fit_files)

    def _fit_files(self, event: tk.Event[tk.Misc]) -> None:
        width = max(260, event.width - 84)
        self.status_label.configure(wraplength=max(200, width - 96))
        self.capability_label.configure(wraplength=max(160, width - 330))
        self.folder_label.configure(wraplength=width)
        self.session_label.configure(wraplength=width)
        self.drop_title.configure(wraplength=width)

    def _toggle_details(self) -> None:
        if self.closing:
            return
        if self.file_details.winfo_manager():
            self.file_details.grid_remove()
            self.details_button.configure(text="Details")
        else:
            self.file_details.grid()
            self.details_button.configure(text="Hide details")

    def _open_selected(self, event: tk.Event[tk.Misc] | None = None) -> str:
        self.inspect_file()
        return "break"

    def _open_row(self, event: tk.Event[tk.Misc]) -> str:
        row = self.history.identify_row(event.y)
        if row and self.history.identify_region(event.x, event.y) in {"cell", "tree"}:
            self.history.selection_set(row)
            self._select()
            self.inspect_file()
        return "break"

    def _update_file_count(self) -> None:
        count = len(self.records)
        self.saved_heading.configure(
            text=f"{count} session file{'s' if count != 1 else ''}" if count else "No session files"
        )
        if count:
            self.empty_state.place_forget()
        else:
            self.empty_state.place(relx=0.5, rely=0.42, anchor="center")

    def _path_row(
        self, parent: ttk.Frame, row: int, label: str, value: tk.StringVar, button: str
    ) -> ttk.Button:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=4)
        entry = ttk.Entry(parent, textvariable=value, state="readonly")
        entry.grid(row=row, column=1, sticky="ew", pady=4)
        copy = ttk.Button(parent, text=button, command=lambda: self.copy_location(value.get()))
        copy.grid(row=row, column=2, padx=(10, 0), pady=4)
        return copy

    def _register_drops(self, parent: tk.Misc | None = None) -> None:
        # Register descendants so dropping over text, buttons, or the list also works.
        pending: list[tk.Misc] = [parent if parent is not None else self.root]
        while pending:
            widget = pending.pop()
            if isinstance(widget, tk.Toplevel):
                continue
            target = cast(DropTarget, widget)
            target.drop_target_register(DND_FILES)
            target.dnd_bind("<<Drop>>", self._drop)
            pending.extend(widget.winfo_children())

    def _message(self, text: str, *, error: bool = False) -> None:
        self.status.set(text)
        self.status_label.configure(foreground=ERROR if error else ACCENT)

    def _drop(self, event: DropEvent) -> str:
        if self.closing:
            return "refuse_drop"
        self.tabs.select(self.files_page)
        try:
            paths = self.root.tk.splitlist(event.data)
        except tk.TclError:
            self._message(
                "The dropped file location could not be read. Use Add file instead.", error=True
            )
            return "refuse_drop"
        if len(paths) != 1:
            self._message("Please choose one file at a time.", error=True)
            return "refuse_drop"
        return "copy" if self.add_file(Path(paths[0])) else "refuse_drop"

    def browse(self) -> None:
        if self.worker is not None or self.closing:
            return
        selected = filedialog.askopenfilename(
            parent=self.root,
            title="Choose a CSV, XML, or Excel file",
            filetypes=[
                ("CSV, XML, and Excel", "*.csv *.xml *.xlsx *.xls *.xlsm *.xlsb"),
                ("All files", "*.*"),
            ],
        )
        if selected:
            self.add_file(Path(selected))

    def add_file(self, path: Path) -> bool:
        if self.worker is not None or self.closing:
            self._message("A file is still saving. Wait for it to finish.", error=True)
            return False
        self._message(f"Saving {path.name}…")
        self.browse_button.state(["disabled"])
        self.refresh_button.state(["disabled"])
        self.drop_title.configure(text="Saving your file…")
        self.progress.grid()
        self.progress.start(12)

        store, results = self.store, self.results

        def copy() -> None:
            try:
                result: SavedFile | Exception = store.save_path(path)
            except Exception as error:
                # Report worker failures to the main thread rather than losing them.
                result = error
            results.put(result)

        self.worker = self.workers.start(copy, "file-copy")
        return True

    def _poll(self) -> None:
        if self.closed:
            return
        try:
            result = self.results.get_nowait()
        except queue.Empty:
            pass
        else:
            if self.worker is not None:
                self.worker.join()
                self.worker = None
            self.progress.stop()
            self.progress.grid_remove()
            self.browse_button.state(["!disabled"])
            self.refresh_button.state(["!disabled"])
            self.drop_title.configure(
                text="CSV, XML or Excel · Drop a file anywhere · Up to 100 MB"
            )
            if isinstance(result, Exception):
                if isinstance(result, IntakeError):
                    message = str(result)
                elif isinstance(result, FileNotFoundError):
                    message = "The file could not be found. Choose it again."
                elif isinstance(result, PermissionError):
                    message = "Could not read or save the file. Check file and folder permissions."
                else:
                    message = "Could not save the file. Check disk space and file access."
                self._message(message, error=True)
            else:
                self.records[result["id"]] = result
                self._insert(result, 0)
                self.history.selection_set(result["id"])
                self.history.see(result["id"])
                self._select()
                _, can_preview = format_capability(result["original_name"])
                if can_preview:
                    message = (
                        f"{result['original_name']} saved. Select Open file to preview its data."
                    )
                else:
                    message = (
                        f"{result['original_name']} saved unchanged. "
                        "In-app preview is unavailable for this format."
                    )
                self._message(message)
        if self.closing:
            if self.worker is None and not self.workers.active_names():
                self._destroy()
                return
            self._message("Closing Loan Tape: finishing the save and stopping background work...")
        self.poll_id = self.root.after(80, self._poll)

    def _insert(self, record: SavedFile, index: int | Literal["end"] = "end") -> None:
        saved_at = (
            datetime.fromisoformat(record["saved_at"]).astimezone().strftime("%b %d, %Y  %H:%M")
        )
        self.history.insert(
            "",
            index,
            iid=record["id"],
            values=(record["original_name"], display_size(record["size_bytes"]), saved_at),
        )
        self._update_file_count()

    def refresh(self) -> None:
        if self.worker is not None or self.closing:
            return
        selected = self.history.selection()
        try:
            records = self.store.list_files()
        except (IntakeError, OSError) as error:
            self._message(str(error), error=True)
            return
        self.records = {record["id"]: record for record in records}
        for item in self.history.get_children():
            self.history.delete(item)
        for record in records:
            self._insert(record)
        self._update_file_count()
        if records:
            identity = selected[0] if selected and selected[0] in self.records else records[0]["id"]
            self.history.selection_set(identity)
        self._select()
        self._message("")

    def _select(self, event: tk.Event[tk.Misc] | None = None) -> None:
        selection = self.history.selection()
        record = self.records.get(selection[0]) if selection else None
        self.original_path.set(
            record["original_path"] or "Not recorded for this earlier copy" if record else ""
        )
        self.saved_path.set(str(self.store.describe(record)["saved_path"]) if record else "")
        self.original_button.state(
            ["!disabled"] if record and record["original_path"] else ["disabled"]
        )
        self.saved_button.state(["!disabled"] if record else ["disabled"])
        capability, can_preview = (
            format_capability(record["original_name"]) if record else ("", False)
        )
        self.capability.set(capability)
        self.inspect_button.configure(
            text="Open file" if record is None or can_preview else "Preview unavailable"
        )
        self.inspect_button.state(["!disabled"] if can_preview else ["disabled"])
        self.details_button.state(["!disabled"] if record else ["disabled"])
        if record is None:
            self.file_details.grid_remove()
            self.details_button.configure(text="Details")

    def inspect_file(self) -> None:
        if self.closing:
            return
        selected = self.history.selection()
        record = self.records.get(selected[0]) if selected else None
        if record is None:
            return
        path = Path(str(self.store.describe(record)["saved_path"]))
        if path.suffix.lower() not in PREVIEW_EXTENSIONS:
            self.tabs.select(self.files_page)
            self._message(
                f"{path.suffix.lower()} files are preserved, but in-app preview is unavailable. "
                "Save a separate .xlsx copy to review it.",
                error=True,
            )
            return
        if self.inspector is not None and not self.inspector.closed:
            if self.inspector.path == path:
                self.activate_preview()
                return
            if not self._allow_discard_setup():
                return
            self.inspector.close()
        self.inspector = PreviewPanel(
            self.tabs,
            path,
            self.session,
            self.workers,
            self.activate_preview,
            self._preview_closed,
            self.pack_store,
        )
        self.tabs.add_preview(self.inspector.frame, path.name)
        self.order_panel = OrderPanel(
            self.tabs,
            path,
            self.session,
            self.inspector.order_scope,
            self.inspector._jump_to_column_row,
            self.activate_preview,
            self.workers,
        )
        self.tabs.add(self.order_panel.frame, text="Order")
        self._register_drops(self.inspector.frame)
        self._register_drops(self.order_panel.frame)
        excel = path.suffix.lower() in {".xlsx", ".xlsm"}
        self.root.minsize(980 if excel else 760, 740 if excel else 720)
        width = min(1180 if excel else 1080, self.root.winfo_screenwidth() - 60)
        height = min(920 if excel else 800, self.root.winfo_screenheight() - 70)
        self.root.geometry(
            f"{max(self.root.winfo_width(), width)}x{max(self.root.winfo_height(), height)}"
        )
        self.activate_preview()

    def activate_preview(self) -> None:
        if self.inspector is not None and not self.inspector.closed and not self.closing:
            self.tabs.select(self.inspector.frame)
            self.inspector.table.focus_set()

    def _tab_changed(self, event: tk.Event[tk.Misc] | None = None) -> None:
        if self.closed:
            return
        selected = str(self.tabs.select())
        active = (
            self.inspector is not None
            and not self.inspector.closed
            and selected == str(self.inspector.frame)
        )
        ordering = (
            self.order_panel is not None
            and not self.order_panel.closed
            and selected == str(self.order_panel.frame)
        )
        if active and self.inspector:
            title = f"{self.inspector.path.name} — Loan Tape"
        elif ordering and self.inspector:
            title = f"Order — {self.inspector.path.name} — Loan Tape"
        else:
            title = "Loan Tape"
        self.root.title(title)
        if self.inspector is not None and not self.inspector.closed:
            self.inspector.set_active(active)
        if ordering and self.order_panel is not None:
            self.order_panel.activate()

    def _allow_discard_setup(self) -> bool:
        if self.inspector is None or self.inspector.closed:
            return True
        navigator = self.inspector.navigator or self.inspector.xml_navigation
        if navigator is None or not navigator.has_unsaved_setup():
            return True
        self.activate_preview()
        return messagebox.askokcancel(
            "Discard unsaved setup?",
            "This file has unsaved data set setup changes. Close it and discard those changes?\n\n"
            "Choose Cancel to return and Save data set. The source file stays unchanged.",
            parent=self.root,
            default=messagebox.CANCEL,
        )

    def close_preview(self) -> None:
        if self.closing or not self._allow_discard_setup():
            return
        if self.inspector is not None:
            self.inspector.close()

    def _close_active_tab(self, event: tk.Event[tk.Misc]) -> str:
        if str(self.tabs.select()) != str(self.files_page):
            self.close_preview()
        return "break"

    def _preview_closed(self) -> None:
        if self.order_panel is not None and not self.order_panel.closed:
            self.order_panel.close()
        self.tabs.select(self.files_page)
        self.root.title("Loan Tape")
        self.root.minsize(760, 720)
        self.history.focus_set()

    def open_packs(self) -> None:
        if self.closing:
            return
        if self.pack_manager is None or self.pack_manager.closed:
            self.pack_manager = PackManager(self.root, self.pack_store, self.workers)
        self.pack_manager.window.deiconify()
        self.pack_manager.window.lift()
        self.pack_manager.window.focus_set()

    def request_exit(self) -> None:
        if not self.closing and self._allow_discard_setup():
            self.close()

    def copy_location(self, path: str) -> None:
        if not path:
            return
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(path)
            self.root.update_idletasks()
        except tk.TclError:
            self._message(
                "Clipboard unavailable. Select the location and press Ctrl+C.", error=True
            )
        else:
            self._message("Location copied.")

    def close(self) -> None:
        if self.closed:
            return
        if self.pack_manager is not None and not self.pack_manager.close():
            return
        self.closing = True
        self.exit_button.configure(text="Closing...", state="disabled")
        self.workers.cancel_reads()
        self.packs_button.state(["disabled"])
        if self.inspector is not None:
            self.inspector.close()
        elif self.order_panel is not None:
            self.order_panel.close()
        self.browse_button.state(["disabled"])
        self.refresh_button.state(["disabled"])
        self.inspect_button.state(["disabled"])
        self.details_button.state(["disabled"])
        if self.worker is not None or self.workers.active_names():
            self._message("Closing Loan Tape: finishing the save and stopping background work...")
            return
        self._destroy()

    def _destroy(self) -> None:
        if self.inspector is not None:
            self.inspector.close()
        elif self.order_panel is not None:
            self.order_panel.close()
        try:
            reset_file_session(self.store, self.session.id)
        except (IntakeError, OSError) as error:
            self.closing = False
            self.exit_button.configure(text="Exit", state="normal")
            self.packs_button.state(["!disabled"])
            self.browse_button.state(["!disabled"])
            self.refresh_button.state(["!disabled"])
            self._select()
            message = (
                "Loan Tape could not remove its session working files. Close any saved copy "
                "that is open in Excel, then choose Exit again. The original source file "
                f"was not changed.\n\nDetails: {error}"
            )
            self._message(message, error=True)
            messagebox.showerror("Session reset incomplete", message, parent=self.root)
            return
        self.closed = True
        self.root.after_cancel(self.poll_id)
        self.root.destroy()


def launch(directory: Path) -> int:
    root = create_root()
    try:
        LoanTapeApp(root, IntakeStore(directory))
        root.mainloop()
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass  # The normal window-close handler already destroyed the root.
    return 0
