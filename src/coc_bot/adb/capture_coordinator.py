"""Serialize captures per device and share previews without extra ADB commands."""
from __future__ import annotations

import threading
import time
import inspect
from functools import wraps

_guard = threading.Lock()
_locks: dict[str, threading.Lock] = {}
_frames: dict[str, tuple[object, float]] = {}


def publish_frame(device, frame):
    with _guard:
        _frames[device] = (frame.copy(), time.monotonic())


def latest_frame(device):
    with _guard:
        snapshot = _frames.get(device)
        return (snapshot[0].copy(), time.monotonic() - snapshot[1]) if snapshot else None


def serialized_capture(method):
    default_budget = inspect.signature(method).parameters["timeout_seconds"].default
    @wraps(method)
    def capture(self, *args, **kwargs):
        from coc_bot.adb.client import AdbError, AdbStopped
        with _guard:
            lock = _locks.setdefault(self.client.device, threading.Lock())
        timeout = float(kwargs.get("timeout_seconds", args[0] if args else default_budget))
        deadline = time.monotonic() + timeout
        while not lock.acquire(timeout=min(.1, max(0, deadline - time.monotonic()))):
            if self.client.stop_check and self.client.stop_check():
                raise AdbStopped("Stop requested while waiting for capture")
            if time.monotonic() >= deadline:
                raise AdbError("Screenshot owner is busy; capture budget exhausted")
        try:
            self._deadline = deadline
            return method(self, *args, **kwargs)
        finally:
            self._deadline = None
            lock.release()
    return capture
