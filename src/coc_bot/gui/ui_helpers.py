"""Small typed helpers for GUI labels, hints, and window state."""

from __future__ import annotations

import json
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


def load_window_geometry(path: Path) -> str | None:
    """Load saved window geometry from JSON, or ``None`` on any error."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    geometry = data.get("geometry")
    return geometry if isinstance(geometry, str) and geometry else None


def save_window_geometry(path: Path, geometry: str) -> None:
    """Persist window geometry as JSON ``{"geometry": "WxH+X+Y"}``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"geometry": geometry}, indent=2) + "\n",
        encoding="utf-8",
    )


def adb_status_label(ok: bool | None) -> tuple[str, ColorRole]:
    """Return ``(label, color_role)`` for the ADB connection indicator."""
    if ok is True:
        return "ADB · connected", "ok"
    if ok is False:
        return "ADB · offline", "bad"
    return "ADB · …", "unknown"
