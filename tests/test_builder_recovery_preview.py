"""A rejected research preview must retain a safe, non-spending exit."""
import shutil
import unittest
from unittest.mock import patch
from pathlib import Path
import cv2
from coc_bot.builder_base.vision import BuilderReader
from coc_bot.upgrades.vision import Candidate


@unittest.skipUnless(shutil.which('tesseract'),'Tesseract is required')
class BuilderPreviewRecoveryTests(unittest.TestCase):
    def test_level_five_ocr_confusion_can_close_but_does_not_authorize_payment(self):
        frame=cv2.imread(str(Path(__file__).parent/'fixtures/builder_base/rejected-level-five-preview.png'))
        reader=BuilderReader()
        self.assertEqual(reader.detail_close(frame),(1555,67))
        with patch.object(reader,'label',return_value='UpgrRade to level S?'):
            self.assertEqual(reader.detail_close(frame),(1555,67))
        self.assertIsNone(reader.confirmation(frame,Candidate('Night Witch',100000,'elixir',(0,0))))
        self.assertIsNone(reader.confirmation(frame,Candidate('Sneaky Archer',999,'elixir',(0,0))))
        missing=frame.copy();missing[25:116,1512:1605]=0
        self.assertIsNone(reader.detail_close(missing))
        missing=frame.copy();missing[125:189,880:1502]=0
        self.assertIsNone(reader.detail_close(missing))
