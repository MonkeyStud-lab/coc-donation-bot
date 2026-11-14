import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from coc_bot.progression import wall_evidence as evidence
from coc_bot.progression.walls import WallUpgrade


class WallEvidenceTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.r = Mock()
        self.r.path = Path(folder.name) / 'state.json'
        self.r.config.account_tag = '#HOME'
        self.r.config.upgrade_gold_reserve = 0
        self.r.state.side_effect = self.state
        self.r.stopped.return_value = self.r.wait.return_value = False
        self.r.eligibility.return_value = None
        self.r.reader.balances.return_value = {'gold': 15739}
        self.row = dict(name='Wall', cost=5000, currency='gold', point=(1, 1),
                        quantity=225, target_level=4)
        self.r.reader.rows.return_value = [self.row]
        self.r.reader.menu_kind.return_value = 'buildings'
        self.r.reader.confirmation.return_value = None
        self.frames = [np.full((16, 16, 3), i, np.uint8) for i in range(16)]
        self.r.find_row.return_value = (self.row, self.frames[0])
        self.r.capture.screenshot.side_effect = self.frames
        self.r.open_menu.return_value = self.frames[9]
        self.panel = dict(level=3, cost=5000, currency='gold', upgrade=True, point=(2, 2))
        self.r.scan.return_value = dict(complete=True, unfiltered=True, unknown=False,
                                        balances={'gold': 739}, rows=[self.row | {'quantity': 222}])

    def state(self):
        return json.loads(self.r.path.read_text()) if self.r.path.exists() else {}

    def query(self, sql):
        with closing(sqlite3.connect(self.r.path.with_name('wall-evidence.sqlite3'))) as db:
            return db.execute(sql).fetchall()

    def single(self, balance=10739):
        with patch('coc_bot.progression.bulk_walls.control', return_value=None), \
             patch('coc_bot.progression.walls.wall_panel', side_effect=[
                 self.panel, self.panel] + [self.panel | {'level': 4}] * 3), \
             patch('coc_bot.progression.walls.wall_balance', side_effect=[15739] + [balance] * 3):
            return WallUpgrade(self.r).run(self.row)

    def bulk(self):
        from coc_bot.progression.bulk_walls import BulkWalls
        def selected(count):
            return dict(level=3, count=count, price=5000*count, red=count == 4,
                        plus=(4, 4), minus=(5, 5), pay=(6, 6))
        with patch('coc_bot.progression.walls.wall_panel', return_value=self.panel), \
             patch('coc_bot.progression.walls.wall_balance', return_value=15739), \
             patch('coc_bot.progression.bulk_walls.control', return_value=(3, 3)), \
             patch.object(BulkWalls, 'settled', side_effect=[selected(i) for i in (1, 2, 3, 4, 3)]), \
             patch('coc_bot.progression.bulk_walls.selection', return_value=selected(3)), \
             patch('coc_bot.progression.bulk_walls.confirmation', return_value=(7, 7)):
            return WallUpgrade(self.r).run(self.row)

    def taps(self):
        return [call.args for call in self.r.input.tap.call_args_list]

    def test_single_links_original_images_and_readings_to_completed_receipt(self):
        self.assertEqual(self.single()['status'], 'started')
        receipt = self.state()['last_completed']
        self.assertEqual(self.taps(), [(1, 1), (2, 2)])
        [(ident, tag, before, confirmed)] = self.query('SELECT * FROM intents')
        self.assertEqual((ident, tag), (receipt['intent_id'], '#HOME'))
        self.assertEqual(json.loads(before)['balance_before'], 15739)
        self.assertIsNotNone(confirmed)
        rows = self.query('SELECT intent_id, stage, readings, png FROM observations ORDER BY rowid')
        self.assertEqual([r[1] for r in rows], ['before_queue', 'before_queue', 'after_panel'])
        self.assertEqual(json.loads(rows[-1][2]), {'level': 4, 'balance': 10739})
        for i, (key, _, _, png) in enumerate(rows):
            self.assertEqual(key, ident)
            np.testing.assert_array_equal(cv2.imdecode(np.frombuffer(png, np.uint8), 1), self.frames[i])

    def test_bulk_links_selection_and_two_scan_observations_to_one_payment(self):
        self.assertEqual(self.bulk()['status'], 'started')
        receipt = self.state()['last_completed']
        self.assertEqual((receipt['account'], receipt['count'], receipt['cost']), ('#HOME', 3, 15000))
        self.assertEqual(self.taps().count((6, 6)), 1)
        self.assertEqual(self.taps().count((7, 7)), 1)
        rows = self.query('SELECT intent_id, stage, readings FROM observations ORDER BY rowid')
        self.assertEqual({r[0] for r in rows}, {receipt['intent_id']})
        self.assertEqual([r[1] for r in rows], ['before_queue', 'before_queue', 'before_selection',
                                                 'bulk_dialog', 'after_inventory', 'after_inventory'])
        for _, _, readings in rows[-2:]:
            self.assertEqual(json.loads(readings)['remaining'], 222)
            self.assertEqual(json.loads(readings)['balance'], 739)

    def test_late_wall_balance_is_verified_without_repeating_payment(self):
        with patch('coc_bot.progression.bulk_walls.control', return_value=None), \
             patch('coc_bot.progression.walls.wall_panel', side_effect=[
                 self.panel, self.panel, self.panel, None, self.panel | {'level': 4}]), \
             patch('coc_bot.progression.walls.wall_balance', side_effect=[15739,15739,11012,10739]):
            self.assertEqual(WallUpgrade(self.r).run(self.row)['status'],'started')
        self.assertEqual(self.taps(), [(1,1),(2,2)])
        self.assertEqual(self.state()['last_completed']['level_after'],4)

    def test_unpaid_bulk_failure_reopens_and_pays_for_one_wall(self):
        with patch('coc_bot.progression.bulk_walls.control', return_value=(3, 3)), \
             patch('coc_bot.progression.bulk_walls.BulkWalls.run',
                   return_value={'status': 'blocked', 'message': 'Bulk preview unreadable'}), \
             patch('coc_bot.progression.walls.wall_panel',
                   side_effect=[self.panel] * 4 + [self.panel | {'level': 4}]), \
             patch('coc_bot.progression.walls.wall_balance', side_effect=[15739, 15739, 10739]):
            self.assertEqual(WallUpgrade(self.r).run(self.row)['status'], 'started')
        self.r.close.assert_called_once()
        self.assertEqual(self.taps(), [(1, 1), (1, 1), (2, 2)])
        receipt = self.state()['last_completed']
        self.assertTrue(receipt['single_wall_fallback'])
        self.assertEqual(receipt['level_after'], 4)

    def test_red_wall_price_is_skipped_before_payment(self):
        with patch('coc_bot.progression.walls.wall_panel', return_value=self.panel | {'red': True}), \
             patch('coc_bot.progression.bulk_walls.BulkWalls.run') as bulk:
            self.assertEqual(WallUpgrade(self.r).run(self.row)['status'], 'waiting')
        bulk.assert_not_called()
        self.assertEqual(self.taps(), [(1, 1)])
        self.assertEqual(self.state(), {})

    def test_bulk_with_pending_payment_cannot_fall_back(self):
        def uncertain(*args):
            self.r.path.write_text('{"pending":{"kind":"wall"}}')
            return {'status': 'needs_review'}
        with patch('coc_bot.progression.bulk_walls.control', return_value=(3, 3)), \
             patch('coc_bot.progression.bulk_walls.BulkWalls.run', side_effect=uncertain), \
             patch('coc_bot.progression.walls.wall_panel', return_value=self.panel), \
             patch('coc_bot.progression.walls.wall_balance', return_value=15739):
            self.assertEqual(WallUpgrade(self.r).run(self.row)['status'], 'needs_review')
        self.r.close.assert_not_called()
        self.assertEqual(self.taps(), [(1, 1)])

    def test_partial_before_failure_rolls_back_and_never_pays(self):
        original = evidence.insert_observation
        def fail_second(db, ident, stage, frame, readings):
            if db.execute('SELECT count(*) FROM observations').fetchone()[0]:
                raise sqlite3.OperationalError('full')
            original(db, ident, stage, frame, readings)
        for run in (self.single, self.bulk):
            self.r.capture.screenshot.side_effect = self.frames
            self.r.input.tap.reset_mock()
            with patch.object(evidence, 'insert_observation', side_effect=fail_second):
                self.assertEqual(run()['status'], 'blocked')
            self.assertFalse(self.r.path.exists())
            self.assertTrue(set(self.taps()).isdisjoint({(2, 2), (6, 6), (7, 7)}))
            self.assertEqual(self.query("SELECT name FROM sqlite_master WHERE type='table'"), [])

    def test_failed_after_write_retains_single_intent_for_read_only_recovery(self):
        original = evidence.insert_observation
        def fail_after(db, ident, stage, frame, readings):
            if stage == 'after_panel':
                raise OSError('disk full')
            original(db, ident, stage, frame, readings)
        with patch.object(evidence, 'insert_observation', side_effect=fail_after):
            self.assertEqual(self.single()['status'], 'needs_review')
        pending = self.state()['pending']
        self.assertEqual(self.query('SELECT confirmed_at FROM intents'), [(None,)])
        self.r.scan.return_value.update(balances={'gold': 10739}, rows=[self.row | {'quantity': 224}])
        self.assertEqual(WallUpgrade(self.r).recover(self.state())['status'], 'recovered')
        self.assertEqual(self.state()['last_completed']['intent_id'], pending['intent_id'])
        self.assertEqual(self.taps(), [(1, 1), (2, 2)])

    def test_bulk_dialog_write_failure_and_restart_never_send_confirmation(self):
        original = evidence.insert_observation
        def fail_dialog(db, ident, stage, frame, readings):
            if stage == 'bulk_dialog':
                raise sqlite3.OperationalError('disk full')
            original(db, ident, stage, frame, readings)
        with patch.object(evidence, 'insert_observation', side_effect=fail_dialog):
            self.assertEqual(self.bulk()['status'], 'needs_review')
        journal = self.r.path.read_bytes()
        with patch('coc_bot.progression.bulk_walls.confirmation', return_value=(7, 7)):
            self.assertEqual(WallUpgrade(self.r).recover(self.state())['status'], 'needs_review')
        self.assertEqual(self.r.path.read_bytes(), journal)
        self.assertEqual(self.taps().count((6, 6)), 1)
        self.assertNotIn((7, 7), self.taps())

    def test_uncertain_after_is_preserved_and_retention_only_recycles_confirmed(self):
        with patch.object(evidence, 'MAX_INTENTS', 2):
            self.assertEqual(self.single(balance=15500)['status'], 'needs_review')
            unresolved = self.state()['pending']
            after = self.query("SELECT readings, png FROM observations WHERE stage='after_panel'")
            self.assertEqual(json.loads(after[0][0])['balance'], 15500)
            # Simulate an operator archiving the journal; unresolved images stay pinned.
            self.r.path.unlink()
            self.r.capture.screenshot.side_effect = self.frames
            self.assertEqual(self.single()['status'], 'started')
            completed = self.state()['last_completed']['intent_id']
            self.r.capture.screenshot.side_effect = self.frames
            self.assertEqual(self.single(balance=15500)['status'], 'needs_review')
            ids = {row[0] for row in self.query('SELECT id FROM intents')}
            self.assertEqual(ids, {unresolved['intent_id'], self.state()['pending']['intent_id']})
            self.assertNotIn(completed, ids)
            self.r.path.unlink()
            self.r.input.tap.reset_mock()
            self.r.capture.screenshot.side_effect = self.frames
            self.assertEqual(self.single()['status'], 'blocked')
            self.assertEqual(self.taps(), [(1, 1)])
            self.assertEqual(after[0], self.query(
                "SELECT readings, png FROM observations WHERE stage='after_panel' ORDER BY rowid")[0])

    def test_foreign_account_cannot_attach_after_evidence(self):
        self.assertEqual(self.single(balance=15500)['status'], 'needs_review')
        journal = self.r.path.read_bytes()
        count = self.query('SELECT count(*) FROM observations')
        self.r.config.account_tag = '#OTHER'
        self.assertEqual(WallUpgrade(self.r).recover(self.state())['status'], 'needs_review')
        self.assertEqual(self.r.path.read_bytes(), journal)
        self.assertEqual(self.query('SELECT count(*) FROM observations'), count)
        self.assertEqual(self.taps(), [(1, 1), (2, 2)])

    def test_observation_and_png_limits_fail_closed(self):
        with patch.object(evidence, 'MAX_PNG_BYTES', 1):
            self.assertEqual(self.single()['status'], 'blocked')
        self.assertFalse(self.r.path.exists())
        self.r.capture.screenshot.side_effect = self.frames
        with patch.object(evidence, 'MAX_OBSERVATIONS', 2):
            self.assertEqual(self.single()['status'], 'needs_review')
            journal = self.r.path.read_bytes()
            self.assertEqual(WallUpgrade(self.r).recover(self.state())['status'], 'needs_review')
        self.assertEqual(self.query('SELECT stage FROM observations'), [('before_queue',)]*2)
        self.assertEqual(self.r.path.read_bytes(), journal)
        self.assertEqual(self.taps().count((2, 2)), 1)

    def test_intent_journal_failure_sends_no_payment(self):
        with patch('coc_bot.upgrades.runner.write_json', side_effect=OSError('disk full')):
            self.assertEqual(self.single()['status'], 'needs_review')
        self.assertFalse(self.r.path.exists())
        self.assertEqual(self.taps(), [(1, 1)])
        self.assertEqual(self.query('SELECT confirmed_at FROM intents'), [(None,)])

    def test_retention_marker_failure_keeps_durable_completion(self):
        from contextlib import contextmanager
        transact = evidence.transaction

        @contextmanager
        def fail_after_completion(runner):
            if self.state().get('last_completed'):
                raise evidence.EvidenceError('disk full')
            with transact(runner) as db:
                yield db

        with patch.object(evidence, 'transaction', fail_after_completion):
            self.assertEqual(self.single()['status'], 'started')
        self.assertIn('last_completed', self.state())
        self.assertNotIn('pending', self.state())
        self.assertEqual(self.query('SELECT confirmed_at FROM intents'), [(None,)])
        self.assertEqual(self.taps(), [(1, 1), (2, 2)])

    def test_builder_wall_keeps_its_existing_journal(self):
        self.r.inventory_directory = 'builder_base'
        self.assertEqual(self.single()['status'], 'started')
        self.assertNotIn('intent_id', self.state()['last_completed'])
        self.assertFalse(self.r.path.with_name('wall-evidence.sqlite3').exists())
