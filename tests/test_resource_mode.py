"""Selected-resource verification must tolerate exposure, not selection changes."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

import cv2
import numpy as np

from coc_bot.donation.resource_mode import elixir_is_selected


class ResourceModeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = SimpleNamespace(
            templates_dir=Path(self.tmp.name),
            templates={"donation_elixir_selected": "selected.png"},
            rois={"donation_elixir_selected": [0, 0, 1, 1]},
        )
        self.reference = np.full((80, 200, 3), (75, 160, 220), np.uint8)
        self.reference[:3] = (230, 240, 245)
        self.reference[-3:] = (35, 55, 65)
        cv2.circle(self.reference, (42, 40), 19, (170, 35, 180), -1)
        cv2.rectangle(self.reference, (85, 24), (175, 54), (220, 230, 240), -1)
        cv2.imwrite(str(self.config.templates_dir / "selected.png"), self.reference)

    def exposed(self, gain):
        return np.clip(self.reference.astype(float) * gain, 0, 255).astype(np.uint8)

    def test_common_brightness_change_preserves_selection(self):
        for gain in (.7, .85, 1., 1.1):
            with self.subTest(gain=gain):
                self.assertTrue(elixir_is_selected(self.config, self.exposed(gain)))

    def test_border_change_is_rejected_even_with_brightness_correction(self):
        image = self.exposed(.7)
        image[:3] = image[4]
        self.assertFalse(elixir_is_selected(self.config, image))

    def test_different_fill_and_same_icon_is_rejected(self):
        image = self.reference.copy()
        image[4:-4, 65:190] = (130, 190, 245)
        image = (image.astype(float) * .7).astype(np.uint8)
        self.assertFalse(elixir_is_selected(self.config, image))

    def test_channel_color_change_is_not_exposure(self):
        image = self.exposed(.7)
        image[:, :, 0] = np.clip(image[:, :, 0].astype(float) * 1.8, 0, 255)
        self.assertFalse(elixir_is_selected(self.config, image))

    def test_extreme_darkening_and_blank_frames_are_rejected(self):
        for image in (self.exposed(.5), np.zeros_like(self.reference),
                      np.full_like(self.reference, 100)):
            with self.subTest(mean=float(image.mean())):
                self.assertFalse(elixir_is_selected(self.config, image))

    def test_flat_reference_cannot_enable_exposure_fallback(self):
        cv2.imwrite(str(self.config.templates_dir / "selected.png"),
                    np.full_like(self.reference, 150))
        self.assertFalse(elixir_is_selected(self.config, np.full_like(self.reference, 105)))


if __name__ == "__main__":
    unittest.main()
