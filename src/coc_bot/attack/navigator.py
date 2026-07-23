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
        # Attack! map button — bottom-left on modern home UI.
        if key == "attack_button":
            h, w = frame.shape[:2]
            fx, fy = int(w * 0.065), int(h * 0.90)
            logger.warning("attack_button missing — fallback tap ({}, {})", fx, fy)
            self.input.tap(fx, fy, jitter=0)
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
        Ordered tap points for the home Attack! control (map icon, bottom-left).

        Vision-first: modern CoC uses a large orange rectangle, not a sword badge.
        Calibration is tried after vision so a bad calib point cannot burn the
        success detection (opening Attack then tapping again closes it).
        """
        h, w = frame.shape[:2]
        candidates: list[tuple[int, int]] = []

        blob = self._find_attack_button_blob(frame)
        if blob is not None:
            candidates.append(blob)
            bx, by = blob
            for dx, dy in ((0, -12), (0, 12), (-10, 0), (10, 0)):
                candidates.append((bx + dx, by + dy))

        template = self.load_template("attack_button")
        if template is not None:
            match = self.matcher.find(
                frame,
                template,
                threshold=max(0.68, self.config.template_threshold - 0.14),
            )
            if match:
                candidates.append(match.center)

        # Modern default from live home UI (~nx=0.065, ny=0.90).
        for nx, ny in (
            (0.065, 0.90),
            (0.075, 0.88),
            (0.055, 0.92),
            (0.090, 0.90),
            (0.080, 0.85),
        ):
            candidates.append((int(w * nx), int(h * ny)))

        scaled = self._scaled_point("attack_button", frame)
        if scaled:
            ax, ay = scaled
            # Only keep calib if it sits in the Attack corner (ignore bad picks).
            if ax < w * 0.22 and ay > h * 0.75:
                candidates.append((ax, ay))
            else:
                logger.warning(
                    "Ignoring attack_button calib ({}, {}) — outside bottom-left Attack zone",
                    ax,
                    ay,
                )

        cleaned: list[tuple[int, int]] = []
        seen: set[tuple[int, int]] = set()
        for x, y in candidates:
            x = int(max(4, min(w - 4, x)))
            y = int(max(4, min(h - 4, y)))
            key = (x // 12, y // 12)
            if key in seen:
                continue
            seen.add(key)
            cleaned.append((x, y))
        return cleaned

    def _find_attack_button_blob(self, frame: np.ndarray) -> tuple[int, int] | None:
        """
        Find the large orange Attack! rectangle (map icon) in the bottom-left.

        Current CoC home UI — not the old circular sword badge.
        """
        h, w = frame.shape[:2]
        x0, x1 = 0, int(w * 0.16)
        y0, y1 = int(h * 0.76), h
        crop = frame[y0:y1, x0:x1]
        if crop.size == 0:
            return None

        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        warm = cv2.inRange(hsv, (5, 70, 70), (35, 255, 255))
        warm = cv2.morphologyEx(
            warm, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (11, 11))
        )
        warm = cv2.morphologyEx(
            warm, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        )
        contours, _ = cv2.findContours(warm, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None

        best = None
        best_score = -1.0
        crop_h, crop_w = crop.shape[:2]
        min_area = crop_w * crop_h * 0.04
        for cnt in contours:
            area = float(cv2.contourArea(cnt))
            if area < min_area:
                continue
            bx, by, bw, bh = cv2.boundingRect(cnt)
            aspect = bw / max(1, bh)
            # Rectangular Attack! chip — allow wider than the old round sword.
            if aspect < 0.45 or aspect > 2.8:
                continue
            cx, cy = bx + bw / 2.0, by + bh / 2.0
            # Prefer larger blobs lower in the strip (button under the star bar).
            score = area + cy * 2.0 - cx * 0.5
            if score > best_score:
                best_score = score
                best = (int(x0 + cx), int(y0 + cy))
        return best

    def attack_button_visible(self, frame: np.ndarray) -> bool:
        return self._find_attack_button_blob(frame) is not None

    def _attack_menu_open(self, frame: np.ndarray, *, had_attack_chip: bool = False) -> bool:
        screen = self.classifier.classify(frame)
        if screen in (ScreenType.ATTACK_MENU, ScreenType.MATCHMAKING):
            return True
        if self.classifier._looks_like_attack_menu(frame):  # noqa: SLF001
            return True
        # If we saw Attack! before the tap and it vanished, treat as success —
        # avoids re-tapping (which closes the picker) when heuristics are weak.
        if had_attack_chip and not self.attack_button_visible(frame):
            if screen not in (ScreenType.CLAN_CHAT, ScreenType.DONATION_PANEL, ScreenType.HOME):
                return True
            # HOME classifier can lag; chip gone is still a strong signal.
            if screen == ScreenType.HOME and self.classifier._looks_like_attack_menu(frame):  # noqa: SLF001
                return True
            if screen == ScreenType.HOME and not self.attack_button_visible(frame):
                # Bright center card without bottom-left Attack chip.
                h, w = frame.shape[:2]
                center = frame[int(h * 0.20) : int(h * 0.75), int(w * 0.20) : int(w * 0.80)]
                if center.size:
                    bright = float(cv2.cvtColor(center, cv2.COLOR_BGR2GRAY).mean())
                    if bright > 140:
                        return True
        return False

    def open_attack_menu(self) -> bool:
        frame = self.capture.screenshot()
        if self._attack_menu_open(frame):
            return True

        screen = self.classifier.classify(frame)
        if screen not in (ScreenType.HOME, ScreenType.UNKNOWN):
            if not self.leave_chat_for_home(timeout=10.0):
                logger.warning("open_attack_menu: not on home (screen={})", screen.value)
            frame = self.capture.screenshot()
            if self._attack_menu_open(frame):
                return True

        had_chip = self.attack_button_visible(frame)
        candidates = self.find_attack_button_candidates(frame)
        logger.info(
            "Trying {} Attack! candidate(s) (chip_visible={}, frame={}x{})",
            len(candidates),
            had_chip,
            frame.shape[1],
            frame.shape[0],
        )

        for x, y in candidates:
            logger.info("Trying Attack! at ({}, {})", x, y)
            self.input.tap(x, y, jitter=0)
            time.sleep(1.35)
            check = self.capture.screenshot()
            if self._attack_menu_open(check, had_attack_chip=had_chip):
                logger.info("Attack menu opened after tap at ({}, {})", x, y)
                self.config.tap_points["attack_button"] = [x, y]
                return True
            # Wrong tap opened a building card — dismiss, continue.
            if self.classifier.classify(check) == ScreenType.HOME:
                self._nudge_clear_home_overlays(check)
                had_chip = self.attack_button_visible(self.capture.screenshot())

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
