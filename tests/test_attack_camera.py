import struct
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

import cv2
import numpy as np

from coc_bot.adb.client import AdbStopped
from coc_bot.adb.multitouch import Multitouch, touch_packet
from coc_bot.attack.camera import compare_camera, compare_home_zoom


class MultitouchTests(TestCase):
    def transport(self):
        self.cancel = False
        touch = Multitouch(SimpleNamespace(stop_check=lambda: self.cancel), (1000, 600))
        touch.connection = Mock()
        return touch

    def test_wire_format_is_pinned_32_byte_touch(self):
        packet = touch_packet(0, 1, 250, 200, 1000, 600)
        self.assertEqual(len(packet), 32)
        self.assertEqual(struct.unpack('>BBQiiHHHII', packet),
                         (2, 0, 1, 250, 200, 1000, 600, 65535, 0, 0))
        self.assertEqual(struct.unpack('>BBQiiHHHII', touch_packet(1, 1, 250, 200, 1000, 600))[7], 0)

    def test_invalid_inputs_never_become_events(self):
        for args in [(0, 0, -1, 0, 100, 100), (0, 0, 100, 0, 100, 100),
                     (0, 2, 10, 0, 100, 100), (0, 0, True, 0, 100, 100)]:
            with self.assertRaises(ValueError):
                touch_packet(*args)
        touch = self.transport()
        for kwargs in ({'steps': True}, {'start_span': float('nan')}, {'duration': -1}):
            with self.assertRaises(ValueError):
                touch.pinch(**kwargs)
        touch.connection.sendall.assert_not_called()

    def test_stop_between_finger_downs_releases_first_finger(self):
        touch = self.transport()
        packets = []
        def send(packet):
            packets.append(struct.unpack('>BBQiiHHHII', packet))
            self.cancel = True
        touch.connection.sendall.side_effect = send
        with self.assertRaises(AdbStopped):
            touch.pinch()
        self.assertEqual([(p[1],p[2]) for p in packets], [(0,0),(1,0)])
        self.assertFalse(touch.active)

    def test_stop_during_movement_releases_both_fingers(self):
        touch = self.transport()
        packets = []
        def send(packet):
            packets.append(struct.unpack('>BBQiiHHHII', packet))
            if len(packets) == 3:
                self.cancel = True
        touch.connection.sendall.side_effect = send
        with self.assertRaises(AdbStopped):
            touch.pinch(duration=.2, steps=4)
        self.assertEqual([(p[1],p[2]) for p in packets[-2:]], [(1,1),(1,0)])
        self.assertFalse(touch.active)

    def test_disconnect_attempts_release_without_replaying_gesture(self):
        touch = self.transport()
        touch.connection.sendall.side_effect = [None, OSError('disconnected'), None, None]
        with self.assertRaises(OSError):
            touch.pinch()
        self.assertEqual(touch.connection.sendall.call_count, 4)
        self.assertFalse(touch.active)

    def test_startup_retries_early_adb_eof_and_removes_only_own_forward(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'server.jar'
            path.write_bytes(b'test')
            client = Mock(device='example:5555', stop_check=None)
            client.run.return_value.stdout = '43210'
            first, ready, process = Mock(), Mock(), Mock()
            first.recv.return_value = b''
            ready.recv.return_value = b'\0'
            process.poll.return_value = None
            with patch('coc_bot.adb.multitouch.hashlib.sha256') as checksum, \
                 patch('coc_bot.adb.multitouch.subprocess.Popen', return_value=process), \
                 patch('coc_bot.adb.multitouch.socket.create_connection', side_effect=[first, ready]), \
                 patch('coc_bot.adb.multitouch.AdbClient') as cleanup:
                from coc_bot.adb.multitouch import SERVER_SHA256
                checksum.return_value.hexdigest.return_value = SERVER_SHA256
                with Multitouch(client, (1000, 600), path) as touch:
                    self.assertIs(touch.connection, ready)
                first.close.assert_called_once()
                ready.close.assert_called_once()
                cleanup.return_value.run.assert_called_once_with(
                    ['forward', '--remove', 'tcp:43210'], timeout=3)
                process.terminate.assert_called_once()

    def test_missing_server_never_connects_or_sends_events(self):
        with TemporaryDirectory() as folder:
            touch = Multitouch(SimpleNamespace(stop_check=None), (1000, 600), Path(folder)/'missing')
            with patch('coc_bot.adb.multitouch.subprocess.Popen') as process:
                with self.assertRaisesRegex(ValueError, 'pinned scrcpy'):
                    touch.__enter__()
                process.assert_not_called()


class CameraEvidenceTests(TestCase):
    def textured_map(self):
        rng = np.random.default_rng(42)
        frame = np.full((600, 1000, 3), 100, np.uint8)
        for _ in range(600):
            x,y = rng.integers(160,840),rng.integers(80,460)
            color = tuple(int(v) for v in rng.integers(0,255,3))
            cv2.circle(frame, (int(x),int(y)), int(rng.integers(3,11)), color, -1)
        return frame

    def test_zoom_scale_is_measured_without_claiming_map_readiness(self):
        before = self.textured_map()
        transform = cv2.getRotationMatrix2D((500,250), 0, .8)
        after = cv2.warpAffine(before, transform, (1000,600))
        result = compare_camera(before, after)
        self.assertTrue(result['verified'], result)
        self.assertAlmostEqual(result['scale'], .8, delta=.03)
        self.assertTrue(result['zoomed_out'])
        self.assertFalse(result['battlefield_mapping_ready'])
        self.assertFalse(result['maximum_zoom_confirmed'])

    def test_unchanged_image_does_not_prove_maximum_zoom(self):
        before = self.textured_map()
        result = compare_camera(before, before.copy())
        self.assertTrue(result['verified'])
        self.assertFalse(result['zoomed_out'])
        self.assertFalse(result['maximum_zoom_confirmed'])

    def test_blank_changed_size_and_unrelated_frames_are_rejected(self):
        before = self.textured_map()
        for after in (np.zeros_like(before), before[:300], np.flip(before, axis=0).copy()):
            self.assertFalse(compare_camera(before, after)['verified'])

    def test_large_zoom_is_not_confused_with_stationary_interface(self):
        before = self.textured_map()
        after = cv2.warpAffine(before, cv2.getRotationMatrix2D((500,250), 0, .35), (1000,600))
        # Simulate a fixed bright interface badge outside the map mask.
        before[5:70, 5:140] = after[5:70, 5:140] = 255
        result = compare_camera(before, after)
        self.assertTrue(result['verified'], result)
        self.assertAlmostEqual(result['scale'], .35, delta=.03)

    def test_home_zoom_uses_distributed_world_features_not_stationary_hud(self):
        before=self.textured_map()
        after=cv2.warpAffine(before,cv2.getRotationMatrix2D((500,250),0,.5),(1000,600))
        result=compare_home_zoom(before,after)
        self.assertTrue(result['verified_zoom'],result)
        self.assertAlmostEqual(result['scale'],.5,delta=.02)
        self.assertFalse(result['battlefield_mapping_ready'])
        self.assertNotIn('verified',result)
        # An unchanged resource HUD cannot certify a changed or blank village.
        hud=np.random.default_rng(4).integers(0,255,(400,200,3),dtype=np.uint8)
        before[:]=after[:]=0
        before[20:420,800:]=after[20:420,800:]=hud
        self.assertFalse(compare_home_zoom(before,after)['verified_zoom'])


class HomeZoomGuardTests(TestCase):
    def test_non_home_or_overlay_never_opens_touch_transport(self):
        from coc_bot.control.diagnostics import DebugSession
        from coc_bot.vision.screens import ScreenType
        session = DebugSession.__new__(DebugSession)
        session.capture = Mock()
        session.capture.screenshot.return_value = np.zeros((600,1000,3), np.uint8)
        session.classifier = Mock()
        for screen, build, popup in [(ScreenType.BATTLE, True, False),
                                     (ScreenType.HOME, False, False),
                                     (ScreenType.HOME, True, True)]:
            session.classifier.classify.return_value = screen
            session.classifier.looks_like_blocking_popup.return_value = popup
            with patch('coc_bot.vision.battle_menu.home_build_control_visible', return_value=build), \
                 patch('coc_bot.adb.multitouch.Multitouch') as transport:
                with self.assertRaisesRegex(ValueError, 'home village'):
                    session.test_home_zoom_out()
                transport.assert_not_called()

    def test_mismatched_input_dimensions_block_gesture(self):
        from coc_bot.control.diagnostics import DebugSession
        from coc_bot.vision.screens import ScreenType
        session = DebugSession.__new__(DebugSession)
        session.capture = Mock()
        session.capture.screenshot.return_value = np.zeros((600,1000,3), np.uint8)
        session.classifier = Mock()
        session.classifier.classify.return_value = ScreenType.HOME
        session.classifier.looks_like_blocking_popup.return_value = False
        session.client = Mock()
        session.client.wm_size.return_value = (500,300)
        with patch('coc_bot.vision.battle_menu.home_build_control_visible', return_value=True), \
             patch('coc_bot.adb.multitouch.Multitouch') as transport:
            with self.assertRaisesRegex(ValueError, 'dimensions'):
                session.test_home_zoom_out()
            transport.assert_not_called()
