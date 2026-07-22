#!/usr/bin/env python3
"""
Interactive pixel coordinate / ROI picker for calibration.

Usage:
  python3 scripts/pick_coordinates.py              # fresh ADB screenshot
  python3 scripts/pick_coordinates.py ~/coc-screenshot.png   # existing image

Note: The calibration wizard now opens this picker automatically for each
point/ROI step. This script remains for standalone use.

Controls:
  Move mouse     — live (x, y) under cursor
  Left-click     — mark a corner (2 clicks = ROI) or a point in point mode
  r              — capture a new screenshot from ADB
  c              — clear marked points
  Enter          — confirm selection
  q / Escape     — quit
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from coc_bot.adb.capture import ScreenCapture
from coc_bot.adb.client import AdbClient
from coc_bot.calibration.picker import InteractivePicker, CoordinatePicker  # noqa: F401
from coc_bot.config import load_config


def load_frame_from_adb():
    config = load_config()
    client = AdbClient(device=config.adb_device)
    client.ensure_connected()
    capture = ScreenCapture(client)
    frame = capture.screenshot()
    out = Path.home() / "coc-screenshot.png"
    cv2.imwrite(str(out), frame)
    print(f"Saved screenshot: {out} ({frame.shape[1]}x{frame.shape[0]})")
    return frame


def load_frame_from_path(path: Path):
    frame = cv2.imread(str(path))
    if frame is None:
        raise SystemExit(f"Could not load image: {path}")
    print(f"Loaded: {path} ({frame.shape[1]}x{frame.shape[0]})")
    return frame


def main() -> None:
    try:
        import tkinter as tk
    except ImportError as exc:
        raise SystemExit(
            "tkinter is required. Install with: sudo apt install python3-tk"
        ) from exc

    if len(sys.argv) > 1:
        frame = load_frame_from_path(Path(sys.argv[1]).expanduser())
        refresh_cb = None
    else:
        print("Capturing screenshot from ADB...")
        frame = load_frame_from_adb()
        refresh_cb = load_frame_from_adb

    root = tk.Tk()
    picker = InteractivePicker(
        root,
        frame,
        mode="roi",
        title="CoC Coordinate Picker",
    )
    if refresh_cb is not None:
        picker.set_refresh_callback(refresh_cb)
    print("Window opened. 2 clicks = ROI, then Confirm (Enter).\n")
    root.mainloop()
    if picker.result is not None:
        print(f"\n>>> Result: {' '.join(str(v) for v in picker.result)}\n")


if __name__ == "__main__":
    main()
