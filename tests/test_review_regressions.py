"""Regression checks for failure isolation, account data and optional OCR."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from coc_bot.accounts.store import write
from coc_bot.control.resource_status import resource_status
from coc_bot.runtime.persistence import load_runtime_state
from coc_bot.runtime.tracker import RuntimeTracker
from coc_bot.runtime.verification import record_failure
from coc_bot.runtime.visits import Visit, STEPS
from coc_bot.vision.ocr import QuantityOCR
from coc_bot.config import load_config
from coc_bot.bot import DonationBot


class ReviewRegressions(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.config=load_config();self.config.data_dir=Path(self.temp.name)
        self.config.account_tag='#PYLQG'

    def test_corrupt_resource_observations_are_displayed_as_unverified(self):
        path=self.config.data_dir/'resources/home.json';path.parent.mkdir(parents=True)
        for value in ('invalid','[]','null','{"observed_at":NaN}',
                      '{"observation":{"balances":[]}}','{"status":12}',
                      '{"account":"#OTHER"}','{"observation":{"capacities":{"gold":-1}}}'):
            with self.subTest(value=value):
                path.write_text(value)
                result=resource_status(self.config)
                self.assertEqual(result['status'],'unverified')
                self.assertIsNone(result['observation'])
                json.dumps(result,allow_nan=False)
                self.assertEqual(path.read_text(),value)

    def test_valid_resource_readings_survive_status_projection(self):
        saved={'account':self.config.account_tag,'observed_at':1000,'status':'refilling',
               'observation':{'balances':{'gold':100},'capacities':{'gold':1000},'resources':['gold']}}
        write(self.config.data_dir/'resources/home.json',saved)
        self.assertEqual(resource_status(self.config)['observation'],saved['observation'])

    def test_invalid_visit_cursor_or_deadline_is_never_silently_resumed(self):
        visit=Visit(self.config,lambda:1000)
        valid=visit.load()
        variants=[valid|{'step':step} for step in (-1,len(STEPS)+1,'2',True)]
        variants += [valid|{'started_at':float('nan')},valid|{'outcomes':[]},
                     valid|{'deferred':{'farm':{'retry_at':float('inf')}}}]
        for state in variants:
            with self.subTest(state=state):
                write(visit.path,state);before=visit.path.read_bytes()
                with self.assertRaisesRegex(ValueError,'invalid'):visit.order()
                self.assertEqual(visit.path.read_bytes(),before)

    def test_invalid_active_runtime_is_rejected(self):
        path=self.config.data_dir/'runtime_state.json'
        for field,value in [('active_seconds',float('nan')),('active_seconds',float('inf')),
                            ('active_seconds',-1),('active_seconds',True)]:
            with self.subTest(field=field,value=value):
                path.write_text(json.dumps({field:value}))
                state=load_runtime_state(path)
                self.assertEqual(state.active_seconds,0)

    def test_failed_attack_completion_save_restores_previous_durable_identity(self):
        tracker=RuntimeTracker(self.config)
        tracker.state.last_farm_at='2026-01-01T00:00:00+00:00'
        tracker.state.last_completed_attack_id='previous'
        with patch('coc_bot.attack.recovery.atomic_json',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):tracker.mark_farm_success(attack_id='new')
        self.assertEqual(tracker.state.last_completed_attack_id,'previous')
        self.assertEqual(tracker.state.last_farm_at,'2026-01-01T00:00:00+00:00')

    def test_malformed_diagnostic_metadata_cannot_crash_the_controller(self):
        ident=record_failure(self.config,'test','unreadable')
        path=self.config.data_dir/'verification/failures.json'
        original=json.loads(path.read_text())[0]
        path.write_text(json.dumps([original|{'count':None,'last_warning':{},'first_seen':float('nan'),
                                             'resolved_at':123,'status':'resolved'}]))
        self.assertEqual(record_failure(self.config,'test','unreadable'),ident)
        entry=json.loads(path.read_text())[0]
        self.assertEqual(entry['count'],1);self.assertEqual(entry['status'],'needs_review')
        self.assertNotIn('resolved_at',entry)
        json.dumps(entry,allow_nan=False)

    def test_optional_ocr_never_downloads_models_in_a_device_worker(self):
        module=SimpleNamespace(Reader=Mock(side_effect=FileNotFoundError('not preloaded')))
        ocr=QuantityOCR()
        with patch.dict('sys.modules',{'easyocr':module}):
            with self.assertRaises(FileNotFoundError):ocr._get_reader()
            with self.assertRaises(RuntimeError):ocr._get_reader()
        module.Reader.assert_called_once_with(['en'],gpu=False,verbose=False,download_enabled=False)

    def bot(self):
        bot=DonationBot.__new__(DonationBot);bot.config=self.config
        bot.capture=Mock();bot.navigator=Mock();bot.nav_input=Mock();bot.game_state=Mock()
        bot._last_anti_idle=0;bot._state='scan_chat';bot.should_stop=lambda:False
        return bot

    def test_generic_recovery_never_navigates_past_an_uncertain_home_payment(self):
        bot=self.bot();receipt={'kind':'buildings','phase':'confirming','name':'Cannon'}
        write(self.config.data_dir/'upgrades/state.json',{'pending':receipt})
        with self.assertRaisesRegex(RuntimeError,'upgrade receipt'):bot._recover()
        bot.capture.screenshot.assert_not_called();bot.nav_input.back.assert_not_called()
        bot.navigator.ensure_clan_chat.assert_not_called()
        self.assertEqual(json.loads((self.config.data_dir/'upgrades/state.json').read_text())['pending'],receipt)

    def test_anti_idle_requires_live_chat_and_respects_stop_between_swipes(self):
        bot=self.bot();bot.navigator.classifier._clan_chat_anchor_visible.return_value=False
        with patch('coc_bot.bot.time.monotonic',return_value=10000):bot._maybe_anti_idle()
        bot.nav_input.swipe.assert_not_called()
        bot._last_anti_idle=0;bot.navigator.classifier._clan_chat_anchor_visible.return_value=True
        with patch('coc_bot.bot.time.monotonic',return_value=10000),\
             patch('coc_bot.bot.interrupted_sleep',return_value=True):bot._maybe_anti_idle()
        bot.nav_input.swipe.assert_called_once()

    def test_anti_idle_does_not_touch_pending_upgrade_or_layout_controls(self):
        bot=self.bot()
        for relative,state in [('upgrades/state.json',{'pending':{'kind':'buildings'}}),
                               ('layouts/state.json',{'last_survey':{'payment':{'cost':100}}})]:
            path=self.config.data_dir/relative;write(path,state)
            with patch('coc_bot.bot.time.monotonic',return_value=10000):bot._maybe_anti_idle()
            path.unlink()
        bot.capture.screenshot.assert_not_called();bot.nav_input.swipe.assert_not_called()

    def test_desktop_readiness_does_not_require_old_taps_for_automatic_attacks(self):
        from coc_bot.gui.ux_helpers import FarmReadiness
        self.assertFalse(FarmReadiness(True,True,False,requires_sequence=True).ready_for_manual)
        self.assertTrue(FarmReadiness(True,True,False,requires_sequence=False).ready_for_auto)
        self.assertFalse(FarmReadiness(True,False,False,requires_sequence=False).ready_for_manual)


if __name__=='__main__':unittest.main()
