#!/usr/bin/env python3
"""
Live Waydroid end-to-end farm verify.

Prerequisites:
  - Waydroid + Clash running, ADB connected
  - Calibration → Farm completed
  - Electro dragon army as the active preset
  - Prefer a quiet moment (bot stopped)

Usage:
  python scripts/verify_farm_live.py           # full attack
  python scripts/verify_farm_live.py --dry-nav # only open Attack menu, then stop
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from loguru import logger  # noqa: E402

from coc_bot.adb.capture import ScreenCapture  # noqa: E402
from coc_bot.adb.client import AdbClient  # noqa: E402
from coc_bot.adb.input import InputController  # noqa: E402
from coc_bot.attack.farmer import AttackFarmer  # noqa: E402
from coc_bot.attack.navigator import AttackNavigator  # noqa: E402
from coc_bot.config import load_config  # noqa: E402
from coc_bot.donation.navigator import Navigator  # noqa: E402
from coc_bot.logging_utils import setup_logging  # noqa: E402
from coc_bot.runtime.tracker import RuntimeTracker  # noqa: E402
from coc_bot.vision.matcher import TemplateMatcher  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Live farm attack verify")
    parser.add_argument(
        "--dry-nav",
        action="store_true",
        help="Only leave chat and open Attack menu (no match / deploy)",
    )
    args = parser.parse_args()
    setup_logging(debug=True, log_file=ROOT / "data" / "bot.log")

    config = load_config()
    if not config.farm_calibrated:
        logger.error("Farm not calibrated. Run: python scripts/calibrate.py --step farm")
        return 1

    client = AdbClient(device=config.adb_device)
    client.health_check()
    capture = ScreenCapture(client)
    inp = InputController(
        client,
        jitter_px=config.tap_jitter_px,
        delay_ms=config.action_delay_ms,
        dry_run=False,
    )
    matcher = TemplateMatcher(
        threshold=config.template_threshold,
        scale_range=config.scale_range,
    )
    donation_nav = Navigator(config, capture, inp, matcher)
    attack_nav = AttackNavigator(config, capture, inp, matcher, donation_nav)

    if args.dry_nav:
        if not attack_nav.leave_chat_for_home():
            logger.error("Failed to reach home")
            return 1
        if not attack_nav.open_attack_menu():
            logger.error("Failed to open Attack menu")
            return 1
        logger.info("dry-nav OK — Attack menu opened. Close it manually.")
        return 0

    logger.info("Starting full farm verify (unranked Battle + edge deploy + wait)")
    result = AttackFarmer(config, capture, inp, matcher, donation_nav).run_one_attack()
    if result.success:
        RuntimeTracker(config).mark_farm_success()
        logger.info("verify_farm_live: SUCCESS")
        return 0
    logger.error("verify_farm_live: FAILED — {}", result.reason)
    time.sleep(0.5)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
