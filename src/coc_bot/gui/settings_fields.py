"""GUI-editable settings definitions and persistence helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from coc_bot.config import BotConfig, load_config, load_user_settings, save_user_settings
from coc_bot.gui.theme import normalize_theme_id, theme_label, theme_labels
from coc_bot.gui.timing_presets import (
    PRESET_LABELS,
    RAW_TIMING_FIELD_KEYS,
    apply_timing_preset,
    infer_preset_from_timing,
    normalize_timing_preset,
    timing_preset_id_from_label,
    timing_preset_label,
)


@dataclass(frozen=True)
class SettingField:
    key: str
    label: str
    description: str
    kind: str  # int, float, bool, str, int_pair, choice
    getter: Callable[[BotConfig], Any]
    section: str
    yaml_path: tuple[str, ...]  # e.g. ("timing", "anti_idle_seconds")
    choices: tuple[str, ...] = ()  # for kind "choice"


def _pair(lo_hi: tuple[int, int]) -> str:
    return f"{lo_hi[0]}, {lo_hi[1]}"


SETTINGS: list[SettingField] = [
    SettingField(
        "gui_timing_preset",
        "Timing preset",
        "Safe = slower and steadier; Balanced = defaults; Fast = snappier taps/scans. "
        "Turn on Dev options (Interface) to edit raw millisecond values.",
        "choice",
        lambda c: timing_preset_label(c.gui_timing_preset),
        "Timing",
        ("gui", "timing_preset"),
        choices=PRESET_LABELS,
    ),
    SettingField(
        "scan_interval_ms",
        "Screenshot / scan interval (ms)",
        "How long to wait between each bot loop (min, max). Lower = faster reactions but more "
        "ADB screenshots and a laggier game. Example: 800, 1500",
        "int_pair",
        lambda c: _pair(c.scan_interval_ms),
        "Timing",
        ("timing", "scan_interval_ms"),
    ),
    SettingField(
        "anti_idle_seconds",
        "Inactivity prevention interval (seconds)",
        "About how often the bot does a small chat-panel swipe so Clash of Clans does not "
        "kick you for being idle. Typical: 60",
        "int",
        lambda c: c.anti_idle_seconds,
        "Timing",
        ("timing", "anti_idle_seconds"),
    ),
    SettingField(
        "action_delay_ms",
        "Delay between taps (ms)",
        "Random pause after each tap/swipe (min, max). Makes actions look less robotic. "
        "Example: 120, 350",
        "int_pair",
        lambda c: _pair(c.action_delay_ms),
        "Timing",
        ("timing", "action_delay_ms"),
    ),
    SettingField(
        "tap_jitter_px",
        "Tap jitter (pixels)",
        "Random offset added to tap coordinates so taps are not pixel-perfect every time "
        "(donations, navigation, etc.). Farm deploy sequence has its own jitter below.",
        "int",
        lambda c: c.tap_jitter_px,
        "Timing",
        ("timing", "tap_jitter_px"),
    ),
    SettingField(
        "donate_open_requests",
        "Donate to open / non-specific requests",
        "If enabled, the bot fills requests with no specific troop icons (open requests) by "
        "tapping colored slots. If disabled, only specific (icon) requests are donated.",
        "bool",
        lambda c: c.donate_open_requests,
        "Donation",
        ("donation", "donate_open_requests"),
    ),
    SettingField(
        "bar_max_scroll_attempts",
        "Troop bar max scrolls",
        "How many times to swipe the troop bar right to reach siege machines (~3 usually needed).",
        "int",
        lambda c: c.bar_max_scroll_attempts,
        "Donation",
        ("donation", "bar_max_scroll_attempts"),
    ),
    SettingField(
        "spell_bar_max_scroll_attempts",
        "Spell bar max scrolls",
        "How many times to swipe the spell bar after tapping all visible colored spells.",
        "int",
        lambda c: c.spell_bar_max_scroll_attempts,
        "Donation",
        ("donation", "spell_bar_max_scroll_attempts"),
    ),
    SettingField(
        "chat_max_scroll_attempts",
        "Chat scroll attempts",
        "Max chat scrolls while searching for Donate buttons before resetting search strategy.",
        "int",
        lambda c: c.chat_max_scroll_attempts,
        "Donation",
        ("donation", "chat_max_scroll_attempts"),
    ),
    SettingField(
        "donation_panel_wait_seconds",
        "Donation panel wait (seconds)",
        "How long to wait for the donation popup after tapping Donate before giving up.",
        "float",
        lambda c: c.donation_panel_wait_seconds,
        "Donation",
        ("donation", "donation_panel_wait_seconds"),
    ),
    SettingField(
        "handled_request_ttl_seconds",
        "Handled request memory (seconds)",
        "Ignore a request button we already finished for this many seconds (avoids reopening).",
        "int",
        lambda c: c.handled_request_ttl_seconds,
        "Donation",
        ("donation", "handled_request_ttl_seconds"),
    ),
    SettingField(
        "parse_request_capacity",
        "OCR request capacity bars",
        "If enabled, uses EasyOCR to read 0/35-style bars (slow). Not required for simple "
        "colored-slot donating.",
        "bool",
        lambda c: c.parse_request_capacity,
        "Donation",
        ("donation", "parse_request_capacity"),
    ),
    SettingField(
        "clan_level",
        "Clan level",
        "Your clan level — used for max housing you can donate per action (from clan_perks.yaml).",
        "int",
        lambda c: c.clan_level,
        "Clan",
        ("clan", "level"),
    ),
    SettingField(
        "farm_enabled",
        "Enable elixir farm attacks",
        "When enabled, run one unranked Battle per interval using your programmed "
        "deploy tap sequence. Requires Setup → Farm calibration and a deploy sequence.",
        "bool",
        lambda c: c.farm_enabled,
        "Farm",
        ("farm", "enabled"),
    ),
    SettingField(
        "farm_interval_seconds",
        "Farm interval (seconds)",
        "Base time between auto farm attacks after a battle is fought "
        "(7200 = every 2 hours). Applies even if Return Home / chat confirm fails. "
        "Stop and Start the bot after saving so the running loop picks this up.",
        "int",
        lambda c: c.farm_interval_seconds,
        "Farm",
        ("farm", "interval_seconds"),
    ),
    SettingField(
        "farm_interval_variance_seconds",
        "Farm interval variance (± seconds)",
        "Random ± this many seconds around the farm interval so attacks are not "
        "metronomic (300 ≈ ±5 minutes). Set 0 for an exact interval. "
        "The rolled wait is saved until the next fought farm.",
        "int",
        lambda c: c.farm_interval_variance_seconds,
        "Farm",
        ("farm", "interval_variance_seconds"),
    ),
    SettingField(
        "farm_deploy_side",
        "Deploy side",
        "Default battlefield edge when programming a new deploy sequence "
        "(the saved sequence stores its own side).",
        "choice",
        lambda c: c.farm_deploy_side,
        "Farm",
        ("farm", "deploy_side"),
        choices=("left", "right"),
    ),
    SettingField(
        "farm_pan_swipes",
        "Camera pan swipes",
        "Default pan count when programming a new deploy sequence "
        "(decimals ok, e.g. 1.25). The saved sequence stores its own value.",
        "float",
        lambda c: c.farm_pan_swipes,
        "Farm",
        ("farm", "pan_swipes"),
    ),
    SettingField(
        "farm_deploy_jitter_px",
        "Farm deploy jitter (pixels)",
        "Random offset for farm deploy sequence taps only (±N on X and Y). "
        "Does not affect donations or other taps. Also adjustable in the program-deploy "
        "editor (circle radius = N). Keep ≤12 for small army-bar icons.",
        "int",
        lambda c: c.farm_deploy_jitter_px,
        "Farm",
        ("farm", "deploy_jitter_px"),
    ),
    SettingField(
        "farm_match_timeout_seconds",
        "Matchmaking timeout (seconds)",
        "How long to wait in Find a Match / clouds before aborting the farm attempt.",
        "int",
        lambda c: c.farm_match_timeout_seconds,
        "Farm",
        ("farm", "match_timeout_seconds"),
    ),
    SettingField(
        "farm_battle_timeout_seconds",
        "Battle wait after deploy (seconds)",
        "After the first troop is placed, wait this long then tap Return Home "
        "(default 210 = 3 minutes 30 seconds). Then confirm home village / chat.",
        "int",
        lambda c: c.farm_battle_timeout_seconds,
        "Farm",
        ("farm", "battle_timeout_seconds"),
    ),
    SettingField(
        "farm_retry_cooldown_seconds",
        "Farm failure cooldown (seconds)",
        "Only used when a farm fails before deploy (e.g. could not open Attack). "
        "After a fought battle, the Farm interval above applies instead.",
        "int",
        lambda c: c.farm_retry_cooldown_seconds,
        "Farm",
        ("farm", "retry_cooldown_seconds"),
    ),
    SettingField(
        "adb_device",
        "ADB device address",
        "ADB target for the Android session, e.g. 127.0.0.1:5555 or host:5555. "
        "Check with: adb devices",
        "str",
        lambda c: c.adb_device,
        "Device",
        ("adb", "device"),
    ),
    SettingField(
        "session_limit_seconds",
        "Session limit before break (seconds)",
        "Base how long the bot runs before a forced break (default 14400 = 4 hours) to reduce "
        "Clash “take a break” / anti-bot risk.",
        "int",
        lambda c: c.session_limit_seconds,
        "Breaks",
        ("runtime", "session_limit_seconds"),
    ),
    SettingField(
        "session_limit_variance_seconds",
        "Session limit variance (± seconds)",
        "Random ± this many seconds around the session limit so breaks are not metronomic "
        "(300 ≈ ±5 minutes). Set 0 for an exact limit. The rolled length is saved until "
        "the next break.",
        "int",
        lambda c: c.session_limit_variance_seconds,
        "Breaks",
        ("runtime", "session_limit_variance_seconds"),
    ),
    SettingField(
        "break_min_seconds",
        "Break length min (seconds)",
        "Shortest random break after the session limit (game is force-stopped during the break).",
        "int",
        lambda c: c.break_min_seconds,
        "Breaks",
        ("runtime", "break_min_seconds"),
    ),
    SettingField(
        "break_max_seconds",
        "Break length max (seconds)",
        "Longest random break after the session limit.",
        "int",
        lambda c: c.break_max_seconds,
        "Breaks",
        ("runtime", "break_max_seconds"),
    ),
    SettingField(
        "game_load_timeout_seconds",
        "Game load timeout (seconds)",
        "Max time to wait for Clash to finish loading after a relaunch.",
        "int",
        lambda c: c.game_load_timeout_seconds,
        "Breaks",
        ("runtime", "game_load_timeout_seconds"),
    ),
    SettingField(
        "state_watchdog_seconds",
        "Watchdog timeout (seconds)",
        "If the bot stays in one state longer than this, it runs recovery (BACK + reopen chat).",
        "int",
        lambda c: c.state_watchdog_seconds,
        "Breaks",
        ("runtime", "state_watchdog_seconds"),
    ),
    SettingField(
        "template_threshold",
        "Template match threshold",
        "How strict OpenCV template matching is (0–1). Higher = fewer false matches, may miss buttons.",
        "float",
        lambda c: c.template_threshold,
        "Vision",
        ("vision", "template_threshold"),
    ),
    SettingField(
        "donate_button_threshold",
        "Donate button threshold",
        "Match threshold specifically for the green Donate button in clan chat.",
        "float",
        lambda c: c.donate_button_threshold,
        "Vision",
        ("vision", "donate_button_threshold"),
    ),
    SettingField(
        "gui_show_debug_activity",
        "Show DEBUG messages in activity log",
        "When enabled, Home → Activity also shows DEBUG lines (ADB commands, screen "
        "classifications, etc.). Leave off for a quieter log of INFO and above.",
        "bool",
        lambda c: c.gui_show_debug_activity,
        "Interface",
        ("gui", "show_debug_activity"),
    ),
    SettingField(
        "gui_dev_options",
        "Dev options",
        "When enabled, Timing shows raw millisecond fields so you can edit values by hand. "
        "When off, use Timing preset (Safe / Balanced / Fast) only.",
        "bool",
        lambda c: c.gui_dev_options,
        "Interface",
        ("gui", "dev_options"),
    ),
    SettingField(
        "gui_theme",
        "Theme",
        "Full UI theme (colors + control layout). Classic = stacked cards; "
        "Modern = row layout; Graphite / Midnight / Amethyst / Frost / Ember "
        "are additional palettes. Applies to the whole window after Save.",
        "choice",
        lambda c: theme_label(c.gui_theme),
        "Interface",
        ("gui", "theme"),
        choices=theme_labels(),
    ),
]


def is_raw_timing_field(field_key: str) -> bool:
    return field_key in RAW_TIMING_FIELD_KEYS


def parse_int_pair(text: str) -> list[int]:
    parts = [p.strip() for p in text.replace(";", ",").split(",") if p.strip()]
    if len(parts) != 2:
        raise ValueError("Expected two numbers like: 800, 1500")
    return [int(parts[0]), int(parts[1])]


def build_user_settings_payload(values: dict[str, str | bool]) -> dict[str, Any]:
    """Convert GUI widget values into a nested YAML payload."""
    payload: dict[str, Any] = {}
    for field in SETTINGS:
        raw = values[field.key]
        if field.kind == "bool":
            parsed: Any = bool(raw)
        elif field.kind == "int":
            parsed = int(str(raw).strip())
            if field.key in (
                "farm_interval_variance_seconds",
                "session_limit_variance_seconds",
            ) and parsed < 0:
                raise ValueError(f"{field.label} cannot be negative")
            if field.key in (
                "farm_interval_variance_seconds",
                "session_limit_variance_seconds",
            ) and parsed > 24 * 3600:
                raise ValueError(f"{field.label} must be at most 86400 seconds")
        elif field.kind == "float":
            parsed = float(str(raw).strip())
            if field.key == "farm_pan_swipes" and parsed < 0:
                raise ValueError("Camera pan swipes cannot be negative")
        elif field.kind == "int_pair":
            parsed = parse_int_pair(str(raw))
        elif field.kind == "choice":
            raw_text = str(raw).strip()
            if field.key == "gui_theme":
                parsed = normalize_theme_id(raw_text)
            elif field.key == "gui_timing_preset":
                parsed = timing_preset_id_from_label(raw_text)
            else:
                parsed = raw_text.lower()
                allowed = {c.lower() for c in field.choices}
                if parsed not in allowed:
                    raise ValueError(
                        f"{field.label} must be one of: {', '.join(field.choices)}"
                    )
                for choice in field.choices:
                    if choice.lower() == parsed:
                        parsed = choice
                        break
        else:
            parsed = str(raw).strip()

        cursor = payload
        for part in field.yaml_path[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[field.yaml_path[-1]] = parsed
    return payload


def current_setting_values() -> dict[str, Any]:
    config = load_config()
    return {field.key: field.getter(config) for field in SETTINGS}


def save_settings_from_gui(values: dict[str, str | bool]) -> None:
    existing = load_user_settings()
    previous = load_config()
    incoming = build_user_settings_payload(values)

    # Named timing presets overwrite timing.* ; Custom keeps whatever raw fields say.
    gui_in = incoming.get("gui") if isinstance(incoming.get("gui"), dict) else {}
    preset = normalize_timing_preset(gui_in.get("timing_preset", previous.gui_timing_preset))
    dev_options = bool(gui_in.get("dev_options", previous.gui_dev_options))
    if preset != "custom":
        timing_values = apply_timing_preset(preset)
        if timing_values:
            incoming.setdefault("timing", {})
            if isinstance(incoming["timing"], dict):
                incoming["timing"].update(timing_values)
    elif dev_options:
        # Editing raw fields while Dev options is on → mark Custom.
        timing_in = incoming.get("timing") if isinstance(incoming.get("timing"), dict) else {}
        if timing_in:
            scan = timing_in.get("scan_interval_ms", list(previous.scan_interval_ms))
            action = timing_in.get("action_delay_ms", list(previous.action_delay_ms))
            jitter = timing_in.get("tap_jitter_px", previous.tap_jitter_px)
            anti = timing_in.get("anti_idle_seconds", previous.anti_idle_seconds)
            inferred = infer_preset_from_timing(scan, action, int(jitter), int(anti))
            incoming.setdefault("gui", {})
            if isinstance(incoming["gui"], dict):
                incoming["gui"]["timing_preset"] = inferred

    # Shallow-section merge: replace sections we edit.
    for section, data in incoming.items():
        if isinstance(data, dict) and isinstance(existing.get(section), dict):
            existing[section] = {**existing[section], **data}
        else:
            existing[section] = data
    save_user_settings(existing)

    # Re-roll the next farm wait when interval / variance changes.
    farm_in = incoming.get("farm") or {}
    if isinstance(farm_in, dict) and (
        "interval_seconds" in farm_in or "interval_variance_seconds" in farm_in
    ):
        new_interval = int(farm_in.get("interval_seconds", previous.farm_interval_seconds))
        new_variance = int(
            farm_in.get("interval_variance_seconds", previous.farm_interval_variance_seconds)
        )
        if (
            new_interval != previous.farm_interval_seconds
            or new_variance != previous.farm_interval_variance_seconds
        ):
            _reroll_next_farm_interval(new_interval, new_variance)

    # Re-roll the next session limit when limit / variance changes.
    runtime_in = incoming.get("runtime") or {}
    if isinstance(runtime_in, dict) and (
        "session_limit_seconds" in runtime_in
        or "session_limit_variance_seconds" in runtime_in
    ):
        new_limit = int(
            runtime_in.get("session_limit_seconds", previous.session_limit_seconds)
        )
        new_limit_var = int(
            runtime_in.get(
                "session_limit_variance_seconds",
                previous.session_limit_variance_seconds,
            )
        )
        if (
            new_limit != previous.session_limit_seconds
            or new_limit_var != previous.session_limit_variance_seconds
        ):
            _reroll_next_session_limit(new_limit, new_limit_var)


def _reroll_next_farm_interval(base: int, variance: int) -> None:
    from coc_bot.runtime.persistence import load_runtime_state, save_runtime_state
    from coc_bot.runtime.tracker import roll_farm_interval_seconds

    config = load_config()
    path = config.data_dir / "runtime_state.json"
    state = load_runtime_state(path)
    state.next_farm_interval_seconds = roll_farm_interval_seconds(base, variance)
    save_runtime_state(path, state)


def _reroll_next_session_limit(base: int, variance: int) -> None:
    from coc_bot.runtime.persistence import load_runtime_state, save_runtime_state
    from coc_bot.runtime.tracker import roll_session_limit_seconds

    config = load_config()
    path = config.data_dir / "runtime_state.json"
    state = load_runtime_state(path)
    state.next_session_limit_seconds = roll_session_limit_seconds(base, variance)
    save_runtime_state(path, state)
