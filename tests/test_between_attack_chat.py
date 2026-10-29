import tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from coc_bot.donation.chat_check import peek_requests
from coc_bot.bot import DonationBot
from coc_bot.attack.farmer import FarmResult


class BetweenAttackChatTests(unittest.TestCase):
    def test_fleet_checkpoint_verification_failure_uses_normal_loop_recovery(self):
        from coc_bot.config import load_config
        with tempfile.TemporaryDirectory() as root:
            bot=DonationBot.__new__(DonationBot);bot.config=load_config();bot.config.data_dir=Path(root)
            bot._stop_requested=False;bot.should_stop=lambda:False;bot._state='scan_chat'
            bot.client=Mock();bot.break_manager=Mock();bot.tracker=Mock();bot.navigator=Mock();bot.farmer=Mock()
            bot.navigator.ensure_clan_chat.return_value=True;bot.game_state=Mock()
            bot.set_mode=Mock();bot._set_state=Mock();bot._has_donate_request=Mock()
            bot._settings_stop_ready=lambda:False;bot._recover=Mock();bot._loop_tick=Mock()
            bot._fleet_should_yield=Mock(side_effect=[ValueError('Home not verified before clan chat check'),True])
            with patch('coc_bot.attack.recovery.recover_attack'),\
                 patch('coc_bot.attack.recovery.pending',return_value=None),\
                 patch('coc_bot.builder_base.runner.pending',return_value=False),\
                 patch('coc_bot.runtime.screenshot_retention.prune_attack_diagnostics'),\
                 patch('coc_bot.bot.interrupted_sleep',return_value=False):
                bot._run_inner()
            bot._recover.assert_called_once();self.assertEqual(bot._fleet_should_yield.call_count,2)
            bot._loop_tick.assert_not_called();bot.tracker.pause.assert_called_once()

    def test_hidden_request_is_read_after_a_verified_jump(self):
        capture=Mock();nav=Mock();monitor=Mock();request=object()
        nav.classifier._clan_chat_anchor_visible.return_value=True
        monitor.find_donate_request.side_effect=[None,request]
        nav.seek_donation_requests_step.return_value='jump'
        self.assertIs(peek_requests(capture,nav,monitor,lambda:False),request)
        self.assertEqual(capture.screenshot.call_count,2)
        nav._open_clan_chat.assert_not_called()

    def test_jump_to_an_unverified_screen_never_counts_as_a_clear_chat(self):
        capture=Mock();nav=Mock();monitor=Mock()
        nav.classifier._clan_chat_anchor_visible.side_effect=[True,True,False]
        monitor.find_donate_request.return_value=None;nav.seek_donation_requests_step.return_value='jump'
        with self.assertRaisesRegex(ValueError,'changed after'):
            peek_requests(capture,nav,monitor,lambda:False)
        monitor.find_donate_request.assert_called_once()

    def test_stop_prevents_request_jump_and_further_capture(self):
        capture=Mock();nav=Mock();monitor=Mock();cancelled=[False]
        nav.classifier._clan_chat_anchor_visible.return_value=True
        def scan(frame):cancelled[0]=True;return None
        monitor.find_donate_request.side_effect=scan
        self.assertIsNone(peek_requests(capture,nav,monitor,lambda:cancelled[0]))
        nav.seek_donation_requests_step.assert_not_called();self.assertEqual(capture.screenshot.call_count,1)

    def test_single_account_handles_a_request_before_another_attack(self):
        bot=DonationBot.__new__(DonationBot);bot.config=SimpleNamespace(donation_enabled=True)
        bot.capture=Mock();bot.navigator=Mock();bot.chat_monitor=Mock();bot.should_stop=lambda:False
        bot._set_state=Mock();bot._should_handle_request=Mock(return_value=True);bot._farm_chat_check_due=True
        request=object()
        with patch('coc_bot.donation.chat_check.peek_requests',return_value=request):
            self.assertTrue(bot._check_chat_between_attacks())
        self.assertIs(bot._pending_request,request);bot._set_state.assert_called_once_with('open_donation')
        self.assertFalse(bot._farm_chat_check_due)

    def test_every_returned_manual_attack_arms_the_chat_checkpoint(self):
        with tempfile.TemporaryDirectory() as root:
            bot=DonationBot.__new__(DonationBot)
            bot.config=SimpleNamespace(data_dir=Path(root),farm_engine='automatic',farm_calibrated=True,
                                       farm_enabled=True,donation_enabled=True)
            bot._state='scan_chat';bot._farm_requested=True;bot._stop_requested=False
            bot._farm_due=Mock(return_value=True);bot._set_state=Mock();bot.set_mode=Mock()
            bot.game_state=Mock();bot.farmer=Mock();bot.tracker=Mock();bot.navigator=Mock()
            bot._has_donate_request=Mock();bot._fleet_after_step=Mock()
            bot.farmer.run_one_attack.return_value=FarmResult(True,'ok',True,True)
            self.assertTrue(bot._maybe_run_farm())
            self.assertTrue(bot._farm_chat_check_due);self.assertTrue(bot._visit_chat_pending)
            bot._fleet_after_step.assert_called_once()
