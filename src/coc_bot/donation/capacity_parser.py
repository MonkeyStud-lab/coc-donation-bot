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
    """Read donated/total capacity rows from the chat bubble above Donate."""

    def __init__(self, config: BotConfig) -> None:
        self.config = config
        self.ocr = QuantityOCR(confidence_threshold=config.ocr_confidence_threshold)

    def parse(self, frame: np.ndarray, donate_button: MatchResult) -> RequestCapacity | None:
        region = self._chat_message_region(frame, donate_button)
        if region.size == 0:
            return None

        h, _w = region.shape[:2]
        # Capacity bars sit just above Donate (below any requested-unit icons).
        # Try the lower band first, then the full bubble if needed.
        bands = [
            region[int(h * 0.45) : int(h * 0.98), :],
            region[int(h * 0.25) : int(h * 0.85), :],
            region,
        ]

        fractions: list[tuple[int, int]] = []
        for band in bands:
            if band.size == 0:
                continue
            fractions = self.ocr.read_fractions(band, max_count=3)
            if len(fractions) >= 3:
                break
            # Fallback: three horizontal strips inside this band.
            strip_fracs = self._parse_strips(band)
            if len(strip_fracs) >= 3:
                fractions = strip_fracs
                break

        if len(fractions) < 3:
            logger.debug("Capacity OCR found {}/3 fractions", len(fractions))
            return None

        # Chat UI shows donated/total. Planner needs remaining = total - donated.
        capacity = self._from_donated_totals(fractions[0], fractions[1], fractions[2])
        logger.debug(
            "Request capacity: troops={}/{} spells={}/{} siege={}/{} (remaining/total)",
            capacity.troop_remaining,
            capacity.troop_total,
            capacity.spell_remaining,
            capacity.spell_total,
            capacity.siege_remaining,
            capacity.siege_total,
        )
        return capacity

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
        y1 = max(0, by - int(bh * 0.1))
        x0 = max(0, bx - bw * 2)
        x1 = min(w, bx + bw * 12)

        if y1 <= y0 or x1 <= x0:
            return np.array([])

        return frame[y0:y1, x0:x1].copy()
