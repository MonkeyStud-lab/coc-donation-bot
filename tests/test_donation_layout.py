"""Automatic donation geometry must never authorize stale or gem-mode taps."""
import copy
from unittest import TestCase
from unittest.mock import Mock, patch

import cv2
import numpy as np

from coc_bot.config import load_config
from coc_bot.donation.executor import DonationExecutor
from coc_bot.donation.inventory import InventoryParser
from coc_bot.donation.layout import DonationLayout, DonationLayoutSession
from test_donation_calibration import panel


def colored_panel():
    frame = panel()
    # Two eligible troop cards; all other cells remain featureless/disabled.
    for x in (760, 890):
        cv2.rectangle(frame, (x, 260), (x+100, 400), (180, 65, 100), -1)
        cv2.rectangle(frame, (x+20, 300), (x+70, 360), (240, 240, 240), -1)
    return frame


class AutomaticDonationLayout(TestCase):
    def setUp(self):
        self.frame = colored_panel()
        self.config = load_config()
        self.config.rois = {}
        self.config.grid = {}
        self.config.tap_points = {}
        self.config.templates = {}
        self.config.colors = {}
        self.parser = InventoryParser(self.config)
        self.parser.layout_session = DonationLayoutSession(DonationLayout.detect(self.frame))

    def executor(self):
        executor = DonationExecutor(self.config, Mock(), Mock())
        executor.inventory_parser = self.parser
        executor.capture.screenshot.return_value = self.frame.copy()
        return executor

    def test_slots_and_swipe_without_saved_grid_or_colors(self):
        before = copy.deepcopy((self.config.rois, self.config.grid, self.config.tap_points))
        slots = self.parser.parse_slots(self.frame, identify=False)
        self.assertEqual(len(slots), 2)
        for slot, xmin, xmax in zip(slots, (753, 883), (883, 1013)):
            self.assertTrue(xmin <= slot.center[0] <= xmax)
            self.assertTrue(252 <= slot.center[1] <= 415)
        line = self.parser.bar_swipe_line(self.frame, 'donation_troop_bar')
        self.assertTrue(753 < line[2] < line[0] < 1666)
        self.assertEqual(before, (self.config.rois, self.config.grid, self.config.tap_points))

    def test_changed_resolution_or_position_invalidates_session(self):
        shifted = cv2.warpAffine(self.frame, np.float32([[1, 0, -90], [0, 1, 0]]), (1853, 1048))
        for changed in (shifted, cv2.resize(self.frame, (1280, 724))):
            session = DonationLayoutSession(DonationLayout.detect(self.frame))
            self.assertIsNone(session.observe(changed))
            self.assertIsNone(session.observe(self.frame))

    def test_missing_panel_never_uses_calibration_mid_request(self):
        self.config.rois['donation_troop_bar'] = [0, 0, 1, 1]
        self.config.grid['troop_bar'] = {'cols': 1, 'rows': 1}
        other = np.full_like(self.frame, (200, 20, 130))
        self.assertEqual(self.parser.parse_bar_slots(other, 'donation_troop_bar'), [])
        self.assertIsNone(self.parser.bar_swipe_line(self.frame, 'donation_troop_bar'))
        self.assertEqual(self.parser.parse_bar_slots(self.frame, 'donation_troop_bar'), [])

    def test_new_session_at_resized_translated_panel_works(self):
        shifted = cv2.warpAffine(self.frame, np.float32([[1, 0, -90], [0, 1, -20]]), (1853, 1048))
        frame = cv2.resize(shifted, (1280, 724))
        self.parser.layout_session = DonationLayoutSession(DonationLayout.detect(frame))
        slots = self.parser.parse_slots(frame, identify=False)
        self.assertEqual(len(slots), 2)
        self.assertTrue(all(450 < s.center[0] < 650 and 200 < s.center[1] < 240 for s in slots))

    def test_entry_requires_two_agreeing_frames(self):
        executor = self.executor()
        self.assertTrue(executor._prepare_layout(self.frame))
        self.assertIsNotNone(self.parser.layout_session)
        executor.capture.screenshot.return_value = np.zeros_like(self.frame)
        self.assertFalse(executor._prepare_layout(self.frame))
        self.assertIsNone(self.parser.layout_session)
        executor.input.tap.assert_not_called()

    def test_unsupported_entry_retains_calibrated_path(self):
        executor = self.executor()
        self.assertTrue(executor._prepare_layout(np.zeros_like(self.frame)))
        self.assertIsNone(self.parser.layout_session)
        executor.capture.screenshot.assert_not_called()
        self.config.rois['donation_troop_bar'] = [753/1853, 252/1048, 913/1853, 327/1048]
        self.config.grid['troop_bar'] = {'cols': 7, 'rows': 2}
        self.assertEqual(len(self.parser.parse_bar_slots(self.frame, 'donation_troop_bar', identify=False)), 2)

    def test_geometry_does_not_replace_elixir_state_confirmation(self):
        executor = self.executor()
        self.assertFalse(executor._ensure_elixir_resource())
        executor.input.tap.assert_not_called()

    def test_automatic_elixir_button_without_saved_tap_coordinates(self):
        executor = self.executor()
        self.config.templates['donation_elixir_selected'] = 'selected.png'
        self.config.rois['donation_elixir_selected'] = [.6, .1, .1, .1]
        self.config.frame_width = self.config.frame_height = 0
        with patch('coc_bot.donation.resource_mode.elixir_is_selected', side_effect=[False, True]), \
                patch('coc_bot.donation.executor.interrupted_sleep', return_value=False):
            self.assertTrue(executor._ensure_elixir_resource())
        executor.input.tap.assert_called_once_with(*self.parser.layout_session.layout.elixir_center, jitter=0)

    def test_panel_closes_after_first_tap_no_second_tap(self):
        executor = self.executor()
        slots = self.parser.parse_slots(self.frame, identify=False)
        executor.capture.screenshot.side_effect = [self.frame.copy(), np.zeros_like(self.frame)]
        with patch('coc_bot.donation.resource_mode.elixir_is_selected', return_value=True), \
                patch('coc_bot.donation.executor.interrupted_sleep', return_value=False):
            self.assertTrue(executor._tap_colored_slots(slots))
        executor.input.tap.assert_called_once_with(*slots[0].center, jitter=0)
        self.assertFalse(self.parser.layout_session.valid)

    def test_gem_mode_stops_before_next_tap(self):
        executor = self.executor()
        slots = self.parser.parse_slots(self.frame, identify=False)
        with patch('coc_bot.donation.resource_mode.elixir_is_selected', side_effect=[True, False]), \
                patch('coc_bot.donation.executor.interrupted_sleep', return_value=False):
            self.assertTrue(executor._tap_colored_slots(slots))
        self.assertEqual(executor.input.tap.call_count, 1)
        self.assertFalse(self.parser.layout_session.valid)

    def test_no_longer_colored_slot_is_not_tapped(self):
        executor = self.executor()
        slots = self.parser.parse_slots(self.frame, identify=False)
        executor.capture.screenshot.return_value = panel()
        with patch('coc_bot.donation.resource_mode.elixir_is_selected', return_value=True):
            self.assertFalse(executor._tap_colored_slots(slots))
        executor.input.tap.assert_not_called()

    def test_stop_arriving_during_capture_prevents_tap(self):
        executor = self.executor()
        slots = self.parser.parse_slots(self.frame, identify=False)
        stopped = [False]
        executor.stop_check = lambda: stopped[0]
        def capture():
            stopped[0] = True
            return self.frame
        executor.capture.screenshot.side_effect = capture
        self.assertFalse(executor._tap_colored_slots(slots))
        executor.input.tap.assert_not_called()

    def test_complete_request_rechecks_after_each_tap_without_grid_calibration(self):
        executor = self.executor()
        self.config.templates['donation_elixir_selected'] = 'selected.png'
        self.config.rois['donation_elixir_selected'] = [.6, .1, .1, .1]
        self.config.bar_max_scroll_attempts = 0
        self.config.spell_bar_max_scroll_attempts = 0
        current = [self.frame.copy()]
        executor.capture.screenshot.side_effect = lambda: current[0].copy()
        executor._finish_donation = Mock()
        def tap(x, y, **kwargs):
            if executor.input.tap.call_count == 1:
                current[0][252:415, 753:883] = 230
            else:
                current[0] = np.zeros_like(self.frame)
        executor.input.tap.side_effect = tap
        before = copy.deepcopy((self.config.rois, self.config.grid, self.config.tap_points))
        with patch('coc_bot.donation.resource_mode.elixir_is_selected', return_value=True), \
                patch('coc_bot.donation.executor.interrupted_sleep', return_value=False):
            self.assertTrue(executor.donate_for_request())
        self.assertEqual(executor.input.tap.call_count, 2)
        executor.input.swipe.assert_not_called()
        self.assertFalse(self.parser.layout_session.valid)
        self.assertEqual(before, (self.config.rois, self.config.grid, self.config.tap_points))
