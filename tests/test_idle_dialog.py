import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from coc_bot.config import load_config
from coc_bot.donation.navigator import Navigator
from coc_bot.vision.idle_dialog import IdleDialogDetector, _anchor
from coc_bot.vision.screens import BotMode, ScreenClassifier, ScreenType


def dialog_frame():
    frame = np.full((724, 1280, 3), 27, dtype=np.uint8)
    for name, x, y in (("idle_title", 380, 290), ("idle_reload", 380, 372)):
        anchor = _anchor(name)
        color = cv2.cvtColor(anchor, cv2.COLOR_GRAY2BGR)
        if name == "idle_reload":
            # Restore the bright cyan action color from the bundled grayscale text.
            text = anchor > 100
            color[text] = (245, 229, 145)
        h, w = anchor.shape
        frame[y:y+h, x:x+w] = color
    return frame


class IdleDialogTests(unittest.TestCase):
    def test_scaled_dialog_and_button_coordinates(self):
        frame = dialog_frame()
        baseline = IdleDialogDetector().detect(frame)
        self.assertIsNotNone(baseline)
        for width in (960, 1280, 1853, 1920):
            scale = width / 1280
            resized = cv2.resize(frame, (width, round(724 * scale)))
            found = IdleDialogDetector().detect(resized)
            self.assertIsNotNone(found, width)
            self.assertLess(abs(found[0] - baseline[0] * scale), 3)
            self.assertLess(abs(found[1] - baseline[1] * scale), 3)

    def test_rejects_missing_action_title_dimmed_or_wrong_placement(self):
        for variant in ("title", "action", "dimmed", "misaligned", "empty"):
            frame = dialog_frame()
            if variant == "title":
                frame[290:340, 380:700] = 27
            elif variant == "action":
                frame[370:400, 380:470] = 27
            elif variant == "dimmed":
                frame = (frame * .4).astype(np.uint8)
            elif variant == "misaligned":
                frame[370:400, 600:690] = frame[370:400, 380:470]
                frame[370:400, 380:470] = 27
            else:
                frame[:] = 27
            self.assertIsNone(IdleDialogDetector().detect(frame), variant)

    def test_dialog_wins_over_background_in_all_modes(self):
        classifier = ScreenClassifier(load_config())
        for mode in BotMode:
            with patch.object(classifier, "auxiliary_page", side_effect=AssertionError("background consulted")):
                self.assertEqual(classifier._classify(dialog_frame(), mode), ScreenType.POPUP)

    def test_reload_exact_tap_cooldown_retry_limit_and_stop(self):
        nav = Navigator(load_config(), Mock(), Mock())
        frame = dialog_frame()
        point = nav.classifier.find_reload_game_button(frame)
        with patch("coc_bot.donation.navigator.time.monotonic") as clock, patch.object(ScreenClassifier, "arm_live_replay_watch") as arm:
            clock.return_value = 100
            self.assertTrue(nav._dismiss_popup(frame))
            nav.input.tap.assert_called_once_with(*point, jitter=0)
            arm.assert_called_once()
            clock.return_value = 105
            self.assertIsNone(nav._dismiss_popup(frame))
            self.assertEqual(nav.input.tap.call_count, 1)
            for instant in (111, 122):
                clock.return_value = instant
                self.assertTrue(nav._dismiss_popup(frame))
            clock.return_value = 140
            self.assertFalse(nav._dismiss_popup(frame))
            self.assertEqual(nav.input.tap.call_count, 3)
            nav.stop_check = lambda: True
            clock.return_value = 300
            self.assertFalse(nav._dismiss_popup(frame))
            self.assertEqual(nav.input.tap.call_count, 3)

    def test_stop_arriving_during_recognition_prevents_reload(self):
        nav = Navigator(load_config(), Mock(), Mock())
        stopped = [False]
        nav.stop_check = lambda: stopped[0]
        def recognize(frame):
            stopped[0] = True
            return (415, 381)
        with patch.object(nav.classifier, "find_reload_game_button", side_effect=recognize):
            self.assertFalse(nav._dismiss_popup(dialog_frame()))
        nav.input.tap.assert_not_called()

    def test_chat_recovery_uses_new_frame_after_reload(self):
        capture, inputs = Mock(), Mock()
        nav = Navigator(load_config(), capture, inputs)
        dialog, chat = dialog_frame(), np.zeros((724, 1280, 3), dtype=np.uint8)
        capture.screenshot.side_effect = [dialog, chat]
        with patch.object(nav, "classify", side_effect=[ScreenType.POPUP, ScreenType.CLAN_CHAT]), \
             patch.object(nav, "_sleep", return_value=False), \
             patch.object(nav, "navigate_to_donation_requests") as navigate, \
             patch.object(nav.classifier, "is_global_chat", return_value=False), \
             patch.object(ScreenClassifier, "arm_live_replay_watch"):
            self.assertTrue(nav.ensure_clan_chat(timeout=5))
        navigate.assert_called_once_with(chat, None)
        self.assertEqual(capture.screenshot.call_count, 2)
        inputs.tap.assert_called_once_with(415, 381, jitter=0)


if __name__ == "__main__":
    unittest.main()
