from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock,patch
import hashlib
import json
import time
import cv2
import numpy as np

from coc_bot.adb.client import AdbStopped
from coc_bot.attack.army import ArmyCard,zero_glyph,resolve_just_depleted,card_boxes
from coc_bot.attack.battle_gate import BattleFrameGate
from coc_bot.attack.executor import VerifiedExecutor,selected_card,hero_health_visible
from coc_bot.attack.plans import AttackPlan,ArmyEntry,PlanStep,MapPoint
from coc_bot.attack.projection import Projection,deployable,validate_geometry,fit_projection
from coc_bot.control.attack_planner import save_preview,execute_preview,load_template,learned_catalog
from coc_bot.control.attack_observation import write_report,read_report
from coc_bot.attack.planned_farmer import restore_camera


class ProjectionTests(TestCase):
    def projection(self):return Projection(((500,50),(900,300),(500,550),(100,300)))

    def test_round_trip_and_legal_deployment_band(self):
        projection=self.projection()
        point=MapPoint(.055,.5)
        np.testing.assert_allclose([projection.world(*projection.pixel(point)).x,projection.world(*projection.pixel(point)).y],
                                   [point.x,point.y],atol=1e-5)
        self.assertTrue(deployable(point))
        for point in (MapPoint(.5,.5),MapPoint(.001,.5),MapPoint(float('nan'),.5)):
            self.assertFalse(deployable(point))

    def test_all_four_sides_required_not_a_hidden_corner_guess(self):
        corners=self.projection().corners
        segments=[{'points':[[a[0]/1000,a[1]/600],[b[0]/1000,b[1]/600]],'support':1}
                  for a,b in zip(corners,corners[1:]+corners[:1])]
        self.assertIsNotNone(fit_projection(segments,1000,600))
        for index in range(4):self.assertIsNone(fit_projection(segments[:index]+segments[index+1:],1000,600))

    def test_one_short_observed_side_needs_three_strong_sides(self):
        corners=self.projection().corners
        def segments(fractions):
            values=[]
            for (a,b),fraction in zip(zip(corners,corners[1:]+corners[:1]),fractions):
                a,b=np.array(a),np.array(b)
                start=a+(b-a)*(1-fraction)/2
                end=a+(b-a)*(1+fraction)/2
                values.append({'points':[(start/[1000,600]).tolist(),(end/[1000,600]).tolist()],'support':1})
            return values
        self.assertIsNotNone(fit_projection(segments([1,1,1,.12]),1000,600))
        for fractions in ([1,1,.12,.12],[.4,.4,.4,.12],[1,1,1,.08]):
            self.assertIsNone(fit_projection(segments(fractions),1000,600))

    def test_weak_side_hints_only_guide_observation_and_do_not_approve_a_map(self):
        from coc_bot.attack.survey import survey_pan
        corners=self.projection().corners
        segments=[]
        for a,b in zip(corners,corners[1:]+corners[:1]):
            a,b=np.array(a),np.array(b)
            segments.append({'points':[(a/[1000,600]).tolist(),((a+(b-a)*.2)/[1000,600]).tolist()]})
        evidence={}
        self.assertIsNone(fit_projection(segments,1000,600,survey_evidence=evidence))
        self.assertEqual(len(evidence['weak_sides']),4)
        pan=survey_pan(evidence,np.eye(3),1000,600)
        self.assertIsNotNone(pan)
        self.assertLessEqual(abs(pan[0]),.22);self.assertLessEqual(abs(pan[1]),.20)
        # A missing side doesn't become an observation hint from an older map.
        self.assertIsNone(fit_projection(segments[:-1],1000,600,survey_evidence=evidence))
        self.assertEqual(evidence,{})
        self.assertIsNone(survey_pan(evidence,np.eye(3),1000,600))

    def test_geometry_keeps_troops_outside_and_spells_inside(self):
        army=(ArmyEntry('electro_dragon','troop',2,True),)
        plan=AttackPlan(army,(PlanStep('deploy_line','electro_dragon',2,(MapPoint(.055,.2),MapPoint(.055,.8))),))
        validate_geometry(plan,self.projection())
        with self.assertRaises(ValueError):
            validate_geometry(replace(plan,steps=(PlanStep('deploy_point','electro_dragon',1,(MapPoint(.5,.5),)),)),self.projection())
        with self.assertRaises(ValueError):Projection(((0,0),(2,2),(3,1),(1,2))).validate()

    def test_narrow_fragment_envelope_is_not_a_complete_village(self):
        with self.assertRaises(ValueError):
            Projection(((1497,255),(1588,323),(898,841),(808,773))).validate()
        with self.assertRaises(ValueError):
            Projection(((1013,40),(1545,440),(893,930),(360,529))).validate()


class BattleEvidenceTests(TestCase):
    def test_wounded_hero_health_is_allowed_only_for_ability_check(self):
        card=ArmyCard('hero',(100,834,130,203),'king','hero',1)
        for color in ((0,0,220),(0,180,220),(0,220,0)):
            frame=np.zeros((1048,1853,3),np.uint8)
            cv2.rectangle(frame,(110,838),(143,850),color,-1)
            cv2.line(frame,(143,850),(175,850),color,1)
            self.assertFalse(hero_health_visible(frame,card))
            self.assertTrue(hero_health_visible(frame,card,allow_low=True))
            frame[:]=(140,170,140)
            cv2.rectangle(frame,(110,838),(143,850),color,-1)
            self.assertFalse(hero_health_visible(frame,card,allow_low=True))
        frame[:]=0
        # Colored portrait/equipment fragments further down are not health.
        cv2.rectangle(frame,(110,870),(143,882),(0,0,220),-1)
        self.assertFalse(hero_health_visible(frame,card,allow_low=True))

    def test_health_bar_rejects_cyan_background_and_one_pixel_highlight(self):
        card=ArmyCard('siege',(100,800,140,200),'flinger','siege',1)
        frame=np.zeros((1048,1853,3),np.uint8)
        cv2.rectangle(frame,(115,810),(220,821),(180,180,0),-1)
        self.assertFalse(hero_health_visible(frame,card))
        frame[:]=0;cv2.line(frame,(115,810),(220,810),(0,220,0),1)
        self.assertFalse(hero_health_visible(frame,card))
        cv2.rectangle(frame,(115,810),(220,821),(0,220,0),-1)
        self.assertTrue(hero_health_visible(frame,card))
        frame[:]=0;cv2.rectangle(frame,(120,800),(239,817),(0,180,0),-1)
        self.assertFalse(hero_health_visible(frame,card))  # Scenery above the card touches its crop edge.

    def test_rising_hero_health_bar_requires_dark_enclosure(self):
        card=ArmyCard('hero',(100,834,130,203),'hero_4','hero',1)
        frame=np.zeros((1048,1853,3),np.uint8)
        cv2.rectangle(frame,(110,830),(215,842),(0,220,0),-1)
        self.assertTrue(hero_health_visible(frame,card))
        # Same green strip over scenery, without the health widget's border.
        frame[:]=(140,170,140)
        cv2.rectangle(frame,(110,830),(215,842),(0,220,0),-1)
        self.assertFalse(hero_health_visible(frame,card))

    def test_selected_hero_equipment_does_not_merge_into_card_bounds(self):
        frame=np.full((1048,1853,3),140,np.uint8)
        cv2.rectangle(frame,(440,830),(576,1038),(20,20,20),-1)
        cv2.rectangle(frame,(444,860),(572,1034),(180,40,100),-1)
        cv2.rectangle(frame,(442,858),(574,1036),(250,250,250),3)
        self.assertTrue(any(abs(x-440)<8 and abs(y-858)<8 and h<195
                            for x,y,w,h in card_boxes(frame,'battle')))

    def test_deployed_siege_card_can_rise_above_army_row(self):
        frame=np.full((1048,1853,3),140,np.uint8)
        cv2.rectangle(frame,(296,831),(428,1043),(20,20,20),3)
        cv2.rectangle(frame,(300,835),(424,1039),(200,140,40),-1)
        self.assertTrue(any(abs(x-296)<5 and y<840 and h>200
                            for x,y,w,h in card_boxes(frame,'battle')))

    def test_tooltip_alternative_needs_prior_battle_and_both_fresh_labels(self):
        from coc_bot.vision.battle_menu import active_battle_ready
        frame=np.zeros((600,1000,3),np.uint8)
        original=Mock(return_value=False); alternative=Mock(return_value=True)
        gate=BattleFrameGate(original,alternative)
        self.assertFalse(gate.accept(frame));alternative.assert_not_called()
        original.return_value=True;self.assertTrue(gate.accept(frame))
        original.return_value=False;self.assertTrue(gate.accept(frame));alternative.assert_called_once()
        for timer in ('battleendsin','battbleendsin','battleefidsin'):
            with patch('coc_bot.vision.battle_menu._white_label',side_effect=[timer,'overalldamage']):
                self.assertTrue(active_battle_ready(frame))
        for labels in (['battleendsin',''], ['returnhome','overalldamage']):
            with patch('coc_bot.vision.battle_menu._white_label',side_effect=labels):
                self.assertFalse(active_battle_ready(frame))

    def test_broken_outline_is_supplemented_without_duplicating_other_cards(self):
        frame=np.full((1000,1800,3),140,np.uint8)
        # Two complete dark outlines, then two purple cards joined at the top.
        for x in (150,300):
            cv2.rectangle(frame,(x,830),(x+125,990),(20,20,20),4)
            cv2.rectangle(frame,(x+4,834),(x+121,986),(200,40,100),-1)
        for x in (450,588):
            cv2.rectangle(frame,(x,830),(x+125,990),(200,40,100),-1)
        cv2.rectangle(frame,(570,830),(594,840),(200,40,100),-1)
        boxes=card_boxes(frame,'battle')
        self.assertEqual(len(boxes),4)
        self.assertTrue(any(440<x<460 for x,y,w,h in boxes))

    def test_tooltip_can_reuse_verified_timer_but_still_needs_damage(self):
        from coc_bot.vision.battle_menu import active_battle_ready
        frame=np.zeros((600,1000,3),np.uint8)
        cv2.putText(frame,'END',(20,450),cv2.FONT_HERSHEY_SIMPLEX,.6,(255,255,255),2)
        cv2.putText(frame,'BATTLE',(450,24),cv2.FONT_HERSHEY_SIMPLEX,.6,(255,255,255),2)
        recognize=Mock(return_value=True)
        gate=BattleFrameGate(recognize,active_battle_ready)
        self.assertTrue(gate.accept(frame))
        tooltip=frame.copy();tooltip[420:470,:150]=0
        recognize.return_value=False
        with patch('coc_bot.vision.battle_menu._white_label',return_value=''):
            self.assertFalse(gate.accept(tooltip))
        with patch('coc_bot.vision.battle_menu._white_label',return_value='overalldamage') as ocr:
            self.assertTrue(gate.accept(tooltip))
            ocr.assert_called_once() # unchanged timer, fresh damage
            self.assertFalse(gate.accept(tooltip//2))
            self.assertFalse(gate.accept(np.zeros_like(frame)))

    def test_lettering_reuse_requires_prior_ocr_and_rejects_dimmed_overlay(self):
        frame=np.zeros((600,1000,3),np.uint8)
        cv2.putText(frame,'END',(20,450),cv2.FONT_HERSHEY_SIMPLEX,.6,(255,255,255),2)
        cv2.putText(frame,'BATTLE',(435,24),cv2.FONT_HERSHEY_SIMPLEX,.6,(255,255,255),2)
        recognize=Mock(return_value=True);gate=BattleFrameGate(recognize)
        self.assertTrue(gate.accept(frame));recognize.return_value=False
        self.assertTrue(gate.accept(frame.copy()));self.assertEqual(recognize.call_count,1)
        self.assertFalse(gate.accept(frame//2));self.assertFalse(gate.accept(np.zeros_like(frame)))

    def test_block_zero_is_distinct_from_six_nine_eight(self):
        zero=np.full((25,23),255,np.uint8);zero[7:19,8:14]=0
        self.assertTrue(zero_glyph(zero))
        for start,end in ((3,10),(15,22)):
            other=np.full_like(zero,255);other[start:end,8:14]=0
            self.assertFalse(zero_glyph(other))
        eight=zero.copy();eight[12:15,8:14]=255
        self.assertFalse(zero_glyph(eight))

    def test_empty_card_needs_same_current_artwork_and_zero_not_old_position(self):
        frame=np.zeros((600,1000,3),np.uint8)
        card=ArmyCard('card-0',(100,500,70,95),'electro_dragon','troop',1)
        catalog=Mock();catalog.identify_reference.return_value=('electro_dragon','troop',1.,1.)
        with patch('coc_bot.attack.army.depleted_card',return_value=True), \
                patch('coc_bot.attack.army.read_badge',return_value=0):
            self.assertEqual(resolve_just_depleted(frame,catalog,card).quantity,0)
            catalog.identify_reference.return_value=('rage_spell','spell',1.,1.)
            with self.assertRaises(ValueError):resolve_just_depleted(frame,catalog,card)
        catalog.identify_reference.return_value=('electro_dragon','troop',1.,1.)
        with patch('coc_bot.attack.army.depleted_card',return_value=True), \
                patch('coc_bot.attack.army.read_badge',return_value=None):
            with self.assertRaises(ValueError):resolve_just_depleted(frame,catalog,card)


class ExecutorTests(TestCase):
    def executor(self, root, quantity=2):
        session=Mock();session.config.data_dir=Path(root);session.client.stop_check=lambda:False
        session.config.adb_device='test'
        frame=np.zeros((600,1000,3),np.uint8)
        session.capture.screenshot.return_value=frame
        session.attack_nav.battlefield_ready.return_value=True
        plan=AttackPlan((ArmyEntry('electro_dragon','troop',quantity,True),),
                        (PlanStep('deploy_point','electro_dragon',quantity,(MapPoint(.055,.5),)),))
        projection=Projection(((500,50),(900,300),(500,550),(100,300)))
        exe=VerifiedExecutor(session,plan,projection,frame,Mock())
        exe.position=Mock(return_value=(frame,(250,300)))
        exe.target=Mock(return_value=(250,300))
        exe.frame=Mock(return_value=frame)
        return exe,session,frame

    def card(self, q):return ArmyCard('card-0',(100,500,70,95),'electro_dragon','troop',q)

    def test_each_deployment_requires_observed_count_decrease(self):
        with TemporaryDirectory() as root:
            exe,session,frame=self.executor(root)
            exe.resolve=Mock(side_effect=[self.card(2),self.card(2),self.card(1),self.card(1),self.card(0)])
            with patch('coc_bot.attack.executor.selected_card',return_value=True):result=exe.run()
            self.assertTrue(result.success);self.assertEqual(result.verified_taps,2)
            self.assertEqual(session.input.tap.call_count,2)
            self.assertIsNotNone(result.first_deploy_at)

    def test_no_change_never_replays_uncertain_map_tap(self):
        with TemporaryDirectory() as root:
            exe,session,_=self.executor(root);exe.resolve=Mock(return_value=self.card(2))
            with patch('coc_bot.attack.executor.selected_card',return_value=True):result=exe.run()
            self.assertFalse(result.success);self.assertTrue(result.uncertain_tap)
            session.input.tap.assert_called_once()

    def test_deployed_siege_uses_health_bar_not_an_empty_card(self):
        with TemporaryDirectory() as root:
            exe,session,frame=self.executor(root,quantity=1)
            exe.plan=AttackPlan((ArmyEntry('flinger','siege',1,True),),
                (PlanStep('deploy_point','flinger',1,(MapPoint(.055,.5),)),))
            card=ArmyCard('card-1',(100,500,70,95),'flinger','siege',1)
            exe.resolve=Mock(return_value=card)
            with patch('coc_bot.attack.executor.selected_card',return_value=True), \
                    patch('coc_bot.attack.executor.hero_health_visible',side_effect=[False,False,True]):
                result=exe.run()
            self.assertTrue(result.success);self.assertEqual(result.verified_taps,1)
            session.input.tap.assert_called_once()

    def test_rising_card_gets_second_observation_without_repeating_tap(self):
        with TemporaryDirectory() as root:
            exe,session,frame=self.executor(root,quantity=1)
            exe.resolve=Mock(side_effect=[self.card(1),self.card(1),ValueError('moving'),self.card(0)])
            with patch('coc_bot.attack.executor.selected_card',return_value=True), \
                    patch('coc_bot.attack.executor.resolve_just_depleted',side_effect=ValueError('moving')):
                result=exe.run()
            self.assertTrue(result.success);session.input.tap.assert_called_once()

    def test_hidden_army_card_is_searched_only_in_army_bar(self):
        with TemporaryDirectory() as root:
            exe,session,frame=self.executor(root)
            exe.resolve=Mock(side_effect=[ValueError('Unit is hidden or ambiguous'),self.card(2)])
            _,card=exe.find(frame,'electro_dragon')
            self.assertEqual(card.quantity,2)
            args=session.input.swipe.call_args.args
            self.assertEqual(args[1],round(frame.shape[0]*.91))
            self.assertEqual(args[3],round(frame.shape[0]*.91))

    def test_real_thin_selection_outline_not_bright_portrait(self):
        frame=np.zeros((600,1000,3),np.uint8);card=self.card(2)
        x,y,w,h=card.box
        cv2.rectangle(frame,(x,y),(x+w-1,y+h-1),(240,240,240),2)
        self.assertTrue(selected_card(frame,card))
        frame[:]=0
        cv2.rectangle(frame,(x,y),(x+w-1,y+h-9),(240,240,240),2)
        self.assertTrue(selected_card(frame,card))
        frame[:]=0;cv2.rectangle(frame,(x+10,y+10),(x+w-10,y+h-10),(255,255,255),-1)
        self.assertFalse(selected_card(frame,card))

    def test_selection_border_below_equipment_still_needs_both_sides(self):
        frame=np.zeros((600,1000,3),np.uint8)
        card=ArmyCard('hero',(100,470,70,125),'queen','hero',1)
        cv2.rectangle(frame,(100,500),(169,594),(250,250,250),2)
        self.assertTrue(selected_card(frame,card))
        frame[505:585,100:104]=0
        self.assertFalse(selected_card(frame,card))

    def test_failed_selection_cannot_send_map_tap(self):
        with TemporaryDirectory() as root:
            exe,session,_=self.executor(root);exe.resolve=Mock(return_value=self.card(2))
            with patch('coc_bot.attack.executor.selected_card',return_value=False):result=exe.run()
            self.assertFalse(result.success);self.assertFalse(result.uncertain_tap)
            self.assertEqual(session.input.tap.call_count,2) # bounded army-card taps only
            self.assertTrue(all(c.args==(135,547) for c in session.input.tap.call_args_list))

    def test_delayed_selection_gets_another_observation_without_another_click(self):
        with TemporaryDirectory() as root:
            exe,session,frame=self.executor(root)
            exe.find=Mock(return_value=(frame,self.card(2)))
            exe.resolve=Mock(side_effect=[ValueError('card moving'),self.card(2)])
            with patch('coc_bot.attack.executor.selected_card',side_effect=[False,True]):
                exe.select(frame,'electro_dragon')
            session.input.tap.assert_called_once_with(135,547,jitter=0)

    def test_missed_card_click_retries_at_fresh_position_without_deploying(self):
        with TemporaryDirectory() as root:
            exe,session,frame=self.executor(root)
            old=ArmyCard('card-2',(100,470,70,125),'warden','hero',1)
            moved=replace(old,box=(230,470,70,125))
            exe.find=Mock(return_value=(frame,old));exe.resolve=Mock(return_value=moved)
            with patch('coc_bot.attack.executor.selected_card',side_effect=[False,False,False,False,True]):
                exe.select(frame,'warden')
            self.assertEqual([c.args for c in session.input.tap.call_args_list],[(135,532),(265,532)])

    def test_selection_retry_never_activates_an_already_deployed_hero(self):
        with TemporaryDirectory() as root:
            exe,session,frame=self.executor(root)
            hero=ArmyCard('card-2',(100,470,70,125),'warden','hero',1)
            exe.find=Mock(return_value=(frame,hero));exe.resolve=Mock(return_value=hero)
            with patch('coc_bot.attack.executor.selected_card',return_value=False), \
                    patch('coc_bot.attack.executor.hero_health_visible',side_effect=[False,True]):
                with self.assertRaisesRegex(ValueError,'already deployed'):exe.select(frame,'warden')
            session.input.tap.assert_called_once()

    def test_stop_during_selection_observation_prevents_retry(self):
        with TemporaryDirectory() as root:
            exe,session,frame=self.executor(root)
            exe.find=Mock(return_value=(frame,self.card(2)))
            session._sleep.side_effect=AdbStopped('Stopped')
            with patch('coc_bot.attack.executor.selected_card',return_value=False):
                with self.assertRaises(AdbStopped):exe.select(frame,'electro_dragon')
            session.input.tap.assert_called_once()

    def test_numpy_selection_evidence_is_saved_as_plain_json_boolean(self):
        with TemporaryDirectory() as root:
            exe,session,frame=self.executor(root)
            exe.find=Mock(return_value=(frame,self.card(2)));exe.resolve=Mock(return_value=self.card(2))
            with patch('coc_bot.attack.executor.selected_card',side_effect=[np.bool_(False),np.bool_(True)]):
                exe.select(frame,'electro_dragon')
            rows=[json.loads(line) for line in exe.path.read_text().splitlines()]
            self.assertIs(rows[-1]['confirmed'],True)

    def test_already_deployed_hero_blocks_preflight_before_any_map_tap(self):
        with TemporaryDirectory() as root:
            exe,session,_=self.executor(root)
            exe.plan=AttackPlan((ArmyEntry('king','hero',1,True),),
                               (PlanStep('deploy_point','king',1,(MapPoint(.055,.5),)),))
            exe.resolve=Mock(return_value=ArmyCard('card-1',(100,500,70,95),'king','hero',1))
            with patch('coc_bot.attack.executor.hero_health_visible',return_value=True):
                result=exe.run()
            self.assertFalse(result.success)
            session.input.tap.assert_not_called()

    def test_stop_after_sent_tap_prevents_next_tap(self):
        with TemporaryDirectory() as root:
            exe,session,_=self.executor(root);exe.resolve=Mock(return_value=self.card(2))
            session.input.tap.side_effect=AdbStopped('Stopped after send')
            with patch('coc_bot.attack.executor.selected_card',return_value=True):
                with self.assertRaises(AdbStopped):exe.run()
            self.assertTrue(exe.result.uncertain_tap);session.input.tap.assert_called_once()
            self.assertIsNotNone(exe.result.first_attempt_at)

    def test_unavailable_ability_does_not_block_the_next_verified_hero(self):
        with TemporaryDirectory() as root:
            exe,session,frame=self.executor(root)
            exe.deployed_heroes={'king','queen'}
            hero=lambda name:ArmyCard(name,(100,500,70,95),name,'hero',1)
            exe.find=Mock(side_effect=[(frame,hero('king')),(frame,hero('queen'))])
            with patch('coc_bot.attack.executor.hero_health_visible',side_effect=[False,True]):
                exe.ability('king');exe.ability('queen')
            session.input.tap.assert_called_once()
            self.assertEqual(exe.skipped_abilities,{'king'})
            self.assertEqual(exe.abilities,{'queen'})
            with self.assertRaises(ValueError):exe.ability('king')
            with self.assertRaises(ValueError):exe.ability('undeployed')

    def test_stale_camera_and_screen_change_are_blocked(self):
        with TemporaryDirectory() as root:
            exe,session,_=self.executor(root);del exe.frame
            session.attack_nav.battlefield_ready.return_value=False
            with self.assertRaises(ValueError):exe.frame()
            session.attack_nav.battlefield_ready.return_value=True
            with patch('coc_bot.attack.executor.compare_camera',return_value={'verified':False}):
                with self.assertRaises(ValueError):exe.frame()

    def test_timed_overlay_waits_without_inputs_and_rechecks_camera(self):
        with TemporaryDirectory() as root:
            exe,session,frame=self.executor(root);del exe.frame
            exe.battle_gate.accept=Mock(side_effect=[False,False,True])
            with patch('coc_bot.attack.executor.compare_camera',return_value={
                    'verified':True,'transform':[[1,0,0],[0,1,0]]}):
                np.testing.assert_array_equal(exe.frame(),frame)
            self.assertEqual(session._sleep.call_count,2)
            session.input.tap.assert_not_called()
            session.input.swipe.assert_not_called()

    def test_stop_while_waiting_for_overlay_never_sends_inputs(self):
        with TemporaryDirectory() as root:
            exe,session,_=self.executor(root);del exe.frame
            exe.battle_gate.accept=Mock(return_value=False)
            session._sleep.side_effect=AdbStopped('Stopped')
            with self.assertRaises(AdbStopped):exe.frame()
            session.input.tap.assert_not_called()
            session.input.swipe.assert_not_called()


class TemplateTests(TestCase):
    def test_renamed_unit_does_not_compete_with_its_old_portrait_name(self):
        with TemporaryDirectory() as root:
            config=SimpleNamespace(data_dir=Path(root),adb_device='test-device')
            units=Path(root)/'attack-planner/units';units.mkdir(parents=True)
            image=np.random.default_rng(42).integers(0,255,(180,130,3),dtype=np.uint8)
            for name in ('old_name','reviewed_hero'):
                cv2.imwrite(str(units/(name+'.png')),image)
                (units/(name+'.json')).write_text(json.dumps({'device':'test-device','unit_id':name,'kind':'hero'}))
            plan=AttackPlan((ArmyEntry('reviewed_hero','hero',1,True),),
                           (PlanStep('deploy_point','reviewed_hero',1,(MapPoint(.055,.5),)),))
            (units.parent/'routine.json').write_text(json.dumps({'device':'test-device','plan':plan.to_dict()}))
            self.assertEqual(learned_catalog(config).identify_reference(image)[0],'reviewed_hero')
            self.assertEqual(learned_catalog(config,unit_ids={'old_name'}).identify_reference(image)[0],'old_name')
            self.assertTrue((units/'old_name.png').exists())

    def test_saved_routine_is_separate_and_cannot_be_replayed(self):
        with TemporaryDirectory() as root:
            config=SimpleNamespace(data_dir=Path(root),adb_device='test-device')
            folder=Path(root)/'debug/attack-observations'/('c'*32);folder.mkdir(parents=True)
            card=ArmyCard('card-0',(10,10,100,100),'electro_dragon','troop',11,confirmed=True)
            report={'observation_id':'c'*32,'page':'battle','device':'test-device','survey':{'captured_at':time.time()},
                    'cards':[card.to_dict()],'executed':True}
            write_report(folder,report);cv2.imwrite(str(folder/'frame.png'),np.zeros((600,1000,3),np.uint8))
            plan=AttackPlan((ArmyEntry('electro_dragon','troop',11,True),),
                           (PlanStep('deploy_point','electro_dragon',11,(MapPoint(.055,.5),)),))
            corners=[[500,50],[900,300],[500,550],[100,300]]
            saved=save_preview(config,'c'*32,report['revision'],plan.to_dict(),corners,save_routine=True)
            _,loaded=load_template(config);self.assertEqual(loaded,plan)
            self.assertEqual(json.loads(json.dumps(plan.to_dict())),plan.to_dict())
            session=Mock();session.config=config
            with self.assertRaisesRegex(ValueError,'already been used'):execute_preview(session,'c'*32,saved['revision'])
            self.assertFalse((Path(root)/'calibrated.yaml').exists())
            with self.assertRaisesRegex(ValueError,'changed'):save_preview(config,'c'*32,report['revision'],plan.to_dict(),corners)

            path=Path(root)/'attack-planner/routine.json'
            value=json.loads(path.read_text());value['live_verified']=True
            path.write_text(json.dumps(value))
            saved=save_preview(config,'c'*32,saved['revision'],plan.to_dict(),corners,save_routine=True)
            self.assertTrue(load_template(config,require_live=True)[0]['live_verified'])
            changed=AttackPlan(plan.army,(PlanStep('deploy_point','electro_dragon',10,(MapPoint(.055,.5),)),))
            save_preview(config,'c'*32,saved['revision'],changed.to_dict(),corners,save_routine=True)
            with self.assertRaisesRegex(ValueError,'supervised attack'):load_template(config,require_live=True)


class CameraRecoveryTests(TestCase):
    def test_ignored_small_zoom_gets_one_bounded_escape_then_fresh_correction(self):
        with TemporaryDirectory() as root:
            folder=Path(root)/'attack-planner';folder.mkdir()
            pending=folder/'camera-pending.json';pending.write_text(json.dumps({'device':'test'}))
            frame=np.zeros((600,1000,3),np.uint8);cv2.imwrite(str(folder/'camera-before.png'),frame)
            session=Mock();session.config.data_dir=Path(root);session.config.adb_device='test'
            session.client.stop_check=lambda:False;session.capture.screenshot.return_value=frame
            with patch('coc_bot.vision.battle_menu.home_build_control_visible',return_value=True), \
                    patch('coc_bot.attack.planned_farmer.compare_camera',side_effect=
                          [{'verified':True,'scale':n} for n in (1.043,1.043,.88,1.01)]), \
                    patch('coc_bot.adb.multitouch.Multitouch') as touch:
                self.assertTrue(restore_camera(session))
            calls=touch.return_value.__enter__.return_value.pinch.call_args_list
            self.assertEqual(len(calls),3)
            self.assertAlmostEqual(calls[1].kwargs['end_span']/calls[1].kwargs['start_span'],1.2)
            self.assertAlmostEqual(calls[2].kwargs['end_span']/calls[2].kwargs['start_span'],1/.88)
            self.assertFalse(pending.exists())

    def test_last_allowed_gesture_gets_one_fresh_verification_without_another_input(self):
        with TemporaryDirectory() as root:
            folder=Path(root)/'attack-planner';folder.mkdir()
            pending=folder/'camera-pending.json';pending.write_text(json.dumps({'device':'test'}))
            frame=np.zeros((600,1000,3),np.uint8);cv2.imwrite(str(folder/'camera-before.png'),frame)
            session=Mock();session.config.data_dir=Path(root);session.config.adb_device='test'
            session.client.stop_check=lambda:False;session.capture.screenshot.return_value=frame
            with patch('coc_bot.vision.battle_menu.home_build_control_visible',return_value=True), \
                    patch('coc_bot.attack.planned_farmer.compare_camera',side_effect=
                          [{'verified':True,'scale':1.1}]*5+[{'verified':True,'scale':1.01}]), \
                    patch('coc_bot.adb.multitouch.Multitouch') as touch:
                self.assertTrue(restore_camera(session))
            self.assertEqual(touch.return_value.__enter__.return_value.pinch.call_count,5)
            self.assertEqual(session.capture.screenshot.call_count,6)
            self.assertFalse(pending.exists())

    def test_home_overview_requires_measured_home_scale_not_opponent_hint(self):
        with TemporaryDirectory() as root:
            folder=Path(root)/'attack-planner';folder.mkdir()
            pending=folder/'camera-pending.json'
            pending.write_text(json.dumps({'device':'test','measured_scale':.3}))
            frame=np.zeros((600,1000,3),np.uint8)
            cv2.imwrite(str(folder/'camera-before.png'),frame)
            session=Mock();session.config.data_dir=Path(root);session.config.adb_device='test'
            session.client.stop_check=lambda:False;session.capture.screenshot.return_value=frame
            with patch('coc_bot.vision.battle_menu.home_build_control_visible',return_value=True), \
                    patch('coc_bot.attack.planned_farmer.compare_camera',side_effect=[
                        {'verified':False},{'verified':False},{'verified':True,'scale':1.01}]), \
                    patch('coc_bot.attack.planned_farmer.compare_zoom',return_value={'verified_zoom':False}), \
                    patch('coc_bot.attack.planned_farmer.compare_home_zoom',side_effect=[
                        {'verified_zoom':False},{'verified_zoom':True,'scale':.5}]), \
                    patch('coc_bot.adb.multitouch.Multitouch') as touch:
                self.assertTrue(restore_camera(session))
            calls=touch.return_value.__enter__.return_value.pinch.call_args_list
            self.assertEqual(len(calls),2)
            self.assertEqual(calls[0].kwargs,{}) # one wider overview, then observe
            self.assertAlmostEqual(calls[1].kwargs['end_span']/calls[1].kwargs['start_span'],2.)
            self.assertFalse(pending.exists())

    def test_uncertain_home_translation_can_only_probe_then_requires_fresh_verified_image(self):
        with TemporaryDirectory() as root:
            folder=Path(root)/'attack-planner';folder.mkdir()
            pending=folder/'camera-pending.json'
            pending.write_text(json.dumps({'device':'test','measured_scale':.32}))
            frame=np.zeros((600,1000,3),np.uint8)
            cv2.imwrite(str(folder/'camera-before.png'),frame)
            session=Mock();session.config.data_dir=Path(root);session.config.adb_device='test'
            session.client.stop_check=lambda:False;session.capture.screenshot.return_value=frame
            hint={'verified':False,'scale':1.02,'inliers':40,'rotation_degrees':0.,
                  'transform':[[1.02,0,-450],[0,1.02,100]]}
            with patch('coc_bot.vision.battle_menu.home_build_control_visible',return_value=True), \
                    patch('coc_bot.attack.planned_farmer.compare_camera',side_effect=[hint,{'verified':True,'scale':1.02}]), \
                    patch('coc_bot.attack.planned_farmer.compare_zoom',return_value={'verified_zoom':False}), \
                    patch('coc_bot.adb.multitouch.Multitouch') as touch:
                self.assertTrue(restore_camera(session))
            session.input.swipe.assert_called_once()
            touch.assert_not_called()
            self.assertFalse(pending.exists())

            pending.write_text(json.dumps({'device':'test','measured_scale':.32}))
            session.input.reset_mock()
            with patch('coc_bot.vision.battle_menu.home_build_control_visible',return_value=True), \
                    patch('coc_bot.attack.planned_farmer.compare_camera',return_value=hint), \
                    patch('coc_bot.attack.planned_farmer.compare_zoom',return_value={'verified_zoom':False}):
                with self.assertRaisesRegex(ValueError,'Could not match'):restore_camera(session)
            self.assertEqual(session.input.swipe.call_count,2)
            self.assertTrue(pending.exists())

    def test_measured_hint_cannot_clear_pending_without_home_image_confirmation(self):
        with TemporaryDirectory() as root:
            folder=Path(root)/'attack-planner';folder.mkdir()
            pending=folder/'camera-pending.json'
            pending.write_text(json.dumps({'device':'test','measured_scale':.4}))
            frame=np.zeros((600,1000,3),np.uint8)
            cv2.imwrite(str(folder/'camera-before.png'),frame)
            session=Mock();session.config.data_dir=Path(root);session.config.adb_device='test'
            session.client.stop_check=lambda:False;session.capture.screenshot.return_value=frame
            with patch('coc_bot.vision.battle_menu.home_build_control_visible',return_value=True), \
                    patch('coc_bot.attack.planned_farmer.compare_camera',return_value={'verified':False}), \
                    patch('coc_bot.attack.planned_farmer.compare_zoom',return_value={'verified_zoom':False}), \
                    patch('coc_bot.adb.multitouch.Multitouch') as touch:
                with self.assertRaisesRegex(ValueError,'Could not match'):restore_camera(session)
                touch.return_value.__enter__.return_value.pinch.assert_called_once()
            self.assertTrue(pending.exists())
