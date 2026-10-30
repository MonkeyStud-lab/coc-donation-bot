"""GUI-editable settings definitions and persistence helpers."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable

from coc_bot.config import BotConfig, load_config, load_user_settings, save_user_settings
from coc_bot.control.themes import normalize_theme_id, theme_label, theme_labels
from coc_bot.control.timing_presets import (
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


# Shared by browser validation and desktop settings persistence.
UPGRADE_INTEGER_LIMITS = {
    'farm_resource_start_percent': (1, 99),
    'farm_resource_target_percent': (2, 100),
    'builder_base_interval_seconds': (300, 86400),
    'builder_base_builders_reserved': (0, 3),
    'builder_base_gold_reserve': (0, 20_000_000),
    'builder_base_elixir_reserve': (0, 20_000_000),
    'upgrade_interval_seconds': (60, 86400),
    'upgrade_builders_reserved': (0, 6),
    'upgrade_gold_reserve': (0, 100_000_000),
    'upgrade_elixir_reserve': (0, 100_000_000),
    'upgrade_dark_elixir_reserve': (0, 100_000_000),
}


SETTINGS: list[SettingField] = [
    SettingField('builder_base_collect_resources','Collect Builder Base resources','Collect verified mine/collector bubbles in both areas and defense rewards from the Elixir Cart. Works without attacks or upgrades.','bool',lambda c:c.builder_base_collect_resources,'Builder Base',('builder_base','collect_resources')),
    SettingField('builder_base_progression_enabled','Builder village progression','Prioritize the Star Laboratory, build missing structures, then upgrade existing buildings. Builder Hall advancement requires a complete max-building check.','bool',lambda c:c.builder_base_progression_enabled,'Builder Base',('builder_base','progression_enabled')),
    SettingField('builder_base_research_enabled','Builder Base research','Use Builder Elixir for supported farming troops. Night Witch and the first Sneaky Archer upgrade are verified; unfamiliar confirmation screens pause safely.','bool',lambda c:c.builder_base_research_enabled,'Builder Base',('builder_base','research_enabled')),
    SettingField('builder_base_elixir_reserve','Builder Elixir to keep','Minimum Builder Elixir remaining after research.','int',lambda c:c.builder_base_elixir_reserve,'Builder Base',('builder_base','elixir_reserve')),
    SettingField('builder_base_attacks_enabled','Refill Builder Base resources','Use the Farm resource percentages to refill Builder storages before upgrade checks. Supports starter Barbarian camps or six Night Witches with Battle Machine. Unknown armies or counters defer farming; upgrade checks still run.','bool',lambda c:c.builder_base_attacks_enabled,'Builder Base',('builder_base','attacks_enabled')),
    SettingField('builder_base_upgrades_enabled','Builder Base building upgrades','Use Builder Gold or Builder Elixir while keeping the selected reserves and spare builders. Progression adds construction and a gated Builder Hall check. Gems and items are excluded.','bool',lambda c:c.builder_base_upgrades_enabled,'Builder Base',('builder_base','upgrades_enabled')),
    SettingField('builder_base_builders_reserved','Builder Base builders to keep free','Only affects Builder Base builders.','int',lambda c:c.builder_base_builders_reserved,'Builder Base',('builder_base','builders_reserved')),
    SettingField('builder_base_gold_reserve','Builder Gold to keep','Minimum Builder Gold remaining after an upgrade.','int',lambda c:c.builder_base_gold_reserve,'Builder Base',('builder_base','gold_reserve')),
    SettingField('progression_enabled','Village progression','Prioritize the Laboratory, build missing structures, then improve the village and prepare farming armies from verified unlocks. Town Hall upgrades require a complete max-building check.','bool',lambda c:c.progression_enabled,'Upgrades',('progression','enabled')),
    SettingField('progression_rearrange','Search for building space','Move the new-building preview to find a valid spot before paying. Ordinary-obstacle clearing is a separate option.','bool',lambda c:c.progression_rearrange,'Upgrades',('progression','rearrange')),
    SettingField('layouts_enabled','Automatic defensive layouts','Off by default. When enabled for this account, clear build-zone obstacles and import a matching defensive layout. Activate only after completion and Home village verification.','bool',lambda c:c.layouts_enabled,'Upgrades',('layouts','enabled')),
    SettingField('layouts_replace_inactive','Replace inactive layouts','Allow automatic layouts to replace a spare inactive slot. The current active village is preserved until its replacement is complete.','bool',lambda c:c.layouts_replace_inactive,'Upgrades',('layouts','replace_inactive')),
    SettingField('progression_clear_obstacles','Clear ordinary obstacles','Allow verified gold/elixir removal of ordinary obstacles to create building space. Seasonal removal needs its separate option.','bool',lambda c:c.progression_clear_obstacles,'Upgrades',('progression','clear_obstacles')),
    SettingField('progression_clear_seasonal_obstacles','Remove seasonal obstacles','Also allow permanent removal of seasonal obstacles for verified gold/elixir costs. Gems, shovels and storage actions are excluded.','bool',lambda c:c.progression_clear_seasonal_obstacles,'Upgrades',('progression','clear_seasonal_obstacles')),
    SettingField('upgrade_buildings_enabled','Automatic building upgrades','Use spare builders. Village progression adds new construction and full-building checks; otherwise follows Suggested upgrades.','bool',lambda c:c.upgrade_buildings_enabled,'Upgrades',('upgrades','buildings_enabled')),
    SettingField('upgrade_research_enabled','Automatic army research','Start the first eligible Suggested troop or spell research when the laboratory is free. Never spend gems or items.','bool',lambda c:c.upgrade_research_enabled,'Upgrades',('upgrades','research_enabled')),
    SettingField('upgrade_pets_enabled','Automatic pet upgrades','Upgrade an eligible unassigned pet when the pet-upgrade slot is free. Uses dark elixir while keeping your reserve. Never spends gems or items.','bool',lambda c:c.upgrade_pets_enabled,'Upgrades',('upgrades','pets_enabled')),
    SettingField('upgrade_pets_include_assigned','Allow upgrades of equipped pets','Also consider pets assigned to heroes after checking unassigned pets. A pet being upgraded may be unavailable for attacks. Off keeps equipped pets out of automatic upgrades.','bool',lambda c:c.upgrade_pets_include_assigned,'Upgrades',('upgrades','pets_include_assigned')),
    SettingField('upgrade_interval_seconds','Upgrade check interval (seconds)','Check between donation rounds, never during a battle or donation. Minimum 60 seconds.','int',lambda c:c.upgrade_interval_seconds,'Upgrades',('upgrades','interval_seconds')),
    SettingField('upgrade_builders_reserved','Builders to keep free','Do not start a building upgrade if it would leave fewer free builders than this number.','int',lambda c:c.upgrade_builders_reserved,'Upgrades',('upgrades','builders_reserved')),
    SettingField('upgrade_gold_reserve','Gold to keep','Minimum gold remaining after an upgrade.','int',lambda c:c.upgrade_gold_reserve,'Upgrades',('upgrades','gold_reserve')),
    SettingField('upgrade_elixir_reserve','Elixir to keep for donations','Minimum elixir remaining after building or army upgrades.','int',lambda c:c.upgrade_elixir_reserve,'Upgrades',('upgrades','elixir_reserve')),
    SettingField('upgrade_dark_elixir_reserve','Dark elixir to keep for donations','Minimum dark elixir remaining after army research or pet upgrades.','int',lambda c:c.upgrade_dark_elixir_reserve,'Upgrades',('upgrades','dark_elixir_reserve')),
    SettingField('upgrade_excluded_names','Never upgrade these names','Optional comma-separated names, for example Bowler, Blacksmith. Other recommendations remain eligible.','str',lambda c:c.upgrade_excluded_names,'Upgrades',('upgrades','excluded_names')),
    SettingField("collection_enabled", "Collect useful screenshots", "Passively save unusual screens and failures for review. Does not change game actions. Takes effect after Stop/Start.", "bool", lambda c: c.collection_enabled, "Screenshot collection", ("collection", "enabled")),
    SettingField("collection_daily_limit", "Daily screenshot limit", "Maximum screenshots saved per UTC day, including failure context. Collection pauses when the limit is reached.", "int", lambda c: c.collection_daily_limit, "Screenshot collection", ("collection", "daily_limit")),
    SettingField("collection_storage_gb", "Screenshot storage limit (GB)", "Stop saving when collected images reach this size. Existing images are never automatically deleted. Review them from Library.", "float", lambda c: c.collection_storage_gb, "Screenshot collection", ("collection", "storage_gb")),
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
        "Refill Home Village resources",
        "Attack when storage is low and recheck after each battle until the refill target is reached. "
        "Requires the normal Farm navigation calibration.",
        "bool",
        lambda c: c.farm_enabled,
        "Farm",
        ("farm", "enabled"),
    ),
    SettingField(
        'farm_engine', 'Attack method',
        'Automatic reads the army and uses a farming routine without saved taps. Village progression also prepares troops from verified unlocks. '
        'Supports optional Rage, siege and recognized heroes; uncertain or unsupported armies are skipped. '
        'Planner uses a saved, live-tested routine. Sequence keeps your existing taps.',
        'choice', lambda c: c.farm_engine, 'Farm', ('farm','engine'),
        choices=('sequence','planner','automatic'),
    ),
    SettingField(
        "farm_resource_start_percent",
        "Start refill below (%)",
        "Start a refill when any unlocked resource falls below this percentage. Applies to Home and Builder Base farming.",
        "int",
        lambda c: c.farm_resource_start_percent,
        "Farm",
        ("farm", "resource_start_percent"),
    ),
    SettingField(
        "farm_resource_target_percent",
        "Refill to (%)",
        "Continue the refill until every unlocked resource reaches this target. Must exceed the start percentage. Failed or unproductive attacks pause for review/retry.",
        "int",
        lambda c: c.farm_resource_target_percent,
        "Farm",
        ("farm", "resource_target_percent"),
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
        "Battle results fallback (seconds)",
        "Watch for the results screen after deploying. Return early only when its "
        "labels are confirmed twice. If recognition fails, tap Return Home after "
        "this time from first deploy (default 210 = 3 minutes 30 seconds).",
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
        "game_load_timeout_seconds",
        "Game load timeout (seconds)",
        "Max time to wait for Clash to finish loading after a relaunch.",
        "int",
        lambda c: c.game_load_timeout_seconds,
        "Device",
        ("runtime", "game_load_timeout_seconds"),
    ),
    SettingField(
        "state_watchdog_seconds",
        "Watchdog timeout (seconds)",
        "If the bot stays in one state longer than this, it runs recovery (BACK + reopen chat).",
        "int",
        lambda c: c.state_watchdog_seconds,
        "Device",
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
        "Show DEBUG messages by default",
        "Default for the activity log's Debug filter when opening the app. "
        "The filter in Overview can change it temporarily.",
        "bool",
        lambda c: c.gui_show_debug_activity,
        "Interface",
        ("gui", "show_debug_activity"),
    ),
    SettingField(
        "gui_practice_mode",
        "Practice mode (no donate taps)",
        "When enabled, Start runs in practice mode: navigation still works, but donation "
        "taps are skipped. Useful to verify calibration safely. Stop/Start after changing.",
        "bool",
        lambda c: c.gui_practice_mode,
        "Interface",
        ("gui", "practice_mode"),
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
        "Color palette for the desktop app. The web app uses the Harbor interface. "
        "Previews immediately. Save changes keeps it without restarting the bot.",
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
            if field.key in UPGRADE_INTEGER_LIMITS:
                lower,upper=UPGRADE_INTEGER_LIMITS[field.key]
                if not lower <= parsed <= upper:
                    raise ValueError(f'{field.label} must be between {lower} and {upper}')
        elif field.kind == "float":
            parsed = float(str(raw).strip())
            if not math.isfinite(parsed):
                raise ValueError(f"{field.label} must be a finite number")
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
            if field.key=='upgrade_excluded_names' and len(parsed)>1000:
                raise ValueError('Upgrade exclusions are too long')

        if field.key in ("collection_daily_limit", "collection_storage_gb") and parsed <= 0:
            raise ValueError(f"{field.label} must be greater than zero")
        cursor = payload
        for part in field.yaml_path[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[field.yaml_path[-1]] = parsed
    from coc_bot.runtime.resource_farming import thresholds
    thresholds(payload['farm']['resource_start_percent'], payload['farm']['resource_target_percent'])
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
