"""Steam-inspired dark theme helpers for the control GUI."""

from __future__ import annotations

import platform
import tkinter as tk
from tkinter import ttk


# Steam-adjacent dark library palette.
BG = "#1b2838"
SIDEBAR = "#171a21"
SURFACE = "#2a475e"
SURFACE_2 = "#1e2329"
SURFACE_HOVER = "#3d5a73"
TEXT = "#c7d5e0"
TEXT_SECONDARY = "#8f98a0"
BORDER = "#000000"
ACCENT = "#66c0f4"
ACCENT_PRESSED = "#4aa0d5"
PLAY = "#5c7e10"
PLAY_HOVER = "#6b8f12"
PLAY_FG = "#beee11"
DANGER = "#c45c5c"
DANGER_HOVER = "#a84848"
SUCCESS = "#5ba32b"
LOG_BG = "#0e1419"
LOG_FG = "#c7d5e0"
STATUS_BAR = "#171a21"
NAV_SELECTED = "#2a475e"


def ui_font(size: int = 12, weight: str = "normal") -> tuple:
    system = platform.system()
    if system == "Darwin":
        family = "SF Pro Text"
    elif system == "Windows":
        family = "Segoe UI"
    else:
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
    style.configure("Sidebar.TFrame", background=SIDEBAR)
    style.configure("Surface.TFrame", background=SURFACE_2)
    style.configure("Card.TFrame", background=SURFACE_2, relief="flat")
    style.configure("StatusBar.TFrame", background=STATUS_BAR)
    style.configure("TLabel", background=BG, foreground=TEXT, font=ui_font(11))
    style.configure("Sidebar.TLabel", background=SIDEBAR, foreground=TEXT, font=ui_font(11))
    style.configure(
        "Brand.TLabel",
        background=SIDEBAR,
        foreground=TEXT,
        font=ui_font(14, "bold"),
    )
    style.configure(
        "BrandSub.TLabel",
        background=SIDEBAR,
        foreground=TEXT_SECONDARY,
        font=ui_font(9),
    )
    style.configure("Surface.TLabel", background=SURFACE_2, foreground=TEXT, font=ui_font(11))
    style.configure("Title.TLabel", background=BG, foreground=TEXT, font=ui_font(22, "bold"))
    style.configure("PageTitle.TLabel", background=BG, foreground=TEXT, font=ui_font(20, "bold"))
    style.configure(
        "Subtitle.TLabel", background=BG, foreground=TEXT_SECONDARY, font=ui_font(11)
    )
    style.configure("Section.TLabel", background=BG, foreground=TEXT, font=ui_font(13, "bold"))
    style.configure(
        "Caption.TLabel", background=SURFACE_2, foreground=TEXT_SECONDARY, font=ui_font(10)
    )
    style.configure(
        "Status.TLabel", background=STATUS_BAR, foreground=TEXT_SECONDARY, font=ui_font(10)
    )
    style.configure(
        "StatusAccent.TLabel", background=STATUS_BAR, foreground=ACCENT, font=ui_font(10)
    )

    style.configure(
        "Nav.TButton",
        background=SIDEBAR,
        foreground=TEXT_SECONDARY,
        font=ui_font(11),
        padding=(16, 10),
        borderwidth=0,
        focuscolor=SIDEBAR,
        anchor="w",
    )
    style.map(
        "Nav.TButton",
        background=[("active", SURFACE), ("disabled", SIDEBAR)],
        foreground=[("active", TEXT), ("disabled", TEXT_SECONDARY)],
    )
    style.configure(
        "NavSelected.TButton",
        background=NAV_SELECTED,
        foreground=TEXT,
        font=ui_font(11, "bold"),
        padding=(16, 10),
        borderwidth=0,
        focuscolor=NAV_SELECTED,
        anchor="w",
    )
    style.map(
        "NavSelected.TButton",
        background=[("active", SURFACE_HOVER)],
        foreground=[("active", TEXT)],
    )

    style.configure(
        "Play.TButton",
        background=PLAY,
        foreground=PLAY_FG,
        font=ui_font(12, "bold"),
        padding=(22, 10),
        borderwidth=0,
        focuscolor=PLAY,
    )
    style.map(
        "Play.TButton",
        background=[("active", PLAY_HOVER), ("disabled", "#3a4a20")],
        foreground=[("disabled", "#7a8a40")],
    )

    style.configure(
        "Accent.TButton",
        background=ACCENT,
        foreground="#1b2838",
        font=ui_font(11, "bold"),
        padding=(16, 8),
        borderwidth=0,
        focuscolor=ACCENT,
    )
    style.map(
        "Accent.TButton",
        background=[("active", ACCENT_PRESSED), ("disabled", "#3a5a70")],
        foreground=[("disabled", "#8f98a0")],
    )

    style.configure(
        "Secondary.TButton",
        background=SURFACE,
        foreground=TEXT,
        font=ui_font(11),
        padding=(14, 8),
        borderwidth=0,
    )
    style.map(
        "Secondary.TButton",
        background=[("active", SURFACE_HOVER), ("disabled", SURFACE_2)],
        foreground=[("disabled", TEXT_SECONDARY)],
    )

    style.configure(
        "Danger.TButton",
        background=SURFACE,
        foreground=DANGER,
        font=ui_font(11),
        padding=(14, 8),
        borderwidth=0,
    )
    style.map(
        "Danger.TButton",
        background=[("active", DANGER_HOVER)],
        foreground=[("active", TEXT)],
    )

    style.configure(
        "TEntry",
        fieldbackground=SURFACE_2,
        foreground=TEXT,
        insertcolor=TEXT,
        padding=8,
        bordercolor=SURFACE,
        lightcolor=SURFACE,
        darkcolor=SURFACE,
    )
    style.map(
        "TEntry",
        fieldbackground=[("focus", "#16202d")],
        bordercolor=[("focus", ACCENT)],
    )
    # Cursor-like compact controls (same palette, tighter geometry).
    style.configure(
        "Modern.TEntry",
        fieldbackground="#16202d",
        foreground=TEXT,
        insertcolor=TEXT,
        padding=(10, 7),
        bordercolor=SURFACE,
        lightcolor=SURFACE,
        darkcolor=SURFACE,
    )
    style.map(
        "Modern.TEntry",
        fieldbackground=[("focus", "#121a24")],
        bordercolor=[("focus", ACCENT)],
        lightcolor=[("focus", ACCENT)],
        darkcolor=[("focus", ACCENT)],
    )
    style.configure(
        "Modern.Accent.TButton",
        background=ACCENT,
        foreground="#1b2838",
        font=ui_font(11, "bold"),
        padding=(18, 9),
        borderwidth=0,
        focuscolor=ACCENT,
    )
    style.map(
        "Modern.Accent.TButton",
        background=[("active", ACCENT_PRESSED), ("disabled", "#3a5a70")],
        foreground=[("disabled", "#8f98a0")],
    )
    style.configure(
        "Modern.Secondary.TButton",
        background=SURFACE,
        foreground=TEXT,
        font=ui_font(11),
        padding=(16, 9),
        borderwidth=0,
    )
    style.map(
        "Modern.Secondary.TButton",
        background=[("active", SURFACE_HOVER), ("disabled", SURFACE_2)],
        foreground=[("disabled", TEXT_SECONDARY)],
    )
    style.configure(
        "Modern.Danger.TButton",
        background=SURFACE,
        foreground=DANGER,
        font=ui_font(11),
        padding=(16, 9),
        borderwidth=0,
    )
    style.map(
        "Modern.Danger.TButton",
        background=[("active", DANGER_HOVER)],
        foreground=[("active", TEXT)],
    )
    style.configure(
        "Modern.Play.TButton",
        background=PLAY,
        foreground=PLAY_FG,
        font=ui_font(12, "bold"),
        padding=(26, 11),
        borderwidth=0,
        focuscolor=PLAY,
    )
    style.map(
        "Modern.Play.TButton",
        background=[("active", PLAY_HOVER), ("disabled", "#3a4a20")],
        foreground=[("disabled", "#7a8a40")],
    )
    style.configure(
        "TCheckbutton",
        background=SURFACE_2,
        foreground=TEXT,
        font=ui_font(11),
        focuscolor=BG,
    )
    style.map(
        "TCheckbutton",
        background=[("active", SURFACE_2)],
        foreground=[("active", TEXT)],
    )
    style.configure(
        "Treeview",
        background=SURFACE_2,
        fieldbackground=SURFACE_2,
        foreground=TEXT,
        rowheight=28,
        font=ui_font(11),
        bordercolor=SURFACE,
    )
    style.configure(
        "Treeview.Heading",
        background=SURFACE,
        foreground=TEXT_SECONDARY,
        font=ui_font(10, "bold"),
        relief="flat",
    )
    style.map(
        "Treeview",
        background=[("selected", SURFACE)],
        foreground=[("selected", ACCENT)],
    )
    style.configure(
        "TScrollbar",
        background=SURFACE,
        troughcolor=SURFACE_2,
        bordercolor=SURFACE_2,
        arrowcolor=TEXT_SECONDARY,
        arrowsize=12,
    )
    style.map("TScrollbar", background=[("active", SURFACE_HOVER)])
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
