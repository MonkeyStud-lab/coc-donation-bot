import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from contextlib import nullcontext
from coc_bot.accounts.store import AccountStore,write
from coc_bot.accounts.rotation import RotationStore,AccountFleet
from coc_bot.control.lifecycle import RunOptions


class RotationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.store=AccountStore(self.root)
        self.main={'id':'a'*32,'tag':'#PYLQG','nickname':'Donor','selector':'Donor','original':True,'roles':['donating']}
        self.other={'id':'b'*32,'tag':'#YQGRJPC2L','nickname':'Test','selector':'Test','original':False,'roles':['upgrading']}
        write(self.store.path,{'version':1,'active':self.main['id'],'pending':None,'accounts':[self.main,self.other]})
        for account in (self.main,self.other):
            write(self.store.profile(account)/'data/clan/state.json',
                  {'account':account['tag'],'tag':'#PYLQG','checked_at':1000})
        self.rotation=RotationStore(self.store)

    def configure(self, **values):
        return self.rotation.configure(**({'enabled':True,'primary_id':self.main['id'],
                                           'watch_seconds':300,'visit_seconds':100,'interval_seconds':300}|values))

    def test_donation_majority_and_valid_roles_are_required(self):
        for values in ({'watch_seconds':300,'visit_seconds':101},{'primary_id':self.other['id']},
                       {'enabled':1},{'interval_seconds':0}):
            with self.subTest(values=values),self.assertRaises(ValueError):self.configure(**values)
        self.assertTrue(self.configure()['enabled'])

    def test_round_robin_never_selects_roleless_accounts_or_primary(self):
        self.configure();self.assertEqual(self.rotation.next_account(100)['id'],self.other['id'])
        self.rotation.complete(self.other['id'],100,99)
        self.assertIsNone(self.rotation.next_account(200))
        self.assertEqual(self.rotation.next_account(400)['id'],self.other['id'])
        self.store.update(self.other['id'],'Test',[])
        self.assertIsNone(self.rotation.next_account(500))

    def test_stop_freezes_account_visit_and_farm_due_times(self):
        self.configure();s=self.rotation.load();s['visits']={self.other['id']:{'next_visit_at':400,'next_farm_at':500}}
        write(self.rotation.path,s);self.rotation.pause(200);self.rotation.resume(1200)
        visit=self.rotation.load()['visits'][self.other['id']]
        self.assertEqual((visit['next_visit_at'],visit['next_farm_at']),(1400,1500))
        self.rotation.resume(1300)
        self.assertEqual(self.rotation.load()['visits'][self.other['id']]['next_farm_at'],1500)

    def test_long_goal_visit_does_not_starve_other_accounts_for_hours(self):
        self.configure();self.rotation.complete(self.other['id'],1000,500)
        self.assertEqual(self.rotation.load()['next_watch_seconds'],300)

    def test_interrupted_account_setup_cannot_enable_rotation(self):
        self.store.begin('add')
        with self.assertRaises(ValueError):self.configure()

    def test_existing_farm_timestamp_is_not_imported_into_resource_schedule(self):
        self.configure();fleet=AccountFleet(self.store,RunOptions(),clock=lambda:1000)
        tracker=Mock();tracker.state.last_completed_attack_id='historical'
        fleet.current=SimpleNamespace(config=SimpleNamespace(farm_enabled=True),tracker=tracker)
        fleet._initialize_schedule(self.main)
        visit=self.rotation.load()['visits'][self.main['id']]
        self.assertNotIn('next_farm_at',visit)
        self.assertEqual(visit['last_attack_id'],'historical')
        fleet._initialize_schedule(self.main)
        self.assertNotIn('next_farm_at',self.rotation.load()['visits'][self.main['id']])

    def test_long_upgrade_visits_cannot_starve_farm_and_builder_work(self):
        from coc_bot.bot import DonationBot
        self.configure()
        calls=[]
        for expected in ('requests','upgrades','farm','builder_base','layouts','requests'):
            bot=DonationBot.__new__(DonationBot)
            bot._stop_requested=False;bot._farm_requested=False
            bot.should_stop=lambda:False;bot._settings_stop_ready=lambda:False
            bot.config=SimpleNamespace(scan_interval_ms=(0,0),donation_enabled=False,data_dir=self.root)
            bot._check_watchdog=Mock();bot._maybe_anti_idle=Mock()

            bot.tracker=Mock()
            bot.capture=Mock();bot.nav_input=Mock();bot.navigator=Mock()
            bot._fleet_work_order=lambda:self.rotation.work_order(self.other['id'])
            bot._fleet_work_attempted=lambda kind:self.rotation.work_attempted(self.other['id'],kind,1000)
            def attempted(kind):
                calls.append(kind)
                return True  # Takes the whole visit: next opportunity is a new bot.
            bot._maybe_request_reinforcements=lambda:attempted('requests')
            bot._maybe_run_upgrades=lambda:attempted('upgrades')
            bot._maybe_run_farm=lambda:attempted('farm')
            bot._maybe_run_builder_base=lambda:attempted('builder_base')
            bot._maybe_run_layouts=lambda:attempted('layouts')
            with patch('coc_bot.attack.recovery.pending',return_value=None),\
                 patch('coc_bot.builder_base.runner.pending',return_value=None),\
                 patch('coc_bot.upgrades.runner.UpgradeRunner.state',return_value={}):
                bot._loop_tick()
            self.assertEqual(calls[-1],expected)
            # Recreating the store is part of the regression: an in-memory turn
            # would be lost each time the coordinator constructs a new bot.
            self.rotation=RotationStore(self.store)
        self.assertEqual(calls,['requests','upgrades','farm','builder_base','layouts','requests'])

    def test_skipped_tasks_keep_their_turn_and_donor_order_is_unchanged(self):
        self.configure()
        self.rotation.work_attempted(self.other['id'],'upgrades',100)
        self.assertEqual(self.rotation.work_order(self.other['id']),('farm','builder_base','layouts','requests','upgrades'))
        self.rotation.pause(150);self.rotation.resume(250)
        self.assertEqual(self.rotation.work_order(self.other['id'])[0],'farm')
        self.rotation.work_attempted(self.main['id'],'farm',300)
        self.assertEqual(self.rotation.work_order(self.main['id']),('requests','upgrades','farm','builder_base','layouts'))
        self.assertNotIn('next_work',self.rotation.load()['visits'].get(self.main['id'],{}))

    def test_unfinished_layout_gets_a_turn_before_scheduled_farming(self):
        from coc_bot.bot import DonationBot
        bot=DonationBot.__new__(DonationBot)
        bot._stop_requested=False;bot._farm_requested=False
        bot.should_stop=lambda:False;bot._settings_stop_ready=lambda:False
        bot.config=SimpleNamespace(data_dir=self.root,account_town_hall=10,layouts_enabled=True)
        bot._check_watchdog=Mock();bot._maybe_anti_idle=Mock()

        bot.tracker=Mock();bot.capture=Mock();bot.nav_input=Mock();bot.navigator=Mock()
        bot._fleet_work_order=lambda:('farm','builder_base','upgrades','layouts')
        bot._maybe_run_layouts=Mock(return_value=True)
        bot._maybe_run_upgrades=Mock(return_value=True);bot._maybe_run_farm=Mock(return_value=True)
        bot._maybe_run_builder_base=Mock(return_value=True)
        with patch('coc_bot.attack.recovery.pending',return_value=None),\
             patch('coc_bot.builder_base.runner.pending',return_value=None),\
             patch('coc_bot.upgrades.runner.UpgradeRunner.state',return_value={}):bot._loop_tick()
        bot._maybe_run_layouts.assert_called_once();bot._maybe_run_farm.assert_not_called()

    def test_pending_upgrade_blocks_even_an_explicit_farm_request(self):
        from coc_bot.bot import DonationBot
        self.configure();self.rotation.work_attempted(self.other['id'],'upgrades',100)
        bot=DonationBot.__new__(DonationBot)
        bot._stop_requested=False;bot._farm_requested=True
        bot.should_stop=lambda:False;bot._settings_stop_ready=lambda:False
        bot.config=SimpleNamespace(scan_interval_ms=(0,0),donation_enabled=False,data_dir=self.root)
        bot._check_watchdog=Mock();bot._maybe_anti_idle=Mock()

        bot.tracker=Mock();bot.capture=Mock();bot.nav_input=Mock();bot.navigator=Mock()
        bot._fleet_work_order=lambda:self.rotation.work_order(self.other['id'])
        bot._maybe_run_upgrades=Mock(return_value=True)
        bot._maybe_run_farm=Mock(return_value=True)
        bot._maybe_run_builder_base=Mock(return_value=True)
        with patch('coc_bot.attack.recovery.pending',return_value=None),\
             patch('coc_bot.builder_base.runner.pending',return_value=None),\
             patch('coc_bot.upgrades.runner.UpgradeRunner.state',return_value={'pending':{'kind':'obstacle'}}):
            bot._loop_tick()
        bot._maybe_run_upgrades.assert_called_once()
        bot._maybe_run_farm.assert_not_called();bot._maybe_run_builder_base.assert_not_called()

    def test_layout_receipt_recovery_precedes_even_a_manual_farm_and_upgrade_receipt(self):
        from coc_bot.bot import DonationBot
        write(self.root/'layouts/state.json',{'last_survey':{'payment':{'kind':'obstacle'}}})
        bot=DonationBot.__new__(DonationBot)
        bot._stop_requested=False;bot._farm_requested=True
        bot.should_stop=lambda:False;bot._settings_stop_ready=lambda:False
        bot.config=SimpleNamespace(data_dir=self.root)
        bot._check_watchdog=Mock();bot._maybe_anti_idle=Mock()

        bot.tracker=Mock();bot.capture=Mock();bot.nav_input=Mock();bot.navigator=Mock()
        bot._maybe_run_layouts=Mock(return_value=True)
        bot._maybe_run_upgrades=Mock(return_value=True);bot._maybe_run_farm=Mock(return_value=True)
        bot._maybe_run_builder_base=Mock(return_value=True)
        with patch('coc_bot.attack.recovery.pending',return_value=None),\
             patch('coc_bot.builder_base.runner.pending',return_value=None),\
             patch('coc_bot.upgrades.runner.UpgradeRunner.state',return_value={'pending':{'kind':'obstacle'}}):
            bot._loop_tick()
        bot._maybe_run_layouts.assert_called_once()
        bot._maybe_run_farm.assert_not_called();bot._maybe_run_upgrades.assert_not_called()
        bot._maybe_run_builder_base.assert_not_called()

    def test_one_lease_covers_visits_and_verified_returns_to_donor(self):
        self.configure();now=[1000];fleet=None;visited=[];switches=[]
        def factory(options):
            account=self.store.account();visited.append(account['id'])
            config=SimpleNamespace(data_dir=self.store.profile(account)/'data',adb_device='test')
            bot=SimpleNamespace(config=config,tracker=SimpleNamespace(
                state=SimpleNamespace(last_completed_attack_id=None)),capture=Mock(),nav_input=Mock(),navigator=Mock(),
                _has_donate_request=lambda _:False,request_stop=Mock())
            def run():
                if len(visited)==3:fleet.cancel.set();return
                now[0]+=301 if account['original'] else 101
                self.assertTrue(bot._fleet_should_yield())
            bot.run_owned=run
            return bot
        def switch(account):
            self.assertEqual(self.store.load()['pending']['target'],account['id'])
            switches.append(account['id']);return {'tag':account['tag']}
        fleet=AccountFleet(self.store,RunOptions(),factory=factory,clock=lambda:now[0])
        fleet._check_chat_before_switch=Mock()
        with patch('coc_bot.control.diagnostics.DebugSession',return_value=SimpleNamespace(config=SimpleNamespace(adb_device='test'))),\
             patch('coc_bot.accounts.startup.recognize_loaded',return_value=None),\
             patch('coc_bot.runtime.device_lease.DeviceLease',side_effect=lambda _:nullcontext()) as lease,\
             patch('coc_bot.accounts.navigation.AccountNavigator') as nav:
            nav.return_value.switch.side_effect=switch
            # Web controller threads inherit the initially selected profile.
            # The coordinator must re-pin each account after a handoff.
            with self.store.scope(self.main['id']):fleet.run()
        self.assertEqual(visited,[self.main['id'],self.other['id'],self.main['id']])
        self.assertEqual(switches,[self.other['id'],self.main['id']])
        self.assertEqual(lease.call_count,1)
        self.assertIsNone(self.store.load()['pending'])

    def test_final_handoff_check_recovers_same_account_without_switching_or_crashing(self):
        from coc_bot.donation.chat_check import ChatCheckUnverified
        self.configure();visited=[];fleet=None
        def factory(options):
            account=self.store.account();visited.append(account['id'])
            bot=SimpleNamespace(config=SimpleNamespace(data_dir=self.store.profile(account)/'data',adb_device='test'),
                tracker=SimpleNamespace(state=SimpleNamespace(last_completed_attack_id=None)),
                capture=Mock(),nav_input=Mock(),navigator=Mock())
            def run():
                fleet._next=self.other['id']
                if len(visited)==2:fleet.cancel.set()
            bot.run_owned=run;return bot
        fleet=AccountFleet(self.store,RunOptions(),factory=factory,clock=lambda:1000)
        fleet._check_chat_before_switch=Mock(side_effect=ChatCheckUnverified('Unreadable chat'))
        with patch('coc_bot.control.diagnostics.DebugSession',return_value=SimpleNamespace(config=SimpleNamespace(adb_device='test'))),\
             patch('coc_bot.accounts.startup.recognize_loaded',return_value=None),\
             patch('coc_bot.runtime.device_lease.DeviceLease',side_effect=lambda _:nullcontext()),\
             patch('coc_bot.stop.interrupted_sleep',return_value=False),\
             patch('coc_bot.accounts.navigation.AccountNavigator') as nav:
            with self.store.scope(self.main['id']):fleet.run()
        self.assertEqual(visited,[self.main['id'],self.main['id']])
        nav.return_value.switch.assert_not_called();self.assertIsNone(self.store.load()['pending'])

    def test_suspended_visit_preserves_cursor_and_returns_donor_time(self):
        self.configure()
        self.rotation.complete(self.other['id'],1000,120,suspended=True)
        state=self.rotation.load();visit=state['visits'][self.other['id']]
        self.assertNotIn('last_finished_at',visit)
        self.assertEqual(visit['next_visit_at'],1300)
        self.assertEqual(state['next_watch_seconds'],240)

    def test_deferred_builder_work_does_not_wait_another_full_half_hour(self):
        self.configure(interval_seconds=1800)
        write(self.store.profile(self.other)/'data/upgrades/maintenance.json',{
            'categories':{'buildings':{'status':'blocked','message':'Unreadable unpaid preview'}}})
        self.rotation.complete(self.other['id'],1000,90)
        self.assertEqual(self.rotation.load()['visits'][self.other['id']]['next_visit_at'],1300)

    def test_non_donor_request_routes_to_donor_and_persists_resume(self):
        self.configure();fleet=AccountFleet(self.store,RunOptions(),clock=lambda:1000)
        fleet.current=Mock();fleet.current.chat_monitor.find_donate_request.return_value=SimpleNamespace(signature='request')
        fleet.current._visit=None
        fleet.current.navigator.classifier._clan_chat_anchor_visible.return_value=True
        fleet._next=self.other['id']
        fleet._check_chat_before_switch(self.other)
        self.assertEqual(fleet._next,self.main['id'])
        self.assertEqual(self.rotation.load()['donation_detour']['resume'],self.other['id'])
        fleet.current.tracker.state.last_completed_attack_id=None
        fleet.current._has_donate_request.return_value=False
        self.assertTrue(fleet._checkpoint(self.main,990))
        self.assertEqual(fleet._next,self.other['id'])
        self.assertEqual(self.rotation.load()['donation_detour']['phase'],'returning')

    def closed_chat_fleet(self):
        # Use the real bot class: a broad Mock would hide a nonexistent _sleep.
        from coc_bot.bot import DonationBot
        self.configure();fleet=AccountFleet(self.store,RunOptions(),clock=lambda:1000)
        fleet.current=DonationBot.__new__(DonationBot)
        fleet.current.navigator=Mock();fleet.current.capture=Mock();fleet.current.chat_monitor=Mock()
        fleet.current.navigator.classifier._clan_chat_anchor_visible.side_effect=[False,True]
        fleet.current.chat_monitor.find_donate_request.return_value=None
        fleet._next=self.other['id']
        return fleet

    def test_closed_chat_is_opened_and_checked_without_a_bot_sleep_method(self):
        fleet=self.closed_chat_fleet()
        self.assertFalse(hasattr(fleet.current,'_sleep'))
        with patch('coc_bot.vision.battle_menu.home_build_control_visible',return_value=True),\
             patch('coc_bot.donation.chat_check.interrupted_sleep',return_value=False) as wait:
            fleet._check_chat_before_switch(self.other)
        fleet.current.navigator._open_clan_chat.assert_called_once()
        self.assertEqual(fleet.current.capture.screenshot.call_count,2)
        fleet.current.chat_monitor.find_donate_request.assert_called_once()
        self.assertEqual(wait.call_args.args[0],.5);self.assertFalse(wait.call_args.args[1]())
        self.assertEqual(fleet._next,self.other['id'])

    def test_request_found_after_opening_chat_routes_to_the_donor(self):
        fleet=self.closed_chat_fleet()
        fleet.current.chat_monitor.find_donate_request.return_value=SimpleNamespace(signature='request')
        with patch('coc_bot.vision.battle_menu.home_build_control_visible',return_value=True),\
             patch('coc_bot.donation.chat_check.interrupted_sleep',return_value=False):
            fleet._check_chat_before_switch(self.other)
        self.assertEqual(fleet._next,self.main['id'])
        self.assertEqual(self.rotation.load()['donation_detour']['resume'],self.other['id'])

    def test_stop_or_settings_restart_during_chat_wait_prevents_more_work(self):
        for finish in (False,True):
            fleet=self.closed_chat_fleet()
            def stop(seconds,should_stop):
                if finish:fleet.finish_action=True
                else:fleet.cancel.set()
                return should_stop()
            with patch('coc_bot.vision.battle_menu.home_build_control_visible',return_value=True),\
                 patch('coc_bot.donation.chat_check.interrupted_sleep',side_effect=stop):
                fleet._check_chat_before_switch(self.other)
            self.assertEqual(fleet.current.capture.screenshot.call_count,1)
            fleet.current.chat_monitor.find_donate_request.assert_not_called()
            self.assertNotIn('donation_detour',self.rotation.load())

    def test_chat_check_sends_no_inputs_after_stop_or_on_unknown_village(self):
        fleet=self.closed_chat_fleet();fleet.cancel.set()
        fleet._check_chat_before_switch(self.other)
        fleet.current.capture.screenshot.assert_not_called()
        fleet=self.closed_chat_fleet()
        with patch('coc_bot.vision.battle_menu.home_build_control_visible',return_value=False):
            with patch('coc_bot.runtime.verification.record_failure') as log, self.assertRaisesRegex(ValueError,'Home not verified'):
                fleet.current.config=SimpleNamespace(data_dir=self.root,account_tag=self.other['tag'])
                fleet._check_chat_before_switch(self.other)
            log.assert_called_once()
        fleet.current.navigator._open_clan_chat.assert_not_called()

    def test_donor_selection_is_random_from_all_donation_roles(self):
        self.configure();extra=self.other|{'id':'c'*32,'tag':'#PQLYCG','roles':['donating']}
        state=self.store.load();state['accounts'].append(extra);write(self.store.path,state)
        write(self.store.profile(extra)/'data/clan/state.json',
              {'account':extra['tag'],'tag':'#PYLQG','checked_at':1000})
        fleet=AccountFleet(self.store,RunOptions(),clock=lambda:1000);fleet.current=Mock()
        fleet.current.navigator.classifier._clan_chat_anchor_visible.return_value=True
        fleet.current.chat_monitor.find_donate_request.return_value=SimpleNamespace(signature='request')
        fleet._next=self.main['id']
        with patch('coc_bot.accounts.rotation.random.choice',return_value=extra) as choose:
            fleet._check_chat_before_switch(self.other)
        self.assertEqual({a['id'] for a in choose.call_args.args[0]},{self.main['id'],extra['id']})
        self.assertEqual(fleet._next,extra['id'])
