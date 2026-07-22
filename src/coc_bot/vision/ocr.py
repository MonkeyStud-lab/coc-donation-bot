from __future__ import annotations

import re

import cv2
import numpy as np
from loguru import logger


class QuantityOCR:
    """Extract digit quantities from badge regions using EasyOCR with fallback."""

    def __init__(self, confidence_threshold: float = 0.5) -> None:
        self.confidence_threshold = confidence_threshold
        self._reader = None

    def _get_reader(self):
        if self._reader is None:
            import easyocr

            logger.info("Loading EasyOCR model (first time can take 1–3 minutes on CPU)...")
            self._reader = easyocr.Reader(["en"], gpu=False, verbose=False)
            logger.info("EasyOCR model ready")
        return self._reader

    def read_quantity(self, badge_roi: np.ndarray) -> int | None:
        if badge_roi.size == 0:
            return None

        text = self._read_easyocr(badge_roi)
        if text is not None:
            return text

        return self._read_contour_fallback(badge_roi)

    def read_fraction(self, roi: np.ndarray) -> tuple[int, int] | None:
        """OCR a capacity fraction like '35/35' or '0/1'. Returns (current, total)."""
        if roi.size == 0:
            return None
        # Single-row crops: try a couple variants and return the first parse.
        min_conf = min(0.2, self.confidence_threshold)
        for prepared in self._fraction_variants(roi):
            try:
                reader = self._get_reader()
                results = reader.readtext(prepared, allowlist="0123456789/", detail=1)
                # Prefer individual hits, then joined text.
                scored: list[tuple[float, int, int]] = []
                for _bbox, text, conf in results:
                    if conf < min_conf:
                        continue
                    parsed = self._parse_fraction_text(text)
                    if parsed is not None:
                        scored.append((float(conf), parsed[0], parsed[1]))
                if scored:
                    scored.sort(reverse=True)
                    return scored[0][1], scored[0][2]
                joined = "".join(t for _b, t, c in results if c >= min_conf)
                parsed = self._parse_fraction_text(joined)
                if parsed is not None:
                    return parsed
                # Unrestricted pass — slash sometimes dropped from allowlist path.
                results2 = reader.readtext(prepared, detail=1)
                joined2 = " ".join(t for _b, t, c in results2 if c >= min_conf)
                parsed2 = self._parse_fraction_text(joined2)
                if parsed2 is not None:
                    return parsed2
            except Exception as exc:
                logger.debug("EasyOCR fraction failed: {}", exc)
        return None

    def read_fractions(self, roi: np.ndarray, max_count: int = 3) -> list[tuple[int, int]]:
        """OCR multiple N/M fractions ordered top → bottom."""
        if roi.size == 0:
            return []

        min_conf = min(0.2, self.confidence_threshold)
        candidates: list[tuple[float, int, int, float]] = []

        for prepared in self._fraction_variants(roi):
            try:
                reader = self._get_reader()
                results = reader.readtext(prepared, allowlist="0123456789/", detail=1)
                for bbox, text, conf in results:
                    if conf < min_conf:
                        continue
                    parsed = self._parse_fraction_text(text)
                    if parsed is None:
                        continue
                    y0 = float(bbox[0][1]) if bbox else 0.0
                    candidates.append((y0, parsed[0], parsed[1], float(conf)))
                joined = " ".join(t for _b, t, c in results if c >= min_conf)
                for match in re.finditer(r"(\d+)\s*/\s*(\d+)", joined):
                    candidates.append((999.0, int(match.group(1)), int(match.group(2)), 0.5))
                if len({(c, t) for _y, c, t, _cf in candidates}) >= max_count:
                    break
            except Exception as exc:
                logger.debug("EasyOCR fractions failed on variant: {}", exc)

        if not candidates:
            return []

        candidates.sort(key=lambda item: (item[0], -item[3]))
        unique: list[tuple[float, int, int]] = []
        for y0, cur, tot, _conf in candidates:
            if tot <= 0 or cur < 0 or cur > max(tot * 2, tot):
                continue
            if any(abs(y0 - uy) < 8 and ut == tot for uy, _uc, ut in unique):
                continue
            unique.append((y0, cur, tot))

        unique.sort(key=lambda item: item[0])
        return [(c, t) for _y, c, t in unique[:max_count]]

    def _fraction_variants(self, roi: np.ndarray) -> list[np.ndarray]:
        """A few preprocess variants — keep this small; EasyOCR is expensive."""
        if len(roi.shape) == 2 or (len(roi.shape) == 3 and roi.shape[2] == 1):
            # Already a prepared mask / gray crop from capacity_parser.
            if len(roi.shape) == 2:
                return [roi, cv2.bitwise_not(roi)]
            gray = roi[:, :, 0]
            return [gray, cv2.bitwise_not(gray)]

        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        color = roi
        up_color = cv2.resize(color, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
        up_gray = cv2.resize(gray, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
        _, bright = cv2.threshold(up_gray, 160, 255, cv2.THRESH_BINARY)
        return [up_color, bright, cv2.bitwise_not(bright)]

    @staticmethod
    def _parse_fraction_text(text: str) -> tuple[int, int] | None:
        cleaned = text.strip().replace(" ", "").replace("|", "/").replace("\\", "/")
        match = re.search(r"(\d+)\s*/\s*(\d+)", cleaned)
        if match:
            return int(match.group(1)), int(match.group(2))
        digits = re.sub(r"\D", "", cleaned)
        if digits.startswith("0") and 2 <= len(digits) <= 4:
            total = int(digits[1:])
            if 1 <= total <= 99:
                return 0, total
        return None

    def _read_easyocr(self, badge_roi: np.ndarray) -> int | None:
        try:
            reader = self._get_reader()
            gray = cv2.cvtColor(badge_roi, cv2.COLOR_BGR2GRAY) if len(badge_roi.shape) == 3 else badge_roi
            up = cv2.resize(gray, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
            _, binary = cv2.threshold(up, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            results = reader.readtext(binary, allowlist="0123456789", detail=1)
            for _bbox, text, conf in results:
                digits = re.sub(r"\D", "", text)
                if digits and conf >= self.confidence_threshold:
                    return int(digits)
        except Exception as exc:
            logger.debug("EasyOCR failed: {}", exc)
        return None

    def _read_contour_fallback(self, badge_roi: np.ndarray) -> int | None:
        gray = cv2.cvtColor(badge_roi, cv2.COLOR_BGR2GRAY) if len(badge_roi.shape) == 3 else badge_roi
        up = cv2.resize(gray, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
        _, binary = cv2.threshold(up, 180, 255, cv2.THRESH_BINARY)
        white_ratio = float(np.mean(binary == 255))
        if white_ratio < 0.05:
            return None
        if white_ratio > 0.35:
            return 2
        return 1
