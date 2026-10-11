"""Explicit, cancellable input ownership for live video. Coordinates are normalized."""
import asyncio
from contextlib import suppress
import math
import secrets
import threading
import time
from coc_bot.runtime.device_lease import DeviceLease


class LiveControl:
    def __init__(self, service, device):
        self.service, self.device = service, device
        self.token = None
        self.cancel = threading.Event()
        self.lease = self.session = None
        self.dimensions = None
        self.last_input = 0

    async def call(self, function, *args):
        task = asyncio.create_task(asyncio.to_thread(function, *args))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            self.cancel.set()
            with suppress(Exception):
                await task
            raise

    async def acquire(self):
        if self.token:
            raise ValueError("Live control is already enabled")
        self.cancel = threading.Event()
        with self.service.lock:
            self.service.idle()
            self.token = secrets.token_hex(16)
            self.service.manual_owner = self.token
            self.service.manual_cancel = self.cancel
        try:
            self.lease = DeviceLease(self.device)
            self.lease.__enter__()
            self.session = await self.call(self.service.session, self.cancel)
            if self.session.config.adb_device != self.device:
                raise ValueError("Device changed. Reopen Live view.")
            self.dimensions = await self.call(self.session.client.wm_size)
            if not self.dimensions or any(n <= 0 for n in self.dimensions):
                raise ValueError("Cannot determine Android input dimensions")
            if self.cancel.is_set():
                raise ValueError("Control cancelled")
            self.last_input = 0
            return self.token
        except BaseException:
            self.release()
            raise

    def release(self):
        self.cancel.set()
        if self.lease:
            self.lease.__exit__()
        with self.service.lock:
            if self.token and self.service.manual_owner == self.token:
                self.service.manual_owner = self.service.manual_cancel = None
        self.token = self.session = self.lease = None

    async def input(self, message):
        # Old queued gestures cannot acquire a new lease or survive Stop.
        if not self.token or self.cancel.is_set() or message.get("token") != self.token:
            return
        if time.monotonic() - self.last_input < .15:
            return
        def point(key):
            p = message.get(key)
            if not isinstance(p, list) or len(p) != 2 or any(
                type(n) not in (int, float) or not math.isfinite(n) or not 0 <= n <= 1 for n in p
            ):
                raise ValueError("Invalid live control coordinates")
            return [str(min(size-1, round(n*(size-1)))) for n, size in zip(p, self.dimensions)]
        command = message.get("type")
        if command == "tap":
            args = ["shell", "input", "tap", *point("from")]
        elif command == "swipe":
            args = ["shell", "input", "swipe", *point("from"), *point("to"), "300"]
        elif command == "key" and message.get("key") in ("back", "home"):
            args = ["shell", "input", "keyevent", "KEYCODE_" + message["key"].upper()]
        else:
            raise ValueError("Unsupported live control command")
        self.last_input = time.monotonic()
        await self.call(self.session.client.run, args)
