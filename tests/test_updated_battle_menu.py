import unittest
from unittest.mock import MagicMock, patch
import cv2
import numpy as np
from coc_bot.vision.battle_menu import direct_match_button, army_confirmation_button, battlefield_ready, reward_continue_button
from coc_bot.attack.navigator import AttackNavigator
from coc_bot.config import load_config
from coc_bot.vision.screens import ScreenClassifier, ScreenType, BotMode


class UpdatedMenuTests(unittest.TestCase):
    def frame(self, scale=1):
        frame = np.zeros((int(1048*scale), int(1853*scale), 3), np.uint8)
        cv2.rectangle(frame, (int(108*scale),int(711*scale)),
                      (int(527*scale),int(843*scale)), (0,170,255), -1)
        return frame

    def test_requires_multiplayer_and_find_match_not_color_alone(self):
        for labels in ((None,None), ('singleplayer','findamatch'), ('multiplayer','jointournament')):
            with patch('coc_bot.vision.battle_menu.read_short_label', side_effect=labels):
                self.assertIsNone(direct_match_button(self.frame()))
        with patch('coc_bot.vision.battle_menu.read_short_label', side_effect=['multiplayer','findamatch']):
            self.assertEqual(direct_match_button(self.frame()), (318,775))

    def test_button_coordinates_scale_with_frame(self):
        with patch('coc_bot.vision.battle_menu.read_short_label', side_effect=['multiplayer','findamatch']):
            x,y = direct_match_button(self.frame(.5))
        self.assertLess(abs(x-159),2)
        self.assertLess(abs(y-388),2)

    def navigator(self, direct=False):
        config = load_config()
        config.farm_direct_search = direct
        nav = AttackNavigator(config, MagicMock(), MagicMock())
        nav.capture.screenshot.return_value=self.frame()
        nav._sleep=MagicMock(return_value=False)
        nav._tap_named=MagicMock(return_value=True)
        return nav

    def test_direct_search_taps_once_even_with_stale_second_point(self):
        nav=self.navigator()
        nav.config.tap_points['find_match']=[1645,930]
        nav.classifier.find_direct_match_button=MagicMock(return_value=(318,775))
        self.assertTrue(nav.start_unranked_battle())
        nav.input.tap.assert_called_once_with(318,775,jitter=0)
        nav._tap_named.assert_not_called()
        nav.capture.screenshot.assert_called_once()

    def test_chat_anchor_is_closed_before_accepting_a_false_attack_chip(self):
        nav=self.navigator()
        nav.donation_nav=MagicMock()
        nav.classifier.find_reload_game_button=MagicMock(return_value=None)
        nav.classifier.auxiliary_page=MagicMock(return_value=None)
        nav.classifier._clan_chat_anchor_visible=MagicMock(side_effect=[True,False])
        nav.attack_button_visible=MagicMock(return_value=True)
        self.assertTrue(nav.leave_chat_for_home(timeout=2))
        nav.donation_nav.close_clan_chat.assert_called_once()

    def test_attack_candidates_are_blocked_when_confirmed_chat_does_not_close(self):
        nav=self.navigator()
        nav.donation_nav=MagicMock()
        nav.classifier._clan_chat_anchor_visible=MagicMock(return_value=True)
        self.assertFalse(nav.open_attack_menu())
        nav.donation_nav.close_clan_chat.assert_called_once()
        nav.input.tap.assert_not_called()

    def test_calibrated_direct_flow_still_skips_second_tap_when_ocr_is_unavailable(self):
        nav=self.navigator(True)
        nav.config.tap_points['find_match']=[1645,930]
        nav.classifier.find_direct_match_button=MagicMock(return_value=None)
        self.assertTrue(nav.start_unranked_battle())
        self.assertEqual([c.args[0] for c in nav._tap_named.call_args_list], ['unranked_battle'])

    def test_legacy_two_step_flow_remains_available(self):
        nav=self.navigator()
        nav.config.tap_points['find_match']=[1645,930]
        nav.classifier.find_direct_match_button=MagicMock(return_value=None)
        self.assertTrue(nav.start_unranked_battle())
        self.assertEqual([c.args[0] for c in nav._tap_named.call_args_list], ['unranked_battle','find_match'])

    def test_stop_before_search_never_taps(self):
        nav=self.navigator(True)
        nav.stop_check=lambda:True
        self.assertFalse(nav.start_unranked_battle())
        nav.input.tap.assert_not_called()
        nav._tap_named.assert_not_called()

    def test_strong_menu_anchors_win_over_battle_heuristics(self):
        classifier=ScreenClassifier(load_config())
        with patch.object(classifier,'find_reload_game_button',return_value=None), \
                patch.object(classifier,'auxiliary_page',return_value=None), \
                patch.object(classifier,'_template_visible',return_value=False), \
                patch.object(classifier,'find_direct_match_button',return_value=(318,775)):
            for mode in (BotMode.HOME,BotMode.ATTACK,BotMode.ANY):
                self.assertEqual(classifier.classify(self.frame(),mode),ScreenType.ATTACK_MENU)

    def test_donation_panel_is_not_an_attack_menu_even_with_green_buttons(self):
        nav=self.navigator()
        nav.classifier.find_direct_match_button=MagicMock(return_value=None)
        nav.classifier.is_donation_panel=MagicMock(return_value=True)
        self.assertFalse(nav._attack_menu_open(self.frame(),had_attack_chip=True))

    def test_chat_is_not_an_attack_menu_when_legacy_heuristic_is_loose(self):
        nav=self.navigator()
        nav.classifier.find_direct_match_button=MagicMock(return_value=None)
        nav.classifier.is_donation_panel=MagicMock(return_value=False)
        nav.classifier.classify=MagicMock(return_value=ScreenType.CLAN_CHAT)
        self.assertFalse(nav._attack_menu_open(self.frame(),had_attack_chip=True))

    def test_visible_build_control_vetoes_false_live_replay(self):
        classifier=ScreenClassifier(load_config())
        with patch.object(classifier,'live_replay_watch_armed',return_value=True), \
                patch('coc_bot.vision.battle_menu.home_build_control_visible',return_value=True):
            self.assertFalse(classifier.looks_like_live_replay(self.frame()))

    def test_verified_multiplayer_menu_is_never_a_surrender_dialog(self):
        classifier=ScreenClassifier(load_config())
        with patch.object(classifier,'find_direct_match_button',return_value=(318,775)):
            self.assertFalse(classifier.looks_like_surrender_dialog(self.frame()))

    def test_army_confirmation_requires_headers_and_attack_not_green_alone(self):
        frame=self.frame()
        cv2.rectangle(frame,(1450,900),(1810,980),(40,220,100),-1)
        with patch('coc_bot.vision.battle_menu._white_label',side_effect=['myarmy','cookbook','attack']):
            self.assertEqual(army_confirmation_button(frame),(1638,932))
        for labels in (['home'], ['myarmy','other'], ['myarmy','cookbook','save']):
            with patch('coc_bot.vision.battle_menu._white_label',side_effect=labels):
                self.assertIsNone(army_confirmation_button(frame))

    def test_deploy_gate_requires_both_scout_labels(self):
        for labels in (['attack'], ['endbattle','save','','',''], ['endbattle','','','',''], ['endbattle','next'], ['surrender','','battleendsin']):
            with patch('coc_bot.vision.battle_menu._white_label',side_effect=labels):
                self.assertEqual(battlefield_ready(self.frame()),labels in (['endbattle','next'],['surrender','','battleendsin']))

    def test_countdown_title_retry_excludes_adjacent_defender_labels(self):
        with patch('coc_bot.vision.battle_menu._white_label',
                   side_effect=['endbattie','','babtleendsin','battleendsiin']):
            self.assertTrue(battlefield_ready(self.frame()))

    def test_observed_bold_font_errors_still_require_two_battle_labels(self):
        from coc_bot.vision.battle_menu import active_battle_ready
        with patch('coc_bot.vision.battle_menu._white_label',
                   side_effect=['surreender','','battleendsin']):
            self.assertTrue(battlefield_ready(self.frame()))
        with patch('coc_bot.vision.battle_menu._white_label',
                   side_effect=['battleendsin','qveralldamage']):
            self.assertTrue(active_battle_ready(self.frame()))
        with patch('coc_bot.vision.battle_menu._white_label',
                   side_effect=['surreender','','','','']):
            self.assertFalse(battlefield_ready(self.frame()))

    def test_end_battle_and_damage_are_independent_active_battle_anchors(self):
        with patch('coc_bot.vision.battle_menu._white_label',
                   side_effect=['endbattie','','unreadable','unreadable','overalldamage']):
            self.assertTrue(battlefield_ready(self.frame()))
        with patch('coc_bot.vision.battle_menu._white_label',return_value='overalldamage'):
            self.assertFalse(battlefield_ready(self.frame()))

    def test_army_confirmation_is_tapped_before_accepting_opponent(self):
        nav=self.navigator(True)
        nav.classify=MagicMock(return_value=ScreenType.HOME)
        nav.battlefield_ready=MagicMock(return_value=True)
        with patch('coc_bot.vision.battle_menu.army_confirmation_button',side_effect=[(1638,932),None]), \
             patch.object(nav.classifier,'find_reload_game_button',return_value=None):
            self.assertTrue(nav.wait_for_battle(timeout=5))
        nav.input.tap.assert_called_once_with(1638,932,jitter=0)
        nav.battlefield_ready.assert_called_once()

    def test_weak_battle_classification_cannot_authorize_deployment(self):
        nav=self.navigator(True)
        nav.classify=MagicMock(return_value=ScreenType.BATTLE)
        nav.classifier._looks_like_battle=MagicMock(return_value=True)
        nav.battlefield_ready=MagicMock(return_value=False)
        with patch.object(nav.classifier,'find_reload_game_button',return_value=None):
            self.assertFalse(nav.wait_for_battle(timeout=0))
        nav.input.tap.assert_not_called()

    def reward_frame(self):
        frame=self.frame()
        frame[:]=(40,90,150)
        cv2.rectangle(frame,(800,905),(1090,995),(40,220,100),-1)
        return frame

    def test_resource_rewards_require_known_title_and_continue(self):
        frame=self.reward_frame()
        for labels in (['shop'],['capitalgold','buy'],['capitalgold','continue'],
                       ['darkelixir','continue'],['ddrkelixir','continue'],['gold','continue'],['elixir','continue']):
            with patch('coc_bot.vision.battle_menu._white_label',side_effect=labels):
                target=reward_continue_button(frame)
                self.assertEqual(target is not None,len(labels)==2 and labels[1]=='continue')

    def test_resource_title_and_green_button_without_reward_backdrop_are_rejected(self):
        frame=self.frame()
        cv2.rectangle(frame,(800,905),(1090,995),(40,220,100),-1)
        with patch('coc_bot.vision.battle_menu._white_label',return_value='darkelixir') as ocr:
            self.assertIsNone(reward_continue_button(frame))
            ocr.assert_not_called()

    def test_each_reward_is_cleared_before_home_confirmation(self):
        nav=self.navigator()
        nav.donation_nav=MagicMock()
        nav.classifier._clan_chat_anchor_visible=MagicMock(return_value=True)
        with patch('coc_bot.vision.battle_menu.reward_continue_button',side_effect=[(941,945),(941,945),None]):
            self.assertEqual(nav._confirm_leave_via_clan_chat(timeout=5),'confirmed')
        self.assertEqual(nav.input.tap.call_count,2)
        nav.donation_nav._open_clan_chat.assert_not_called()

    def test_stop_during_reward_recognition_prevents_continue_tap(self):
        nav=self.navigator()
        nav.donation_nav=MagicMock()
        nav.stop_check=MagicMock(side_effect=[False,True])
        with patch('coc_bot.vision.battle_menu.reward_continue_button',return_value=(941,945)):
            self.assertEqual(nav._confirm_leave_via_clan_chat(timeout=5),'stopped')
        nav.input.tap.assert_not_called()
