from __future__ import annotations

import time

import cv2
import numpy as np
from loguru import logger

from coc_bot.adb.input import InputController
from coc_bot.adb.capture import ScreenCapture
from coc_bot.config import BotConfig
from coc_bot.vision.matcher import MatchResult, TemplateMatcher
from coc_bot.vision.rois import ROI, roi_center
from coc_bot.vision.screens import ScreenClassifier, ScreenType


class Navigator:
    """Navigate to clan chat and manage UI transitions."""

    def __init__(
        self,
        config: BotConfig,
        capture: ScreenCapture,
        input_ctrl: InputController,
        matcher: TemplateMatcher | None = None,
    ) -> None:
        self.config = config
        self.capture = capture
        self.input = input_ctrl
        self.matcher = matcher or TemplateMatcher(threshold=config.template_threshold)
        self.classifier = ScreenClassifier(config, self.matcher)
        self._template_cache: dict[str, np.ndarray] = {}

    def load_template(self, key: str) -> np.ndarray | None:
        if key in self._template_cache:
            return self._template_cache[key]
        rel = self.config.templates.get(key)
        if not rel:
            return None
        path = self.config.templates_dir / rel
        if not path.exists():
            return None
        img = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if img is not None:
            self._template_cache[key] = img
        return img

    def ensure_clan_chat(self, timeout: float | None = None) -> bool:
        timeout = timeout or self.config.state_watchdog_seconds
        deadline = time.time() + timeout

        close_streak = 0

        while time.time() < deadline:
            frame = self.capture.screenshot()
            screen = self.classifier.classify(frame)
            logger.debug("ensure_clan_chat: detected screen={}", screen.value)

            if screen == ScreenType.DONATION_PANEL:
                before = screen
                self.close_donation_panel(frame)
                after = self.classifier.classify(self.capture.screenshot())
                if after == before:
                    close_streak += 1
                else:
                    close_streak = 0
                if close_streak >= 3:
                    logger.warning("Stuck in donation-panel close loop — opening clan chat instead")
                    self._open_clan_chat(self.capture.screenshot())
                    close_streak = 0
                    time.sleep(1.0)
                continue

            close_streak = 0

            if screen == ScreenType.POPUP:
                self._dismiss_popup(frame)
                continue

            if screen == ScreenType.CLAN_CHAT:
                self.navigate_to_donation_requests(frame)
                return True

            if screen == ScreenType.HOME or screen == ScreenType.UNKNOWN:
                logger.info("Not in clan chat (screen={}) — opening chat", screen.value)
                self._open_clan_chat(frame)
                time.sleep(1.0)
                continue

            if screen == ScreenType.LOADING:
                time.sleep(2.0)
                continue

        logger.warning("Failed to reach clan chat within timeout")
        return False

    def _open_clan_chat(self, frame: np.ndarray) -> None:
        h, w = frame.shape[:2]
        point = self.config.tap_points.get("open_chat")
        if point:
            logger.info("Opening clan chat via tap point ({}, {})", point[0], point[1])
            self.input.tap(point[0], point[1])
            return
        template = self.load_template("open_chat")
        if template is not None:
            match = self.matcher.find(frame, template)
            if match:
                cx, cy = match.center
                logger.info(
                    "Opening clan chat via template at ({}, {}), conf={:.2f}",
                    cx,
                    cy,
                    match.confidence,
                )
                self.input.tap(cx, cy)
                return
            logger.warning(
                "open_chat template saved but not found on screen — recalibrate tap point on home screen"
            )
        else:
            logger.warning("No open_chat template or tap point — using fallback position")

        fx, fy = int(w * 0.08), int(h * 0.45)
        logger.info("Fallback tap to open chat at ({}, {})", fx, fy)
        self.input.tap(fx, fy)

    def close_donation_panel(self, frame: np.ndarray | None = None) -> None:
        """Close donation panel by tapping outside it (CoC has no X button)."""
        if frame is None:
            frame = self.capture.screenshot()

        if not self.classifier.is_donation_panel(frame):
            logger.debug(
                "Skip close tap — donation panel not detected (screen={})",
                self.classifier.classify(frame).value,
            )
            return

        point = self.config.tap_points.get("tap_outside_donation") or self.config.tap_points.get(
            "close_donation"
        )
        if point:
            logger.info("Closing donation panel — tap outside at ({}, {})", point[0], point[1])
            self.input.tap(point[0], point[1])
            return

        # Fallback: tap upper chat area (usually outside the popup)
        h, w = frame.shape[:2]
        if "chat_panel" in self.config.rois:
            roi = ROI(*self.config.rois["chat_panel"])
            cx, _ = roi_center(roi, w, h)
            ty = int(h * 0.12)
            logger.warning("tap_outside_donation not calibrated — fallback tap ({}, {})", cx, ty)
            self.input.tap(cx, ty)
        else:
            logger.warning("tap_outside_donation not calibrated — using BACK")
            self.input.back()

    def _dismiss_popup(self, frame: np.ndarray) -> None:
        template = self.load_template("popup_dismiss")
        if template is not None:
            match = self.matcher.find(frame, template)
            if match:
                cx, cy = match.center
                self.input.tap(cx, cy)
                return
        self.input.back()

    def _find_in_chat_panel(self, frame: np.ndarray, template_key: str) -> MatchResult | None:
        template = self.load_template(template_key)
        if template is None:
            return None
        threshold = self.config.donate_button_threshold
        if "chat_panel" in self.config.rois:
            return self.matcher.find_in_roi(frame, template, self.config.rois["chat_panel"], threshold=threshold)
        return self.matcher.find(frame, template, threshold=threshold)

    def _find_scroll_down_indicator(self, frame: np.ndarray) -> MatchResult | None:
        return self._find_in_chat_panel(frame, "chat_scroll_down")

    def _find_request_jump_icon(self, frame: np.ndarray) -> MatchResult | None:
        return self._find_in_chat_panel(frame, "chat_request_jump")

    def _chat_swipe_center(self, frame: np.ndarray) -> tuple[int, int]:
        h, w = frame.shape[:2]
        if "chat_panel" in self.config.rois:
            roi = ROI(*self.config.rois["chat_panel"])
            return roi_center(roi, w, h)
        return w // 2, int(h * 0.65)

    def _swipe_chat_toward_bottom(self, frame: np.ndarray) -> None:
        h, w = frame.shape[:2]
        cx, cy = self._chat_swipe_center(frame)
        self.input.swipe(cx, cy, cx, cy - int(h * 0.28), duration_ms=350)

    def navigate_to_donation_requests(self, frame: np.ndarray | None = None) -> None:
        """
        Move chat view toward donation requests.

        1. Tap the exclamation-mark jump icon if visible (scrolls to next request).
        2. Otherwise tap scroll-down indicator until it disappears (= at bottom).
        """
        if frame is None:
            frame = self.capture.screenshot()

        jump = self._find_request_jump_icon(frame)
        if jump is not None:
            cx, cy = jump.center
            logger.info("Tapping donation request jump icon at ({}, {}), conf={:.2f}", cx, cy, jump.confidence)
            self.input.tap(cx, cy)
            time.sleep(0.5)
            return

        self.scroll_chat_to_bottom(frame)

    def scroll_chat_to_bottom(self, frame: np.ndarray | None = None) -> None:
        """
        Scroll to bottom of clan chat.

        At bottom when the scroll-down indicator is NO LONGER visible.
        """
        scroll_tpl = self.load_template("chat_scroll_down")
        if scroll_tpl is None:
            logger.warning("chat_scroll_down template missing — swiping chat as fallback")
            self._scroll_by_swipe_only(frame)
            return

        self._scroll_via_indicator(frame)

    def _scroll_via_indicator(self, frame: np.ndarray | None) -> None:
        max_attempts = self.config.chat_max_scroll_attempts

        for attempt in range(1, max_attempts + 1):
            if frame is None:
                frame = self.capture.screenshot()
            match = self._find_scroll_down_indicator(frame)
            if match is None:
                logger.debug("Chat at bottom (scroll-down indicator absent)")
                return

            cx, cy = match.center
            logger.info(
                "Scroll-down indicator visible — tapping ({}, {}) [{}/{}]",
                cx,
                cy,
                attempt,
                max_attempts,
            )
            self.input.tap(cx, cy)
            time.sleep(0.45)
            frame = self.capture.screenshot()

            if self._find_scroll_down_indicator(frame) is not None:
                logger.debug("Indicator still visible after tap — swiping chat")
                self._swipe_chat_toward_bottom(frame)
                time.sleep(0.35)
                frame = None

        logger.warning("Chat scroll stopped after {} attempts (indicator may still be visible)", max_attempts)

    def _scroll_by_swipe_only(self, frame: np.ndarray | None) -> None:
        if frame is None:
            frame = self.capture.screenshot()
        for _ in range(3):
            self._swipe_chat_toward_bottom(frame)
            frame = self.capture.screenshot()
