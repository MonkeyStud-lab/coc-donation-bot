from __future__ import annotations

import time
from collections.abc import Callable

import cv2
import numpy as np
from loguru import logger

from coc_bot.adb.input import InputController
from coc_bot.adb.capture import ScreenCapture
from coc_bot.config import BotConfig
from coc_bot.vision.matcher import MatchResult, TemplateMatcher
from coc_bot.vision.rois import ROI, roi_center, denormalize_roi
from coc_bot.vision.screens import BotMode, ScreenClassifier, ScreenType


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
        self.mode = BotMode.DONATE
        self._template_cache: dict[str, np.ndarray] = {}
        self._last_jump_at = 0.0
        self.stop_check: Callable[[], bool] | None = None

    def _stopping(self) -> bool:
        return bool(self.stop_check and self.stop_check())

    def classify(self, frame: np.ndarray, mode: BotMode | None = None) -> ScreenType:
        """Classify using the navigator's current mode (or an override)."""
        return self.classifier.classify(frame, mode=mode if mode is not None else self.mode)

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

    def ensure_clan_chat(
        self,
        timeout: float | None = None,
        has_donate_request: Callable[[np.ndarray], bool] | None = None,
    ) -> bool:
        timeout = timeout or self.config.state_watchdog_seconds
        deadline = time.time() + timeout

        close_streak = 0
        # Full classify: may be recovering from farm / boot / desync.
        prev_mode = self.mode
        self.mode = BotMode.ANY

        try:
            while time.time() < deadline:
                if self._stopping():
                    logger.info("ensure_clan_chat: stop requested — aborting")
                    return False
                frame = self.capture.screenshot()
                screen = self.classify(frame, mode=BotMode.ANY)
                logger.debug("ensure_clan_chat: detected screen={}", screen.value)

                if screen == ScreenType.DONATION_PANEL:
                    before = screen
                    self.close_donation_panel(frame)
                    after = self.classify(self.capture.screenshot(), mode=BotMode.ANY)
                    if after == before:
                        close_streak += 1
                    else:
                        close_streak = 0
                    if close_streak >= 3:
                        logger.warning(
                            "Stuck in donation-panel close loop — opening clan chat instead"
                        )
                        self._open_clan_chat(self.capture.screenshot())
                        close_streak = 0
                        if self._sleep(1.0):
                            return False
                    continue

                close_streak = 0

                if screen == ScreenType.POPUP:
                    self._dismiss_popup(frame)
                    if self._sleep(1.0):
                        return False
                    continue

                if screen == ScreenType.CLAN_CHAT:
                    # Chat Groups uses the same drawer; switch back to the swords tab.
                    if self.classifier.is_global_chat(frame):
                        self._return_from_global_chat(frame)
                        if self._sleep(0.8):
                            return False
                        continue
                    self.navigate_to_donation_requests(frame, has_donate_request)
                    return True

                if screen == ScreenType.HOME or screen == ScreenType.UNKNOWN:
                    open_chat = self.classifier._open_chat_icon_visible(frame)  # noqa: SLF001
                    attack = self.classifier._home_attack_chip_visible(frame)  # noqa: SLF001
                    logger.info(
                        "Not in clan chat (screen={}) — opening chat "
                        "(open_chat_icon={}, attack_chip={})",
                        screen.value,
                        open_chat,
                        attack,
                    )
                    self._open_clan_chat(frame)
                    if self._sleep(1.0):
                        return False
                    continue

                if screen == ScreenType.LOADING:
                    if self._sleep(2.0):
                        return False
                    continue

                if screen == ScreenType.LIVE_REPLAY:
                    logger.info(
                        "ensure_clan_chat: Live Replay (defense) — waiting (no taps)"
                    )
                    if self._sleep(3.0):
                        return False
                    continue

                if screen in (
                    ScreenType.ATTACK_MENU,
                    ScreenType.MATCHMAKING,
                    ScreenType.BATTLE,
                    ScreenType.BATTLE_RESULTS,
                ):
                    logger.info(
                        "ensure_clan_chat: leaving attack UI (screen={})",
                        screen.value,
                    )
                    if self.classifier.looks_like_live_replay(frame):
                        logger.info(
                            "ensure_clan_chat: Live Replay under false attack UI — waiting"
                        )
                        if self._sleep(3.0):
                            return False
                        continue
                    # Never Android BACK during live battle — that opens Surrender.
                    if self.classifier.looks_like_surrender_dialog(frame):
                        cancel = self.classifier.find_surrender_cancel_button(frame)
                        if cancel:
                            logger.info(
                                "Surrender dialog open — tapping Cancel at ({}, {})",
                                cancel[0],
                                cancel[1],
                            )
                            self.input.tap(cancel[0], cancel[1], jitter=0)
                        if self._sleep(1.0):
                            return False
                        continue
                    if screen == ScreenType.BATTLE:
                        logger.info(
                            "ensure_clan_chat: live battle — waiting (not pressing BACK)"
                        )
                        if self._sleep(2.0):
                            return False
                        continue
                    if screen == ScreenType.BATTLE_RESULTS:
                        # Mid-fight can false-read as results — wait if End Battle is up.
                        if self.classifier._live_battle_chrome_visible(frame):  # noqa: SLF001
                            logger.info(
                                "ensure_clan_chat: false results (live chrome) — waiting"
                            )
                            if self._sleep(2.0):
                                return False
                            continue
                        found = self.classifier.find_return_home_button(frame)
                        if found is not None:
                            self.input.tap(found[0], found[1], jitter=0)
                        else:
                            point = self.config.tap_points.get("return_home")
                            if point:
                                self.input.tap(int(point[0]), int(point[1]))
                            else:
                                h, w = frame.shape[:2]
                                self.input.tap(int(w * 0.50), int(h * 0.88))
                        if self._sleep(1.2):
                            return False
                        continue
                    # Attack menu / matchmaking — BACK is safe here.
                    self.input.back()
                    if self._sleep(1.2):
                        return False
                    continue

            logger.warning("Failed to reach clan chat within timeout")
            return False
        finally:
            self.mode = BotMode.DONATE if prev_mode == BotMode.ANY else prev_mode

    def _sleep(self, seconds: float) -> bool:
        from coc_bot.stop import interrupted_sleep

        return interrupted_sleep(seconds, self.stop_check)

    def _open_clan_chat(self, frame: np.ndarray) -> None:
        h, w = frame.shape[:2]
        # Prefer a live template hit over a stale tap point (coords drift / wrong target).
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
                self.input.tap(cx, cy, jitter=0)
                return
            logger.warning(
                "open_chat template saved but not found on screen — trying tap point"
            )

        point = self.config.tap_points.get("open_chat")
        if point:
            logger.info("Opening clan chat via tap point ({}, {})", point[0], point[1])
            self.input.tap(point[0], point[1], jitter=0)
            return

        logger.warning("No open_chat template or tap point — using fallback position")
        fx, fy = int(w * 0.08), int(h * 0.45)
        logger.info("Fallback tap to open chat at ({}, {})", fx, fy)
        self.input.tap(fx, fy, jitter=0)

    def _return_from_global_chat(self, frame: np.ndarray) -> None:
        """Tap the swords/shield tab to leave Chat Groups for clan chat."""
        point = self.config.tap_points.get("clan_chat_tab")
        if point and len(point) >= 2:
            logger.info(
                "Chat Groups open — tapping clan chat tab at ({}, {})",
                point[0],
                point[1],
            )
            self.input.tap(int(point[0]), int(point[1]), jitter=0)
            return

        rel = self.config.templates.get("clan_chat_tab")
        if rel:
            path = self.config.templates_dir / rel
            if path.exists():
                tpl = cv2.imread(str(path), cv2.IMREAD_COLOR)
                if tpl is not None:
                    match = self.matcher.find(frame, tpl)
                    if match:
                        logger.info(
                            "Chat Groups open — tapping clan chat tab template at ({}, {})",
                            match.center[0],
                            match.center[1],
                        )
                        self.input.tap(match.center[0], match.center[1], jitter=0)
                        return

        close_pt = self.config.tap_points.get("close_chat")
        if close_pt and len(close_pt) >= 2:
            h = frame.shape[0]
            x, y = int(close_pt[0]), int(close_pt[1]) - max(36, int(h * 0.06))
            if y > 0:
                logger.info(
                    "Chat Groups open — estimating clan tab above close_chat at ({}, {})",
                    x,
                    y,
                )
                self.input.tap(x, y, jitter=0)
                return

        logger.warning(
            "Chat Groups open but clan_chat_tab not calibrated — "
            "Setup → Optional UI → Clan chat tab (swords)"
        )

    def find_close_chat_tab(self, frame: np.ndarray) -> tuple[int, int] | None:
        """
        Locate the orange ``<`` tab on the right edge of an open clan chat panel.

        This is NOT the same control as open_chat (chat bubble / ``>`` on home).
        """
        h, w = frame.shape[:2]
        # Prefer the right strip of the calibrated chat panel.
        if "chat_panel" in self.config.rois:
            from coc_bot.vision.rois import crop_roi

            x, y, rw, rh = denormalize_roi(ROI(**self.config.rois["chat_panel"]), w, h)
            # Search a band just inside/outside the panel's right edge.
            x0 = max(0, x + int(rw * 0.88))
            x1 = min(w, x + rw + int(w * 0.04))
            y0 = max(0, y + int(rh * 0.25))
            y1 = min(h, y + int(rh * 0.75))
        else:
            # Chat usually covers ~left third; tab sits on its right edge, mid-height.
            x0, x1 = int(w * 0.22), int(w * 0.40)
            y0, y1 = int(h * 0.30), int(h * 0.70)

        crop = frame[y0:y1, x0:x1]
        if crop.size == 0:
            return None

        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        orange = cv2.inRange(hsv, (5, 100, 100), (30, 255, 255))
        orange = cv2.morphologyEx(
            orange, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 9))
        )
        contours, _ = cv2.findContours(orange, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None

        best = None
        best_score = -1.0
        crop_h, crop_w = crop.shape[:2]
        min_area = max(40.0, crop_w * crop_h * 0.002)
        for cnt in contours:
            area = float(cv2.contourArea(cnt))
            if area < min_area:
                continue
            bx, by, bw, bh = cv2.boundingRect(cnt)
            # Tab is a small upright chip (taller than wide, or roughly square).
            aspect = bw / max(1, bh)
            if aspect > 1.6 or bh < 8:
                continue
            cx, cy = bx + bw / 2.0, by + bh / 2.0
            # Prefer mid-height, larger blobs.
            score = area - abs(cy - crop_h / 2) * 0.4
            if score > best_score:
                best_score = score
                best = (int(x0 + cx), int(y0 + cy))
        return best

    def close_clan_chat(self, frame: np.ndarray | None = None) -> bool:
        """
        Close an open clan chat panel via the orange ``<`` edge tab.

        Returns True if a close control was tapped.
        """
        if frame is None:
            frame = self.capture.screenshot()

        point = self.config.tap_points.get("close_chat")
        if point:
            logger.info("Closing clan chat via tap point ({}, {})", point[0], point[1])
            self.input.tap(int(point[0]), int(point[1]), jitter=0)
            return True

        template = self.load_template("close_chat")
        if template is not None:
            match = self.matcher.find(frame, template, threshold=max(0.70, self.config.template_threshold - 0.10))
            if match:
                cx, cy = match.center
                logger.info("Closing clan chat via template at ({}, {})", cx, cy)
                self.input.tap(cx, cy, jitter=0)
                return True

        tab = self.find_close_chat_tab(frame)
        if tab is not None:
            logger.info("Closing clan chat via orange < tab at ({}, {})", tab[0], tab[1])
            self.input.tap(tab[0], tab[1], jitter=0)
            return True

        # Last resort: right edge of chat_panel ROI center.
        if "chat_panel" in self.config.rois:
            h, w = frame.shape[:2]
            x, y, rw, rh = denormalize_roi(ROI(**self.config.rois["chat_panel"]), w, h)
            cx = x + rw - max(8, int(rw * 0.03))
            cy = y + rh // 2
            logger.warning("close_chat missing — tapping chat panel right edge ({}, {})", cx, cy)
            self.input.tap(cx, cy, jitter=0)
            return True

        logger.warning("Could not find close_chat control")
        return False

    def close_donation_panel(self, frame: np.ndarray | None = None) -> None:
        """Close donation panel by tapping outside it (CoC has no X button)."""
        if frame is None:
            frame = self.capture.screenshot()

        if not self.classifier.is_donation_panel(frame):
            logger.debug(
                "Skip close tap — donation panel not detected (screen={})",
                self.classify(frame, mode=BotMode.DONATE).value,
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
        """
        Clear launch/news/Star Bonus modals.

        Prefer calibrated Okay/Claim. Otherwise tap a screen corner outside the
        centered card (Star Bonus dismisses from any corner).
        """
        template = self.load_template("popup_dismiss")
        if template is not None:
            match = self.matcher.find(frame, template)
            if match:
                cx, cy = match.center
                logger.info("Dismissing popup via template at ({}, {})", cx, cy)
                self.input.tap(cx, cy)
                return

        point = self.config.tap_points.get("dismiss_popup")
        if point:
            logger.info("Dismissing popup via tap point ({}, {})", point[0], point[1])
            self.input.tap(point[0], point[1])
            return

        h, w = frame.shape[:2]
        # Top-right corner — outside the blue Star Bonus / news card.
        tx, ty = int(w * 0.96), int(h * 0.05)
        logger.info("Dismissing popup — tap corner ({}, {})", tx, ty)
        self.input.tap(tx, ty)

    def _chat_region_roi(self, region: str) -> list[float] | None:
        """
        Return normalized ROI for chat jump-icon search.

        region: "top" or "bottom" strip of the chat panel.
        """
        if region == "top" and "chat_request_jump_area" in self.config.rois:
            return self.config.rois["chat_request_jump_area"]
        if region == "bottom" and "chat_scroll_down_area" in self.config.rois:
            return self.config.rois["chat_scroll_down_area"]

        if "chat_panel" not in self.config.rois:
            return None

        panel = ROI(*self.config.rois["chat_panel"])
        strip_h = panel.h * 0.30
        if region == "top":
            return [panel.x, panel.y, panel.w, strip_h]
        if region == "bottom":
            return [panel.x, panel.y + panel.h - strip_h, panel.w, strip_h]
        return self.config.rois["chat_panel"]

    def _find_in_chat_region(
        self,
        frame: np.ndarray,
        template_key: str,
        region: str,
    ) -> MatchResult | None:
        template = self.load_template(template_key)
        if template is None:
            return None
        threshold = self.config.donate_button_threshold
        roi_dict = self._chat_region_roi(region)
        if roi_dict is not None:
            return self.matcher.find_in_roi(frame, template, roi_dict, threshold=threshold)
        return self.matcher.find(frame, template, threshold=threshold)

    def _find_request_jump_icon(self, frame: np.ndarray) -> MatchResult | None:
        """
        Exclamation jump icon — same control at top or bottom of the chat log.

        Top: request is above the current view. Bottom: request is below.
        When both are visible, pick the highest-confidence match only.
        """
        candidates: list[MatchResult] = []
        for region in ("top", "bottom"):
            match = self._find_in_chat_region(frame, "chat_request_jump", region)
            if match is not None:
                candidates.append(match)
        legacy = self._find_in_chat_region(frame, "chat_scroll_down", "bottom")
        if legacy is not None:
            candidates.append(legacy)
        if not candidates:
            return None
        return max(candidates, key=lambda m: m.confidence)

    def _jump_icon_location(self, match: MatchResult, frame: np.ndarray) -> str:
        if "chat_panel" not in self.config.rois:
            return "chat"
        fh, fw = frame.shape[:2]
        _, panel_y, _, panel_h = denormalize_roi(ROI(*self.config.rois["chat_panel"]), fw, fh)
        mid_y = panel_y + panel_h // 2
        return "top" if match.center[1] < mid_y else "bottom"

    def tap_request_jump_if_visible(
        self,
        frame: np.ndarray | None = None,
        *,
        has_donate_request: Callable[[np.ndarray], bool] | None = None,
    ) -> bool:
        """Tap the exclamation jump icon (top or bottom of chat) if no donate button is on screen."""
        if frame is None:
            frame = self.capture.screenshot()

        if has_donate_request and has_donate_request(frame):
            logger.debug("Donate button visible on screen — skipping exclamation tap")
            return False

        if time.time() - self._last_jump_at < 2.0:
            logger.debug("Exclamation jump cooldown — waiting for chat to settle")
            return False

        jump = self._find_request_jump_icon(frame)
        if jump is None:
            return False

        cx, cy = jump.center
        where = self._jump_icon_location(jump, frame)
        logger.info(
            "Tapping exclamation at {} of chat to jump to request ({}, {}), conf={:.2f}",
            where,
            cx,
            cy,
            jump.confidence,
        )
        self.input.tap(cx, cy)
        self._last_jump_at = time.time()
        time.sleep(0.5)
        return True

    def seek_donation_requests_step(
        self,
        frame: np.ndarray | None = None,
        has_donate_request: Callable[[np.ndarray], bool] | None = None,
    ) -> str:
        """
        One step toward a donate request.

        Always prefers a visible Donate button over tapping exclamation.
        Returns: "donate_visible", "jump", or "none".
        """
        if frame is None:
            frame = self.capture.screenshot()

        if has_donate_request and has_donate_request(frame):
            logger.debug("Donate button on screen — not using exclamation")
            return "donate_visible"

        if self.tap_request_jump_if_visible(frame, has_donate_request=has_donate_request):
            return "jump"

        if self.load_template("chat_request_jump") is None and self.load_template("chat_scroll_down") is None:
            logger.debug(
                "No donate button in view and no jump icon calibrated "
                "(calibrate.py --step clan_chat)"
            )
        else:
            logger.debug("No donate button in view and no exclamation icon visible")
        return "none"

    def navigate_to_donation_requests(
        self,
        frame: np.ndarray | None = None,
        has_donate_request: Callable[[np.ndarray], bool] | None = None,
    ) -> None:
        """Initial chat navigation on startup — donate buttons take priority over exclamation."""
        if frame is None:
            frame = self.capture.screenshot()

        if has_donate_request and has_donate_request(frame):
            return

        max_steps = self.config.chat_max_scroll_attempts
        for step in range(1, max_steps + 1):
            if frame is None:
                frame = self.capture.screenshot()
            action = self.seek_donation_requests_step(frame, has_donate_request)
            if action in ("none", "donate_visible"):
                return
            if action == "jump":
                return
            frame = None
            if step >= max_steps:
                logger.warning("Chat navigation stopped after {} steps", max_steps)
