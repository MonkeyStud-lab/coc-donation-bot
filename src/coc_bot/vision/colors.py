from __future__ import annotations

import cv2
import numpy as np


def bgr_to_hsv_pixel(bgr: tuple[int, int, int]) -> np.ndarray:
    pixel = np.uint8([[list(bgr)]])
    return cv2.cvtColor(pixel, cv2.COLOR_BGR2HSV)[0][0]


def hsv_distance(a: np.ndarray, b: np.ndarray) -> float:
    diff = np.abs(a.astype(float) - b.astype(float))
    if diff[0] > 90:
        diff[0] = 180 - diff[0]
    return float(np.linalg.norm(diff))


def cell_center_hsv(cell: np.ndarray) -> np.ndarray:
    if cell.size == 0:
        return np.zeros(3, dtype=float)
    h, w = cell.shape[:2]
    cy, cx = h // 2, w // 2
    margin_y = max(2, h // 6)
    margin_x = max(2, w // 6)
    patch = cell[cy - margin_y : cy + margin_y, cx - margin_x : cx + margin_x]
    if patch.size == 0:
        patch = cell
    mean_bgr = np.mean(patch.reshape(-1, 3), axis=0)
    return bgr_to_hsv_pixel(tuple(mean_bgr.astype(int)))


class SlotColorDetector:
    """
    Detect donatable donation-panel slots.

    In CoC, slots the bot may tap are full color; slots that cannot be donated
    (wrong type or won't fit the requester's CC) are grey/monochrome.
    """

    def __init__(
        self,
        troop_color_bgr: list[int] | None = None,
        troop_grey_bgr: list[int] | None = None,
        spell_color_bgr: list[int] | None = None,
        spell_grey_bgr: list[int] | None = None,
        saturation_threshold: float = 35.0,
    ) -> None:
        self.troop_color_hsv = bgr_to_hsv_pixel(tuple(troop_color_bgr)) if troop_color_bgr else None
        self.troop_grey_hsv = bgr_to_hsv_pixel(tuple(troop_grey_bgr)) if troop_grey_bgr else None
        self.spell_color_hsv = bgr_to_hsv_pixel(tuple(spell_color_bgr)) if spell_color_bgr else None
        self.spell_grey_hsv = bgr_to_hsv_pixel(tuple(spell_grey_bgr)) if spell_grey_bgr else None
        self.saturation_threshold = saturation_threshold

    def is_donatable_troop(self, cell: np.ndarray) -> bool:
        return self._is_donatable(cell, self.troop_color_hsv, self.troop_grey_hsv)

    def is_donatable_spell(self, cell: np.ndarray) -> bool:
        return self._is_donatable(cell, self.spell_color_hsv, self.spell_grey_hsv)

    @staticmethod
    def has_icon(cell: np.ndarray) -> bool:
        gray = cv2.cvtColor(cell, cv2.COLOR_BGR2GRAY) if len(cell.shape) == 3 else cell
        return float(np.std(gray)) > 10.0

    def _is_donatable(
        self,
        cell: np.ndarray,
        colored_hsv: np.ndarray | None,
        grey_hsv: np.ndarray | None,
    ) -> bool:
        if cell.size == 0:
            return False
        if not SlotColorDetector.has_icon(cell):
            return False

        sample = cell_center_hsv(cell)

        if colored_hsv is not None and grey_hsv is not None:
            return hsv_distance(sample, colored_hsv) <= hsv_distance(sample, grey_hsv)

        if colored_hsv is not None:
            return hsv_distance(sample, colored_hsv) <= 45.0

        # Fallback: colored icons are saturated; grey icons are not.
        return float(sample[1]) >= self.saturation_threshold
