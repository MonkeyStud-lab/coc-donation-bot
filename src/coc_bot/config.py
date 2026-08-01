from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


def project_root() -> Path:
    """Repo root (contains ``scripts/``, ``config/``, ``data/``)."""
    return Path(__file__).resolve().parents[2]


# Back-compat alias used throughout the package.
_project_root = project_root


@dataclass(frozen=True)
class DonationLimits:
    troop_housing: int
    spell_housing: int
    siege_count: int


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
    anti_idle_seconds: int
    session_limit_seconds: int
    break_min_seconds: int
    break_max_seconds: int
    game_load_timeout_seconds: int
    state_watchdog_seconds: int
    frame_width: int = 0
    frame_height: int = 0
    rois: dict[str, list[float]] = field(default_factory=dict)
    tap_points: dict[str, list[int]] = field(default_factory=dict)
    templates: dict[str, str] = field(default_factory=dict)
    colors: dict[str, list[int]] = field(default_factory=dict)
    grid: dict[str, Any] = field(default_factory=dict)
    donation_order: list[str] = field(default_factory=lambda: ["troop", "spell", "siege"])
    handled_request_ttl_seconds: int = 120
    chat_max_scroll_attempts: int = 20
    bar_max_scroll_attempts: int = 5
    spell_bar_max_scroll_attempts: int = 2
    donate_open_requests: bool = True
    parse_request_capacity: bool = False
    donation_panel_wait_seconds: float = 3.0
    clan_level: int = 8
    clan_donation_limits: dict[int, DonationLimits] = field(default_factory=dict)
    ocr_confidence_threshold: float = 0.5
    debug_save_frames: bool = False
    dry_run: bool = False
    farm_enabled: bool = False
    farm_interval_seconds: int = 3600
    farm_interval_variance_seconds: int = 300
    farm_deploy_side: str = "left"
    farm_pan_swipes: float = 3.0
    farm_deploy_jitter_px: int = 6
    farm_match_timeout_seconds: int = 120
    farm_battle_timeout_seconds: int = 210
    farm_retry_cooldown_seconds: int = 300
    farm_edrag_deploy_taps: int = 14
    farm_hero_count: int = 4
    farm_deploy_siege: bool = True
    farm_activate_hero_abilities: bool = True
    farm_deploy_rage: bool = True
    farm_rage_count: int = 5
    farm_rage_inward_frac: float = 0.22
    # Ordered army+map taps after pan; when taps non-empty, overrides built-in recipe.
    farm_deploy_sequence: dict[str, Any] = field(default_factory=dict)
    gui_show_debug_activity: bool = False
    gui_ui_style: str = "modern"  # modern | classic
    data_dir: Path = field(default_factory=lambda: _project_root() / "data")
    templates_dir: Path = field(default_factory=lambda: _project_root() / "data" / "templates")

    @property
    def calibrated(self) -> bool:
        return self.frame_width > 0 and self.frame_height > 0 and bool(self.rois)

    @property
    def farm_calibrated(self) -> bool:
        """Minimum taps needed to run an unranked farm attack."""
        taps = self.tap_points
        return bool(
            taps.get("attack_button")
            and taps.get("unranked_battle")
            and taps.get("return_home")
        )

    def donor_limits(self) -> DonationLimits:
        """Max troops/spells/siege this account can donate per action at current clan level."""
        level = self.clan_level
        if level in self.clan_donation_limits:
            return self.clan_donation_limits[level]
        # Levels 11+ share level 10 perks
        if level > 10 and 10 in self.clan_donation_limits:
            return self.clan_donation_limits[10]
        # Fallback: lowest tier
        if self.clan_donation_limits:
            return self.clan_donation_limits[min(self.clan_donation_limits)]
        return DonationLimits(troop_housing=6, spell_housing=1, siege_count=1)


def _load_clan_perks(root: Path) -> dict[int, DonationLimits]:
    path = root / "config" / "clan_perks.yaml"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    limits: dict[int, DonationLimits] = {}
    for level_str, values in raw.get("limits_by_level", {}).items():
        limits[int(level_str)] = DonationLimits(
            troop_housing=int(values["troop_housing"]),
            spell_housing=int(values["spell_housing"]),
            siege_count=int(values["siege_count"]),
        )
    return limits


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def user_settings_path(root: Path | None = None) -> Path:
    root = root or _project_root()
    return root / "data" / "user_settings.yaml"


def load_user_settings(path: Path | None = None) -> dict[str, Any]:
    path = path or user_settings_path()
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data if isinstance(data, dict) else {}


def save_user_settings(payload: dict[str, Any], path: Path | None = None) -> Path:
    path = path or user_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(payload, f, default_flow_style=False, sort_keys=False)
    return path


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
        defaults = yaml.safe_load(f) or {}

    calibrated: dict[str, Any] = {}
    if calibrated_path.exists():
        with open(calibrated_path, encoding="utf-8") as f:
            calibrated = yaml.safe_load(f) or {}

    merged: dict[str, Any] = dict(defaults)
    _deep_merge(merged, load_user_settings(user_settings_path(root)))
    for key in (
        "frame_width",
        "frame_height",
        "rois",
        "tap_points",
        "templates",
        "colors",
        "grid",
        "farm_deploy_sequence",
    ):
        if key in calibrated:
            merged[key] = calibrated[key]

    adb = merged.get("adb", {})
    vision = merged.get("vision", {})
    timing = merged.get("timing", {})
    runtime = merged.get("runtime", {})
    donation = merged.get("donation", {})
    clan = merged.get("clan", {})
    farm = merged.get("farm", {})
    clan_limits = _load_clan_perks(root)
    deploy_side = str(farm.get("deploy_side", "left")).strip().lower()
    if deploy_side not in ("left", "right"):
        deploy_side = "left"

    return BotConfig(
        adb_device=os.environ.get("ADB_DEVICE", adb.get("device", "127.0.0.1:5555")),
        coc_package=adb.get("coc_package", "com.supercell.clashofclans"),
        template_threshold=vision.get("template_threshold", 0.82),
        donate_button_threshold=vision.get("donate_button_threshold", 0.78),
        scale_range=vision.get("scale_range", [0.95, 1.0, 1.05]),
        tap_jitter_px=timing.get("tap_jitter_px", 6),
        action_delay_ms=tuple(timing.get("action_delay_ms", [120, 350])),
        scan_interval_ms=tuple(timing.get("scan_interval_ms", [800, 1500])),
        anti_idle_seconds=int(timing.get("anti_idle_seconds", 60)),
        session_limit_seconds=runtime.get("session_limit_seconds", 4 * 3600),
        break_min_seconds=runtime.get("break_min_seconds", 600),
        break_max_seconds=runtime.get("break_max_seconds", 900),
        game_load_timeout_seconds=runtime.get("game_load_timeout_seconds", 90),
        state_watchdog_seconds=runtime.get("state_watchdog_seconds", 45),
        frame_width=int(merged.get("frame_width") or 0),
        frame_height=int(merged.get("frame_height") or 0),
        rois=merged.get("rois") or {},
        tap_points=merged.get("tap_points") or {},
        templates=merged.get("templates") or {},
        colors=merged.get("colors") or {},
        grid=merged.get("grid") or {},
        donation_order=donation.get("order", ["troop", "spell", "siege"]),
        handled_request_ttl_seconds=donation.get("handled_request_ttl_seconds", 120),
        chat_max_scroll_attempts=donation.get("chat_max_scroll_attempts", 20),
        bar_max_scroll_attempts=donation.get("bar_max_scroll_attempts", 5),
        spell_bar_max_scroll_attempts=donation.get("spell_bar_max_scroll_attempts", 2),
        donate_open_requests=donation.get("donate_open_requests", True),
        parse_request_capacity=donation.get("parse_request_capacity", False),
        donation_panel_wait_seconds=float(donation.get("donation_panel_wait_seconds", 3.0)),
        clan_level=int(clan.get("level", 8)),
        clan_donation_limits=clan_limits,
        ocr_confidence_threshold=vision.get("ocr_confidence_threshold", 0.5),
        farm_enabled=bool(farm.get("enabled", False)),
        farm_interval_seconds=int(farm.get("interval_seconds", 3600)),
        farm_interval_variance_seconds=max(0, int(farm.get("interval_variance_seconds", 300))),
        farm_deploy_side=deploy_side,
        farm_pan_swipes=max(0.0, float(farm.get("pan_swipes", 3))),
        farm_deploy_jitter_px=max(0, min(40, int(farm.get("deploy_jitter_px", 6)))),
        farm_match_timeout_seconds=int(farm.get("match_timeout_seconds", 120)),
        farm_battle_timeout_seconds=int(farm.get("battle_timeout_seconds", 210)),
        farm_retry_cooldown_seconds=int(farm.get("retry_cooldown_seconds", 300)),
        farm_edrag_deploy_taps=int(farm.get("edrag_deploy_taps", 14)),
        farm_hero_count=max(0, min(4, int(farm.get("hero_count", 4)))),
        farm_deploy_siege=bool(farm.get("deploy_siege", True)),
        farm_activate_hero_abilities=bool(farm.get("activate_hero_abilities", True)),
        farm_deploy_rage=bool(farm.get("deploy_rage", True)),
        farm_rage_count=max(0, min(20, int(farm.get("rage_count", 5)))),
        farm_rage_inward_frac=max(0.0, min(0.45, float(farm.get("rage_inward_frac", 0.22)))),
        farm_deploy_sequence=normalize_farm_deploy_sequence(
            merged.get("farm_deploy_sequence")
        ),
        gui_show_debug_activity=bool((merged.get("gui") or {}).get("show_debug_activity", False)),
        gui_ui_style=_normalize_ui_style((merged.get("gui") or {}).get("ui_style", "modern")),
        data_dir=root / "data",
        templates_dir=root / "data" / "templates",
    )


def _normalize_ui_style(raw: Any) -> str:
    style = str(raw or "modern").strip().lower()
    if style in ("classic", "legacy", "old"):
        return "classic"
    return "modern"


def normalize_farm_deploy_sequence(raw: Any) -> dict[str, Any]:
    """Return a clean ``{side, pan_swipes, taps}`` dict (empty taps if invalid)."""
    if not isinstance(raw, dict):
        return {"side": "left", "pan_swipes": 3.0, "taps": []}
    side = str(raw.get("side", "left")).strip().lower()
    if side not in ("left", "right"):
        side = "left"
    try:
        pan = max(0.0, float(raw.get("pan_swipes", 3.0)))
    except (TypeError, ValueError):
        pan = 3.0
    taps: list[list[int]] = []
    for item in raw.get("taps") or []:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        try:
            taps.append([int(item[0]), int(item[1])])
        except (TypeError, ValueError):
            continue
    return {"side": side, "pan_swipes": pan, "taps": taps}


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
        "colors": config.colors,
        "grid": config.grid,
        "farm_deploy_sequence": normalize_farm_deploy_sequence(config.farm_deploy_sequence),
    }
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(payload, f, default_flow_style=False, sort_keys=False)
