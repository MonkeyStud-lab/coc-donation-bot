#!/usr/bin/env python3
"""Save a screenshot from Waydroid via ADB (avoids shell redirect corruption)."""

import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from coc_bot.adb.capture import ScreenCapture
from coc_bot.adb.client import AdbClient, AdbError
from coc_bot.config import load_config


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "coc-screenshot.png"
    out = out.expanduser().resolve()

    config = load_config()
    device = config.adb_device
    print(f"Connecting to ADB device {device}...")
    client = AdbClient(device=device)
    try:
        client.ensure_connected()
    except AdbError as exc:
        print(f"ADB error: {exc}")
        print(f"Make sure Waydroid is running, then try: adb connect {device}")
        sys.exit(1)

    print("Capturing screen...")
    capture = ScreenCapture(client)
    try:
        frame = capture.screenshot()
    except AdbError as exc:
        print(f"Capture failed: {exc}")
        sys.exit(1)

    h, w = frame.shape[:2]
    out.parent.mkdir(parents=True, exist_ok=True)
    ok = cv2.imwrite(str(out), frame)
    if not ok:
        print(f"Failed to write image to {out}")
        sys.exit(1)

    size_kb = out.stat().st_size / 1024
    print(f"Saved: {out}")
    print(f"Size: {size_kb:.1f} KB, resolution: {w}x{h}")
    if size_kb < 10:
        print("WARNING: file is very small — capture may have failed.")


if __name__ == "__main__":
    main()
