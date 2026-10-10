"""Named timing presets for non-dev users."""

from __future__ import annotations

from typing import Any, Literal

TimingPresetId = Literal["safe", "balanced", "fast", "custom"]

PRESET_LABELS: tuple[str, ...] = ("Safe", "Balanced", "Fast", "Custom")

# Values applied when a named preset is selected (not Custom).
TIMING_PRESETS: dict[str, dict[str, Any]] = {
    "safe": {
        "scan_interval_ms": [1200, 2000],
        "action_delay_ms": [180, 400],
        "tap_jitter_px": 8,
        "anti_idle_seconds": 50,
    },
    "balanced": {
        "scan_interval_ms": [800, 1500],
        "action_delay_ms": [120, 350],
        "tap_jitter_px": 6,
        "anti_idle_seconds": 60,
    },
    "fast": {
        "scan_interval_ms": [500, 900],
        "action_delay_ms": [60, 150],
        "tap_jitter_px": 4,
        "anti_idle_seconds": 70,
    },
}

# Settings field keys that are hidden unless Dev options is on.
RAW_TIMING_FIELD_KEYS: frozenset[str] = frozenset(
    {
        "scan_interval_ms",
        "action_delay_ms",
        "tap_jitter_px",
        "anti_idle_seconds",
    }
)


def normalize_timing_preset(raw: object) -> TimingPresetId:
    text = str(raw or "balanced").strip().lower()
    if text in TIMING_PRESETS or text == "custom":
        return text  # type: ignore[return-value]
    aliases = {
        "safe": "safe",
        "balanced": "balanced",
        "fast": "fast",
        "custom": "custom",
    }
    for label in PRESET_LABELS:
        aliases[label.lower()] = label.lower()  # type: ignore[assignment]
    return aliases.get(text, "balanced")  # type: ignore[return-value]


def timing_preset_label(preset_id: str) -> str:
    pid = normalize_timing_preset(preset_id)
    for label in PRESET_LABELS:
        if label.lower() == pid:
            return label
    return "Balanced"


def timing_preset_id_from_label(label: str) -> TimingPresetId:
    return normalize_timing_preset(label)


def apply_timing_preset(preset_id: str) -> dict[str, Any]:
    """Return a ``timing`` section dict for ``user_settings.yaml``."""
    pid = normalize_timing_preset(preset_id)
    if pid == "custom" or pid not in TIMING_PRESETS:
        return {}
    return dict(TIMING_PRESETS[pid])


def infer_preset_from_timing(
    scan_interval_ms: tuple[int, int] | list[int],
    action_delay_ms: tuple[int, int] | list[int],
    tap_jitter_px: int,
    anti_idle_seconds: int,
) -> TimingPresetId:
    """Match current timing values to a named preset, else ``custom``."""
    scan = [int(scan_interval_ms[0]), int(scan_interval_ms[1])]
    action = [int(action_delay_ms[0]), int(action_delay_ms[1])]
    for pid, values in TIMING_PRESETS.items():
        if (
            list(values["scan_interval_ms"]) == scan
            and list(values["action_delay_ms"]) == action
            and int(values["tap_jitter_px"]) == int(tap_jitter_px)
            and int(values["anti_idle_seconds"]) == int(anti_idle_seconds)
        ):
            return pid  # type: ignore[return-value]
    return "custom"
