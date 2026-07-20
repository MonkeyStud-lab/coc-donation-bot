from __future__ import annotations

import cv2
import numpy as np


def bgr_to_hsv_pixel(bgr: tuple[int, int, int]) -> np.ndarray:
    pixel = np.uint8([[list(bgr)]])
    return cv2.cvtColor(pixel, cv2.COLOR_BGR2HSV)[0][0]


def hsv_distance(a: np.ndarray, b: np.ndarray) -> float:
    diff = np.abs(a.astype(float) - b.astype(float))
    # Hue wraps at 180
    if diff[0] > 90:
        diff[0] = 180 - diff[0]
    return float(np.linalg.norm(diff))


class SlotColorDetector:
    """Detect donatable troop/spell slots by calibrated color signatures."""

    def __init__(
        self,
        troop_color_bgr: list[int] | None = None,
        spell_color_bgr: list[int] | None = None,
        threshold: float = 40.0,
    ) -> None:
        self.troop_hsv = bgr_to_hsv_pixel(tuple(troop_color_bgr)) if troop_color_bgr else None
        self.spell_hsv = bgr_to_hsv_pixel(tuple(spell_color_bgr)) if spell_color_bgr else None
        self.threshold = threshold

    def is_donatable_troop(self, cell: np.ndarray) -> bool:
        if self.troop_hsv is None:
            return self._has_content(cell)
        return self._matches_color(cell, self.troop_hsv)

    def is_donatable_spell(self, cell: np.ndarray) -> bool:
        if self.spell_hsv is None:
            return self._has_content(cell)
        return self._matches_color(cell, self.spell_hsv)

    def is_donatable_siege(self, cell: np.ndarray) -> bool:
        return self._has_content(cell)

    @staticmethod
    def _has_content(cell: np.ndarray) -> bool:
        if cell.size == 0:
            return False
        gray = cv2.cvtColor(cell, cv2.COLOR_BGR2GRAY) if len(cell.shape) == 3 else cell
        return float(np.std(gray)) > 12.0

    def _matches_color(self, cell: np.ndarray, target_hsv: np.ndarray) -> bool:
        if cell.size == 0:
            return False
        h, w = cell.shape[:2]
        cy, cx = h // 2, w // 2
        patch = cell[max(0, cy - 2) : cy + 3, max(0, cx - 2) : cx + 3]
        mean_bgr = np.mean(patch.reshape(-1, 3), axis=0)
        sample_hsv = bgr_to_hsv_pixel(tuple(mean_bgr.astype(int)))
        return hsv_distance(sample_hsv, target_hsv) <= self.threshold
