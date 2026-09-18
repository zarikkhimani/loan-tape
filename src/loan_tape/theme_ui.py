"""Shared desktop colors and restrained native widget styles."""

from __future__ import annotations

import math
import tkinter as tk
from dataclasses import dataclass
from tkinter import font, ttk

BACKGROUND = "#fafaf8"
FOREGROUND = "#252d28"
MUTED = "#667067"
ACCENT = "#0d281d"
ACCENT_HOVER = "#183c2c"
SURFACE = "#ffffff"
CHROME = "#eff1ed"
BORDER = "#e2e6de"
SELECTION = "#e7eee4"
HOVER = "#f0f3ec"
ERROR = "#a1342d"
TAB_PADDING = (12, 6)


@dataclass(frozen=True)
class DesktopTheme:
    family: str
    button_images: tuple[tk.PhotoImage, ...]


def _button_surface(root: tk.Tk, color: str) -> tk.PhotoImage:
    """A small stretchable rounded surface; the button itself remains native ttk."""
    image = tk.PhotoImage(master=root, width=20, height=20)
    image.put(BACKGROUND, to=(0, 0, 20, 20))
    radius = 5
    for y in range(20):
        edge = min(y, 19 - y)
        inset = (
            math.ceil(radius - math.sqrt(radius**2 - (radius - edge - 0.5) ** 2))
            if edge < radius
            else 0
        )
        image.put(color, to=(inset, y, 20 - inset, y + 1))
    return image


def configure_theme(root: tk.Tk) -> DesktopTheme:
    """Configure one interpreter; retain native keyboard and focus behavior."""
    default = font.nametofont("TkDefaultFont", root=root)
    default.configure(size=10)
    family = str(default.actual("family"))
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("TFrame", background=BACKGROUND)
    style.configure("TLabel", background=BACKGROUND, foreground=FOREGROUND)
    style.configure("Muted.TLabel", foreground=MUTED)
    style.configure("TSeparator", background=BORDER)
    style.configure(
        "TButton",
        font=(family, 10),
        padding=(12, 8),
        background=BACKGROUND,
        foreground=FOREGROUND,
        borderwidth=1,
        relief="flat",
        bordercolor=BORDER,
        lightcolor=BACKGROUND,
        darkcolor=BACKGROUND,
    )
    style.map(
        "TButton",
        background=[("disabled", BACKGROUND), ("pressed", SELECTION), ("active", HOVER)],
        foreground=[("disabled", "#8c948b")],
        bordercolor=[("focus", ACCENT), ("active", BORDER)],
        lightcolor=[("active", HOVER)],
        darkcolor=[("active", HOVER)],
    )
    style.configure(
        "Accent.TButton",
        background=ACCENT,
        foreground=SURFACE,
        borderwidth=0,
        bordercolor=ACCENT,
        lightcolor=ACCENT,
        darkcolor=ACCENT,
        focuscolor=SURFACE,
    )
    primary_states = [("disabled", "#8b9b90"), ("pressed", ACCENT), ("active", ACCENT_HOVER)]
    style.map(
        "Accent.TButton",
        background=primary_states,
        bordercolor=primary_states,
        lightcolor=primary_states,
        darkcolor=primary_states,
        foreground=[("disabled", SURFACE)],
    )
    # Inherit the complete primary-button state map through the style name.
    style.configure("AddFile.Accent.TButton", padding=(17, 8))
    images = tuple(_button_surface(root, color) for color in (ACCENT, ACCENT_HOVER, "#8b9b90"))
    style.element_create(
        "Hunter.border",
        "image",
        images[0],
        ("disabled", images[2]),
        ("pressed", images[0]),
        ("active", images[1]),
        border=6,
        sticky="nswe",
    )
    style.layout(
        "AddFile.Accent.TButton",
        [
            (
                "Hunter.border",
                {
                    "sticky": "nswe",
                    "children": [
                        (
                            "Button.padding",
                            {
                                "sticky": "nswe",
                                "children": [
                                    (
                                        "Button.focus",
                                        {
                                            "sticky": "nswe",
                                            "children": [("Button.label", {"sticky": "nswe"})],
                                        },
                                    )
                                ],
                            },
                        )
                    ],
                },
            )
        ],
    )
    style.configure("Quiet.TButton", borderwidth=0, padding=(10, 6), foreground=MUTED)
    style.configure("FilesTitle.TLabel", font=(family, 27), foreground=FOREGROUND)
    style.configure("FilesCount.TLabel", font=(family, 10), foreground=MUTED)
    style.configure("Small.TLabel", font=(family, 9), foreground=MUTED)
    style.configure(
        "Files.Treeview",
        background=BACKGROUND,
        fieldbackground=BACKGROUND,
        foreground=FOREGROUND,
        rowheight=56,
        font=(family, 11),
        borderwidth=0,
    )
    style.configure(
        "Files.Treeview.Heading",
        font=(family, 9),
        foreground=MUTED,
        background=BACKGROUND,
        relief="flat",
        padding=(10, 12),
        borderwidth=0,
    )
    style.map(
        "Files.Treeview.Heading", background=[("active", HOVER)], relief=[("pressed", "flat")]
    )
    style.map(
        "Files.Treeview",
        background=[("selected", SELECTION)],
        foreground=[("selected", FOREGROUND)],
    )
    style.layout("Files.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
    style.configure(
        "Files.Treeview.Heading",
        bordercolor=BACKGROUND,
        lightcolor=BACKGROUND,
        darkcolor=BACKGROUND,
    )
    style.configure("Treeview", rowheight=32, font=(family, 10), borderwidth=0)
    style.configure("Treeview.Heading", font=(family, 10, "bold"), padding=(8, 8))
    style.map(
        "Treeview", background=[("selected", SELECTION)], foreground=[("selected", FOREGROUND)]
    )
    style.configure("TEntry", padding=7)
    style.map("TEntry", fieldbackground=[("readonly", SURFACE)])
    style.configure("Horizontal.TProgressbar", background=ACCENT)
    style.configure(
        "Files.Vertical.TScrollbar",
        arrowsize=11,
        width=11,
        borderwidth=0,
        background=BORDER,
        troughcolor=BACKGROUND,
    )
    configure_tabs(root)
    return DesktopTheme(family, images)


def configure_tabs(parent: tk.Misc) -> None:
    """Style tabs without replacing Notebook traversal or close hit-testing."""
    style = ttk.Style(parent)
    style.configure(
        "Workspace.TNotebook",
        background=CHROME,
        borderwidth=0,
        bordercolor=BACKGROUND,
        lightcolor=BACKGROUND,
        darkcolor=BACKGROUND,
        tabmargins=(12, 8, 0, 0),
    )
    style.configure(
        "Workspace.TNotebook.Tab",
        padding=TAB_PADDING,
        font="TkDefaultFont",
        background=CHROME,
        foreground=MUTED,
        borderwidth=0,
        lightcolor=CHROME,
        darkcolor=CHROME,
        focuscolor=ACCENT,
        bordercolor=CHROME,
    )
    style.map(
        "Workspace.TNotebook.Tab",
        background=[("selected", BACKGROUND), ("active", HOVER)],
        foreground=[("selected", FOREGROUND), ("active", FOREGROUND)],
        lightcolor=[("selected", BACKGROUND)],
        darkcolor=[("selected", BACKGROUND)],
        expand=[("selected", (0, 0, 0, 0))],
        padding=[("selected", TAB_PADDING), ("!selected", TAB_PADDING)],
        bordercolor=[("selected", BACKGROUND), ("!selected", CHROME)],
    )
