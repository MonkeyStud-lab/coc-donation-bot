from pathlib import Path
from dataclasses import replace
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
import json
import os
import subprocess
import sys

import numpy as np
import cv2

from coc_bot.adb.client import AdbStopped
from coc_bot.attack.recovery import (AttackCheckpoint, RecoveryRequired, atomic_json, recover_attack,
                                     finish_attack, accept_home_zoom_limit, accept_automatic_home_camera)
from coc_bot.runtime.tracker import RuntimeTracker
from coc_bot.config import load_config


class CheckpointTests(TestCase):
    def test_abrupt_process_exit_preserves_intent(self):
        with TemporaryDirectory() as folder:
            code = """
import os,sys
from pathlib import Path
from types import SimpleNamespace
from coc_bot.attack.recovery import AttackCheckpoint
c=AttackCheckpoint(SimpleNamespace(data_dir=Path(sys.argv[1]),adb_device='test'))
c.begin('deploying');c.update(deployment_possible=True,unit_id='electro_dragon')
os._exit(17)
"""
            result = subprocess.run([sys.executable, '-c', code, folder], env=os.environ.copy(), capture_output=True)
            self.assertEqual(result.returncode, 17, result.stderr)
            state = AttackCheckpoint(SimpleNamespace(data_dir=Path(folder), adb_device='test')).load()
            self.assertTrue(state['deployment_possible'])
            self.assertEqual(state['unit_id'], 'electro_dragon')

    def test_failed_atomic_replace_leaves_previous_checkpoint(self):
        with TemporaryDirectory() as folder:
            path = Path(folder)/'pending.json'
            atomic_json(path, {'phase':'opponent'})
            with patch('coc_bot.attack.recovery.os.replace', side_effect=OSError('disk full')):
                with self.assertRaises(OSError): atomic_json(path, {'phase':'deploying'})
            self.assertEqual(json.loads(path.read_text()), {'phase':'opponent'})
            self.assertEqual(list(Path(folder).glob('*.tmp')), [])

    def test_corrupt_or_foreign_checkpoint_fails_closed(self):
        with TemporaryDirectory() as folder:
            c = AttackCheckpoint(SimpleNamespace(data_dir=Path(folder), adb_device='test'))
            c.begin()
            value = c.load()
            for raw in ('', '[]', '{}', '{', json.dumps(value|{'device':'other'})):
                c.path.write_text(raw)
                with self.assertRaises(RecoveryRequired): c.load()
                self.assertTrue(c.path.exists())

    def test_completion_id_survives_repeated_recovery_and_tracker_restart(self):
        with TemporaryDirectory() as folder:
            config = replace(load_config(), data_dir=Path(folder))
            tracker = RuntimeTracker(config)
            tracker.mark_farm_success(attack_id='same-attack')
            first = tracker.state.last_farm_at
            tracker = RuntimeTracker(config)
            with patch('coc_bot.attack.recovery.atomic_json',side_effect=AssertionError('must not record twice')):
                tracker.mark_farm_success(attack_id='same-attack')
            self.assertEqual(first,tracker.state.last_farm_at)
            self.assertIsNone(tracker.state.next_farm_interval_seconds)

    def test_failed_completion_save_keeps_checkpoint_and_can_retry(self):
        with TemporaryDirectory() as folder:
            config = replace(load_config(), data_dir=Path(folder))
            checkpoint = AttackCheckpoint(config)
            checkpoint.begin('home_confirmed'); checkpoint.update(deployment_possible=True)
            tracker = RuntimeTracker(config)
            with patch('coc_bot.attack.recovery.atomic_json', side_effect=OSError('disk full')):
                with self.assertRaises(OSError): finish_attack(SimpleNamespace(config=config), tracker=tracker)
            self.assertTrue(checkpoint.path.exists())
            finish_attack(SimpleNamespace(config=config), tracker=tracker)
            self.assertFalse(checkpoint.path.exists())

    def test_entered_opponent_counts_even_if_mapping_failed_before_deployment(self):
        with TemporaryDirectory() as folder:
            config = replace(load_config(),data_dir=Path(folder))
            checkpoint = AttackCheckpoint(config)
            checkpoint.begin('home_confirmed');checkpoint.update(entered_opponent=True)
            tracker=Mock()
            finish_attack(SimpleNamespace(config=config),tracker=tracker)
            tracker.mark_farm_success.assert_called_once()

    def test_legacy_camera_guard_blocks_fixed_taps_without_navigation(self):
        from coc_bot.attack.farmer import AttackFarmer
        with TemporaryDirectory() as folder:
            config=replace(load_config(),data_dir=Path(folder),farm_engine='sequence')
            marker=config.data_dir/'attack-planner/camera-legacy-blocked.json'
            atomic_json(marker,{'device':config.adb_device})
            farmer=Mock();farmer.config=config
            result=AttackFarmer._run_one_attack(farmer)
            self.assertFalse(result.success)
            self.assertIn('saved sequence camera changed',result.reason)
            farmer.attack_nav.assert_not_called();farmer.input.tap.assert_not_called()


class RecoveryTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.config = replace(load_config(), data_dir=Path(self.tmp.name), adb_device='test')
        self.checkpoint = AttackCheckpoint(self.config); self.checkpoint.begin('deploying')
        self.checkpoint.update(deployment_possible=True)
        self.frame = np.zeros((540,960,3),np.uint8)
        self.nav = Mock()
        self.nav.classifier._clan_chat_anchor_visible.return_value = False
        self.nav.classifier.find_direct_match_button.return_value = None
        self.nav.battle_completion.detect.return_value = None
        self.nav.donation_nav.ensure_clan_chat.return_value = True
        self.session = SimpleNamespace(config=self.config, client=SimpleNamespace(stop_check=lambda:False),
            attack_nav=self.nav, input=Mock(), capture=Mock(), _sleep=Mock())
        self.session.capture.screenshot.return_value = self.frame
        self.clock = 0.
        def sleep(seconds): self.clock += seconds
        self.session._sleep.side_effect = sleep
        self.patches = [patch('coc_bot.attack.recovery.time.monotonic', side_effect=lambda:self.clock),
                        patch('coc_bot.attack.planned_farmer.restore_camera'),
                        patch('coc_bot.vision.battle_menu.home_build_control_visible', return_value=False),
                        patch('coc_bot.vision.battle_menu.battlefield_ready', return_value=False),
                        patch('coc_bot.vision.battle_menu.active_battle_ready', return_value=False),
                        patch('coc_bot.vision.battle_menu.army_confirmation_button', return_value=None),
                        patch('coc_bot.vision.battle_menu.reward_continue_button', return_value=None)]
        self.mocks = [p.start() for p in self.patches]
        for p in self.patches: self.addCleanup(p.stop)
        self.tracker = Mock()

    def test_home_restores_camera_then_requires_chat_anchor(self):
        self.mocks[2].return_value=True
        self.nav.classifier._clan_chat_anchor_visible.side_effect=[False,True]
        self.assertTrue(recover_attack(self.session, tracker=self.tracker))
        self.mocks[1].assert_called_once_with(self.session)
        self.tracker.mark_farm_success.assert_called_once()
        self.assertFalse(self.checkpoint.path.exists())
        self.session.input.tap.assert_not_called(); self.session.input.back.assert_not_called()

    def test_uncertain_home_confirmation_keeps_guard(self):
        self.mocks[2].return_value=True
        with self.assertRaisesRegex(RecoveryRequired,'anchor'): recover_attack(self.session,tracker=self.tracker)
        self.assertTrue(self.checkpoint.path.exists()); self.tracker.mark_farm_success.assert_not_called()

    def test_battle_waits_then_two_results_observations_before_tap(self):
        self.mocks[3].side_effect = [True,False,False]
        self.nav.battle_completion.detect.side_effect = [None,(480,470),(480,470)]
        self.mocks[2].side_effect = [False,False,False,True]
        self.nav.classifier._clan_chat_anchor_visible.side_effect=[False,False,False,False,True]
        self.assertTrue(recover_attack(self.session,tracker=self.tracker))
        self.session.input.tap.assert_called_once_with(480,470,jitter=0)
        self.session.input.back.assert_not_called()
        self.assertGreaterEqual(self.clock,3.2)

    def test_live_battle_timeout_never_forces_return_or_replays_troops(self):
        self.mocks[3].return_value=True
        with self.assertRaises(RecoveryRequired): recover_attack(self.session,tracker=self.tracker)
        self.session.input.tap.assert_not_called(); self.session.input.back.assert_not_called()
        self.assertTrue(self.checkpoint.path.exists())

    def test_unknown_exhausts_bounded_budget_and_restart_sends_no_input(self):
        for _ in range(2):
            with self.assertRaises(RecoveryRequired): recover_attack(self.session,tracker=self.tracker)
        self.assertEqual(self.checkpoint.load()['attempts'],3)
        self.session.input.tap.assert_not_called(); self.session.input.back.assert_not_called()

    def test_generic_screen_labels_never_authorize_back(self):
        self.nav.classify.return_value='matchmaking'
        self.nav._attack_menu_open.return_value=True
        with self.assertRaises(RecoveryRequired): recover_attack(self.session,tracker=self.tracker)
        self.session.input.back.assert_not_called()

    def test_manual_home_after_exhausted_budget_can_finish(self):
        self.checkpoint.update(attempts=3)
        self.mocks[2].return_value=True
        self.nav.classifier._clan_chat_anchor_visible.side_effect=[False,True]
        self.assertTrue(recover_attack(self.session,tracker=self.tracker))

    def test_verified_army_page_can_cancel_without_attacking(self):
        self.mocks[5].side_effect=[(800,470),None]
        self.mocks[2].side_effect=[False,True]
        self.nav.classifier._clan_chat_anchor_visible.side_effect=[False,False,True]
        self.assertTrue(recover_attack(self.session,tracker=self.tracker))
        self.session.input.back.assert_called_once(); self.session.input.tap.assert_not_called()

    def test_stop_preserves_checkpoint_and_sends_no_cleanup_input(self):
        self.session.client.stop_check=lambda:True
        with self.assertRaises(AdbStopped): recover_attack(self.session,tracker=self.tracker)
        self.session.input.tap.assert_not_called(); self.session.input.back.assert_not_called()
        self.assertTrue(self.checkpoint.path.exists())

    def test_camera_restore_failure_preserves_checkpoint(self):
        self.mocks[2].return_value=True
        self.mocks[1].side_effect=ValueError('camera failed')
        with self.assertRaisesRegex(ValueError,'camera failed'): recover_attack(self.session,tracker=self.tracker)
        self.assertTrue(self.checkpoint.path.exists())

    def test_old_camera_marker_is_migrated_without_replaying_plan(self):
        self.checkpoint.path.unlink()
        atomic_json(self.checkpoint.path.with_name('camera-pending.json'),{'device':'test','at':0})
        self.mocks[2].return_value=True
        self.nav.classifier._clan_chat_anchor_visible.side_effect=[False,True]
        self.assertTrue(recover_attack(self.session,tracker=self.tracker))
        self.tracker.mark_farm_success.assert_called_once()

    def test_automatic_endpoint_fallback_is_not_available_to_legacy_sequences(self):
        self.mocks[2].return_value=True
        self.mocks[1].side_effect=ValueError('Camera restoration did not converge')
        self.session.config=replace(self.config,farm_engine='sequence')
        with patch('coc_bot.attack.recovery.accept_home_zoom_limit') as endpoint:
            with self.assertRaises(ValueError):recover_attack(self.session,tracker=self.tracker)
        endpoint.assert_not_called()

    def test_nearby_endpoint_preserves_reference_and_blocks_fixed_sequence(self):
        root=self.config.data_dir/'attack-planner'
        cv2.imwrite(str(root/'camera-before.png'),self.frame)
        atomic_json(root/'camera-pending.json',{'device':'test'})
        self.mocks[2].return_value=True
        with patch('coc_bot.attack.camera.compare_camera',side_effect=[
                {'verified':True,'scale':1.043},{'verified':True,'scale':1.0001},
                {'verified':True,'scale':1.043}]),patch('coc_bot.adb.multitouch.Multitouch') as touch:
            self.assertTrue(accept_home_zoom_limit(self.session))
        touch.return_value.__enter__.return_value.pinch.assert_called_once_with()
        self.assertTrue((root/'camera-legacy-blocked.json').exists())
        self.assertEqual((root/'camera-legacy-before.png').read_bytes(),(root/'camera-before.png').read_bytes())
        self.assertFalse((root/'camera-pending.json').exists())
        self.assertTrue(self.checkpoint.path.exists())

    def test_changing_zoom_or_large_difference_cannot_be_accepted_as_endpoint(self):
        root=self.config.data_dir/'attack-planner'
        cv2.imwrite(str(root/'camera-before.png'),self.frame)
        atomic_json(root/'camera-pending.json',{'device':'test'})
        self.mocks[2].return_value=True
        for readings in ([{'verified':True,'scale':1.15}],
                         [{'verified':True,'scale':1.043},{'verified':True,'scale':.9},
                          {'verified':True,'scale':.94}]):
            with patch('coc_bot.attack.camera.compare_camera',side_effect=readings), \
                    patch('coc_bot.adb.multitouch.Multitouch'):
                self.assertFalse(accept_home_zoom_limit(self.session))
        self.assertTrue((root/'camera-pending.json').exists())
        self.assertFalse((root/'camera-legacy-blocked.json').exists())

    def prepare_remap(self):
        self.session.config = replace(self.config, farm_engine='automatic')
        root = self.config.data_dir/'attack-planner'
        cv2.imwrite(str(root/'camera-before.png'), self.frame)
        atomic_json(root/'camera-pending.json', {'device':'test'})
        self.mocks[2].return_value = True
        return root

    def test_stable_automatic_camera_preserves_legacy_and_attack_guards(self):
        root = self.prepare_remap()
        with patch('coc_bot.attack.camera.compare_camera', return_value={
                'verified':True, 'transform':[[1,0,0],[0,1,0]]}):
            self.assertTrue(accept_automatic_home_camera(self.session))
        self.assertFalse((root/'camera-pending.json').exists())
        self.assertTrue((root/'camera-legacy-blocked.json').exists())
        self.assertEqual((root/'camera-legacy-before.png').read_bytes(), (root/'camera-before.png').read_bytes())
        self.assertTrue(self.checkpoint.path.exists())  # not yet confirmed chat
        self.tracker.mark_farm_success.assert_not_called()
        self.session.input.tap.assert_not_called()
        self.session.input.swipe.assert_not_called()

    def test_remap_rejects_moving_missing_foreign_and_nonautomatic_views(self):
        root = self.prepare_remap()
        for matrix in (None, [[1,0,30],[0,1,0]], [[1.02,0,0],[0,1.02,0]], [[float('nan'),0,0],[0,1,0]]):
            with patch('coc_bot.attack.camera.compare_camera', return_value={'verified':True,'transform':matrix}):
                self.assertFalse(accept_automatic_home_camera(self.session))
        self.mocks[2].return_value = False
        self.assertFalse(accept_automatic_home_camera(self.session))
        self.mocks[2].return_value = True
        atomic_json(root/'camera-pending.json', {'device':'other'})
        self.assertFalse(accept_automatic_home_camera(self.session))
        self.session.config = replace(self.config, farm_engine='sequence')
        self.assertFalse(accept_automatic_home_camera(self.session))
        self.assertTrue((root/'camera-pending.json').exists())
        self.assertFalse((root/'camera-legacy-blocked.json').exists())

    def test_stop_between_remap_observations_preserves_all_guards(self):
        root = self.prepare_remap()
        stopped = [False]
        self.session.client.stop_check = lambda:stopped[0]
        self.session._sleep.side_effect = lambda _: stopped.__setitem__(0, True)
        with self.assertRaises(AdbStopped): accept_automatic_home_camera(self.session)
        self.assertTrue((root/'camera-pending.json').exists())
        self.assertTrue(self.checkpoint.path.exists())

    def test_existing_legacy_reference_is_never_replaced(self):
        root = self.prepare_remap()
        cv2.imwrite(str(root/'camera-legacy-before.png'), self.frame+50)
        old = (root/'camera-legacy-before.png').read_bytes()
        atomic_json(root/'camera-legacy-blocked.json', {'device':'test','reason':'earlier reference'})
        with patch('coc_bot.attack.camera.compare_camera', return_value={
                'verified':True, 'transform':[[1,0,0],[0,1,0]]}):
            self.assertTrue(accept_automatic_home_camera(self.session))
        self.assertEqual((root/'camera-legacy-before.png').read_bytes(), old)
        self.assertEqual(json.loads((root/'camera-legacy-blocked.json').read_text())['reason'], 'earlier reference')

    def test_unmatched_restore_uses_fallback_but_explicit_legacy_restore_does_not(self):
        self.prepare_remap()
        # Use the real restore entry point, not setUp's orchestration mock.
        self.patches[1].stop()
        from coc_bot.attack.planned_farmer import restore_camera
        with patch('coc_bot.attack.planned_farmer.compare_camera',return_value={'verified':False}), \
                patch('coc_bot.attack.planned_farmer.compare_zoom',return_value={'verified_zoom':False}), \
                patch('coc_bot.attack.planned_farmer.compare_home_zoom',return_value={'verified_zoom':False}), \
                patch('coc_bot.adb.multitouch.Multitouch'), \
                patch('coc_bot.attack.recovery.accept_automatic_home_camera',return_value=True) as accept:
            self.assertTrue(restore_camera(self.session))
            accept.assert_called_once_with(self.session)
            accept.reset_mock()
            with self.assertRaisesRegex(ValueError,'Could not match'):
                restore_camera(self.session,legacy=True)
            accept.assert_not_called()
