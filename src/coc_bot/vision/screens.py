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

    def classify(self, frame: np.ndarray) -> ScreenType:
        if self._template_visible(frame, "loading"):
            return ScreenType.LOADING

        if self.looks_like_blocking_popup(frame):
            return ScreenType.POPUP

        if self._is_home_screen(frame):
            return ScreenType.HOME

        if self._clan_chat_anchor_visible(frame):
            return ScreenType.CLAN_CHAT

        if self._in_clan_chat_context(frame) and self._donation_panel_heuristic(frame):
            return ScreenType.DONATION_PANEL

        if self._in_clan_chat_context(frame):
            return ScreenType.CLAN_CHAT

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
