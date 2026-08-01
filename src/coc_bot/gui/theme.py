"""GUI themes: palettes + layout mode for the control window."""

from __future__ import annotations

import platform
import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk


@dataclass(frozen=True)
class GuiTheme:
    """One selectable look for the control app."""

    id: str
    label: str
    layout: str  # "classic" (stacked cards) | "modern" (row + toggles)
    bg: str
    sidebar: str
    surface: str
    surface_2: str
    surface_hover: str
    text: str
    text_secondary: str
    border: str
    accent: str
    accent_pressed: str
    accent_fg: str
    play: str
    play_hover: str
    play_fg: str
    danger: str
    danger_hover: str
    success: str
    log_bg: str
    log_fg: str
    status_bar: str
    nav_selected: str
    field_bg: str
    field_focus: str


# --- Theme catalog -----------------------------------------------------------------

THEMES: dict[str, GuiTheme] = {
    "classic": GuiTheme(
        id="classic",
        label="Classic",
        layout="classic",
        bg="#1b2838",
        sidebar="#171a21",
        surface="#2a475e",
        surface_2="#1e2329",
        surface_hover="#3d5a73",
        text="#c7d5e0",
        text_secondary="#8f98a0",
        border="#000000",
        accent="#66c0f4",
        accent_pressed="#4aa0d5",
        accent_fg="#1b2838",
        play="#5c7e10",
        play_hover="#6b8f12",
        play_fg="#beee11",
        danger="#c45c5c",
        danger_hover="#a84848",
        success="#5ba32b",
        log_bg="#0e1419",
        log_fg="#c7d5e0",
        status_bar="#171a21",
        nav_selected="#2a475e",
        field_bg="#1e2329",
        field_focus="#16202d",
    ),
    "modern": GuiTheme(
        id="modern",
        label="Modern",
        layout="modern",
        bg="#1b2838",
        sidebar="#171a21",
        surface="#2a475e",
        surface_2="#1e2329",
        surface_hover="#3d5a73",
        text="#c7d5e0",
        text_secondary="#8f98a0",
        border="#000000",
        accent="#66c0f4",
        accent_pressed="#4aa0d5",
        accent_fg="#1b2838",
        play="#5c7e10",
        play_hover="#6b8f12",
        play_fg="#beee11",
        danger="#c45c5c",
        danger_hover="#a84848",
        success="#5ba32b",
        log_bg="#0e1419",
        log_fg="#c7d5e0",
        status_bar="#171a21",
        nav_selected="#2a475e",
        field_bg="#16202d",
        field_focus="#121a24",
    ),
    "windows11": GuiTheme(
        id="windows11",
        label="Graphite",
        layout="modern",
        bg="#202020",
        sidebar="#2c2c2c",
        surface="#373737",
        surface_2="#2b2b2b",
        surface_hover="#3e3e3e",
        text="#ffffff",
        text_secondary="#c5c5c5",
        border="#1a1a1a",
        accent="#60cdff",
        accent_pressed="#4bb4e6",
        accent_fg="#001a26",
        play="#6ccb5f",
        play_hover="#5db852",
        play_fg="#0a1f0a",
        danger="#ff99a4",
        danger_hover="#e87a86",
        success="#6ccb5f",
        log_bg="#1a1a1a",
        log_fg="#e6e6e6",
        status_bar="#1f1f1f",
        nav_selected="#3d3d3d",
        field_bg="#1f1f1f",
        field_focus="#171717",
    ),
    "ios26": GuiTheme(
        id="ios26",
        label="Midnight",
        layout="modern",
        bg="#000000",
        sidebar="#0a0a0a",
        surface="#2c2c2e",
        surface_2="#1c1c1e",
        surface_hover="#3a3a3c",
        text="#f5f5f7",
        text_secondary="#8e8e93",
        border="#000000",
        accent="#0a84ff",
        accent_pressed="#0066d6",
        accent_fg="#ffffff",
        play="#30d158",
        play_hover="#28b84c",
        play_fg="#003214",
        danger="#ff453a",
        danger_hover="#d63a31",
        success="#30d158",
        log_bg="#0c0c0e",
        log_fg="#e5e5ea",
        status_bar="#0a0a0a",
        nav_selected="#2c2c2e",
        field_bg="#2c2c2e",
        field_focus="#3a3a3c",
    ),
    "android17": GuiTheme(
        id="android17",
        label="Amethyst",
        layout="modern",
        bg="#131313",
        sidebar="#0e0e0e",
        surface="#2b2930",
        surface_2="#1d1b20",
        surface_hover="#36343b",
        text="#e6e1e5",
        text_secondary="#cac4d0",
        border="#0e0e0e",
        accent="#d0bcff",
        accent_pressed="#b69df8",
        accent_fg="#381e72",
        play="#4ade80",
        play_hover="#34c76a",
        play_fg="#052e16",
        danger="#f2b8b5",
        danger_hover="#e09a96",
        success="#4ade80",
        log_bg="#0a0a0a",
        log_fg="#e6e1e5",
        status_bar="#0e0e0e",
        nav_selected="#2b2930",
        field_bg="#211f26",
        field_focus="#2b2930",
    ),
    "nord": GuiTheme(
        id="nord",
        label="Frost",
        layout="modern",
        bg="#2e3440",
        sidebar="#3b4252",
        surface="#434c5e",
        surface_2="#3b4252",
        surface_hover="#4c566a",
        text="#eceff4",
        text_secondary="#d8dee9",
        border="#2e3440",
        accent="#88c0d0",
        accent_pressed="#81a1c1",
        accent_fg="#2e3440",
        play="#a3be8c",
        play_hover="#8faf74",
        play_fg="#2e3440",
        danger="#bf616a",
        danger_hover="#a54e57",
        success="#a3be8c",
        log_bg="#242933",
        log_fg="#eceff4",
        status_bar="#3b4252",
        nav_selected="#434c5e",
        field_bg="#2e3440",
        field_focus="#242933",
    ),
    "ember": GuiTheme(
        id="ember",
        label="Ember",
        layout="modern",
        bg="#1a1410",
        sidebar="#120e0b",
        surface="#3a2a1f",
        surface_2="#241c16",
        surface_hover="#4a3728",
        text="#f3e9dc",
        text_secondary="#b9a894",
        border="#0d0a08",
        accent="#f0a04b",
        accent_pressed="#d4893a",
        accent_fg="#1a1410",
        play="#c4d65a",
        play_hover="#a8ba45",
        play_fg="#1a1410",
        danger="#e07a5f",
        danger_hover="#c4634c",
        success="#81b29a",
        log_bg="#100c09",
        log_fg="#f3e9dc",
        status_bar="#120e0b",
        nav_selected="#3a2a1f",
        field_bg="#1f1813",
        field_focus="#16110d",
    ),
}

DEFAULT_THEME_ID = "modern"
THEME_ORDER = (
    "classic",
    "modern",
    "windows11",
    "ios26",
    "android17",
    "nord",
    "ember",
)

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


def theme_labels() -> tuple[str, ...]:
    """Human labels for the theme dropdown (stable order)."""
    return tuple(THEMES[tid].label for tid in THEME_ORDER)


def normalize_theme_id(raw: object) -> str:
    """Map saved values / labels / legacy ui_style names to a theme id."""
    text = str(raw or DEFAULT_THEME_ID).strip().lower()
    aliases = {
        "classic": "classic",
        "legacy": "classic",
        "old": "classic",
        "modern": "modern",
        "cursor": "modern",
        "windows11": "windows11",
        "windows 11": "windows11",
        "win11": "windows11",
        "graphite": "windows11",
        "ios26": "ios26",
        "ios 26": "ios26",
        "ios": "ios26",
        "midnight": "ios26",
        "android17": "android17",
        "android 17": "android17",
        "android": "android17",
        "amethyst": "android17",
        "nord": "nord",
        "frost": "nord",
        "ember": "ember",
    }
    # Match by current label too ("Graphite", "Midnight", …).
    for tid in THEME_ORDER:
        label = THEMES[tid].label.lower()
        aliases[label] = tid
    return aliases.get(text, DEFAULT_THEME_ID if text not in THEMES else text)


def theme_id_from_label(label: str) -> str:
    return normalize_theme_id(label)


def theme_label(theme_id: str) -> str:
    tid = normalize_theme_id(theme_id)
    return THEMES[tid].label


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
    # Home Stop — same font/padding as Play so Start/Stop share size.
    style.configure(
        "HomeStop.TButton",
        background=t.surface,
        foreground=t.text,
        font=ui_font(12, "bold"),
        padding=(22, 10),
        borderwidth=0,
        focuscolor=t.surface,
    )
    style.map(
        "HomeStop.TButton",
        background=[("active", t.surface_hover), ("disabled", t.surface_2)],
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
        background=t.surface,
        foreground=t.text,
        font=ui_font(12, "bold"),
        padding=(26, 11),
        borderwidth=0,
        focuscolor=t.surface,
    )
    style.map(
        "Modern.HomeStop.TButton",
        background=[("active", t.surface_hover), ("disabled", t.surface_2)],
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
        arrowcolor=t.text_secondary,
        arrowsize=12,
    )
    style.map("TScrollbar", background=[("active", t.surface_hover)])
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
