from unittest import TestCase
from unittest.mock import Mock, patch
import numpy as np

from coc_bot.bot import DonationBot
from coc_bot.config import load_config
from coc_bot.donation.navigator import Navigator
from coc_bot.vision.matcher import MatchResult
from coc_bot.vision.screens import ScreenClassifier, ScreenType


class GlobalChatTests(TestCase):
    def setUp(self):
        self.frame = np.zeros((1048, 1853, 3), dtype=np.uint8)
        self.config = load_config()
        self.config.tap_points = {'clan_chat_tab': [1084, 289], 'close_chat': [751, 473]}

    def detection(self, arrow_x):
        classifier = ScreenClassifier(self.config, Mock())
        classifier.matcher.find.side_effect = [MatchResult(1050, 245, .96, 69, 89),
                                               MatchResult(arrow_x-47, 395, .99, 95, 157)]
        with patch.object(classifier, '_load', return_value=np.ones((10, 10, 3), dtype=np.uint8)):
            return classifier._global_conversation_drawer_visible(self.frame)

    def test_global_conversation_without_title_has_two_expanded_edge_controls(self):
        self.assertTrue(self.detection(1084))

    def test_clan_drawer_or_unrelated_arrow_does_not_count_as_global(self):
        self.assertFalse(self.detection(751))

    def test_missing_calibration_is_not_guessed(self):
        self.config.tap_points.pop('clan_chat_tab')
        self.assertFalse(ScreenClassifier(self.config)._global_conversation_drawer_visible(self.frame))

    def test_scan_does_not_accept_global_chat_as_ready_for_donation(self):
        bot = Mock()
        bot.navigator.classify.return_value = ScreenType.CLAN_CHAT
        bot.navigator.classifier.is_global_chat.return_value = True
        bot.navigator.ensure_clan_chat.return_value = False
        self.assertFalse(DonationBot._ensure_chat_open(bot, self.frame))
        bot.navigator.ensure_clan_chat.assert_called_once()

    def test_closing_global_switches_to_clan_instead_of_tapping_old_arrow(self):
        controls = Mock()
        navigator = Navigator(self.config, Mock(), controls)
        navigator.classifier.is_global_chat = Mock(return_value=True)
        self.assertTrue(navigator.close_clan_chat(self.frame))
        controls.tap.assert_called_once_with(1084, 289, jitter=0)
