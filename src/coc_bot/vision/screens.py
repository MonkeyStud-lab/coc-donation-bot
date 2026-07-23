from __future__ import annotations

from enum import Enum

import cv2
import numpy as np

from coc_bot.config import BotConfig
from coc_bot.vision.matcher import TemplateMatcher


class ScreenType(str, Enum):
    HOME = "home"
    CLAN_CHAT = "clan_chat"
    DONATION_PANEL = "donation_panel"
    LOADING = "loading"
    POPUP = "popup"
    ATTACK_MENU = "attack_menu"
    MATCHMAKING = "matchmaking"
    BATTLE = "battle"
    BATTLE_RESULTS = "battle_results"
    UNKNOWN = "unknown"


class ScreenClassifier:
    """Classify current game screen using calibrated anchor templates."""

    def __init__(self, config: BotConfig, matcher: TemplateMatcher | None = None) -> None:
        self.config = config
        self.matcher = matcher or TemplateMatcher(threshold=config.template_threshold)
        self._cache: dict[str, np.ndarray] = {}

    def _load(self, key: str) -> np.ndarray | None:
        if key in self._cache:
            return self._cache[key]
        rel = self.config.templates.get(key)
        if not rel:
            return None
        path = self.config.templates_dir / rel
        if not path.exists():
            path = self.config.data_dir.parent / rel
        if not path.exists():
            return None
        img = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if img is not None:
            self._cache[key] = img
        return img

    def _template_visible(self, frame: np.ndarray, key: str) -> bool:
        template = self._load(key)
        return template is not None and self.matcher.find(frame, template) is not None

    def _roi_std(self, frame: np.ndarray, roi_key: str) -> float | None:
        if roi_key not in self.config.rois:
            return None
        from coc_bot.vision.rois import crop_roi

        region = crop_roi(frame, self.config.rois[roi_key])
        return float(np.std(region))

    def _is_home_screen(self, frame: np.ndarray) -> bool:
        if self._template_visible(frame, "home"):
            return True
        if self._template_visible(frame, "open_chat"):
            return True
        # Tap-point-only calibration: village screen does not show the chat panel UI.
        if self.config.tap_points.get("open_chat") and not self._clan_chat_anchor_visible(frame):
            chat_std = self._roi_std(frame, "chat_panel")
            if chat_std is not None and chat_std <= 15:
                return True
        return False

    def _clan_chat_anchor_visible(self, frame: np.ndarray) -> bool:
        """Calibrated anchor visible in chat but hidden when the donation panel is open."""
        return self._template_visible(frame, "clan_chat")

    def _in_clan_chat_context(self, frame: np.ndarray) -> bool:
        """Chat UI is on screen (panel open or closed). Not true on the village/home screen."""
        chat_std = self._roi_std(frame, "chat_panel")
        return chat_std is not None and chat_std > 15

    def _donation_panel_heuristic(self, frame: np.ndarray) -> bool:
        """Fallback when clan_chat anchor is obscured by the donation popup."""
        if self._template_visible(frame, "donation_panel"):
            return True

        troop_std = self._roi_std(frame, "donation_troop_bar")
        spell_std = self._roi_std(frame, "donation_spell_bar")

        # Require both bars — a single busy ROI false-matches on home/chat backgrounds.
        if troop_std is not None and spell_std is not None:
            return troop_std > 20 and spell_std > 20

        return False

    def is_home_screen(self, frame: np.ndarray) -> bool:
        return self._is_home_screen(frame)

    def _has_green_dialog_button(self, frame: np.ndarray) -> bool:
        """CoC Okay/Claim buttons are a large green pill in the lower-center of modals."""
        h, w = frame.shape[:2]
        y0, y1 = int(h * 0.52), int(h * 0.88)
        x0, x1 = int(w * 0.30), int(w * 0.70)
        crop = frame[y0:y1, x0:x1]
        if crop.size == 0:
            return False
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, (35, 90, 80), (90, 255, 255))
        return float(mask.mean()) / 255.0 > 0.035

    def _has_dimmed_modal_overlay(self, frame: np.ndarray) -> bool:
        """
        Launch/news popups darken the village and show a bright center card.

        Corners stay dim; the center has a large light panel. Works without
        calibrating a template for every popup variant.
        """
        h, w = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        cy0, cy1 = int(h * 0.22), int(h * 0.78)
        cx0, cx1 = int(w * 0.22), int(w * 0.78)
        center = gray[cy0:cy1, cx0:cx1]
        if center.size == 0:
            return False

        corner_means = [
            float(gray[0 : int(h * 0.14), 0 : int(w * 0.14)].mean()),
            float(gray[0 : int(h * 0.14), int(w * 0.86) : w].mean()),
            float(gray[int(h * 0.86) : h, 0 : int(w * 0.14)].mean()),
            float(gray[int(h * 0.86) : h, int(w * 0.86) : w].mean()),
        ]
        corner_mean = sum(corner_means) / len(corner_means)
        center_p90 = float(np.percentile(center, 90))
        bright_frac = float((center > 210).mean())
        return center_p90 > 190 and corner_mean < 115 and bright_frac > 0.12

    def looks_like_blocking_popup(self, frame: np.ndarray) -> bool:
        """True for Welcome Back / event / news modals that block play."""
        if self._template_visible(frame, "popup_dismiss") or self._template_visible(frame, "popup"):
            return True
        # Dimmed overlay alone can false-match busy villages; require the green Okay/Claim too.
        return self._has_dimmed_modal_overlay(frame) and self._has_green_dialog_button(frame)

    def _looks_like_attack_menu(self, frame: np.ndarray) -> bool:
        """
        Multiplayer Attack picker (Ranked / Battle) without requiring a template.

        Modern CoC shows a large center card with green action buttons after Attack!.
        """
        if self._template_visible(frame, "attack_menu") or self._template_visible(
            frame, "unranked_battle"
        ):
            return True

        h, w = frame.shape[:2]
        # Home Attack! chip lives bottom-left — if that warm rectangle is gone and a
        # bright center card + green button appear, the picker is open.
        bl = frame[int(h * 0.78) : h, 0 : int(w * 0.14)]
        attack_chip = False
        if bl.size:
            hsv_bl = cv2.cvtColor(bl, cv2.COLOR_BGR2HSV)
            warm = cv2.inRange(hsv_bl, (5, 70, 70), (35, 255, 255))
            attack_chip = float(warm.mean()) / 255.0 > 0.08

        center = frame[int(h * 0.18) : int(h * 0.82), int(w * 0.18) : int(w * 0.82)]
        if center.size == 0:
            return False
        gray = cv2.cvtColor(center, cv2.COLOR_BGR2GRAY)
        bright_frac = float((gray > 200).mean())
        hsv = cv2.cvtColor(center, cv2.COLOR_BGR2HSV)
        green = cv2.inRange(hsv, (35, 70, 70), (95, 255, 255))
        green_frac = float(green.mean()) / 255.0

        # Strict path: dimmed modal (legacy heuristic).
        if self._has_dimmed_modal_overlay(frame) and green_frac > 0.03:
            return True
        # Loose path: Attack chip gone + bright card + green CTA (new UI / Waydroid).
        if (not attack_chip) and bright_frac > 0.10 and green_frac > 0.025:
            return True
        return False

    def _looks_like_matchmaking(self, frame: np.ndarray) -> bool:
        """Cloud search screen — optional template, else soft blue-sky heuristic."""
        if self._template_visible(frame, "matchmaking") or self._template_visible(frame, "find_match"):
            return True
        h, w = frame.shape[:2]
        # Upper half is often bright sky/clouds while searching.
        crop = frame[0 : int(h * 0.45), int(w * 0.15) : int(w * 0.85)]
        if crop.size == 0:
            return False
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        blue = cv2.inRange(hsv, (90, 40, 120), (130, 255, 255))
        white = cv2.inRange(hsv, (0, 0, 200), (180, 60, 255))
        frac = float((blue | white).mean()) / 255.0
        return frac > 0.45 and not self._is_home_screen(frame)

    def _looks_like_battle(self, frame: np.ndarray) -> bool:
        """
        True on opponent scout / live attack (army tray at bottom).

        Scout UI (before first deploy) shows: bottom troop cards, red End Battle
        (bottom-left), orange Next (right). Do NOT treat End Battle as home Attack!.
        """
        if self._template_visible(frame, "battle"):
            return True
        if self._clan_chat_anchor_visible(frame):
            return False
        # Victory/defeat summary can show a troop icon — never treat as live battle.
        if self._looks_like_battle_results(frame):
            return False

        h, w = frame.shape[:2]

        # Orange "Next" (skip base) on the right — only on scout/battle, not home.
        next_roi = frame[int(h * 0.52) : int(h * 0.92), int(w * 0.80) : w]
        if next_roi.size:
            hsv_n = cv2.cvtColor(next_roi, cv2.COLOR_BGR2HSV)
            next_orange = cv2.inRange(hsv_n, (5, 90, 90), (28, 255, 255))
            if float(next_orange.mean()) / 255.0 > 0.06:
                return True

        # Red "End Battle" chip bottom-left — scout/battle only (not home Attack!).
        end_roi = frame[int(h * 0.78) : h, 0 : int(w * 0.20)]
        if end_roi.size:
            hsv_e = cv2.cvtColor(end_roi, cv2.COLOR_BGR2HSV)
            red1 = cv2.inRange(hsv_e, (0, 100, 80), (8, 255, 255))
            red2 = cv2.inRange(hsv_e, (170, 100, 80), (180, 255, 255))
            if float(cv2.bitwise_or(red1, red2).mean()) / 255.0 > 0.04:
                return True

        # Army tray along the bottom (cards / wood chrome).
        bar = frame[int(h * 0.78) : h, int(w * 0.02) : int(w * 0.98)]
        if bar.size == 0:
            return False
        hsv = cv2.cvtColor(bar, cv2.COLOR_BGR2HSV)
        dark = cv2.inRange(hsv, (0, 0, 0), (180, 255, 100))
        dark_frac = float(dark.mean()) / 255.0
        brown = cv2.inRange(hsv, (5, 30, 40), (30, 255, 220))
        brown_frac = float(brown.mean()) / 255.0
        gray = cv2.cvtColor(bar, cv2.COLOR_BGR2GRAY)
        edge_frac = float(cv2.Canny(gray, 30, 100).mean()) / 255.0

        bl = frame[int(h * 0.82) : h, 0 : int(w * 0.12)]
        gold_chip = False
        if bl.size:
            hsv_bl = cv2.cvtColor(bl, cv2.COLOR_BGR2HSV)
            gold = cv2.inRange(hsv_bl, (12, 80, 90), (35, 255, 255))
            gold_chip = float(gold.mean()) / 255.0 > 0.12

        structured = edge_frac > 0.04 and (dark_frac > 0.10 or brown_frac > 0.06)
        dark_tray = dark_frac > 0.25
        if gold_chip and not structured and not dark_tray:
            return False
        return structured or dark_tray

    def find_return_home_button(self, frame: np.ndarray) -> tuple[int, int] | None:
        """
        Tap target for the green Return Home button on defeat/victory.

        Prefers a wide green CTA in the lower center (not other green UI), and
        biases slightly down-right so we don't miss high/left of the pill.
        """
        h, w = frame.shape[:2]
        # Button sits bottom-center of the results card — keep ROI tight.
        x0, x1 = int(w * 0.28), int(w * 0.72)
        y0, y1 = int(h * 0.78), int(h * 0.96)
        crop = frame[y0:y1, x0:x1]
        if crop.size == 0:
            return None
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        green = cv2.inRange(hsv, (35, 70, 70), (95, 255, 255))
        green = cv2.morphologyEx(
            green, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (11, 7))
        )
        contours, _ = cv2.findContours(green, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None
        min_area = crop.shape[0] * crop.shape[1] * 0.015
        crop_cx = crop.shape[1] / 2.0

        def _score(c: np.ndarray) -> float:
            area = float(cv2.contourArea(c))
            if area < min_area:
                return -1.0
            bx, by, bw, bh = cv2.boundingRect(c)
            if bh < 8 or bw < 40:
                return -1.0
            aspect = bw / float(bh)
            if aspect < 1.4:
                return -1.0
            # Prefer wide pills near horizontal center of the ROI.
            cx = bx + bw / 2.0
            center_pen = 1.0 - min(1.0, abs(cx - crop_cx) / (crop.shape[1] * 0.5))
            return area * aspect * (0.55 + 0.45 * center_pen)

        best = max(contours, key=_score)
        if _score(best) < 0:
            return None
        m = cv2.moments(best)
        if m["m00"] > 1e-3:
            cx = x0 + m["m10"] / m["m00"]
            cy = y0 + m["m01"] / m["m00"]
        else:
            bx, by, bw, bh = cv2.boundingRect(best)
            cx = x0 + bx + bw / 2.0
            cy = y0 + by + bh / 2.0
        # Slight down-right bias — blob center reads a bit high/left of the label.
        return int(cx + w * 0.018), int(cy + h * 0.022)

    def _looks_like_battle_results(self, frame: np.ndarray) -> bool:
        """
        End-of-attack screen with a large green Return Home / OK button.

        Distinct from live scout/battle: no Next, no End Battle, big green CTA.
        """
        if self._template_visible(frame, "return_home") or self._template_visible(
            frame, "battle_end"
        ):
            return True
        if self.find_return_home_button(frame) is not None:
            # Live scout still has Next (right) or End Battle (left) — not results.
            h, w = frame.shape[:2]
            next_roi = frame[int(h * 0.52) : int(h * 0.92), int(w * 0.80) : w]
            if next_roi.size:
                hsv_n = cv2.cvtColor(next_roi, cv2.COLOR_BGR2HSV)
                nxt = cv2.inRange(hsv_n, (5, 90, 90), (28, 255, 255))
                if float(nxt.mean()) / 255.0 > 0.06:
                    return False
            end_roi = frame[int(h * 0.78) : h, 0 : int(w * 0.20)]
            if end_roi.size:
                hsv_e = cv2.cvtColor(end_roi, cv2.COLOR_BGR2HSV)
                red1 = cv2.inRange(hsv_e, (0, 100, 80), (8, 255, 255))
                red2 = cv2.inRange(hsv_e, (170, 100, 80), (180, 255, 255))
                if float(cv2.bitwise_or(red1, red2).mean()) / 255.0 > 0.04:
                    return False
            return True
        return False

    def classify(self, frame: np.ndarray) -> ScreenType:
        if self._template_visible(frame, "loading"):
            return ScreenType.LOADING

        # Results before live-battle — green Return Home must win over tray heuristics.
        if self._looks_like_battle_results(frame):
            return ScreenType.BATTLE_RESULTS

        # Live battle / scout (army tray, Next, End Battle).
        if self._looks_like_battle(frame):
            return ScreenType.BATTLE

        if self._template_visible(frame, "return_home") or self._template_visible(
            frame, "battle_end"
        ):
            return ScreenType.BATTLE_RESULTS

        # Attack picker also dims the village + shows a green Battle button — detect
        # it before the generic popup heuristic so we do not "dismiss" Attack.
        if self._looks_like_attack_menu(frame):
            return ScreenType.ATTACK_MENU

        if self.looks_like_blocking_popup(frame):
            return ScreenType.POPUP

        # Prefer chat/donation before matchmaking — donation bars look like army bars.
        if self._clan_chat_anchor_visible(frame):
            return ScreenType.CLAN_CHAT

        if self._in_clan_chat_context(frame) and self._donation_panel_heuristic(frame):
            return ScreenType.DONATION_PANEL

        if self._in_clan_chat_context(frame):
            return ScreenType.CLAN_CHAT

        if self._looks_like_matchmaking(frame):
            return ScreenType.MATCHMAKING

        if self._is_home_screen(frame):
            return ScreenType.HOME

        return ScreenType.UNKNOWN

    def is_donation_panel(self, frame: np.ndarray) -> bool:
        return self.classify(frame) == ScreenType.DONATION_PANEL

    def wait_for_donation_panel(self, capture, timeout_seconds: float = 3.0, poll_interval: float = 0.35) -> bool:
        """Poll until donation panel appears or timeout."""
        import time

        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            frame = capture.screenshot()
            if self.is_donation_panel(frame):
                return True
            time.sleep(poll_interval)
        return False
