#!/usr/bin/env python3
"""Offline sanity checks for elixir farm (no ADB / Waydroid required)."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from coc_bot.attack.deployer import EdgeDeployer  # noqa: E402
from coc_bot.calibration.wizard import STEP_IDS, STEPS  # noqa: E402
from coc_bot.config import load_config, normalize_farm_deploy_sequence  # noqa: E402
from coc_bot.gui.settings_fields import SETTINGS  # noqa: E402
from coc_bot.vision.screens import ScreenType  # noqa: E402


def main() -> int:
    config = load_config()
    assert hasattr(config, "farm_enabled")
    assert config.farm_interval_seconds >= 60
    assert config.farm_interval_variance_seconds >= 0
    assert config.farm_deploy_side in ("left", "right")
    assert config.farm_match_timeout_seconds > 0
    assert config.farm_battle_timeout_seconds >= 180

    for name in ("ATTACK_MENU", "MATCHMAKING", "BATTLE", "BATTLE_RESULTS"):
        assert hasattr(ScreenType, name), name

    assert "farm" in STEP_IDS
    assert "farm" in STEPS

    farm_keys = {f.key for f in SETTINGS if f.section == "Farm"}
    assert "farm_enabled" in farm_keys
    assert "farm_deploy_side" in farm_keys
    assert "farm_edrag_deploy_taps" not in farm_keys
    assert "farm_deploy_siege" not in farm_keys

    side_field = next(f for f in SETTINGS if f.key == "farm_deploy_side")
    assert side_field.kind == "choice" and side_field.choices == ("left", "right")
    theme_field = next(f for f in SETTINGS if f.key == "gui_theme")
    assert theme_field.kind == "choice"
    assert "Modern" in theme_field.choices
    assert "Windows 11" in theme_field.choices
    assert "iOS 26" in theme_field.choices
    assert "Android 17" in theme_field.choices
    assert "Nord" in theme_field.choices
    assert "Ember" in theme_field.choices

    seq = normalize_farm_deploy_sequence(config.farm_deploy_sequence)
    assert "taps" in seq and isinstance(seq["taps"], list)
    assert seq["side"] in ("left", "right")

    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    deployer = EdgeDeployer(config, input_ctrl=None)  # type: ignore[arg-type]
    left = deployer.deploy_points(frame, side="left")
    right = deployer.deploy_points(frame, side="right")
    assert len(left) >= 8 and len(right) >= 8
    assert all(p[0] < frame.shape[1] * 0.2 for p in left)
    assert all(p[0] > frame.shape[1] * 0.8 for p in right)

    print("verify_farm_offline: OK")
    print(f"  farm_enabled={config.farm_enabled} farm_calibrated={config.farm_calibrated}")
    print(f"  deploy sequence taps={len(seq['taps'])}")
    print(f"  deploy points left={len(left)} right={len(right)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
