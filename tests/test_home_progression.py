from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, skipUnless
from unittest.mock import Mock, patch
import shutil
import tempfile
import cv2
import numpy as np

from coc_bot.config import BotConfig
from coc_bot.attack.army import ArmyCard
from coc_bot.progression.army import composition, farming_plan
from coc_bot.progression.policy import town_hall_blockers, priority
from coc_bot.progression.reader import ProgressionReader
from coc_bot.progression.construction import controls, Construction
from coc_bot.upgrades.vision import compact, crop

FIXTURES = Path(__file__).parent/'fixtures/progression'


class LabPriorityTests(TestCase):
    def test_lab_precedes_new_buildings_but_other_new_buildings_precede_upgrades(self):
        rows=[{'name':'Cannon','new':True,'cost':100},
              {'name':'Army Camp','new':False,'cost':100},
              {'name':'Laboratory','new':False,'cost':1000},
              {'name':'Town Hall','new':False,'cost':100}]
        self.assertEqual([r['name'] for r in sorted(rows,key=priority)],
                         ['Laboratory','Cannon','Army Camp','Town Hall'])
class ProgressionPolicyTests(TestCase):
    def test_research_padlock_requires_the_actual_lock_and_build_menu(self):
        reader=ProgressionReader()
        frame=cv2.imread(str(FIXTURES/'barracks-red-price-list.png'))
        with patch.object(reader,'menu_kind',return_value='buildings'):
            self.assertTrue(reader.research_locked(frame))
            frame[945:1020,1495:1580]=0
            self.assertFalse(reader.research_locked(frame))
        with patch.object(reader,'menu_kind',return_value=None):
            self.assertFalse(reader.research_locked(cv2.imread(str(FIXTURES/'barracks-red-price-list.png'))))

    def test_locked_lab_never_receives_a_tab_or_payment_tap(self):
        from coc_bot.progression.runner import ProgressionRunner,ResearchUnavailable
        runner=ProgressionRunner.__new__(ProgressionRunner)
        runner.stop=None;runner.input=Mock();runner.capture=Mock();runner.reader=Mock()
        runner.reader.menu_kind.return_value='buildings'
        runner.reader.research_locked.return_value=True
        with patch('coc_bot.upgrades.runner.UpgradeRunner.open_menu',return_value=object()) as opened:
            with self.assertRaises(ResearchUnavailable):runner.open_menu('research')
            opened.assert_called_once_with('buildings')
        runner.input.tap.assert_not_called()
        runner.reader.research_locked.side_effect=[True,False]
        with patch('coc_bot.upgrades.runner.UpgradeRunner.open_menu',return_value=object()):
            with self.assertRaisesRegex(ValueError,'availability changed'):runner.open_menu('research')
        runner.input.tap.assert_not_called()

    def test_camp_fraction_uses_digits_and_a_real_slash_without_ocr(self):
        from coc_bot.progression.preparation import capacity
        for name,expected in [('army-editor.png',(20,20)),('troop-picker.png',(20,20)),
                              ('dimmed-picker.png',(20,20)),('army-expanded.png',(20,30)),
                              ('army-partial.png',(21,30)),('army-28.png',(28,30)),
                              ('army-15.png',(15,30)),('army-12.png',(12,30)),('army-26.png',(26,30)),
                              ('unlocked-picker.png',(30,30))]:
            with self.subTest(name=name):
                frame=cv2.imread(str(FIXTURES/name));self.assertEqual(capacity(frame),expected)
                frame[215:267,584:834]=0
                self.assertIsNone(capacity(frame))
    def test_picker_reference_matches_giant_but_rejects_archer_with_same_level_badge(self):
        from coc_bot.attack.army import UnitCatalog
        from coc_bot.progression.troop_info import remember_reference
        frame=cv2.imread(str(FIXTURES/'unlocked-picker.png'))
        giant=frame[629:809,234:418];archer=frame[825:1005,46:230]
        with tempfile.TemporaryDirectory() as folder:
            catalog=UnitCatalog(Path(folder))
            remember_reference(Path(folder)/'learned',catalog,'giant',giant)
            match=catalog.identify_reference(giant,kind='troop')
            self.assertIsNotNone(match)
            self.assertEqual(match[0],'giant')
            self.assertIsNone(catalog.identify_reference(archer,kind='troop'))
    def test_info_artwork_cache_requires_known_name_and_matching_image_digest(self):
        from coc_bot.progression.troop_info import remember_reference,load_references
        import json
        with tempfile.TemporaryDirectory() as folder:
            catalog=Mock();root=Path(folder);cell=np.zeros((180,184,3),np.uint8)
            remember_reference(root,catalog,'giant',cell)
            catalog.reset_mock();load_references(root,catalog)
            catalog.add_references.assert_called_once()
            (root/'giant.json').write_text('[]');catalog.reset_mock()
            load_references(root,catalog);catalog.add_references.assert_not_called()
            (root/'giant.json').write_text(json.dumps({'unit_id':'giant','source':'two_info_frames','sha256':'wrong'}))
            load_references(root,catalog);catalog.add_references.assert_not_called()
            with self.assertRaises(ValueError):remember_reference(root,catalog,'../unknown',cell)

    def test_geometrically_verified_picker_reference_is_not_an_alpha_score(self):
        from coc_bot.progression.preparation import picker_unlocks
        catalog=Mock();catalog.identify_reference.return_value=('barbarian','troop',.9,1.)
        with patch('coc_bot.progression.preparation.picker_boxes',return_value=[(0,0,184,180)]),\
             patch('coc_bot.progression.preparation.picker_level',return_value=1):
            self.assertEqual(picker_unlocks(np.zeros((180,184,3),np.uint8),catalog)['barbarian']['level'],1)
        catalog.identify.assert_not_called()

    def test_disagreeing_troop_info_never_labels_artwork_or_edits_army(self):
        from coc_bot.progression.preparation import ArmyPreparation
        prep=ArmyPreparation.__new__(ArmyPreparation);prep.stop=None;prep.references=Path('unused')
        prep.catalog=Mock();prep.catalog.identify_reference.return_value=None
        prep.catalog.identify.return_value=(None,'unknown',.96,.004)
        prep.tap=Mock();frame=np.zeros((1048,1853,3),np.uint8);prep.frame=Mock(return_value=frame)
        giant={'unit_id':'giant','level':1,'close':(1642,79)}
        with patch('coc_bot.progression.preparation.picker_boxes',return_value=[(234,629,184,180)]),\
             patch('coc_bot.progression.preparation.picker_level',return_value=1),\
             patch('coc_bot.progression.preparation.info_point',return_value=(153,29)),\
             patch('coc_bot.progression.preparation.read_info',side_effect=[giant,giant|{'unit_id':'archer'}]),\
             patch('coc_bot.progression.preparation.remember_reference') as remember:
            with self.assertRaisesRegex(ValueError,'did not agree'):prep.learn_unlocks(frame)
            remember.assert_not_called()
        prep.tap.assert_called_once_with((387,658))
    def test_wall_queue_requires_exact_target_level_count_and_complete_evidence_for_zero(self):
        from coc_bot.progression.walls import queue_count
        row={'name':'Wall','cost':1000,'currency':'gold','target_level':2,'quantity':25}
        self.assertEqual(queue_count([row],row,2),25)
        self.assertIsNone(queue_count([row,row],row,2))
        self.assertIsNone(queue_count([row|{'target_level':None}],row,2,complete=True))
        self.assertIsNone(queue_count([],row,2))
        self.assertEqual(queue_count([],row,2,complete=True),0)

    def test_wall_queue_confirmation_checks_two_frames_without_repaying(self):
        from coc_bot.progression.walls import WallUpgrade
        row={'name':'Wall','cost':1000,'currency':'gold','target_level':2,'quantity':24}
        runner=Mock();runner.stop=None;runner.stopped.return_value=False
        runner.reader.menu_kind.return_value='buildings';runner.reader.rows.return_value=[row]
        runner.reader.balances.return_value={'gold':2633}
        self.assertTrue(WallUpgrade(runner).confirm_queue(row,2,25,object(),2633))
        runner.input.tap.assert_not_called()
        runner.reader.rows.return_value=[row|{'quantity':23}]
        self.assertFalse(WallUpgrade(runner).confirm_queue(row,2,25,object(),2633))

    def test_last_wall_requires_two_complete_readable_inventories(self):
        from coc_bot.progression.walls import WallUpgrade
        row={'name':'Wall','cost':1000,'currency':'gold','target_level':2,'quantity':1}
        runner=Mock();runner.stop=None;runner.stopped.return_value=False
        good={'complete':True,'unfiltered':True,'unknown':False,'balances':{'gold':2633},'rows':[]}
        runner.scan.side_effect=[good,good|{'complete':False}]
        self.assertFalse(WallUpgrade(runner).confirm_queue(row,2,1,object(),2633))
        runner.scan.side_effect=[good,good]
        self.assertTrue(WallUpgrade(runner).confirm_queue(row,2,1,object(),2633))
        runner.input.tap.assert_not_called()
    def test_wall_payment_checks_home_counter_and_confirms_level_and_exact_cost(self):
        from coc_bot.progression.walls import WallUpgrade
        row={'name':'Wall','currency':'gold','cost':1000,'point':(100,200)}
        before={'level':1,'cost':1000,'currency':'gold','upgrade':True,'point':(500,800)}
        frame=np.zeros((1048,1853,3),np.uint8)
        with tempfile.TemporaryDirectory() as folder:
            runner=Mock();runner.path=Path(folder)/'state.json';runner.stop=None
            runner.find_row.return_value=(row,frame);runner.reader.balances.return_value={'gold':2000}
            runner.reader.availability.return_value=(2,2);runner.eligibility.return_value=None
            runner.stopped.return_value=False;runner.wait.return_value=False;runner.state.return_value={}
            runner.capture.screenshot.return_value=frame;runner.reader.confirmation.return_value=None
            runner.reader.menu_kind.return_value=None
            with patch('coc_bot.progression.walls.wall_panel',side_effect=[before,before,before|{'level':2}]),\
                 patch('coc_bot.progression.walls.balance_amount',side_effect=[2000,1000]):
                report=WallUpgrade(runner).run(row)
            self.assertEqual(report['status'],'started')
            self.assertEqual(runner.input.tap.call_count,2)
            import json
            state=json.loads(runner.path.read_text())
            self.assertNotIn('pending',state)
            self.assertEqual(state['last_completed']['level_after'],2)

    def test_wall_unreadable_home_balance_blocks_before_payment(self):
        from coc_bot.progression.walls import WallUpgrade
        row={'name':'Wall','currency':'gold','cost':1000,'point':(100,200)}
        panel={'level':1,'cost':1000,'currency':'gold','upgrade':True,'point':(500,800)}
        runner=Mock();runner.stop=None;frame=np.zeros((1048,1853,3),np.uint8)
        runner.find_row.return_value=(row,frame);runner.reader.balances.return_value={'gold':2000}
        runner.eligibility.return_value=None;runner.stopped.return_value=False;runner.wait.return_value=False
        runner.capture.screenshot.return_value=frame
        runner.reader.menu_kind.return_value=None
        with patch('coc_bot.progression.walls.wall_panel',return_value=panel),\
             patch('coc_bot.progression.walls.balance_amount',return_value=None):
            report=WallUpgrade(runner).run(row)
        self.assertEqual(report['status'],'blocked')
        runner.input.tap.assert_called_once_with(100,200,jitter=0)
        runner.state.assert_not_called()

    def test_wall_balance_requires_the_observed_sidebar_or_home_layout(self):
        from coc_bot.progression.walls import wall_balance
        reader=Mock();reader.menu_kind.return_value='buildings';reader.balances.return_value={'gold':3633}
        frame=np.zeros((1048,1853,3),np.uint8)
        with patch('coc_bot.progression.walls.balance_amount',return_value=9000) as home:
            self.assertEqual(wall_balance(frame,reader,'gold'),3633)
            home.assert_not_called()
            reader.menu_kind.return_value=None
            self.assertEqual(wall_balance(frame,reader,'gold'),9000)
            reader.menu_kind.return_value='research'
            self.assertIsNone(wall_balance(frame,reader,'gold'))

    def test_batched_adb_input_is_bounded_integer_only_and_honors_stop(self):
        from coc_bot.adb.input import InputController
        from coc_bot.adb.client import AdbStopped
        client=Mock();client.stop_check=lambda:False;client.wm_size.return_value=(1000,600)
        control=InputController(client,delay_ms=(0,0))
        with patch('coc_bot.adb.input.recorder.note_action'):
            control.tap_many([(200,300),(210,310)])
        client.run_shell.assert_called_once_with('input tap 200 300 && input tap 210 310')
        client.run_shell.reset_mock()
        for points in ([],[(1,2)]*6,[(1.5,2)],[(True,2)],[('1; x',2)]):
            with self.assertRaises(ValueError):control.tap_many(points)
        client.run_shell.assert_not_called()
        client.stop_check=lambda:True
        with self.assertRaises(AdbStopped):control.tap_many([(200,300)])
        client.run_shell.assert_not_called()

    def test_starter_envelope_requires_outline_stationarity_and_visibility(self):
        from coc_bot.progression.mapping import compact_projection
        from coc_bot.attack.plans import MapPoint
        frame=cv2.imread(str(FIXTURES/'sparse-boundary.png'))
        p=compact_projection(frame,frame)
        self.assertIsNotNone(p)
        for y in (.27,.5,.73):
            target=p.pixel(MapPoint(.055,y))
            self.assertLess(cv2.pointPolygonTest(np.float32(p.corners),target,True),-10)
        shifted=cv2.warpAffine(frame,np.float32([[1,0,20],[0,1,0]]),(frame.shape[1],frame.shape[0]))
        self.assertIsNone(compact_projection(frame,shifted))
        blank=np.zeros_like(frame)
        self.assertIsNone(compact_projection(blank,blank))

    def test_starter_long_walls_keep_all_deployments_clear_of_controls(self):
        from coc_bot.progression.mapping import compact_projection,deployment_line
        from coc_bot.attack.projection import step_points,input_area
        frame=cv2.imread(str(FIXTURES/'long-wall-boundary.png'))
        p=compact_projection(frame,frame)
        self.assertIsNotNone(p)
        line=deployment_line(p,frame.shape[1],frame.shape[0])
        cards=[ArmyCard('0',(0,0,140,160),'barbarian','troop',20,stable=True)]
        plan=farming_plan(cards,deploy_line=line)
        for point in step_points(plan.steps[0]):
            x,y=p.pixel(point)
            self.assertTrue(input_area(x,y,frame.shape[1],frame.shape[0]))
            self.assertLess(cv2.pointPolygonTest(np.float32(p.corners),(x,y),True),-10)

    def test_short_starter_footprints_enclose_the_whole_observed_village(self):
        from coc_bot.progression.mapping import compact_projection, deployment_line
        from coc_bot.attack.mapping import boundary_mask
        from coc_bot.attack.projection import input_area
        from coc_bot.attack.plans import MapPoint
        before=cv2.imread(str(FIXTURES/'compact-short-steps-before.png'))
        after=cv2.imread(str(FIXTURES/'compact-short-steps-after.png'))
        p=compact_projection(before,after)
        self.assertIsNotNone(p)
        # Both disconnected footprints, including the lower castle, must be
        # inside the envelope; all deployment points stay outside and off HUD.
        for x,y in ((719,421),(861,338),(1145,433),(957,622),(813,731)):
            self.assertGreaterEqual(cv2.pointPolygonTest(np.float32(p.corners),(x,y),True),0)
        first,last=deployment_line(p,after.shape[1],after.shape[0])
        for y in np.linspace(first.y,last.y,30):
            xy=p.pixel(MapPoint(first.x,float(y)))
            self.assertTrue(input_area(*xy,after.shape[1],after.shape[0]))
            self.assertLess(cv2.pointPolygonTest(np.float32(p.corners),xy,True),-10)
        shifted=cv2.warpAffine(after,np.float32([[1,0,10],[0,1,0]]),
                               (after.shape[1],after.shape[0]))
        self.assertIsNone(compact_projection(before,shifted))
        # A missing outline in the preceding frame cannot authorize taps.
        mask=boundary_mask(after)
        with patch('coc_bot.progression.mapping.boundary_mask',
                   side_effect=[mask,np.zeros_like(mask)]):
            self.assertIsNone(compact_projection(before,after))

    def test_starter_partial_or_single_direction_outline_never_authorizes_taps(self):
        from coc_bot.progression.mapping import compact_projection
        from coc_bot.attack.mapping import boundary_mask
        frame=cv2.imread(str(FIXTURES/'compact-short-steps-after.png'))
        # A footprint touching the observation crop is not a complete survey.
        mask=boundary_mask(frame)
        cv2.line(mask,(280,400),(340,445),255,1)
        with patch('coc_bot.progression.mapping.boundary_mask',return_value=mask):
            self.assertIsNone(compact_projection(frame,frame))
        # Many parallel fragments still lack the other map direction.
        mask[:]=0
        for y in range(300,650,50):cv2.line(mask,(700,y),(780,y+60),255,1)
        with patch('coc_bot.progression.mapping.boundary_mask',return_value=mask):
            self.assertIsNone(compact_projection(frame,frame))

    def test_unresolved_payment_never_falls_back_to_legacy_purchases(self):
        from coc_bot.progression.runner import ProgressionRunner
        for pending in ({'kind':'wall'}, {'kind':'construction'}, ['bad journal']):
            runner=ProgressionRunner.__new__(ProgressionRunner)
            runner.state=lambda:{'pending':pending}
            runner.input=Mock()
            self.assertEqual(runner.run('buildings',execute=True)['status'],'needs_review')
            runner.input.tap.assert_not_called()

    def test_recovery_finishes_without_starting_another_upgrade(self):
        from coc_bot.progression.runner import ProgressionRunner
        runner=ProgressionRunner.__new__(ProgressionRunner)
        runner.state=lambda:{'pending':{'kind':'buildings'}}
        runner.open_menu=Mock(return_value=object());runner.close=Mock()
        runner._verify_pending=Mock(return_value=True);runner.stopped=lambda:False
        runner.input=Mock()
        with patch('coc_bot.upgrades.runner.UpgradeRunner.run',side_effect=AssertionError('must not spend')):
            self.assertEqual(runner.run('buildings',execute=True)['status'],'recovered')
        runner.input.tap.assert_not_called()

    def test_hall_reading_is_current_level_and_rejects_unrelated_titles(self):
        from coc_bot.progression.preparation import hall_from_titles
        self.assertEqual(hall_from_titles('Upgrade Town Hall to Level 3',''),2)
        self.assertEqual(hall_from_titles('','Town Hall (Level 2)'),2)
        self.assertIsNone(hall_from_titles('Upgrade Gold Storage to Level 3',''))
        self.assertIsNone(hall_from_titles('','Town Hall (Level I)'))
        self.assertIsNone(hall_from_titles('','Town Hall (Level 1)'))

    def test_locked_portrait_has_no_verified_level_chip(self):
        from coc_bot.progression.preparation import picker_boxes,level_chip,picker_level
        frame=cv2.imread(str(FIXTURES/'troop-picker.png'))
        boxes=picker_boxes(frame)
        barb=next(b for b in boxes if b[0]<100 and b[1]<700)
        archer=next(b for b in boxes if b[0]<100 and b[1]>800)
        def cell(b):
            x,y,w,h=b;return frame[y:y+h,x:x+w]
        self.assertIsNotNone(level_chip(cell(barb)))
        self.assertIsNone(level_chip(cell(archer)))
        self.assertEqual(picker_level(cell(barb)),1)
        self.assertIsNone(picker_level(cell(archer)))

    def test_construction_filter_refuses_gems_before_any_input(self):
        from coc_bot.progression.runner import ProgressionRunner
        runner=ProgressionRunner.__new__(ProgressionRunner);runner.input=Mock()
        with self.assertRaises(ValueError):runner.filter_resource(None,'gems')
        runner.input.tap.assert_not_called()

    def test_rejected_army_edit_closes_known_ui_and_keeps_original_failure(self):
        from coc_bot.progression.preparation import ArmyPreparation
        prep=ArmyPreparation.__new__(ArmyPreparation)
        prep.stop=None;prep._prepare=Mock(side_effect=ValueError('count changed'))
        prep.close=Mock(side_effect=ValueError('unknown overlay'))
        with self.assertRaisesRegex(ValueError,'count changed'):prep.prepare()
        prep.close.assert_called_once()

    def test_stopped_army_preparation_never_sends_cleanup_inputs(self):
        from coc_bot.progression.preparation import ArmyPreparation
        from coc_bot.adb.client import AdbStopped
        prep=ArmyPreparation.__new__(ArmyPreparation)
        prep.stop=lambda:True;prep._prepare=Mock(side_effect=AdbStopped('stop'))
        prep.close=Mock()
        with self.assertRaises(AdbStopped):prep.prepare()
        prep.close.assert_not_called()

    def test_army_edit_rechecks_delayed_count_without_repeating_input(self):
        from coc_bot.progression.preparation import ArmyPreparation
        prep=ArmyPreparation.__new__(ArmyPreparation);prep.tap=Mock();prep.s=Mock()
        def observation(n):return None,[ArmyCard('card',(0,0,100,150),'barbarian','troop',n,stable=True)],(n,30)
        prep.observe=Mock(side_effect=[observation(20),observation(20),ValueError('changing badge'),observation(21),observation(21)])
        prep.catalog=Mock();prep.stop=None
        with patch('coc_bot.progression.preparation.picker_unlocks',return_value={'barbarian':{'level':1,'point':(138,746)}}),\
             patch('coc_bot.progression.preparation.capacity',return_value=(20,30)):
            prep.adjust({'barbarian':21},{'barbarian':{'level':1,'point':(138,746)}})
        prep.tap.assert_called_once_with((138,746))

    def test_uncertain_army_edit_stops_after_one_input(self):
        from coc_bot.progression.preparation import ArmyPreparation
        prep=ArmyPreparation.__new__(ArmyPreparation);prep.tap=Mock();prep.s=Mock()
        observation=(None,[ArmyCard('card',(0,0,100,150),'barbarian','troop',20,stable=True)],(20,30))
        prep.observe=Mock(return_value=observation)
        prep.catalog=Mock();prep.stop=None
        with patch('coc_bot.progression.preparation.picker_unlocks',return_value={'barbarian':{'level':1,'point':(138,746)}}),\
             patch('coc_bot.progression.preparation.capacity',return_value=(20,30)):
            with self.assertRaisesRegex(ValueError,'did not confirm'):
                prep.adjust({'barbarian':21},{'barbarian':{'level':1,'point':(138,746)}})
        prep.tap.assert_called_once()

    def test_each_edit_reuses_the_previous_verified_pair_without_replaying_inputs(self):
        from coc_bot.progression.preparation import ArmyPreparation
        prep=ArmyPreparation.__new__(ArmyPreparation);prep.tap=Mock();prep.s=Mock();prep.catalog=Mock();prep.stop=None
        def observation(n):return None,[ArmyCard('card',(0,0,100,150),'barbarian','troop',n,stable=True)],(n,30)
        prep.observe=Mock(side_effect=[observation(10),observation(11),observation(12)])
        with patch('coc_bot.progression.preparation.picker_unlocks',return_value={'barbarian':{'level':1,'point':(138,746)}}),\
             patch('coc_bot.progression.preparation.capacity',side_effect=[(10,30),(11,30)]):
            prep.adjust({'barbarian':12},{'barbarian':{'level':1,'point':(138,746)}})
        self.assertEqual(prep.tap.call_count,2);self.assertEqual(prep.observe.call_count,3)

    def test_new_army_card_needs_one_named_addition_and_exact_housing_change(self):
        from coc_bot.progression.preparation import ArmyPreparation
        prep=ArmyPreparation.__new__(ArmyPreparation);prep.stop=None;prep.catalog=Mock();prep.s=Mock()
        prep.army_references=set();prep.small_references=Path('unused')
        frame=np.zeros((1048,1853,3),np.uint8);prep.frame=Mock(return_value=frame)
        known=ArmyCard('old',(546,278,148,150),'barbarian','troop',10,stable=True)
        added=ArmyCard('new',(700,278,148,150),None,'unknown',1)
        with patch('coc_bot.progression.preparation.army_page',return_value=True),\
             patch('coc_bot.progression.preparation.capacity',return_value=(15,30)),\
             patch('coc_bot.progression.preparation.read_army',return_value=[known,added]),\
             patch('coc_bot.progression.preparation.remember_reference') as remember:
            prep.learn_added_unit('giant',{'barbarian':10},(10,30))
            remember.assert_called_once()
            self.assertEqual(remember.call_args.args[2],'giant')
            self.assertFalse(remember.call_args.kwargs['picker'])
        self.assertIn('giant',prep.army_references)

    def test_new_card_identity_is_not_inferred_when_counts_or_housing_disagree(self):
        from coc_bot.progression.preparation import ArmyPreparation
        frame=np.zeros((1048,1853,3),np.uint8)
        known=ArmyCard('old',(546,278,148,150),'barbarian','troop',10,stable=True)
        added=ArmyCard('new',(700,278,148,150),None,'unknown',1)
        for cards,space in (([replace(known,quantity=11),added],(15,30)),
                            ([known,added,replace(added,box=(850,278,148,150))],(15,30)),
                            ([known,added],(14,30))):
            prep=ArmyPreparation.__new__(ArmyPreparation);prep.stop=None;prep.catalog=Mock();prep.s=Mock()
            prep.frame=Mock(return_value=frame);prep.small_references=Path('unused');prep.army_references=set()
            with patch('coc_bot.progression.preparation.army_page',return_value=True),\
                 patch('coc_bot.progression.preparation.capacity',return_value=space),\
                 patch('coc_bot.progression.preparation.read_army',return_value=cards),\
                 patch('coc_bot.progression.preparation.remember_reference') as remember:
                with self.assertRaisesRegex(ValueError,'did not agree'):
                    prep.learn_added_unit('giant',{'barbarian':10},(10,30))
                remember.assert_not_called()

    def test_starter_uses_real_unlocks_and_capacity(self):
        self.assertEqual(composition(2,20,{'barbarian':1}),{'barbarian':20})
        self.assertEqual(composition(2,30,{'barbarian':1,'archer':1}),{'barbarian':15,'archer':15})
        self.assertEqual(composition(2,30,{'barbarian':1,'archer':1,'giant':1}),
                         {'giant':2,'barbarian':10,'archer':10})
        with self.assertRaises(ValueError):composition(2,20,{})

    def test_town_hall_requires_full_unfiltered_and_finished_inventory(self):
        base={'complete':True,'unfiltered':True,'unknown':False,'busy':False,
              'rows':[{'name':'Town Hall','cost':4000,'currency':'gold','new':False}]}
        self.assertFalse(town_hall_blockers(base))
        for field,value in [('complete',False),('unfiltered',False),('unknown',True),('busy',True),('busy',None)]:
            self.assertTrue(town_hall_blockers(base|{field:value}))
        for row in ({'name':'Cannon','cost':999999,'new':False},
                    {'name':'Wall','new':False},{'name':'Elixir Collector','new':True},
                    {'name':'Barracks','cost':None,'new':False}):
            self.assertTrue(town_hall_blockers(base|{'rows':base['rows']+[row]}))
        premium={'name':"Builder's Hut",'new':True,'currency':'gems'}
        self.assertFalse(town_hall_blockers(base|{'rows':base['rows']+[premium]}))

    def test_new_buildings_sort_before_offensive_upgrades_and_town_hall(self):
        rows=[{'name':'Town Hall','cost':4000}, {'name':'Army Camp','cost':2000},
              {'name':'Cannon','new':True,'cost':250}]
        self.assertEqual([r['name'] for r in sorted(rows,key=priority)],['Cannon','Army Camp','Town Hall'])

    def test_th2_rebuild_exception_does_not_skip_other_buildings_or_th3_castle(self):
        hall={'name':'Town Hall','cost':4000,'currency':'gold'}
        castle={'name':'Clan Castle','cost':10000,'currency':'elixir','target_level':1}
        base={'complete':True,'unfiltered':True,'unknown':False,'busy':False,'hall':2,
              'hall_verified':True,'balances':{'elixir':8500},'rows':[hall,castle]}
        self.assertFalse(town_hall_blockers(base))
        for change in ({'hall':3},{'hall_verified':False},{'balances':{'elixir':10000}},
                       {'rows':[hall,castle|{'target_level':2}]},
                       {'rows':[hall,castle,{'name':'Wall'}]}):
            self.assertTrue(town_hall_blockers(base|change))

    def test_town_hall_agreement_tolerates_only_tiny_settling_of_identical_rows(self):
        from coc_bot.progression.reader import same_row_observation
        row={'name':'Town Hall','cost':4000,'currency':'gold','box':[1358,715,495,117]}
        self.assertTrue(same_row_observation(row,row|{'box':[1358,717,495,117]},(1048,1853,3)))
        self.assertFalse(same_row_observation(row,row|{'box':[1358,835,495,117]},(1048,1853,3)))
        self.assertFalse(same_row_observation(row,row|{'cost':5000},(1048,1853,3)))
        self.assertFalse(same_row_observation(row,row|{'name':'Clan Castle'},(1048,1853,3)))

    def test_ground_plan_tanks_before_ranged_and_no_locked_units(self):
        def card(unit,n):return ArmyCard(unit,(0,0,100,140),unit,'troop',n,stable=True)
        plan=farming_plan([card('archer',10),card('giant',2),card('barbarian',10)])
        self.assertEqual(plan.strategy,'farming_ground')
        self.assertEqual(plan.steps[0].unit_id,'giant')
        self.assertEqual(plan.steps[-1].unit_id,'archer')
        self.assertEqual(sum(s.quantity for s in plan.steps),22)
        with self.assertRaises(ValueError):farming_plan([replace(card('barbarian',20),stable=False)])
        with self.assertRaises(ValueError):farming_plan([card('unknown',20)])

    def test_placement_controls_require_both_checkmark_and_cancel(self):
        frame=cv2.imread(str(FIXTURES/'placement.png'))
        found=controls(frame)
        self.assertIsNotNone(found['confirm'])
        frame[515:560,910:955]=0
        self.assertIsNone(controls(frame)['confirm'])
        self.assertIsNone(controls(np.zeros_like(frame)))
        zoomed=controls(cv2.imread(str(FIXTURES/'placement-zoom.png')))
        self.assertIsNotNone(zoomed['confirm'])
        self.assertLess(abs(zoomed['confirm'][0]-1024),6)
        tall=controls(cv2.imread(str(FIXTURES/'tall-placement.png')))
        self.assertIsNotNone(tall['confirm'])
        self.assertLess(abs(tall['confirm'][1]-97),6)

    def test_stop_during_placement_sends_no_confirmation(self):
        runner=SimpleNamespace(capture=Mock(), stopped=lambda:True)
        runner.capture.screenshot.return_value=cv2.imread(str(FIXTURES/'placement.png'))
        self.assertIsNone(Construction(runner).locate_space())

    def test_electro_dragon_family_includes_support_balloons_and_rage(self):
        def card(u,n,kind='troop'):return ArmyCard(u,(0,0,100,140),u,kind,n,stable=True)
        plan=farming_plan([card('electro_dragon',8),card('balloon',4),card('rage',5,'spell')])
        self.assertEqual(plan.steps[0].unit_id,'balloon')
        self.assertEqual(sum(s.quantity for s in plan.steps if s.unit_id=='electro_dragon'),8)
        self.assertEqual(plan.steps[-1].action,'cast_points')
        self.assertEqual(plan.steps[-1].quantity,5)

    def test_no_donation_home_does_not_open_locked_chat(self):
        from coc_bot.progression.home import ensure_home
        nav=Mock();nav._stopping.return_value=False
        nav.classifier._clan_chat_anchor_visible.return_value=False
        nav.classifier.auxiliary_page.return_value=None
        nav.classifier.looks_like_blocking_popup.return_value=False
        with patch('coc_bot.progression.home.home_build_control_visible',return_value=True),patch('coc_bot.progression.home.interrupted_sleep',return_value=False):
            self.assertTrue(ensure_home(nav))
        nav.input.tap.assert_not_called()


@skipUnless(shutil.which('tesseract'),'Tesseract required for inspected UI fixtures')
class ProgressionReaderTests(TestCase):
    def test_running_starter_upgrade_requires_name_and_real_busy_builder_count(self):
        r=ProgressionReader();frame=cv2.imread(str(FIXTURES/'running-upgrade.png'))
        self.assertEqual(r.availability(frame,'buildings'),(1,2))
        self.assertIn('armycamp',r.active_names(frame))
        frame[988:1040,1360:1465]=0
        self.assertIsNone(r.availability(frame,'buildings'))

    def test_barracks_heading_font_correction_still_requires_exact_name_price_currency(self):
        from coc_bot.upgrades.vision import Candidate
        frame=cv2.imread(str(FIXTURES/'barracks-confirmation.png'));r=ProgressionReader()
        wanted=Candidate('Barracks',500,'elixir',(0,0))
        self.assertIsNotNone(r.confirmation(frame,wanted))
        for wrong in (replace(wanted,name='Cannon'),replace(wanted,cost=501),replace(wanted,currency='gold')):
            self.assertIsNone(r.confirmation(frame,wrong))

    def test_centered_battle_quantity_is_twenty_not_a_missing_badge(self):
        from coc_bot.attack.army import read_badge
        cell=cv2.imread(str(FIXTURES/'barbarian-card.png'))
        self.assertEqual(read_badge(cell),20)
        cell[:45]=0
        self.assertIsNone(read_badge(cell))

    def test_prepared_barbarian_identity_carries_to_the_live_battle_card(self):
        from coc_bot.attack.army import UnitCatalog,card_boxes,read_army,agree_cards
        import tempfile
        editor=cv2.imread(str(FIXTURES/'army-editor.png'))
        with tempfile.TemporaryDirectory() as folder:
            catalog=UnitCatalog(Path(folder))
        boxes=card_boxes(editor,'army_confirmation')
        self.assertEqual(len(boxes),1)
        catalog.add_references(editor,[ArmyCard('0',boxes[0],'barbarian','troop',20,confirmed=True)])
        frame=cv2.imread(str(FIXTURES/'barbarian-battle.png'))
        cards=agree_cards(read_army(frame,'battle',catalog),read_army(frame,'battle',catalog))
        self.assertEqual(len(cards),1)
        self.assertEqual((cards[0].unit_id,cards[0].quantity,cards[0].stable),('barbarian',20,True))

    def test_unaffordable_prices_and_balance_highlight_do_not_block_full_inventory(self):
        r=ProgressionReader();frame=cv2.imread(str(FIXTURES/'unaffordable-list.png'))
        self.assertEqual(r.balances(frame),{'gold':519,'elixir':1794,'dark_elixir':None})
        rows=r.rows(frame);camp=next(v for v in rows if compact(v['name'])=='armycamp')
        self.assertEqual(camp['cost'],2000)
        # Its partial row must be read after scrolling, never as missing price.
        self.assertFalse(any(compact(v['name'])=='archertower' for v in rows))

    def test_small_white_starter_counters_use_inspected_font_variants(self):
        reader=ProgressionReader()
        frame=cv2.imread(str(FIXTURES/'starter-short-balances.png'))
        self.assertEqual(reader.balances(frame),{'gold':136,'elixir':2635,'dark_elixir':None})
        frame[30:80,960:1260]=0
        self.assertIsNone(reader.balances(frame)['gold'])

    def test_conflicting_balance_reads_do_not_fall_back_to_another_font(self):
        from coc_bot.progression.reader import balance_amount
        frame=cv2.imread(str(FIXTURES/'starter-short-balances.png'))
        image=crop(frame,(.525,.035,.679,.072))
        with patch('coc_bot.progression.reader.amount',side_effect=[136,138]), \
             patch('coc_bot.upgrades.digits.read_digits') as extra:
            self.assertIsNone(balance_amount(image))
            extra.assert_not_called()

    def test_edit_army_requires_text_without_portrait_letters_and_green(self):
        from coc_bot.progression.preparation import edit_army_button
        from coc_bot.vision.battle_menu import direct_match_button
        frame=cv2.imread(str(FIXTURES/'attack-menu.png'))
        self.assertIsNotNone(edit_army_button(frame))
        point=direct_match_button(frame)
        self.assertIsNotNone(point)
        self.assertLess(point[0],760)
        frame[960:1030,160:350]=0
        self.assertIsNone(edit_army_button(frame))

    def test_town_hall_target_badge_is_read_without_opening_upgrade(self):
        r=ProgressionReader();frame=cv2.imread(str(FIXTURES/'locked-hall-list.png'))
        row=next(v for v in r.rows(frame) if compact(v['name'])=='townhall')
        self.assertEqual(r.target_level(frame,row),3)
        frame[840:873,1360:1405]=0
        self.assertIsNone(r.target_level(frame,row))

    def test_all_visible_new_rows_and_gems_are_distinct(self):
        r=ProgressionReader();rows=r.rows(cv2.imread(str(FIXTURES/'build.png')))
        by_name={compact(c['name']):c for c in rows}
        self.assertTrue(by_name['elixircollector']['new'])
        self.assertEqual(by_name['elixircollector']['cost'],150)
        self.assertEqual(by_name['buildershut']['currency'],'gems')
        self.assertEqual(by_name['armycamp']['cost'],2000)
        self.assertTrue(by_name['archertower']['new'])

    def test_red_barracks_price_does_not_block_the_complete_inventory(self):
        reader=ProgressionReader()
        rows=reader.rows(cv2.imread(str(FIXTURES/'barracks-red-price-list.png')))
        barracks=next(row for row in rows if compact(row['name'])=='barracks')
        self.assertEqual((barracks['cost'],barracks['currency']),(5000,'elixir'))
        self.assertEqual(next(r for r in rows if compact(r['name'])=='clancastle')['cost'],10000)

    def test_selected_filter_cannot_be_mistaken_for_unfiltered(self):
        r=ProgressionReader()
        clear=cv2.imread(str(FIXTURES/'filters.png'))
        selected=cv2.imread(str(FIXTURES/'filter-selected.png'))
        self.assertTrue(r.filters_open(clear))
        self.assertIsNone(r.selected_filter(clear))
        self.assertIsNotNone(r.selected_filter(selected))

    def test_low_hall_confirmation_without_cookbook(self):
        from coc_bot.vision.battle_menu import army_confirmation_button
        frame=cv2.imread(str(FIXTURES/'army-editor.png'))
        self.assertIsNotNone(army_confirmation_button(frame))
        frame[75:145,740:1150]=0
        self.assertIsNone(army_confirmation_button(frame))

    def test_ordinary_obstacle_requires_known_name_and_resource_price(self):
        from coc_bot.progression.space import obstacle
        frame=cv2.imread(str(FIXTURES/'ordinary-obstacle.png'))
        value=obstacle(frame)
        self.assertEqual(compact(value['name']),'trunk')
        self.assertEqual((value['cost'],value['currency']),(1000,'elixir'))
        frame[665:730,740:1040]=0
        self.assertIsNone(obstacle(frame))

    def test_my_army_capacity_and_picker_stay_separate_from_battle(self):
        from coc_bot.progression.preparation import capacity,picker_boxes,army_page
        frame=cv2.imread(str(FIXTURES/'army-editor.png'))
        self.assertEqual(capacity(frame),(20,20))
        self.assertTrue(army_page(frame))
        expanded=cv2.imread(str(FIXTURES/'army-expanded.png'))
        self.assertEqual(capacity(expanded),(20,30))
        self.assertTrue(army_page(expanded))
        partial=cv2.imread(str(FIXTURES/'army-partial.png'))
        self.assertEqual(capacity(partial),(21,30))
        twenty_eight=cv2.imread(str(FIXTURES/'army-28.png'))
        self.assertEqual(capacity(twenty_eight),(28,30))
        from coc_bot.attack.army import read_badge
        self.assertEqual(read_badge(twenty_eight[278:428,546:694]),28)
        twelve=cv2.imread(str(FIXTURES/'army-12.png'))
        self.assertEqual(read_badge(twelve[278:428,546:694]),12)
        picker=cv2.imread(str(FIXTURES/'troop-picker.png'))
        self.assertEqual(capacity(picker),(20,20))
        self.assertGreaterEqual(len(picker_boxes(picker)),18)
        dim=cv2.imread(str(FIXTURES/'dimmed-picker.png'))
        self.assertTrue(army_page(dim))
        dim[75:145,740:1150]=0
        self.assertFalse(army_page(dim))

    def test_wall_world_control_is_not_a_builder_timer_confirmation(self):
        from coc_bot.progression.walls import wall_panel
        frame=cv2.imread(str(FIXTURES/'wall-panel.png'))
        value=wall_panel(frame)
        self.assertEqual((value['level'],value['cost'],value['currency']),(1,1000,'gold'))
        self.assertTrue(value['upgrade'])

    def test_selected_wall_can_keep_the_sidebar_resource_counter(self):
        from coc_bot.progression.walls import wall_balance,wall_panel
        frame=cv2.imread(str(FIXTURES/'wall-sidebar.png'));reader=ProgressionReader()
        self.assertEqual(reader.menu_kind(frame),'buildings')
        self.assertEqual(wall_balance(frame,reader,'gold'),3633)
        self.assertEqual(wall_panel(frame)['level'],1)
        before=next(v for v in reader.rows(frame) if compact(v['name'])=='wall')
        self.assertEqual((before['quantity'],before['target_level']),(25,2))
        after=cv2.imread(str(FIXTURES/'wall-upgraded-sidebar.png'))
        changed=next(v for v in reader.rows(after) if compact(v['name'])=='wall')
        self.assertEqual((changed['quantity'],changed['target_level']),(24,2))
        self.assertEqual(wall_balance(after,reader,'gold'),2633)
        frame[25:85,925:1265]=0
        self.assertIsNone(wall_balance(frame,reader,'gold'))

    def test_native_troop_info_requires_name_level_housing_label_and_close(self):
        from coc_bot.progression.troop_info import read_info
        frame=cv2.imread(str(FIXTURES/'giant-info.png'))
        result=read_info(frame,expected_level=1)
        self.assertIsNotNone(result)
        self.assertEqual((result['unit_id'],result['level']),('giant',1))
        self.assertIsNone(read_info(frame,expected_level=2))
        archer=read_info(cv2.imread(str(FIXTURES/'archer-info.png')),expected_level=1)
        self.assertIsNotNone(archer)
        self.assertEqual(archer['unit_id'],'archer')
        frame[520:565,895:1140]=0
        self.assertIsNone(read_info(frame,expected_level=1))
