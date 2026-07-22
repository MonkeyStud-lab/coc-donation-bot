"""One-shot debug actions for the GUI Debugging tab."""

from __future__ import annotations

import random
import time
from datetime import datetime

from loguru import logger

from coc_bot.adb.app import AppController
from coc_bot.adb.capture import ScreenCapture
from coc_bot.adb.client import AdbClient, AdbError
from coc_bot.adb.input import InputController
from coc_bot.config import load_config
from coc_bot.donation.chat_monitor import ChatMonitor
from coc_bot.donation.navigator import Navigator
from coc_bot.vision.matcher import TemplateMatcher
from coc_bot.vision.rois import ROI, roi_center
from coc_bot.vision.screens import ScreenClassifier


class DebugSession:
    """Shared ADB/vision helpers for manual step tests."""

    def __init__(self) -> None:
        self.config = load_config()
        self.client = AdbClient(device=self.config.adb_device)
        self.capture = ScreenCapture(self.client)
        self.input = InputController(
            self.client,
            jitter_px=self.config.tap_jitter_px,
            delay_ms=self.config.action_delay_ms,
            dry_run=False,
        )
        self.matcher = TemplateMatcher(
            threshold=self.config.template_threshold,
            scale_range=self.config.scale_range,
        )
        self.classifier = ScreenClassifier(self.config, self.matcher)
        self.navigator = Navigator(self.config, self.capture, self.input, self.matcher)
        self.chat_monitor = ChatMonitor(
            self.config, self.capture, self.input, self.matcher, debug=True
        )
        self.app = AppController(self.client, self.config, self.capture)

    def health_check(self) -> str:
        self.client.health_check()
        return f"ADB OK — device {self.config.adb_device}"

    def classify_screen(self) -> str:
        frame = self.capture.screenshot()
        screen = self.classifier.classify(frame)
        return f"Current screen: {screen.value}"

    def open_clan_chat(self) -> str:
        ok = self.navigator.ensure_clan_chat(
            has_donate_request=lambda f: self.chat_monitor.find_donate_request(f) is not None
        )
        if ok:
            return "Clan chat is open (or was already open)."
        return "Failed to open clan chat — check calibration / that CoC is visible."

    def find_and_classify_request(self) -> str:
        frame = self.capture.screenshot()
        request = self.chat_monitor.find_donate_request(frame)
        if request is None:
            return "No Donate request found on the current screen."
        return (
            f"Found request: kind={request.kind.value}, "
            f"is_specific={request.is_specific}, "
            f"button={request.button_match.center}, "
            f"conf={request.button_match.confidence:.2f}"
        )

    def open_donation_panel(self) -> str:
        frame = self.capture.screenshot()
        request = self.chat_monitor.find_donate_request(frame)
        if request is None:
            return "No Donate button found — open clan chat and ensure a request is visible."
        self.chat_monitor.open_donation(request)
        ok = self.classifier.wait_for_donation_panel(
            self.capture, timeout_seconds=self.config.donation_panel_wait_seconds
        )
        if ok:
            return (
                f"Opened donation panel for kind={request.kind.value} "
                f"(specific={request.is_specific})."
            )
        return "Tapped Donate but donation panel was not detected."

    def close_donation_panel(self) -> str:
        self.navigator.close_donation_panel()
        time.sleep(0.4)
        screen = self.classifier.classify(self.capture.screenshot())
        return f"Close donation attempted — screen now: {screen.value}"

    def scroll_chat_step(self) -> str:
        frame = self.capture.screenshot()
        self.navigator.seek_donation_requests_step(
            frame,
            has_donate_request=lambda f: self.chat_monitor.find_donate_request(f) is not None,
        )
        return "Performed one chat seek/scroll step."

    def anti_idle_nudge(self) -> str:
        frame = self.capture.screenshot()
        h, w = frame.shape[:2]
        if "chat_panel" in self.config.rois:
            cx, cy = roi_center(ROI(*self.config.rois["chat_panel"]), w, h)
        else:
            cx, cy = int(w * 0.32), int(h * 0.55)
        dist = random.randint(45, 90)
        self.input.swipe(cx, cy + dist // 2, cx, cy - dist // 2, duration_ms=200)
        time.sleep(0.12)
        self.input.swipe(cx, cy - dist // 2, cx, cy + dist // 2, duration_ms=200)
        return f"Anti-idle nudge at ({cx}, {cy})."

    def save_screenshot(self) -> str:
        frame = self.capture.screenshot()
        debug_dir = self.config.data_dir / "debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        path = debug_dir / f"gui_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        import cv2

        cv2.imwrite(str(path), frame)
        return f"Saved screenshot: {path}"

    def force_stop_coc(self) -> str:
        self.app.force_stop()
        return f"Force-stopped {self.config.coc_package}."

    def relaunch_coc(self) -> str:
        pkg = self.config.coc_package
        was_running = self.app.is_running()
        if was_running:
            logger.info("Clash already running — force-stopping before relaunch")
            self.app.force_stop()
            time.sleep(2.0)

        loading = self.navigator.load_template("loading")
        self.app.launch()
        ready = self.app.wait_until_ready(loading_template=loading)
        running = self.app.is_running()
        if ready and running:
            return "Clash relaunched and appears loaded."
        if running and not ready:
            return (
                "Clash process is running but load wait timed out "
                "(optional loading template / slow start). Check the game window."
            )
        return (
            "Clash did not start. Try opening it once from Waydroid manually, "
            "then retry. Also check: waydroid app list | grep -i clash"
        )

    def break_cycle_short(self, wait_seconds: int = 8) -> str:
        """Simulate take-a-break: force-stop, wait, relaunch, reopen chat."""
        logger.info("Debug break cycle — force-stop, wait {}s, relaunch", wait_seconds)
        self.app.force_stop()
        time.sleep(max(3, wait_seconds))
        loading = self.navigator.load_template("loading")
        self.app.launch()
        self.app.wait_until_ready(loading_template=loading)
        ok = self.navigator.ensure_clan_chat(
            has_donate_request=lambda f: self.chat_monitor.find_donate_request(f) is not None
        )
        if ok:
            return f"Break cycle done (waited {wait_seconds}s) — clan chat open."
        return f"Break cycle finished (waited {wait_seconds}s) but clan chat reopen failed."


DEBUG_ACTIONS: list[tuple[str, str, str]] = [
    # id, label, description
    (
        "health_check",
        "ADB health check",
        "Verify the bot can talk to Waydroid over ADB.",
    ),
    (
        "classify_screen",
        "Classify current screen",
        "Detect home / clan chat / donation panel / popup / unknown.",
    ),
    (
        "open_clan_chat",
        "Open clan chat",
        "Navigate from home (or recover) until clan chat is open.",
    ),
    (
        "find_classify_request",
        "Find + classify donation request",
        "Look for a Donate button and report specific vs open/hybrid.",
    ),
    (
        "open_donation",
        "Open a donation panel",
        "Tap the first visible Donate and wait for the donation popup.",
    ),
    (
        "close_donation",
        "Close donation panel",
        "Tap outside the donation popup to close it.",
    ),
    (
        "scroll_chat",
        "Scroll / seek chat once",
        "One step of searching chat for donation requests.",
    ),
    (
        "anti_idle",
        "Anti-idle nudge once",
        "Small swipe in the chat area (same idea as inactivity prevention).",
    ),
    (
        "save_screenshot",
        "Save screenshot",
        "Write a debug PNG under data/debug/.",
    ),
    (
        "force_stop",
        "Force-stop Clash of Clans",
        "Close the game only (Waydroid stays up). Leaves you on Android home.",
    ),
    (
        "relaunch",
        "Relaunch Clash of Clans",
        "Start CoC again and wait until it looks loaded.",
    ),
    (
        "break_cycle",
        "Test break / take-a-break cycle",
        "Force-stop CoC, wait ~8s, relaunch, reopen clan chat — simulates the "
        "session-limit break used to avoid long continuous play.",
    ),
]


def run_debug_action(action_id: str) -> str:
    session = DebugSession()
    mapping = {
        "health_check": session.health_check,
        "classify_screen": session.classify_screen,
        "open_clan_chat": session.open_clan_chat,
        "find_classify_request": session.find_and_classify_request,
        "open_donation": session.open_donation_panel,
        "close_donation": session.close_donation_panel,
        "scroll_chat": session.scroll_chat_step,
        "anti_idle": session.anti_idle_nudge,
        "save_screenshot": session.save_screenshot,
        "force_stop": session.force_stop_coc,
        "relaunch": session.relaunch_coc,
        "break_cycle": session.break_cycle_short,
    }
    fn = mapping.get(action_id)
    if fn is None:
        raise ValueError(f"Unknown debug action: {action_id}")
    try:
        return fn()
    except AdbError as exc:
        return f"ADB error: {exc}"
    except Exception as exc:  # noqa: BLE001
        logger.exception("Debug action {} failed", action_id)
        return f"Error: {exc}"
