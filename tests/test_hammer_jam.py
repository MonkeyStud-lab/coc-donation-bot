from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock
import cv2
import numpy as np
from coc_bot.vision import notices
from coc_bot.vision.notices import hammer_jam_close_button, mass_mommas_close_button
from coc_bot.progression.home import recover_home_announcement

ROOT=Path(__file__).parent/'fixtures/accounts'


class HammerJamTests(TestCase):
    def frame(self):return cv2.imread(str(ROOT/'hammer-jam.png'))

    def test_actual_popup_closes_only_at_its_native_x_and_scales(self):
        for size in ((1853,1048),(1280,724)):
            point=hammer_jam_close_button(cv2.resize(self.frame(),size))
            self.assertIsNotNone(point)
            self.assertLess(abs(point[0]/size[0]-1594/1853),.005)
            self.assertLess(abs(point[1]/size[1]-114/1048),.005)

    def test_title_message_close_and_brightness_are_all_required(self):
        for x,y,w,h in ((518,673,816,67),(445,761,961,78),(1556,76,77,77)):
            frame=self.frame();frame[y:y+h,x:x+w]=0
            self.assertIsNone(hammer_jam_close_button(frame))
        self.assertIsNone(hammer_jam_close_button((self.frame()*.4).astype('uint8')))
        for name in ('defense-results.png','event-ended.png','connection-error.png'):
            self.assertIsNone(hammer_jam_close_button(cv2.imread(str(ROOT/name))))

    def test_fresh_frame_stop_and_repeat_limit(self):
        nav=SimpleNamespace(_stopping=Mock(return_value=False),capture=Mock(),input=Mock())
        nav.capture.screenshot.return_value=self.frame()
        self.assertTrue(recover_home_announcement(nav,self.frame()))
        self.assertTrue(recover_home_announcement(nav,self.frame()))
        self.assertFalse(recover_home_announcement(nav,self.frame()))
        self.assertEqual(nav.input.tap.call_count,2)
        nav._hammer_jam_taps=0;nav._stopping.return_value=True
        self.assertFalse(recover_home_announcement(nav,self.frame()))
        nav._stopping.return_value=False;nav.capture.screenshot.return_value=self.frame()*0
        self.assertFalse(recover_home_announcement(nav,self.frame()))
        self.assertEqual(nav.input.tap.call_count,2)


class MassMommasTests(TestCase):
    def test_announcement_recovery_rechecks_the_close_control(self):
        assets = Path(notices.__file__).with_name('assets')
        frame = np.zeros((1048, 1853, 3), dtype=np.uint8)
        for name, x, y in (('title', 586, 670), ('go', 762, 860), ('close', 1557, 77)):
            anchor = cv2.imread(str(assets / f'mass_mommas_{name}.png'))
            height, width = anchor.shape[:2]
            frame[y:y+height, x:x+width] = anchor
        self.assertEqual(mass_mommas_close_button(frame), (1597, 116))
        dimmed = (frame * .4).astype(np.uint8)
        nav = SimpleNamespace(_stopping=Mock(return_value=False), capture=Mock(), input=Mock())
        nav.capture.screenshot.return_value = dimmed
        self.assertFalse(recover_home_announcement(nav, frame))
        nav.input.tap.assert_not_called()
        nav.capture.screenshot.return_value = frame.copy()
        self.assertTrue(recover_home_announcement(nav, frame))
        nav.input.tap.assert_called_once_with(1597, 116, jitter=0)
