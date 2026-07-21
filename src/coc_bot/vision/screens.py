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

    def _clan_chat_anchor_visible(self, frame: np.ndarray) -> bool:
        """Calibrated anchor visible in chat but hidden when the donation panel is open."""
        return self._template_visible(frame, "clan_chat")

    def _donation_panel_heuristic(self, frame: np.ndarray) -> bool:
        """Fallback when clan_chat anchor is obscured by the donation popup."""
        if self._template_visible(frame, "donation_panel"):
            return True

        from coc_bot.vision.rois import crop_roi

        if "donation_troop_bar" in self.config.rois:
            bar = crop_roi(frame, self.config.rois["donation_troop_bar"])
            if float(np.std(bar)) > 20:
                return True

        if "donation_spell_bar" in self.config.rois:
            spell = crop_roi(frame, self.config.rois["donation_spell_bar"])
            if float(np.std(spell)) > 20:
                return True

        return False

    def classify(self, frame: np.ndarray) -> ScreenType:
        # clan_chat anchor wins over troop-bar variance — chat UI can look "busy"
        # in the troop bar ROI even when no donation panel is open.
        if self._clan_chat_anchor_visible(frame):
            return ScreenType.CLAN_CHAT

        if self._donation_panel_heuristic(frame):
            return ScreenType.DONATION_PANEL

        checks = [
            ("loading", ScreenType.LOADING),
            ("home", ScreenType.HOME),
            ("popup_dismiss", ScreenType.POPUP),
            ("popup", ScreenType.POPUP),
        ]
        for template_key, screen_type in checks:
            if self._template_visible(frame, template_key):
                return screen_type

        if "chat_panel" in self.config.rois:
            from coc_bot.vision.rois import crop_roi

            chat = crop_roi(frame, self.config.rois["chat_panel"])
            if float(np.std(chat)) > 15:
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
