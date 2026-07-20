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

    def classify(self, frame: np.ndarray) -> ScreenType:
        # Donation panel: check panel UI elements captured during calibration
        for panel_key in ("donation_panel", "panel_close", "quick_donate"):
            template = self._load(panel_key)
            if template is not None and self.matcher.find(frame, template) is not None:
                return ScreenType.DONATION_PANEL

        checks = [
            ("clan_chat", ScreenType.CLAN_CHAT),
            ("loading", ScreenType.LOADING),
            ("home", ScreenType.HOME),
            ("popup_dismiss", ScreenType.POPUP),
            ("popup", ScreenType.POPUP),
        ]
        for template_key, screen_type in checks:
            template = self._load(template_key)
            if template is not None and self.matcher.find(frame, template) is not None:
                return screen_type

        # Heuristic fallbacks using ROIs
        if "donation_troop_bar" in self.config.rois:
            from coc_bot.vision.rois import crop_roi

            bar = crop_roi(frame, self.config.rois["donation_troop_bar"])
            if float(np.std(bar)) > 20:
                return ScreenType.DONATION_PANEL

        if "chat_panel" in self.config.rois:
            from coc_bot.vision.rois import crop_roi

            chat = crop_roi(frame, self.config.rois["chat_panel"])
            if float(np.std(chat)) > 15:
                return ScreenType.CLAN_CHAT

        return ScreenType.UNKNOWN
