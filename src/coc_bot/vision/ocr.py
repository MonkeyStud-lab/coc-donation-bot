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

            self._reader = easyocr.Reader(["en"], gpu=False, verbose=False)
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
        fracs = self.read_fractions(roi, max_count=1)
        return fracs[0] if fracs else None

    def read_fractions(self, roi: np.ndarray, max_count: int = 3) -> list[tuple[int, int]]:
        """OCR multiple N/M fractions ordered top → bottom."""
        if roi.size == 0:
            return []

        # Prefer lower confidence for small chat text; still filter junk later.
        min_conf = min(0.25, self.confidence_threshold)

        candidates: list[tuple[float, int, int, float]] = []
        for prepared in self._fraction_variants(roi):
            try:
                reader = self._get_reader()
                # Try with slash allowlist first, then unrestricted digits.
                for allowlist in ("0123456789/", "0123456789"):
                    results = reader.readtext(prepared, allowlist=allowlist, detail=1)
                    for bbox, text, conf in results:
                        if conf < min_conf:
                            continue
                        parsed = self._parse_fraction_text(text)
                        if parsed is None:
                            continue
                        y0 = float(bbox[0][1]) if bbox else 0.0
                        candidates.append((y0, parsed[0], parsed[1], float(conf)))
                    # Also scan concatenated line for missed splits.
                    joined = " ".join(t for _b, t, c in results if c >= min_conf)
                    for match in re.finditer(r"(\d+)\s*/\s*(\d+)", joined):
                        candidates.append(
                            (999.0, int(match.group(1)), int(match.group(2)), 0.5)
                        )
            except Exception as exc:
                logger.debug("EasyOCR fractions failed on variant: {}", exc)

        if not candidates:
            return []

        # Dedupe near-identical fractions (same total, similar y).
        candidates.sort(key=lambda item: (item[0], -item[3]))
        unique: list[tuple[float, int, int]] = []
        for y0, cur, tot, _conf in candidates:
            if tot <= 0 or cur < 0 or cur > tot * 2:
                continue
            if any(abs(y0 - uy) < 8 and ut == tot for uy, _uc, ut in unique):
                continue
            unique.append((y0, cur, tot))

        unique.sort(key=lambda item: item[0])
        return [(c, t) for _y, c, t in unique[:max_count]]

    def _fraction_variants(self, roi: np.ndarray) -> list[np.ndarray]:
        """Return preprocessed images that often help EasyOCR on CoC chat text."""
        if len(roi.shape) == 3:
            gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            color = roi
        else:
            gray = roi
            color = cv2.cvtColor(roi, cv2.COLOR_GRAY2BGR)

        variants: list[np.ndarray] = []
        for scale in (3, 4):
            up_gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
            up_color = cv2.resize(color, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
            variants.append(up_color)
            variants.append(up_gray)
            _, otsu = cv2.threshold(up_gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            variants.append(otsu)
            variants.append(cv2.bitwise_not(otsu))
            # Boost contrast for pale text on beige chat bubbles.
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            variants.append(clahe.apply(up_gray))
        return variants

    @staticmethod
    def _parse_fraction_text(text: str) -> tuple[int, int] | None:
        cleaned = text.strip().replace(" ", "").replace("|", "/").replace("\\", "/")
        match = re.search(r"(\d+)\s*/\s*(\d+)", cleaned)
        if match:
            return int(match.group(1)), int(match.group(2))
        # OCR sometimes drops the slash: "045" for 0/45, "01" for 0/1.
        digits = re.sub(r"\D", "", cleaned)
        if len(digits) >= 2:
            # Prefer splitting after a leading 0 when total looks plausible.
            if digits.startswith("0") and len(digits) <= 4:
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
        # Heuristic: more white pixels often correlates with larger numbers in small badges
        if white_ratio > 0.35:
            return 2
        return 1
