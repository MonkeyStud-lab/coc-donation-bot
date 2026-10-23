"""Serialize captures per device and share previews without extra ADB commands."""
from __future__ import annotations

import threading
import time
import inspect
from functools import wraps

_guard = threading.Lock()
_locks: dict[str, threading.Lock] = {}
_frames: dict[str, tuple[object, float]] = {}
_failures: dict[str, int] = {}
_failure_listener = None


def set_failure_listener(listener):
    """The managed dashboard installs one listener; desktop capture stays inert."""
    global _failure_listener
    with _guard:
        _failure_listener = listener


def capture_failed(device):
    with _guard:
        _failures[device] = count = _failures.get(device, 0) + 1
        listener = _failure_listener
    if count >= 3 and listener is not None:
        try:
            listener(device)
        except Exception as exc:
            from loguru import logger
            logger.warning('Capture recovery could not be scheduled: {}', exc)


def capture_succeeded(device):
    with _guard:
        _failures.pop(device, None)


def publish_frame(device, frame):
    with _guard:
        _frames[device] = (frame.copy(), time.monotonic())
        _failures.pop(device, None)


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
        except AdbStopped:
            raise
        except AdbError:
            # Owner contention and optional observation misses do not establish
            # a broken Android renderer.
            if method.__name__ == 'screenshot':
                capture_failed(self.client.device)
            raise
        finally:
            self._deadline = None
            lock.release()
    return capture
