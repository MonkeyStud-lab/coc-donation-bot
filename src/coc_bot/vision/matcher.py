from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class MatchResult:
    x: int
    y: int
    confidence: float
    width: int
    height: int

    @property
    def center(self) -> tuple[int, int]:
        return self.x + self.width // 2, self.y + self.height // 2


class TemplateMatcher:
    """Multi-scale OpenCV template matching."""

    def __init__(
        self,
        threshold: float = 0.82,
        scale_range: list[float] | None = None,
    ) -> None:
        self.threshold = threshold
        self.scale_range = scale_range or [0.95, 1.0, 1.05]

    @staticmethod
    def _to_gray(image: np.ndarray) -> np.ndarray:
        if len(image.shape) == 2:
            return image
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    def find(
        self,
        frame: np.ndarray,
        template: np.ndarray,
        threshold: float | None = None,
        roi: np.ndarray | None = None,
    ) -> MatchResult | None:
        thresh = threshold if threshold is not None else self.threshold
        search = frame if roi is None else roi
        gray_search = self._to_gray(search)
        gray_template = self._to_gray(template)

        best: MatchResult | None = None
        th, tw = gray_template.shape[:2]

        for scale in self.scale_range:
            sw = max(1, int(tw * scale))
            sh = max(1, int(th * scale))
            if sw >= gray_search.shape[1] or sh >= gray_search.shape[0]:
                continue
            scaled = cv2.resize(gray_template, (sw, sh), interpolation=cv2.INTER_AREA)
            result = cv2.matchTemplate(gray_search, scaled, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)
            if max_val >= thresh and (best is None or max_val > best.confidence):
                x, y = max_loc
                if roi is not None:
                    # offset handled by caller if needed
                    pass
                best = MatchResult(x=x, y=y, confidence=float(max_val), width=sw, height=sh)
        return best

    def find_all(
        self,
        frame: np.ndarray,
        template: np.ndarray,
        threshold: float | None = None,
        max_matches: int = 10,
    ) -> list[MatchResult]:
        thresh = threshold if threshold is not None else self.threshold
        gray_frame = self._to_gray(frame)
        gray_template = self._to_gray(template)
        th, tw = gray_template.shape[:2]
        if tw > gray_frame.shape[1] or th > gray_frame.shape[0]:
            return []
        result = cv2.matchTemplate(gray_frame, gray_template, cv2.TM_CCOEFF_NORMED)
        matches: list[MatchResult] = []
        working = result.copy()
        for _ in range(max_matches):
            _, max_val, _, max_loc = cv2.minMaxLoc(working)
            if max_val < thresh:
                break
            x, y = max_loc
            matches.append(MatchResult(x=x, y=y, confidence=float(max_val), width=tw, height=th))
            cv2.rectangle(
                working,
                (max(0, x - tw // 2), max(0, y - th // 2)),
                (min(working.shape[1], x + tw + tw // 2), min(working.shape[0], y + th + th // 2)),
                0,
                -1,
            )
        return matches

    def find_in_roi(
        self,
        frame: np.ndarray,
        template: np.ndarray,
        roi_dict: dict | list,
        threshold: float | None = None,
    ) -> MatchResult | None:
        from coc_bot.vision.rois import ROI, crop_roi, denormalize_roi

        roi = ROI(*roi_dict) if isinstance(roi_dict, (list, tuple)) else ROI(**roi_dict)
        h, w = frame.shape[:2]
        x0, y0, _, _ = denormalize_roi(roi, w, h)
        cropped = crop_roi(frame, roi)
        match = self.find(cropped, template, threshold=threshold)
        if match is None:
            return None
        return MatchResult(
            x=match.x + x0,
            y=match.y + y0,
            confidence=match.confidence,
            width=match.width,
            height=match.height,
        )

    @staticmethod
    def load_template(path: str) -> np.ndarray:
        import cv2

        img = cv2.imread(path, cv2.IMREAD_COLOR)
        if img is None:
            raise FileNotFoundError(f"Template not found: {path}")
        return img
