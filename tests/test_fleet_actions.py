import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch, call
import cv2
from coc_bot.attack.abort import leave_unstarted_opponent
from coc_bot.attack.recovery import AttackCheckpoint, RecoveryRequired
from coc_bot.donation.reinforcements import castle_contents, request_dialog, eligible, available_button, request_if_empty


class AbandonTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.config=SimpleNamespace(data_dir=Path(self.tmp.name),adb_device='test')
        self.cp=AttackCheckpoint(self.config);self.cp.begin('opponent')
        self.s=SimpleNamespace(config=self.config,client=SimpleNamespace(stop_check=lambda:False),
                               capture=Mock(),input=Mock(),attack_nav=Mock(),_sleep=Mock())
        self.s.attack_nav.battle_completion.detect.return_value=None

    def test_never_abandons_after_possible_deployment(self):
        self.cp.update(deployment_possible=True)
        with self.assertRaises(RecoveryRequired):leave_unstarted_opponent(self.s)
        self.s.input.tap.assert_not_called()

    def test_verified_end_returns_without_battle_timer(self):
        with patch('coc_bot.attack.abort.home_build_control_visible',side_effect=[False,True]),\
             patch('coc_bot.attack.abort.end_button',return_value=(100,200)):
            self.assertTrue(leave_unstarted_opponent(self.s))
        self.s.input.tap.assert_called_once_with(100,200,jitter=0)
        self.s.attack_nav.wait_for_battle_end.assert_not_called()
        self.assertEqual(self.cp.load()['phase'],'aborting_unstarted')

    def test_unknown_screen_is_bounded_and_never_tapped(self):
        with patch('coc_bot.attack.abort.home_build_control_visible',return_value=False),\
             patch('coc_bot.attack.abort.end_button',return_value=None):
            with self.assertRaises(RecoveryRequired):leave_unstarted_opponent(self.s)
        self.assertEqual(self.s.capture.screenshot.call_count,8)
        self.s.input.tap.assert_not_called()

    def test_persisted_limit_prevents_repeated_end_inputs(self):
        self.cp.update(abort_end_taps=2)
        with patch('coc_bot.attack.abort.home_build_control_visible',return_value=False),\
             patch('coc_bot.attack.abort.end_button',return_value=(100,200)):
            with self.assertRaises(RecoveryRequired):leave_unstarted_opponent(self.s)
        self.s.input.tap.assert_not_called()


class RequestVisionTests(unittest.TestCase):
    def setUp(self):
        root=Path(__file__).parent/'fixtures/requests'
        self.army=cv2.imread(str(root/'army-empty.png'))
        self.dialog=cv2.imread(str(root/'send-dialog.png'))

    def test_empty_castle_categories_read_independently(self):
        self.assertEqual(castle_contents(self.army),(('troop',0,55),('spell',0,3),('siege',0,2)))
        self.assertIsNotNone(available_button(self.army))
        self.assertIsNone(castle_contents(self.dialog))

    def test_real_suggested_row_does_not_lose_builders_hut(self):
        from coc_bot.upgrades.vision import UpgradeReader,compact
        frame=cv2.imread(str(Path(__file__).parent/'fixtures/requests/upgrade-multiple-builders.png'))
        reader=UpgradeReader()
        rows,complete=reader.candidates(frame)
        self.assertTrue(complete)
        self.assertIn(('buildershut',8000000,'gold'),[(compact(c.name),c.cost,c.currency) for c in rows])
        self.assertEqual(reader.balances(frame)['elixir'],28346459)

    def test_scenery_does_not_invent_a_dark_elixir_digit(self):
        from coc_bot.upgrades.vision import UpgradeReader
        frame=cv2.imread(str(Path(__file__).parent/'fixtures/requests/research-idle.png'))
        self.assertEqual(UpgradeReader().balances(frame)['dark_elixir'],87184)

    def test_running_healing_spell_duplicate_heading_letter_is_safe_to_close(self):
        from coc_bot.upgrades.vision import UpgradeReader,Candidate
        frame=cv2.imread(str(Path(__file__).parent/'fixtures/requests/research-running.png'))
        reader=UpgradeReader()
        self.assertEqual(reader.detail_close(frame),(1642,79))
        self.assertTrue(reader.running_detail(frame,Candidate('Healing Spell',900000,'elixir',(1,2))))
        self.assertFalse(reader.running_detail(frame,Candidate('Rage Spell',900000,'elixir',(1,2))))

    def test_modal_requires_title_and_both_buttons(self):
        self.assertIsNotNone(request_dialog(self.dialog))
        self.assertIsNone(request_dialog(self.army))
        for y1,y2,x1,x2 in [(80,145,570,1283),(661,791,974,1294),(662,790,560,879)]:
            image=self.dialog.copy();image[y1:y2,x1:x2]=0
            self.assertIsNone(request_dialog(image))

    def test_donor_practice_and_locked_castle_are_excluded(self):
        config=SimpleNamespace(account_tag='#ABC',account_roles=('farming',),account_town_hall=10,dry_run=False)
        self.assertTrue(eligible(config))
        config.account_roles=('donating','farming');self.assertFalse(eligible(config))
        config.account_roles=('farming',);config.account_town_hall=2;self.assertFalse(eligible(config))
        config.account_town_hall=10;config.dry_run=True;self.assertFalse(eligible(config))


class RequestTransactionTests(unittest.TestCase):
    def test_durable_send_and_cooldown_prevent_duplicate_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            config=SimpleNamespace(data_dir=Path(tmp),account_tag='#ABC',account_roles=('farming',),
                                   account_town_hall=10,dry_run=False)
            session=SimpleNamespace(config=config,client=SimpleNamespace(stop_check=lambda:False),
                                    capture=Mock(),input=Mock(),_sleep=Mock())
            with patch('coc_bot.donation.reinforcements.ArmyPreparation') as prep,\
                 patch('coc_bot.donation.reinforcements.castle_contents',return_value=(('troop',0,35),)),\
                 patch('coc_bot.donation.reinforcements.available_button',side_effect=[(1,2),(1,2),None]),\
                 patch('coc_bot.donation.reinforcements.request_dialog',side_effect=[{'send':(3,4),'cancel':(5,6)}]*2+[None]),\
                 patch('coc_bot.donation.reinforcements.army_heading_visible',return_value=True):
                def tap(*args,**kwargs):
                    if args==(3,4):
                        import json
                        self.assertEqual(json.loads((Path(tmp)/'reinforcements/state.json').read_text())['status'],'send_pending')
                session.input.tap.side_effect=tap
                self.assertTrue(request_if_empty(session))
                self.assertFalse(request_if_empty(session))
                prep.return_value.open.assert_called_once_with(require_capacity=False)
                self.assertEqual(session.input.tap.call_args_list,[call(1,2,jitter=0),call(3,4,jitter=0)])

    def test_nonempty_castle_never_opens_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            config=SimpleNamespace(data_dir=Path(tmp),account_tag='#ABC',account_roles=('farming',),account_town_hall=10,dry_run=False)
            session=SimpleNamespace(config=config,client=SimpleNamespace(stop_check=lambda:False),capture=Mock(),input=Mock())
            with patch('coc_bot.donation.reinforcements.ArmyPreparation'),\
                 patch('coc_bot.donation.reinforcements.castle_contents',return_value=(('troop',0,35),('spell',1,2))),\
                 patch('coc_bot.donation.reinforcements.available_button',return_value=(1,2)),\
                 patch('coc_bot.donation.reinforcements.request_dialog',return_value=None):
                self.assertTrue(request_if_empty(session))
                session.input.tap.assert_not_called()


class ProgressionAvailabilityTests(unittest.TestCase):
    def runner(self,root):
        from coc_bot.progression.runner import ProgressionRunner
        import numpy as np
        config=SimpleNamespace(data_dir=Path(root),upgrade_builders_reserved=0,upgrade_excluded_names='',
                               upgrade_gold_reserve=0,upgrade_elixir_reserve=0,upgrade_dark_elixir_reserve=0)
        runner=ProgressionRunner(config,Mock(),Mock(),Mock())
        runner.capture.screenshot.return_value=np.zeros((1048,1853,3),dtype=np.uint8)
        runner.reader=Mock();runner.reader.menu_kind.return_value=None;runner.reader.filters_open.return_value=False
        runner.reader.availability.return_value=(1,5)
        runner.open_menu=Mock(return_value=runner.capture.screenshot.return_value);runner.close=Mock()
        return runner

    def test_unreadable_existing_price_does_not_idle_other_builders_or_unlock_hall(self):
        from coc_bot.progression.policy import town_hall_blockers
        with tempfile.TemporaryDirectory() as root:
            runner=self.runner(root)
            unknown={'name':'Dark Barracks','cost':None,'currency':'elixir','new':False,'point':(1,2)}
            known={'name':'Gold Mine','cost':1000,'currency':'elixir','new':False,'point':(3,4)}
            inventory={'complete':True,'unknown':True,'unfiltered':True,'busy':False,
                       'balances':{'gold':10000,'elixir':10000},'rows':[unknown,known]}
            runner.inventory=inventory;runner.scan=Mock(return_value=inventory)
            result=runner.run('buildings',execute=False)
            self.assertEqual(result['status'],'ready')
            self.assertEqual(result['selected']['name'],'Gold Mine')
            self.assertTrue(town_hall_blockers(inventory))
            unknown['new']=True;known['currency']='gems'
            self.assertNotEqual(runner.run('buildings',execute=False)['status'],'ready')
            runner.input.tap.assert_not_called()

    def test_busy_lab_does_not_scan_entire_inventory(self):
        with tempfile.TemporaryDirectory() as root:
            runner=self.runner(root);runner.reader.availability.return_value=(0,1);runner.scan=Mock()
            self.assertEqual(runner.run('research',execute=False)['status'],'busy')
            runner.scan.assert_not_called()

    def test_other_research_follows_farming_priorities(self):
        with tempfile.TemporaryDirectory() as root:
            runner=self.runner(root);runner.reader.availability.return_value=(1,1)
            rows=[{'name':'Bowler','cost':1000,'currency':'dark_elixir','new':False,'point':(1,2)},
                  {'name':'Barbarian','cost':1000,'currency':'elixir','new':False,'point':(3,4)}]
            inventory={'complete':True,'unknown':False,'unfiltered':True,'busy':False,
                       'balances':{'gold':10000,'elixir':10000,'dark_elixir':10000},'rows':rows}
            runner.inventory=inventory;runner.scan=Mock(return_value=inventory)
            self.assertEqual(runner.run('research',execute=False)['selected']['name'],'Barbarian')
            rows.pop()
            self.assertEqual(runner.run('research',execute=False)['selected']['name'],'Bowler')
