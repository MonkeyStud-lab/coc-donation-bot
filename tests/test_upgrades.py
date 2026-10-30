import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch, call
from types import SimpleNamespace

import cv2
import numpy as np
from coc_bot.upgrades.policy import reason
from coc_bot.upgrades.vision import Candidate, UpgradeReader, resource_amount, pet_name
from coc_bot.upgrades.runner import UpgradeRunner
from coc_bot.upgrades.digits import read_digits,bank


def config(path):
    return SimpleNamespace(data_dir=Path(path),upgrade_builders_reserved=1,
        upgrade_gold_reserve=1_000_000,upgrade_elixir_reserve=2_000_000,
        upgrade_dark_elixir_reserve=50_000,upgrade_excluded_names='')


class UpgradePolicyTests(unittest.TestCase):
    def test_pet_slot_reserves_identity_and_assignment(self):
        c=config('.')
        pet=Candidate('L.A.S.S.I',60_000,'dark_elixir',(10,10),False)
        self.assertIsNone(reason(c,'pets',pet,{'dark_elixir':259_011},(1,1)))
        for available in (None,(0,1),(2,5)):
            self.assertIsNotNone(reason(c,'pets',pet,{'dark_elixir':259_011},available))
        self.assertIsNotNone(reason(c,'pets',pet,{'dark_elixir':100_000},(1,1)))
        for name,currency,assignment in [('Unknown Pet','dark_elixir',False),
                                        ('L.A.S.S.I','gems',False),('L.A.S.S.I','dark_elixir',None),
                                        ('L.A.S.S.I','dark_elixir',True),('Pet House','dark_elixir',False)]:
            self.assertIsNotNone(reason(c,'pets',Candidate(name,60_000,currency,(1,1),assignment),
                                        {'dark_elixir':259_011},(1,1)))
        c.upgrade_pets_include_assigned=True
        self.assertIsNone(reason(c,'pets',Candidate('Frosty',200_000,'dark_elixir',(1,1),True),
                                 {'dark_elixir':259_011},(1,1)))
        c.upgrade_excluded_names='L.A.S.S.I'
        self.assertIsNotNone(reason(c,'pets',pet,{'dark_elixir':259_011},(1,1)))

    def test_protect_reserves_busy_slots_heroes_and_gems(self):
        c=config('.')
        bowler=Candidate('Bowler',360000,'dark_elixir',(10,10))
        self.assertIsNone(reason(c,'research',bowler,{'dark_elixir':450790},(1,1)))
        self.assertIsNotNone(reason(c,'research',bowler,{'dark_elixir':400000},(1,1)))
        self.assertIsNotNone(reason(c,'research',bowler,{'dark_elixir':450790},(0,1)))
        for name in ('Town Hall','Barbarian King','Barbarian Klng','Unknown Building','Wall'):
            self.assertIsNotNone(reason(c,'buildings',Candidate(name,1000,'gold',(1,1)),{'gold':30000000},(3,5)))
        self.assertIsNotNone(reason(c,'research',Candidate('Bowler',1,'gems',(1,1)),{'gems':403},(1,1)))
        self.assertIsNotNone(reason(c,'research',bowler,{'dark_elixir':None},(1,1)))
        c.upgrade_excluded_names='Bowler, Blacksmith'
        self.assertIsNotNone(reason(c,'research',bowler,{'dark_elixir':450790},(1,1)))

    def test_one_builder_is_reserved(self):
        item=Candidate("Builder's Hut",6000000,'gold',(1,1))
        c=config('.')
        self.assertIsNotNone(reason(c,'buildings',item,{'gold':30000000},(1,5)))
        self.assertIsNone(reason(c,'buildings',item,{'gold':30000000},(2,5)))

    def test_digits_reject_blank_and_unknown_shapes(self):
        self.assertEqual(set(k.split('_')[0] for k in bank()),set('0123456789')|{'slash'})
        frame=np.zeros((50,200,3),np.uint8)
        self.assertIsNone(read_digits(frame))
        cv2.rectangle(frame,(10,10),(80,40),(255,255,255),-1)
        self.assertIsNone(read_digits(frame))


class UpgradeImageTests(unittest.TestCase):
    """Only isolated game controls are stored, with no account or village data."""
    fixtures=Path(__file__).with_name('fixtures')/'upgrades'

    def test_discount_reads_payable_price_not_crossed_out_price(self):
        frame=cv2.imread(str(self.fixtures/'discounted-confirmation-controls.png'))
        reader=UpgradeReader()
        self.assertIsNotNone(reader.confirmation(frame,Candidate('Archer',1_500_000,'elixir',(1,1))))
        for name,price,resource in [('Archer',3_000_000,'elixir'),('Archer',150_000,'elixir'),
                                    ('Archer',1_500_000,'gold'),('Archer',1_500_000,'gems'),
                                    ('Giant',1_500_000,'elixir')]:
            self.assertIsNone(reader.confirmation(frame,Candidate(name,price,resource,(1,1))))
        # Without the observed strike, green text cannot authorize an alternate read.
        altered=frame.copy();altered[944:955,1160:1445]=0
        self.assertIsNone(reader.confirmation(altered,Candidate('Archer',1_500_000,'elixir',(1,1))))

    def pet_frame(self):
        frame=np.zeros((1048,1853,3),np.uint8)
        frame[:,1350:]=cv2.imread(str(self.fixtures/'pet-menu-panel.png'))
        return frame

    def test_pet_menu_recognizes_slot_and_unassigned_rows(self):
        reader=UpgradeReader();frame=self.pet_frame()
        self.assertEqual(reader.menu_kind(frame),'pets')
        self.assertEqual(reader.availability(frame,'pets'),(1,1))
        rows,_=reader.pet_candidates(frame);pets={p.name:p for p in rows}
        self.assertFalse(pets['L.A.S.S.I'].assigned)
        self.assertEqual(pets['L.A.S.S.I'].cost,60_000)
        self.assertTrue(pets['Frosty'].assigned)
        self.assertEqual(pets['Mighty Yak'].cost,40_000)
        self.assertEqual(pets['Poison Lizard'].cost,75_000)
        self.assertNotIn('Greedy Raven',pets)  # Locked; no resource price.
        self.assertIsNone(reader.menu_kind((frame.astype(float)*.60).astype(np.uint8)))

    def test_pet_counter_prices_and_confirmation_use_strict_font_reads(self):
        for name,expected in [('pet-dark-counter',259_011),('pet-elixir-counter',30_932_802),
                              ('pet-yak-price',40_000),('pet-lizard-price',75_000)]:
            self.assertEqual(resource_amount(cv2.imread(str(self.fixtures/(name+'.png')))),expected)
        frame=cv2.imread(str(self.fixtures/'pet-confirmation-controls.png'))
        reader=UpgradeReader()
        self.assertIsNotNone(reader.confirmation(frame,Candidate('L.A.S.S.I',60_000,'dark_elixir',(1,1),False)))
        for name,cost,currency in [('Frosty',60_000,'dark_elixir'),('L.A.S.S.I',6_000,'dark_elixir'),
                                   ('L.A.S.S.I',60_000,'gems')]:
            self.assertIsNone(reader.confirmation(frame,Candidate(name,cost,currency,(1,1),False)))

    def test_new_pet_timer_and_busy_slot_are_recognized(self):
        frame=np.zeros((1048,1853,3),np.uint8)
        frame[:,1350:]=cv2.imread(str(self.fixtures/'pet-running-panel.png'))
        reader=UpgradeReader()
        self.assertEqual(reader.menu_kind(frame),'pets')
        self.assertEqual(reader.availability(frame,'pets'),(0,1))
        self.assertEqual(reader.active_names(frame,kind='pets'),['lassi'])
        self.assertEqual(reader.active_names(self.pet_frame(),kind='pets'),[])
        for value in ['L.A.S.5.]','L.A.5.5.1','L-A:S:S.1']:
            self.assertEqual(pet_name(value),'L.A.S.S.I')

    def test_pet_assignment_is_not_guessed_when_headings_are_missing(self):
        reader=UpgradeReader();frame=self.pet_frame()
        with patch.object(reader,'_headings',return_value=[]):
            rows,_=reader.pet_candidates(frame)
        self.assertTrue(rows)
        self.assertTrue(all(p.assigned is None for p in rows))
        reader.pet_candidates(frame) # Observe the real Unassigned heading.
        with patch.object(reader,'_headings',return_value=[]):
            rows,_=reader.pet_candidates(frame)
        pets={p.name:p for p in rows}
        self.assertFalse(pets['L.A.S.S.I'].assigned)
        self.assertIsNone(pets['Frosty'].assigned)

    def test_small_free_builder_counter(self):
        counter=cv2.imread(str(self.fixtures/'builder-four-counter.png'))
        self.assertEqual(read_digits(counter,fraction=True),'4/5')
        frame=np.zeros((1048,1853,3),np.uint8)
        frame[990:1029,1369:1460]=counter
        self.assertEqual(UpgradeReader().availability(frame,'buildings'),(4,5))

    def test_small_three_digit(self):
        image=cv2.imread(str(self.fixtures/'builder-three-digit.png'))
        self.assertEqual(read_digits(image),'3')
        counter=cv2.imread(str(self.fixtures/'builder-three-counter.png'))
        self.assertEqual(read_digits(counter,fraction=True),'3/5')

    def test_full_and_partly_empty_resource_bars(self):
        for name,expected in (('before-elixir',31_000_000),('partial-elixir',13_000_000),
                              ('research-dark_elixir',450_790)):
            with self.subTest(name=name):
                image=cv2.imread(str(self.fixtures/(name+'.png')))
                self.assertEqual(resource_amount(image),expected)
        with patch('coc_bot.upgrades.vision.amount',side_effect=[31_000_000,3_000_000]):
            self.assertIsNone(resource_amount(image))

    def test_eight_digit_confirmation_keeps_leading_digit(self):
        frame=cv2.imread(str(self.fixtures/'blacksmith-confirmation.png'))
        reader=UpgradeReader()
        candidate=Candidate('Blacksmith',18_000_000,'elixir',(1,1))
        result=reader.confirmation(frame,candidate)
        self.assertIsNotNone(result)
        self.assertEqual(result['cost'],18_000_000)
        self.assertEqual(result['point'],(1301,916))
        # A truncated price or different resource must never authorize a tap.
        self.assertIsNone(reader.confirmation(frame,Candidate('Blacksmith',8_000_000,'elixir',(1,1))))
        self.assertIsNone(reader.confirmation(frame,Candidate('Blacksmith',18_000_000,'gold',(1,1))))

    def test_shaded_building_confirmation_uses_strict_isolated_price(self):
        frame=cv2.imread(str(self.fixtures/'builder-hut-gold-confirmation.png'))
        reader=UpgradeReader()
        candidate=Candidate("Builder's Hut",7_000_000,'gold',(1,1))
        result=reader.confirmation(frame,candidate)
        self.assertIsNotNone(result)
        self.assertEqual(result['cost'],7_000_000)
        self.assertEqual(result['point'],(1301,916))
        for name,price,resource in [("Builder's Hut",700_000,'gold'),
                                    ("Builder's Hut",7_000_000,'gems'),
                                    ("Builder's Hut",7_000_000,'elixir'),
                                    ('Blacksmith',7_000_000,'gold')]:
            self.assertIsNone(reader.confirmation(frame,Candidate(name,price,resource,(1,1))))
        # A disagreeing raw price must never be replaced by the expected value.
        with patch('coc_bot.upgrades.vision.amount',side_effect=[700_000,7_000_000]):
            self.assertIsNone(reader.confirmation(frame,candidate))


class UpgradeRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.runner=UpgradeRunner(config(self.temp.name),MagicMock(),MagicMock(),MagicMock())
        self.runner.close=MagicMock()
        self.runner.wait=MagicMock(return_value=False)
        self.runner.open_menu=MagicMock(return_value='frame')
        self.runner.reader=MagicMock()
        self.runner.reader.menu_kind.return_value='research'
        self.runner.reader.detail_close.return_value=None
        self.runner.reader.running_detail.return_value=False
        self.runner.reader.confirmation.return_value={'point':(50,50),'name':'Bowler','cost':360000,'currency':'dark_elixir'}
        self.item={'name':'Bowler','cost':360000,'currency':'dark_elixir','point':(10,10),'skip':None}
        self.report={'kind':'research','availability':(1,1),'balances':{'dark_elixir':450790},
                     'recommendations':[self.item],'section_complete':True}
        self.runner.inspect=MagicMock(side_effect=lambda *args:dict(self.report))

    def save_pending(self, kind, name, free_before):
        pending={'kind':kind,'name':name,'free_before':free_before,
                 'active_before':0,'phase':'confirming'}
        self.runner.path.parent.mkdir(parents=True,exist_ok=True)
        self.runner.path.write_text(json.dumps({'pending':pending}))
        return pending

    def test_pending_research_is_reconciled_before_building_preview(self):
        self.save_pending('research','Bowler',1)
        self.runner.reader.active_names.return_value=['bowler']
        self.runner.reader.availability.return_value=(0,1)
        self.report.update(kind='buildings',recommendations=[])
        result=self.runner.run('buildings')
        self.assertEqual(result['status'],'nothing_eligible')
        self.assertEqual(self.runner.open_menu.call_args_list,[call('research'),call('buildings')])
        self.assertNotIn('pending',self.runner.state())
        self.assertEqual(self.runner.state()['last_completed']['name'],'Bowler')
        self.runner.input.tap.assert_not_called()

    def test_pending_pet_is_reconciled_on_pet_tab_before_buildings(self):
        self.save_pending('pets','L.A.S.S.I',1)
        self.runner.reader.active_names.return_value=['lassi']
        self.runner.reader.availability.return_value=(0,1)
        self.report.update(kind='buildings',recommendations=[])
        self.assertEqual(self.runner.run('buildings')['status'],'nothing_eligible')
        self.assertEqual(self.runner.open_menu.call_args_list,[call('pets'),call('buildings')])
        self.runner.reader.active_names.assert_called_once_with('frame',kind='pets')
        self.assertNotIn('pending',self.runner.state())
        self.runner.input.tap.assert_not_called()

    def test_unresolved_pet_outcome_blocks_other_upgrade_categories(self):
        pending=self.save_pending('pets','L.A.S.S.I',1)
        self.runner.reader.active_names.return_value=[]
        self.runner.reader.availability.return_value=(0,1)
        self.assertEqual(self.runner.run('research',execute=True)['status'],'needs_review')
        self.assertEqual(self.runner.state()['pending'],pending)
        self.runner.input.tap.assert_not_called()

    def test_pet_assignment_change_after_preview_blocks_spending(self):
        self.report.update(kind='pets')
        self.item.update(name='L.A.S.S.I',cost=60_000,assigned=False)
        changed=dict(self.report,recommendations=[dict(self.item,assigned=True)])
        self.runner.reader.menu_kind.return_value='pets'
        self.runner.inspect.side_effect=[dict(self.report),changed]
        self.assertEqual(self.runner.run('pets',execute=True)['status'],'changed')
        self.runner.input.tap.assert_not_called()

    def test_pending_building_is_reconciled_before_research_preview(self):
        self.save_pending('buildings','Blacksmith',4)
        self.runner.reader.active_names.return_value=['blacksmith']
        self.runner.reader.availability.return_value=(3,5)
        result=self.runner.run('research')
        self.assertEqual(result['status'],'ready')
        self.assertEqual(self.runner.open_menu.call_args_list,[call('buildings'),call('research')])
        self.assertNotIn('pending',self.runner.state())
        self.runner.input.tap.assert_not_called()

    def test_unresolved_other_category_blocks_spending_and_retains_intent(self):
        pending=self.save_pending('research','Bowler',1)
        self.runner.reader.active_names.return_value=[]
        self.runner.reader.availability.return_value=(0,1)
        result=self.runner.run('buildings',execute=True)
        self.assertEqual(result['status'],'needs_review')
        self.runner.open_menu.assert_called_once_with('research')
        self.runner.inspect.assert_not_called()
        self.runner.input.tap.assert_not_called()
        self.assertEqual(self.runner.state()['pending'],pending)

    def test_stop_after_reconciliation_does_not_start_a_new_upgrade(self):
        self.save_pending('research','Bowler',1)
        self.runner.reader.active_names.return_value=['bowler']
        self.runner.reader.availability.return_value=(0,1)
        self.runner.open_menu.side_effect=['frame',None]
        result=self.runner.run('buildings',execute=True)
        self.assertEqual(result['status'],'stopped')
        self.runner.inspect.assert_not_called()
        self.runner.input.tap.assert_not_called()

    def test_invalid_pending_category_blocks_without_navigation(self):
        pending=self.save_pending('unknown','Bowler',1)
        result=self.runner.run('buildings',execute=True)
        self.assertEqual(result['status'],'needs_review')
        self.runner.open_menu.assert_not_called()
        self.runner.input.tap.assert_not_called()
        self.assertEqual(self.runner.state()['pending'],pending)

    def test_preview_never_sends_spending_taps(self):
        report=self.runner.run('research')
        self.assertEqual(report['status'],'ready')
        self.runner.input.tap.assert_not_called()
        self.assertFalse(self.runner.path.exists())

    def test_changed_price_or_token_blocks_spending(self):
        self.assertEqual(self.runner.run('research',execute=True,expected='wrong')['status'],'changed')
        self.runner.input.tap.assert_not_called()

    def test_durable_intent_precedes_spending_and_no_duplicate_on_uncertainty(self):
        def tap(x,y,**kwargs):
            if (x,y)==(50,50):
                state=json.loads(self.runner.path.read_text())
                self.assertEqual(state['pending']['phase'],'confirming')
        self.runner.input.tap.side_effect=tap
        self.runner.reader.active_names.return_value=[]
        self.runner.reader.availability.return_value=(1,1)
        result=self.runner.run('research',execute=True)
        self.assertEqual(result['status'],'needs_review')
        calls=self.runner.input.tap.call_count
        self.assertEqual(self.runner.run('research',execute=True)['status'],'needs_review')
        self.assertEqual(self.runner.input.tap.call_count,calls)

    def test_matching_timer_and_busy_slot_confirm_research(self):
        self.runner.reader.active_names.side_effect=[[],['bowler']]
        self.runner.reader.availability.return_value=(0,1)
        result=self.runner.run('research',execute=True)
        self.assertEqual(result['status'],'started')
        self.assertNotIn('pending',self.runner.state())
        self.assertEqual(self.runner.state()['last_completed']['name'],'Bowler')

    def test_mismatched_confirmation_never_spends(self):
        self.runner.reader.confirmation.return_value=None
        result=self.runner.run('research',execute=True)
        self.assertEqual(result['status'],'blocked')
        self.runner.input.tap.assert_called_once_with(10,10,jitter=0)

    def test_running_detail_is_closed_without_using_finish_now(self):
        self.runner.reader.running_detail.return_value=True
        self.runner.reader.detail_close.return_value=(80,10)
        self.runner.reader.active_names.side_effect=[[],['bowler']]
        self.runner.reader.availability.return_value=(0,1)
        result=self.runner.run('research',execute=True)
        self.assertEqual(result['status'],'started')
        points=[call.args for call in self.runner.input.tap.call_args_list]
        self.assertEqual(points,[(10,10),(50,50),(80,10)])

    def test_pet_original_detail_can_be_closed_but_requires_busy_slot_and_name(self):
        self.report.update(kind='pets')
        self.item.update(name='L.A.S.S.I',cost=60_000,assigned=False)
        self.runner.reader.menu_kind.return_value='pets'
        self.runner.reader.detail_close.return_value=(80,10)
        self.runner.reader.active_names.side_effect=[[],['lassi']]
        self.runner.reader.availability.return_value=(0,1)
        self.assertEqual(self.runner.run('pets',execute=True)['status'],'started')
        self.assertEqual([c.args for c in self.runner.input.tap.call_args_list],[(10,10),(50,50),(80,10)])

    def test_corrupt_journal_blocks_further_spending(self):
        self.runner.path.parent.mkdir(parents=True)
        self.runner.path.write_text('')
        self.assertEqual(self.runner.run('research',execute=True)['status'],'needs_review')
        self.runner.input.tap.assert_not_called()

    def test_stop_before_navigation(self):
        self.runner.stop=lambda:True
        self.assertEqual(self.runner.run('research',execute=True)['status'],'stopped')
        self.runner.open_menu.assert_not_called()


class UpgradeSchedulingTests(unittest.TestCase):
    def test_fill_builders_after_giving_lab_and_pets_a_turn(self):
        bot=self.make_bot();bot.config.upgrade_buildings_enabled=True;bot.config.upgrade_pets_enabled=True
        with patch('coc_bot.upgrades.runner.UpgradeRunner') as runner:
            runner.return_value.run.side_effect=[{'status':s} for s in ('started','started','started','started','nothing_eligible')]
            self.assertTrue(bot._maybe_run_upgrades())
            self.assertEqual([c.args[0] for c in runner.return_value.run.call_args_list],
                             ['buildings','research','pets','buildings','buildings'])

    def test_uncertain_upgrade_stops_remaining_categories(self):
        bot=self.make_bot();bot.config.upgrade_buildings_enabled=True
        with patch('coc_bot.upgrades.runner.UpgradeRunner') as runner:
            runner.return_value.run.return_value={'status':'needs_review'}
            bot._maybe_run_upgrades()
            runner.return_value.run.assert_called_once_with('buildings',execute=True)

    def make_bot(self):
        from coc_bot.bot import DonationBot
        bot=object.__new__(DonationBot)
        bot.config=SimpleNamespace(dry_run=False,upgrade_buildings_enabled=False,
                                   upgrade_research_enabled=True,upgrade_interval_seconds=900)
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        bot.config.data_dir=Path(temp.name)
        bot._state='scan_chat'
        bot._stop_requested=False
        bot._next_upgrade_check=0
        bot.capture=MagicMock()
        bot.navigator=MagicMock()
        bot.nav_input=MagicMock()
        bot.game_state=MagicMock()
        bot.set_mode=MagicMock()
        bot._has_donate_request=MagicMock(return_value=False)
        return bot

    def test_no_upgrade_during_donation_practice_stop_or_disabled_mode(self):
        for scenario in ('donate','practice','stop','disabled'):
            bot=self.make_bot()
            if scenario=='donate': bot._state='donate'
            if scenario=='practice': bot.config.dry_run=True
            if scenario=='stop': bot._stop_requested=True
            if scenario=='disabled': bot.config.upgrade_research_enabled=False
            self.assertFalse(bot._maybe_run_upgrades(),scenario)
            bot.capture.screenshot.assert_not_called()

    def test_visible_request_takes_priority_and_checks_respect_interval(self):
        bot=self.make_bot()
        bot._has_donate_request.return_value=True
        self.assertFalse(bot._maybe_run_upgrades())
        self.assertEqual(bot._next_upgrade_check,0)
        bot._has_donate_request.return_value=False
        with patch('coc_bot.upgrades.runner.UpgradeRunner') as runner:
            runner.return_value.run.return_value={'status':'nothing_eligible'}
            self.assertTrue(bot._maybe_run_upgrades())
            runner.return_value.run.assert_called_once_with('research',execute=True)
            self.assertFalse(bot._maybe_run_upgrades())
            runner.assert_called_once()

    def test_pet_only_schedule_is_supported_and_can_be_disabled(self):
        bot=self.make_bot();bot.config.upgrade_research_enabled=False;bot.config.upgrade_pets_enabled=True
        with patch('coc_bot.upgrades.runner.UpgradeRunner') as runner:
            runner.return_value.run.return_value={'status':'nothing_eligible'}
            self.assertTrue(bot._maybe_run_upgrades())
            runner.return_value.run.assert_called_once_with('pets',execute=True)
        bot._next_upgrade_check=0;bot.config.upgrade_pets_enabled=False
        self.assertFalse(bot._maybe_run_upgrades())

    def test_scheduler_recovers_research_before_buildings_even_if_research_disabled(self):
        for research_enabled in (True,False):
            with self.subTest(research_enabled=research_enabled), tempfile.TemporaryDirectory() as folder:
                bot=self.make_bot()
                bot.config.data_dir=Path(folder)
                bot.config.upgrade_buildings_enabled=True
                bot.config.upgrade_research_enabled=research_enabled
                runner=UpgradeRunner(bot.config,bot.capture,bot.nav_input,bot.navigator,bot.should_stop)
                runner.open_menu=MagicMock(return_value='frame')
                runner.close=MagicMock()
                runner.reader=MagicMock()
                runner.reader.active_names.return_value=['bowler']
                runner.reader.availability.return_value=(0,1)
                runner.inspect=MagicMock(side_effect=lambda kind,frame:{
                    'kind':kind,'recommendations':[],'section_complete':True})
                runner.path.parent.mkdir(parents=True)
                runner.path.write_text(json.dumps({'pending':{'kind':'research','name':'Bowler',
                    'free_before':1,'active_before':0,'phase':'confirming'}}))
                with patch('coc_bot.upgrades.runner.UpgradeRunner',return_value=runner):
                    self.assertTrue(bot._maybe_run_upgrades())
                expected=[call('research'),call('buildings')]
                if research_enabled: expected.append(call('research'))
                self.assertEqual(runner.open_menu.call_args_list,expected)
                self.assertNotIn('pending',runner.state())
                self.assertEqual(runner.state()['last_completed']['name'],'Bowler')
                bot.nav_input.tap.assert_not_called()
