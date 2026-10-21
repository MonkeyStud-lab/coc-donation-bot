"""Donation proposal identity, abstention and frame-coordinate checks; no ADB."""
from pathlib import Path
from unittest import TestCase

import cv2
import numpy as np

from coc_bot.vision.donation_calibration import REFERENCE, suggest_donation


def panel():
    frame = np.full((1048, 1853, 3), 25, np.uint8)
    cv2.rectangle(frame, (720, 72), (1710, 1047), (230, 230, 230), -1)
    cv2.rectangle(frame, (720, 72), (1710, 198), (128, 117, 110), -1)
    assets = Path(__file__).resolve().parents[1] / 'src/coc_bot/vision/assets'
    for name, (x, y, w, h) in REFERENCE.items():
        crop = cv2.imread(str(assets / f'donation_{name}.png'))
        frame[y:y+h, x:x+w] = crop
    return frame


class DonationSuggestions(TestCase):
    def test_visible_references_locate_proposals_without_calibration(self):
        result = suggest_donation(panel())
        self.assertTrue(result['supported'])
        parts = {p['part']: p for p in result['proposals']}
        self.assertEqual(set(parts), {'donation_panel', 'donation_elixir_button',
            'donation_troop_bar', 'donation_spell_bar', 'troop_bar', 'spell_bar'})
        self.assertEqual((parts['troop_bar']['cols'], parts['troop_bar']['rows']), (7, 2))
        self.assertEqual((parts['spell_bar']['cols'], parts['spell_bar']['rows']), (7, 1))
        # State-sensitive calibration is deliberately never inferred from icons.
        self.assertNotIn('donation_elixir_selected', parts)
        self.assertNotIn('donatable_troop', parts)

    def test_translation_and_resolution_return_original_coordinates(self):
        original = panel()
        translated = cv2.warpAffine(original, np.float32([[1, 0, -100], [0, 1, -30]]), (1853, 1048))
        base = suggest_donation(original)['proposals'][2]['selection']
        for width in (960, 1280, 1920):
            resized = cv2.resize(translated, (width, round(1048*width/1853)))
            result = suggest_donation(resized)
            self.assertTrue(result['supported'], width)
            actual = result['proposals'][2]['selection']
            expected = [(base[0]-100)*width/1853, (base[1]-30)*width/1853,
                        base[2]*width/1853, base[3]*width/1853]
            self.assertTrue(all(abs(a-b) <= 5 for a,b in zip(actual, expected)), (actual, expected))

    def test_missing_spell_layout_dimmed_dialog_and_other_screens_abstain(self):
        missing = panel()
        x,y,w,h = REFERENCE['spells']
        missing[y-5:y+h+5, x-5:x+w+5] = 230
        for frame in (missing, (panel() * .5).astype(np.uint8),
                      np.full((1048,1853,3), 240, np.uint8),
                      np.zeros((1048,1853,3), np.uint8), np.zeros((800,400,3), np.uint8),
                      np.zeros((30,30),np.uint8)):
            self.assertFalse(suggest_donation(frame)['supported'])

    def test_proposals_are_inside_the_frame(self):
        result = suggest_donation(panel())
        for p in result['proposals']:
            x,y,w,h = p['selection']
            self.assertTrue(0 <= x < x+w <= 1853 and 0 <= y < y+h <= 1048)
