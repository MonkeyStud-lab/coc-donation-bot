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

        while time.time() < deadline:
            frame = self.capture.screenshot()
            screen = self.classifier.classify(frame)

            if screen == ScreenType.DONATION_PANEL:
                self._close_donation_panel(frame)
                continue

            if screen == ScreenType.POPUP:
                self._dismiss_popup(frame)
                continue

            if screen == ScreenType.CLAN_CHAT:
                self.scroll_chat_to_bottom(frame)
                return True

            if screen == ScreenType.HOME or screen == ScreenType.UNKNOWN:
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

    def _close_donation_panel(self, frame: np.ndarray) -> None:
        for key in ("panel_close", "quick_donate"):
            template = self.load_template(key)
            if template is None:
                continue
            match = self.matcher.find(frame, template)
            if match:
                cx, cy = match.center
                self.input.tap(cx, cy)
                return
        point = self.config.tap_points.get("close_donation")
        if point:
            self.input.tap(point[0], point[1])
        else:
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

    def _find_scroll_down_indicator(self, frame: np.ndarray) -> MatchResult | None:
        """Find UI element that appears when chat can still scroll toward bottom."""
        template = self.load_template("chat_scroll_down")
        if template is None:
            return None

        threshold = self.config.donate_button_threshold
        if "chat_panel" in self.config.rois:
            return self.matcher.find_in_roi(frame, template, self.config.rois["chat_panel"], threshold=threshold)

        return self.matcher.find(frame, template, threshold=threshold)

    def _chat_swipe_center(self, frame: np.ndarray) -> tuple[int, int]:
        h, w = frame.shape[:2]
        if "chat_panel" in self.config.rois:
            roi = ROI(*self.config.rois["chat_panel"])
            return roi_center(roi, w, h)
        return w // 2, int(h * 0.65)

    def _swipe_chat_toward_bottom(self, frame: np.ndarray) -> None:
        """Swipe up on the chat list to reveal newer messages at the bottom."""
        h, w = frame.shape[:2]
        cx, cy = self._chat_swipe_center(frame)
        # Finger moves up → chat content scrolls down toward newest messages
        self.input.swipe(cx, cy, cx, cy - int(h * 0.28), duration_ms=350)

    def scroll_chat_to_bottom(self, frame: np.ndarray | None = None) -> None:
        """
        Scroll clan chat to the bottom (newest messages / donation requests).

        Uses the calibrated ``chat_scroll_down`` template: an element visible only
        while the chat is not yet at the bottom. The bot taps it repeatedly until
        it disappears.
        """
        scroll_tpl = self.load_template("chat_scroll_down")
        if scroll_tpl is not None:
            self._scroll_via_indicator(frame)
            return

        logger.warning("chat_scroll_down template missing — using legacy scroll fallback")
        self._scroll_legacy(frame)

    def _scroll_via_indicator(self, frame: np.ndarray | None) -> None:
        max_attempts = self.config.chat_max_scroll_attempts

        for attempt in range(1, max_attempts + 1):
            if frame is None:
                frame = self.capture.screenshot()
            match = self._find_scroll_down_indicator(frame)
            if match is None:
                logger.debug("Chat at bottom (scroll-down indicator not visible)")
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

    def _scroll_legacy(self, frame: np.ndarray | None) -> None:
        """Fallback when chat_scroll_down template was not calibrated."""
        if frame is None:
            frame = self.capture.screenshot()

        bottom_tpl = self.load_template("chat_at_bottom")
        if bottom_tpl is not None and self.matcher.find(frame, bottom_tpl):
            return

        for _ in range(3):
            self._swipe_chat_toward_bottom(frame)
            frame = self.capture.screenshot()
            if bottom_tpl is not None and self.matcher.find(frame, bottom_tpl):
                return
