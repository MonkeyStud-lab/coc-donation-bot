"""Best-effort desktop notifications (Linux notify-send)."""

from __future__ import annotations

import shutil
import subprocess


def notify(title: str, body: str = "") -> None:
    """Show a desktop notification if ``notify-send`` is available; otherwise no-op."""
    if not shutil.which("notify-send"):
        return
    cmd = ["notify-send", "--app-name=CoC Donation Bot", title]
    if body:
        cmd.append(body)
    try:
        subprocess.run(cmd, check=False, timeout=5, capture_output=True)
    except (OSError, subprocess.TimeoutExpired):
        return
