"""Recover an interrupted two-file calibration restore before loading config."""
import json
import os
import shutil
import threading
import time
from functools import wraps
from pathlib import Path

_lock = threading.RLock()
_held = threading.local()


def calibration_locked(method):
    @wraps(method)
    def guarded(*args, **kwargs):
        from coc_bot.runtime.device_lease import DeviceLease, DeviceBusy
        from coc_bot.config import project_root
        # All config reads and restores share the same lock, including across GUIs.
        with _lock:
            identity = str(project_root().resolve())
            if getattr(_held, "identity", None) == identity:
                return method(*args, **kwargs)
            deadline = time.monotonic() + 5
            lease = DeviceLease("calibration:" + identity)
            while True:
                try:
                    lease.__enter__()
                    break
                except DeviceBusy:
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Calibration is busy in another app. Try again shortly.")
                    time.sleep(.05)
            try:
                previous = getattr(_held, "identity", None)
                _held.identity = identity
                return method(*args, **kwargs)
            finally:
                _held.identity = previous
                lease.__exit__()
    return guarded


def recover_pending_restores(data: Path):
    if not data.is_dir():
        return
    for transaction in data.glob("calibration-restore-*"):
        if not transaction.is_dir() or transaction.resolve().parent != data.resolve():
            continue
        journal = transaction / "journal.json"
        if not journal.is_file():
            continue
        state = json.loads(journal.read_text(encoding="utf-8"))
        if not state.get("committed"):
            for live_name, old_name, new_name, had_key in (
                ("templates", "old_templates", "new_templates", "had_templates"),
                ("calibrated.yaml", "old.yaml", "new.yaml", "had_yaml"),
            ):
                live, old, new = data / live_name, transaction / old_name, transaction / new_name
                if old.exists():
                    if live.exists():
                        os.replace(live, transaction / ("rejected_" + live_name))
                    os.replace(old, live)
                elif not state[had_key] and not new.exists() and live.exists():
                    os.replace(live, transaction / ("rejected_" + live_name))
        shutil.rmtree(transaction)
