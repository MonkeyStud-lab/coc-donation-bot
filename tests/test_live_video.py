"""Bounded scrcpy protocol and cleanup checks without Android or optional codecs."""
import asyncio
from fractions import Fraction
import struct
import sys
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch, AsyncMock
from coc_bot.web.live import ScrcpySource


class LiveVideoTests(IsolatedAsyncioTestCase):
    def source(self, data):
        source = ScrcpySource("test-device", "unused")
        source.reader = asyncio.StreamReader()
        source.reader.feed_data(data)
        source.reader.feed_eof()
        return source

    async def test_configuration_keyframe_and_timestamp(self):
        def wire(stamp, payload):
            return struct.pack(">QI", stamp, len(payload)) + payload
        source = self.source(wire(1 << 63, b"config") + wire((1 << 62) | 1000000, b"keyframe")
                             + wire(1050000, b"next"))
        def packet(data):
            return SimpleNamespace(data=data)
        with patch.dict(sys.modules, {"av": SimpleNamespace(Packet=packet)}):
            first, second = await source.packet(), await source.packet()
        self.assertEqual(first.data, b"configkeyframe")
        self.assertEqual(first.pts, 0)
        self.assertEqual(second.data, b"next")
        self.assertEqual(second.pts, 50000)
        self.assertEqual(second.time_base, Fraction(1, 1000000))

    async def test_packet_bounds_and_truncated_stream(self):
        for size in (0, 4*1024*1024+1):
            with self.assertRaises(ValueError):
                await self.source(struct.pack(">QI", 1, size)).packet()
        with self.assertRaises(asyncio.IncompleteReadError):
            await self.source(struct.pack(">QI", 1, 5) + b"x").packet()

    async def test_close_removes_only_its_forward(self):
        source = ScrcpySource("test-device", "unused")
        source.port = "12345"
        wake_task = source.wake_task = asyncio.create_task(asyncio.sleep(1000))
        source.adb = AsyncMock()
        source.writer = SimpleNamespace(close=lambda: None, wait_closed=AsyncMock())
        await source.close()
        self.assertTrue(wake_task.cancelled())
        source.adb.assert_awaited_once_with("forward", "--remove", "tcp:12345")
        await source.close()
        self.assertEqual(source.adb.await_count, 1)

    async def test_only_matching_frozen_waydroid_is_resumed(self):
        for state, ip, expected in (("FROZEN", "192.168.240.112", 2),
                                   ("FROZEN", "192.168.240.113", 1),
                                   ("RUNNING", "192.168.240.112", 1),
                                   ("STOPPED", "", 1)):
            process = SimpleNamespace(returncode=0,
                communicate=AsyncMock(return_value=(f"Container:\t{state}\nIP address:\t{ip}\n".encode(),b"")))
            with patch("coc_bot.web.live.shutil.which", return_value="/usr/bin/tool"), patch(
                    "coc_bot.web.live.asyncio.create_subprocess_exec", new=AsyncMock(return_value=process)) as command:
                await ScrcpySource("192.168.240.112:5555", "unused").wake_waydroid()
                self.assertEqual(command.await_count, expected)
                if expected == 2:
                    self.assertIn("id.waydro.ContainerManager.Unfreeze", command.call_args.args)
