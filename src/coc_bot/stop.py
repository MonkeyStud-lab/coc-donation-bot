"""Cooperative stop checks for long-running bot actions."""

from __future__ import annotations

import time
from collections.abc import Callable


def interrupted_sleep(
    seconds: float,
    should_stop: Callable[[], bool] | None = None,
    *,
    slice_s: float = 0.15,
) -> bool:
    """
    Sleep in short slices so Stop can interrupt waits.

    Returns True if stop was requested during/after the wait.
    """
    deadline = time.monotonic() + max(0.0, float(seconds))
    while time.monotonic() < deadline:
        if should_stop and should_stop():
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(slice_s, remaining))
    return bool(should_stop and should_stop())
