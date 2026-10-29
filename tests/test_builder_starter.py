import unittest
from pathlib import Path
import cv2
import shutil
from types import SimpleNamespace
from unittest.mock import Mock,patch
import numpy as np
from coc_bot.builder_base.vision import BuilderReader
from coc_bot.builder_base.starter import army,card,watch


class StarterTests(unittest.TestCase):
    def frame(self,name):return cv2.imread(str(Path(__file__).parent/'fixtures/builder_base'/name))

    def test_preflight_uses_art_count_and_all_visible_camps(self):
        r=BuilderReader();f=self.frame('starter-menu.png')
        self.assertEqual(army(r,f),{'family':'raged_barbarian','groups':1,'units':3})
        for box in ((315,400,415,505),(330,400,353,431),(1200,630,1560,751)):
            bad=f.copy();x0,y0,x1,y1=box;bad[y0:y1,x0:x1]=0
            self.assertIsNone(army(r,bad))
        # A different unit/hero cannot pass as an empty second camp.
        f[400:503,425:529]=127
        self.assertIsNone(army(r,f))

    def test_existing_witch_army_is_not_relabelled_starter(self):
        self.assertIsNone(army(BuilderReader(),self.frame('controls-14.png')))

    def test_busy_boundary_midpoints_do_not_hide_clear_fallback_tiles(self):
        from coc_bot.builder_base.runner import deployment_points
        frame=self.frame('starter-zoomed-obstructed-boundary.png')
        self.assertTrue(deployment_points(frame))
        self.assertIn((593,482),deployment_points(frame))
        self.assertEqual(deployment_points(np.zeros_like(frame)),[])

    def test_inspected_winter_arena_has_terrain_candidates_after_zoom(self):
        from coc_bot.builder_base.runner import deployment_points
        frame=self.frame('starter-zoomed-winter.png')
        self.assertGreaterEqual(len(deployment_points(frame)),2)

    def test_home_and_results_cannot_authorize_starter_deployment(self):
        r=BuilderReader()
        self.assertIsNone(card(r,self.frame('controls-24.png')))
        self.assertIsNone(card(r,self.frame('controls-23.png')))

    @unittest.skipUnless(shutil.which('tesseract'),'OCR executable is required')
    def test_normal_selected_and_spent_cards_keep_their_real_counts(self):
        r=BuilderReader()
        for name,count in [('idle-3',3),('selected-3',3),('selected-2',2),('selected-1',1),('spent-0',0)]:
            with self.subTest(name=name):
                result=card(r,self.frame('starter-'+name+'.png'))
                self.assertIsNotNone(result);self.assertEqual(result['count'],count)
        bad=self.frame('starter-selected-2.png');bad[840:900]=0
        self.assertIsNone(card(r,bad))

    def test_uncertain_receipt_stops_after_one_possible_deployment(self):
        r=Mock();r.frame.return_value=np.zeros((20,20,3),np.uint8)
        r.reader.result_button.return_value=None;r.reader.reward_button.return_value=None
        r.reader.home.return_value=False;r.reader.battle.return_value=True
        r.record={'starter_army':{'groups':1,'units':3}}
        observed=[{'point':(208,929),'count':3}]
        with patch('coc_bot.builder_base.starter.cards',side_effect=[observed,observed,[]]),\
             patch('coc_bot.builder_base.runner.deployment_points',return_value=[(500,400)]),\
             patch('coc_bot.builder_base.tutorials.recover',return_value=False):
            with self.assertRaisesRegex(ValueError,'receipt is uncertain'):watch(r,deploy=True)
        self.assertEqual([c.args[0] for c in r.tap.call_args_list],[(208,929),(500,400)])
        self.assertEqual(r.record['starter_sent'],1)
        self.assertNotIn('starter_confirmed',r.record)
        r.zoom.assert_called_once()

    def test_recovery_never_replays_a_saved_deployment(self):
        r=Mock();r.reader.result_button.return_value=None;r.reader.reward_button.return_value=None
        r.reader.home.return_value=True;r.record={'starter_sent':1,'starter_army':{'groups':1,'units':3}}
        with patch('coc_bot.builder_base.tutorials.recover',return_value=False):
            self.assertEqual(watch(r,deploy=False)['status'],'returned')
        r.tap.assert_not_called()
        r.zoom.assert_not_called()
