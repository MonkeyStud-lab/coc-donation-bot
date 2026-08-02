"""Small typed helpers for GUI labels, hints, and window state."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

ColorRole = Literal["ok", "bad", "unknown"]

_SECONDS_KEYS = ("anti_idle_seconds",)


def _parse_seconds(raw: Any) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        value = float(raw)
    elif isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        try:
            value = float(text)
        except ValueError:
            return None
    else:
        return None
    if value < 0:
        return None
    return value


def humanize_seconds(raw: Any) -> str | None:
    """Parse seconds and return a compact hint like ``≈ 4h`` / ``≈ 12m`` / ``≈ 45s``."""
    value = _parse_seconds(raw)
    if value is None:
        return None
    total = int(value)
    if total >= 86_400:
        return f"≈ {total // 86_400}d"
    if total >= 3_600:
        return f"≈ {total // 3_600}h"
    if total >= 60:
        return f"≈ {total // 60}m"
    return f"≈ {total}s"


def humanize_setting_value(field_key: str, raw: Any) -> str | None:
    """Return a human hint for timing-related settings fields, or ``None``."""
    if field_key.endswith("_seconds") or field_key in _SECONDS_KEYS:
        return humanize_seconds(raw)
    if field_key.endswith("_ms"):
        if isinstance(raw, str) and "," in raw:
            return None
        ms = _parse_seconds(raw)
        if ms is None:
            return None
        total_ms = int(ms)
        if total_ms < 1000:
            return f"≈ {total_ms}ms"
        return humanize_seconds(total_ms / 1000.0)
    return None


def format_countdown(seconds: float) -> str:
    """Compact countdown like ``2h 15m`` / ``12m 5s`` / ``40s``."""
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


@dataclass
class GuiWindowState:
    """Persisted control-window chrome (geometry, last page, onboarding)."""

    geometry: str | None = None
    last_page: str = "home"
    onboarding_dismissed: bool = False
    # Dev: Home Get-started card is forced visible (does not wipe calibration).
    first_launch_preview: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GuiWindowState:
        geom = data.get("geometry")
        if not isinstance(geom, str) or not geom:
            geom = None
        page = str(data.get("last_page") or "home").strip().lower()
        if page not in ("home", "settings", "setup", "tools"):
            page = "home"
        return cls(
            geometry=geom,
            last_page=page,
            onboarding_dismissed=bool(data.get("onboarding_dismissed", False)),
            first_launch_preview=bool(data.get("first_launch_preview", False)),
        )


def load_gui_window_state(path: Path) -> GuiWindowState:
    """Load saved GUI window state from JSON."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return GuiWindowState()
    if not isinstance(data, dict):
        return GuiWindowState()
    return GuiWindowState.from_dict(data)


def save_gui_window_state(path: Path, state: GuiWindowState) -> None:
    """Persist GUI window state as JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(state)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def load_window_geometry(path: Path) -> str | None:
    """Load saved window geometry from JSON, or ``None`` on any error."""
    return load_gui_window_state(path).geometry


def save_window_geometry(path: Path, geometry: str) -> None:
    """Persist window geometry, preserving other GUI window state fields."""
    state = load_gui_window_state(path)
    state.geometry = geometry
    save_gui_window_state(path, state)


def adb_status_label(ok: bool | None) -> tuple[str, ColorRole]:
    """Return ``(label, color_role)`` for the ADB connection indicator."""
    if ok is True:
        return "ADB · connected", "ok"
    if ok is False:
        return "ADB · offline", "bad"
    return "ADB · …", "unknown"
