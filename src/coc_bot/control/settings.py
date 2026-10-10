"""Validated, revision-checked settings shared with the desktop."""
from dataclasses import asdict
import hashlib
import math
from coc_bot.config import load_config, user_settings_path
from coc_bot.control.settings_fields import (
    SETTINGS, current_setting_values, save_settings_from_gui, parse_int_pair,
    is_raw_timing_field,
)
from coc_bot.control.themes import THEMES
from coc_bot.calibration.transactions import calibration_locked


class RevisionConflict(ValueError):
    pass


def revision():
    path = user_settings_path()
    return hashlib.sha256(path.read_bytes() if path.exists() else b"").hexdigest()


def settings_snapshot():
    return {"revision": revision(), "values": current_setting_values(),
            "fields": [{k: v for k, v in asdict(f).items() if k != "getter"}
                       | {"advanced": is_raw_timing_field(f.key)}
                       for f in SETTINGS],
            "themes": [asdict(t) for t in THEMES.values()]}


@calibration_locked
def save_settings(values, expected_revision):
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
            if not math.isfinite(number) or number < 0 or number > 10000000:
                raise ValueError(f"{f.label} must be a finite, non-negative number")
            if f.kind == "int" and not number.is_integer():
                raise ValueError(f"{f.label} must be a whole number")
        if f.kind == "int_pair":
            lo, hi = parse_int_pair(str(raw))
            if not 0 <= lo <= hi <= 60000:
                raise ValueError(f"{f.label}: use two ordered values between 0 and 60000")
        if f.kind not in ("bool", "choice", "int", "float", "int_pair"):
            if not isinstance(raw, str) or len(raw) > 500 or "\n" in raw:
                raise ValueError(f"Invalid {f.label}")
    save_settings_from_gui(complete)
    return settings_snapshot()
