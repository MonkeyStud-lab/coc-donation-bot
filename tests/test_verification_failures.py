import json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch

from coc_bot.accounts.store import read,write
from coc_bot.runtime.verification import fingerprint,record_failure,log_result,resolve_receipt
from coc_bot.builder_base.verification import deferred
from coc_bot.builder_base.runner import BuilderBaseRunner,pending


class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.config=SimpleNamespace(data_dir=Path(self.temp.name),account_tag='#TEST',dry_run=False)
        self.path=self.config.data_dir/'builder_base/upgrades.json'
        self.receipt={'kind':'construction','row':{'name':'Wall','currency':'free','cost':0,'quantity':18},
                      'before':{'gold':5000,'elixir':8053,'gems':297}}

    def test_failures_survive_restart_deduplicate_and_bound_the_log(self):
        first=record_failure(self.config,'builder_base.upgrades','Unreadable wall',pending=self.receipt)
        second=record_failure(self.config,'builder_base.upgrades','Unreadable wall',pending=self.receipt)
        self.assertEqual(first,second)
        path=self.config.data_dir/'verification/failures.json';values=json.loads(path.read_text())
        self.assertEqual(values[0]['count'],2);self.assertEqual(values[0]['receipt'],self.receipt)
        self.assertEqual(values[0]['account'],'#TEST')
        for n in range(105):record_failure(self.config,'test',str(n))
        self.assertEqual(len(json.loads(path.read_text())),100)
        self.assertIsNone(log_result(self.config,'test',{'status':'started'}))

    def test_later_independent_verification_resolves_only_its_exact_receipt(self):
        record_failure(self.config,'builder_base.upgrades','Unreadable wall',pending=self.receipt)
        path=self.config.data_dir/'verification/failures.json'
        resolve_receipt(self.config,self.receipt|{'at':99})
        self.assertEqual(json.loads(path.read_text())[0]['status'],'needs_review')
        resolve_receipt(self.config,self.receipt)
        entry=json.loads(path.read_text())[0]
        self.assertEqual(entry['status'],'resolved');self.assertIn('resolved_at',entry)

    def test_logging_io_failure_does_not_turn_a_failed_check_into_a_crash(self):
        with patch('coc_bot.runtime.verification.write_json',side_effect=OSError('disk full')):
            self.assertTrue(record_failure(self.config,'builder_base','Unreadable quantity'))

    def marker(self):
        return {'account':'#TEST','fingerprint':fingerprint(self.receipt),'home_verified_at':123}

    def test_only_the_same_receipt_and_account_can_use_the_verified_home_marker(self):
        write(self.path,{'pending':self.receipt,'deferred_receipt':self.marker()})
        self.assertTrue(deferred(self.config));self.assertFalse(pending(self.config))
        for marker in ({},None,[],self.marker()|{'account':'#OTHER'},self.marker()|{'home_verified_at':None}):
            write(self.path,{'pending':self.receipt,'deferred_receipt':marker})
            self.assertFalse(deferred(self.config));self.assertTrue(pending(self.config))
        changed=self.receipt|{'at':999}
        write(self.path,{'pending':changed,'deferred_receipt':self.marker()})
        self.assertTrue(pending(self.config))
        write(self.path,{'pending':self.receipt,'deferred_receipt':self.marker()})
        write(self.config.data_dir/'builder_base/visit.json',{'phase':'battle'})
        self.assertTrue(pending(self.config))

    def runner(self):
        r=BuilderBaseRunner(self.config,Mock(),Mock(),Mock(),Mock())
        r.frame=Mock(return_value=object());r.reader=Mock()
        r.reader.home.return_value=True;r.reader.battle.return_value=False;r.reader.result_button.return_value=None
        r.home_village=Mock(return_value=True);r.evidence=Mock();r.finish=Mock()
        return r

    def test_safe_return_preserves_the_receipt_and_releases_other_work(self):
        write(self.path,{'pending':self.receipt});r=self.runner()
        with patch('coc_bot.builder_base.progression.BuilderProgressionRunner') as receipt:
            receipt.return_value.construction_controls.return_value=None
            result=r.pause_upgrades({'message':'Unreadable wall quantity'})
        self.assertEqual(result['status'],'deferred');r.finish.assert_called_once()
        self.assertEqual(read(self.path)['pending'],self.receipt)
        self.assertTrue(deferred(self.config));self.assertFalse(pending(self.config))
        r.input.tap.assert_not_called()
        r.frame.reset_mock()
        self.assertEqual(r.run()['status'],'deferred');r.frame.assert_not_called()

    def test_held_placement_or_unknown_village_still_blocks_handoff(self):
        for placement,home in (({'confirm':(1,1)},True),(None,False)):
            write(self.path,{'pending':self.receipt});r=self.runner();r.reader.home.return_value=home
            with patch('coc_bot.builder_base.progression.BuilderProgressionRunner') as receipt:
                receipt.return_value.construction_controls.return_value=placement
                with self.assertRaisesRegex(ValueError,'unsettled screen'):r.pause_upgrades({'message':'Failed'})
            self.assertTrue(pending(self.config));r.finish.assert_not_called();r.input.tap.assert_not_called()

    def test_home_proof_failure_stop_or_changed_receipt_never_release_the_guard(self):
        from coc_bot.adb.client import AdbStopped
        for mode in ('home','stop','changed'):
            write(self.path,{'pending':self.receipt});r=self.runner()
            if mode=='home':
                r.home_village.return_value=False;r.nav.classifier._clan_chat_anchor_visible.return_value=False
            elif mode=='stop':r.finish.side_effect=AdbStopped('Stopped')
            else:r.finish.side_effect=lambda:write(self.path,{'pending':self.receipt|{'at':99}})
            with patch('coc_bot.builder_base.progression.BuilderProgressionRunner') as receipt:
                receipt.return_value.construction_controls.return_value=None
                with self.assertRaises((ValueError,AdbStopped)):r.pause_upgrades({'message':'Failed'})
            self.assertTrue(pending(self.config));self.assertNotIn('deferred_receipt',read(self.path))
