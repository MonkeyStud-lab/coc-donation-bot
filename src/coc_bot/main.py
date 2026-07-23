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
from coc_bot.attack.farmer import AttackFarmer
from coc_bot.config import load_config
from coc_bot.donation.chat_monitor import ChatMonitor, DonateRequest
from coc_bot.donation.executor import DonationExecutor
from coc_bot.donation.navigator import Navigator
from coc_bot.donation.request_parser import RequestKind
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

    def __init__(
        self,
        dry_run: bool = False,
        debug_save_frames: bool = False,
        debug: bool = False,
    ) -> None:
        self.config = load_config()
        self.config.dry_run = dry_run
        self.config.debug_save_frames = debug_save_frames
        self._debug = debug

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
        self.capture.bind_input(self.nav_input)
        self.capture.bind_input(self.donation_input)
        self.app = AppController(self.client, self.config, self.capture)
        self.matcher = TemplateMatcher(
            threshold=self.config.template_threshold,
            scale_range=self.config.scale_range,
        )
        self.navigator = Navigator(self.config, self.capture, self.nav_input, self.matcher)
        self.chat_monitor = ChatMonitor(
            self.config, self.capture, self.donation_input, self.matcher, debug=debug
        )
        self.executor = DonationExecutor(self.config, self.capture, self.donation_input, self.matcher)
        self.tracker = RuntimeTracker(self.config)
        self.break_manager = BreakManager(self.config, self.tracker, self.app, self.navigator)
        self.farmer = AttackFarmer(
            self.config, self.capture, self.nav_input, self.matcher, self.navigator
        )
        self._state = "boot"
        self._state_entered = time.monotonic()
        self._frame_count = 0
        self._last_anti_idle = time.monotonic()
        self._stop_requested = False
        self._farm_requested = False
        self._farm_fail_cooldown_until = 0.0
        self.last_screen: str = "unknown"

        # Stop button interrupts long waits (chat nav, farm, donation panel, breaks).
        stop = self.should_stop
        self.navigator.stop_check = stop
        self.farmer.stop_check = stop
        self.farmer.attack_nav.stop_check = stop
        self.executor.stop_check = stop
        self.break_manager.stop_check = stop

    def should_stop(self) -> bool:
        return self._stop_requested

    def request_stop(self) -> None:
        """Ask the bot to stop ASAP (leaves Clash running)."""
        self._stop_requested = True
        logger.info("Stop requested — interrupting current action")

    def request_farm_attack(self) -> None:
        """Queue one farm attack as soon as the loop is not mid-donation."""
        self._farm_requested = True
        logger.info("Farm attack requested — will run when not mid-donation")

    def farm_status_line(self) -> str:
        """Short status for the GUI (next auto farm / cooldown)."""
        if not self.config.farm_enabled:
            return "Farm: disabled"
        if not self.config.farm_calibrated:
            return "Farm: needs calibration (Calibration → Farm)"
        if self._farm_requested:
            return "Farm: manual attack queued"
        now = time.monotonic()
        if now < self._farm_fail_cooldown_until:
            left = int(self._farm_fail_cooldown_until - now)
            return f"Farm: retry cooldown {left // 60}m {left % 60}s"
        since = self.tracker.seconds_since_last_farm()
        interval = max(60, int(self.config.farm_interval_seconds))
        if since is None:
            return "Farm: due on next safe tick"
        remaining = max(0, int(interval - since))
        if remaining <= 0:
            return "Farm: due on next safe tick"
        return f"Farm: next auto in {remaining // 60}m {remaining % 60}s"

    def screen_status_line(self) -> str:
        """Short screen label for the GUI."""
        from coc_bot.vision.screens import screen_display_name

        return f"Screen: {screen_display_name(self.last_screen)}"

    def run(self) -> None:
        logger.info("CoC Donation Bot starting (dry_run={})", self.config.dry_run)
        self._stop_requested = False
        try:
            self.client.health_check()
        except AdbError as exc:
            logger.error("ADB health check failed: {}", exc)
            raise

        self.break_manager.resume_pending_break()
        self.tracker.start_loop_timing()

        if not self.navigator.ensure_clan_chat(has_donate_request=self._has_donate_request):
            if self._stop_requested:
                logger.info("Bot stopped")
                return
            logger.error("Could not reach clan chat on startup")
            raise RuntimeError("Could not reach clan chat on startup")

        self._set_state("scan_chat")
        self._last_anti_idle = time.monotonic()

        while not self._stop_requested:
            try:
                self._loop_tick()
            except KeyboardInterrupt:
                logger.info("Shutting down...")
                self.tracker.tick()
                break
            except AdbError as exc:
                if self._stop_requested:
                    break
                logger.error("ADB error: {} — reconnecting...", exc)
                time.sleep(3)
                self.client.ensure_connected()
            except Exception as exc:
                if self._stop_requested:
                    break
                logger.exception("Unexpected error: {}", exc)
                self._recover()
                time.sleep(2)

        self.tracker.tick()
        logger.info("Bot stopped")

    def _loop_tick(self) -> None:
        if self._stop_requested:
            return
        self._check_watchdog()
        if self._stop_requested:
            return
        self._maybe_anti_idle()
        if self._stop_requested:
            return

        if self.break_manager.check_and_break_if_needed():
            self._set_state("scan_chat")
            return

        # Farm between donation states only — never mid open_donation / donate.
        if self._maybe_run_farm():
            self.tracker.tick()
            lo, hi = self.config.scan_interval_ms
            from coc_bot.stop import interrupted_sleep

            interrupted_sleep(random.uniform(lo, hi) / 1000.0, self.should_stop)
            return

        if self._stop_requested:
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

        if self._stop_requested:
            return

        self.tracker.tick()
        lo, hi = self.config.scan_interval_ms
        from coc_bot.stop import interrupted_sleep

        interrupted_sleep(random.uniform(lo, hi) / 1000.0, self.should_stop)

    def _farm_due(self) -> bool:
        if self._farm_requested:
            return True
        if not self.config.farm_enabled:
            return False
        if not self.config.farm_calibrated:
            return False
        if time.monotonic() < self._farm_fail_cooldown_until:
            return False
        since = self.tracker.seconds_since_last_farm()
        interval = max(60, int(self.config.farm_interval_seconds))
        return since is None or since >= interval

    def _maybe_run_farm(self) -> bool:
        """Run one farm cycle if due. Returns True if farm work was attempted."""
        if self._state in ("donate", "open_donation"):
            return False
        if not self._farm_due():
            return False

        manual = self._farm_requested
        self._farm_requested = False
        if not self.config.farm_calibrated:
            logger.warning("Farm requested but calibration incomplete — skipping")
            return True
        if not manual and not self.config.farm_enabled:
            return False

        logger.info("Pausing donations for farm attack (manual={})", manual)
        self._set_state("farm")
        result = self.farmer.run_one_attack()
        if self._stop_requested:
            self._set_state("scan_chat")
            return True
        if result.success:
            self.tracker.mark_farm_success()
            self._farm_fail_cooldown_until = 0.0
        else:
            cooldown = max(60, int(self.config.farm_retry_cooldown_seconds))
            self._farm_fail_cooldown_until = time.monotonic() + cooldown
            logger.warning(
                "Farm failed ({}) — retry cooldown {}s",
                result.reason,
                cooldown,
            )
        if not self._stop_requested:
            self.navigator.ensure_clan_chat(has_donate_request=self._has_donate_request)
        self._set_state("scan_chat")
        self._last_anti_idle = time.monotonic()
        return True

    def _maybe_anti_idle(self) -> None:
        """Tiny chat-panel swipe so CoC does not disconnect for inactivity."""
        interval = max(20, int(self.config.anti_idle_seconds))
        # Jitter so the nudge is not perfectly metronomic.
        due = interval + random.uniform(-8, 8)
        if time.monotonic() - self._last_anti_idle < due:
            return
        # Don't interrupt donation taps / panel opens.
        if self._state in ("donate", "open_donation"):
            return

        w = self.config.frame_width or 1853
        h = self.config.frame_height or 1048
        if "chat_panel" in self.config.rois:
            from coc_bot.vision.rois import ROI, roi_center

            cx, cy = roi_center(ROI(*self.config.rois["chat_panel"]), w, h)
        else:
            cx, cy = int(w * 0.32), int(h * 0.55)

        dist = random.randint(45, 90)
        logger.debug("Anti-idle nudge at ({}, {})", cx, cy)
        self.nav_input.swipe(cx, cy + dist // 2, cx, cy - dist // 2, duration_ms=200)
        time.sleep(0.12)
        self.nav_input.swipe(cx, cy - dist // 2, cx, cy + dist // 2, duration_ms=200)
        self._last_anti_idle = time.monotonic()

    def _should_handle_request(self, request: DonateRequest) -> bool:
        if request.kind == RequestKind.SPECIFIC:
            return True
        # Open and hybrid use simple colored-slot fill when enabled.
        return self.config.donate_open_requests

    def _has_donate_request(self, frame) -> bool:
        request = self.chat_monitor.find_donate_request(frame)
        return request is not None and self._should_handle_request(request)

    def _ensure_chat_open(self, frame=None) -> bool:
        """
        Re-open clan chat if the user closed it or we drifted to home/unknown.

        The scan/scroll loop alone never calls ensure_clan_chat, so closing chat
        manually used to leave the bot stuck looking for Donate forever.
        """
        if frame is None:
            frame = self.capture.screenshot()
        screen = ScreenClassifier(self.config, self.matcher).classify(frame)
        self.last_screen = screen.value
        if screen in (ScreenType.CLAN_CHAT, ScreenType.DONATION_PANEL):
            return True
        if screen == ScreenType.LOADING:
            return False

        logger.info("Chat not open (screen={}) — reopening clan chat", screen.value)
        ok = self.navigator.ensure_clan_chat(has_donate_request=self._has_donate_request)
        if not ok:
            logger.warning("Could not reopen clan chat")
        return ok

    def _do_scan_chat(self) -> None:
        frame = self.capture.screenshot()
        self._maybe_save_debug(frame, "scan")

        if not self._ensure_chat_open(frame):
            self._set_state("scan_chat")
            return

        # Re-capture after a possible reopen so Donate search uses a fresh frame.
        frame = self.capture.screenshot()
        request = self.chat_monitor.find_donate_request(frame)
        if request is None:
            self._set_state("scroll_chat")
            return

        if not self._should_handle_request(request):
            logger.info(
                "Skipping {} request — only specific requests are enabled",
                request.kind.value,
            )
            self.chat_monitor.mark_handled(request)
            return

        self._pending_request = request
        self._set_state("open_donation")

    def _do_scroll_chat(self) -> None:
        frame = self.capture.screenshot()
        if not self._ensure_chat_open(frame):
            self._set_state("scan_chat")
            return

        frame = self.capture.screenshot()
        request = self.chat_monitor.find_donate_request(frame)
        if request is not None:
            if not self._should_handle_request(request):
                logger.info(
                    "Skipping {} request — only specific requests are enabled",
                    request.kind.value,
                )
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
            self._set_state("donate")
            return

        classifier = ScreenClassifier(self.config, self.matcher)
        opened = False
        for attempt in range(2):
            if self._stop_requested:
                return
            self.chat_monitor.open_donation(self._pending_request)
            if classifier.wait_for_donation_panel(
                self.capture,
                timeout_seconds=self.config.donation_panel_wait_seconds,
                should_stop=self.should_stop,
            ):
                opened = True
                break
            if self._stop_requested:
                return
            logger.warning(
                "Donation panel did not appear after tapping Donate (attempt {})",
                attempt + 1,
            )
            from coc_bot.stop import interrupted_sleep

            if interrupted_sleep(0.4, self.should_stop):
                return

        if self._stop_requested:
            return

        if not opened:
            logger.warning(
                "Donation panel still not detected — leaving request unmarked so it can retry. "
                "If this keeps happening, recalibrate donation_troop_bar / donation_spell_bar "
                "or capture a donation_panel template."
            )
            self._pending_request = None
            self._set_state("scroll_chat")
            return

        from coc_bot.stop import interrupted_sleep

        if interrupted_sleep(0.3, self.should_stop):
            return
        self._set_state("donate")

    def _do_donate(self) -> None:
        if self._stop_requested:
            return
        request = getattr(self, "_pending_request", None)
        if request is None:
            self._set_state("scan_chat")
            return
        if self.config.dry_run:
            frame = self.capture.screenshot()
            self._maybe_save_debug(frame, "donate_dry_run")
            logger.info(
                "[DRY-RUN] Would execute donation kind={} (open fill=colored slots)",
                request.kind.value,
            )
            self._pending_request = None
            self._set_state("scan_chat")
            return

        donated = self.executor.donate_for_request(
            is_specific=request.is_specific,
            kind=request.kind,
            capacity=request.capacity,
        )
        logger.info("Donation round complete (donated={})", donated)
        if not donated:
            logger.info(
                "No donation made — marking request handled to avoid reopening "
                "(likely open/generic misclassified or already filled)"
            )
            self.chat_monitor.mark_handled(request)
        self._pending_request = None
        self._set_state("scan_chat")

    def _recover(self) -> None:
        logger.info("Running recovery sequence")
        self.nav_input.back()
        time.sleep(0.5)
        self.navigator.ensure_clan_chat(has_donate_request=self._has_donate_request)
        self._set_state("scan_chat")

    def _check_watchdog(self) -> None:
        # Farm battles routinely exceed state_watchdog_seconds.
        if self._state == "farm":
            return
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
    parser.add_argument(
        "--no-gui",
        action="store_true",
        help="Run the bot in the terminal only (no control window)",
    )
    args = parser.parse_args()

    setup_logging(debug=args.debug, log_file=Path("data") / "bot.log")

    if args.no_gui:
        bot = DonationBot(
            dry_run=args.dry_run,
            debug_save_frames=args.debug_save_frames,
            debug=args.debug,
        )
        try:
            bot.run()
        except (AdbError, RuntimeError) as exc:
            logger.error("{}", exc)
            sys.exit(1)
        return

    from coc_bot.gui.app import run_gui

    run_gui(
        dry_run=args.dry_run,
        debug_save_frames=args.debug_save_frames,
        debug=args.debug,
    )


if __name__ == "__main__":
    main()
