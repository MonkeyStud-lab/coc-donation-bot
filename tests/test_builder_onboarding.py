import tempfile
import shutil
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch

import cv2
import numpy as np

from coc_bot.adb.client import AdbStopped
from coc_bot.accounts.store import write,read
from coc_bot.builder_base.onboarding import BuilderOnboarding
from coc_bot.builder_base.vision import BuilderReader


class OnboardingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.runner=SimpleNamespace(config=SimpleNamespace(data_dir=Path(self.temp.name),account_tag='#PYLQG'),
            reader=BuilderReader(),stop=lambda:False,frame=Mock(return_value=np.zeros((1048,1853,3),np.uint8)),
            tap=Mock(),wait=Mock(),phase=Mock(),check=Mock(),evidence=Mock())
        self.flow=BuilderOnboarding(self.runner)
        self.fixtures=Path(__file__).parent/'fixtures/builder_base'

    def frame(self,name):return cv2.imread(str(self.fixtures/name))

    def test_intro_waits_through_transition_without_guessing_a_control(self):
        write(self.flow.path,{'account':'#PYLQG','phase':'first_travel_requested'})
        calls=[]
        def advance():
            calls.append(True)
            if len(calls)==3:write(self.flow.path,{'account':'#PYLQG','phase':'first_battle_returned'})
            return False
        self.flow.step=Mock(side_effect=advance);self.flow.dialog=Mock(return_value=None)
        self.runner.reader=Mock();self.runner.reader.home.return_value=True
        with patch('coc_bot.vision.battle_menu.home_build_control_visible',return_value=True):self.flow.drive()
        self.assertEqual(read(self.flow.path)['phase'],'complete')
        self.assertEqual(self.runner.wait.call_count,2)
        self.runner.tap.assert_not_called()

    def test_unknown_intro_still_stops_after_observation_grace_period(self):
        write(self.flow.path,{'account':'#PYLQG','phase':'first_travel_requested'})
        self.flow.step=Mock(return_value=False);self.flow.dialog=Mock(return_value=None)
        self.runner.reader=Mock();self.runner.reader.home.return_value=False
        clock=[0.0]
        self.runner.wait.side_effect=lambda seconds:clock.__setitem__(0,clock[0]+seconds)
        with patch('coc_bot.builder_base.onboarding.time.monotonic',side_effect=lambda:clock[0]):
            with self.assertRaisesRegex(ValueError,'Unrecognized'):self.flow.drive()
        self.assertEqual(clock[0],12)
        self.runner.tap.assert_not_called()

    def test_first_sail_uses_exact_caption_and_boat_after_camera_recenters(self):
        frame=self.frame('setup-rebuilt-sail.png')
        found=self.flow.dialog(frame)
        self.assertEqual(found[0],'first_sail')
        self.assertEqual(found[1],(926,387))
        frame[340:430,880:970]=0
        self.assertNotEqual((self.flow.dialog(frame) or (None,))[0],'first_sail')

    def test_first_sail_allows_only_small_bobbing_between_fresh_observations(self):
        write(self.flow.path,{'account':'#PYLQG','phase':'boat_rebuilt'})
        self.flow.dialog=Mock(side_effect=[('first_sail',(926,387)),('first_sail',(926,393))])
        self.runner.tap.side_effect=lambda _:self.assertEqual(read(self.flow.path)['phase'],'first_sail_requested')
        self.assertTrue(self.flow.advance_dialog())
        self.runner.tap.assert_called_once_with((926,393))

    def test_rebuilt_boat_closes_a_verified_build_sidebar_before_travel(self):
        state={'account':'#PYLQG','phase':'boat_rebuilt'}
        reader=Mock();reader.menu_kind.return_value='buildings'
        with patch('coc_bot.progression.reader.ProgressionReader',return_value=reader):
            self.assertTrue(self.flow.resume_first_sail(self.runner.frame(),state))
        self.runner.tap.assert_called_once_with((1823,34))
        self.assertEqual(state['phase'],'boat_rebuilt')

    def test_rebuilt_boat_reacquires_travel_bubble_and_records_intent_before_input(self):
        state={'account':'#PYLQG','phase':'boat_rebuilt'}
        self.runner.home_village=Mock(return_value=True)
        self.runner.reader=Mock();self.runner.reader.find.side_effect=[(570,650),(572,652)]
        self.flow.dialog=Mock(return_value=None)
        self.runner.tap.side_effect=lambda _:self.assertEqual(read(self.flow.path)['phase'],'first_sail_requested')
        reader=Mock();reader.menu_kind.return_value=None
        with patch('coc_bot.progression.reader.ProgressionReader',return_value=reader):
            self.assertTrue(self.flow.resume_first_sail(self.runner.frame(),state))
        self.runner.tap.assert_called_once_with((572,652))
        self.assertEqual(read(self.flow.path)['travel_attempts'],1)

    def test_first_sail_recovery_cannot_cross_accounts_or_pending_payments(self):
        for state in ({'account':'#OTHER','phase':'boat_rebuilt'},
                      {'account':'#PYLQG','phase':'boat_rebuilt','pending_payment':{'cost':3500}}):
            self.assertFalse(self.flow.resume_first_sail(self.runner.frame(),state))
        self.runner.tap.assert_not_called()

    def test_first_sail_does_not_use_a_bubble_that_moved_across_the_map(self):
        state={'account':'#PYLQG','phase':'boat_rebuilt'}
        self.runner.home_village=Mock(return_value=True)
        self.runner.reader=Mock();self.runner.reader.find.side_effect=[(570,650),(700,650)]
        self.flow.dialog=Mock(return_value=None)
        reader=Mock();reader.menu_kind.return_value=None
        with patch('coc_bot.progression.reader.ProgressionReader',return_value=reader):
            self.assertFalse(self.flow.resume_first_sail(self.runner.frame(),state))
        self.runner.tap.assert_not_called()

    def test_free_boat_can_be_found_below_the_first_build_page(self):
        base=np.zeros((1048,1853,3),np.uint8);later=base.copy();later[:,1360:]=100
        row={'name':'Boat','cost':0,'currency':'free','box':[1358,500,495,80],'point':(1594,540)}
        self.runner.home_village=Mock(return_value=True);self.runner.input=Mock();self.runner.capture=Mock();self.runner.nav=Mock()
        self.runner.frame.side_effect=[base,base,later,later]
        self.flow.rebuild_free_boat=Mock(return_value=True)
        reader=Mock();reader.menu_kind.return_value='buildings';reader.rows.side_effect=[[],[row],[row]]
        navigation=Mock();navigation.clear_filters.return_value=base
        with patch('coc_bot.vision.battle_menu.home_build_control_visible',return_value=True),\
             patch('coc_bot.progression.reader.ProgressionReader',return_value=reader),\
             patch('coc_bot.progression.runner.ProgressionRunner',return_value=navigation):
            self.assertTrue(self.flow.prepare())
        self.runner.input.swipe.assert_called_once()
        self.flow.rebuild_free_boat.assert_called_once()
        self.assertEqual(self.runner.tap.call_args_list[-1].args,(row['point'],))

    @unittest.skipUnless(shutil.which('tesseract'),'Home Build label requires Tesseract')
    def test_tutorial_boat_selection_requires_boat_and_its_adjacent_arrow(self):
        for name in ('setup-existing-boat.png','setup-existing-boat-bounce.png'):
            frame=self.frame(name)
            self.assertIsNotNone(self.runner.reader.setup_boat_target(frame),name)
            for box in ((440,660,610,790),(440,515,610,660),(1640,840,1853,1048)):
                bad=frame.copy();x,y,u,v=box;bad[y:v,x:u]=0
                self.assertIsNone(self.runner.reader.setup_boat_target(bad))
            self.assertIsNone(self.runner.reader.setup_boat_target((frame*.4).astype('uint8')))

    @unittest.skipUnless(shutil.which('tesseract'),'Home Build label requires Tesseract')
    def test_ready_boat_navigation_is_journaled_once_and_other_accounts_cannot_claim_it(self):
        frame=self.frame('setup-existing-boat.png')
        self.runner.home_village=Mock(return_value=True);self.runner.frame.return_value=frame
        self.runner.tap.side_effect=lambda _:self.assertEqual(read(self.flow.path)['phase'],'selecting_boat')
        with patch('coc_bot.builder_base.onboarding.backup',return_value=Path('verified-backup')) as snapshot:
            self.assertTrue(self.flow.select_setup_boat(frame))
            snapshot.assert_called_once()
        self.assertEqual(read(self.flow.path)['source'],'visible_uninitialized_boat')
        self.runner.tap.assert_called_once()
        write(self.flow.path,{'account':'#YQGRJPC2L','phase':'first_sail_requested'})
        self.assertFalse(self.flow.select_setup_boat(frame))
        self.runner.tap.assert_called_once()

    @unittest.skipUnless(shutil.which('tesseract'),'Home Build label requires Tesseract')
    def test_selected_boat_requires_free_label_title_and_rebuild_control(self):
        frame=self.frame('setup-selected-boat.png')
        self.assertIsNotNone(self.runner.reader.selected_boat_rebuild(frame))
        for box in ((855,670,1005,725),(880,730,975,775),(850,845,1005,895)):
            bad=frame.copy();x,y,u,v=box;bad[y:v,x:u]=0
            self.assertIsNone(self.runner.reader.selected_boat_rebuild(bad))
        self.assertIsNone(self.runner.reader.selected_boat_rebuild((frame*.4).astype('uint8')))

    @unittest.skipUnless(shutil.which('tesseract'),'Home Build label requires Tesseract')
    def test_selected_free_rebuild_still_requires_native_free_confirmation(self):
        selected=self.frame('setup-selected-boat.png');confirmed=self.frame('setup-boat.png')
        world=self.frame('setup-existing-boat.png')
        write(self.flow.path,{'account':'#PYLQG','phase':'first_sail_requested','backup':'verified-backup'})
        self.runner.frame.side_effect=[selected,selected,confirmed,confirmed,world]
        phases=[];self.runner.tap.side_effect=lambda _:phases.append(read(self.flow.path)['phase'])
        self.assertTrue(self.flow.step())
        self.assertEqual(phases,['inspecting_free_boat_rebuild','rebuilding_free_boat'])
        self.assertEqual(read(self.flow.path)['phase'],'boat_rebuilt')

    def test_research_requires_the_exact_price_currency_and_ability(self):
        frame=self.frame('setup-research-confirm.png')
        self.assertEqual(self.flow.payment(frame)['currency'],'elixir')
        self.assertEqual(self.flow.payment(frame)['cost'],3500)
        for box in ((703,50,1147,91),(1090,272,1453,304),(1220,768,1302,809),(1460,879,1522,950)):
            bad=frame.copy();x,y,u,v=box;bad[y:v,x:u]=0
            self.assertIsNone(self.flow.payment(bad))
        self.assertIsNone(self.flow.payment((frame*.5).astype('uint8')))

    def test_boosted_starter_hall_still_requires_gold_price_and_expected_level(self):
        frame=self.frame('setup-hall-boosted.png')
        payment=self.flow.payment(frame)
        self.assertEqual((payment['name'],payment['cost'],payment['currency']),('Builder Hall',3500,'gold'))
        for box in ((385,444,455,498),(580,40,1180,110),(775,880,1007,970)):
            bad=frame.copy();x,y,u,v=box;bad[y:v,x:u]=0
            self.assertIsNone(self.flow.payment(bad))

    def test_boosted_starter_research_keeps_the_same_unit_price_and_currency_guards(self):
        frame=self.frame('setup-research-boosted.png')
        payment=self.flow.payment(frame)
        self.assertEqual((payment['name'],payment['cost'],payment['currency']),('Raged Barbarian',3500,'elixir'))
        bad=frame.copy();bad[768:809,1220:1302]=0
        self.assertIsNone(self.flow.payment(bad))

    def payment_case(self):
        payment={'point':(100,200),'requires':'inspect_first_barbarian','name':'Raged Barbarian',
            'cost':3500,'currency':'elixir','seconds':30,'phase':'first_research_complete'}
        self.flow.payment=Mock(return_value=payment)
        write(self.flow.path,{'account':'#PYLQG','last_dialog':'inspect_first_barbarian'})

    def test_payment_journal_precedes_input_and_gems_must_not_change(self):
        self.payment_case()
        self.runner.tap.side_effect=lambda _:self.assertIn('pending_payment',read(self.flow.path))
        with patch('coc_bot.builder_base.onboarding.resource_amount',side_effect=[12575,780,12575,780,9075,780]):
            self.assertTrue(self.flow.step())
        self.assertNotIn('pending_payment',read(self.flow.path))
        self.assertEqual(read(self.flow.path)['phase'],'first_research_complete')

    def test_uncertain_payment_never_repeats(self):
        self.payment_case()
        with patch('coc_bot.builder_base.onboarding.resource_amount',side_effect=[12575,780,12575,780,9075,779]):
            with self.assertRaisesRegex(ValueError,'needs review'):self.flow.step()
        self.assertIn('pending_payment',read(self.flow.path))
        with self.assertRaisesRegex(ValueError,'no retry'):self.flow.step()
        self.runner.tap.assert_called_once()

    def test_stop_during_payment_retains_recovery_record(self):
        self.payment_case();self.runner.tap.side_effect=AdbStopped('stop')
        with patch('coc_bot.builder_base.onboarding.resource_amount',side_effect=[12575,780,12575,780]):
            with self.assertRaises(AdbStopped):self.flow.step()
        self.assertIn('pending_payment',read(self.flow.path))

    def test_other_account_cannot_advance_setup(self):
        write(self.flow.path,{'account':'#YQGRJPC2L','phase':'first_research_complete'})
        self.assertFalse(self.flow.step());self.runner.frame.assert_not_called()

    def test_gold_tooltip_is_not_elixir_capacity(self):
        reader=self.runner.reader;frame=self.frame('storage-gold.png')
        self.assertEqual(reader.storage_capacity(frame,'gold'),75000)
        self.assertIsNone(reader.storage_capacity(frame,'elixir'))
        frame[110:139,1622:1690]=0
        self.assertIsNone(reader.storage_capacity(frame,'gold'))

    def test_tutorial_deploy_is_limited_to_npc_and_recognized_card(self):
        frame=self.frame('setup-tutorial-battle.png')
        self.assertEqual(self.flow.first_battle(frame),3)
        frame[50:86,92:361]=0
        self.assertIsNone(self.flow.first_battle(frame))
