"""Old break settings cannot pause work or erase durable attack history."""
import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch

from coc_bot.bot import DonationBot
from coc_bot.config import load_config
from coc_bot.runtime.persistence import load_runtime_state
from coc_bot.runtime.tracker import RuntimeTracker


class NoScheduledBreakTests(TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);(self.root/'data').mkdir()
        shutil.copytree(Path(__file__).parents[1]/'config',self.root/'config')
        self.env=patch.dict(os.environ,{'COC_BOT_HOME':str(self.root),'ADB_DEVICE':'offline-no-breaks'})
        self.env.start();self.addCleanup(self.env.stop)

    def test_legacy_break_settings_are_ignored_and_not_offered_for_editing(self):
        from coc_bot.control.settings_fields import current_setting_values
        (self.root/'data/user_settings.yaml').write_text(
            'runtime:\n  session_limit_seconds: obsolete\n  session_limit_variance_seconds: obsolete\n'
            '  break_min_seconds: obsolete\n  break_max_seconds: obsolete\n',encoding='utf-8')
        config=load_config();values=current_setting_values()
        for key in ('session_limit_seconds','session_limit_variance_seconds','break_min_seconds','break_max_seconds'):
            self.assertFalse(hasattr(config,key));self.assertNotIn(key,values)

    def test_old_future_break_does_not_discard_attack_history_or_pause_work(self):
        path=self.root/'data/runtime_state.json'
        path.write_text(json.dumps({'active_seconds':100_000,'break_until':'2099-01-01T00:00:00+00:00',
            'last_break_seconds':-1,'cycle_count':'obsolete','next_session_limit_seconds':1,
            'last_farm_at':'2026-10-29T01:00:00+00:00','last_completed_attack_id':'durable-receipt'}))
        state=load_runtime_state(path)
        self.assertEqual(state.last_completed_attack_id,'durable-receipt')
        self.assertEqual(state.active_seconds,100_000);self.assertFalse(hasattr(state,'break_until'))
        bot=DonationBot.__new__(DonationBot);bot.config=load_config();bot._state='scan_chat'
        bot._stop_requested=False;bot._farm_requested=False;bot.should_stop=lambda:False
        bot._settings_stop_ready=lambda:False;bot._check_watchdog=Mock();bot._maybe_anti_idle=Mock()
        bot.tracker=RuntimeTracker(bot.config);bot.capture=Mock();bot.nav_input=Mock();bot.navigator=Mock();bot.app=Mock()
        for name in ('_maybe_request_reinforcements','_maybe_run_upgrades','_maybe_run_farm','_maybe_run_layouts','_maybe_run_builder_base'):
            setattr(bot,name,Mock(return_value=True))
        with patch('coc_bot.attack.recovery.pending',return_value=None),\
             patch('coc_bot.builder_base.runner.pending',return_value=False),\
             patch('coc_bot.upgrades.runner.UpgradeRunner.state',return_value={}):
            bot._loop_tick()
        bot._maybe_request_reinforcements.assert_called_once()
        bot.app.force_stop.assert_not_called();bot.app.launch.assert_not_called()
        self.assertEqual(load_runtime_state(path).last_completed_attack_id,'durable-receipt')
        bot._stop_requested=True;bot._maybe_request_reinforcements.reset_mock();bot._loop_tick()
        bot._maybe_request_reinforcements.assert_not_called()
