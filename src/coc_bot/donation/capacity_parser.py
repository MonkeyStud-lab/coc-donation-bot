"""OCR clan-chat request capacity bars (troop / spell / siege)."""

from __future__ import annotations

from dataclasses import dataclass

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
    """Read 35/35, 0/1, 0/1 style capacity rows from the chat bubble above Donate."""

    def __init__(self, config: BotConfig) -> None:
        self.config = config
        self.ocr = QuantityOCR(confidence_threshold=config.ocr_confidence_threshold)

    def parse(self, frame: np.ndarray, donate_button: MatchResult) -> RequestCapacity | None:
        region = self._chat_message_region(frame, donate_button)
        if region.size == 0:
            return None

        h, _w = region.shape[:2]
        # Capacity bars sit above the requested-icon strip (icons are ~68–92% height).
        capacity_band = region[int(h * 0.30) : int(h * 0.72), :]
        if capacity_band.size == 0:
            return None

        fractions = self.ocr.read_fractions(capacity_band, max_count=3)
        if len(fractions) < 3:
            # Retry with three horizontal strips in case OCR misses one row.
            fractions = self._parse_strips(capacity_band)
        if len(fractions) < 3:
            logger.debug("Capacity OCR found {}/3 fractions", len(fractions))
            return None

        (tr, tt), (sr, st), (gr, gt) = fractions[0], fractions[1], fractions[2]
        capacity = RequestCapacity(
            troop_remaining=tr,
            troop_total=tt,
            spell_remaining=sr,
            spell_total=st,
            siege_remaining=gr,
            siege_total=gt,
        )
        logger.debug(
            "Request capacity: troops={}/{} spells={}/{} siege={}/{}",
            tr,
            tt,
            sr,
            st,
            gr,
            gt,
        )
        return capacity

    def _parse_strips(self, capacity_band: np.ndarray) -> list[tuple[int, int]]:
        h = capacity_band.shape[0]
        strips = [
            capacity_band[0 : h // 3, :],
            capacity_band[h // 3 : 2 * h // 3, :],
            capacity_band[2 * h // 3 :, :],
        ]
        found: list[tuple[int, int]] = []
        for strip in strips:
            frac = self.ocr.read_fraction(strip)
            if frac is not None:
                found.append(frac)
        return found

    @staticmethod
    def _chat_message_region(frame: np.ndarray, donate_button: MatchResult) -> np.ndarray:
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
