import tempfile
import shutil
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from coc_bot.accounts.store import write, read, AccountStore
from coc_bot.runtime.resource_farming import decide,record_outcome,thresholds
from coc_bot.runtime.visits import Visit, STEPS
from coc_bot.accounts.clan import donors_for, membership


def observation(gold=100, elixir=100, **extra):
    return {'resources':['gold','elixir'], 'balances':{'gold':gold,'elixir':elixir},
            'capacities':{'gold':100,'elixir':100}}|extra


class ResourcePolicyTests(unittest.TestCase):
    def test_hysteresis_starts_low_and_continues_to_target(self):
        state={}
        self.assertFalse(decide(observation(80,80),state).attack)
        self.assertTrue(decide(observation(74,80),state).attack)
        self.assertTrue(decide(observation(85,90),state).attack)
        self.assertFalse(decide(observation(95,100),state).attack)
        self.assertFalse(state['refilling'])
        self.assertFalse(decide(observation(80,80),state).attack)

    def test_unlocked_dark_shortage_triggers_even_when_gold_full(self):
        value=observation();value['resources'].append('dark_elixir')
        value['balances']['dark_elixir']=10;value['capacities']['dark_elixir']=100
        self.assertEqual(decide(value,{}).resources,('dark_elixir',))

    def test_overflow_is_full_but_locked_dark_never_required(self):
        self.assertFalse(decide(observation(200,100),{}).attack)

    def test_unknown_or_conflicting_reads_never_attack(self):
        for value in ({},observation(None,10),observation(-1,10),
                      observation(capacities={'gold':0,'elixir':100}),
                      observation(resources=['gems']),observation(True,10)):
            with self.subTest(value=value):self.assertEqual(decide(value,{}).status,'unverified')

    def test_percent_targets_are_ordered_and_strictly_typed(self):
        for a,b in ((95,75),(100,100),(0,90),(True,95),(75,101)):
            with self.assertRaises(ValueError):thresholds(a,b)

    def test_full_gold_gains_do_not_mask_no_elixir_progress(self):
        state={}
        for _ in range(3):record_outcome(state,{'gold':100,'elixir':10},{'gold':120,'elixir':10},('elixir',))
        self.assertEqual(state['no_progress'],3)
        record_outcome(state,{'elixir':10},{'elixir':12},('elixir',))
        self.assertEqual(state['no_progress'],0)


class VisitTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.config=SimpleNamespace(data_dir=Path(self.temp.name),account_tag='#PYLQG')
        self.now=[1000];self.visit=Visit(self.config,lambda:self.now[0])

    def test_refill_can_span_more_than_three_minutes_and_restarts(self):
        for _ in range(5):
            self.visit.finish_step('farm',repeat=True);self.now[0]+=240
            self.visit=Visit(self.config,lambda:self.now[0])
            self.assertEqual(self.visit.order(),('farm',))
        self.visit.finish_step('farm');self.assertEqual(self.visit.order(),('requests',))

    def test_farm_first_keeps_the_rest_of_the_saved_checklist(self):
        self.config.upgrade_buildings_enabled = True
        self.assertEqual(self.visit.order(), ('upgrades',))
        self.assertEqual(self.visit.order(farm_first=True), ('farm',))
        for step in ('farm', 'requests'):
            self.visit.finish_step(step)
        self.assertEqual(self.visit.order(farm_first=True), ('upgrades',))

    def test_full_checklist_and_disabled_steps_finish_before_visit_ends(self):
        for step in STEPS:
            self.assertFalse(self.visit.complete());self.assertEqual(self.visit.order(),(step,))
            self.visit.finish_step(step)
        self.assertTrue(self.visit.complete());self.assertEqual(self.visit.order(),())
        self.now[0]+=301;self.assertEqual(self.visit.order(),('farm',))

    def test_deferred_farming_does_not_starve_upgrades_or_builder_base(self):
        self.visit.finish_step('farm',reason='unreadable',retry_at=2000)
        for step in STEPS[1:]:self.visit.finish_step(step)
        self.now[0]=1400;self.assertEqual(self.visit.order(),('farm',))
        self.assertEqual(self.visit.deferred('farm')['retry_at'],2000)
        self.now[0]=2001;self.assertIsNone(self.visit.deferred('farm'))

    def test_wrong_account_cannot_resume_saved_work(self):
        self.visit.finish_step('farm',repeat=True)
        self.config.account_tag='#YQGRJPC2L'
        with self.assertRaises(ValueError):self.visit.load()


class ClanRoutingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=AccountStore(Path(self.temp.name))
        self.source={'id':'a'*32,'tag':'#PYLQG','original':True,'roles':['farming']}
        self.same={'id':'b'*32,'tag':'#YQGRJPC2L','original':False,'roles':['donating']}
        self.other={'id':'c'*32,'tag':'#PQLYCG','original':False,'roles':['donating']}
        write(self.store.path,{'version':1,'accounts':[self.source,self.same,self.other],
                               'active':self.source['id'],'pending':None})
        for account,clan in ((self.source,'#PYLQG'),(self.same,'#PYLQG'),(self.other,'#YQGRJPC2L')):
            write(self.store.profile(account)/'data/clan/state.json',
                  {'account':account['tag'],'tag':clan,'checked_at':1000})

    def test_only_same_clan_donors_qualify(self):
        self.assertEqual([a['id'] for a in donors_for(self.store,self.source,1001)],[self.same['id']])

    def test_unknown_stale_or_wrong_identity_never_routes(self):
        path=self.store.profile(self.source)/'data/clan/state.json'
        for value in ({},{'account':self.same['tag'],'tag':'#PYLQG','checked_at':1000},
                      {'account':self.source['tag'],'tag':123,'checked_at':1000},
                      {'account':self.source['tag'],'tag':'#PYLQG','checked_at':-90000},
                      {'account':self.source['tag'],'tag':'#PYLQG','checked_at':2000}):
            write(path,value);self.assertEqual(donors_for(self.store,self.source,1001),[])


class GoalFleetTests(ClanRoutingTests):
    def fleet(self, account):
        from coc_bot.accounts.rotation import AccountFleet,RotationStore
        from coc_bot.control.lifecycle import RunOptions
        RotationStore(self.store).configure(enabled=True,primary_id=self.same['id'],
                                           watch_seconds=900,visit_seconds=180,interval_seconds=1800)
        fleet=AccountFleet(self.store,RunOptions(),clock=lambda:1001)
        config=SimpleNamespace(data_dir=self.store.profile(account)/'data',account_tag=account['tag'])
        fleet.current=SimpleNamespace(config=config,_visit=Visit(config,lambda:1001),
            tracker=SimpleNamespace(state=SimpleNamespace(last_completed_attack_id=None)),
            capture=Mock(),navigator=Mock(),chat_monitor=Mock(),_has_donate_request=Mock(return_value=False))
        fleet.current.navigator.classifier._clan_chat_anchor_visible.return_value=True
        fleet.current.chat_monitor.find_donate_request.return_value=None
        fleet._clan_checked=True;fleet._chat_due=False
        return fleet

    def test_secondary_yields_to_donor_without_losing_unfinished_checklist(self):
        fleet=self.fleet(self.source)
        self.assertTrue(fleet._checkpoint(self.source,0))
        self.assertFalse(fleet.current._visit.complete())
        self.assertTrue(fleet._visit_suspended)
        self.assertEqual(fleet.current._visit.order(),('farm',))
        for step in STEPS:fleet.current._visit.finish_step(step)
        self.assertTrue(fleet._checkpoint(self.source,0))
        self.assertEqual(fleet._next,self.same['id'])

    def test_primary_refill_cannot_starve_due_accounts_after_its_full_watch_window(self):
        fleet=self.fleet(self.same);visit=fleet.current._visit
        fleet._watch.started=0;fleet._watch.credit(1001)
        self.assertTrue(fleet._checkpoint(self.same,0))
        self.assertEqual(fleet._next,self.source['id'])
        self.assertTrue(fleet._visit_suspended)
        self.assertFalse(visit.complete());self.assertEqual(visit.order(),('farm',))
        fleet.rotation.complete(self.same['id'],1001,1001,suspended=True)
        self.assertNotIn('last_finished_at',fleet.rotation.load()['visits'][self.same['id']])
        self.assertEqual(fleet.rotation.load()['next_watch_seconds'],900)
        fleet._initialize_schedule(self.same)
        self.assertEqual(visit.order(),('farm',))

    def test_primary_keeps_its_watch_window_and_waits_when_nobody_is_due(self):
        fleet=self.fleet(self.same)
        fleet._watch.started=200;fleet._watch.credit(801)
        self.assertFalse(fleet._checkpoint(self.same,200))  # Only 801 verified chat seconds.
        fleet._watch.started=0;fleet._watch.credit(200)
        state=fleet.rotation.load();state['visits'][self.source['id']]={'next_visit_at':2000}
        write(fleet.rotation.path,state)
        self.assertFalse(fleet._checkpoint(self.same,0))
        self.assertFalse(getattr(fleet,'_visit_suspended',False))

    def test_primary_handoff_waits_for_requests_and_unresolved_actions(self):
        fleet=self.fleet(self.same)
        fleet._watch.started=0;fleet._watch.credit(1001)
        fleet.current._has_donate_request.return_value=True
        self.assertFalse(fleet._checkpoint(self.same,0))
        fleet.current._has_donate_request.return_value=False
        with patch('coc_bot.attack.recovery.pending',return_value=True):
            self.assertFalse(fleet._checkpoint(self.same,0))
        for relative,value in (('upgrades/state.json',{'pending':{'phase':'confirming'}}),
                               ('layouts/state.json',{'pending':{'phase':'placing'}}),
                               ('layouts/state.json',{'last_survey':{'payment':{'phase':'confirming'}}})):
            with self.subTest(relative=relative,value=value):
                path=fleet.current.config.data_dir/relative
                write(path,value)
                try:self.assertFalse(fleet._checkpoint(self.same,0))
                finally:path.unlink()
        self.assertFalse(getattr(fleet,'_visit_suspended',False))

    def test_due_account_wins_after_long_donor_work_and_a_persistent_chat_request(self):
        fleet=self.fleet(self.same)
        now=[1350];fleet.clock=lambda:now[0]
        fleet.current._has_donate_request.return_value=True
        self.assertFalse(fleet._checkpoint(self.same,0))
        now[0]+=29
        self.assertFalse(fleet._checkpoint(self.same,0))
        now[0]+=1
        with patch('coc_bot.attack.recovery.pending',return_value=True):
            self.assertFalse(fleet._checkpoint(self.same,0))
        self.assertTrue(fleet._checkpoint(self.same,0))
        self.assertEqual(fleet._next,self.source['id'])
        with patch('coc_bot.accounts.clan.donors_for',return_value=[self.same]), \
             patch('coc_bot.donation.chat_check.peek_requests',return_value=object()):
            self.assertTrue(fleet._check_chat_before_switch(self.same))
        self.assertEqual(fleet._next,self.source['id'])

    def test_between_step_request_saves_interrupted_account_as_resume(self):
        fleet=self.fleet(self.source);fleet._chat_due=True
        fleet.current.chat_monitor.find_donate_request.return_value=SimpleNamespace(signature='new-request')
        fleet.current._visit.finish_step('farm',repeat=True)
        self.assertTrue(fleet._checkpoint(self.source,900))
        detour=fleet.rotation.load()['donation_detour']
        self.assertEqual((detour['donor'],detour['resume'],detour['clan']),
                         (self.same['id'],self.source['id'],'#PYLQG'))
        self.assertEqual(fleet.current._visit.order(),('farm',))

    def test_attack_completion_forces_chat_check_even_when_step_notification_was_missing(self):
        fleet=self.fleet(self.source);fleet.current._farm_chat_check_due=True
        fleet.current.navigator.seek_donation_requests_step.return_value='jump'
        fleet.current.chat_monitor.find_donate_request.side_effect=[None,SimpleNamespace(signature='after-attack')]
        fleet.current._visit.finish_step('farm',repeat=True)
        self.assertTrue(fleet._checkpoint(self.source,900))
        self.assertFalse(fleet.current._farm_chat_check_due)
        self.assertEqual(fleet.rotation.load()['donation_detour']['resume'],self.source['id'])
        self.assertEqual(fleet.current._visit.order(),('farm',))

    def test_changed_donor_clan_cancels_before_any_donation(self):
        fleet=self.fleet(self.same);fleet._clan_checked=False
        state=fleet.rotation.load();state['donation_detour']={'donor':self.same['id'],
              'resume':self.source['id'],'source':self.source['id'],'clan':'#PYLQG'}
        write(fleet.rotation.path,state)
        with patch('coc_bot.accounts.clan.ClanIdentity') as identity:
            identity.return_value.learn.return_value='#YQGRJPC2L'
            self.assertTrue(fleet._checkpoint(self.same,900))
        self.assertEqual(fleet._next,self.source['id'])
        fleet.current._has_donate_request.assert_not_called()

    def test_resolved_full_visit_starts_a_new_checklist_on_next_admission(self):
        fleet=self.fleet(self.source)
        old=fleet.current._visit;old.clock=lambda:0
        for step in STEPS:old.finish_step(step)
        self.assertTrue(old.complete());old.clock=lambda:1001
        fleet._initialize_schedule(self.source)
        self.assertEqual(old.order(),('farm',))


class WallReceiptTests(unittest.TestCase):
    def test_recovery_checks_two_full_queues_and_never_pays(self):
        from coc_bot.progression.walls import WallUpgrade
        with tempfile.TemporaryDirectory() as folder:
            runner=Mock();runner.path=Path(folder)/'upgrades.json';runner.stopped.return_value=False
            pending={'kind':'wall','name':'Wall','cost':1000,'currency':'gold',
                     'remaining_before':23,'target_level':2,'balance_before':3140}
            row={'name':'Wall','cost':1000,'currency':'gold','quantity':22,'target_level':2}
            good={'complete':True,'unfiltered':True,'unknown':False,'balances':{'gold':2140},'rows':[row]}
            for change in ({'complete':False},{'unknown':True},{'rows':[row|{'quantity':21}]},
                           {'balances':{'gold':3140}}):
                state={'pending':pending.copy()};runner.scan.return_value=good|change
                self.assertEqual(WallUpgrade(runner).recover(state)['status'],'needs_review')
                self.assertIn('pending',state)
            runner.scan.return_value=good
            state={'pending':pending.copy()}
            self.assertEqual(WallUpgrade(runner).recover(state)['status'],'recovered')
            self.assertNotIn('pending',state);runner.input.tap.assert_not_called()


class BulkWallTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('tesseract'),'Native badge rejection uses OCR fallback')
    def test_compact_native_wall_badge_keeps_the_before_target_level(self):
        import cv2
        from coc_bot.progression.reader import ProgressionReader
        frame=cv2.imread(str(Path(__file__).parent/'fixtures/resource_visits/wall-compact-level-four.png'))
        reader=ProgressionReader(None);row={'box':[1358,310,495,67]}
        self.assertEqual(reader.target_level(frame,row),4)
        frame[351:375,1366:1391]=0
        self.assertIsNone(reader.target_level(frame,row))

    def test_native_red_five_thousand_is_unaffordable_not_unknown(self):
        import cv2
        from coc_bot.progression.bulk_walls import payments
        frame=cv2.imread(str(Path(__file__).parent/'fixtures/resource_visits/wall-starter-red-five.png'))
        prices=payments(frame)
        self.assertEqual(len(prices),1)
        self.assertEqual((prices[0]['price'],prices[0]['currency'],prices[0]['red']),(5000,'gold',True))
        # Missing currency must never become a spendable price.
        frame[740:790,1034:1064]=0
        self.assertEqual(payments(frame),[])

    @unittest.skipUnless(shutil.which('tesseract'),'Native wall heading OCR is required')
    def test_red_five_count_agrees_with_price_and_has_subtraction_control(self):
        import cv2
        from coc_bot.progression.bulk_walls import selection
        frame=cv2.imread(str(Path(__file__).parent/'fixtures/resource_visits/wall-starter-red-five.png'))
        value=selection(frame,'gold')
        self.assertEqual((value['level'],value['count'],value['price'],value['red']),(1,5,5000,True))
        self.assertIsNotNone(value['minus'])

    def test_conflicting_red_masks_reject_price(self):
        import cv2
        from coc_bot.progression.bulk_walls import payment
        frame=cv2.imread(str(Path(__file__).parent/'fixtures/resource_visits/wall-starter-red-five.png'))
        with patch('coc_bot.progression.reader.balance_amount',return_value=None),\
             patch('coc_bot.upgrades.digits.read_digits',side_effect=['5000','6000']):
            self.assertIsNone(payment(frame,(976,870)))
        with patch('coc_bot.progression.reader.balance_amount',return_value=None),\
             patch('coc_bot.upgrades.digits.read_digits',side_effect=['5000','5000','6000']):
            self.assertIsNone(payment(frame,(976,870)))

    def test_bulk_level_one_ocr_correction_requires_matching_heading(self):
        import cv2
        from coc_bot.progression.bulk_walls import selection
        path = Path(__file__).parent/'fixtures/resource_visits/wall-starter-three.png'
        frame = cv2.imread(str(path))
        with patch('coc_bot.progression.reader.selected_title', return_value='Wall (Level 1l)x 3'):
            result = selection(frame, 'gold')
            self.assertEqual((result['level'], result['count'], result['price']), (1, 3, 3000))
            frame[675:720, 764:800] = 0
            self.assertIsNone(selection(frame, 'gold'))
        frame = cv2.imread(str(path))
        frame[675:720, 764:800] = 0
        with patch('coc_bot.progression.reader.selected_title', return_value='Wall (Level 11)x 3'):
            self.assertEqual(selection(frame, 'gold')['level'], 11)

    @unittest.skipUnless(shutil.which('tesseract'),'Native wall heading OCR is required')
    def test_starter_bulk_price_is_not_contaminated_by_the_tiles_bright_border(self):
        import cv2
        from coc_bot.progression.bulk_walls import selection
        frame=cv2.imread(str(Path(__file__).parent/'fixtures/resource_visits/wall-starter-three.png'))
        value=selection(frame,'gold')
        self.assertEqual((value['level'],value['count'],value['price'],value['currency']),(1,3,3000,'gold'))
        self.assertFalse(value['red'])
        frame[738:790,1028:1065]=0
        self.assertIsNone(selection(frame,'gold'))
    def test_budget_respects_reserves_and_available_count(self):
        from coc_bot.progression.bulk_walls import maximum_affordable
        self.assertEqual(maximum_affordable(2140,0,1000,22),2)
        self.assertEqual(maximum_affordable(2140,500,1000,22),1)
        self.assertEqual(maximum_affordable(100000,0,1000,22),22)
        self.assertEqual(maximum_affordable(500,1000,1000,22),0)

    def test_plus_to_red_minus_one_and_exact_batch_intent(self):
        from coc_bot.progression.bulk_walls import BulkWalls
        import numpy as np
        with tempfile.TemporaryDirectory() as folder:
            r=Mock();r.path=Path(folder)/'state.json';r.stop=None
            r.config.account_tag='#HOME'
            frame=np.zeros((16,16,3),np.uint8)
            r.capture.screenshot.return_value=frame
            r.config.upgrade_gold_reserve=0;r.stopped.return_value=False;r.wait.return_value=False
            r.state.return_value={};r.eligibility.return_value=None
            value=lambda n,red=False:{'level':1,'count':n,'price':n*1000,'red':red,
                                       'plus':(20,20),'minus':(30,30),'pay':(40,40)}
            batch=BulkWalls(r);batch.settled=Mock(side_effect=[value(1),value(2),value(3,True),value(2)])
            with patch('coc_bot.progression.bulk_walls.control',return_value=(10,10)),\
                 patch('coc_bot.progression.bulk_walls.selection',return_value=value(2)),\
                 patch('coc_bot.progression.walls.wall_balance',return_value=2140),\
                 patch('coc_bot.progression.walls.WallUpgrade.recover',return_value={'status':'recovered'}):
                result=batch.run({'currency':'gold','cost':1000},{'level':1},22,2140,(frame,frame))
            self.assertEqual((result['count'],result['spent']),(2,2000))
            self.assertEqual([call.args for call in r.input.tap.call_args_list],
                             [(10,10),(20,20),(20,20),(30,30),(40,40)])
            pending=read(r.path)['pending']
            self.assertEqual((pending['count'],pending['cost'],pending['unit_cost']),(2,2000,1000))

    def test_changed_count_or_price_never_pays(self):
        from coc_bot.progression.bulk_walls import BulkWalls
        r=Mock();r.config.upgrade_gold_reserve=0;r.stopped.return_value=False;r.wait.return_value=False
        first={'level':1,'count':1,'price':1000,'red':False,'plus':(20,20),'minus':(30,30),'pay':(40,40)}
        batch=BulkWalls(r);batch.settled=Mock(side_effect=[first,first|{'count':3,'price':2000}])
        with patch('coc_bot.progression.bulk_walls.control',return_value=(10,10)):
            result=batch.run({'currency':'gold','cost':1000},{'level':1},22,2140,())
        self.assertEqual(result['status'],'blocked')
        r.state.assert_not_called()
        self.assertNotIn((40,40),[call.args for call in r.input.tap.call_args_list])


class BuilderChecklistTests(unittest.TestCase):
    def test_unverified_refill_and_busy_lab_still_check_free_builders(self):
        from coc_bot.builder_base.runner import BuilderBaseRunner
        runner=BuilderBaseRunner.__new__(BuilderBaseRunner)
        runner.config=SimpleNamespace(dry_run=False,builder_base_collect_resources=False,
            builder_base_attacks_enabled=True,builder_base_upgrades_enabled=True,
            builder_base_research_enabled=True,builder_base_progression_enabled=False)
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        runner.config.data_dir=Path(temp.name)
        runner.record={};runner.enter=Mock();runner.finish=Mock();runner.phase=Mock()
        runner.refill_resources=Mock(return_value={'retry_at':2000,'message':'unreadable storage'})
        runner.capture=Mock();runner.input=Mock();runner.nav=Mock();runner.stop=lambda:False
        with patch('coc_bot.builder_base.runner.pending',return_value=False),\
             patch('coc_bot.builder_base.runner.BuilderUpgradeRunner') as factory:
            factory.return_value.run.side_effect=[{'status':'busy'},{'status':'started'},{'status':'busy'}]
            result=runner.run(refill=True)
        self.assertEqual([c.args[0] for c in factory.return_value.run.call_args_list],
                         ['research','buildings','buildings'])
        self.assertEqual(result['retry_at'],2000)
        self.assertEqual(len(result['upgrade']['completed_operations']),1)
        runner.finish.assert_called_once()


class HomeChecklistTests(unittest.TestCase):
    def bot(self):
        from coc_bot.bot import DonationBot
        bot=DonationBot.__new__(DonationBot)
        bot.config=SimpleNamespace(dry_run=False,upgrade_buildings_enabled=True,
            upgrade_research_enabled=True,upgrade_pets_enabled=True,upgrade_interval_seconds=60,
            donation_enabled=False,progression_enabled=False)
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        bot.config.data_dir=Path(temp.name)
        bot._state='scan_chat';bot._stop_requested=False;bot._next_upgrade_check=0
        bot._visit_retry_at=None;bot._visit_reason=None
        bot.should_stop=lambda:False;bot._has_donate_request=Mock(return_value=False)
        bot.capture=Mock();bot.nav_input=Mock();bot.navigator=Mock();bot.game_state=Mock();bot.set_mode=Mock()
        return bot

    def test_pre_payment_block_does_not_starve_research_or_pets(self):
        bot=self.bot()
        with patch('coc_bot.upgrades.runner.UpgradeRunner') as factory:
            factory.return_value.state.return_value={}
            factory.return_value.run.side_effect=[{'status':'blocked','message':'Unreadable building'},
                                                  {'status':'busy'},{'status':'nothing_eligible'}]
            self.assertTrue(bot._maybe_run_upgrades())
        self.assertEqual([c.args[0] for c in factory.return_value.run.call_args_list],
                         ['buildings','research','pets'])

    def test_unresolved_payment_stops_instead_of_cycling_all_upgrade_categories(self):
        from coc_bot.runtime.verification import ActionNeedsReview
        bot=self.bot()
        pending={'kind':'wall','remaining_before':None,'cost':5000}
        with patch('coc_bot.upgrades.runner.UpgradeRunner') as factory:
            factory.return_value.state.return_value={'pending':pending}
            factory.return_value.run.return_value={'status':'needs_review','message':'Wall before count is missing'}
            with self.assertRaisesRegex(ActionNeedsReview,'Wall before count is missing'):
                bot._maybe_run_upgrades()
        self.assertEqual(factory.return_value.run.call_count,1)
        self.assertEqual(factory.return_value.state()['pending'],pending)
        bot.nav_input.tap.assert_not_called()

    def test_donation_preserves_builder_check_as_unfinished(self):
        bot=self.bot();bot._has_donate_request.side_effect=[False,True]
        with patch('coc_bot.upgrades.runner.UpgradeRunner') as factory:
            factory.return_value.run.return_value={'status':'started'}
            self.assertTrue(bot._maybe_run_upgrades())
        self.assertTrue(bot._visit_repeat)
        self.assertEqual(factory.return_value.run.call_count,1)

    def test_task_mode_does_not_recheck_a_request_instead_of_starting_maintenance(self):
        bot=self.bot();bot._fleet_task_driven=True
        bot._has_donate_request.return_value=True
        with patch('coc_bot.upgrades.runner.UpgradeRunner') as factory:
            factory.return_value.state.return_value={}
            factory.return_value.run.return_value={'status':'busy'}
            self.assertTrue(bot._maybe_run_upgrades())
        self.assertEqual(factory.return_value.run.call_count,3)
        bot._has_donate_request.assert_not_called()


class ArmyHallHintTests(unittest.TestCase):
    def test_verified_air_army_survives_missing_filler_unlock(self):
        from coc_bot.progression.army import composition
        self.assertEqual(composition(18,340,{'electro_dragon':4}),{'electro_dragon':11})
        self.assertEqual(composition(18,340,{'electro_dragon':4,'barbarian':4}),
                         {'electro_dragon':11})
        self.assertEqual(composition(8,185,{'dragon':2}),{'dragon':9})
        with self.assertRaises(ValueError):composition(10,240,{'electro_dragon':4})

    def test_missing_upgrade_row_can_use_only_matching_verified_account_hint(self):
        from coc_bot.progression.preparation import ArmyPreparation
        from coc_bot.accounts.store import selected_account
        prep=ArmyPreparation.__new__(ArmyPreparation)
        prep.s=SimpleNamespace(config=SimpleNamespace(account_tag='#PYLQG',account_town_hall=18))
        prep.hall=Mock(side_effect=ValueError('Town Hall entry was not found'))
        for account in (None,{'tag':'#YQGRJPC2L','town_hall':18},{'tag':'#PYLQG','town_hall':17}):
            token=selected_account.set(account)
            try:
                with self.assertRaises(ValueError):prep.army_hall()
            finally:selected_account.reset(token)
        token=selected_account.set({'tag':'#PYLQG','town_hall':18})
        try:
            self.assertEqual(prep.army_hall(),18)
            prep.hall.side_effect=ValueError('Current Town Hall level badge could not be verified')
            with self.assertRaises(ValueError):prep.army_hall()
        finally:selected_account.reset(token)

    def test_electro_dragons_override_every_mixed_preset_when_unlocked(self):
        from coc_bot.progression.army import composition
        from coc_bot.progression.profiles import HOUSING
        for hall in range(11,19):
            for capacity in (260,280,300,320,340,352):
                with self.subTest(hall=hall,capacity=capacity):
                    self.assertEqual(composition(hall,capacity,{u:1 for u in HOUSING}),
                                     {'electro_dragon':capacity//30})
        self.assertNotIn('electro_dragon',composition(11,260,{'electro_dragon':0,'dragon':1}))
        self.assertNotIn('electro_dragon',composition(10,240,{'dragon':1}))
