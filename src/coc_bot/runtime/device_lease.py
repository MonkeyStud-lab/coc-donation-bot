"""One controller per ADB serial, with OS locks released automatically on exit."""
from __future__ import annotations

import hashlib
import os
import tempfile
from functools import wraps
from pathlib import Path


class DeviceBusy(RuntimeError):
    pass


class DeviceLease:
    def __init__(self, device: str):
        name = hashlib.sha256(device.encode()).hexdigest()
        self.device = device
        self.path = Path(tempfile.gettempdir()) / f"coc-bot-device-{name}.lock"
        if os.environ.get("COC_HOST_SOCKET") and device.startswith("calibration:"):
            # Shared profile storage synchronizes container edits with host backups.
            self.path = Path(device.removeprefix("calibration:")) / "data/.calibration.lock"
        self.handle = None
        self.bridge = None

    def __enter__(self):
        if os.environ.get("COC_HOST_SOCKET") and not self.device.startswith(("web-server:", "calibration:")):
            from coc_bot.host_bridge import acquire_lease
            try:
                self.bridge = acquire_lease(self.device)
            except RuntimeError as exc:
                raise DeviceBusy(str(exc)) from exc
            return self
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b")
        self.handle.seek(0, os.SEEK_END)
        if self.handle.tell() == 0:
            self.handle.write(b"0")
            self.handle.flush()
        self.handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.handle.close()
            self.handle = None
            raise DeviceBusy(f"Another bot is controlling {self.device}. Stop it first.") from exc
        return self

    def __exit__(self, *args):
        if self.bridge is not None:
            from coc_bot.host_bridge import release_lease
            try:
                release_lease(self.bridge)
            finally:
                self.bridge = None
        if self.handle is not None:
            self.handle.close()
            self.handle = None
        # Never unlink the lock file: a second process may already have it open.


def exclusive_device(method):
    @wraps(method)
    def controlled(self, *args, **kwargs):
        with DeviceLease(self.config.adb_device):
            return method(self, *args, **kwargs)
    return controlled
