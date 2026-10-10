"""Results-only evidence for an already deployed farm attack.

Never infer completion from green scenery, silhouettes or generic screen labels.
No OCR or learned model is required; fixed text anchors must agree spatially.
"""
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np


@lru_cache(maxsize=2)
def _anchor(name):
    return cv2.imread(str(Path(__file__).with_name("assets") / f"{name}.png"), cv2.IMREAD_GRAYSCALE)


class BattleCompletionDetector:
    """Return a target only when both fixed results labels are present."""

    def detect(self, frame: np.ndarray) -> tuple[int, int] | None:
        h, w = frame.shape[:2]
        small = cv2.resize(frame, (960, 540), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        button = self._match(gray, "results_return_home", (370, 420, 590, 520))
        spent = self._match(gray, "results_troops_expended", (340, 320, 620, 400))
        if button is None or spent is None:
            return None
        bx, by, bw, bh = button
        sx, sy, sw, sh = spent
        if abs(bx + bw / 2 - (sx + sw / 2)) > 35 or by - sy < 65:
            return None
        # An obscuring popup can leave matching labels beneath it. Check that
        # the Return Home control is green and its text is still bright white.
        crop = small[by:by + bh, bx:bx + bw]
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        green = cv2.inRange(hsv, (35, 70, 70), (95, 255, 255))
        bright = (crop.min(axis=2) > 210).mean()
        if green.mean() / 255 < .20 or bright < .08:
            return None
        return round((bx + bw / 2) * w / 960), round((by + bh / 2) * h / 540)

    @staticmethod
    def _match(gray, name, box):
        template = _anchor(name)
        if template is None:
            return None
        x0, y0, x1, y1 = box
        result = cv2.matchTemplate(gray[y0:y1, x0:x1], template, cv2.TM_CCOEFF_NORMED)
        _, score, _, point = cv2.minMaxLoc(result)
        if score < .90:
            return None
        th, tw = template.shape
        return x0 + point[0], y0 + point[1], tw, th
