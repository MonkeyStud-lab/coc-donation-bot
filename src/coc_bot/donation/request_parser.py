from __future__ import annotations

import cv2
import numpy as np
from loguru import logger

from coc_bot.config import BotConfig
from coc_bot.vision.matcher import MatchResult


class RequestParser:
    """Detect specific vs open donation requests from clan chat messages."""

    def __init__(self, config: BotConfig, *, debug: bool = False) -> None:
        self.config = config
        self.debug = debug

    def has_requested_icons_in_chat(self, frame: np.ndarray, donate_button: MatchResult) -> bool:
        """
        True when the chat bubble shows a row of requested unit/spell icons.

        Open requests only show the three capacity bars (troop/spell/siege) — no unit icon row.
        Specific requests add a row of small colorful unit icons just above the Donate button.
        """
        region = self._chat_message_region(frame, donate_button)
        if region.size == 0:
            return False

        h, _w = region.shape[:2]
        # Requested unit icons sit in a narrow band directly above the Donate button.
        # Capacity bars (sword/potion/siege + progress) are higher up and must be ignored.
        strip = region[int(h * 0.68) : int(h * 0.92), :]
        if strip.size == 0:
            return False

        cols = 20
        sw = max(1, strip.shape[1] // cols)
        icon_cols: list[int] = []
        for col in range(cols):
            cell = strip[:, col * sw : (col + 1) * sw]
            if cell.size == 0:
                continue
            if self._looks_like_unit_icon(cell):
                icon_cols.append(col)

        max_run = self._max_consecutive_run(icon_cols)
        is_specific = len(icon_cols) >= 4 and max_run >= 2

        if self.debug:
            logger.debug(
                "Request icon strip: icon_cols={}/{} max_run={} -> specific={}",
                len(icon_cols),
                cols,
                max_run,
                is_specific,
            )

        return is_specific

    @staticmethod
    def _looks_like_unit_icon(cell: np.ndarray) -> bool:
        """Detect a colorful game icon slice — not grey progress bars or chat background."""
        gray = cv2.cvtColor(cell, cv2.COLOR_BGR2GRAY)
        if float(np.std(gray)) < 22:
            return False

        hsv = cv2.cvtColor(cell, cv2.COLOR_BGR2HSV)
        sat = hsv[:, :, 1]
        val = hsv[:, :, 2]
        mean_sat = float(np.mean(sat))
        mean_val = float(np.mean(val))

        # Progress bars and empty bubble are low-saturation; unit icons are vivid.
        if mean_sat < 55:
            return False
        if mean_val < 40:
            return False

        # Reject pale/beige chat bubble background even when it has slight texture.
        bgr = cell.reshape(-1, 3).astype(np.float32)
        if float(np.std(bgr[:, 0] - bgr[:, 1])) < 8 and mean_sat < 70:
            return False

        return True

    @staticmethod
    def _max_consecutive_run(cols: list[int]) -> int:
        if not cols:
            return 0
        best = 1
        run = 1
        for idx in range(1, len(cols)):
            if cols[idx] == cols[idx - 1] + 1:
                run += 1
                best = max(best, run)
            else:
                run = 1
        return best

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
