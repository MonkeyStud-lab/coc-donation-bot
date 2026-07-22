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

    def _tap_named(self, key: str, frame: np.ndarray | None = None) -> bool:
        """Tap a calibrated point, falling back to a template match."""
        point = self.config.tap_points.get(key)
        if point:
            logger.info("Tap {} at ({}, {})", key, point[0], point[1])
            self.input.tap(int(point[0]), int(point[1]))
            return True
        if frame is None:
            frame = self.capture.screenshot()
        template = self.load_template(key)
        if template is not None:
            match = self.matcher.find(frame, template)
            if match:
                cx, cy = match.center
                logger.info("Tap {} via template at ({}, {})", key, cx, cy)
                self.input.tap(cx, cy)
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
                    self.input.tap(int(w * 0.72), int(h * 0.45))
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
            self.input.tap(int(w * 0.72), int(h * 0.45))
            time.sleep(0.8)
        logger.warning("Could not reach home before attack")
        return self.classifier.classify(self.capture.screenshot()) == ScreenType.HOME

    def open_attack_menu(self) -> bool:
        frame = self.capture.screenshot()
        if self.classifier.classify(frame) == ScreenType.ATTACK_MENU:
            return True
        if not self._tap_named("attack_button", frame):
            return False
        time.sleep(1.2)
        screen = self.classifier.classify(self.capture.screenshot())
        return screen in (ScreenType.ATTACK_MENU, ScreenType.MATCHMAKING, ScreenType.UNKNOWN)

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
