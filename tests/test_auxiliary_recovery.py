"""Conflicting/transient menu observations must never authorize a tap."""
from unittest import TestCase
from unittest.mock import Mock, patch
import cv2
import numpy as np
from pathlib import Path

from coc_bot.auxiliary_recovery import AuxiliaryRecovery
from coc_bot.vision.auxiliary import AuxiliaryPage, AuxiliaryPageDetector


class AuxiliaryRecoveryTests(TestCase):
    def setUp(self):
        self.classifier = Mock()
        self.inputs = Mock()
        self.recovery = AuxiliaryRecovery(self.classifier, self.inputs, lambda:False)
        self.frame = np.zeros((540, 960, 3), np.uint8)

    def test_second_fresh_observation_required(self):
        self.classifier.auxiliary_page.return_value = AuxiliaryPage('settings', (842,43))
        self.assertTrue(self.recovery.close(self.frame))
        self.inputs.tap.assert_not_called()
        self.assertTrue(self.recovery.close(self.frame.copy()))
        self.inputs.tap.assert_called_once_with(842,43,jitter=0)

    def test_reused_frame_or_changing_pages_exhaust_without_input(self):
        self.classifier.auxiliary_page.return_value = AuxiliaryPage('shop', (920,40))
        self.assertTrue(self.recovery.close(self.frame))
        self.assertTrue(self.recovery.close(self.frame))
        self.assertFalse(self.recovery.close(self.frame))
        self.inputs.tap.assert_not_called()
        self.recovery = AuxiliaryRecovery(self.classifier, self.inputs, lambda:False)
        self.classifier.auxiliary_page.side_effect = [AuxiliaryPage(s, (920,40)) for s in ('shop','settings','shop')]
        self.assertTrue(self.recovery.close(self.frame.copy()))
        self.assertTrue(self.recovery.close(self.frame.copy()))
        self.assertFalse(self.recovery.close(self.frame.copy()))
        self.inputs.tap.assert_not_called()

    def test_obscured_control_and_stop_never_tap(self):
        self.classifier.auxiliary_page.return_value = AuxiliaryPage('shop', None)
        for _ in range(2): self.assertTrue(self.recovery.close(self.frame.copy()))
        self.assertFalse(self.recovery.close(self.frame.copy()))
        self.classifier.auxiliary_page.return_value = AuxiliaryPage('shop', (920,40))
        self.assertFalse(AuxiliaryRecovery(self.classifier,self.inputs,lambda:True).close(self.frame))
        self.inputs.tap.assert_not_called()

    def test_settings_tab_alone_is_not_settings_and_dimmed_close_is_refused(self):
        root = Path(__file__).resolve().parents[1]/'src/coc_bot/vision/assets'
        frame = self.frame.copy()
        def add(name,x,y):
            image=cv2.imread(str(root/(name+'.png')));h,w=image.shape[:2]
            frame[y:y+h,x:x+w]=image
        add('settings_title',723,36)
        add('settings_close',826,26)
        with patch('coc_bot.upgrades.vision.UpgradeReader.menu_kind', return_value=None):
            self.assertIsNone(AuxiliaryPageDetector().detect(frame))
            add('settings_music',317,165);add('settings_sound',564,165)
            result=AuxiliaryPageDetector().detect(frame)
            self.assertEqual(result.screen,'settings');self.assertIsNotNone(result.close)
            dim=AuxiliaryPageDetector().detect((frame*.4).astype(np.uint8))
            self.assertEqual(dim.screen,'settings');self.assertIsNone(dim.close)
