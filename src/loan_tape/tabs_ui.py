"""Native workspace tabs with a close target on the single file tab."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import font, ttk

from loan_tape.theme_ui import TAB_PADDING, configure_tabs


class WorkspaceTabs(ttk.Notebook):
    def __init__(self, parent: tk.Tk, close_preview: Callable[[], None]) -> None:
        configure_tabs(parent)
        super().__init__(parent, style="Workspace.TNotebook")
        self.close_preview = close_preview
        self._pressed_close = False
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<ButtonRelease-1>", self._release)
        self.enable_traversal()

    def select(self, tab_id: ttk.Frame | str | None = None) -> str:
        return str(super().select(tab_id))  # type: ignore[no-untyped-call]

    def index(self, tab_id: str | int) -> int:
        return int(super().index(tab_id))  # type: ignore[no-untyped-call]

    def add_preview(self, frame: ttk.Frame, name: str) -> None:
        # The complete name stays in the preview heading and main window title.
        label = name if len(name) <= 40 else name[:25] + "…" + name[-12:]
        self.add(frame, text=label + "   ×")

    def _over_close(self, x: int, y: int) -> bool:
        """Hit-test the trailing × using the native tab boundary and font size.

        Notebook has no per-tab child buttons or bounding-box API. Looking just
        beyond the close glyph plus right padding finds its right edge without
        assuming a filename width, display scale, or selected-tab position.
        """
        if not self.identify(x, y):
            return False
        try:
            if self.index(f"@{x},{y}") != 1:
                return False
        except tk.TclError:
            return False
        close_width = font.nametofont("TkDefaultFont").measure("×") + TAB_PADDING[0] + 4
        try:
            return self.index(f"@{x + close_width},{y}") != 1
        except tk.TclError:
            return True  # Past the right edge of the file tab.

    def _press(self, event: tk.Event[tk.Misc]) -> str | None:
        self._pressed_close = self._over_close(event.x, event.y)
        return "break" if self._pressed_close else None

    def _release(self, event: tk.Event[tk.Misc]) -> str | None:
        pressed, self._pressed_close = self._pressed_close, False
        if pressed:
            if self._over_close(event.x, event.y):
                self.close_preview()
            return "break"
        return None
