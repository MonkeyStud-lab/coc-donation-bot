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
        self.handle = None

    def __enter__(self):
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
