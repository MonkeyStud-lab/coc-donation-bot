from dataclasses import replace
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
import time

import cv2
import numpy as np

from coc_bot.adb.client import AdbStopped
from coc_bot.attack.army import ArmyCard, UnitCatalog, agree_cards, correct_cards, read_badge, read_army, card_boxes
from coc_bot.attack.mapping import OpponentMap, observe_boundary, map_is_current
from coc_bot.control.attack_observation import inspect_attack, review_army, observation_asset, write_report, page_for


class ArmyTests(TestCase):
    def badge(self,count=2):
        cell=np.full((150,150,3),(180,90,40),np.uint8)
        cv2.line(cell,(14,18),(27,32),(255,255,255),5)
        cv2.line(cell,(27,18),(14,32),(255,255,255),5)
        for i in range(count):
            cv2.rectangle(cell,(33+i*11,14),(39+i*11,33),(255,255,255),-1)
        return cell

    def test_two_separate_ones_stay_eleven(self):
        with patch('coc_bot.attack.army.shutil.which',return_value='tesseract'):
            self.assertEqual(read_badge(self.badge()),11)
            self.assertEqual(read_badge(self.badge(1)),1)

    def test_bottom_level_cannot_become_quantity(self):
        frame=np.zeros((180,150,3),np.uint8)
        cv2.putText(frame,'48',(3,170),cv2.FONT_HERSHEY_SIMPLEX,.8,(255,255,255),2)
        with patch('coc_bot.attack.army.shutil.which',return_value='tesseract'):
            self.assertIsNone(read_badge(frame))

    def test_card_outlines_survive_a_blue_scenery_background(self):
        for color in ((20,30,20),(190,110,60)):
            frame=np.full((600,1000,3),color,np.uint8)
            for index in range(7):
                x=70+index*85
                cv2.rectangle(frame,(x,498),(x+70,592),(5,5,5),4)
                cv2.rectangle(frame,(x+3,501),(x+67,589),(180,90,70),-1)
            self.assertEqual(len(card_boxes(frame,'battle')),7)

    def test_inconsistent_or_moved_cards_are_not_stable(self):
        a=ArmyCard('card-0',(10,20,100,150),'electro_dragon','troop',11)
        self.assertTrue(agree_cards([a],[a])[0].stable)
        for b in (replace(a,quantity=10),replace(a,unit_id=None),replace(a,box=(30,20,100,150))):
            self.assertFalse(agree_cards([a],[b])[0].stable)
        self.assertFalse(agree_cards([a],[a])[0].confirmed)

    def test_corrections_are_explicit_and_do_not_change_other_cards(self):
        a=ArmyCard('card-0',(1,1,10,10),None,'hero',1)
        b=replace(a,slot='card-1')
        values=[{'slot':'card-0','unit_id':'barbarian_king','kind':'hero','quantity':1,'confirmed':True}]
        changed=correct_cards([a,b],values)
        self.assertTrue(changed[0].confirmed)
        self.assertIsNone(a.unit_id)
        self.assertEqual(changed[1],b)
        for field,value in [('quantity',True),('quantity',2),('unit_id','../../wrong'),('confirmed',1)]:
            bad=[dict(values[0],**{field:value})]
            with self.assertRaises(ValueError):correct_cards([a,b],bad)
        with self.assertRaises(ValueError):correct_cards([a],values+values)

    def test_cancelled_catalog_does_not_continue_matching(self):
        with TemporaryDirectory() as folder:
            catalog=UnitCatalog(Path(folder))
            catalog.templates=[('unit','troop',np.ones((30,30,3),np.uint8),np.ones((30,30),np.uint8)*255)]
            with self.assertRaises(AdbStopped):catalog.identify(np.zeros((60,60,3),np.uint8),stop_check=lambda:True)

    def test_unknown_hero_is_not_assigned_from_card_order(self):
        with patch('coc_bot.attack.army.card_boxes',return_value=[(10,100,100,600)]):
            catalog=Mock()
            cards=read_army(np.zeros((1000,1800,3),np.uint8),'army_confirmation',catalog)
            self.assertEqual(cards[0].kind,'hero')
            self.assertIsNone(cards[0].unit_id)
            self.assertFalse(cards[0].confirmed)
            catalog.identify.assert_not_called()

    def test_references_require_stability_or_human_confirmation(self):
        with TemporaryDirectory() as folder:
            catalog=UnitCatalog(Path(folder))
            image=np.random.default_rng(4).integers(0,255,(150,150,3),dtype=np.uint8)
            card=ArmyCard('card-0',(0,0,150,150),'test','troop',1)
            catalog.add_references(image,[card]);self.assertFalse(catalog.references)
            catalog.add_references(image,[replace(card,stable=True)])
            self.assertTrue(catalog.references)
            match=catalog.identify_reference(image)
            self.assertIsNotNone(match)
            self.assertEqual(match[0],'test')

    def test_hero_identity_survives_a_lower_portrait_ability_overlay(self):
        with TemporaryDirectory() as folder:
            catalog=UnitCatalog(Path(folder))
            image=np.full((200,160,3),60,np.uint8)
            rng=np.random.default_rng(91)
            for _ in range(100):
                x,y=rng.integers([25,18],[135,71])
                cv2.circle(image,(int(x),int(y)),int(rng.integers(1,4)),
                           tuple(int(n) for n in rng.integers(0,255,3)),-1)
            card=ArmyCard('card-0',(0,0,160,200),'test_hero','hero',1,confirmed=True)
            catalog.add_references(image,[card])
            deployed=image.copy();deployed[75:]=(120,40,220)
            match=catalog.identify_reference(deployed)
            self.assertIsNotNone(match)
            self.assertEqual(match[0],'test_hero')
            unrelated=deployed.copy();unrelated[:75]=60
            self.assertIsNone(catalog.identify_reference(unrelated))

    def test_artwork_localization_tracks_current_position_without_card_border(self):
        with TemporaryDirectory() as folder:
            catalog=UnitCatalog(Path(folder))
            portrait=np.random.default_rng(32).integers(0,255,(110,80,3),dtype=np.uint8)
            catalog.add_references(portrait,[ArmyCard('ref',(0,0,80,110),'hero','hero',1,confirmed=True)])
            for left in (400,570):
                frame=np.full((600,1000,3),(100,90,80),np.uint8)
                frame[485:595,left:left+80]=portrait
                boxes=catalog.locate_references(frame)
                self.assertEqual(len(boxes),1)
                x,y,w,h=boxes[0]
                self.assertLess(abs(x-left),4)
                self.assertLess(abs(y-485),4)
                self.assertGreater(w,75)
            self.assertFalse(catalog.locate_references(np.zeros_like(frame)))


class MappingTests(TestCase):
    def map_frame(self):
        frame=np.full((600,1000,3),(70,120,70),np.uint8)
        cv2.polylines(frame,[np.array([[200,270],[500,100],[800,270],[500,425]])],True,(25,30,190),2)
        return frame

    def test_red_scenery_without_battle_evidence_is_not_a_map(self):
        result=observe_boundary(self.map_frame())
        self.assertEqual(result.coverage,'none')
        self.assertFalse(result.deployment_ready)
        self.assertFalse(result.segments)

    def test_supported_boundary_is_partial_not_a_guessed_full_map(self):
        result=observe_boundary(self.map_frame(),battle_confirmed=True)
        self.assertGreaterEqual(len(result.segments),4)
        self.assertEqual(result.coverage,'partial')
        self.assertFalse(result.deployment_ready)

    def test_hud_red_buttons_do_not_produce_boundary(self):
        frame=np.zeros((600,1000,3),np.uint8)
        cv2.rectangle(frame,(5,440),(130,495),(30,30,200),-1)
        result=observe_boundary(frame,battle_confirmed=True)
        self.assertFalse(result.segments)

    def test_orange_gold_wall_trim_is_not_a_red_boundary(self):
        frame=self.map_frame()
        frame[:]=(70,120,70)
        cv2.polylines(frame,[np.array([[200,270],[500,100],[800,270],[500,425]])],True,(60,150,215),2)
        result=observe_boundary(frame,battle_confirmed=True)
        self.assertFalse(result.segments)

    def test_expiry_resize_wrong_reference_and_camera_motion_invalidate_map(self):
        frame=self.map_frame();now=time.time()
        observation=OpponentMap(1000,600,now,hashlib.sha256(frame.tobytes()).hexdigest(),[],True)
        stationary={'verified':True,'scale':1.,'transform':[[1,0,0],[0,1,0]]}
        with patch('coc_bot.attack.mapping.compare_camera',return_value=stationary):
            self.assertTrue(map_is_current(observation,frame,frame,now=now))
            self.assertFalse(map_is_current(observation,frame,frame,now=now+31))
            self.assertFalse(map_is_current(observation,frame,frame[:300],now=now))
            self.assertFalse(map_is_current(observation,np.zeros_like(frame),frame,now=now))
        moved=stationary|{'transform':[[1,0,5],[0,1,0]]}
        with patch('coc_bot.attack.mapping.compare_camera',return_value=moved):
            self.assertFalse(map_is_current(observation,frame,frame,now=now))


class SurveyBoundsTests(TestCase):
    def run_survey(self, projection=None, stop_after=None, weak_target=None):
        from coc_bot.attack.survey import survey
        with TemporaryDirectory() as root:
            session=Mock()
            session.config.data_dir=Path(root)
            frame=np.full((600,1000,3),80,np.uint8)
            session.capture.screenshot.return_value=frame
            session.client.wm_size.return_value=(1000,600)
            session.client.stop_check=lambda: stop_after is not None and session.input.swipe.call_count>=stop_after
            evidence={'verified':True,'scale':1.,'transform':[[1,0,0],[0,1,0]]}
            observation=OpponentMap(1000,600,time.time(),'test',[],True)
            def fit(*args,**kwargs):
                if weak_target is not None:
                    kwargs['survey_evidence']['weak_sides']=[{'coverage':.12,'target':weak_target}]
                return projection
            with patch('coc_bot.attack.survey.compare_camera',return_value=evidence), \
                    patch('coc_bot.attack.survey.observe_boundary',return_value=observation), \
                    patch('coc_bot.attack.survey.fit_projection',side_effect=fit), \
                    patch('coc_bot.attack.army.card_boxes',return_value=[(100,500,80,90)]):
                if stop_after is not None:
                    with self.assertRaises(AdbStopped):survey(session,zoom=False,full_map=True)
                    self.assertEqual(session.input.swipe.call_count,stop_after)
                    return
                result=survey(session,zoom=False,full_map=True)
            self.assertEqual(session.input.tap.call_count,2) # Card selection only, no map deploy.
            self.assertTrue(all(c.args==(140,545) for c in session.input.tap.call_args_list))
            self.pan_calls=session.input.swipe.call_args_list
            return result,session.input.swipe.call_count

    def test_incomplete_map_gets_bounded_extended_pass_without_guessing(self):
        result,pans=self.run_survey()
        self.assertEqual(pans,12)
        self.assertEqual(result['views'],13)
        self.assertIsNone(result['projection'])

    def test_complete_first_pass_does_not_make_extra_pans(self):
        _,pans=self.run_survey(projection=Mock())
        self.assertLess(pans,8)

    def test_stop_during_extended_pass_never_sends_remaining_pans(self):
        self.run_survey(stop_after=9)

    def test_final_pass_targets_missing_evidence_without_adding_more_pans(self):
        result,pans=self.run_survey(weak_target=(800,100))
        self.assertEqual(pans,12)
        self.assertIsNone(result['projection'])
        self.assertTrue(all(c.args==(480,276,260,396,350) for c in self.pan_calls[-4:]))


class OutlineSelectionTests(TestCase):
    def test_existing_outline_is_not_toggled_off(self):
        from coc_bot.attack.survey import reveal_boundary
        frame=np.zeros((600,1000,3),np.uint8);session=Mock()
        session.client.stop_check=lambda:False;session.capture.screenshot.return_value=frame
        visible=OpponentMap(1000,600,time.time(),'test',[{},{}],True)
        with patch('coc_bot.attack.survey.observe_boundary',return_value=visible):
            reveal_boundary(session,frame)
        session.input.tap.assert_not_called()

    def test_failed_outline_click_retries_using_new_card_position(self):
        from coc_bot.attack.survey import reveal_boundary
        frame=np.zeros((600,1000,3),np.uint8);session=Mock()
        session.client.stop_check=lambda:False;session.capture.screenshot.return_value=frame
        absent=OpponentMap(1000,600,time.time(),'test',[],False)
        visible=replace(absent,segments=[{},{}],stable=True)
        with patch('coc_bot.attack.survey.observe_boundary',side_effect=[absent,absent,absent,visible]), \
                patch('coc_bot.attack.army.card_boxes',side_effect=[[(100,500,70,90)],[(150,500,70,90)]]):
            reveal_boundary(session,frame)
        self.assertEqual([c.args for c in session.input.tap.call_args_list],[(135,545),(185,545)])


class ObservationReviewTests(TestCase):
    def test_review_revision_and_image_path_guards(self):
        with TemporaryDirectory() as folder:
            data=Path(folder);ident='a'*32;p=data/'debug/attack-observations'/ident;p.mkdir(parents=True)
            card=ArmyCard('card-0',(0,0,10,10),None,'hero',1)
            report={'cards':[card.to_dict()],'ready_for_execution':False,'map':{'coverage':'partial'}}
            write_report(p,report)
            correction={'slot':'card-0','unit_id':'barbarian_king','kind':'hero','quantity':1,'confirmed':True}
            updated=review_army(data,ident,report['revision'],[correction])
            self.assertTrue(updated['cards'][0]['confirmed'])
            self.assertFalse(updated['ready_for_execution'])
            with self.assertRaises(ValueError):review_army(data,ident,report['revision'],[correction])
            for value in ('../../calibrated.yaml','report.json','card-999.png'):
                with self.assertRaises(ValueError):observation_asset(data,ident,value)

    def test_screen_change_or_stop_prevents_report(self):
        session=Mock()
        session.client.stop_check=lambda:False
        session.capture.screenshot.side_effect=[np.zeros((600,1000,3),np.uint8),np.zeros((300,1000,3),np.uint8)]
        with patch('coc_bot.control.attack_observation.page_for',return_value='battle'):
            with self.assertRaisesRegex(ValueError,'changed'):inspect_attack(session)
        with self.assertRaises(AdbStopped):page_for(np.zeros((60,100,3),np.uint8),lambda:True)
