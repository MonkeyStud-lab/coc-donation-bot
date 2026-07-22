"""OCR clan-chat request capacity bars (troop / spell / siege)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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


def chat_message_region(frame: np.ndarray, donate_button: MatchResult) -> np.ndarray:
    """
    Crop the chat bubble ABOVE and LEFT of Donate.

    Capacity text (0/35) sits left of the Donate button. Extending far right
    pulls in village HUD (e.g. builders 5/5) and poisons OCR.
    """
    h, w = frame.shape[:2]
    bx, by = donate_button.x, donate_button.y
    bw, bh = donate_button.width, donate_button.height

    msg_h = max(int(bh * 7), 100)
    y0 = max(0, by - msg_h)
    y1 = max(0, by + int(bh * 0.05))
    # Bars + fractions are to the left of Donate.
    x0 = max(0, bx - int(bw * 11))
    x1 = min(w, bx + int(bw * 0.2))

    if y1 <= y0 or x1 <= x0:
        return np.array([])

    return frame[y0:y1, x0:x1].copy()


class RequestCapacityParser:
    """Read donated/total capacity rows from the chat bubble above Donate."""

    def __init__(self, config: BotConfig) -> None:
        self.config = config
        self.ocr = QuantityOCR(confidence_threshold=config.ocr_confidence_threshold)

    def parse(self, frame: np.ndarray, donate_button: MatchResult) -> RequestCapacity | None:
        region = chat_message_region(frame, donate_button)
        if region.size == 0:
            return None

        self._maybe_save_debug(region, "capacity_region.png")

        h, w = region.shape[:2]
        # Capacity rows sit in the lower part of the bubble (just above Donate).
        lower = region[int(h * 0.35) : int(h * 0.98), :]
        if lower.size == 0:
            return None

        lh, lw = lower.shape[:2]
        row_h = max(1, lh // 3)
        # Text is toward the right of the bar, still inside the bubble (near Donate).
        text_x0 = int(lw * 0.35)
        row_rois = [
            lower[0:row_h, text_x0:],
            lower[row_h : 2 * row_h, text_x0:],
            lower[2 * row_h :, text_x0:],
        ]

        logger.info("Running capacity OCR on 3 row text crops...")
        fractions: list[tuple[int, int]] = []
        for idx, row in enumerate(row_rois):
            self._maybe_save_debug(row, f"capacity_row_{idx}.png")
            frac = self._read_row_fraction(row)
            logger.info("Capacity row {} OCR -> {}", idx, frac)
            if frac is None:
                break
            fractions.append(frac)

        if len(fractions) < 3:
            logger.info("Row OCR incomplete — trying full lower band")
            fractions = self.ocr.read_fractions(lower, max_count=3)
            logger.info("Lower-band OCR fractions -> {}", fractions)

        if len(fractions) < 3:
            logger.debug("Capacity OCR found {}/3 fractions", len(fractions))
            return None

        if not self._plausible_donated_totals(fractions):
            logger.warning(
                "Rejecting implausible capacity OCR {} (likely HUD leak or misread)",
                fractions,
            )
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

    def _maybe_save_debug(self, image: np.ndarray, name: str) -> None:
        try:
            debug_dir = Path(self.config.data_dir) / "debug"
            debug_dir.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(debug_dir / name), image)
        except Exception as exc:
            logger.debug("Could not save debug image {}: {}", name, exc)

    def _read_row_fraction(self, row: np.ndarray) -> tuple[int, int] | None:
        if row.size == 0:
            return None
        prepared = self._prepare_text_roi(row)
        frac = self.ocr.read_fraction(prepared)
        if frac is not None:
            return frac
        return self.ocr.read_fraction(row)

    @staticmethod
    def _prepare_text_roi(row: np.ndarray) -> np.ndarray:
        """Upscale + isolate bright glyph pixels for EasyOCR."""
        if len(row.shape) == 3:
            gray = cv2.cvtColor(row, cv2.COLOR_BGR2GRAY)
        else:
            gray = row
        up = cv2.resize(gray, None, fx=5, fy=5, interpolation=cv2.INTER_CUBIC)
        _, bright = cv2.threshold(up, 160, 255, cv2.THRESH_BINARY)
        inverted = cv2.bitwise_not(bright)
        return cv2.copyMakeBorder(inverted, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=255)

    @staticmethod
    def _plausible_donated_totals(fractions: list[tuple[int, int]]) -> bool:
        """Reject readings that look like village HUD (builders 5/5) or junk."""
        if len(fractions) < 3:
            return False
        (td, tt), (sd, st), (gd, gt) = fractions[0], fractions[1], fractions[2]
        if tt < 1 or tt > 100 or st < 1 or st > 12 or gt < 1 or gt > 4:
            return False
        if td > tt or sd > st or gd > gt:
            return False
        # Builders HUD is often 5/5; open CC requests are rarely all tiny equal totals.
        if tt <= 8 and st >= 3 and gt >= 3:
            return False
        if (td, tt) == (sd, st) == (gd, gt):
            return False
        return True

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
