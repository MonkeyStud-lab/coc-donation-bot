"""A visible donation header must beat coarse dark-side results guesses."""
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

import numpy as np

from coc_bot.vision.screens import ScreenClassifier, ScreenType


class DonationResultsPrecedence(TestCase):
    def classifier(self, header):
        result = ScreenClassifier(SimpleNamespace(template_threshold=.82))
        result._template_visible = Mock(side_effect=lambda f, key: header and key == 'donation_panel')
        result.looks_like_live_replay = Mock(return_value=False)
        result._home_attack_chip_visible = Mock(return_value=False)
        result._home_blocking_popup = Mock(return_value=False)
        result._live_battle_chrome_visible = Mock(return_value=False)
        result.find_return_home_button = Mock(return_value=None)
        return result

    def test_dark_edges_without_donation_header_still_indicate_results(self):
        classifier = self.classifier(False)
        self.assertTrue(classifier.looks_like_results_side_silhouettes(np.zeros((540,960,3),np.uint8)))

    def test_header_prevents_direct_silhouette_false_positive_and_recognizes_panel(self):
        frame = np.zeros((540,960,3),np.uint8)
        classifier = self.classifier(True)
        self.assertFalse(classifier.looks_like_results_side_silhouettes(frame))
        self.assertFalse(classifier._looks_like_battle_results(frame))
        self.assertTrue(classifier.is_donation_panel(frame))
        self.assertEqual(classifier._classify_donate(frame), ScreenType.DONATION_PANEL)
        self.assertEqual(classifier._classify_any(frame), ScreenType.DONATION_PANEL)
