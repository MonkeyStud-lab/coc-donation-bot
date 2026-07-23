from __future__ import annotations

import time

import cv2
import numpy as np
from loguru import logger

from coc_bot.adb.capture import ScreenCapture
from coc_bot.adb.input import InputController
from coc_bot.config import BotConfig
from coc_bot.donation.navigator import Navigator
from coc_bot.vision.matcher import TemplateMatcher
from coc_bot.vision.screens import ScreenClassifier, ScreenType


class AttackNavigator:
    """Home → Attack → unranked Battle → matchmaking → battle → results → home."""

    def __init__(
        self,
        config: BotConfig,
        capture: ScreenCapture,
        input_ctrl: InputController,
        matcher: TemplateMatcher | None = None,
        donation_navigator: Navigator | None = None,
    ) -> None:
        self.config = config
        self.capture = capture
        self.input = input_ctrl
        self.matcher = matcher or TemplateMatcher(threshold=config.template_threshold)
        self.classifier = ScreenClassifier(config, self.matcher)
        self.donation_nav = donation_navigator
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

    def _scaled_point(self, key: str, frame: np.ndarray) -> tuple[int, int] | None:
        """Return a tap point scaled to the current frame size if needed."""
        point = self.config.tap_points.get(key)
        if not point or len(point) < 2:
            return None
        x, y = int(point[0]), int(point[1])
        fh, fw = frame.shape[:2]
        cw = int(self.config.frame_width or 0)
        ch = int(self.config.frame_height or 0)
        if cw > 0 and ch > 0 and (cw != fw or ch != fh):
            x = int(round(x * fw / cw))
            y = int(round(y * fh / ch))
            logger.debug(
                "Scaled tap {} from {}x{} calib → ({}, {}) on {}x{}",
                key,
                cw,
                ch,
                x,
                y,
                fw,
                fh,
            )
        return x, y

    def _tap_named(self, key: str, frame: np.ndarray | None = None) -> bool:
        """Tap a calibrated point (resolution-scaled), then template, then key-specific fallback."""
        if frame is None:
            frame = self.capture.screenshot()
        point = self._scaled_point(key, frame)
        if point:
            logger.info("Tap {} at ({}, {})", key, point[0], point[1])
            self.input.tap(point[0], point[1])
            return True
        template = self.load_template(key)
        if template is not None:
            match = self.matcher.find(frame, template)
            if match:
                cx, cy = match.center
                logger.info("Tap {} via template at ({}, {})", key, cx, cy)
                self.input.tap(cx, cy)
                return True
        # Attack is always bottom-left on home — use a stable default if uncalibrated.
        if key == "attack_button":
            h, w = frame.shape[:2]
            fx, fy = int(w * 0.09), int(h * 0.93)
            logger.warning("attack_button missing — fallback tap ({}, {})", fx, fy)
            self.input.tap(fx, fy)
            return True
        logger.warning("No tap point or template for {}", key)
        return False

    def leave_chat_for_home(self, timeout: float = 15.0) -> bool:
        """Close donation panel / clan chat so Attack is reachable on home."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            frame = self.capture.screenshot()
            screen = self.classifier.classify(frame)
            if screen == ScreenType.HOME:
                # Dismiss any open building/shop sheet that can cover Attack.
                self._nudge_clear_home_overlays(frame)
                return True
            if screen == ScreenType.DONATION_PANEL and self.donation_nav is not None:
                self.donation_nav.close_donation_panel(frame)
                time.sleep(0.6)
                continue
            if screen == ScreenType.POPUP and self.donation_nav is not None:
                self.donation_nav._dismiss_popup(frame)  # noqa: SLF001
                time.sleep(0.8)
                continue
            if screen == ScreenType.CLAN_CHAT:
                # Toggle chat closed via the same open_chat control.
                if not self._tap_named("open_chat", frame):
                    h, w = frame.shape[:2]
                    self.input.tap(int(w * 0.72), int(h * 0.45), jitter=0)
                time.sleep(0.8)
                continue
            if screen in (
                ScreenType.ATTACK_MENU,
                ScreenType.MATCHMAKING,
                ScreenType.BATTLE,
                ScreenType.BATTLE_RESULTS,
            ):
                self.return_home_from_attack()
                time.sleep(1.0)
                continue
            if screen == ScreenType.LOADING:
                time.sleep(1.5)
                continue
            # Unknown — try tapping open_chat toggle / village.
            h, w = frame.shape[:2]
            self.input.tap(int(w * 0.72), int(h * 0.45), jitter=0)
            time.sleep(0.8)
        logger.warning("Could not reach home before attack")
        return self.classifier.classify(self.capture.screenshot()) == ScreenType.HOME

    def _nudge_clear_home_overlays(self, frame: np.ndarray) -> None:
        """Tap empty village space so shop/info cards do not cover the Attack button."""
        h, w = frame.shape[:2]
        # Upper-center is usually empty sky / map, not the bottom UI bar.
        self.input.tap(int(w * 0.50), int(h * 0.28), jitter=2)
        time.sleep(0.35)

    def find_attack_button_candidates(self, frame: np.ndarray) -> list[tuple[int, int]]:
        """
        Ordered tap points for the home Attack (sword) control.

        Prefers calibration / template, then a warm-color blob search in the
        bottom-left chrome, then a dense fixed grid (UI spot is stable).
        """
        h, w = frame.shape[:2]
        candidates: list[tuple[int, int]] = []

        scaled = self._scaled_point("attack_button", frame)
        if scaled:
            ax, ay = scaled
            candidates.append((ax, ay))
            # Neighbors around the calibrated point (picker can be a few px off).
            for dx, dy in (
                (0, -18),
                (0, 18),
                (-18, 0),
                (18, 0),
                (-22, -22),
                (22, -22),
                (-22, 22),
                (22, 22),
            ):
                candidates.append((ax + dx, ay + dy))

        template = self.load_template("attack_button")
        if template is not None:
            # Wider scales + slightly lower threshold — Attack art varies by skin/UI.
            match = self.matcher.find(frame, template, threshold=max(0.70, self.config.template_threshold - 0.12))
            if match:
                candidates.append(match.center)

        blob = self._find_attack_button_blob(frame)
        if blob is not None:
            candidates.append(blob)

        # Dense bottom-left grid — Attack lives in this corner on home village.
        for nx in (0.05, 0.07, 0.09, 0.11, 0.13, 0.16):
            for ny in (0.86, 0.88, 0.90, 0.92, 0.94, 0.96):
                candidates.append((int(w * nx), int(h * ny)))

        # Clamp + dedupe.
        cleaned: list[tuple[int, int]] = []
        seen: set[tuple[int, int]] = set()
        for x, y in candidates:
            x = int(max(4, min(w - 4, x)))
            y = int(max(4, min(h - 4, y)))
            key = (x // 10, y // 10)
            if key in seen:
                continue
            seen.add(key)
            cleaned.append((x, y))
        return cleaned

    def _find_attack_button_blob(self, frame: np.ndarray) -> tuple[int, int] | None:
        """
        Find a warm circular UI chip in the bottom-left (Attack sword badge).

        Scenery-independent: searches only the bottom UI chrome strip.
        """
        h, w = frame.shape[:2]
        x0, x1 = 0, int(w * 0.22)
        y0, y1 = int(h * 0.78), h
        crop = frame[y0:y1, x0:x1]
        if crop.size == 0:
            return None

        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        # Wooden / gold Attack badge: warm hues, decent saturation.
        warm = cv2.inRange(hsv, (5, 60, 70), (35, 255, 255))
        warm = cv2.morphologyEx(
            warm, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        )
        warm = cv2.morphologyEx(
            warm, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
        )
        contours, _ = cv2.findContours(warm, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None

        best = None
        best_score = -1.0
        crop_h, crop_w = crop.shape[:2]
        min_area = crop_w * crop_h * 0.01
        max_area = crop_w * crop_h * 0.35
        for cnt in contours:
            area = float(cv2.contourArea(cnt))
            if area < min_area or area > max_area:
                continue
            bx, by, bw, bh = cv2.boundingRect(cnt)
            # Prefer round-ish blobs near the lower-left of the strip.
            aspect = bw / max(1, bh)
            if aspect < 0.55 or aspect > 1.8:
                continue
            cx, cy = bx + bw / 2, by + bh / 2
            # Prefer lower-left within the ROI.
            score = area - cx * 0.15 - (crop_h - cy) * 0.35
            if score > best_score:
                best_score = score
                best = (int(x0 + cx), int(y0 + cy))
        return best

    def _attack_menu_open(self, frame: np.ndarray) -> bool:
        screen = self.classifier.classify(frame)
        if screen in (ScreenType.ATTACK_MENU, ScreenType.MATCHMAKING):
            return True
        return self.classifier._looks_like_attack_menu(frame)  # noqa: SLF001

    def open_attack_menu(self) -> bool:
        frame = self.capture.screenshot()
        if self._attack_menu_open(frame):
            return True

        # Make sure chat/popups are not covering the sword.
        screen = self.classifier.classify(frame)
        if screen != ScreenType.HOME:
            if not self.leave_chat_for_home(timeout=10.0):
                logger.warning("open_attack_menu: not on home (screen={})", screen.value)
            frame = self.capture.screenshot()
            if self._attack_menu_open(frame):
                return True

        candidates = self.find_attack_button_candidates(frame)
        logger.info("Trying {} Attack-button candidate(s)", len(candidates))

        for x, y in candidates:
            logger.info("Trying Attack button at ({}, {})", x, y)
            self.input.tap(x, y, jitter=0)
            time.sleep(1.25)
            check = self.capture.screenshot()
            if self._attack_menu_open(check):
                logger.info("Attack menu opened after tap at ({}, {})", x, y)
                # Remember what worked for this session's config (not persisted).
                self.config.tap_points["attack_button"] = [x, y]
                return True
            # If we opened a shop/builder card instead, dismiss and continue.
            if self.classifier.classify(check) == ScreenType.HOME:
                self._nudge_clear_home_overlays(check)

        logger.warning("Could not open Attack menu after {} taps", len(candidates))
        return False

    def start_unranked_battle(self) -> bool:
        """Tap unranked Battle, then Find a Match if calibrated."""
        frame = self.capture.screenshot()
        if not self._tap_named("unranked_battle", frame):
            return False
        time.sleep(1.0)
        if self.config.tap_points.get("find_match") or self.config.templates.get("find_match"):
            frame = self.capture.screenshot()
            self._tap_named("find_match", frame)
            time.sleep(1.0)
        return True

    def wait_for_battle(self, timeout: float | None = None) -> bool:
        timeout = timeout if timeout is not None else float(self.config.farm_match_timeout_seconds)
        deadline = time.time() + timeout
        while time.time() < deadline:
            frame = self.capture.screenshot()
            screen = self.classifier.classify(frame)
            if screen == ScreenType.BATTLE:
                logger.info("Battle field ready")
                return True
            if screen == ScreenType.BATTLE_RESULTS:
                logger.warning("Saw battle results before deploy — opponent may have ended early")
                return False
            if screen == ScreenType.HOME:
                logger.warning("Returned to home during matchmaking")
                return False
            if screen == ScreenType.POPUP and self.donation_nav is not None:
                self.donation_nav._dismiss_popup(frame)  # noqa: SLF001
            time.sleep(0.8)
        logger.warning("Matchmaking timed out after {}s", timeout)
        return False

    def wait_for_battle_end(self, timeout: float | None = None) -> ScreenType:
        """Wait until results or home; do not surrender early."""
        timeout = timeout if timeout is not None else float(self.config.farm_battle_timeout_seconds)
        deadline = time.time() + timeout
        while time.time() < deadline:
            frame = self.capture.screenshot()
            screen = self.classifier.classify(frame)
            if screen in (ScreenType.BATTLE_RESULTS, ScreenType.HOME, ScreenType.CLAN_CHAT):
                logger.info("Battle ended — screen={}", screen.value)
                return screen
            if screen == ScreenType.POPUP and self.donation_nav is not None:
                self.donation_nav._dismiss_popup(frame)  # noqa: SLF001
            time.sleep(1.2)
        logger.warning("Battle wait timed out after {}s", timeout)
        return self.classifier.classify(self.capture.screenshot())

    def return_home_from_attack(self) -> bool:
        """Tap Return Home / dismiss attack UI until home or chat."""
        for _ in range(8):
            frame = self.capture.screenshot()
            screen = self.classifier.classify(frame)
            if screen in (ScreenType.HOME, ScreenType.CLAN_CHAT):
                return True
            if screen == ScreenType.BATTLE_RESULTS or self.load_template("return_home") is not None:
                if self._tap_named("return_home", frame):
                    time.sleep(1.5)
                    continue
            if screen == ScreenType.ATTACK_MENU:
                self.input.back()
                time.sleep(0.8)
                continue
            if screen == ScreenType.MATCHMAKING:
                self.input.back()
                time.sleep(1.0)
                continue
            # Still in battle or unknown — try return_home then BACK.
            if self._tap_named("return_home", frame):
                time.sleep(1.2)
                continue
            self.input.back()
            time.sleep(0.8)
        return self.classifier.classify(self.capture.screenshot()) in (
            ScreenType.HOME,
            ScreenType.CLAN_CHAT,
        )
