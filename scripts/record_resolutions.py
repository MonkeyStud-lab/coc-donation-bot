#!/usr/bin/env python3
"""
Capture perception frames at extra Android resolutions (no taps).

The live donation bot is calibrated for one size. Changing `wm size` while it is
tapping would miss buttons. This script:

  1. optionally stops ``coc-record.service``
  2. sets each requested ``wm size``
  3. screenshots + classifies in a loop (FrameRecorder) for N minutes
  4. restores the original size
  5. optionally restarts the donation recorder

Usage (on the Waydroid host)::

    python scripts/record_resolutions.py --minutes 20
    python scripts/record_resolutions.py --minutes 15 --sizes 1920x1080,1280x720,1600x900
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from loguru import logger

from coc_bot.adb.app import AppController
from coc_bot.adb.capture import ScreenCapture
from coc_bot.adb.client import AdbClient, AdbError
from coc_bot.config import load_config
from coc_bot.vision.matcher import TemplateMatcher
from coc_bot.vision.recorder import FrameRecorder, config_fingerprint
from coc_bot.vision import recorder
from coc_bot.vision.screens import BotMode, ScreenClassifier

_SIZE_RE = re.compile(r"(\d+)\s*x\s*(\d+)", re.I)


def _parse_size(text: str) -> tuple[int, int]:
    m = _SIZE_RE.search(text.strip())
    if not m:
        raise ValueError(f"Not a WxH size: {text!r}")
    return int(m.group(1)), int(m.group(2))


def read_wm_size(client: AdbClient) -> tuple[tuple[int, int] | None, tuple[int, int] | None]:
    """Return (override, physical) from ``wm size``."""
    result = client.run_shell("wm size", check=False)
    text = (result.stdout or "") + "\n" + (result.stderr or "")
    override = None
    physical = None
    for line in text.splitlines():
        line = line.strip()
        if "Override size:" in line:
            override = _parse_size(line.split(":", 1)[-1])
        elif "Physical size:" in line:
            physical = _parse_size(line.split(":", 1)[-1])
    return override, physical


def set_wm_size(client: AdbClient, size: tuple[int, int] | None) -> None:
    if size is None:
        logger.info("wm size reset")
        client.run_shell("wm size reset", check=False)
        return
    spec = f"{size[0]}x{size[1]}"
    logger.info("wm size {}", spec)
    client.run_shell(f"wm size {spec}", check=False)


def wait_for_capture_size(
    capture: ScreenCapture, want: tuple[int, int], timeout: float = 40.0
) -> tuple[int, int]:
    deadline = time.time() + timeout
    last = (0, 0)
    while time.time() < deadline:
        frame = capture.screenshot()
        last = (frame.shape[1], frame.shape[0])
        if last == want:
            logger.info("Screencap is {}x{}", last[0], last[1])
            return last
        logger.info("Waiting for {}x{} (got {}x{})", want[0], want[1], last[0], last[1])
        time.sleep(2.0)
    logger.warning("Timed out waiting for {}x{} — last capture {}x{}", want[0], want[1], last[0], last[1])
    return last


def systemctl_user(*args: str) -> None:
    subprocess.run(["systemctl", "--user", *args], check=False)


def record_at_size(
    *,
    minutes: float,
    every_n: int,
    capture: ScreenCapture,
    classifier: ScreenClassifier,
    config,
    label: str,
) -> None:
    rec = FrameRecorder(
        config.data_dir / "frames",
        every_n=every_n,
        extra_meta={
            "mode": "resolution_sweep",
            "label": label,
            "calib_frame": [config.frame_width, config.frame_height],
            "calib_fingerprint": config_fingerprint(config),
            "adb_device": config.adb_device,
            "dry_run": True,
        },
    )
    recorder.start(rec)
    deadline = time.time() + max(30.0, minutes * 60.0)
    n = 0
    try:
        while time.time() < deadline:
            frame = capture.screenshot()
            classifier.classify(frame, mode=BotMode.ANY)
            n += 1
            time.sleep(1.2)
    finally:
        recorder.stop()
    logger.info("Finished {} — {} captures in this size", label, n)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--minutes", type=float, default=20.0, help="Minutes to record at each extra size")
    ap.add_argument(
        "--sizes",
        default="1920x1080,1280x720",
        help="Comma-separated WxH list (does not include the native size)",
    )
    ap.add_argument("--every", type=int, default=4, help="Save every Nth idle frame")
    ap.add_argument("--stop-bot", action="store_true", help="Stop coc-record.service before changing size")
    ap.add_argument("--restart-bot", action="store_true", help="Start coc-record.service after restore")
    args = ap.parse_args()
    sizes = [_parse_size(part) for part in args.sizes.split(",") if part.strip()]

    config = load_config()
    client = AdbClient(device=config.adb_device)
    try:
        client.ensure_connected()
    except AdbError as exc:
        logger.error("ADB: {}", exc)
        sys.exit(1)

    capture = ScreenCapture(client)
    matcher = TemplateMatcher(threshold=config.template_threshold)
    classifier = ScreenClassifier(config, matcher)
    app = AppController(client, config, capture)

    override, physical = read_wm_size(client)
    original = override or physical
    logger.info("Current wm size override={} physical={}", override, physical)

    if args.stop_bot:
        logger.info("Stopping coc-record")
        systemctl_user("stop", "coc-record")
        time.sleep(2)

    try:
        for size in sizes:
            set_wm_size(client, size)
            time.sleep(3)
            got = wait_for_capture_size(capture, size)
            try:
                app.launch()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not focus Clash: {}", exc)
            time.sleep(4)
            record_at_size(
                minutes=args.minutes,
                every_n=args.every,
                capture=capture,
                classifier=classifier,
                config=config,
                label=f"{got[0]}x{got[1]}",
            )
    finally:
        logger.info("Restoring original wm size {}", original)
        if original and original == physical and override:
            set_wm_size(client, None)
        elif original:
            set_wm_size(client, original)
        else:
            set_wm_size(client, None)
        time.sleep(3)
        wait_for_capture_size(capture, original or (1853, 1048), timeout=30.0)
        try:
            app.launch()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not refocus Clash after restore: {}", exc)

    if args.restart_bot:
        logger.info("Starting coc-record")
        systemctl_user(
            "reset-failed",
            "coc-record",
        )
        # Transient units die when stopped; recreate the donation recorder.
        subprocess.run(
            [
                "systemd-run",
                "--user",
                "--unit=coc-record",
                f"--working-directory={ROOT}",
                str(ROOT / ".venv" / "bin" / "python"),
                "-m",
                "coc_bot",
                "--no-gui",
                "--record",
                "--record-every",
                "10",
            ],
            check=False,
        )
        logger.info("coc-record restart issued")


if __name__ == "__main__":
    main()
