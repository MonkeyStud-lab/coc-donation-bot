import asyncio
import threading
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import Mock, MagicMock, patch
from coc_bot.control.service import ControlService, BusyError
from coc_bot.web.live_control import LiveControl


class LiveControlTests(IsolatedAsyncioTestCase):
    def setUp(self):
        self.client = SimpleNamespace(wm_size=lambda: (1853, 1048), run=Mock())
        self.session = SimpleNamespace(client=self.client, config=SimpleNamespace(adb_device="test"))
        self.service = ControlService()
        self.service.session = lambda cancel: self.session
        self.control = LiveControl(self.service, "test")
        self.lease = MagicMock()
        self.patch = patch("coc_bot.web.live_control.DeviceLease", return_value=self.lease)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.addCleanup(self.control.release)

    async def test_normalized_input_and_release(self):
        token = await self.control.acquire()
        with self.assertRaises(BusyError):
            self.service.idle()
        await self.control.input({"type": "tap", "token": token, "from": [.5, 1]})
        self.client.run.assert_called_once_with(["shell", "input", "tap", "926", "1047"])
        self.control.release()
        self.service.idle()
        self.lease.__exit__.assert_called_once()

    async def test_stop_and_stale_gestures_do_not_tap(self):
        old = await self.control.acquire()
        self.service.stop()
        await self.control.input({"type": "tap", "token": old, "from": [.5, .5]})
        self.control.release()
        await self.control.acquire()
        await self.control.input({"type": "tap", "token": old, "from": [.5, .5]})
        self.client.run.assert_not_called()

    async def test_busy_bot_and_external_owner(self):
        with patch.object(self.service.controller, "snapshot", return_value=SimpleNamespace(active=True)):
            with self.assertRaises(BusyError):
                await self.control.acquire()
        self.lease.__enter__.side_effect = RuntimeError("device busy")
        with self.assertRaisesRegex(RuntimeError, "device busy"):
            await self.control.acquire()
        self.assertIsNone(self.service.manual_owner)

    async def test_invalid_coordinates_and_key(self):
        token = await self.control.acquire()
        for p in ([float('nan'), 0], [2, 0], [True, 0], "bad"):
            with self.assertRaises(ValueError):
                await self.control.input({"type": "tap", "token": token, "from": p})
        with self.assertRaises(ValueError):
            await self.control.input({"type": "key", "token": token, "key": "shell"})
        self.client.run.assert_not_called()

    async def test_cancellation_retains_lease_until_command_finishes(self):
        entered, finished = threading.Event(), threading.Event()
        def command(args):
            entered.set()
            finished.wait(2)
        self.client.run = command
        token = await self.control.acquire()
        task = asyncio.create_task(self.control.input({"type": "tap", "token": token, "from": [0, 0]}))
        await asyncio.to_thread(entered.wait, 1)
        task.cancel()
        await asyncio.sleep(.01)
        self.lease.__exit__.assert_not_called()
        finished.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.control.release()
        self.assertIsNone(self.service.manual_owner)
