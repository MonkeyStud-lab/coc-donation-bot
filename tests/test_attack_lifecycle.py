"""Scheduled planner recovery must not hand an active battle to donations."""
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
from tempfile import TemporaryDirectory
from pathlib import Path

from coc_bot.adb.client import AdbStopped
from coc_bot.attack.executor import ExecutionResult
from coc_bot.attack.planned_farmer import run_planned_attack


class PlannedLifecycleTests(TestCase):
    def test_restart_and_legacy_farm_require_camera_recovery_before_any_input(self):
        from coc_bot.bot import DonationBot
        from coc_bot.attack.farmer import AttackFarmer
        with TemporaryDirectory() as root:
            pending=Path(root)/'attack-planner/camera-pending.json'
            pending.parent.mkdir();pending.write_text('{}')
            config=SimpleNamespace(data_dir=Path(root),adb_device='test',farm_engine='sequence',farm_calibrated=True)
            bot=Mock(spec=DonationBot);bot.config=config;bot.client=Mock();bot.farmer=Mock();bot.tracker=Mock();bot.navigator=Mock()
            bot.game_state=Mock()
            farmer=Mock(spec=AttackFarmer);farmer.config=config;farmer.attack_nav=Mock();farmer.input=Mock();farmer.tracker=Mock()
            farmer.capture=Mock()
            with patch('coc_bot.attack.recovery.recover_attack',side_effect=ValueError('Recovery paused')):
                with self.assertRaisesRegex(ValueError,'Recovery paused'): DonationBot._run_inner(bot)
                with self.assertRaisesRegex(ValueError,'Recovery paused'): AttackFarmer.run_one_attack(farmer)
            bot.client.health_check.assert_called_once()
            bot.navigator.ensure_clan_chat.assert_not_called()
            farmer._run_one_attack.assert_not_called()

    def test_unrestored_camera_stops_bot_before_donation_navigation(self):
        from coc_bot.bot import DonationBot
        from coc_bot.attack.farmer import FarmResult
        with TemporaryDirectory() as root:
            pending = Path(root)/'attack-planner/camera-pending.json'
            pending.parent.mkdir(); pending.write_text('{}')
            bot = Mock(spec=DonationBot)
            bot.config = SimpleNamespace(data_dir=Path(root), farm_engine='planner', farm_enabled=True,
                                         farm_calibrated=True, farm_interval_seconds=7200)
            bot._state = 'scan_chat'; bot._farm_requested = True; bot._stop_requested = False
            bot._farm_due.return_value = True
            bot.farmer = Mock(); bot.tracker = Mock(); bot.game_state = Mock(); bot.navigator = Mock()
            bot.farmer.run_one_attack.return_value = FarmResult(False, 'camera recovery failed', True)
            self.assertTrue(DonationBot._maybe_run_farm(bot))
            bot._recover.assert_called_once()
            bot.tracker.mark_farm_success.assert_not_called()  # recovered checkpoint owns interval accounting
            bot.navigator.ensure_clan_chat.assert_not_called()
            self.assertEqual(bot._set_state.call_args.args, ('farm',))

    def farmer(self):
        farmer = Mock()
        temporary=TemporaryDirectory();self.addCleanup(temporary.cleanup)
        farmer.config.data_dir=Path(temporary.name)
        farmer.config.adb_device='test'
        farmer.config.farm_battle_timeout_seconds = 200
        farmer.input.client.stop_check = lambda: False
        farmer.attack_nav.classifier._clan_chat_anchor_visible.return_value = True
        farmer._sleep.return_value = False
        return farmer

    def test_unverified_routine_never_opens_attack(self):
        farmer = self.farmer()
        with patch('coc_bot.attack.planned_farmer.load_template',
                   side_effect=ValueError('Supervised attack required')):
            result = run_planned_attack(farmer)
        self.assertFalse(result.success)
        farmer.attack_nav.leave_chat_for_home.assert_not_called()
        farmer.input.tap.assert_not_called()

    def test_failed_mapping_abandons_without_timer_and_restores_camera(self):
        farmer = self.farmer()
        calls = []
        farmer.attack_nav.wait_for_battle_end.side_effect = lambda **kw: calls.append(('wait', kw))
        farmer.attack_nav.return_home_from_attack.side_effect = lambda: calls.append(('home', {})) or True
        farmer.donation_nav.ensure_clan_chat.side_effect = lambda: calls.append(('chat', {})) or True
        with patch('coc_bot.attack.planned_farmer.load_template', return_value=({}, Mock())), \
                patch('coc_bot.attack.planned_farmer.remember_camera'), \
                patch('coc_bot.attack.planned_farmer.restore_camera', side_effect=lambda s: calls.append(('restore', {}))), \
                patch('coc_bot.attack.planned_farmer.survey', return_value={'projection': None}), \
                patch('coc_bot.attack.abort.leave_unstarted_opponent',side_effect=lambda s:calls.append(('abandon',{})) or True), \
                patch('coc_bot.attack.planned_farmer.VerifiedExecutor') as executor:
            result = run_planned_attack(farmer)
        self.assertFalse(result.success)
        self.assertTrue(result.counts_toward_interval)
        executor.assert_not_called()
        self.assertEqual([c[0] for c in calls], ['restore', 'abandon', 'restore', 'chat'])
        farmer.attack_nav.wait_for_battle_end.assert_not_called()

    def test_uncertain_tap_uses_attempt_time_and_never_replays_plan(self):
        farmer = self.farmer()
        result = ExecutionResult(False, 'Count unreadable', uncertain_tap=True, first_attempt_at=123)
        with patch('coc_bot.attack.planned_farmer.load_template', return_value=({}, Mock())), \
                patch('coc_bot.attack.planned_farmer.remember_camera'), \
                patch('coc_bot.attack.planned_farmer.restore_camera'), \
                patch('coc_bot.attack.planned_farmer.learned_catalog'), \
                patch('coc_bot.attack.planned_farmer.survey', return_value={'projection': Mock(), 'reference': Mock()}), \
                patch('coc_bot.attack.planned_farmer.VerifiedExecutor') as executor:
            executor.return_value.run.return_value = result
            outcome = run_planned_attack(farmer)
        self.assertFalse(outcome.success)
        self.assertTrue(outcome.counts_toward_interval)
        executor.return_value.run.assert_called_once()
        farmer.attack_nav.wait_for_battle_end.assert_called_once_with(timeout=None, since=123)

    def test_stop_during_survey_sends_no_cleanup_inputs(self):
        farmer = self.farmer()
        with patch('coc_bot.attack.planned_farmer.load_template', return_value=({}, Mock())), \
                patch('coc_bot.attack.planned_farmer.remember_camera'), \
                patch('coc_bot.attack.planned_farmer.restore_camera') as restore, \
                patch('coc_bot.attack.planned_farmer.survey', side_effect=AdbStopped('Stopped')):
            result = run_planned_attack(farmer)
        self.assertFalse(result.success)
        self.assertEqual(result.reason, 'stopped')
        self.assertEqual(restore.call_count, 1)  # Only before entering the match.
        farmer.attack_nav.wait_for_battle_end.assert_not_called()
        farmer.attack_nav.return_home_from_attack.assert_not_called()
        farmer.donation_nav.ensure_clan_chat.assert_not_called()

    def test_failed_home_confirmation_never_restores_or_resumes_chat(self):
        farmer = self.farmer()
        farmer.attack_nav.return_home_from_attack.return_value = False
        with patch('coc_bot.attack.planned_farmer.load_template', return_value=({}, Mock())), \
                patch('coc_bot.attack.planned_farmer.remember_camera'), \
                patch('coc_bot.attack.planned_farmer.restore_camera') as restore, \
                patch('coc_bot.attack.planned_farmer.survey', side_effect=ValueError('No map')):
            result = run_planned_attack(farmer)
        self.assertFalse(result.success)
        self.assertEqual(restore.call_count, 1)
        farmer.donation_nav.ensure_clan_chat.assert_not_called()
