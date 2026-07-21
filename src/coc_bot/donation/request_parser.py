from __future__ import annotations

import cv2
import numpy as np

from coc_bot.config import BotConfig
from coc_bot.vision.matcher import MatchResult


class RequestParser:
    """Detect specific vs open donation requests from clan chat messages."""

    def __init__(self, config: BotConfig) -> None:
        self.config = config

    def has_requested_icons_in_chat(self, frame: np.ndarray, donate_button: MatchResult) -> bool:
        """True when the chat bubble shows a row of requested unit/spell icons."""
        region = self._chat_message_region(frame, donate_button)
        if region.size == 0:
            return False

        h, _w = region.shape[:2]
        strip = region[int(h * 0.30) : int(h * 0.88), :]
        if strip.size == 0:
            return False

        cols = 12
        sw = max(1, strip.shape[1] // cols)
        icon_cells = 0
        for col in range(cols):
            cell = strip[:, col * sw : (col + 1) * sw]
            if cell.size == 0:
                continue
            gray = cv2.cvtColor(cell, cv2.COLOR_BGR2GRAY)
            if float(np.std(gray)) > 16:
                icon_cells += 1

        return icon_cells >= 2

    def _chat_message_region(self, frame: np.ndarray, donate_button: MatchResult) -> np.ndarray:
        """Crop the chat message bubble sitting above a Donate button."""
        h, w = frame.shape[:2]
        bx, by = donate_button.x, donate_button.y
        bw, bh = donate_button.width, donate_button.height

        msg_h = max(int(bh * 6), 80)
        y0 = max(0, by - msg_h)
        y1 = max(0, by - int(bh * 0.25))
        x0 = max(0, bx - bw * 2)
        x1 = min(w, bx + bw * 10)

        if y1 <= y0 or x1 <= x0:
            return np.array([])

        return frame[y0:y1, x0:x1].copy()
