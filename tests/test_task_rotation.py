from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
from contextlib import nullcontext

from coc_bot.accounts.store import AccountStore, write
from coc_bot.accounts.rotation import AccountFleet, RotationStore
from coc_bot.control.lifecycle import RunOptions
from coc_bot.bot import DonationBot


class TaskRotationTests(TestCase):
    def setUp(self):
        temp=TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.store=AccountStore(temp.name)
        self.accounts=[dict(id=c*32,tag=tag,nickname=c,original=i==0,
                           roles=['donating','farming'] if i==0 else ['farming','upgrading'])
                       for i,(c,tag) in enumerate(zip('abc',('#PYLQG','#YQGRJPC2L','#PQLYCG')))]
        write(self.store.path,dict(version=1,active=self.accounts[0]['id'],pending=None,accounts=self.accounts))
        self.rotation=RotationStore(self.store)
        self.rotation.configure(enabled=True,primary_id=self.accounts[0]['id'],task_driven=True,
                                watch_seconds=900,visit_seconds=180,interval_seconds=1800)
        self.now=1000

    def fleet(self,index=0):
        fleet=AccountFleet(self.store,RunOptions(),clock=lambda:self.now)
        fleet._clan_checked=True;fleet._chat_due=False
        fleet.current=SimpleNamespace(config=SimpleNamespace(data_dir=self.store.profile(self.accounts[index])/'data'),
            tracker=SimpleNamespace(state=SimpleNamespace(last_completed_attack_id=None)),
            _visit=SimpleNamespace(complete=lambda:False,order=lambda:('farm',)),
            _visit_chat_pending=False,_farm_chat_check_due=False,capture=Mock())
        return fleet

    def test_donor_yields_without_chat_quota_and_secondary_goes_directly_to_next(self):
        fleet=self.fleet()
        self.assertTrue(fleet._checkpoint(self.accounts[0],800))
        self.assertEqual(fleet._next,self.accounts[1]['id'])
        self.assertEqual(fleet._watch.seconds,0)
        self.rotation.complete(self.accounts[0]['id'],1000,200,suspended=True)
        fleet=self.fleet(1)
        self.assertTrue(fleet._checkpoint(self.accounts[1],800))
        self.assertEqual(fleet._next,self.accounts[2]['id'])
        self.rotation.complete(self.accounts[1]['id'],1001,200,suspended=True)
        self.rotation.complete(self.accounts[2]['id'],1002,200,suspended=True)
        self.assertEqual(self.rotation.next_account(1003,current_id=self.accounts[2]['id'])['id'],self.accounts[0]['id'])

    def test_owned_run_does_not_gate_donor_work_or_return_between_other_accounts(self):
        visited=[];fleet=None
        def factory(options):
            account=self.store.account();visited.append(account['id'])
            bot=SimpleNamespace(config=SimpleNamespace(data_dir=self.store.profile(account)/'data',adb_device='test'),
                tracker=SimpleNamespace(state=SimpleNamespace(last_completed_attack_id=None)),
                capture=Mock(),nav_input=Mock(),navigator=Mock(),_visit_chat_pending=False)
            def run():
                self.assertTrue(bot._fleet_task_driven)
                self.now+=200
                self.assertTrue(bot._fleet_work_order())  # No chat credit was earned.
                if len(visited)==4:fleet.cancel.set();return
                self.assertTrue(bot._fleet_should_yield())
            bot.run_owned=run
            return bot
        fleet=AccountFleet(self.store,RunOptions(),factory=factory,clock=lambda:self.now)
        fleet._check_chat_before_switch=Mock(return_value=True)
        with patch('coc_bot.control.diagnostics.DebugSession',return_value=SimpleNamespace(config=SimpleNamespace(adb_device='test'))),\
             patch('coc_bot.accounts.startup.recognize_loaded',return_value=None),\
             patch('coc_bot.runtime.device_lease.DeviceLease',side_effect=lambda _:nullcontext()) as lease,\
             patch('coc_bot.accounts.navigation.AccountNavigator') as nav:
            nav.return_value.switch.side_effect=lambda account:{'tag':account['tag']}
            fleet.run()
        self.assertEqual(visited,[a['id'] for a in self.accounts]+[self.accounts[0]['id']])
        self.assertEqual(lease.call_count,1)

    def test_chat_after_attack_and_upgrade_runs_before_more_work(self):
        for attack in (False,True):
            fleet=self.fleet(1);fleet._chat_due=not attack
            fleet.current._farm_chat_check_due=attack
            fleet._check_chat_before_switch=Mock(return_value=True)
            self.assertFalse(fleet._checkpoint(self.accounts[1],999))
            fleet._check_chat_before_switch.assert_called_once_with(self.accounts[1])
            self.assertFalse(fleet._chat_due)
            self.assertFalse(fleet.current._farm_chat_check_due)

    def test_pending_battle_payment_and_placement_prevent_handoff_and_chat(self):
        for path,value in (('upgrades/state.json',{'pending':{'cost':123}}),
                           ('layouts/state.json',{'pending':{'held':True}}),
                           ('layouts/state.json',{'last_survey':{'payment':{'cost':1}}})):
            fleet=self.fleet();fleet._chat_due=True;fleet._check_chat_before_switch=Mock()
            target=fleet.current.config.data_dir/path;write(target,value)
            self.assertFalse(fleet._checkpoint(self.accounts[0],0))
            fleet._check_chat_before_switch.assert_not_called();target.unlink()
        for module in ('coc_bot.attack.recovery.pending','coc_bot.builder_base.runner.pending'):
            fleet=self.fleet();fleet._check_chat_before_switch=Mock();fleet._chat_due=True
            with patch(module,return_value=True):self.assertFalse(fleet._checkpoint(self.accounts[0],0))
            fleet._check_chat_before_switch.assert_not_called()

    def test_donation_detour_returns_after_one_pass_without_waiting_for_request_to_disappear(self):
        state=self.rotation.load();state['donation_detour']={'donor':self.accounts[0]['id'],
            'resume':self.accounts[1]['id'],'source':self.accounts[1]['id'],'phase':'donating'}
        write(self.rotation.path,state)
        fleet=self.fleet();fleet.current._visit_chat_pending=True
        self.assertFalse(fleet._checkpoint(self.accounts[0],999))
        fleet.current._visit_chat_pending=False
        self.assertTrue(fleet._checkpoint(self.accounts[0],999))
        self.assertEqual(fleet._next,self.accounts[1]['id'])
        fleet.current.capture.screenshot.assert_not_called()

    def test_mode_change_clears_old_scheduling_delay_only_and_old_clients_preserve_mode(self):
        state=self.rotation.load();state['task_driven']=False
        state['visits']={self.accounts[1]['id']:{'next_visit_at':9000,'last_checked_at':700}}
        write(self.rotation.path,state)
        path=self.store.profile(self.accounts[1])/'data/visits/state.json'
        write(path,{'step':2,'deferred':{'farm':{'retry_at':7000}}})
        before=path.read_bytes()
        self.rotation.configure(enabled=True,primary_id=self.accounts[0]['id'],task_driven=True)
        self.assertEqual(path.read_bytes(),before)
        self.assertEqual(self.rotation.load()['visits'][self.accounts[1]['id']]['next_visit_at'],0)
        self.rotation.configure(enabled=True,primary_id=self.accounts[0]['id'])
        self.assertTrue(self.rotation.load()['task_driven'])

    def test_suspended_work_is_due_next_turn_and_completed_work_keeps_own_recheck(self):
        self.rotation.complete(self.accounts[1]['id'],1000,300,suspended=True)
        self.assertEqual(self.rotation.load()['visits'][self.accounts[1]['id']]['next_visit_at'],1000)
        write(self.store.profile(self.accounts[1])/'data/visits/state.json',{'next_check_at':1300})
        self.rotation.complete(self.accounts[1]['id'],1000,300)
        self.assertEqual(self.rotation.load()['visits'][self.accounts[1]['id']]['next_visit_at'],1300)
        self.assertNotIn('next_watch_seconds',self.rotation.load())

    def test_no_due_task_does_not_trigger_permanent_donor_chat_scan(self):
        bot=DonationBot.__new__(DonationBot)
        bot._stop_requested=False;bot._farm_requested=False;bot._state='scan_chat'
        bot._fleet_task_driven=True;bot._fleet_work_order=lambda:()
        bot.config=SimpleNamespace(data_dir=Path(self.store.root)/'empty',donation_enabled=True)
        bot.should_stop=lambda:False;bot._settings_stop_ready=lambda:False
        bot._check_watchdog=Mock();bot._maybe_anti_idle=Mock();bot.tracker=Mock()
        bot.capture=Mock();bot.nav_input=Mock();bot.navigator=Mock();bot._chat_tick=Mock()
        with patch('coc_bot.upgrades.runner.UpgradeRunner.state',return_value={}),\
             patch('coc_bot.bot.interrupted_sleep',return_value=False):bot._loop_tick()
        bot._chat_tick.assert_not_called()

    def test_overdue_building_check_gets_a_turn_before_attack_handoff(self):
        self.rotation.configure(enabled=True, primary_id=self.accounts[0]['id'],
                                attack_target_per_hour=3)
        account = self.accounts[1]
        self.rotation.record_farming(account['id'], self.now, completed=True)
        fleet = self.fleet(1)
        fleet.current.config.upgrade_buildings_enabled = True
        fleet.current.config.upgrade_builders_reserved = 0
        self.assertFalse(fleet._checkpoint(account, self.now - 200))
        write(fleet.current.config.data_dir / 'upgrades/maintenance.json',
              {'categories': {'buildings': {'at': self.now, 'status': 'started', 'availability': [3, 4]}}})
        self.assertTrue(fleet._checkpoint(account, self.now - 200))
        fleet.current._fleet_building_checks = 1
        self.assertFalse(fleet._checkpoint(account, self.now - 200))
        fleet.current._fleet_building_checks = 3
        self.assertTrue(fleet._checkpoint(account, self.now - 200))

    def test_finished_donation_pass_does_not_hold_work_for_repeated_requests(self):
        bot=DonationBot.__new__(DonationBot)
        bot._stop_requested=False;bot._farm_requested=False;bot._state='donate'
        bot._fleet_task_driven=True;bot._visit=Mock();bot._visit_chat_pending=True
        bot.config=SimpleNamespace(data_dir=Path(self.store.root)/'empty',donation_enabled=True)
        bot.should_stop=lambda:False;bot._settings_stop_ready=lambda:False
        bot._check_watchdog=Mock();bot._maybe_anti_idle=Mock();bot.tracker=Mock()
        bot._do_donate=Mock(side_effect=lambda:setattr(bot,'_state','scan_chat'))
        bot._loop_tick()
        bot._do_donate.assert_called_once();self.assertFalse(bot._visit_chat_pending)

    def test_visit_checks_castle_before_maintenance_without_advancing_checklist(self):
        bot = DonationBot.__new__(DonationBot)
        bot._stop_requested = False
        bot._farm_requested = False
        bot._state = 'scan_chat'
        bot._fleet_task_driven = True
        bot._visit = Mock()
        bot._visit.deferred.return_value = None
        bot._fleet_work_order = lambda: ('upgrades',)
        bot.config = SimpleNamespace(data_dir=Path(self.store.root) / 'empty', donation_enabled=False)
        bot.should_stop = lambda: False
        bot._settings_stop_ready = lambda: False
        bot._check_watchdog = Mock()
        bot._maybe_anti_idle = Mock()
        bot.tracker = Mock()
        bot.capture = Mock()
        bot.nav_input = Mock()
        bot.navigator = Mock()
        bot._maybe_request_reinforcements = Mock(return_value=True)
        bot._maybe_run_upgrades = Mock(return_value=True)
        with patch('coc_bot.upgrades.runner.UpgradeRunner.state', return_value={}):
            bot._loop_tick()
            bot._maybe_request_reinforcements.assert_called_once()
            bot._maybe_run_upgrades.assert_not_called()
            bot._visit.finish_step.assert_not_called()
            bot._loop_tick()
            bot._maybe_request_reinforcements.assert_called_once()
            bot._maybe_run_upgrades.assert_called_once()
