"""Conservative recognition of pages that obstruct village navigation.

Only fixed navigation chrome is matched: no seasonal artwork, offers, balances,
or OCR. Page identity and permission to tap its close button are separate.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import weakref

import cv2
import numpy as np


@dataclass(frozen=True)
class AuxiliaryPage:
    screen: str
    close: tuple[int, int] | None


@lru_cache(maxsize=7)
def _anchor(name: str) -> np.ndarray | None:
    path = Path(__file__).with_name("assets") / f"{name}.png"
    return cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)


class AuxiliaryPageDetector:
    """Match at a small reference size, then return original screenshot coords."""

    def __init__(self) -> None:
        self._frame: weakref.ReferenceType | None = None
        self._result: AuxiliaryPage | None = None

    @staticmethod
    def _find(
        gray: np.ndarray,
        name: str,
        bounds: tuple[int, int, int, int],
        threshold: float = 0.86,
    ) -> tuple[int, int, int, int] | None:
        template = _anchor(name)
        if template is None:
            return None
        x1, y1, x2, y2 = bounds
        crop = gray[y1:y2, x1:x2]
        th, tw = template.shape
        if crop.shape[0] < th or crop.shape[1] < tw:
            return None
        _, score, _, point = cv2.minMaxLoc(
            cv2.matchTemplate(crop, template, cv2.TM_CCOEFF_NORMED)
        )
        if score < threshold:
            return None
        return x1 + point[0], y1 + point[1], tw, th

    def detect(self, frame: np.ndarray) -> AuxiliaryPage | None:
        if self._frame is not None and self._frame() is frame:
            return self._result
        self._frame = weakref.ref(frame)
        self._result = self._detect(frame)
        return self._result

    def _detect(self, frame: np.ndarray) -> AuxiliaryPage | None:
        h, w = frame.shape[:2]
        # These full-screen menus use landscape layouts. Do not stretch portrait
        # or ultrawide captures into a convincing match.
        if not 1.6 <= w / h <= 1.95:
            return None
        small = cv2.resize(frame, (960, 540), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        shop = sum(
            self._find(gray, name, bounds) is not None
            for name, bounds in (
                ("shop_build", (150, 10, 240, 83)),
                ("shop_army", (230, 10, 320, 83)),
                ("shop_treasure", (310, 10, 400, 83)),
            )
        ) >= 2
        season = (
            self._find(gray, "pass_rewards", (390, 5, 520, 65)) is not None
            and self._find(gray, "pass_bank", (775, 5, 895, 65)) is not None
        )
        if not shop and not season:
            return None
        screen = "shop" if shop else "clash_pass"
        button = self._find(gray, f"{'shop' if shop else 'pass'}_close", (890, 5, 960, 83))
        close = None
        if button is not None:
            x, y, bw, bh = button
            hsv = cv2.cvtColor(small[y:y + bh, x:x + bw], cv2.COLOR_BGR2HSV)
            # Correlation also matches dimmed UI underneath a blocking dialog.
            # Require the white X to be bright and the button to be red before
            # permitting a tap; otherwise recognition is informational only.
            white = (hsv[:, :, 1] < 60) & (hsv[:, :, 2] > 210)
            red = (
                ((hsv[:, :, 0] < 12) | (hsv[:, :, 0] > 170))
                & (hsv[:, :, 1] > 120)
                & (hsv[:, :, 2] > 170)
            )
            if float(white.mean()) > 0.08 and float(red.mean()) > 0.20:
                close = (round((x + bw / 2) * w / 960), round((y + bh / 2) * h / 540))
        return AuxiliaryPage(screen, close)
