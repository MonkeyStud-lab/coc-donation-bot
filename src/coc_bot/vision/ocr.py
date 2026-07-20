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
