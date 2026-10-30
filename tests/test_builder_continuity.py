"""Restart identity, donation checkpoints, and resumable builder maintenance."""
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from coc_bot.accounts.store import AccountStore, write, read
from coc_bot.config import project_root, load_config
from coc_bot.runtime.visits import Visit


class StartupRecognitionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);shutil.copytree(project_root()/'config',self.root/'config')
        self.store=AccountStore(self.root)
        self.a=self.store.register({'tag':'#PYLQG','name':'Donor'},'Donor',['donating'])
        self.b=self.store.register({'tag':'#YQGRJPC2L','name':'Other'},'Other',['upgrading'])
        self.store.complete(self.a['tag'])
        self.session=SimpleNamespace(config=SimpleNamespace(data_dir=self.root/'data',adb_device='test'))
        self.nav=Mock();self.nav.identity.return_value={'tag':self.b['tag']}
        p=patch('coc_bot.accounts.navigation.AccountNavigator',return_value=self.nav);p.start();self.addCleanup(p.stop)
        from coc_bot.accounts.store import selected_account
        p=patch('coc_bot.config.load_config',side_effect=lambda:SimpleNamespace(adb_device='test',
                data_dir=self.store.profile(selected_account.get())/'data'))
        self.config_patch=p.start();self.addCleanup(p.stop)

    def recognize(self,stop=lambda:False):
        from coc_bot.accounts.startup import recognize_loaded
        return recognize_loaded(self.store,self.session,object(),stop)

    def test_saved_loaded_village_selects_its_own_profile_without_registering(self):
        before=self.store.profile(self.b)/'data/user_settings.yaml'
        original=before.read_bytes()
        proof=self.recognize()
        self.assertEqual(self.store.account()['id'],self.b['id'])
        self.assertEqual(proof.tag,self.b['tag'])
        self.assertEqual(before.read_bytes(),original)
        self.assertEqual(len(self.store.load()['accounts']),2)
        self.nav.switch.assert_not_called()

    def test_unknown_or_unverified_identity_never_selects_any_account(self):
        for identity in ({'tag':'#PQLYCG'},):
            self.nav.identity.return_value=identity
            with self.assertRaises(ValueError):self.recognize()
            self.assertEqual(self.store.account()['id'],self.a['id'])
        self.nav.identity.side_effect=ValueError('Two independent tags disagree')
        with self.assertRaises(ValueError):self.recognize()
        self.assertEqual(self.store.account()['id'],self.a['id'])

    def test_pending_source_or_target_payment_never_gets_abandoned(self):
        write(self.root/'data/upgrades/state.json',{'pending':{'phase':'confirming'}})
        self.assertIsNone(self.recognize());self.nav.identity.assert_not_called()
        write(self.root/'data/upgrades/state.json',{})
        write(self.store.profile(self.b)/'data/upgrades/state.json',{'pending':{'phase':'confirming'}})
        with self.assertRaisesRegex(ValueError,'unresolved'):self.recognize()
        self.assertEqual(self.store.account()['id'],self.a['id'])

    def test_registry_change_during_read_cannot_be_overwritten(self):
        self.nav.identity.side_effect=lambda:(self.store.begin('add') or {'tag':self.b['tag']})
        with self.assertRaisesRegex(ValueError,'changed'):self.recognize()
        self.assertIsNotNone(self.store.load()['pending'])

    def test_other_device_profile_cannot_inherit_this_device_lease(self):
        self.config_patch.side_effect=lambda:SimpleNamespace(adb_device='other-device',
            data_dir=self.store.profile(self.b)/'data')
        with self.assertRaisesRegex(ValueError,'same Android'):self.recognize()
        self.assertEqual(self.store.account()['id'],self.a['id'])


class BuilderMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.config=SimpleNamespace(data_dir=self.root,account_tag='#PYLQG',
                                    upgrade_buildings_enabled=True)
        self.visit=Visit(self.config,lambda:1000)

    def test_builder_preflight_precedes_refill_without_reindexing_old_journals(self):
        self.assertEqual(self.visit.order(),('upgrades',))
        self.visit.finish_step('upgrades',repeat=True)
        self.assertEqual(self.visit.order(),('upgrades',))
        self.visit.finish_step('upgrades')
        self.assertEqual(self.visit.order(),('farm',))
        self.assertEqual(self.visit.load()['step'],0)
        self.visit.finish_step('farm');self.visit.finish_step('requests')
        self.assertEqual(self.visit.order(),('upgrades',))

    def test_one_transaction_then_checkpoint_retains_lab_and_pet_queue_after_restart(self):
        from coc_bot.bot import DonationBot
        def bot():
            b=DonationBot.__new__(DonationBot)
            b.config=SimpleNamespace(**(vars(self.config)|{'dry_run':False,
                'upgrade_research_enabled':True,'upgrade_pets_enabled':True,
                'upgrade_interval_seconds':60,'donation_enabled':False,'progression_enabled':False}))
            b._visit=self.visit;b._state='scan_chat';b._stop_requested=False;b._next_upgrade_check=0
            b._visit_retry_at=None;b.should_stop=lambda:False
            b.capture=Mock();b.nav_input=Mock();b.navigator=Mock();b.game_state=Mock();b.set_mode=Mock()
            b._has_donate_request=Mock(return_value=False)
            return b
        with patch('coc_bot.upgrades.runner.UpgradeRunner') as factory:
            factory.return_value.state.return_value={}
            factory.return_value.run.side_effect=[{'status':'started'},{'status':'busy'},{'status':'busy'}]
            for expected in ('buildings','research','pets'):
                current=bot();self.assertTrue(current._maybe_run_upgrades())
                self.assertEqual(factory.return_value.run.call_args.args[0],expected)
                self.assertTrue(current._visit_repeat)
            self.assertEqual(factory.return_value.run.call_count,3)
        self.assertEqual(read(self.root/'upgrades/maintenance.json')['remaining'],['buildings'])

    def test_failed_unpaid_candidate_is_deferred_but_uncertain_payment_is_not(self):
        from coc_bot.progression.runner import ProgressionRunner
        r=ProgressionRunner.__new__(ProgressionRunner)
        r.path=self.root/'upgrades/state.json';r.stopped=lambda:False
        r.target={'name':'Gold Mine','new':True,'level':0,'cost':1000,'currency':'gold'}
        r._run_once=Mock(return_value={'status':'blocked','message':'Unpaid preview did not fit'})
        r.state=Mock(return_value={})
        self.assertTrue(r.run('buildings',execute=True)['retry_other_candidates'])
        self.assertIn(r.retry_key(r.target),read(r.path.with_name('candidate-retries.json')))
        r._run_once.return_value={'status':'no_room','message':'No safe building space'}
        self.assertTrue(r.run('buildings',execute=True)['retry_other_candidates'])
        self.assertIn('construction',read(r.path.with_name('candidate-retries.json')))
        r.state.return_value={'pending':{'phase':'confirming'}}
        self.assertNotIn('retry_other_candidates',r.run('buildings',execute=True))

    def test_default_reserves_do_not_idle_builders(self):
        # Test defaults independently of a user's local settings.
        from coc_bot.config import BotConfig
        for key in ('upgrade_builders_reserved','upgrade_gold_reserve','upgrade_elixir_reserve',
                    'upgrade_dark_elixir_reserve','builder_base_gold_reserve','builder_base_elixir_reserve'):
            self.assertEqual(BotConfig.__dataclass_fields__[key].default,0)

    def test_construction_filter_requires_two_agreeing_native_selections(self):
        from coc_bot.progression.runner import ProgressionRunner
        r=ProgressionRunner.__new__(ProgressionRunner)
        import numpy as np
        f=np.zeros((1000,1800,3),np.uint8)
        r.clear_filters=Mock(return_value=f);r.wait=lambda:False;r.stopped=lambda:False
        r.capture=Mock();r.capture.screenshot.return_value=f;r.input=Mock();r.reader=Mock()
        r.reader.filters_open.return_value=True
        point=(round(1800*.418),240)
        r.reader.selected_filter.side_effect=[None,point,point]
        r.reader.menu_kind.return_value='buildings'
        self.assertIs(r.filter_resource(f,'gold'),f)
        r.reader.label.assert_not_called()
        r.reader.selected_filter.side_effect=[None,point,(100,100)]
        with self.assertRaisesRegex(ValueError,'changed'):r.filter_resource(f,'gold')
