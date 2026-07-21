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
        if roi.size == 0:
            return None
        try:
            reader = self._get_reader()
            gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if len(roi.shape) == 3 else roi
            up = cv2.resize(gray, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
            _, binary = cv2.threshold(up, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            results = reader.readtext(binary, allowlist="0123456789/", detail=1)
            candidates: list[tuple[float, int, int, float]] = []
            for bbox, text, conf in results:
                if conf < self.confidence_threshold:
                    continue
                parsed = self._parse_fraction_text(text)
                if parsed is None:
                    continue
                # Sort by vertical position (top → bottom) using bbox top-left y.
                y0 = float(bbox[0][1]) if bbox else 0.0
                current, total = parsed
                candidates.append((y0, current, total, float(conf)))
            if not candidates:
                # Fallback: concatenate all text and search for N/M patterns.
                joined = " ".join(t for _b, t, c in results if c >= self.confidence_threshold)
                for match in re.finditer(r"(\d+)\s*/\s*(\d+)", joined):
                    return int(match.group(1)), int(match.group(2))
                return None
            candidates.sort(key=lambda item: item[0])
            _y, current, total, _conf = candidates[0]
            return current, total
        except Exception as exc:
            logger.debug("EasyOCR fraction failed: {}", exc)
            return None

    def read_fractions(self, roi: np.ndarray, max_count: int = 3) -> list[tuple[int, int]]:
        """OCR multiple N/M fractions ordered top → bottom."""
        if roi.size == 0:
            return []
        try:
            reader = self._get_reader()
            gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if len(roi.shape) == 3 else roi
            up = cv2.resize(gray, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
            _, binary = cv2.threshold(up, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            results = reader.readtext(binary, allowlist="0123456789/", detail=1)
            candidates: list[tuple[float, int, int]] = []
            for bbox, text, conf in results:
                if conf < self.confidence_threshold:
                    continue
                parsed = self._parse_fraction_text(text)
                if parsed is None:
                    continue
                y0 = float(bbox[0][1]) if bbox else 0.0
                candidates.append((y0, parsed[0], parsed[1]))
            if not candidates:
                joined = " ".join(t for _b, t, c in results if c >= self.confidence_threshold)
                for match in re.finditer(r"(\d+)\s*/\s*(\d+)", joined):
                    candidates.append((float(len(candidates)), int(match.group(1)), int(match.group(2))))
            candidates.sort(key=lambda item: item[0])
            return [(c, t) for _y, c, t in candidates[:max_count]]
        except Exception as exc:
            logger.debug("EasyOCR fractions failed: {}", exc)
            return []

    @staticmethod
    def _parse_fraction_text(text: str) -> tuple[int, int] | None:
        cleaned = text.strip().replace(" ", "")
        match = re.search(r"(\d+)\s*/\s*(\d+)", cleaned)
        if not match:
            return None
        return int(match.group(1)), int(match.group(2))

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
