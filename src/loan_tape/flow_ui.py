"""Small native control groups that wrap rather than disappear in narrow windows."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class FlowBar(ttk.Frame):
    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent)
        self.groups: dict[tk.Widget, bool] = {}
        self.bind("<Configure>", self._layout)

    def add(self, widget: tk.Widget) -> None:
        self.groups[widget] = True
        widget.bind("<Configure>", self._layout, add="+")
        self._layout()

    def show(self, widget: tk.Widget, visible: bool) -> None:
        if self.groups[widget] != visible:
            self.groups[widget] = visible
            self._layout()

    def _layout(self, event: tk.Event[tk.Misc] | None = None) -> None:
        width = self.winfo_width()
        row = column = used = 0
        for widget, visible in self.groups.items():
            if not visible:
                widget.grid_remove()
                continue
            required = widget.winfo_reqwidth() + 12
            if column and used + required > width:
                row += 1
                column = used = 0
            widget.grid(row=row, column=column, sticky="w", padx=(0, 12), pady=2)
            used += required
            column += 1
