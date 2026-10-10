"""Shared color palettes; no display dependencies."""
from dataclasses import dataclass

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


