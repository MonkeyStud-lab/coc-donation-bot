"""GUI-editable settings definitions and persistence helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from coc_bot.config import BotConfig, load_config, load_user_settings, save_user_settings


@dataclass(frozen=True)
class SettingField:
    key: str
    label: str
    description: str
    kind: str  # int, float, bool, str, int_pair
    getter: Callable[[BotConfig], Any]
    section: str
    yaml_path: tuple[str, ...]  # e.g. ("timing", "anti_idle_seconds")


def _pair(lo_hi: tuple[int, int]) -> str:
    return f"{lo_hi[0]}, {lo_hi[1]}"


SETTINGS: list[SettingField] = [
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
        "Clan / device",
        ("clan", "level"),
    ),
    SettingField(
        "farm_enabled",
        "Enable elixir farm attacks",
        "When enabled, run one unranked Battle per interval (electro dragons along one edge). "
        "Requires Calibration → Farm. Leave e-drags as the active army preset.",
        "bool",
        lambda c: c.farm_enabled,
        "Farm",
        ("farm", "enabled"),
    ),
    SettingField(
        "farm_interval_seconds",
        "Farm interval (seconds)",
        "Minimum time between auto farm attacks after a battle is fought "
        "(7200 = every 2 hours). Applies even if Return Home / chat confirm fails. "
        "Stop and Start the bot after saving so the running loop picks this up.",
        "int",
        lambda c: c.farm_interval_seconds,
        "Farm",
        ("farm", "interval_seconds"),
    ),
    SettingField(
        "farm_deploy_side",
        "Deploy side (left / right)",
        "Which battlefield edge to dump troops along. Use left or right.",
        "str",
        lambda c: c.farm_deploy_side,
        "Farm",
        ("farm", "deploy_side"),
    ),
    SettingField(
        "farm_pan_swipes",
        "Camera pan swipes",
        "How many swipes from the centered match view toward the deploy edge. "
        "Decimals allowed (e.g. 1.25 = one full swipe + a short extra pan).",
        "float",
        lambda c: c.farm_pan_swipes,
        "Farm",
        ("farm", "pan_swipes"),
    ),
    SettingField(
        "farm_deploy_jitter_px",
        "Farm deploy jitter (pixels)",
        "Random offset for custom farm deploy sequence taps only (±N on X and Y). "
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
        "farm_edrag_deploy_taps",
        "E-drag map taps",
        "How many times to tap the village edge while electro dragons are selected "
        "(use a bit more than 11 so all leave the bar).",
        "int",
        lambda c: c.farm_edrag_deploy_taps,
        "Farm",
        ("farm", "edrag_deploy_taps"),
    ),
    SettingField(
        "farm_hero_count",
        "Heroes to deploy (0–4)",
        "After e-drags, select and place this many heroes from the army bar.",
        "int",
        lambda c: c.farm_hero_count,
        "Farm",
        ("farm", "hero_count"),
    ),
    SettingField(
        "farm_deploy_siege",
        "Deploy siege machine",
        "After e-drags, select the siege slot and drop it on the deploy edge.",
        "bool",
        lambda c: c.farm_deploy_siege,
        "Farm",
        ("farm", "deploy_siege"),
    ),
    SettingField(
        "farm_activate_hero_abilities",
        "Activate hero abilities",
        "After placing each hero, tap their army-bar icon again to trigger the ability.",
        "bool",
        lambda c: c.farm_activate_hero_abilities,
        "Farm",
        ("farm", "activate_hero_abilities"),
    ),
    SettingField(
        "farm_deploy_rage",
        "Deploy rage spells",
        "After e-drags are down, select rage and drop them toward the base from the troop line.",
        "bool",
        lambda c: c.farm_deploy_rage,
        "Farm",
        ("farm", "deploy_rage"),
    ),
    SettingField(
        "farm_rage_count",
        "Rage spell drops",
        "How many rage spells to place after selecting the rage card once "
        "(spread vertically on the base — default 5).",
        "int",
        lambda c: c.farm_rage_count,
        "Farm",
        ("farm", "rage_count"),
    ),
    SettingField(
        "farm_rage_inward_frac",
        "Rage inward offset",
        "How far toward the village from the troop column (screen fraction, e.g. 0.22). "
        "On a left deploy this is well to the right of the troops.",
        "float",
        lambda c: c.farm_rage_inward_frac,
        "Farm",
        ("farm", "rage_inward_frac"),
    ),
    SettingField(
        "adb_device",
        "ADB device address",
        "Waydroid ADB target, e.g. 192.168.240.112:5555 or 127.0.0.1:5555. "
        "Check with: adb devices",
        "str",
        lambda c: c.adb_device,
        "Clan / device",
        ("adb", "device"),
    ),
    SettingField(
        "session_limit_seconds",
        "Session limit before break (seconds)",
        "How long the bot runs before a forced break (default 14400 = 4 hours) to reduce "
        "Clash “take a break” / anti-bot risk.",
        "int",
        lambda c: c.session_limit_seconds,
        "Breaks",
        ("runtime", "session_limit_seconds"),
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
]


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
            if field.key == "farm_hero_count" and (parsed < 0 or parsed > 4):
                raise ValueError("Heroes to deploy must be between 0 and 4")
            if field.key == "farm_edrag_deploy_taps" and parsed < 1:
                raise ValueError("E-drag map taps must be at least 1")
            if field.key == "farm_rage_count" and (parsed < 0 or parsed > 20):
                raise ValueError("Rage spell drops must be between 0 and 20")
        elif field.kind == "float":
            parsed = float(str(raw).strip())
            if field.key == "farm_pan_swipes" and parsed < 0:
                raise ValueError("Camera pan swipes cannot be negative")
            if field.key == "farm_rage_inward_frac" and (parsed < 0 or parsed > 0.45):
                raise ValueError("Rage inward offset must be between 0 and 0.45")
        elif field.kind == "int_pair":
            parsed = parse_int_pair(str(raw))
        else:
            parsed = str(raw).strip()
            if field.key == "farm_deploy_side":
                side = parsed.lower()
                if side not in ("left", "right"):
                    raise ValueError("Deploy side must be 'left' or 'right'")
                parsed = side

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
    incoming = build_user_settings_payload(values)
    # Shallow-section merge: replace sections we edit.
    for section, data in incoming.items():
        if isinstance(data, dict) and isinstance(existing.get(section), dict):
            existing[section] = {**existing[section], **data}
        else:
            existing[section] = data
    save_user_settings(existing)
