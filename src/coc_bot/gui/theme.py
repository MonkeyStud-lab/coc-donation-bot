"""GUI themes: palettes + layout mode for the control window."""

from __future__ import annotations

import platform
import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk


from coc_bot.control.themes import (GuiTheme, THEMES, DEFAULT_THEME_ID, THEME_ORDER, theme_labels, normalize_theme_id, theme_id_from_label, theme_label)

# Active palette mirrors (updated by apply_theme). Imported modules should read
# these after apply_theme, or use `import coc_bot.gui.theme as theme` + theme.BG.
BG = THEMES[DEFAULT_THEME_ID].bg
SIDEBAR = THEMES[DEFAULT_THEME_ID].sidebar
SURFACE = THEMES[DEFAULT_THEME_ID].surface
SURFACE_2 = THEMES[DEFAULT_THEME_ID].surface_2
SURFACE_HOVER = THEMES[DEFAULT_THEME_ID].surface_hover
TEXT = THEMES[DEFAULT_THEME_ID].text
TEXT_SECONDARY = THEMES[DEFAULT_THEME_ID].text_secondary
BORDER = THEMES[DEFAULT_THEME_ID].border
ACCENT = THEMES[DEFAULT_THEME_ID].accent
ACCENT_PRESSED = THEMES[DEFAULT_THEME_ID].accent_pressed
ACCENT_FG = THEMES[DEFAULT_THEME_ID].accent_fg
PLAY = THEMES[DEFAULT_THEME_ID].play
PLAY_HOVER = THEMES[DEFAULT_THEME_ID].play_hover
PLAY_FG = THEMES[DEFAULT_THEME_ID].play_fg
DANGER = THEMES[DEFAULT_THEME_ID].danger
DANGER_HOVER = THEMES[DEFAULT_THEME_ID].danger_hover
SUCCESS = THEMES[DEFAULT_THEME_ID].success
LOG_BG = THEMES[DEFAULT_THEME_ID].log_bg
LOG_FG = THEMES[DEFAULT_THEME_ID].log_fg
STATUS_BAR = THEMES[DEFAULT_THEME_ID].status_bar
NAV_SELECTED = THEMES[DEFAULT_THEME_ID].nav_selected
FIELD_BG = THEMES[DEFAULT_THEME_ID].field_bg
FIELD_FOCUS = THEMES[DEFAULT_THEME_ID].field_focus

_ACTIVE_ID = DEFAULT_THEME_ID


def active_theme() -> GuiTheme:
    return THEMES[_ACTIVE_ID]


def active_layout() -> str:
    return active_theme().layout


def ui_font(size: int = 12, weight: str = "normal") -> tuple:
    system = platform.system()
    if system == "Darwin":
        family = "SF Pro Text"
    elif system == "Windows":
        family = "Segoe UI"
    else:
        family = "Ubuntu"
    return (family, size, weight) if weight != "normal" else (family, size)


def _publish_palette(t: GuiTheme) -> None:
    global BG, SIDEBAR, SURFACE, SURFACE_2, SURFACE_HOVER, TEXT, TEXT_SECONDARY
    global BORDER, ACCENT, ACCENT_PRESSED, ACCENT_FG, PLAY, PLAY_HOVER, PLAY_FG
    global DANGER, DANGER_HOVER, SUCCESS, LOG_BG, LOG_FG, STATUS_BAR, NAV_SELECTED
    global FIELD_BG, FIELD_FOCUS, _ACTIVE_ID
    _ACTIVE_ID = t.id
    BG = t.bg
    SIDEBAR = t.sidebar
    SURFACE = t.surface
    SURFACE_2 = t.surface_2
    SURFACE_HOVER = t.surface_hover
    TEXT = t.text
    TEXT_SECONDARY = t.text_secondary
    BORDER = t.border
    ACCENT = t.accent
    ACCENT_PRESSED = t.accent_pressed
    ACCENT_FG = t.accent_fg
    PLAY = t.play
    PLAY_HOVER = t.play_hover
    PLAY_FG = t.play_fg
    DANGER = t.danger
    DANGER_HOVER = t.danger_hover
    SUCCESS = t.success
    LOG_BG = t.log_bg
    LOG_FG = t.log_fg
    STATUS_BAR = t.status_bar
    NAV_SELECTED = t.nav_selected
    FIELD_BG = t.field_bg
    FIELD_FOCUS = t.field_focus


def apply_theme(root: tk.Tk | None = None, theme_id: str | None = None) -> ttk.Style:
    """Apply a theme palette to ttk styles (and optional root background)."""
    tid = normalize_theme_id(theme_id if theme_id is not None else _ACTIVE_ID)
    t = THEMES[tid]
    _publish_palette(t)

    if root is not None:
        root.configure(bg=t.bg)
        style = ttk.Style(root)
    else:
        style = ttk.Style()
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure(".", background=t.bg, foreground=t.text, font=ui_font(11))
    style.configure("TFrame", background=t.bg)
    style.configure("TNotebook", background=t.bg, borderwidth=0, tabmargins=(0, 0, 0, 12),
                    bordercolor=t.bg, lightcolor=t.bg, darkcolor=t.bg)
    style.configure("TNotebook.Tab", background=t.bg, foreground=t.text_secondary,
                    padding=(16, 10), borderwidth=0,
                    bordercolor=t.bg, lightcolor=t.bg, darkcolor=t.bg)
    style.map("TNotebook.Tab", background=[("selected", t.surface_2), ("active", t.surface_hover)],
              foreground=[("selected", t.accent), ("active", t.text)])
    style.layout("TNotebook.Tab", [("Notebook.tab", {"sticky": "nswe", "children": [
        ("Notebook.padding", {"side": "top", "sticky": "nswe", "children": [
            ("Notebook.label", {"side": "top", "sticky": ""})]})]})])
    style.configure("Sidebar.TFrame", background=t.sidebar)
    style.configure("Surface.TFrame", background=t.surface_2)
    style.configure("Card.TFrame", background=t.surface_2, relief="flat")
    style.configure("StatusBar.TFrame", background=t.status_bar)
    style.configure("TLabel", background=t.bg, foreground=t.text, font=ui_font(11))
    style.configure("Sidebar.TLabel", background=t.sidebar, foreground=t.text, font=ui_font(11))
    style.configure(
        "Brand.TLabel",
        background=t.sidebar,
        foreground=t.text,
        font=ui_font(14, "bold"),
    )
    style.configure(
        "BrandSub.TLabel",
        background=t.sidebar,
        foreground=t.text_secondary,
        font=ui_font(9),
    )
    style.configure("Surface.TLabel", background=t.surface_2, foreground=t.text, font=ui_font(11))
    style.configure("Title.TLabel", background=t.bg, foreground=t.text, font=ui_font(22, "bold"))
    style.configure("PageTitle.TLabel", background=t.bg, foreground=t.text, font=ui_font(20, "bold"))
    style.configure(
        "Subtitle.TLabel", background=t.bg, foreground=t.text_secondary, font=ui_font(11)
    )
    style.configure("Section.TLabel", background=t.bg, foreground=t.text, font=ui_font(13, "bold"))
    style.configure(
        "Caption.TLabel", background=t.surface_2, foreground=t.text_secondary, font=ui_font(10)
    )
    style.configure(
        "Status.TLabel", background=t.status_bar, foreground=t.text_secondary, font=ui_font(10)
    )
    style.configure(
        "StatusAccent.TLabel", background=t.status_bar, foreground=t.accent, font=ui_font(10)
    )

    style.configure(
        "Nav.TButton",
        background=t.sidebar,
        foreground=t.text_secondary,
        font=ui_font(11),
        padding=(16, 10),
        borderwidth=0,
        focuscolor=t.sidebar,
        anchor="w",
    )
    style.map(
        "Nav.TButton",
        background=[("active", t.surface), ("disabled", t.sidebar)],
        foreground=[("active", t.text), ("disabled", t.text_secondary)],
    )
    style.configure(
        "NavSelected.TButton",
        background=t.nav_selected,
        foreground=t.text,
        font=ui_font(11, "bold"),
        padding=(16, 10),
        borderwidth=0,
        focuscolor=t.nav_selected,
        anchor="w",
    )
    style.map(
        "NavSelected.TButton",
        background=[("active", t.surface_hover)],
        foreground=[("active", t.text)],
    )

    style.configure(
        "Play.TButton",
        background=t.play,
        foreground=t.play_fg,
        font=ui_font(12, "bold"),
        padding=(22, 10),
        borderwidth=0,
        focuscolor=t.play,
    )
    style.map(
        "Play.TButton",
        background=[("active", t.play_hover), ("disabled", t.surface_2)],
        foreground=[("disabled", t.text_secondary)],
    )
    # Home Stop — filled danger, same font/padding as Play so Start/Stop share size.
    style.configure(
        "HomeStop.TButton",
        background=t.danger,
        foreground="#ffffff",
        font=ui_font(12, "bold"),
        padding=(22, 10),
        borderwidth=0,
        focuscolor=t.danger,
    )
    style.map(
        "HomeStop.TButton",
        background=[("active", t.danger_hover), ("disabled", t.surface_2)],
        foreground=[("disabled", t.text_secondary)],
    )

    style.configure(
        "Accent.TButton",
        background=t.accent,
        foreground=t.accent_fg,
        font=ui_font(11, "bold"),
        padding=(16, 8),
        borderwidth=0,
        focuscolor=t.accent,
    )
    style.map(
        "Accent.TButton",
        background=[("active", t.accent_pressed), ("disabled", t.surface)],
        foreground=[("disabled", t.text_secondary)],
    )

    style.configure(
        "Secondary.TButton",
        background=t.surface,
        foreground=t.text,
        font=ui_font(11),
        padding=(14, 8),
        borderwidth=0,
    )
    style.map(
        "Secondary.TButton",
        background=[("active", t.surface_hover), ("disabled", t.surface_2)],
        foreground=[("disabled", t.text_secondary)],
    )

    style.configure(
        "Danger.TButton",
        background=t.surface,
        foreground=t.danger,
        font=ui_font(11),
        padding=(14, 8),
        borderwidth=0,
    )
    style.map(
        "Danger.TButton",
        background=[("active", t.danger_hover)],
        foreground=[("active", t.text)],
    )

    style.configure(
        "TEntry",
        fieldbackground=t.field_bg,
        foreground=t.text,
        insertcolor=t.text,
        padding=8,
        bordercolor=t.surface,
        lightcolor=t.surface,
        darkcolor=t.surface,
    )
    style.map(
        "TEntry",
        fieldbackground=[("focus", t.field_focus)],
        bordercolor=[("focus", t.accent)],
    )
    style.configure(
        "Modern.TEntry",
        fieldbackground=t.field_bg,
        foreground=t.text,
        insertcolor=t.text,
        padding=(10, 7),
        bordercolor=t.surface,
        lightcolor=t.surface,
        darkcolor=t.surface,
    )
    style.map(
        "Modern.TEntry",
        fieldbackground=[("focus", t.field_focus)],
        bordercolor=[("focus", t.accent)],
        lightcolor=[("focus", t.accent)],
        darkcolor=[("focus", t.accent)],
    )
    style.configure(
        "Modern.Accent.TButton",
        background=t.accent,
        foreground=t.accent_fg,
        font=ui_font(11, "bold"),
        padding=(18, 9),
        borderwidth=0,
        focuscolor=t.accent,
    )
    style.map(
        "Modern.Accent.TButton",
        background=[("active", t.accent_pressed), ("disabled", t.surface)],
        foreground=[("disabled", t.text_secondary)],
    )
    style.configure(
        "Modern.Secondary.TButton",
        background=t.surface,
        foreground=t.text,
        font=ui_font(11),
        padding=(16, 9),
        borderwidth=0,
    )
    style.map(
        "Modern.Secondary.TButton",
        background=[("active", t.surface_hover), ("disabled", t.surface_2)],
        foreground=[("disabled", t.text_secondary)],
    )
    style.configure(
        "Modern.Danger.TButton",
        background=t.surface,
        foreground=t.danger,
        font=ui_font(11),
        padding=(16, 9),
        borderwidth=0,
    )
    style.map(
        "Modern.Danger.TButton",
        background=[("active", t.danger_hover)],
        foreground=[("active", t.text)],
    )
    style.configure(
        "Modern.Play.TButton",
        background=t.play,
        foreground=t.play_fg,
        font=ui_font(12, "bold"),
        padding=(26, 11),
        borderwidth=0,
        focuscolor=t.play,
    )
    style.map(
        "Modern.Play.TButton",
        background=[("active", t.play_hover), ("disabled", t.surface_2)],
        foreground=[("disabled", t.text_secondary)],
    )
    style.configure(
        "Modern.HomeStop.TButton",
        background=t.danger,
        foreground="#ffffff",
        font=ui_font(12, "bold"),
        padding=(26, 11),
        borderwidth=0,
        focuscolor=t.danger,
    )
    style.map(
        "Modern.HomeStop.TButton",
        background=[("active", t.danger_hover), ("disabled", t.surface_2)],
        foreground=[("disabled", t.text_secondary)],
    )
    style.configure(
        "TCombobox",
        fieldbackground=t.field_bg,
        background=t.surface,
        foreground=t.text,
        arrowcolor=t.text_secondary,
        padding=6,
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", t.field_bg), ("focus", t.field_focus)],
        foreground=[("readonly", t.text)],
        selectbackground=[("readonly", t.surface)],
        selectforeground=[("readonly", t.accent)],
    )
    style.configure(
        "Modern.TCombobox",
        fieldbackground=t.field_bg,
        background=t.surface,
        foreground=t.text,
        arrowcolor=t.text_secondary,
        padding=(10, 6),
    )
    style.map(
        "Modern.TCombobox",
        fieldbackground=[("readonly", t.field_bg), ("focus", t.field_focus)],
        foreground=[("readonly", t.text)],
        selectbackground=[("readonly", t.surface)],
        selectforeground=[("readonly", t.accent)],
    )
    style.configure(
        "TCheckbutton",
        background=t.surface_2,
        foreground=t.text,
        font=ui_font(11),
        focuscolor=t.bg,
    )
    style.map(
        "TCheckbutton",
        background=[("active", t.surface_2)],
        foreground=[("active", t.text)],
    )
    style.configure(
        "Treeview",
        background=t.surface_2,
        fieldbackground=t.surface_2,
        foreground=t.text,
        rowheight=28,
        font=ui_font(11),
        bordercolor=t.surface,
    )
    style.configure(
        "Treeview.Heading",
        background=t.surface,
        foreground=t.text_secondary,
        font=ui_font(10, "bold"),
        relief="flat",
    )
    style.map(
        "Treeview",
        background=[("selected", t.surface)],
        foreground=[("selected", t.accent)],
    )
    style.configure(
        "TScrollbar",
        background=t.surface,
        troughcolor=t.surface_2,
        bordercolor=t.surface_2,
        lightcolor=t.surface_2,
        darkcolor=t.surface_2,
        arrowcolor=t.text_secondary,
        arrowsize=12,
    )
    style.map("TScrollbar", background=[("active", t.surface_hover)])
    return style


def bind_yview_mousewheel(widget: tk.Misc) -> None:
    """Scroll ``widget`` with the mouse wheel (Treeview / Text / Listbox)."""

    def _on_linux_up(_event: tk.Event) -> str | None:
        widget.yview_scroll(-3, "units")  # type: ignore[attr-defined]
        return "break"

    def _on_linux_down(_event: tk.Event) -> str | None:
        widget.yview_scroll(3, "units")  # type: ignore[attr-defined]
        return "break"

    def _on_wheel(event: tk.Event) -> str | None:
        delta = getattr(event, "delta", 0)
        if delta:
            # Windows uses multiples of 120; some X11 Tk builds use smaller deltas.
            steps = int(-1 * (delta / 120)) if abs(delta) >= 120 else (-1 if delta > 0 else 1)
            widget.yview_scroll(steps, "units")  # type: ignore[attr-defined]
            return "break"
        return None

    widget.bind("<MouseWheel>", _on_wheel, add="+")
    widget.bind("<Button-4>", _on_linux_up, add="+")
    widget.bind("<Button-5>", _on_linux_down, add="+")


def bind_mousewheel(widget: tk.Misc, canvas: tk.Canvas) -> None:
    """Scroll `canvas` for wheel events on `widget` and its descendants.

    Nested scrollables (``ttk.Treeview``, ``tk.Text``, ``tk.Listbox``) scroll
    themselves instead of the outer canvas — otherwise the checklist never moves.
    """

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

    def _is_self_scrolling(w: tk.Misc) -> bool:
        return isinstance(w, (ttk.Treeview, tk.Text, tk.Listbox))

    def _bind_recursive(w: tk.Misc) -> None:
        if _is_self_scrolling(w):
            bind_yview_mousewheel(w)
            return
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
