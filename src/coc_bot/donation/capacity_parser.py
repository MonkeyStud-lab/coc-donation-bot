"""OCR clan-chat request capacity bars (troop / spell / siege)."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from loguru import logger

from coc_bot.config import BotConfig
from coc_bot.vision.matcher import MatchResult
from coc_bot.vision.ocr import QuantityOCR


@dataclass(frozen=True)
class RequestCapacity:
    troop_remaining: int
    troop_total: int
    spell_remaining: int
    spell_total: int
    siege_remaining: int
    siege_total: int

    @property
    def has_remaining(self) -> bool:
        return self.troop_remaining > 0 or self.spell_remaining > 0 or self.siege_remaining > 0

    @property
    def troop_open(self) -> bool:
        return self.troop_remaining > 0

    @property
    def spell_open(self) -> bool:
        return self.spell_remaining > 0

    @property
    def siege_open(self) -> bool:
        return self.siege_remaining > 0


class RequestCapacityParser:
    """Read donated/total capacity rows from the chat bubble above Donate."""

    def __init__(self, config: BotConfig) -> None:
        self.config = config
        self.ocr = QuantityOCR(confidence_threshold=config.ocr_confidence_threshold)

    def parse(self, frame: np.ndarray, donate_button: MatchResult) -> RequestCapacity | None:
        region = self._chat_message_region(frame, donate_button)
        if region.size == 0:
            return None

        h, w = region.shape[:2]
        # Capacity rows sit in the lower part of the bubble (just above Donate).
        lower = region[int(h * 0.40) : int(h * 0.98), :]
        if lower.size == 0:
            return None

        lh, lw = lower.shape[:2]
        # Three stacked rows; text is on the right of each row (after icon + bar).
        row_h = max(1, lh // 3)
        text_x0 = int(lw * 0.40)
        row_rois = [
            lower[0:row_h, text_x0:],
            lower[row_h : 2 * row_h, text_x0:],
            lower[2 * row_h :, text_x0:],
        ]

        logger.info("Running capacity OCR on 3 row text crops...")
        fractions: list[tuple[int, int]] = []
        for idx, row in enumerate(row_rois):
            frac = self._read_row_fraction(row)
            logger.debug("Capacity row {} OCR -> {}", idx, frac)
            if frac is None:
                break
            fractions.append(frac)

        if len(fractions) < 3:
            # Fallback: whole lower band
            logger.info("Row OCR incomplete — trying full lower band")
            fractions = self.ocr.read_fractions(lower, max_count=3)

        if len(fractions) < 3:
            logger.debug("Capacity OCR found {}/3 fractions", len(fractions))
            return None

        capacity = self._from_donated_totals(fractions[0], fractions[1], fractions[2])
        logger.info(
            "Request capacity remaining/total: troops={}/{} spells={}/{} siege={}/{}",
            capacity.troop_remaining,
            capacity.troop_total,
            capacity.spell_remaining,
            capacity.spell_total,
            capacity.siege_remaining,
            capacity.siege_total,
        )
        return capacity

    def _read_row_fraction(self, row: np.ndarray) -> tuple[int, int] | None:
        if row.size == 0:
            return None
        # Boost white chat text on dark grey.
        prepared = self._prepare_text_roi(row)
        frac = self.ocr.read_fraction(prepared)
        if frac is not None:
            return frac
        # Try original color crop as well.
        return self.ocr.read_fraction(row)

    @staticmethod
    def _prepare_text_roi(row: np.ndarray) -> np.ndarray:
        """Upscale + isolate bright glyph pixels for EasyOCR."""
        if len(row.shape) == 3:
            gray = cv2.cvtColor(row, cv2.COLOR_BGR2GRAY)
        else:
            gray = row
        up = cv2.resize(gray, None, fx=5, fy=5, interpolation=cv2.INTER_CUBIC)
        # Keep bright text, then invert to dark-on-light (OCR-friendly).
        _, bright = cv2.threshold(up, 160, 255, cv2.THRESH_BINARY)
        inverted = cv2.bitwise_not(bright)
        # Pad so glyphs aren't edge-clipped.
        return cv2.copyMakeBorder(inverted, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=255)

    @staticmethod
    def _from_donated_totals(
        troop: tuple[int, int],
        spell: tuple[int, int],
        siege: tuple[int, int],
    ) -> RequestCapacity:
        def rem(donated: int, total: int) -> tuple[int, int]:
            total = max(total, 0)
            donated = max(0, min(donated, total))
            return total - donated, total

        tr, tt = rem(*troop)
        sr, st = rem(*spell)
        gr, gt = rem(*siege)
        return RequestCapacity(
            troop_remaining=tr,
            troop_total=tt,
            spell_remaining=sr,
            spell_total=st,
            siege_remaining=gr,
            siege_total=gt,
        )

    @staticmethod
    def _chat_message_region(frame: np.ndarray, donate_button: MatchResult) -> np.ndarray:
        """Crop the chat message bubble sitting above a Donate button."""
        h, w = frame.shape[:2]
        bx, by = donate_button.x, donate_button.y
        bw, bh = donate_button.width, donate_button.height

        msg_h = max(int(bh * 7), 100)
        y0 = max(0, by - msg_h)
        y1 = max(0, by - int(bh * 0.05))
        x0 = max(0, bx - bw * 2)
        x1 = min(w, bx + bw * 12)

        if y1 <= y0 or x1 <= x0:
            return np.array([])

        return frame[y0:y1, x0:x1].copy()
