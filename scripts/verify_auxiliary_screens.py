#!/usr/bin/env python3
"""Offline Shop / Clash Pass recognition and recovery tests; never connects ADB.

Optional: --tasks <reviewed Label Studio screen export> --data-dir <data>
tests the reviewed screenshots in addition to the self-contained tests.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlparse
from unittest.mock import Mock

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from coc_bot.auxiliary_recovery import AuxiliaryRecovery
from coc_bot.attack.navigator import AttackNavigator
from coc_bot.config import load_config
from coc_bot.donation.navigator import Navigator
from coc_bot.vision.auxiliary import AuxiliaryPageDetector
from coc_bot.vision.screens import BotMode, ScreenClassifier, ScreenType


def synthetic_page(screen):
    frame = np.zeros((540, 960, 3), dtype=np.uint8)
    positions = (
        (("shop_build", 171, 26), ("shop_army", 255, 27), ("shop_close", 901, 19))
        if screen == "shop" else
        (("pass_rewards", 416, 21), ("pass_bank", 803, 21), ("pass_close", 905, 21))
    )
    for name, x, y in positions:
        icon = cv2.imread(str(ROOT / "src/coc_bot/vision/assets" / f"{name}.png"))
        assert icon is not None, name
        h, w = icon.shape[:2]
        frame[y:y + h, x:x + w] = icon
    return frame


def verify_recovery(frame, config):
    classifier = ScreenClassifier(config)
    target = classifier.auxiliary_page(frame)
    assert target is not None and target.close is not None
    inputs = Mock()
    stopped = [False]
    recovery = AuxiliaryRecovery(classifier, inputs, lambda: stopped[0])
    for _ in range(3):
        assert recovery.close(frame)
    assert not recovery.close(frame)
    assert inputs.tap.call_count == 3
    inputs.tap.assert_called_with(*target.close, jitter=0)
    inputs.back.assert_not_called()
    inputs.reset_mock()
    stopped[0] = True
    assert not AuxiliaryRecovery(classifier, inputs, lambda: stopped[0]).close(frame)
    inputs.tap.assert_not_called()
    stopping_during_match = Mock(side_effect=[False, True])
    assert not AuxiliaryRecovery(classifier, inputs, stopping_during_match).close(frame)
    inputs.tap.assert_not_called()
    dim = (frame * 0.4).astype(np.uint8)
    assert classifier.auxiliary_page(dim).close is None
    assert not AuxiliaryRecovery(classifier, inputs, lambda: False).close(dim)
    inputs.tap.assert_not_called()

    home = np.zeros_like(frame)
    chat = np.ones_like(frame)
    capture = Mock()
    capture.screenshot.side_effect = [frame, home, chat]
    nav = Navigator(config, capture, inputs)
    original = nav.classify
    nav.classify = lambda f, mode=None: (
        ScreenType.HOME if f is home else ScreenType.CLAN_CHAT if f is chat else original(f, mode)
    )
    nav._sleep = lambda _: False
    nav.classifier._open_chat_icon_visible = lambda _: True
    nav.classifier._home_attack_chip_visible = lambda _: True
    nav.classifier.is_global_chat = lambda _: False
    nav._open_clan_chat = Mock()
    nav.navigate_to_donation_requests = Mock()
    assert nav.ensure_clan_chat(timeout=2)
    inputs.tap.assert_called_once_with(*target.close, jitter=0)
    nav._open_clan_chat.assert_called_once_with(home)
    nav.navigate_to_donation_requests.assert_called_once_with(chat, None)

    inputs.reset_mock()
    nav._open_clan_chat.reset_mock()
    capture.screenshot.side_effect = None
    capture.screenshot.return_value = frame
    assert not nav.ensure_clan_chat(timeout=2)
    assert inputs.tap.call_count == 3
    nav._open_clan_chat.assert_not_called()

    # Farm readiness must not override a recognized page, even when the old
    # Attack! heuristic falsely reports the chip beneath that page.
    inputs.reset_mock()
    capture.screenshot.side_effect = [frame, home]
    attack = AttackNavigator(config, capture, inputs, donation_navigator=nav)
    attack._sleep = lambda _: False
    attack.attack_button_visible = Mock(return_value=True)
    assert attack.leave_chat_for_home(timeout=2)
    inputs.tap.assert_called_once_with(*target.close, jitter=0)
    attack.attack_button_visible.assert_called_once_with(home)

    inputs.reset_mock()
    capture.screenshot.side_effect = [frame, home]
    attack.classify = lambda f, mode=None: (
        ScreenType.HOME if f is home else ScreenType(target.screen)
    )
    attack._village_home_anchors_visible = lambda _: True
    attack.classifier.looks_like_blocking_popup = lambda _: False
    attack._confirm_leave_via_clan_chat = Mock(return_value="confirmed")
    assert attack.return_home_from_attack()
    inputs.tap.assert_called_once_with(*target.close, jitter=0)
    attack._confirm_leave_via_clan_chat.assert_called_once()

    inputs.reset_mock()
    capture.screenshot.side_effect = [frame, chat]
    attack = AttackNavigator(config, capture, inputs, donation_navigator=nav)
    attack._sleep = lambda _: False
    attack.classifier._clan_chat_anchor_visible = Mock(return_value=True)
    assert attack._confirm_leave_via_clan_chat(timeout=2) == "confirmed"
    inputs.tap.assert_called_once_with(*target.close, jitter=0)
    attack.classifier._clan_chat_anchor_visible.assert_called_once_with(chat)


def verify_dataset(tasks_path, data_dir):
    tasks = json.loads(tasks_path.read_text(encoding="utf-8"))
    counts = {"frames": 0, "shop": 0, "clash_pass": 0, "blocked": 0}
    detector = AuxiliaryPageDetector()
    for task in tasks:
        relative = parse_qs(urlparse(task["data"]["image"]).query)["d"][0]
        path = (data_dir / relative).resolve()
        assert path.is_relative_to(data_dir.resolve()), path
        frame = cv2.imread(str(path))
        assert frame is not None, path
        label = next(
            r["value"]["choices"][0]
            for r in task["annotations"][0]["result"] if r["type"] == "choices"
        )
        # Older schema called the reviewed Pass Rewards page "other". This
        # override is explicit in the new export; do not infer labels from
        # the detector's own answer.
        expected = label if label in ("shop", "clash_pass") else None
        for size in (None, (1280, 720), (1920, 1080)):
            sample = frame if size is None else cv2.resize(frame, size)
            page = detector.detect(sample)
            if expected:
                assert page and page.screen == expected and page.close, (path, size, page)
            else:
                assert page is None or page.close is None, ("Unsafe false positive", path, size, page)
        counts["frames"] += 1
        if expected:
            counts[expected] += 1
        elif page:
            counts["blocked"] += 1
    print("Reviewed corpus:", counts, "(each checked at 3 resolutions)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=Path)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    args = parser.parse_args()
    config = load_config()
    config.templates = {}
    detector = AuxiliaryPageDetector()
    for screen in ("shop", "clash_pass"):
        frame = synthetic_page(screen)
        for mode in BotMode:
            assert ScreenClassifier(config).classify(frame, mode) == ScreenType(screen)
        verify_recovery(frame, config)
        # A red X alone, or one matching header, must never authorize a tap.
        partial = frame.copy()
        partial[:, :600] = 0
        assert detector.detect(partial) is None
        assert detector.detect(np.zeros_like(frame)) is None
    if args.tasks:
        verify_dataset(args.tasks, args.data_dir)
    print("verify_auxiliary_screens: OK (no ADB calls)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
