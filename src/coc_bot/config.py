from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


@dataclass
class UnitInfo:
    unit_id: str
    category: str  # troop, spell, siege
    tier: str = "normal"  # normal, dark


@dataclass
class BotConfig:
    adb_device: str
    coc_package: str
    template_threshold: float
    donate_button_threshold: float
    scale_range: list[float]
    tap_jitter_px: int
    action_delay_ms: tuple[int, int]
    scan_interval_ms: tuple[int, int]
    session_limit_seconds: int
    break_min_seconds: int
    break_max_seconds: int
    game_load_timeout_seconds: int
    state_watchdog_seconds: int
    units: dict[str, UnitInfo]
    frame_width: int = 0
    frame_height: int = 0
    rois: dict[str, list[float]] = field(default_factory=dict)
    tap_points: dict[str, list[int]] = field(default_factory=dict)
    templates: dict[str, str] = field(default_factory=dict)
    unit_templates: dict[str, str] = field(default_factory=dict)
    colors: dict[str, list[int]] = field(default_factory=dict)
    grid: dict[str, Any] = field(default_factory=dict)
    donation_order: list[str] = field(default_factory=lambda: ["troop", "spell", "siege"])
    handled_request_ttl_seconds: int = 120
    chat_max_scroll_attempts: int = 20
    bar_max_scroll_attempts: int = 8
    donate_open_requests: bool = False
    donation_panel_wait_seconds: float = 3.0
    ocr_confidence_threshold: float = 0.5
    debug_save_frames: bool = False
    dry_run: bool = False
    data_dir: Path = field(default_factory=lambda: _project_root() / "data")
    templates_dir: Path = field(default_factory=lambda: _project_root() / "data" / "templates")

    @property
    def calibrated(self) -> bool:
        return self.frame_width > 0 and self.frame_height > 0 and bool(self.rois)


def _parse_units(raw: dict[str, Any]) -> dict[str, UnitInfo]:
    units: dict[str, UnitInfo] = {}
    for unit_id, info in raw.items():
        units[unit_id] = UnitInfo(
            unit_id=unit_id,
            category=info["category"],
            tier=info.get("tier", "normal"),
        )
    return units


def load_config(
    default_path: Path | None = None,
    calibrated_path: Path | None = None,
) -> BotConfig:
    root = _project_root()
    default_path = default_path or root / "config" / "default.yaml"
    calibrated_path = calibrated_path or Path(
        os.environ.get("COC_BOT_CONFIG", root / "data" / "calibrated.yaml")
    )

    with open(default_path, encoding="utf-8") as f:
        defaults = yaml.safe_load(f)

    calibrated: dict[str, Any] = {}
    if calibrated_path.exists():
        with open(calibrated_path, encoding="utf-8") as f:
            calibrated = yaml.safe_load(f) or {}

    merged = {**defaults, **calibrated}
    adb = merged.get("adb", {})
    vision = merged.get("vision", {})
    timing = merged.get("timing", {})
    runtime = merged.get("runtime", {})
    donation = merged.get("donation", {})

    return BotConfig(
        adb_device=os.environ.get("ADB_DEVICE", adb.get("device", "127.0.0.1:5555")),
        coc_package=adb.get("coc_package", "com.supercell.clashofclans"),
        template_threshold=vision.get("template_threshold", 0.82),
        donate_button_threshold=vision.get("donate_button_threshold", 0.78),
        scale_range=vision.get("scale_range", [0.95, 1.0, 1.05]),
        tap_jitter_px=timing.get("tap_jitter_px", 6),
        action_delay_ms=tuple(timing.get("action_delay_ms", [120, 350])),
        scan_interval_ms=tuple(timing.get("scan_interval_ms", [800, 1500])),
        session_limit_seconds=runtime.get("session_limit_seconds", 4 * 3600),
        break_min_seconds=runtime.get("break_min_seconds", 600),
        break_max_seconds=runtime.get("break_max_seconds", 900),
        game_load_timeout_seconds=runtime.get("game_load_timeout_seconds", 90),
        state_watchdog_seconds=runtime.get("state_watchdog_seconds", 45),
        units=_parse_units(merged.get("units", {})),
        frame_width=calibrated.get("frame_width", 0),
        frame_height=calibrated.get("frame_height", 0),
        rois=calibrated.get("rois", {}),
        tap_points=calibrated.get("tap_points", {}),
        templates=calibrated.get("templates", {}),
        unit_templates=calibrated.get("unit_templates", {}),
        colors=calibrated.get("colors", {}),
        grid=calibrated.get("grid", {}),
        donation_order=donation.get("order", ["troop", "spell", "siege"]),
        handled_request_ttl_seconds=donation.get("handled_request_ttl_seconds", 120),
        chat_max_scroll_attempts=donation.get("chat_max_scroll_attempts", 20),
        bar_max_scroll_attempts=donation.get("bar_max_scroll_attempts", 8),
        donate_open_requests=donation.get("donate_open_requests", False),
        donation_panel_wait_seconds=float(donation.get("donation_panel_wait_seconds", 3.0)),
        ocr_confidence_threshold=vision.get("ocr_confidence_threshold", 0.5),
        data_dir=root / "data",
        templates_dir=root / "data" / "templates",
    )


def save_calibrated(config: BotConfig, path: Path | None = None) -> None:
    root = _project_root()
    path = path or root / "data" / "calibrated.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "frame_width": config.frame_width,
        "frame_height": config.frame_height,
        "rois": config.rois,
        "tap_points": config.tap_points,
        "templates": config.templates,
        "unit_templates": config.unit_templates,
        "colors": config.colors,
        "grid": config.grid,
    }
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(payload, f, default_flow_style=False, sort_keys=False)
