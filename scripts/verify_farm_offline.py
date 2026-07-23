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
from coc_bot.config import load_config  # noqa: E402
from coc_bot.gui.settings_fields import SETTINGS  # noqa: E402
from coc_bot.vision.screens import ScreenType  # noqa: E402


def main() -> int:
    config = load_config()
    assert hasattr(config, "farm_enabled")
    assert config.farm_interval_seconds >= 60
    assert config.farm_deploy_side in ("left", "right")
    assert config.farm_match_timeout_seconds > 0
    assert config.farm_battle_timeout_seconds >= 180
    assert config.farm_edrag_deploy_taps >= 11
    assert 0 <= config.farm_hero_count <= 4

    for name in ("ATTACK_MENU", "MATCHMAKING", "BATTLE", "BATTLE_RESULTS"):
        assert hasattr(ScreenType, name), name

    assert "farm" in STEP_IDS
    assert "farm" in STEPS

    farm_keys = {f.key for f in SETTINGS if f.section == "Farm"}
    assert "farm_enabled" in farm_keys
    assert "farm_deploy_side" in farm_keys

    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    deployer = EdgeDeployer(config, input_ctrl=None)  # type: ignore[arg-type]
    left = deployer.deploy_points(frame, side="left")
    right = deployer.deploy_points(frame, side="right")
    assert len(left) >= 8 and len(right) >= 8
    assert all(p[0] < frame.shape[1] * 0.2 for p in left)
    assert all(p[0] > frame.shape[1] * 0.8 for p in right)

    rage = deployer.rage_drop_points(frame, left, side="left")
    assert len(rage) == config.farm_rage_count
    assert all(r[0] > left[0][0] for r in rage), "rage should sit right of left-edge troops"

    print("verify_farm_offline: OK")
    print(f"  farm_enabled={config.farm_enabled} farm_calibrated={config.farm_calibrated}")
    print(f"  deploy points left={len(left)} right={len(right)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
