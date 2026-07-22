"""Apple-inspired light theme helpers for the control GUI."""

from __future__ import annotations

import platform
import tkinter as tk
from tkinter import ttk


# Soft light palette close to macOS system settings / Finder.
BG = "#F5F5F7"
SURFACE = "#FFFFFF"
SURFACE_2 = "#EFEFF4"
TEXT = "#1D1D1F"
TEXT_SECONDARY = "#6E6E73"
BORDER = "#D2D2D7"
ACCENT = "#0071E3"
ACCENT_PRESSED = "#0077ED"
DANGER = "#FF3B30"
SUCCESS = "#34C759"
LOG_BG = "#1D1D1F"
LOG_FG = "#F5F5F7"


def ui_font(size: int = 12, weight: str = "normal") -> tuple:
    system = platform.system()
    if system == "Darwin":
        family = "SF Pro Text"
    elif system == "Windows":
        family = "Segoe UI"
    else:
        # Ubuntu / GNOME — clean sans close to Apple's weight/feel
        family = "Ubuntu"
    return (family, size, weight) if weight != "normal" else (family, size)


def apply_theme(root: tk.Tk) -> ttk.Style:
    root.configure(bg=BG)
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure(".", background=BG, foreground=TEXT, font=ui_font(11))
    style.configure("TFrame", background=BG)
    style.configure("Surface.TFrame", background=SURFACE)
    style.configure("Card.TFrame", background=SURFACE, relief="flat")
    style.configure("TLabel", background=BG, foreground=TEXT, font=ui_font(11))
    style.configure("Surface.TLabel", background=SURFACE, foreground=TEXT, font=ui_font(11))
    style.configure("Title.TLabel", background=BG, foreground=TEXT, font=ui_font(22, "bold"))
    style.configure("Subtitle.TLabel", background=BG, foreground=TEXT_SECONDARY, font=ui_font(11))
    style.configure("Section.TLabel", background=BG, foreground=TEXT, font=ui_font(13, "bold"))
    style.configure("Caption.TLabel", background=SURFACE, foreground=TEXT_SECONDARY, font=ui_font(10))
    style.configure("Status.TLabel", background=BG, foreground=TEXT_SECONDARY, font=ui_font(12))

    style.configure(
        "TNotebook",
        background=BG,
        borderwidth=0,
        tabmargins=(8, 8, 8, 0),
    )
    style.configure(
        "TNotebook.Tab",
        background=SURFACE_2,
        foreground=TEXT_SECONDARY,
        padding=(16, 8),
        font=ui_font(11),
        borderwidth=0,
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", SURFACE)],
        foreground=[("selected", TEXT)],
    )

    style.configure(
        "Accent.TButton",
        background=ACCENT,
        foreground="#FFFFFF",
        font=ui_font(11, "bold"),
        padding=(16, 8),
        borderwidth=0,
        focuscolor=ACCENT,
    )
    style.map(
        "Accent.TButton",
        background=[("active", ACCENT_PRESSED), ("disabled", "#A1C9F5")],
        foreground=[("disabled", "#FFFFFF")],
    )

    style.configure(
        "Secondary.TButton",
        background=SURFACE_2,
        foreground=TEXT,
        font=ui_font(11),
        padding=(14, 8),
        borderwidth=0,
    )
    style.map("Secondary.TButton", background=[("active", BORDER)])

    style.configure(
        "Danger.TButton",
        background=SURFACE_2,
        foreground=DANGER,
        font=ui_font(11),
        padding=(14, 8),
        borderwidth=0,
    )
    style.map("Danger.TButton", background=[("active", "#FFE5E5")])

    style.configure(
        "TEntry",
        fieldbackground=SURFACE,
        foreground=TEXT,
        insertcolor=TEXT,
        padding=8,
        bordercolor=BORDER,
        lightcolor=BORDER,
        darkcolor=BORDER,
    )
    style.configure(
        "TCheckbutton",
        background=SURFACE,
        foreground=TEXT,
        font=ui_font(11),
        focuscolor=BG,
    )
    style.configure(
        "Treeview",
        background=SURFACE,
        fieldbackground=SURFACE,
        foreground=TEXT,
        rowheight=28,
        font=ui_font(11),
        bordercolor=BORDER,
    )
    style.configure(
        "Treeview.Heading",
        background=SURFACE_2,
        foreground=TEXT_SECONDARY,
        font=ui_font(10, "bold"),
        relief="flat",
    )
    style.map("Treeview", background=[("selected", "#D6E7FF")], foreground=[("selected", TEXT)])
    style.configure("TScrollbar", background=SURFACE_2, troughcolor=BG, bordercolor=BG, arrowsize=12)
    return style


def bind_mousewheel(widget: tk.Misc, canvas: tk.Canvas) -> None:
    """Scroll `canvas` for wheel events on `widget` and its descendants."""

    def _on_linux_up(_event: tk.Event) -> str | None:
        canvas.yview_scroll(-3, "units")
        return "break"

    def _on_linux_down(_event: tk.Event) -> str | None:
        canvas.yview_scroll(3, "units")
        return "break"

    def _on_wheel(event: tk.Event) -> str | None:
        if getattr(event, "delta", 0):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            return "break"
        return None

    def _bind_recursive(w: tk.Misc) -> None:
        w.bind("<MouseWheel>", _on_wheel, add="+")
        w.bind("<Button-4>", _on_linux_up, add="+")
        w.bind("<Button-5>", _on_linux_down, add="+")
        try:
            children = w.winfo_children()
        except tk.TclError:
            return
        for child in children:
            _bind_recursive(child)

    _bind_recursive(widget)


def make_scrollable(parent: ttk.Frame) -> tuple[tk.Canvas, ttk.Frame]:
    """Create a full-tab scroll area; returns (canvas, inner_frame)."""
    wrap = ttk.Frame(parent)
    wrap.pack(fill=tk.BOTH, expand=True)

    canvas = tk.Canvas(wrap, bg=BG, highlightthickness=0, bd=0)
    scroll = ttk.Scrollbar(wrap, orient=tk.VERTICAL, command=canvas.yview)
    inner = ttk.Frame(canvas, style="TFrame")

    window_id = canvas.create_window((0, 0), window=inner, anchor="nw")

    def _on_inner_configure(_event: tk.Event | None = None) -> None:
        canvas.configure(scrollregion=canvas.bbox("all"))

    def _on_canvas_configure(event: tk.Event) -> None:
        canvas.itemconfigure(window_id, width=event.width)

    inner.bind("<Configure>", _on_inner_configure)
    canvas.bind("<Configure>", _on_canvas_configure)
    canvas.configure(yscrollcommand=scroll.set)

    canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scroll.pack(side=tk.RIGHT, fill=tk.Y)

    bind_mousewheel(canvas, canvas)
    return canvas, inner


def finish_scrollable(inner: ttk.Frame, canvas: tk.Canvas) -> None:
    """Call after filling `inner` so wheel works over every child widget."""
    bind_mousewheel(inner, canvas)
    canvas.configure(scrollregion=canvas.bbox("all"))
