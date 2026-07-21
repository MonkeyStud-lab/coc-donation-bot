from __future__ import annotations

import argparse
import random
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2
from loguru import logger

from coc_bot.adb.app import AppController
from coc_bot.adb.capture import ScreenCapture
from coc_bot.adb.client import AdbClient, AdbError
from coc_bot.adb.input import InputController
from coc_bot.config import load_config
from coc_bot.donation.chat_monitor import ChatMonitor
from coc_bot.donation.executor import DonationExecutor
from coc_bot.donation.navigator import Navigator
from coc_bot.logging_utils import setup_logging
from coc_bot.runtime.breaks import BreakManager
from coc_bot.runtime.tracker import RuntimeTracker
from coc_bot.vision.matcher import TemplateMatcher
from coc_bot.vision.screens import ScreenClassifier, ScreenType


class DonationBot:
    """Main donation loop orchestrator."""

    WATCHDOG_STATES = {
        "ensure_chat",
        "scan_chat",
        "open_donation",
        "donate",
        "close_panel",
    }

    def __init__(self, dry_run: bool = False, debug_save_frames: bool = False) -> None:
        self.config = load_config()
        self.config.dry_run = dry_run
        self.config.debug_save_frames = debug_save_frames

        if not self.config.calibrated:
            logger.error("Calibration not found. Run: python scripts/calibrate.py")
            sys.exit(1)

        self.client = AdbClient(device=self.config.adb_device)
        self.capture = ScreenCapture(self.client)
        # Navigation must always tap (even in dry-run) so the bot can reach clan chat.
        self.nav_input = InputController(
            self.client,
            jitter_px=self.config.tap_jitter_px,
            delay_ms=self.config.action_delay_ms,
            dry_run=False,
        )
        self.donation_input = InputController(
            self.client,
            jitter_px=self.config.tap_jitter_px,
            delay_ms=self.config.action_delay_ms,
            dry_run=dry_run,
        )
        self.app = AppController(self.client, self.config, self.capture)
        self.matcher = TemplateMatcher(
            threshold=self.config.template_threshold,
            scale_range=self.config.scale_range,
        )
        self.navigator = Navigator(self.config, self.capture, self.nav_input, self.matcher)
        self.chat_monitor = ChatMonitor(self.config, self.capture, self.donation_input, self.matcher)
        self.executor = DonationExecutor(self.config, self.capture, self.donation_input, self.matcher)
        self.tracker = RuntimeTracker(self.config)
        self.break_manager = BreakManager(self.config, self.tracker, self.app, self.navigator)
        self._state = "boot"
        self._state_entered = time.monotonic()
        self._frame_count = 0

    def run(self) -> None:
        logger.info("CoC Donation Bot starting (dry_run={})", self.config.dry_run)
        try:
            self.client.health_check()
        except AdbError as exc:
            logger.error("ADB health check failed: {}", exc)
            sys.exit(1)

        self.break_manager.resume_pending_break()
        self.tracker.start_loop_timing()

        if not self.navigator.ensure_clan_chat(has_donate_request=self._has_donate_request):
            logger.error("Could not reach clan chat on startup")
            sys.exit(1)

        self._set_state("scan_chat")

        while True:
            try:
                self._loop_tick()
            except KeyboardInterrupt:
                logger.info("Shutting down...")
                self.tracker.tick()
                break
            except AdbError as exc:
                logger.error("ADB error: {} — reconnecting...", exc)
                time.sleep(3)
                self.client.ensure_connected()
            except Exception as exc:
                logger.exception("Unexpected error: {}", exc)
                self._recover()
                time.sleep(2)

    def _loop_tick(self) -> None:
        self._check_watchdog()

        if self.break_manager.check_and_break_if_needed():
            self._set_state("scan_chat")
            return

        if self._state == "scan_chat":
            self._do_scan_chat()
        elif self._state == "scroll_chat":
            self._do_scroll_chat()
        elif self._state == "open_donation":
            self._do_open_donation()
        elif self._state == "donate":
            self._do_donate()
        else:
            self._set_state("scan_chat")

        self.tracker.tick()
        lo, hi = self.config.scan_interval_ms
        time.sleep(random.uniform(lo, hi) / 1000.0)

    def _should_handle_request(self, request) -> bool:
        return request.is_specific or self.config.donate_open_requests

    def _has_donate_request(self, frame) -> bool:
        request = self.chat_monitor.find_donate_request(frame)
        return request is not None and self._should_handle_request(request)

    def _do_scan_chat(self) -> None:
        frame = self.capture.screenshot()
        self._maybe_save_debug(frame, "scan")

        request = self.chat_monitor.find_donate_request(frame)
        if request is None:
            self._set_state("scroll_chat")
            return

        if not self._should_handle_request(request):
            logger.info("Skipping open/generic request — only specific requests are enabled")
            self.chat_monitor.mark_handled(request)
            return

        self._pending_request = request
        self._set_state("open_donation")

    def _do_scroll_chat(self) -> None:
        frame = self.capture.screenshot()
        request = self.chat_monitor.find_donate_request(frame)
        if request is not None:
            if not self._should_handle_request(request):
                logger.info("Skipping open/generic request — only specific requests are enabled")
                self.chat_monitor.mark_handled(request)
            else:
                self._pending_request = request
                self._set_state("open_donation")
            return
        self.navigator.seek_donation_requests_step(frame, self._has_donate_request)
        self._set_state("scan_chat")

    def _do_open_donation(self) -> None:
        if not hasattr(self, "_pending_request"):
            self._set_state("scan_chat")
            return
        if self.config.dry_run:
            m = self._pending_request.button_match
            logger.info(
                "[DRY-RUN] Would tap Donate at ({}, {}), conf={:.2f}",
                m.center[0],
                m.center[1],
                m.confidence,
            )
        else:
            self.chat_monitor.open_donation(self._pending_request)
        classifier = ScreenClassifier(self.config, self.matcher)
        if not classifier.wait_for_donation_panel(
            self.capture, timeout_seconds=self.config.donation_panel_wait_seconds
        ):
            logger.warning("Donation panel did not appear after tapping Donate")
        time.sleep(0.3)
        self._set_state("donate")

    def _do_donate(self) -> None:
        if self.config.dry_run:
            frame = self.capture.screenshot()
            self._maybe_save_debug(frame, "donate_dry_run")
            logger.info("[DRY-RUN] Would execute donation")
            self._set_state("scan_chat")
            return

        donated = self.executor.donate_for_request(
            is_specific=self._pending_request.is_specific,
        )
        logger.info("Donation round complete (donated={})", donated)
        self._set_state("scan_chat")

    def _recover(self) -> None:
        logger.info("Running recovery sequence")
        self.nav_input.back()
        time.sleep(0.5)
        self.navigator.ensure_clan_chat(has_donate_request=self._has_donate_request)
        self._set_state("scan_chat")

    def _check_watchdog(self) -> None:
        elapsed = time.monotonic() - self._state_entered
        if elapsed > self.config.state_watchdog_seconds:
            logger.warning("Watchdog timeout in state '{}' ({:.0f}s)", self._state, elapsed)
            self._recover()

    def _set_state(self, state: str) -> None:
        if state != self._state:
            logger.debug("State: {} -> {}", self._state, state)
        self._state = state
        self._state_entered = time.monotonic()

    def _maybe_save_debug(self, frame, label: str) -> None:
        if not self.config.debug_save_frames:
            return
        self._frame_count += 1
        debug_dir = self.config.data_dir / "debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = debug_dir / f"{ts}_{label}_{self._frame_count:04d}.png"
        cv2.imwrite(str(path), frame)


def main() -> None:
    parser = argparse.ArgumentParser(description="CoC Donation Bot (educational)")
    parser.add_argument("--dry-run", action="store_true", help="Skip donate taps; navigation still runs")
    parser.add_argument("--debug-save-frames", action="store_true", help="Save debug screenshots")
    parser.add_argument("--debug", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    setup_logging(debug=args.debug, log_file=Path("data") / "bot.log")
    bot = DonationBot(dry_run=args.dry_run, debug_save_frames=args.debug_save_frames)
    bot.run()


if __name__ == "__main__":
    main()
