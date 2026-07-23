from __future__ import annotations

import time
from collections.abc import Callable

import cv2
import numpy as np
from loguru import logger

from coc_bot.adb.capture import ScreenCapture
from coc_bot.adb.input import InputController
from coc_bot.config import BotConfig
from coc_bot.donation.navigator import Navigator
from coc_bot.stop import interrupted_sleep
from coc_bot.vision.matcher import TemplateMatcher
from coc_bot.vision.screens import BotMode, ScreenClassifier, ScreenType


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
        self.mode = BotMode.ATTACK
        self._template_cache: dict[str, np.ndarray] = {}
        self.stop_check: Callable[[], bool] | None = None

    def _stopping(self) -> bool:
        return bool(self.stop_check and self.stop_check())

    def classify(self, frame: np.ndarray, mode: BotMode | None = None) -> ScreenType:
        """Classify using the attack navigator's current mode (or an override)."""
        return self.classifier.classify(frame, mode=mode if mode is not None else self.mode)

    def _sleep(self, seconds: float) -> bool:
        return interrupted_sleep(seconds, self.stop_check)

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
            self.input.tap(point[0], point[1], jitter=0 if key == "attack_button" else None)
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
        prev_mode = self.mode
        self.mode = BotMode.ANY
        try:
            while time.time() < deadline:
                if self._stopping():
                    logger.info("leave_chat_for_home: stop requested — aborting")
                    return False
                frame = self.capture.screenshot()
                # Ground truth for farm: Attack! visible ⇒ ready (ignore false clan_chat).
                if self.attack_button_visible(frame):
                    logger.info("Home ready — Attack! chip visible")
                    return True
                if self._attack_menu_open(frame):
                    return True

                screen = self.classify(frame, mode=BotMode.ANY)
                if screen == ScreenType.LIVE_REPLAY or self.classifier.looks_like_live_replay(frame):
                    logger.info("leave_chat_for_home: Live Replay — waiting")
                    if self._sleep(3.0):
                        return False
                    continue
                if screen == ScreenType.HOME:
                    self._nudge_clear_home_overlays(frame)
                    if self.attack_button_visible(self.capture.screenshot()):
                        return True
                    return True
                if screen == ScreenType.DONATION_PANEL and self.donation_nav is not None:
                    self.donation_nav.close_donation_panel(frame)
                    if self._sleep(0.6):
                        return False
                    continue
                if screen == ScreenType.POPUP and self.donation_nav is not None:
                    self.donation_nav._dismiss_popup(frame)  # noqa: SLF001
                    if self._sleep(0.8):
                        return False
                    continue
                if screen == ScreenType.CLAN_CHAT:
                    # Orange ``<`` tab on the chat edge — NOT the same as open_chat.
                    if self.donation_nav is not None:
                        self.donation_nav.close_clan_chat(frame)
                    else:
                        self._close_clan_chat_fallback(frame)
                    if self._sleep(0.8):
                        return False
                    continue
                if screen in (
                    ScreenType.ATTACK_MENU,
                    ScreenType.MATCHMAKING,
                    ScreenType.BATTLE,
                    ScreenType.BATTLE_RESULTS,
                ):
                    self.return_home_from_attack()
                    if self._sleep(1.0):
                        return False
                    continue
                if screen == ScreenType.LOADING:
                    if self._sleep(1.5):
                        return False
                    continue
                # Unknown — do not blindly toggle chat (that can open it over Attack!).
                self._nudge_clear_home_overlays(frame)
                if self._sleep(0.5):
                    return False
            logger.warning("Could not reach home before attack")
            frame = self.capture.screenshot()
            return self.attack_button_visible(frame) or (
                self.classify(frame, mode=BotMode.HOME) == ScreenType.HOME
            )
        finally:
            self.mode = BotMode.ATTACK if prev_mode == BotMode.ANY else prev_mode

    def _nudge_clear_home_overlays(self, frame: np.ndarray) -> None:
        """Tap empty village space so shop/info cards do not cover the Attack button."""
        h, w = frame.shape[:2]
        self.input.tap(int(w * 0.50), int(h * 0.28), jitter=2)
        time.sleep(0.35)

    def _close_clan_chat_fallback(self, frame: np.ndarray) -> None:
        """Close chat when donation Navigator is unavailable."""
        point = self.config.tap_points.get("close_chat")
        if point:
            self.input.tap(int(point[0]), int(point[1]), jitter=0)
            return
        h, w = frame.shape[:2]
        # Typical orange < tab on the right edge of an open chat panel.
        self.input.tap(int(w * 0.32), int(h * 0.48), jitter=0)

    def find_attack_button_candidates(self, frame: np.ndarray) -> list[tuple[int, int]]:
        """Few high-confidence Attack! taps — avoid long grids that re-close the menu."""
        h, w = frame.shape[:2]
        candidates: list[tuple[int, int]] = []

        blob = self._find_attack_button_blob(frame)
        if blob is not None:
            candidates.append(blob)

        scaled = self._scaled_point("attack_button", frame)
        if scaled:
            ax, ay = scaled
            if ax < w * 0.22 and ay > h * 0.75:
                candidates.append((ax, ay))
            else:
                logger.warning(
                    "Ignoring attack_button calib ({}, {}) — outside bottom-left Attack zone",
                    ax,
                    ay,
                )

        template = self.load_template("attack_button")
        if template is not None:
            match = self.matcher.find(
                frame,
                template,
                threshold=max(0.68, self.config.template_threshold - 0.14),
            )
            if match:
                candidates.append(match.center)

        for nx, ny in ((0.065, 0.90), (0.080, 0.88), (0.050, 0.92)):
            candidates.append((int(w * nx), int(h * ny)))

        cleaned: list[tuple[int, int]] = []
        seen: set[tuple[int, int]] = set()
        for x, y in candidates:
            x = int(max(4, min(w - 4, x)))
            y = int(max(4, min(h - 4, y)))
            key = (x // 14, y // 14)
            if key in seen:
                continue
            seen.add(key)
            cleaned.append((x, y))
        return cleaned

    def _find_attack_button_blob(self, frame: np.ndarray) -> tuple[int, int] | None:
        """Find the large orange Attack! rectangle (map icon) in the bottom-left."""
        h, w = frame.shape[:2]
        x0, x1 = 0, int(w * 0.15)
        y0, y1 = int(h * 0.78), h
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
        min_area = crop_w * crop_h * 0.05
        for cnt in contours:
            area = float(cv2.contourArea(cnt))
            if area < min_area:
                continue
            bx, by, bw, bh = cv2.boundingRect(cnt)
            aspect = bw / max(1, bh)
            if aspect < 0.45 or aspect > 2.8:
                continue
            cx, cy = bx + bw / 2.0, by + bh / 2.0
            score = area + cy * 2.0 - cx * 0.5
            if score > best_score:
                best_score = score
                best = (int(x0 + cx), int(y0 + cy))
        return best

    def attack_button_visible(self, frame: np.ndarray) -> bool:
        return self._find_attack_button_blob(frame) is not None

    def _attack_menu_open(self, frame: np.ndarray, *, had_attack_chip: bool = False) -> bool:
        screen = self.classify(frame, mode=BotMode.ATTACK)
        if screen in (ScreenType.ATTACK_MENU, ScreenType.MATCHMAKING):
            return True
        if self.classifier._looks_like_attack_menu(frame):  # noqa: SLF001
            return True
        # Chip vanished after a tap — stop. Re-tapping closes the picker.
        if had_attack_chip and not self.attack_button_visible(frame):
            logger.info(
                "Attack! chip gone after tap (screen={}) — treating as menu open",
                screen.value,
            )
            return True
        return False

    def open_attack_menu(self) -> bool:
        frame = self.capture.screenshot()
        if self._attack_menu_open(frame):
            return True

        if not self.attack_button_visible(frame):
            logger.info("Attack! not visible yet — clearing chat/overlays")
            self.leave_chat_for_home(timeout=12.0)
            frame = self.capture.screenshot()
            if self._attack_menu_open(frame):
                return True

        had_chip = self.attack_button_visible(frame)
        candidates = self.find_attack_button_candidates(frame)
        touch = None
        try:
            touch = self.input.client.wm_size()
        except Exception:  # noqa: BLE001
            pass
        logger.info(
            "Trying {} Attack! candidate(s) (chip_visible={}, frame={}x{}, wm={})",
            len(candidates),
            had_chip,
            frame.shape[1],
            frame.shape[0],
            touch,
        )

        debug_dir = self.config.data_dir / "debug"
        debug_dir.mkdir(parents=True, exist_ok=True)

        for i, (x, y) in enumerate(candidates):
            if i == 0:
                marked = frame.copy()
                cv2.circle(marked, (x, y), 18, (0, 255, 255), 3)
                path = debug_dir / "attack_pre_tap.png"
                cv2.imwrite(str(path), marked)
                logger.info("Saved {}", path)

            logger.info("Trying Attack! at ({}, {})", x, y)
            self.input.tap(x, y, jitter=0)
            time.sleep(1.6)
            check = self.capture.screenshot()
            cv2.imwrite(str(debug_dir / "attack_post_tap.png"), check)

            if self._attack_menu_open(check, had_attack_chip=had_chip):
                logger.info("Attack menu opened after tap at ({}, {})", x, y)
                self.config.tap_points["attack_button"] = [x, y]
                return True

            if self.attack_button_visible(check):
                self._nudge_clear_home_overlays(check)
                frame = self.capture.screenshot()
                had_chip = self.attack_button_visible(frame)
                continue

            logger.warning(
                "Attack! chip state unclear after tap at ({}, {}) screen={}",
                x,
                y,
                self.classify(check, mode=BotMode.ATTACK).value,
            )
            break

        logger.warning("Could not open Attack menu — see data/debug/attack_*.png")
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
        last_screen = "unknown"
        while time.time() < deadline:
            if self._stopping():
                logger.info("wait_for_battle: stop requested — aborting")
                return False
            frame = self.capture.screenshot()
            screen = self.classify(frame, mode=BotMode.ATTACK)
            last_screen = screen.value
            if screen == ScreenType.BATTLE or self.classifier._looks_like_battle(frame):  # noqa: SLF001
                logger.info("Battle field ready (screen={})", screen.value)
                return True
            if screen == ScreenType.BATTLE_RESULTS:
                # Double-check — do not abort a live attack mislabeled as results.
                if self.classifier._looks_like_battle(frame):  # noqa: SLF001
                    logger.info("Battle field ready (overrode false results)")
                    return True
                logger.warning("Saw battle results before deploy — opponent may have ended early")
                return False
            if screen == ScreenType.HOME and self.attack_button_visible(frame):
                logger.warning("Returned to home during matchmaking")
                return False
            if screen == ScreenType.POPUP and self.donation_nav is not None:
                self.donation_nav._dismiss_popup(frame)  # noqa: SLF001
            logger.debug("wait_for_battle: screen={}", screen.value)
            if self._sleep(0.6):
                return False
        logger.warning("Matchmaking timed out after {}s (last_screen={})", timeout, last_screen)
        # Final peek — opponent may have loaded on the last tick.
        frame = self.capture.screenshot()
        if self.classifier._looks_like_battle(frame) or self.classify(frame, mode=BotMode.ATTACK) == ScreenType.BATTLE:  # noqa: SLF001
            logger.info("Battle field ready on final check")
            return True
        return False

    def wait_for_battle_end(self, timeout: float | None = None) -> ScreenType:
        """Wait until results or home; do not surrender early."""
        timeout = timeout if timeout is not None else float(self.config.farm_battle_timeout_seconds)
        # Ignore false \"results\" right after deploy — a real fight takes longer.
        min_results_after = 45.0
        deadline = time.time() + timeout
        started = time.time()
        while time.time() < deadline:
            if self._stopping():
                logger.info("wait_for_battle_end: stop requested — aborting")
                return ScreenType.UNKNOWN
            frame = self.capture.screenshot()
            if self.classifier.looks_like_live_replay(frame):
                logger.info("wait_for_battle_end: Live Replay (defense) — waiting")
                if self._sleep(3.0):
                    return ScreenType.UNKNOWN
                continue
            if self.classifier._live_battle_chrome_visible(frame):  # noqa: SLF001
                if self._sleep(1.2):
                    return ScreenType.UNKNOWN
                continue
            screen = self.classify(frame, mode=BotMode.ATTACK)
            if screen == ScreenType.LIVE_REPLAY:
                logger.info("wait_for_battle_end: Live Replay — waiting")
                if self._sleep(3.0):
                    return ScreenType.UNKNOWN
                continue
            if screen == ScreenType.BATTLE_RESULTS or self.classifier._looks_like_battle_results(  # noqa: SLF001
                frame
            ):
                elapsed = time.time() - started
                if elapsed < min_results_after:
                    logger.debug(
                        "Ignoring early battle_results signal ({:.0f}s < {:.0f}s)",
                        elapsed,
                        min_results_after,
                    )
                    if self._sleep(1.2):
                        return ScreenType.UNKNOWN
                    continue
                logger.info("Battle ended — screen=battle_results")
                return ScreenType.BATTLE_RESULTS
            if screen in (ScreenType.HOME, ScreenType.CLAN_CHAT):
                logger.info("Battle ended — screen={}", screen.value)
                return screen
            if screen == ScreenType.BATTLE:
                if self._sleep(1.2):
                    return ScreenType.UNKNOWN
                continue
            if screen == ScreenType.POPUP and self.donation_nav is not None:
                self.donation_nav._dismiss_popup(frame)  # noqa: SLF001
            if self._sleep(1.2):
                return ScreenType.UNKNOWN
        logger.warning("Battle wait timed out after {}s", timeout)
        frame = self.capture.screenshot()
        if self.classifier._live_battle_chrome_visible(frame):  # noqa: SLF001
            return ScreenType.BATTLE
        if self.classifier._looks_like_battle_results(frame):  # noqa: SLF001
            return ScreenType.BATTLE_RESULTS
        return self.classify(frame, mode=BotMode.ATTACK)

    def _tap_return_home(self, frame: np.ndarray) -> bool:
        """Tap calibrated Return Home, green button blob, or lower-center fallback."""
        # Prefer vision of the green button on the defeat/victory card.
        found = self.classifier.find_return_home_button(frame)
        if found is not None:
            logger.info("Return Home via green button at ({}, {})", found[0], found[1])
            self.input.tap(found[0], found[1], jitter=0)
            return True
        point = self._scaled_point("return_home", frame)
        if point:
            logger.info("Tap return_home at ({}, {})", point[0], point[1])
            self.input.tap(point[0], point[1], jitter=0)
            return True
        template = self.load_template("return_home") or self.load_template("battle_end")
        if template is not None:
            match = self.matcher.find(frame, template)
            if match:
                cx, cy = match.center
                logger.info("Tap return_home via template at ({}, {})", cx, cy)
                self.input.tap(cx, cy, jitter=0)
                return True
        h, w = frame.shape[:2]
        fx, fy = int(w * 0.50), int(h * 0.88)
        logger.info("return_home fallback tap ({}, {})", fx, fy)
        self.input.tap(fx, fy, jitter=0)
        return True

    def return_home_from_attack(self) -> bool:
        """Tap Return Home / dismiss attack UI until home or chat — never mid-deploy battle."""
        for _ in range(12):
            if self._stopping():
                logger.info("return_home_from_attack: stop requested — aborting")
                return False
            frame = self.capture.screenshot()
            screen = self.classify(frame, mode=BotMode.ATTACK)

            # Defense spectator — wait; do not tap Return Home / BACK.
            if screen == ScreenType.LIVE_REPLAY or self.classifier.looks_like_live_replay(frame):
                logger.info("return_home_from_attack: Live Replay — waiting for defense to end")
                if self._sleep(3.0):
                    return False
                continue

            # Android BACK mid-battle opens this — Cancel, never Okay / never BACK again.
            if self.classifier.looks_like_surrender_dialog(frame):
                cancel = self.classifier.find_surrender_cancel_button(frame)
                if cancel:
                    logger.info(
                        "Surrender dialog — tapping Cancel at ({}, {})",
                        cancel[0],
                        cancel[1],
                    )
                    self.input.tap(cancel[0], cancel[1], jitter=0)
                if self._sleep(1.0):
                    return False
                continue

            if screen == ScreenType.POPUP and self.donation_nav is not None:
                logger.info("Dismissing post-battle popup (e.g. Star Bonus)")
                self.donation_nav._dismiss_popup(frame)  # noqa: SLF001
                if self._sleep(0.9):
                    return False
                continue
            if screen in (ScreenType.HOME, ScreenType.CLAN_CHAT):
                # Safety: Attack! can show through a modal that classify missed.
                if (
                    self.donation_nav is not None
                    and self.classifier.looks_like_blocking_popup(frame)
                ):
                    logger.info("Home under a blocking popup — dismissing")
                    self.donation_nav._dismiss_popup(frame)  # noqa: SLF001
                    if self._sleep(0.9):
                        return False
                    continue
                return True

            # Defeat/victory card often still looks like a battle tray. If the green
            # Return Home CTA is visible (and live End Battle chrome is gone), leave.
            if (
                not self.classifier._live_battle_chrome_visible(frame)  # noqa: SLF001
                and self.classifier.find_return_home_button(frame) is not None
            ):
                logger.info(
                    "Return Home button visible (screen={}) — tapping to leave",
                    screen.value,
                )
                self._tap_return_home(frame)
                if self._sleep(1.6):
                    return False
                continue

            results = (
                not self.classifier._live_battle_chrome_visible(frame)  # noqa: SLF001
                and (
                    screen == ScreenType.BATTLE_RESULTS
                    or self.classifier._looks_like_battle_results(frame)  # noqa: SLF001
                )
            )
            in_battle = (not results) and (
                screen == ScreenType.BATTLE
                or self.classifier._live_battle_chrome_visible(frame)  # noqa: SLF001
                or self.classifier._looks_like_battle(frame)  # noqa: SLF001
            )
            if in_battle:
                logger.info("return_home_from_attack: still in battle — waiting (no BACK)")
                if self._sleep(1.5):
                    return False
                continue

            if results or screen == ScreenType.UNKNOWN:
                logger.info("Tapping Return Home (screen={})", screen.value)
                self._tap_return_home(frame)
                if self._sleep(1.6):
                    return False
                continue

            if screen == ScreenType.ATTACK_MENU:
                self.input.back()
                if self._sleep(0.8):
                    return False
                continue
            if screen == ScreenType.MATCHMAKING:
                self.input.back()
                if self._sleep(1.0):
                    return False
                continue

            # Odd UI — try Return Home; do not BACK if battle chrome is still up.
            self._tap_return_home(frame)
            if self._sleep(1.2):
                return False
            check = self.capture.screenshot()
            if self.classify(check, mode=BotMode.ATTACK) in (
                ScreenType.HOME,
                ScreenType.CLAN_CHAT,
            ):
                return True
            if self.classifier._looks_like_battle(check):  # noqa: SLF001
                logger.info("Still looks like battle after Return Home tap — waiting")
                if self._sleep(1.5):
                    return False
                continue
            self.input.back()
            if self._sleep(0.8):
                return False
        return self.classify(self.capture.screenshot(), mode=BotMode.ATTACK) in (
            ScreenType.HOME,
            ScreenType.CLAN_CHAT,
        )
