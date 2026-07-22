"""OCR clan-chat request capacity bars (troop / spell / siege)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from loguru import logger

from coc_bot.config import BotConfig
from coc_bot.vision.matcher import MatchResult
from coc_bot.vision.ocr import QuantityOCR

# Common clan-castle troop request totals (helps score OCR candidates).
_COMMON_TROOP_TOTALS = {15, 20, 25, 30, 35, 40, 45, 50, 55, 60}


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


def find_message_bubble(
    frame: np.ndarray, donate_button: MatchResult
) -> tuple[int, int, int, int] | None:
    """
    Locate the darker chat-message card that contains this Donate button.

    Clan chat uses a lighter panel background with darker rounded message bubbles.
    Seeding just left of Donate (inside the card) and flood-filling similar grey
    keeps OCR/icon search inside one request — resolution-agnostic.
    """
    h, w = frame.shape[:2]
    bx, by = donate_button.x, donate_button.y
    bw, bh = donate_button.width, donate_button.height
    cx, cy = donate_button.center

    # Seed inside the bubble: left of the green Donate button.
    seed_x = max(0, min(w - 1, bx - max(8, bw // 5)))
    seed_y = max(0, min(h - 1, cy))

    # Search window: chat is on the left; keep village HUD out.
    x0 = max(0, bx - int(bw * 14))
    x1 = min(w, bx + bw + 8)
    y0 = max(0, by - int(bh * 10))
    y1 = min(h, by + bh + int(bh * 2))
    if x1 <= x0 or y1 <= y0:
        return None

    roi = frame[y0:y1, x0:x1]
    seed_local = (seed_x - x0, seed_y - y0)
    if not (0 <= seed_local[0] < roi.shape[1] and 0 <= seed_local[1] < roi.shape[0]):
        return None

    # Flood fill on blurred BGR; darker bubble stays connected around the seed.
    blur = cv2.GaussianBlur(roi, (5, 5), 0)
    flood = blur.copy()
    mask_h, mask_w = flood.shape[:2]
    mask = np.zeros((mask_h + 2, mask_w + 2), dtype=np.uint8)
    # Looser thresholds tolerate bubble gradients / slight transparency.
    cv2.floodFill(
        flood,
        mask,
        seedPoint=seed_local,
        newVal=(0, 0, 255),
        loDiff=(12, 12, 12),
        upDiff=(12, 12, 12),
        flags=4 | (255 << 8) | cv2.FLOODFILL_MASK_ONLY,
    )
    filled = mask[1 : mask_h + 1, 1 : mask_w + 1]
    if int(np.count_nonzero(filled)) < 500:
        # Retry with wider color tolerance.
        flood = blur.copy()
        mask = np.zeros((mask_h + 2, mask_w + 2), dtype=np.uint8)
        cv2.floodFill(
            flood,
            mask,
            seedPoint=seed_local,
            newVal=(0, 0, 255),
            loDiff=(22, 22, 22),
            upDiff=(22, 22, 22),
            flags=4 | (255 << 8) | cv2.FLOODFILL_MASK_ONLY,
        )
        filled = mask[1 : mask_h + 1, 1 : mask_w + 1]

    if int(np.count_nonzero(filled)) < 500:
        return None

    ys, xs = np.where(filled > 0)
    if len(xs) == 0:
        return None
    rx0, rx1 = int(xs.min()), int(xs.max()) + 1
    ry0, ry1 = int(ys.min()), int(ys.max()) + 1

    # Absolute frame coords; small pad.
    pad = 4
    abs_x0 = max(0, x0 + rx0 - pad)
    abs_y0 = max(0, y0 + ry0 - pad)
    abs_x1 = min(w, x0 + rx1 + pad)
    abs_y1 = min(h, y0 + ry1 + pad)

    # Sanity: bubble should cover Donate horizontally/vertically enough.
    if abs_x1 - abs_x0 < bw or abs_y1 - abs_y0 < bh:
        return None
    if not (abs_x0 <= cx <= abs_x1 and abs_y0 <= cy <= abs_y1):
        # Donate center should lie in/near the bubble (button is on the card).
        if abs_x1 < bx - 4 or abs_y1 < by - 4:
            return None

    return abs_x0, abs_y0, abs_x1, abs_y1


def chat_message_region(frame: np.ndarray, donate_button: MatchResult) -> np.ndarray:
    """
    Crop the donation request card for capacity/icon analysis.

    Prefer the darker message bubble (color flood from left of Donate).
    Fall back to a geometry crop left of Donate if bubble detection fails.
    """
    bubble = find_message_bubble(frame, donate_button)
    if bubble is not None:
        x0, y0, x1, y1 = bubble
        logger.debug("Message bubble at ({},{})-({},{})", x0, y0, x1, y1)
        return frame[y0:y1, x0:x1].copy()

    logger.debug("Message bubble not found — using geometric left-of-Donate crop")
    h, w = frame.shape[:2]
    bx, by = donate_button.x, donate_button.y
    bw, bh = donate_button.width, donate_button.height

    msg_h = max(int(bh * 7), 100)
    y0 = max(0, by - msg_h)
    y1 = max(0, by + bh)
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
        self._has_tesseract = shutil.which("tesseract") is not None
        if self._has_tesseract:
            logger.debug("tesseract found — will use as capacity OCR helper")
        else:
            logger.debug("tesseract not found — EasyOCR only")

    def parse(self, frame: np.ndarray, donate_button: MatchResult) -> RequestCapacity | None:
        region = chat_message_region(frame, donate_button)
        if region.size == 0:
            return None

        self._maybe_save_debug(region, "capacity_region.png")

        h, w = region.shape[:2]
        # Inside the card: capacity rows are in the lower half (above Donate).
        # Exclude the green Donate button strip on the far right of the bubble.
        content = region[:, : max(1, int(w * 0.72))]
        lower = content[int(h * 0.40) : int(h * 0.92), :]
        if lower.size == 0:
            return None
        self._maybe_save_debug(lower, "capacity_lower.png")

        lh, lw = lower.shape[:2]
        row_h = max(1, lh // 3)
        # Numbers sit to the right of each icon/bar, still left of Donate.
        text_x0 = int(lw * 0.38)
        row_rois = [
            lower[0:row_h, text_x0:],
            lower[row_h : 2 * row_h, text_x0:],
            lower[2 * row_h :, text_x0:],
        ]

        logger.info("Running capacity OCR on 3 row text crops (bubble-limited)...")
        fractions: list[tuple[int, int] | None] = []
        for idx, row in enumerate(row_rois):
            self._maybe_save_debug(row, f"capacity_row_{idx}.png")
            kind = ("troop", "spell", "siege")[idx]
            frac = self._read_row_fraction(row, kind=kind)
            logger.info("Capacity row {} ({}) OCR -> {}", idx, kind, frac)
            fractions.append(frac)

        if any(f is None for f in fractions):
            logger.info("Row OCR incomplete — trying full lower band")
            band_fracs = self.ocr.read_fractions(lower, max_count=3)
            logger.info("Lower-band OCR fractions -> {}", band_fracs)
            for i, frac in enumerate(band_fracs):
                if i < 3 and fractions[i] is None:
                    kind = ("troop", "spell", "siege")[i]
                    if self._score_fraction(frac, kind=kind) > 0:
                        fractions[i] = frac

        if any(f is None for f in fractions):
            logger.debug(
                "Capacity OCR found {}/3 fractions ({})",
                sum(1 for f in fractions if f is not None),
                fractions,
            )
            return None

        typed = [f for f in fractions if f is not None]
        if not self._plausible_donated_totals(typed):
            logger.warning(
                "Rejecting implausible capacity OCR {} (likely HUD leak or misread)",
                typed,
            )
            return None

        capacity = self._from_donated_totals(typed[0], typed[1], typed[2])
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

    def _read_row_fraction(
        self, row: np.ndarray, *, kind: str
    ) -> tuple[int, int] | None:
        if row.size == 0:
            return None

        candidates: list[tuple[int, int, float]] = []
        variants = self._row_variants(row)

        readers = []
        if self._has_tesseract:
            readers.append(self._tesseract_fraction)
        readers.append(self.ocr.read_fraction)

        for prepared in variants:
            for reader in readers:
                try:
                    frac = reader(prepared)
                except Exception:
                    frac = None
                if frac is None:
                    continue
                score = self._score_fraction(frac, kind=kind)
                logger.debug("OCR candidate {} via {} score={:.1f}", frac, reader.__name__, score)
                if score > 0:
                    candidates.append((frac[0], frac[1], score))
            if candidates and max(c[2] for c in candidates) >= 5.0:
                break

        if not candidates:
            return None
        candidates.sort(key=lambda item: item[2], reverse=True)
        best = candidates[0]
        return best[0], best[1]

    def _row_variants(self, row: np.ndarray) -> list[np.ndarray]:
        if len(row.shape) == 3:
            gray = cv2.cvtColor(row, cv2.COLOR_BGR2GRAY)
            color = row
        else:
            gray = row
            color = cv2.cvtColor(row, cv2.COLOR_GRAY2BGR)

        up_c = cv2.resize(color, None, fx=5, fy=5, interpolation=cv2.INTER_CUBIC)
        up_g = cv2.resize(gray, None, fx=5, fy=5, interpolation=cv2.INTER_CUBIC)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(up_g)
        _, bright = cv2.threshold(up_g, 170, 255, cv2.THRESH_BINARY)
        _, otsu = cv2.threshold(up_g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        raw = [up_c, up_g, clahe, bright, cv2.bitwise_not(bright), cv2.bitwise_not(otsu)]
        return [
            cv2.copyMakeBorder(
                v,
                10,
                10,
                10,
                10,
                cv2.BORDER_CONSTANT,
                value=255 if v.ndim == 2 else (255, 255, 255),
            )
            for v in raw
        ]

    def _tesseract_fraction(self, roi: np.ndarray) -> tuple[int, int] | None:
        if not self._has_tesseract:
            return None
        if roi.ndim == 2:
            img = roi
        else:
            img = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            path = tmp.name
        try:
            cv2.imwrite(path, img)
            proc = subprocess.run(
                [
                    "tesseract",
                    path,
                    "stdout",
                    "--psm",
                    "7",
                    "-c",
                    "tessedit_char_whitelist=0123456789/",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=8,
            )
            text = (proc.stdout or "").strip()
            if text:
                logger.debug("tesseract raw text: {!r}", text)
            return QuantityOCR._parse_fraction_text(text)
        except Exception as exc:
            logger.debug("tesseract failed: {}", exc)
            return None
        finally:
            Path(path).unlink(missing_ok=True)

    @staticmethod
    def _score_fraction(frac: tuple[int, int], *, kind: str) -> float:
        donated, total = frac
        if total <= 0 or donated < 0 or donated > total:
            return 0.0
        score = 1.0
        if kind == "troop":
            if total not in _COMMON_TROOP_TOTALS:
                return 0.0
            score += 3.0
            if donated == 0:
                score += 2.0
        elif kind == "spell":
            if total not in {1, 2, 3, 4}:
                return 0.0
            score += 3.0
            if donated == 0:
                score += 1.5
        else:  # siege
            if total not in {1, 2}:
                return 0.0
            score += 3.0
            if donated == 0:
                score += 1.5
        return score

    @staticmethod
    def _plausible_donated_totals(fractions: list[tuple[int, int]]) -> bool:
        if len(fractions) < 3:
            return False
        (td, tt), (sd, st), (gd, gt) = fractions[0], fractions[1], fractions[2]
        if tt < 10 or tt > 100 or st < 1 or st > 12 or gt < 1 or gt > 4:
            return False
        if td > tt or sd > st or gd > gt:
            return False
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
