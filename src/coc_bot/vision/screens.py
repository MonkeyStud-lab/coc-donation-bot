from __future__ import annotations

import time
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
    LIVE_REPLAY = "live_replay"
    UNKNOWN = "unknown"


class BotMode(str, Enum):
    """
    High-level flow context — restricts which screens classify() will return.

    HOME:   village only → open chat or open Attack
    DONATE: clan chat / donation only
    ATTACK: attack menu → battle → results
    ANY:    full unrestricted classify (boot / recovery)
    """

    HOME = "home"
    DONATE = "donate"
    ATTACK = "attack"
    ANY = "any"


# Short labels for the control panel “what screen is this?” line.
SCREEN_LABELS: dict[str, str] = {
    ScreenType.HOME.value: "Home (village)",
    ScreenType.CLAN_CHAT.value: "Clan chat",
    ScreenType.DONATION_PANEL.value: "Donation panel",
    ScreenType.LOADING.value: "Loading",
    ScreenType.POPUP.value: "Popup",
    ScreenType.ATTACK_MENU.value: "Attack menu",
    ScreenType.MATCHMAKING.value: "Matchmaking",
    ScreenType.BATTLE.value: "Battle / scout",
    ScreenType.BATTLE_RESULTS.value: "Battle results",
    ScreenType.LIVE_REPLAY.value: "Live replay (defense)",
    ScreenType.UNKNOWN.value: "Unknown",
}

MODE_LABELS: dict[str, str] = {
    BotMode.HOME.value: "Home",
    BotMode.DONATE.value: "Donate",
    BotMode.ATTACK.value: "Attack",
    BotMode.ANY.value: "Any",
}


def screen_display_name(screen: ScreenType | str) -> str:
    key = screen.value if isinstance(screen, ScreenType) else str(screen)
    return SCREEN_LABELS.get(key, key)


class ScreenClassifier:
    """Classify current game screen using calibrated anchor templates."""

    # Shared across instances — Live Replay only after we relaunch Clash.
    _live_replay_armed_until: float = 0.0

    @classmethod
    def arm_live_replay_watch(cls, duration_seconds: float = 240.0) -> None:
        """
        Allow Live Replay detection for a short window after opening Clash.

        Defenses show up right after relaunch (e.g. post mandatory break). Mid-session
        farm/donate must never misread a screen as Live Replay.
        """
        cls._live_replay_armed_until = time.monotonic() + max(0.0, duration_seconds)
        from loguru import logger

        logger.info(
            "Live Replay watch armed for {:.0f}s (only after Clash relaunch)",
            duration_seconds,
        )

    @classmethod
    def disarm_live_replay_watch(cls) -> None:
        cls._live_replay_armed_until = 0.0

    @classmethod
    def live_replay_watch_armed(cls) -> bool:
        return time.monotonic() < cls._live_replay_armed_until

    def __init__(self, config: BotConfig, matcher: TemplateMatcher | None = None) -> None:
        self.config = config
        self.matcher = matcher or TemplateMatcher(threshold=config.template_threshold)
        self._donation_panel_matcher = TemplateMatcher(threshold=config.donation_panel_threshold)
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
        if template is None:
            return False
        if key == "donation_panel":
            return self._donation_panel_matcher.find(frame, template) is not None
        return self.matcher.find(frame, template) is not None

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

    def _has_white_donation_card(self, frame: np.ndarray) -> bool:
        """
        Large light-gray/white donation popup card (center-right).

        Distinct from clan chat (darker) and battle results (no such card).
        Thresholds are strict on purpose — clan chat can have light message bubbles.
        """
        h, w = frame.shape[:2]
        y0, y1 = int(h * 0.12), int(h * 0.88)
        x0, x1 = int(w * 0.32), int(w * 0.96)
        crop = frame[y0:y1, x0:x1]
        if crop.size == 0:
            return False
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        light = cv2.inRange(gray, 185, 255)
        light_frac = float(light.mean()) / 255.0
        if light_frac < 0.48:
            return False
        contours, _ = cv2.findContours(light, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return False
        largest = max(contours, key=cv2.contourArea)
        area_frac = float(cv2.contourArea(largest)) / float(crop.shape[0] * crop.shape[1])
        if area_frac < 0.50:
            return False
        _bx, _by, bw, bh = cv2.boundingRect(largest)
        return bw > crop.shape[1] * 0.55 and bh > crop.shape[0] * 0.55

    def _donation_resource_title_visible(self, frame: np.ndarray) -> bool:
        """
        True if the unique \"Donation Resource\" header is readable.

        Uses a small top-of-panel crop + tesseract when available (fast). EasyOCR
        is skipped here so wait_for_donation_panel stays snappy.
        """
        import re
        import shutil
        import subprocess
        import tempfile
        from pathlib import Path

        if shutil.which("tesseract") is None:
            return False
        h, w = frame.shape[:2]
        # Title sits on the top-left of the white card.
        crop = frame[int(h * 0.07) : int(h * 0.22), int(w * 0.30) : int(w * 0.70)]
        if crop.size == 0:
            return False
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        # Dark outline text on light card — boost contrast for OCR.
        up = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
        _, bw = cv2.threshold(up, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "title.png"
                cv2.imwrite(str(path), bw)
                proc = subprocess.run(  # noqa: S603
                    [
                        "tesseract",
                        str(path),
                        "stdout",
                        "--psm",
                        "7",
                        "-l",
                        "eng",
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=3,
                )
            text = (proc.stdout or "").lower()
        except (OSError, subprocess.TimeoutExpired):
            return False
        compact = re.sub(r"[^a-z]", "", text)
        return "donation" in compact and "resource" in compact

    def _donation_panel_heuristic(self, frame: np.ndarray) -> bool:
        """
        Donation popup over clan chat.

        Prefer template / \"Donation Resource\" title. A white card alone is not
        enough (clan chat light areas false-positive). Troop+spell bars confirm.
        """
        from loguru import logger as _log
        # Battle results silhouettes / card — never a donation panel.
        if self.looks_like_results_side_silhouettes(frame):
            _log.debug("donation_panel_heuristic: vetoed by results silhouettes")
            return False
        if self._looks_like_battle_results(frame):
            _log.debug("donation_panel_heuristic: vetoed by battle results")
            return False
        if self._open_chat_icon_visible(frame) or self._home_attack_chip_visible(frame):
            _log.debug("donation_panel_heuristic: vetoed by home icons (open_chat or attack chip)")
            return False
        # Check template / OCR BEFORE the clan-chat context veto.
        # The donation panel opens as a modal OVER clan chat — the chat panel
        # is still partially visible behind it, keeping chat_panel ROI std
        # high.  Checking the template first avoids a false veto.
        if self._template_visible(frame, "donation_panel"):
            _log.debug("donation_panel_heuristic: DETECTED via donation_panel template")
            return True
        if self._donation_resource_title_visible(frame):
            _log.debug("donation_panel_heuristic: DETECTED via Donation Resource OCR")
            return True
        # Clan-chat anchor is covered by the popup — if it is still visible, we
        # are still in chat, not on the donation panel.
        if self._clan_chat_anchor_visible(frame):
            _log.debug("donation_panel_heuristic: vetoed by clan_chat anchor template")
            return False
        if self._in_clan_chat_context(frame):
            _log.debug("donation_panel_heuristic: vetoed by clan_chat context (chat_panel ROI std > 22)")
            return False

        troop_std = self._roi_std(frame, "donation_troop_bar")
        spell_std = self._roi_std(frame, "donation_spell_bar")
        _log.debug("donation_panel_heuristic: bar ROIs troop_std={} spell_std={}",
                    f"{troop_std:.1f}" if troop_std is not None else "None",
                    f"{spell_std:.1f}" if spell_std is not None else "None")
        if troop_std is None or spell_std is None:
            return False

        has_card = self._has_white_donation_card(frame)

        # White card + busy bars — real donation popup.
        if has_card and troop_std > 28 and spell_std > 28:
            _log.debug("donation_panel_heuristic: DETECTED via white card + bars")
            return True

        # Strong dual-bar signal without relying on the white-card detector.
        if troop_std > 40 and spell_std > 40:
            _log.debug("donation_panel_heuristic: DETECTED via strong dual-bar signal")
            return True

        # Weaker path: bars + dimmed overlay, and not a Return Home results card.
        if self.find_return_home_button(frame) is not None:
            _log.debug("donation_panel_heuristic: vetoed by return_home button")
            return False
        if troop_std > 30 and spell_std > 30 and self._has_dimmed_modal_overlay(frame):
            _log.debug("donation_panel_heuristic: DETECTED via bars + dimmed overlay")
            return True
        _log.debug("donation_panel_heuristic: no signal — returning False")
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
        """True for Welcome Back / event / news / Star Bonus modals that block play."""
        if self._template_visible(frame, "popup_dismiss") or self._template_visible(frame, "popup"):
            return True
        # Dimmed overlay alone can false-match busy villages; require the green Okay/Claim too.
        return self._has_dimmed_modal_overlay(frame) and self._has_green_dialog_button(frame)

    def looks_like_live_replay(self, frame: np.ndarray) -> bool:
        """
        Spectator view while someone attacks *our* village (Live Replay).

        Only considered after Clash was just opened (mandatory-break relaunch).
        """
        if not self.live_replay_watch_armed():
            return False
        if self._open_chat_icon_visible(frame) or self._home_attack_chip_visible(frame):
            return False
        h, w = frame.shape[:2]

        # Red \"Live Replay\" badge — bottom-right.
        br = frame[int(h * 0.80) : int(h * 0.98), int(w * 0.52) : int(w * 0.98)]
        red_frac = 0.0
        if br.size:
            hsv_br = cv2.cvtColor(br, cv2.COLOR_BGR2HSV)
            r1 = cv2.inRange(hsv_br, (0, 90, 90), (10, 255, 255))
            r2 = cv2.inRange(hsv_br, (170, 90, 90), (180, 255, 255))
            red_frac = float(cv2.bitwise_or(r1, r2).mean()) / 255.0

        # Right side often has the large villager / \"is attacking\" graphic.
        right = frame[int(h * 0.12) : int(h * 0.72), int(w * 0.62) : int(w * 0.98)]
        portrait = False
        if right.size:
            hsv_r = cv2.cvtColor(right, cv2.COLOR_BGR2HSV)
            # Skin / warm illustration tones + bright regions.
            skin = cv2.inRange(hsv_r, (5, 40, 80), (30, 200, 255))
            bright = cv2.cvtColor(right, cv2.COLOR_BGR2GRAY)
            portrait = float(skin.mean()) / 255.0 > 0.04 and float((bright > 180).mean()) > 0.08

        if red_frac > 0.03 and portrait:
            return True

        # OCR fallback — \"live replay\" / \"attacking your village\".
        if red_frac > 0.02 or portrait:
            if self._live_replay_ocr_visible(frame):
                return True
        return False

    def _live_replay_ocr_visible(self, frame: np.ndarray) -> bool:
        import re
        import shutil
        import subprocess
        import tempfile
        from pathlib import Path

        if shutil.which("tesseract") is None:
            return False
        h, w = frame.shape[:2]
        # Bottom-right badge + mid-right speech area.
        crops = [
            frame[int(h * 0.78) : int(h * 0.98), int(w * 0.45) : w],
            frame[int(h * 0.35) : int(h * 0.70), int(w * 0.55) : w],
        ]
        for crop in crops:
            if crop.size == 0:
                continue
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            up = cv2.resize(gray, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC)
            try:
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / "replay.png"
                    cv2.imwrite(str(path), up)
                    proc = subprocess.run(  # noqa: S603
                        ["tesseract", str(path), "stdout", "--psm", "6", "-l", "eng"],
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=3,
                    )
                text = re.sub(r"[^a-z]", "", (proc.stdout or "").lower())
            except (OSError, subprocess.TimeoutExpired):
                continue
            if "livereplay" in text or ("attacking" in text and "village" in text):
                return True
        return False

    def looks_like_surrender_dialog(self, frame: np.ndarray) -> bool:
        """
        Mid-battle Surrender confirm (Cancel orange + Okay green).

        Triggered by Android BACK / red Surrender — must Cancel, never Okay.
        """
        h, w = frame.shape[:2]
        # Button row on the centered card.
        y0, y1 = int(h * 0.50), int(h * 0.72)
        x0, x1 = int(w * 0.28), int(w * 0.72)
        crop = frame[y0:y1, x0:x1]
        if crop.size == 0:
            return False
        mid = crop.shape[1] // 2
        left, right = crop[:, :mid], crop[:, mid:]
        hsv_l = cv2.cvtColor(left, cv2.COLOR_BGR2HSV)
        hsv_r = cv2.cvtColor(right, cv2.COLOR_BGR2HSV)
        orange = cv2.inRange(hsv_l, (5, 90, 90), (28, 255, 255))
        green = cv2.inRange(hsv_r, (35, 90, 80), (90, 255, 255))
        orange_frac = float(orange.mean()) / 255.0
        green_frac = float(green.mean()) / 255.0
        if orange_frac < 0.035 or green_frac < 0.035:
            return False
        # Live battle chrome still visible (timer / army bar) under the dim.
        return self._looks_like_battle(frame) or self._has_dimmed_modal_overlay(frame)

    def find_surrender_cancel_button(self, frame: np.ndarray) -> tuple[int, int] | None:
        """Orange Cancel on the Surrender dialog (left of the green Okay)."""
        h, w = frame.shape[:2]
        y0, y1 = int(h * 0.50), int(h * 0.72)
        x0, x1 = int(w * 0.28), int(w * 0.52)
        crop = frame[y0:y1, x0:x1]
        if crop.size == 0:
            return None
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        orange = cv2.inRange(hsv, (5, 90, 90), (28, 255, 255))
        orange = cv2.morphologyEx(
            orange, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (9, 7))
        )
        contours, _ = cv2.findContours(orange, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return (int(w * 0.38), int(h * 0.60))
        largest = max(contours, key=cv2.contourArea)
        if float(cv2.contourArea(largest)) < crop.shape[0] * crop.shape[1] * 0.01:
            return (int(w * 0.38), int(h * 0.60))
        bx, by, bw, bh = cv2.boundingRect(largest)
        return int(x0 + bx + bw / 2), int(y0 + by + bh / 2)

    def _home_blocking_popup(self, frame: np.ndarray) -> bool:
        """
        Home-village modal (Star Bonus, news, etc.) with Attack! / chat still visible.

        Must win over HOME classification — those chips show through the dimmed backdrop.
        """
        if not self.looks_like_blocking_popup(frame):
            return False
        return self._open_chat_icon_visible(frame) or self._home_attack_chip_visible(frame)

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
        """Opponent-search screen — template or upper-half blue sky heuristic."""
        if self._template_visible(frame, "matchmaking") or self._template_visible(frame, "find_match"):
            return True
        if self._home_attack_chip_visible(frame) or self._open_chat_icon_visible(frame):
            return False
        if self._is_home_screen(frame):
            return False
        return self._matchmaking_sky_band(frame)

    def _matchmaking_sky_band(self, frame: np.ndarray) -> bool:
        """Upper-half blue + white typical of Find a Match / searching."""
        h, w = frame.shape[:2]
        crop = frame[0 : int(h * 0.45), int(w * 0.15) : int(w * 0.85)]
        if crop.size == 0:
            return False
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        blue = cv2.inRange(hsv, (90, 40, 120), (130, 255, 255))
        white = cv2.inRange(hsv, (0, 0, 200), (180, 60, 255))
        blue_frac = float(blue.mean()) / 255.0
        sky_frac = float((blue | white).mean()) / 255.0
        return sky_frac > 0.45 and blue_frac > 0.08

    def _home_attack_chip_visible(self, frame: np.ndarray) -> bool:
        """Orange/gold Attack! button bottom-left on the village — not End Battle."""
        h, w = frame.shape[:2]
        bl = frame[int(h * 0.78) : h, 0 : int(w * 0.14)]
        if bl.size == 0:
            return False
        hsv = cv2.cvtColor(bl, cv2.COLOR_BGR2HSV)
        warm = cv2.inRange(hsv, (5, 70, 70), (35, 255, 255))
        return float(warm.mean()) / 255.0 > 0.08

    def _live_battle_chrome_visible(self, frame: np.ndarray) -> bool:
        """
        True while a live attack/scout still shows End Battle / Surrender or Next.

        Used to veto false \"Return Home\" / results detections mid-fight.
        Never true when village home anchors are visible (Attack! / open chat) —
        home scenery (red roofs, orange UI) otherwise false-triggers this.
        Never true on battle-results side silhouettes.
        """
        if self._home_attack_chip_visible(frame) or self._open_chat_icon_visible(frame):
            return False
        if self._clan_chat_anchor_visible(frame):
            return False
        if self.looks_like_results_side_silhouettes(frame):
            return False

        h, w = frame.shape[:2]
        # Red End Battle / Surrender chip — bottom-left above the army bar.
        end_roi = frame[int(h * 0.70) : h, 0 : int(w * 0.24)]
        if end_roi.size:
            hsv_e = cv2.cvtColor(end_roi, cv2.COLOR_BGR2HSV)
            red1 = cv2.inRange(hsv_e, (0, 70, 70), (12, 255, 255))
            red2 = cv2.inRange(hsv_e, (168, 70, 70), (180, 255, 255))
            if float(cv2.bitwise_or(red1, red2).mean()) / 255.0 > 0.02:
                return True
        # Orange Next on the right (scout before deploy).
        next_roi = frame[int(h * 0.50) : int(h * 0.92), int(w * 0.78) : w]
        if next_roi.size:
            hsv_n = cv2.cvtColor(next_roi, cv2.COLOR_BGR2HSV)
            nxt = cv2.inRange(hsv_n, (5, 80, 80), (30, 255, 255))
            if float(nxt.mean()) / 255.0 > 0.045:
                return True
        return False

    def find_return_home_button(
        self,
        frame: np.ndarray,
        *,
        require_no_live_chrome: bool = True,
    ) -> tuple[int, int] | None:
        """
        Tap target for the green Return Home button on defeat/victory.

        Prefers a wide green CTA in the lower center (not other green UI).
        By default never matches while live End Battle / Next chrome is still on
        screen (avoids scenery greens mid-fight). Pass
        ``require_no_live_chrome=False`` when leave logic needs to see the CTA
        even if red/orange scenery falsely trips the chrome heuristic.

        Never matches when village home anchors are visible — home greens
        (buttons, grass, shops) often look like Return Home.
        """
        if self._home_attack_chip_visible(frame) or self._open_chat_icon_visible(frame):
            return None
        if self._clan_chat_anchor_visible(frame):
            return None
        if require_no_live_chrome and self._live_battle_chrome_visible(frame):
            return None
        return self._find_return_home_green_cta(frame)

    def _find_return_home_green_cta(self, frame: np.ndarray) -> tuple[int, int] | None:
        """Locate the wide green Return Home pill (no live-chrome veto)."""
        h, w = frame.shape[:2]
        # Button sits bottom-center of the results card — keep ROI tight & centered.
        x0, x1 = int(w * 0.32), int(w * 0.68)
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
        min_area = crop.shape[0] * crop.shape[1] * 0.025
        crop_cx = crop.shape[1] / 2.0

        def _score(c: np.ndarray) -> float:
            area = float(cv2.contourArea(c))
            if area < min_area:
                return -1.0
            bx, by, bw, bh = cv2.boundingRect(c)
            if bh < 10 or bw < 60:
                return -1.0
            aspect = bw / float(bh)
            if aspect < 1.8:
                return -1.0
            # Prefer wide pills near horizontal center — reject far-right green junk.
            cx = bx + bw / 2.0
            if abs(cx - crop_cx) > crop.shape[1] * 0.28:
                return -1.0
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
        # Victory/defeat summary — side silhouettes / results card, not live fight.
        if self.looks_like_results_side_silhouettes(frame):
            return False
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

    def looks_like_results_side_silhouettes(self, frame: np.ndarray) -> bool:
        """
        Huge near-black character silhouettes on the left and right of battle results.

        Defeat/Victory screens frame the loot card with opaque black Archer/Wizard
        (etc.) cutouts. Donation panels and live battles do not have these.
        """
        h, w = frame.shape[:2]
        y0, y1 = int(h * 0.22), int(h * 0.96)
        left = frame[y0:y1, 0 : int(w * 0.14)]
        right = frame[y0:y1, int(w * 0.86) : w]
        if left.size == 0 or right.size == 0:
            return False

        def _near_black_frac(crop: np.ndarray) -> float:
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            # Solid silhouette ink — very dark, low variance blobs.
            return float((gray < 45).mean())

        left_frac = _near_black_frac(left)
        right_frac = _near_black_frac(right)
        # Both edges must be heavily inked (one side alone can be night scenery).
        return left_frac > 0.28 and right_frac > 0.28

    def _looks_like_battle_results(self, frame: np.ndarray) -> bool:
        """
        End-of-attack screen with a large green Return Home / OK button.

        Distinct from live scout/battle: no Next, no End Battle, big green CTA.
        Must NOT match clan chat / Donate button screens.
        Side silhouettes are a strong modern CoC results cue.
        """
        # Still fighting — never results (unless silhouettes prove results card).
        if self.looks_like_live_replay(frame):
            return False
        # Real chat/donate / home UI — never Return Home.
        if self._open_chat_icon_visible(frame) or self._home_attack_chip_visible(frame):
            return False
        if self._clan_chat_anchor_visible(frame):
            return False
        if self._template_visible(frame, "donate_button"):
            return False

        if self.looks_like_results_side_silhouettes(frame):
            return True

        if self._live_battle_chrome_visible(frame):
            return False

        if self._template_visible(frame, "return_home") or self._template_visible(
            frame, "battle_end"
        ):
            return True
        return self.find_return_home_button(frame) is not None

    def classify(self, frame: np.ndarray, mode: BotMode | None = None) -> ScreenType:
        """
        Classify the current frame.

        When ``mode`` is set, only screens that belong to that flow are considered
        (plus loading). Pass ``BotMode.ANY`` or ``None`` for a full scan
        (boot / recovery / debug). Popup is checked late so Attack menu
        green buttons are not mistaken for a blocking modal.
        """
        if self._template_visible(frame, "loading"):
            return ScreenType.LOADING

        effective = mode if mode is not None else BotMode.ANY
        if effective == BotMode.HOME:
            return self._classify_home(frame)
        if effective == BotMode.DONATE:
            return self._classify_donate(frame)
        if effective == BotMode.ATTACK:
            return self._classify_attack(frame)
        return self._classify_any(frame)

    def _classify_home(self, frame: np.ndarray) -> ScreenType:
        """Village only: home or Attack menu — never battle results / donation."""
        if self.looks_like_live_replay(frame):
            return ScreenType.LIVE_REPLAY
        if self._home_blocking_popup(frame):
            return ScreenType.POPUP
        if self._looks_like_attack_menu(frame):
            return ScreenType.ATTACK_MENU
        if self._open_chat_icon_visible(frame) or self._home_attack_chip_visible(frame):
            return ScreenType.HOME
        if self._is_home_screen(frame):
            return ScreenType.HOME
        if self.looks_like_blocking_popup(frame):
            return ScreenType.POPUP
        return ScreenType.UNKNOWN

    def _classify_donate(self, frame: np.ndarray) -> ScreenType:
        """Clan chat / donation only — never battle results or live battle."""
        if self.looks_like_live_replay(frame):
            return ScreenType.LIVE_REPLAY
        if self._home_blocking_popup(frame):
            return ScreenType.POPUP
        # Farm leave can land here with results still up — never treat as donate UI.
        if self._looks_like_battle_results(frame) or self.looks_like_results_side_silhouettes(
            frame
        ):
            return ScreenType.BATTLE_RESULTS
        if self._donation_panel_heuristic(frame):
            return ScreenType.DONATION_PANEL
        if self._clan_chat_anchor_visible(frame):
            return ScreenType.CLAN_CHAT
        if self._template_visible(frame, "donate_button"):
            return ScreenType.CLAN_CHAT
        if self._in_clan_chat_context(frame):
            return ScreenType.CLAN_CHAT
        # Drifted to village — allow opening chat again.
        if self._open_chat_icon_visible(frame) or self._home_attack_chip_visible(frame):
            return ScreenType.HOME
        if self._is_home_screen(frame):
            return ScreenType.HOME
        if self.looks_like_blocking_popup(frame):
            return ScreenType.POPUP
        return ScreenType.UNKNOWN

    def _classify_attack(self, frame: np.ndarray) -> ScreenType:
        """Attack flow only — never donation panel / donate-button chat heuristics."""
        # Someone attacking *us* — wait it out, never farm Return Home.
        if self.looks_like_live_replay(frame):
            return ScreenType.LIVE_REPLAY

        # Attack! / open-chat mean village home — reconsider before results/battle.
        # After Return Home, home greens and red roofs otherwise look like results.
        if self._home_blocking_popup(frame):
            return ScreenType.POPUP
        if self._open_chat_icon_visible(frame) or self._home_attack_chip_visible(frame):
            return ScreenType.HOME

        # Side silhouettes / results card before live-battle chrome (Defeat red text
        # and troop icons otherwise look like a live fight).
        if self._looks_like_battle_results(frame) or self.looks_like_results_side_silhouettes(
            frame
        ):
            return ScreenType.BATTLE_RESULTS
        if self._template_visible(frame, "return_home") or self._template_visible(
            frame, "battle_end"
        ):
            return ScreenType.BATTLE_RESULTS

        # Live End Battle / Next wins over any false Return Home green blob.
        if self._live_battle_chrome_visible(frame):
            return ScreenType.BATTLE
        if self._looks_like_battle(frame):
            return ScreenType.BATTLE
        if self._looks_like_matchmaking(frame):
            return ScreenType.MATCHMAKING
        if self._looks_like_attack_menu(frame):
            return ScreenType.ATTACK_MENU
        if self._is_home_screen(frame):
            return ScreenType.HOME
        if self.looks_like_blocking_popup(frame):
            return ScreenType.POPUP
        return ScreenType.UNKNOWN

    def _classify_any(self, frame: np.ndarray) -> ScreenType:
        """Full unrestricted classify (boot / recovery)."""
        # Star Bonus / Welcome Back — Attack! shows through the dimmed village.
        if self._home_blocking_popup(frame):
            return ScreenType.POPUP

        if self.looks_like_live_replay(frame):
            return ScreenType.LIVE_REPLAY

        # Village home first.
        if self._open_chat_icon_visible(frame):
            return ScreenType.HOME

        if self._home_attack_chip_visible(frame) and not self._looks_like_battle(frame):
            if self._looks_like_attack_menu(frame):
                return ScreenType.ATTACK_MENU
            return ScreenType.HOME

        # Battle results (silhouettes) before donation panel — results loot card
        # otherwise looks like a white donation popup.
        if self._looks_like_battle_results(frame) or self.looks_like_results_side_silhouettes(
            frame
        ):
            return ScreenType.BATTLE_RESULTS
        if self._template_visible(frame, "return_home") or self._template_visible(
            frame, "battle_end"
        ):
            return ScreenType.BATTLE_RESULTS

        # Donation popup before clan_chat anchor.
        if self._donation_panel_heuristic(frame):
            return ScreenType.DONATION_PANEL

        if self._clan_chat_anchor_visible(frame):
            return ScreenType.CLAN_CHAT

        if self._template_visible(frame, "donate_button"):
            return ScreenType.CLAN_CHAT

        if self._in_clan_chat_context(frame):
            return ScreenType.CLAN_CHAT

        if self._live_battle_chrome_visible(frame):
            return ScreenType.BATTLE

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
        """True when the donate popup is up (does not require full classify)."""
        return self._donation_panel_heuristic(frame)

    def wait_for_donation_panel(
        self,
        capture,
        timeout_seconds: float = 3.0,
        poll_interval: float = 0.35,
        should_stop=None,
    ) -> bool:
        """Poll until donation panel appears, timeout, or stop requested."""
        import time

        from coc_bot.stop import interrupted_sleep

        deadline = time.time() + timeout_seconds
        last_frame = None
        while time.time() < deadline:
            if should_stop and should_stop():
                return False
            last_frame = capture.screenshot()
            if self.is_donation_panel(last_frame):
                return True
            if interrupted_sleep(poll_interval, should_stop):
                return False
        if last_frame is not None:
            from loguru import logger

            troop = self._roi_std(last_frame, "donation_troop_bar")
            spell = self._roi_std(last_frame, "donation_spell_bar")
            logger.debug(
                "Donation panel wait timed out (troop_std={}, spell_std={}, screen={})",
                f"{troop:.1f}" if troop is not None else "n/a",
                f"{spell:.1f}" if spell is not None else "n/a",
                self.classify(last_frame, mode=BotMode.DONATE).value,
            )
        return False
