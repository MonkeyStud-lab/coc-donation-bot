import unittest

import cv2
import numpy as np

from coc_bot.vision.colors import SlotColorDetector


class SlotColorTests(unittest.TestCase):
    def setUp(self):
        self.detector = SlotColorDetector(
            troop_color_bgr=[101, 148, 188], troop_grey_bgr=[233, 233, 233],
            spell_color_bgr=[255, 115, 14], spell_grey_bgr=[186, 186, 186])

    @staticmethod
    def grey_card(brightness=120):
        cell = np.full((150, 128, 3), brightness, np.uint8)
        cv2.circle(cell, (64, 67), 36, (55, 55, 55), -1)
        cv2.rectangle(cell, (20, 121), (100, 137), (210, 210, 210), -1)
        return cell

    def test_disabled_cards_stay_disabled_at_different_brightness(self):
        for brightness in (45, 70, 100, 140, 190, 230):
            with self.subTest(brightness=brightness):
                self.assertFalse(self.detector.is_donatable_troop(self.grey_card(brightness)))
                self.assertFalse(self.detector.is_donatable_spell(self.grey_card(brightness)))

    def test_pale_face_with_colored_card_and_resource_is_donatable(self):
        cell = self.grey_card()
        cell[:, :13] = (155, 100, 40)
        cell[:, -13:] = (155, 100, 40)
        cv2.circle(cell, (112, 130), 9, (100, 25, 60), -1)
        for gain in (.7, 1.):
            with self.subTest(gain=gain):
                self.assertTrue(self.detector.is_donatable_troop((cell * gain).astype(np.uint8)))

    def test_warning_over_top_of_disabled_card_is_not_a_colored_unit(self):
        cell = self.grey_card(75)
        cv2.putText(cell, 'SPACE', (0, 26), cv2.FONT_HERSHEY_SIMPLEX, .8, (0, 0, 190), 4)
        self.assertFalse(self.detector.is_donatable_troop(cell))

    def test_different_troop_and_spell_hues_are_supported(self):
        for color in ((150, 60, 30), (100, 20, 130), (20, 120, 150), (20, 20, 150)):
            with self.subTest(color=color):
                cell = self.grey_card()
                cv2.rectangle(cell, (15, 65), (110, 110), color, -1)
                self.assertTrue(self.detector.is_donatable_troop(cell))
                self.assertTrue(self.detector.is_donatable_spell(cell))

    def test_small_color_noise_and_blank_cells_are_not_donatable(self):
        cell = self.grey_card()
        cell[80:83, 50:53] = (200, 20, 20)
        self.assertFalse(self.detector.is_donatable_troop(cell))
        self.assertFalse(self.detector.is_donatable_troop(np.zeros_like(cell)))


if __name__ == '__main__':
    unittest.main()
