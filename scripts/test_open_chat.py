#!/usr/bin/env python3
"""Test opening clan chat from the home screen using calibrated tap point/template."""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from coc_bot.adb.capture import ScreenCapture
from coc_bot.adb.client import AdbClient
from coc_bot.adb.input import InputController
from coc_bot.config import load_config
from coc_bot.donation.navigator import Navigator
from coc_bot.vision.matcher import TemplateMatcher
from coc_bot.vision.screens import ScreenClassifier


def main() -> None:
    config = load_config()
    if not config.calibrated:
        print("Run calibration first.")
        sys.exit(1)

    client = AdbClient(device=config.adb_device)
    client.ensure_connected()
    capture = ScreenCapture(client)
    inp = InputController(client, dry_run=False)
    matcher = TemplateMatcher(threshold=config.template_threshold)
    classifier = ScreenClassifier(config, matcher)
    nav = Navigator(config, capture, inp, matcher)

    print("Make sure CoC is on the HOME/village screen.")
    input("Press Enter to test open chat...")

    frame = capture.screenshot()
    screen = classifier.classify(frame)
    print(f"Screen before: {screen.value}")

    if config.tap_points.get("open_chat"):
        print(f"Using tap point: {config.tap_points['open_chat']}")
    elif config.templates.get("open_chat"):
        print(f"Using template: {config.templates['open_chat']}")
    else:
        print("WARNING: No open_chat calibration — will use fallback position")

    nav._open_clan_chat(frame)
    time.sleep(1.5)

    frame = capture.screenshot()
    screen = classifier.classify(frame)
    print(f"Screen after:  {screen.value}")

    if screen.value == "clan_chat":
        print("SUCCESS — clan chat opened.")
    else:
        print("FAILED — chat did not open. Recalibrate open_chat on the HOME screen (Step 1).")
        sys.exit(1)


if __name__ == "__main__":
    main()
