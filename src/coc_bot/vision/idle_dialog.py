"""Recognize the English Android inactivity dialog using its fixed text."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import weakref

import cv2
import numpy as np


@lru_cache(maxsize=4)
def _anchor(name: str) -> np.ndarray | None:
    return cv2.imread(str(Path(__file__).with_name("assets") / f"{name}.png"), cv2.IMREAD_GRAYSCALE)


class IdleDialogDetector:
    """Require both the title/message and the Reload game action; no blind taps."""

    def __init__(self) -> None:
        self._frame: weakref.ReferenceType | None = None
        self._result: tuple[int, int] | None = None

    def detect(self, frame: np.ndarray) -> tuple[int, int] | None:
        if self._frame is not None and self._frame() is frame:
            return self._result
        self._frame = weakref.ref(frame)
        self._result = self._detect(frame)
        return self._result

    @staticmethod
    def _detect(frame: np.ndarray) -> tuple[int, int] | None:
        h, w = frame.shape[:2]
        if not 1.5 <= w / h <= 2.1:
            return None
        scale = 1280 / w
        small = cv2.resize(frame, (1280, round(h * scale)), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        height = gray.shape[0]
        x0, y0 = 190, int(height * .22)
        crop = gray[y0:int(height * .80), x0:1090]
        # Android's larger text layout changes line spacing as well as size.
        # Each inspected variant still requires its own title/message AND action.
        for suffix in ('', '_large'):
            matches = []
            for name in ("idle_title", "idle_reload"):
                template = _anchor(name+suffix)
                if template is None or any(a < b for a, b in zip(crop.shape, template.shape)):
                    break
                _, score, _, point = cv2.minMaxLoc(cv2.matchTemplate(crop, template, cv2.TM_CCOEFF_NORMED))
                if score < .88:
                    break
                matches.append((x0 + point[0], y0 + point[1], template.shape[1], template.shape[0]))
            if len(matches)!=2:continue
            tx, ty, tw, th = matches[0]
            rx, ry, rw, rh = matches[1]
            if abs(tx - rx) > 15 or not 10 <= ry - (ty + th) <= 120:
                continue
            # A dimmed underlying dialog must not authorize a reload tap.
            action = small[ry:ry + rh, rx:rx + rw]
            hsv = cv2.cvtColor(action, cv2.COLOR_BGR2HSV)
            cyan = (hsv[:, :, 0] > 75) & (hsv[:, :, 0] < 110) & (hsv[:, :, 1] > 60) & (hsv[:, :, 2] > 170)
            if float(cyan.mean()) < .04:
                continue
            return round((rx + rw / 2) / scale), round((ry + rh / 2) / scale)
        return None
