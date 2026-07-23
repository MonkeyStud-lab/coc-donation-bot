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

    def _open_chat_icon_visible(self, frame: np.ndarray) -> bool:
        """
        True when the home-screen chat bubble / open-chat control is on screen.

        That icon is only on the village (chat closed). It disappears in battle,
        attack menus, and while clan chat is open — so it is the best home signal.
        """
        return self._template_visible(frame, "open_chat")

    def _is_home_screen(self, frame: np.ndarray) -> bool:
        # Primary: chat icon visible ⇒ village home with chat closed.
        if self._open_chat_icon_visible(frame):
            return True
        if self._template_visible(frame, "home"):
            return True
        # Weak fallback when only a tap point was calibrated (no open_chat image).
        if self.config.tap_points.get("open_chat") and not self._clan_chat_anchor_visible(frame):
            chat_std = self._roi_std(frame, "chat_panel")
            if chat_std is not None and chat_std <= 15:
                return True
        return False

    def _clan_chat_anchor_visible(self, frame: np.ndarray) -> bool:
        """Calibrated anchor visible in chat but hidden when the donation panel is open."""
        return self._template_visible(frame, "clan_chat")

    def _in_clan_chat_context(self, frame: np.ndarray) -> bool:
        """
        Chat panel area looks filled (clan chat open).

        Village home and attack-results cards often paint busy pixels into the
        chat ROI — never treat those as clan chat.
        """
        if self._open_chat_icon_visible(frame) or self._home_attack_chip_visible(frame):
            return False
        # Defeat/victory card sits where chat ROIs are — big green Return Home.
        if self.find_return_home_button(frame) is not None:
            return False
        chat_std = self._roi_std(frame, "chat_panel")
        return chat_std is not None and chat_std > 22

    def _donation_panel_heuristic(self, frame: np.ndarray) -> bool:
        """
        Donation popup over clan chat (troop + spell bars).

        Must not fire on village home, plain clan chat, or attack results.
        """
        if self._open_chat_icon_visible(frame) or self._home_attack_chip_visible(frame):
            return False
        # Results screen green CTA is not a donate bar.
        if self.find_return_home_button(frame) is not None:
            return False
        if self._template_visible(frame, "donation_panel"):
            return True

        troop_std = self._roi_std(frame, "donation_troop_bar")
        spell_std = self._roi_std(frame, "donation_spell_bar")

        # Both bars must look very structured; raise bar so chat/home/results do not match.
        if troop_std is None or spell_std is None:
            return False
        # Require a strong dual-bar signal only (dimmed overlay alone matches results cards).
        return troop_std > 50 and spell_std > 50

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

    def _home_attack_chip_visible(self, frame: np.ndarray) -> bool:
        """Orange/gold Attack! button bottom-left on the village — not End Battle."""
        h, w = frame.shape[:2]
        bl = frame[int(h * 0.78) : h, 0 : int(w * 0.14)]
        if bl.size == 0:
            return False
        hsv = cv2.cvtColor(bl, cv2.COLOR_BGR2HSV)
        warm = cv2.inRange(hsv, (5, 70, 70), (35, 255, 255))
        return float(warm.mean()) / 255.0 > 0.08

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

    def _looks_like_battle(self, frame: np.ndarray) -> bool:
        """
        True on opponent scout / live attack (army tray at bottom).

        Scout UI (before first deploy) shows: bottom troop cards, red End Battle
        (bottom-left), orange Next (right). Do NOT treat village home as battle —
        home has Attack! (orange) and a busy bottom bar that looks like an army tray.
        """
        if self._template_visible(frame, "battle"):
            return True
        if self._clan_chat_anchor_visible(frame):
            return False
        # Victory/defeat summary can show a troop icon — never treat as live battle.
        if self._looks_like_battle_results(frame):
            return False
        # Village home anchors / quiet chat panel — never battle.
        if self._is_home_screen(frame):
            return False

        h, w = frame.shape[:2]

        has_next = False
        # Orange "Next" (skip base) on the right — only on scout/battle, not home.
        next_roi = frame[int(h * 0.52) : int(h * 0.92), int(w * 0.80) : w]
        if next_roi.size:
            hsv_n = cv2.cvtColor(next_roi, cv2.COLOR_BGR2HSV)
            next_orange = cv2.inRange(hsv_n, (5, 90, 90), (28, 255, 255))
            has_next = float(next_orange.mean()) / 255.0 > 0.06

        has_end_battle = False
        # Red "End Battle" chip bottom-left — scout/battle only (not home Attack!).
        end_roi = frame[int(h * 0.78) : h, 0 : int(w * 0.20)]
        if end_roi.size:
            hsv_e = cv2.cvtColor(end_roi, cv2.COLOR_BGR2HSV)
            red1 = cv2.inRange(hsv_e, (0, 100, 80), (8, 255, 255))
            red2 = cv2.inRange(hsv_e, (170, 100, 80), (180, 255, 255))
            has_end_battle = float(cv2.bitwise_or(red1, red2).mean()) / 255.0 > 0.04

        # Clear scout/battle chrome wins immediately.
        if has_next or has_end_battle:
            return True

        # Village Attack! chip without Next/End Battle → home (or shop), not battle.
        if self._home_attack_chip_visible(frame):
            return False

        # Army tray along the bottom (cards / wood chrome) — only when Attack! is gone.
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

        structured = edge_frac > 0.04 and (dark_frac > 0.10 or brown_frac > 0.06)
        dark_tray = dark_frac > 0.25
        return structured or dark_tray

    def _looks_like_battle_results(self, frame: np.ndarray) -> bool:
        """
        End-of-attack screen with a large green Return Home / OK button.

        Distinct from live scout/battle: no Next, no End Battle, big green CTA.
        Must NOT match clan chat / Donate button screens.
        """
        # Real chat/donate UI — never Return Home.
        if self._open_chat_icon_visible(frame) or self._home_attack_chip_visible(frame):
            return False
        if self._clan_chat_anchor_visible(frame):
            return False
        if self._template_visible(frame, "donate_button"):
            return False

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

        # Village home first.
        if self._open_chat_icon_visible(frame):
            return ScreenType.HOME

        if self._home_attack_chip_visible(frame) and not self._looks_like_battle(frame):
            if self._looks_like_attack_menu(frame):
                return ScreenType.ATTACK_MENU
            return ScreenType.HOME

        # Strong chat anchors (not soft ROI heuristics).
        if self._clan_chat_anchor_visible(frame):
            return ScreenType.CLAN_CHAT

        if self._template_visible(frame, "donate_button"):
            if self._donation_panel_heuristic(frame):
                return ScreenType.DONATION_PANEL
            return ScreenType.CLAN_CHAT

        # Attack results: large green Return Home — before soft donation ROI matches.
        if self._looks_like_battle_results(frame):
            return ScreenType.BATTLE_RESULTS

        if self._template_visible(frame, "return_home") or self._template_visible(
            frame, "battle_end"
        ):
            return ScreenType.BATTLE_RESULTS

        # Soft donation / chat only after results are ruled out.
        if self._in_clan_chat_context(frame) and self._donation_panel_heuristic(frame):
            return ScreenType.DONATION_PANEL

        if self._in_clan_chat_context(frame):
            return ScreenType.CLAN_CHAT

        if self._is_home_screen(frame):
            return ScreenType.HOME

        if self._looks_like_battle(frame):
            return ScreenType.BATTLE

        if self._looks_like_attack_menu(frame):
            return ScreenType.ATTACK_MENU

        if self.looks_like_blocking_popup(frame):
            return ScreenType.POPUP

        if self._looks_like_matchmaking(frame):
            return ScreenType.MATCHMAKING

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
