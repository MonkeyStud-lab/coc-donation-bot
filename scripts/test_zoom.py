#!/usr/bin/env python3
"""Try zoom-out on the connected Waydroid/ADB device and print diagnostics."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from coc_bot.adb.capture import ScreenCapture
from coc_bot.adb.client import AdbClient
from coc_bot.adb.pinch import discover_touch_device, zoom_out
from coc_bot.config import load_config
from coc_bot.logging_utils import setup_logging


def main() -> int:
    setup_logging(debug=True)
    config = load_config()
    client = AdbClient(device=config.adb_device)
    client.health_check()

    print("Note: Waydroid does not support adb root; zoom uses waydroid shell if needed.")

    device = discover_touch_device(client)
    if device:
        print(f"Touch device: {device.path} ({device.name}) abs={device.max_x}x{device.max_y}")
    else:
        print("Touch device: NONE FOUND")
        print("Raw getevent -pl (first 80 lines):")
        out = client.run_shell("getevent -pl 2>/dev/null | head -n 80", check=False)
        print(out.stdout or out.stderr)

    frame = ScreenCapture(client).screenshot()
    h, w = frame.shape[:2]
    print(f"Screenshot: {w}x{h}")
    print("Sending pinch zoom-out…")
    result = zoom_out(client, w, h, repeats=3)
    print(f"Result: ok={result.ok} method={result.method}")
    print(f"Detail: {result.detail}")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
