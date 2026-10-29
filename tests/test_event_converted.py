from pathlib import Path
import unittest
import cv2
from coc_bot.vision.notices import event_ended_button


class ConvertedEventTests(unittest.TestCase):
    def setUp(self):
        self.frame=cv2.imread(str(Path(__file__).parent/'fixtures/accounts/event-converted.png'))

    def test_delivered_conversion_and_variable_amount(self):
        self.assertEqual(event_ended_button(self.frame),(926,888))
        changed=self.frame.copy()
        changed[662:702,940:1080]=changed[710,940]
        self.assertIsNotNone(event_ended_button(changed))
        self.assertIsNotNone(event_ended_button(cv2.resize(self.frame,(1280,724))))

    def test_missing_notice_evidence_or_dark_overlay_is_rejected(self):
        for x0,y0,x1,y1 in ((680,400,1170,510),(450,618,1405,659),
                              (670,662,928,702),(770,800,1090,970)):
            frame=self.frame.copy();frame[y0:y1,x0:x1]=0
            self.assertIsNone(event_ended_button(frame))
        self.assertIsNone(event_ended_button((self.frame*.5).astype('uint8')))

    def test_original_trading_notice_still_works(self):
        frame=cv2.imread(str(Path(__file__).parent/'fixtures/accounts/event-ended.png'))
        self.assertIsNotNone(event_ended_button(frame))
