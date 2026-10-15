import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from types import SimpleNamespace

import cv2
import numpy as np
from coc_bot.upgrades.policy import reason
from coc_bot.upgrades.vision import Candidate
from coc_bot.upgrades.runner import UpgradeRunner
from coc_bot.upgrades.digits import read_digits,bank


def config(path):
    return SimpleNamespace(data_dir=Path(path),upgrade_builders_reserved=1,
        upgrade_gold_reserve=1_000_000,upgrade_elixir_reserve=2_000_000,
        upgrade_dark_elixir_reserve=50_000,upgrade_excluded_names='')


class UpgradePolicyTests(unittest.TestCase):
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
    def make_bot(self):
        from coc_bot.bot import DonationBot
        bot=object.__new__(DonationBot)
        bot.config=SimpleNamespace(dry_run=False,upgrade_buildings_enabled=False,
                                   upgrade_research_enabled=True,upgrade_interval_seconds=900)
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
