from pathlib import Path
from unittest import TestCase

import cv2
import numpy as np

from coc_bot.vision.battle_completion import BattleCompletionDetector


ASSETS = Path(__file__).resolve().parents[1]/'src/coc_bot/vision/assets'


def result_frame():
    frame = np.zeros((540, 960, 3), np.uint8)
    for name,x,y in [('results_return_home',444,444), ('results_troops_expended',428,348)]:
        image = cv2.imread(str(ASSETS/(name+'.png')))
        h,w = image.shape[:2]
        frame[y:y+h,x:x+w] = image
    return frame


class BattleCompletionTests(TestCase):
    def test_changing_village_and_army_behind_gold_label_does_not_hide_results(self):
        reference = cv2.imread(str(ASSETS/'results_troops_expended.png'))
        # Keep only the reference's warm-colored lettering; replace everything
        # else with different scenery/portraits, including the lower crop edge.
        b,g,r = cv2.split(reference.astype(np.int16))
        letters = (r > 110) & (r > b+30) & (g > b+20)
        rng = np.random.default_rng(15)
        for size in [(960,540),(1853,1048),(1280,720),(1920,1080)]:
            for background in [(30,140,30),(170,130,100),'noise']:
                frame = result_frame()
                patch = (rng.integers(60,200,reference.shape,dtype=np.uint8)
                         if background=='noise' else np.full_like(reference,background))
                if background=='noise':
                    # Cool, varied scenery rather than gold pixels obscuring
                    # the actual lettering, which should remain uncertain.
                    patch[:,:,2] = patch[:,:,0]//2
                patch[letters] = reference[letters]
                h,w = patch.shape[:2]
                frame[348:348+h,428:428+w] = patch
                self.assertIsNotNone(BattleCompletionDetector().detect(cv2.resize(frame,size)))

    def test_both_labels_spatial_agreement_and_enabled_button_remain_required(self):
        detector = BattleCompletionDetector()
        frame = result_frame()
        self.assertIsNotNone(detector.detect(frame))
        for box in [(340,320,620,400),(370,420,590,520)]:
            x,y,r,b=box;partial=frame.copy();partial[y:b,x:r]=0
            self.assertIsNone(detector.detect(partial))
        self.assertIsNone(detector.detect((frame*.35).astype(np.uint8)))
        shifted=frame.copy();shifted[348:368,340:454]=frame[348:368,428:542]
        shifted[348:368,454:620]=0
        self.assertIsNone(detector.detect(shifted))
        for color in [(30,170,20),(0,0,0),(0,180,230)]:
            self.assertIsNone(detector.detect(np.full_like(frame,color)))

    def test_gold_scenery_below_title_is_excluded_even_when_its_color_matches(self):
        frame=result_frame()
        frame[361:368,428:542]=(0,180,220)
        for size in [(960,540),(1853,1048),(1280,720),(1920,1080)]:
            self.assertIsNotNone(BattleCompletionDetector().detect(cv2.resize(frame,size)))

    def test_two_fresh_observations_stop_and_deadline_safeguards(self):
        from scripts.verify_battle_completion import wait_checks
        wait_checks(result_frame())
