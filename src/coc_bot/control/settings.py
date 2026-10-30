"""Validated, revision-checked settings shared with the desktop."""
from dataclasses import asdict
import hashlib
import math
from coc_bot.config import user_settings_path, load_user_settings, save_user_settings
from coc_bot.control.settings_fields import (
    SETTINGS, current_setting_values, save_settings_from_gui, parse_int_pair,
    is_raw_timing_field,
    build_user_settings_payload,
    UPGRADE_INTEGER_LIMITS,
)
from coc_bot.control.themes import THEMES
from coc_bot.calibration.transactions import calibration_locked

# These preferences are consumed by interfaces, not the automation worker.
LIVE_INTERFACE_FIELDS = frozenset({"gui_theme", "gui_show_debug_activity", "gui_dev_options"})
OPTIONAL_RESERVES = frozenset({"upgrade_builders_reserved", "upgrade_gold_reserve",
    "upgrade_elixir_reserve", "upgrade_dark_elixir_reserve", "builder_base_builders_reserved",
    "builder_base_gold_reserve", "builder_base_elixir_reserve"})


class RevisionConflict(ValueError):
    pass


def revision():
    path = user_settings_path()
    from coc_bot.accounts.store import selected_account
    account = selected_account.get()
    salt = account['id'].encode() if account else b''
    return hashlib.sha256(salt + (path.read_bytes() if path.exists() else b"")).hexdigest()


def settings_snapshot():
    return {"revision": revision(), "values": current_setting_values(),
            "fields": [{k: v for k, v in asdict(f).items() if k != "getter"}
                       | {"advanced": is_raw_timing_field(f.key),
                          "restart_required": f.key not in LIVE_INTERFACE_FIELDS,
                          "expert": f.key in OPTIONAL_RESERVES}
                       for f in SETTINGS],
            "themes": [asdict(t) for t in THEMES.values()]}


@calibration_locked
def validate_settings(values, expected_revision):
    if revision() != expected_revision:
        raise RevisionConflict("Settings changed elsewhere. Reload before saving.")
    known = {f.key: f for f in SETTINGS}
    if set(values) - known.keys():
        raise ValueError("Unknown settings")
    complete = current_setting_values() | values
    for key, raw in complete.items():
        f = known[key]
        if f.kind == "bool" and type(raw) is not bool:
            raise ValueError(f"{f.label} must be on or off")
        if f.kind == "choice" and raw not in f.choices:
            raise ValueError(f"Choose a listed value for {f.label}")
        if f.kind in ("int", "float"):
            if type(raw) not in (int, float, str):
                raise ValueError(f"{f.label} must be a number")
            number = float(raw)
            lower, upper = UPGRADE_INTEGER_LIMITS.get(key, (0, 10_000_000))
            if not math.isfinite(number):
                raise ValueError(f"{f.label} must be a finite, non-negative number")
            if not lower <= number <= upper:
                raise ValueError(f"{f.label} must be between {lower} and {upper}")
            if f.kind == "int" and not number.is_integer():
                raise ValueError(f"{f.label} must be a whole number")
        if f.kind == "int_pair":
            lo, hi = parse_int_pair(str(raw))
            if not 0 <= lo <= hi <= 60000:
                raise ValueError(f"{f.label}: use two ordered values between 0 and 60000")
        if f.kind not in ("bool", "choice", "int", "float", "int_pair"):
            if not isinstance(raw, str) or len(raw) > 500 or "\n" in raw:
                raise ValueError(f"Invalid {f.label}")
    build_user_settings_payload(complete)  # Include field-specific persistence rules before stopping.
    return complete


def _field_value(payload, field):
    for part in field.yaml_path:
        payload = payload[part]
    return payload


def changed_settings(complete):
    """Compare persisted values, including numeric text from browser inputs."""
    before = build_user_settings_payload(current_setting_values())
    after = build_user_settings_payload(complete)
    return {f.key for f in SETTINGS if _field_value(before, f) != _field_value(after, f)}


@calibration_locked
def save_interface_settings(values, expected_revision):
    complete = validate_settings(values, expected_revision)
    changed = changed_settings(complete)
    if not changed <= LIVE_INTERFACE_FIELDS:
        raise ValueError("Bot settings require the normal settings save")
    if changed:
        # Avoid the operational save path: it also reapplies timing presets.
        # Preserve every other setting, including unknown extension keys.
        existing = load_user_settings()
        incoming = build_user_settings_payload(complete)
        for field in SETTINGS:
            if field.key in changed:
                cursor = existing
                for part in field.yaml_path[:-1]:
                    cursor = cursor.setdefault(part, {})
                cursor[field.yaml_path[-1]] = _field_value(incoming, field)
        save_user_settings(existing)
    return settings_snapshot()


@calibration_locked
def save_settings(values, expected_revision):
    complete = validate_settings(values, expected_revision)
    save_settings_from_gui(complete)
    return settings_snapshot()
