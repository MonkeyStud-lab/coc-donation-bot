"""Offline results recognition and farm wait checks; never sends ADB input."""
import argparse
import json
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlparse
from unittest.mock import Mock, patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from coc_bot.adb.capture import ScreenCapture
from coc_bot.attack.navigator import AttackNavigator
from coc_bot.config import load_config
from coc_bot.vision.battle_completion import BattleCompletionDetector
from coc_bot.vision.screens import ScreenType


def results_frame():
    image = np.zeros((540, 960, 3), dtype=np.uint8)
    for name, x, y in (("results_return_home", 444, 444), ("results_troops_expended", 428, 348)):
        anchor = cv2.imread(str(ROOT / "src/coc_bot/vision/assets" / f"{name}.png"))
        h, w = anchor.shape[:2]
        image[y:y+h, x:x+w] = anchor
    return image


def wait_checks(image):
    for scenario in ("confirmed", "transient", "fallback", "stopped", "capture_failed", "slow_capture"):
        config = load_config()
        config.farm_battle_timeout_seconds = 30
        config.tap_points = {"return_home": [123, 456]}
        config.frame_width, config.frame_height = 960, 540
        capture, inputs = Mock(), Mock()
        capture.screenshot.return_value = image
        nav = AttackNavigator(config, capture, inputs)
        clock, stopped = [0.0], [False]
        calls = [0]
        def observe(**kwargs):
            calls[0] += 1
            assert kwargs["timeout_seconds"] <= 3
            if scenario == "slow_capture":
                clock[0] += kwargs["timeout_seconds"]
                return None
            if scenario == "stopped": stopped[0] = True
            if scenario in ("fallback", "capture_failed"): return None
            if scenario == "transient" and calls[0] == 2: return None
            return image
        def sleep(seconds):
            clock[0] += seconds
            return stopped[0]
        capture.observe.side_effect = observe
        nav.stop_check = lambda: stopped[0]
        nav._sleep = sleep
        with patch("coc_bot.attack.navigator.time.monotonic", side_effect=lambda: clock[0]), \
             patch("coc_bot.attack.navigator.time.time", return_value=1000.0):
            end = nav.wait_for_battle_end(since=1000.0)
        inputs.back.assert_not_called()
        if scenario == "stopped":
            assert end == ScreenType.UNKNOWN
            inputs.tap.assert_not_called()
        else:
            assert end == ScreenType.BATTLE_RESULTS
            assert inputs.tap.call_count == 1
            if scenario in ("fallback", "capture_failed", "slow_capture"):
                assert clock[0] == 31.5
                inputs.tap.assert_called_with(123, 456, jitter=0)
                assert nav.last_battle_end_reason == "timer_fallback"
            else:
                assert calls[0] == (4 if scenario == "transient" else 2)
                assert clock[0] < 30
                assert nav.last_battle_end_reason == "results_confirmed"


def capture_checks(image):
    client = Mock()
    capture = ScreenCapture(client)
    assert capture.observe(stop_check=lambda: True) is None
    client.run_shell.assert_not_called()
    def pull(args, **kwargs):
        assert 0 < kwargs["timeout"] <= 3
        assert args[0] == "pull"
        cv2.imwrite(args[2], image)
    client.run.side_effect = pull
    observed = capture.observe()
    assert observed is not None and observed.shape == image.shape
    client.ensure_connected.assert_not_called()
    client.run.side_effect = RuntimeError("unexpected")
    # Known ADB errors are swallowed; unexpected programming errors aren't hidden.
    from coc_bot.adb.client import AdbError
    client.run.side_effect = AdbError("test offline")
    assert capture.observe() is None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=Path)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    args = parser.parse_args()
    detector = BattleCompletionDetector()
    image = results_frame()
    assert detector.detect(image) is not None
    assert detector.detect(np.zeros_like(image)) is None
    green_scenery = np.full_like(image, (30, 150, 20))
    assert detector.detect(green_scenery) is None
    partial = image.copy()
    partial[320:400] = 0
    assert detector.detect(partial) is None
    assert detector.detect((image.astype(float) * .35).astype(np.uint8)) is None
    wait_checks(image)
    capture_checks(image)
    counts = {"positive": 0, "negative": 0}
    if args.tasks:
        for task in json.loads(args.tasks.read_text()):
            choices = [r["value"].get("choices", []) for a in task.get("annotations", [])
                       for r in a.get("result", []) if r.get("from_name") == "screen"]
            expected = ["battle_results"] in choices
            path = args.data_dir / parse_qs(urlparse(task["data"]["image"]).query)["d"][0]
            original = cv2.imread(str(path))
            assert original is not None, path
            for size in ((original.shape[1], original.shape[0]), (1280, 720), (1920, 1080)):
                frame = cv2.resize(original, size)
                target = detector.detect(frame)
                assert bool(target) == expected, (path, size, target, expected)
            counts["positive" if expected else "negative"] += 1
    print("verify_battle_completion: OK", counts,
          "(two-frame confirmation, false-positive vetoes, fallback deadline, Stop, bounded capture)")


if __name__ == "__main__":
    main()
