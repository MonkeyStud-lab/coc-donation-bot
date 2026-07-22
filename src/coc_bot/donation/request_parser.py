from __future__ import annotations

from enum import Enum

import cv2
import numpy as np
from loguru import logger

from coc_bot.config import BotConfig
from coc_bot.donation.capacity_parser import RequestCapacity, chat_message_region
from coc_bot.vision.matcher import MatchResult


class RequestKind(str, Enum):
    SPECIFIC = "specific"
    OPEN = "open"
    HYBRID = "hybrid"


class RequestParser:
    """Detect specific vs open vs hybrid donation requests from clan chat messages."""

    def __init__(self, config: BotConfig, *, debug: bool = False) -> None:
        self.config = config
        self.debug = debug

    def has_requested_icons_in_chat(self, frame: np.ndarray, donate_button: MatchResult) -> bool:
        """True when the chat bubble shows a row of requested unit/spell icons (Phase 1 specific)."""
        return self.classify(frame, donate_button, capacity=None) == RequestKind.SPECIFIC

    def classify(
        self,
        frame: np.ndarray,
        donate_button: MatchResult,
        capacity: RequestCapacity | None = None,
    ) -> RequestKind:
        """
        Classify a donation request.

        - specific: clear row of requested icons (Phase 1 colored-slot path)
        - hybrid: some icons plus open capacity remaining
        - open: capacity bars only (no unit icon row)
        """
        icon_cols, max_run, max_cluster, left_only = self._icon_strip_stats(frame, donate_button)
        # Left-edge-only color (sword/potion/siege glyphs) is capacity chrome, not unit icons.
        if left_only:
            icon_cols = 0
            max_run = 0
            max_cluster = 0

        is_specific_row = icon_cols >= 4 and max_run <= 9 and max_cluster <= 10
        has_any_icons = icon_cols >= 1 and max_run <= 9 and max_cluster <= 10
        remaining = capacity.has_remaining if capacity is not None else False

        if is_specific_row:
            kind = RequestKind.SPECIFIC
        elif has_any_icons and (remaining or capacity is None):
            kind = RequestKind.HYBRID
        else:
            kind = RequestKind.OPEN

        if self.debug:
            logger.debug(
                "Request classify: icon_cols={} max_run={} max_cluster={} left_only={} remaining={} -> {}",
                icon_cols,
                max_run,
                max_cluster,
                left_only,
                remaining,
                kind.value,
            )
        return kind

    def _icon_strip_stats(
        self, frame: np.ndarray, donate_button: MatchResult
    ) -> tuple[int, int, int, bool]:
        """Return (icon_col_count, max_run, max_cluster, left_edge_only)."""
        region = self._chat_message_region(frame, donate_button)
        if region.size == 0:
            return 0, 0, 0, False

        h, _w = region.shape[:2]
        # Unit icons sit above the capacity-bar block. Capacity bars occupy the lower
        # portion near Donate — scan a mid band and ignore pure left-edge chrome.
        strip = region[int(h * 0.35) : int(h * 0.70), :]
        if strip.size == 0:
            return 0, 0, 0, False

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
        clusters = self._split_clusters(icon_cols)
        max_cluster = max((len(c) for c in clusters), default=0)
        # Capacity category icons sit on the far left; real unit icon rows span further right.
        left_only = bool(icon_cols) and max(icon_cols) <= int(cols * 0.45)

        if self.debug:
            logger.debug(
                "Request icon strip: icon_cols={}/{} max_run={} clusters={} max_cluster={} left_only={}",
                len(icon_cols),
                cols,
                max_run,
                len(clusters),
                max_cluster,
                left_only,
            )
        return len(icon_cols), max_run, max_cluster, left_only

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

        if mean_sat < 55:
            return False
        if mean_val < 40:
            return False

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

    @staticmethod
    def _split_clusters(cols: list[int]) -> list[list[int]]:
        if not cols:
            return []
        clusters: list[list[int]] = [[cols[0]]]
        for col in cols[1:]:
            if col == clusters[-1][-1] + 1:
                clusters[-1].append(col)
            else:
                clusters.append([col])
        return clusters

    def _chat_message_region(self, frame: np.ndarray, donate_button: MatchResult) -> np.ndarray:
        return chat_message_region(frame, donate_button)
