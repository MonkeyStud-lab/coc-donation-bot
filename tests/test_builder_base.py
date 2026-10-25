import json
import tempfile
import shutil
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

from coc_bot.adb.client import AdbStopped
from coc_bot.builder_base.runner import BuilderBaseRunner, pending
from coc_bot.builder_base.upgrades import eligibility
from coc_bot.builder_base.vision import BuilderReader
from coc_bot.upgrades.vision import Candidate
from coc_bot.runtime.screenshot_retention import RetentionPolicy, prune_attack_diagnostics


class BuilderVisionTests(unittest.TestCase):
    def frame(self, n):
        return cv2.imread(str(Path(__file__).parent/'fixtures/builder_base'/f'controls-{n}.png'))

    def test_battle_and_results_are_distinct(self):
        reader=BuilderReader()
        for n in (17,18,20):
            self.assertTrue(reader.battle(self.frame(n)),n)
            self.assertIsNone(reader.result_button(self.frame(n)))
        self.assertFalse(reader.battle(self.frame(23)))
        self.assertIsNotNone(reader.result_button(self.frame(23)))
        self.assertFalse(reader.battle(self.frame(14)))

    def test_army_preflight_rejects_missing_or_different_camp(self):
        reader=BuilderReader(); frame=self.frame(14)
        self.assertTrue(reader.supported_army(frame))
        frame[400:510,530:630]=0
        self.assertFalse(reader.supported_army(frame))

    def test_reward_requires_both_headings_and_button(self):
        reader=BuilderReader();frame=self.frame(28)
        self.assertIsNotNone(reader.reward_button(frame))
        frame[550:605]=0
        self.assertIsNone(reader.reward_button(frame))
        self.assertIsNone(reader.reward_button(self.frame(23)))

    def test_cards_and_second_stage_survivors(self):
        reader=BuilderReader()
        first=reader.cards(self.frame(17))
        self.assertEqual(len(first),7)
        self.assertFalse(any(c['deployed'] for c in first))
        active=reader.cards(self.frame(18))
        self.assertEqual(len(active),7)
        self.assertTrue(all(c['deployed'] for c in active))
        survivors=reader.cards(self.frame(20))
        self.assertEqual([c['slot'] for c in survivors],[0,2,3,5,6,7])
        self.assertFalse(any(c['deployed'] for c in survivors))
        self.assertEqual(survivors[0]['unit'],'battle_copter')

    def test_dimmed_home_controls_do_not_establish_village(self):
        reader=BuilderReader();frame=self.frame(24)
        self.assertTrue(reader.home(frame))
        self.assertFalse(reader.home((frame*.5).astype(np.uint8)))

    @unittest.skipUnless(shutil.which('tesseract'), 'OCR executable is required')
    def test_gold_confirmation_requires_matching_price_name_and_resource(self):
        reader=BuilderReader();frame=self.frame(8)
        candidate=Candidate('Elixir Collector',5000,'gold',(1,2))
        self.assertIsNotNone(reader.confirmation(frame,candidate))
        for name,price,currency in [('Elixir Collector',50000,'gold'),('Gold Mine',5000,'gold'),
                                     ('Elixir Collector',5000,'gems')]:
            self.assertIsNone(reader.confirmation(frame,Candidate(name,price,currency,(1,2))))

    @unittest.skipUnless(shutil.which('tesseract'), 'OCR executable is required')
    def test_research_confirmation_and_running_modal(self):
        reader=BuilderReader()
        root=Path(__file__).parent/'fixtures/builder_base'
        frame=cv2.imread(str(root/'progression-research-confirm.png'))
        c=Candidate('Night Witch',2500000,'elixir',(1,2))
        self.assertIsNotNone(reader.confirmation(frame,c))
        for name,price,resource in [('Night Witch',250000,'elixir'),('Night Witch',2500000,'gems'),
                                    ('Baby Dragon',2500000,'elixir')]:
            self.assertIsNone(reader.confirmation(frame,Candidate(name,price,resource,(1,2))))
        frame[770:810,400:600]=0
        self.assertIsNone(reader.confirmation(frame,c))
        running=cv2.imread(str(root/'progression-research-after.png'))
        self.assertIsNotNone(reader.detail_close(running))
        self.assertTrue(reader.running_detail(running,c))
        self.assertIsNone(reader.confirmation(running,c))


class BuilderSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.config=SimpleNamespace(data_dir=Path(self.temp.name),dry_run=False,
            builder_base_builders_reserved=0,builder_base_gold_reserve=100_000,
            builder_base_elixir_reserve=100_000,upgrade_excluded_names='')

    def runner(self, stop=None):
        return BuilderBaseRunner(self.config,MagicMock(),MagicMock(),MagicMock(),MagicMock(),stop)

    def test_policy_reserves_busy_builders_and_no_gems(self):
        c=Candidate('Elixir Collector',5000,'gold',(1,2))
        self.assertIsNone(eligibility(self.config,c,{'gold':200_000},(1,2)))
        for availability in (None,(0,2),(2,6)):
            self.assertIsNotNone(eligibility(self.config,c,{'gold':200_000},availability))
        self.assertIsNotNone(eligibility(self.config,c,{'gold':104_999},(2,2)))
        for name,resource in [('Builder Hall','gold'),('Battle Machine','elixir'),('Wall','gold'),('Cannon','gems')]:
            self.assertIsNotNone(eligibility(self.config,Candidate(name,1,resource,(1,2)),{resource:200_000},(2,2)))

    def test_stop_after_screenshot_prevents_next_tap(self):
        stopped=[False];r=self.runner(lambda:stopped[0])
        r.capture.screenshot.side_effect=lambda:stopped.__setitem__(0,True)
        with self.assertRaises(AdbStopped):r.frame()
        with self.assertRaises(AdbStopped):r.tap((1,2))
        r.input.tap.assert_not_called()

    def test_practice_never_enters_or_spends(self):
        self.config.dry_run=True;r=self.runner()
        self.assertEqual(r.run()['status'],'practice_skipped')
        r.capture.screenshot.assert_not_called();r.input.tap.assert_not_called()

    def test_recovery_observes_battle_without_deployment(self):
        r=self.runner();r.phase('battle');r.reader=MagicMock()
        r.reader.battle.return_value=True
        r.watch_battle=MagicMock();r.finish=MagicMock()
        r.recover();r.watch_battle.assert_called_once_with(deploy=False)
        r.finish.assert_called_once();self.assertTrue(pending(self.config))

    def test_corrupt_journal_blocks_unsafe_home_recovery(self):
        p=self.config.data_dir/'builder_base/visit.json';p.parent.mkdir();p.write_text('')
        with self.assertRaises(RuntimeError):pending(self.config)

    def test_builder_retention_protects_pending_and_unknown_files(self):
        r=self.runner();r.phase('battle')
        p=self.config.data_dir/'debug/builder-base'/('a'*32);p.mkdir(parents=True)
        shot=p/'001-stage-view.png';shot.write_bytes(b'evidence')
        policy=RetentionPolicy(days=0,keep_recent=0,max_groups=0)
        self.assertTrue(prune_attack_diagnostics(self.config.data_dir,policy=policy)['skipped_pending'])
        r.record.pop('phase');r.phase('')
        keep=p/'human-review.txt';keep.write_text('keep')
        prune_attack_diagnostics(self.config.data_dir,policy=policy);self.assertTrue(shot.exists())
        keep.unlink();prune_attack_diagnostics(self.config.data_dir,policy=policy)
        self.assertFalse(shot.exists())

    def test_scheduler_defers_to_donations_and_future_visit(self):
        from coc_bot.bot import DonationBot
        b=DonationBot.__new__(DonationBot);b.config=self.config
        b.config.builder_base_attacks_enabled=True;b.config.builder_base_upgrades_enabled=False
        b._state='scan_chat';b.should_stop=MagicMock(return_value=False)
        b.capture=MagicMock();b._has_donate_request=MagicMock(return_value=True)
        with patch('coc_bot.builder_base.runner.BuilderBaseRunner') as runner:
            self.assertFalse(b._maybe_run_builder_base());runner.assert_not_called()
            b._has_donate_request.return_value=False
            with patch('coc_bot.builder_base.runner.state',return_value={'next_visit_at':1e20}):
                self.assertFalse(b._maybe_run_builder_base());runner.assert_not_called()

    def test_settings_restart_waits_for_builder_visit_but_stop_does_not(self):
        from coc_bot.bot import DonationBot
        b=DonationBot.__new__(DonationBot);b._finish_action_requested=True;b._state='builder_base'
        self.assertFalse(b._settings_stop_ready())
        b._state='scan_chat';self.assertTrue(b._settings_stop_ready())
