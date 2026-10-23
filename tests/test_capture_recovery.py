"""Renderer recovery owns inputs, honors Stop, and never guesses from ICE errors."""
from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

import numpy as np

from coc_bot.adb.client import AdbError, AdbStopped
from coc_bot.adb import capture_coordinator as captures
from coc_bot.control.capture_recovery import CaptureRecovery
from coc_bot.control.platform import Platform
from coc_bot.control.service import ControlService, BusyError


class CaptureFailureTests(TestCase):
    def tearDown(self):
        captures.set_failure_listener(None)
        captures.capture_succeeded('capture-test')

    def test_three_failures_trigger_and_a_good_frame_resets(self):
        listener=MagicMock();captures.set_failure_listener(listener)
        captures.capture_failed('capture-test');captures.capture_failed('capture-test')
        listener.assert_not_called()
        captures.publish_frame('capture-test',np.zeros((2,2,3),np.uint8))
        captures.capture_failed('capture-test');captures.capture_failed('capture-test')
        listener.assert_not_called()
        captures.capture_failed('capture-test');listener.assert_called_once_with('capture-test')

    def test_stops_and_observation_misses_do_not_count_as_capture_failure(self):
        class Source:
            client=SimpleNamespace(device='capture-test',stop_check=None)
            @captures.serialized_capture
            def screenshot(self,timeout_seconds=1): raise AdbStopped('Stop')
            @captures.serialized_capture
            def observe(self,timeout_seconds=1): raise AdbError('Optional sample failed')
        listener=MagicMock();captures.set_failure_listener(listener)
        for _ in range(4):
            with self.assertRaises(AdbStopped): Source().screenshot()
            with self.assertRaises(AdbError): Source().observe()
        listener.assert_not_called()

    def test_listener_failure_does_not_replace_capture_error(self):
        captures.set_failure_listener(MagicMock(side_effect=ValueError('Unreadable settings')))
        for _ in range(3):captures.capture_failed('capture-test')


class CaptureRecoveryTests(TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.config=SimpleNamespace(adb_device='test-device',data_dir=Path(self.temp.name))
        self.service=ControlService()
        self.service.platform=Platform();self.service.platform.update('ready','Ready',ready=True)
        self.state=SimpleNamespace(active=True,stop_requested=False,closing=False)
        self.service.operation='bot'
        self.service.controller=SimpleNamespace(stop=MagicMock(),wait=MagicMock(return_value=True),
            start=MagicMock(return_value=True),options=object(),snapshot=lambda:self.state)
        self.recovery=self.service.capture_recovery

    def test_restart_owns_stop_then_releases_before_startup_and_preserves_options(self):
        trace=[]
        @contextmanager
        def lease(device):
            trace.append('lease');yield;trace.append('released')
        def request(action,**kwargs):
            self.assertEqual(trace[-1],'lease');trace.append('host-stop')
        def prepare(**kwargs):
            self.assertEqual(trace[-1],'released')
            self.assertEqual(kwargs,{'skip_updates':True})
            self.service.platform.update('ready','Recovered',ready=True)
        with patch('coc_bot.runtime.device_lease.DeviceLease',lease),patch.object(self.recovery,'_probe',return_value=True),\
             patch('coc_bot.host_bridge.request',side_effect=request),patch.object(self.service.platform,'prepare',side_effect=prepare):
            self.recovery._run(self.config,True,self.service.controller.options)
        self.assertEqual(trace,['lease','host-stop','released'])
        self.service.controller.start.assert_called_once_with(self.service.controller.options)
        self.assertEqual(len(json.loads((self.config.data_dir/'runtime/renderer-recovery.json').read_text())['attempts']),1)

    def test_transient_capture_recovers_without_restart_or_spending(self):
        with patch('coc_bot.runtime.device_lease.DeviceLease'),patch.object(self.recovery,'_probe',return_value=False),\
             patch('coc_bot.host_bridge.request') as request:
            self.recovery._run(self.config,True,self.service.controller.options)
        request.assert_not_called();self.service.controller.start.assert_called_once()
        self.assertFalse((self.config.data_dir/'runtime/renderer-recovery.json').exists())

    def test_stop_during_restart_never_prepares_or_resumes(self):
        with patch('coc_bot.runtime.device_lease.DeviceLease'),patch.object(self.recovery,'_probe',return_value=True),\
             patch('coc_bot.host_bridge.request',side_effect=lambda *a,**k:self.service.stop()),\
             patch.object(self.service.platform,'prepare') as prepare:
            self.recovery._run(self.config,True,self.service.controller.options)
        prepare.assert_not_called();self.service.controller.start.assert_not_called()
        self.assertIn('canceled',self.service.platform.snapshot()['error'])

    def test_busy_owner_or_unconfirmed_freeze_never_restarts(self):
        for error in (BusyError('Other owner'),RuntimeError('Renderer responded')):
            with patch('coc_bot.runtime.device_lease.DeviceLease'),patch.object(self.recovery,'_probe',side_effect=error),\
                 patch('coc_bot.host_bridge.request') as request:
                self.recovery._run(self.config,True,self.service.controller.options)
            request.assert_not_called();self.service.controller.start.assert_not_called()

    def test_restart_limit_survives_new_recovery_object_and_corruption_blocks(self):
        self.recovery._reserve_restart(self.config);self.recovery._reserve_restart(self.config)
        with self.assertRaisesRegex(RuntimeError,'limit reached'):
            CaptureRecovery(self.service)._reserve_restart(self.config)
        path=self.config.data_dir/'runtime/renderer-recovery.json';path.write_text('')
        with self.assertRaisesRegex(RuntimeError,'history needs review'):
            self.recovery._reserve_restart(self.config)
        self.assertEqual(path.read_text(),'')

    def test_probe_requires_shell_response_and_renderer_timeout(self):
        with patch('coc_bot.adb.client.AdbClient') as client,patch('coc_bot.adb.capture.ScreenCapture') as capture:
            capture.return_value.screenshot.side_effect=AdbError('capture timeout')
            client.return_value.run_shell.side_effect=[SimpleNamespace(stdout='coc-render-probe\n'),AdbError('ADB command timed out')]
            self.assertTrue(self.recovery._probe(self.config))
            client.return_value.run_shell.side_effect=[SimpleNamespace(stdout='coc-render-probe\n'),SimpleNamespace(stdout='Game layers')]
            with self.assertRaisesRegex(RuntimeError,'renderer responded'):self.recovery._probe(self.config)
            client.return_value.run_shell.side_effect=[AdbError('ADB offline')]
            with self.assertRaises(AdbError):self.recovery._probe(self.config)

    def test_single_recovery_blocks_tools_and_stop_prevents_retry(self):
        entered,release=threading.Event(),threading.Event()
        def work(*args):entered.set();release.wait(3)
        with patch('coc_bot.config.load_config',return_value=self.config),patch.object(self.recovery,'_run',side_effect=work):
            self.recovery.request('wrong-device');self.assertIsNone(self.recovery.thread)
            self.service.manual_owner='test';self.recovery.request('test-device');self.assertIsNone(self.recovery.thread)
            self.service.manual_owner=None
            self.recovery.request('test-device');self.assertTrue(entered.wait(1));thread=self.recovery.thread
            try:
                self.recovery.request('test-device');self.assertIs(self.recovery.thread,thread)
                with self.assertRaises(BusyError):self.service.idle()
                self.service.stop();self.assertTrue(self.recovery.cancel.is_set())
            finally:release.set();thread.join(3)
        self.service.controller.start.assert_not_called()
