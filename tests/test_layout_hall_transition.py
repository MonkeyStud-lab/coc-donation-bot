"""Hall-specific scheduling, account isolation and native editor deferral."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch
import numpy as np

from coc_bot.accounts.hall import observe_hall
from coc_bot.accounts.store import AccountStore, read, write
from coc_bot.layouts.runner import LayoutRunner, REVISION
from coc_bot.progression.runner import ProgressionRunner


class HallTransitionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.account = {'id':'a'*32,'tag':'#PYLQG','nickname':'Starter','roles':['upgrading'],
                        'town_hall':2,'original':True}
        self.other = {'id':'b'*32,'tag':'#YQGRJPC2L','nickname':'Other','roles':['upgrading'],
                      'town_hall':12,'original':False}
        self.store = AccountStore(self.root)
        write(self.store.path, {'version':1,'active':self.account['id'],
                               'accounts':[self.account,self.other],'pending':None})
        self.config = SimpleNamespace(data_dir=self.root/'data',account_tag=self.account['tag'],
            account_town_hall=2,layouts_enabled=True,dry_run=False,donation_enabled=False,
            progression_clear_obstacles=True,layouts_replace_inactive=True)

    def test_current_level_updates_runtime_and_only_its_registry_entry(self):
        path = self.config.data_dir/'layouts/state.json'
        old = {'automatic':{'hall':2,'next_check_at':9999999999},'completed':{'hall':2}}
        write(path,old)
        self.assertTrue(observe_hall(self.config,3))
        self.assertEqual(self.config.account_town_hall,3)
        self.assertEqual(self.store.account()['town_hall'],3)
        self.assertEqual(self.store.account(self.other['id'])['town_hall'],12)
        self.assertEqual(read(path),old)  # Preserve the old layout until native replacement succeeds.
        self.assertFalse(observe_hall(self.config,3))

    def test_secondary_profile_observation_cannot_update_the_donor(self):
        state = self.store.load(); state['active']=self.other['id']; write(self.store.path,state)
        self.config.data_dir=self.store.profile(self.other)/'data'
        self.config.account_tag=self.other['tag']; self.config.account_town_hall=12
        self.assertTrue(observe_hall(self.config,13))
        self.assertEqual(self.store.account()['town_hall'],13)
        self.assertEqual(self.store.account(self.account['id'])['town_hall'],2)

    def test_wrong_profile_or_an_unfinished_switch_cannot_write_hall(self):
        self.config.account_tag=self.other['tag']
        with self.assertRaisesRegex(ValueError,'active account'):observe_hall(self.config,3)
        self.config.account_tag=self.account['tag']
        state=self.store.load(); state['pending']={'kind':'switch','target':self.other['id']}
        write(self.store.path,state)
        with self.assertRaisesRegex(ValueError,'active account'):observe_hall(self.config,3)
        self.assertEqual(self.store.account()['town_hall'],2)

    def test_regression_and_noninteger_halls_never_trigger_a_layout(self):
        self.config.account_town_hall=3
        with self.assertRaisesRegex(ValueError,'below'):observe_hall(self.config,2)
        for level in (True,None,'3',3.0,1,19):self.assertFalse(observe_hall(self.config,level))
        self.assertEqual(self.store.account()['town_hall'],2)

    def test_stale_account_chooser_cannot_undo_a_completed_upgrade(self):
        observe_hall(self.config,3)
        account=self.store.complete(self.account['tag'],hall=2)
        self.assertEqual(account['town_hall'],3)
        account=self.store.complete(self.account['tag'],hall=4)
        self.assertEqual(account['town_hall'],4)

    def test_unscoped_army_reader_cannot_create_account_metadata(self):
        self.assertFalse(observe_hall(SimpleNamespace(account_tag=None),3))
        self.assertEqual(self.store.account()['town_hall'],2)

    def session(self):
        return SimpleNamespace(config=self.config,capture=Mock(),input=Mock(),navigator=Mock())

    def test_th2_and_th3_defer_without_any_game_inputs(self):
        s=self.session(); runner=LayoutRunner(s)
        for hall in (2,3):
            self.config.account_town_hall=hall
            with patch('coc_bot.layouts.runner.time.time',return_value=100):result=runner.run()
            self.assertEqual(result['status'],'unavailable')
            self.assertIn('leaving the base unchanged',result['message'])
            automatic=read(runner.i.path)['automatic']
            self.assertEqual(automatic['hall'],hall)
            self.assertEqual(automatic['next_check_at'],3700)
        s.input.tap.assert_not_called(); s.capture.screenshot.assert_not_called()

    def test_unlocked_hall_bypasses_the_starter_cooldown_and_uses_its_own_link(self):
        s=self.session(); r=LayoutRunner(s)
        r.run(); self.config.account_town_hall=4
        r.home=Mock(return_value=True)
        r._clear_one=Mock(return_value={'status':'waiting'})
        self.assertEqual(r.run()['status'],'waiting')
        url,hall,_=r._clear_one.call_args.args
        self.assertEqual(hall,4); self.assertIn('TH4%3AHV%3A',url)
        automatic=read(r.i.path)['automatic']
        self.assertEqual(automatic['hall'],4); self.assertEqual(automatic['revision'],REVISION)
        self.assertEqual(automatic['stage'],'clearing')

    def scan(self, badge):
        frame=np.zeros((1048,1853,3),np.uint8)
        r=ProgressionRunner(self.config,Mock(),Mock(),Mock()); r.clear_filters=lambda f:f
        r.reader=Mock(); r.reader.balances.return_value={}; r.reader.availability.return_value=(2,2)
        r.reader.menu_kind.return_value='buildings'
        row={'name':'Town Hall','currency':'gold','cost':4000,'new':False,
             'target_level':badge,'box':[1358,715,495,117]}
        r.reader.rows.return_value=[row]; r.capture.screenshot.return_value=frame
        r.wait=Mock(return_value=False)
        return r.scan(frame)

    def test_native_next_level_badge_does_not_claim_an_upgrade_is_complete(self):
        inventory=self.scan(3)
        self.assertTrue(inventory['hall_verified']); self.assertEqual(inventory['hall'],2)
        self.assertEqual(self.config.account_town_hall,2)
        self.assertEqual(self.store.account()['town_hall'],2)

    def test_completed_upgrade_detected_by_progression_refreshes_the_layout_level(self):
        inventory=self.scan(4)
        self.assertTrue(inventory['complete']); self.assertEqual(inventory['hall'],3)
        self.assertEqual(self.config.account_town_hall,3)
        self.assertEqual(self.store.account()['town_hall'],3)
