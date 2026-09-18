"""Draw a selected column over a native row-based Treeview without changing its data."""

from __future__ import annotations

import tkinter as tk
from functools import partial
from tkinter import font, ttk


class ColumnHighlight:
    """A clipped visual layer; pointer gestures still reach the original grid."""

    def __init__(self, table: ttk.Treeview, body_font: font.Font, heading_font: font.Font) -> None:
        self.table = table
        self.body_font, self.heading_font = body_font, heading_font
        self.column: str | None = None
        self.pending: str | None = None
        self.closed = False
        self.canvas = tk.Canvas(
            table, background="#e1f0e8", highlightthickness=0, borderwidth=0, takefocus=False
        )
        for sequence in (
            "<ButtonPress-1>",
            "<ButtonRelease-1>",
            "<B1-Motion>",
            "<Button-3>",
            "<MouseWheel>",
        ):
            self.canvas.bind(sequence, partial(self._forward, sequence))
        table.bind("<Configure>", lambda event: self.refresh(), add="+")
        table.bind("<B1-Motion>", lambda event: self.refresh(), add="+")

    def _forward(self, sequence: str, event: tk.Event[tk.Misc]) -> str:
        if sequence == "<ButtonPress-1>":
            self.table.focus_set()
        x = event.x_root - self.table.winfo_rootx()
        y = event.y_root - self.table.winfo_rooty()
        if sequence == "<MouseWheel>":
            self.table.event_generate(sequence, x=x, y=y, state=int(event.state), delta=event.delta)
        else:
            self.table.event_generate(sequence, x=x, y=y, state=int(event.state))
        return "break"

    def select(self, column: str | None) -> None:
        self.column = column
        if column is None:
            self.canvas.place_forget()
        self.refresh()

    def refresh(self) -> None:
        if not self.closed and self.pending is None:
            self.pending = self.table.after_idle(self._draw)

    def _draw(self) -> None:
        self.pending = None
        if self.closed:
            return
        self.canvas.delete("all")
        if self.column is None or self.column not in self.table["columns"]:
            self.canvas.place_forget()
            return
        cells = [(item, self.table.bbox(item, self.column)) for item in self.table.get_children()]
        visible = [(item, box) for item, box in cells if box]
        if not visible:
            self.canvas.place_forget()
            return
        x, heading_height, width, _ = visible[0][1]
        left, right = max(1, x), min(self.table.winfo_width() - 1, x + width)
        if right <= left:
            self.canvas.place_forget()
            return
        height = self.table.winfo_height() - 1
        self.canvas.place(x=left, y=0, width=right - left, height=height)
        self.canvas.create_rectangle(0, 0, right - left, heading_height, fill="#23634c", outline="")
        self.canvas.create_text(
            x - left + 4,
            heading_height / 2,
            text=self.table.heading(self.column, "text"),
            font=self.heading_font,
            fill="white",
            anchor="w",
            tags="heading",
        )
        for item, (_, y, _, row_height) in visible:
            if y + row_height > height:
                continue  # Native Treeview paints only complete rows at the bottom edge.
            self.canvas.create_text(
                x - left + 4,
                y + row_height / 2,
                text=self.table.set(item, self.column),
                font=self.body_font,
                fill="#162b23",
                anchor="w",
                tags=("cell", item),
            )
            if "difference" in self.table.item(item, "tags"):
                self.canvas.create_rectangle(1, y, 4, y + row_height, fill="#bd7e21", outline="")
        self.canvas.create_rectangle(
            0, 0, right - left - 1, height - 1, outline="#23634c", width=1, tags="outline"
        )

    def close(self) -> None:
        self.closed = True
        if self.pending is not None:
            self.table.after_cancel(self.pending)
            self.pending = None
