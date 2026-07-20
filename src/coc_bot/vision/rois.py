from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ROI:
    x: float
    y: float
    w: float
    h: float


def normalize_roi(x: int, y: int, w: int, h: int, frame_w: int, frame_h: int) -> ROI:
    return ROI(x / frame_w, y / frame_h, w / frame_w, h / frame_h)


def denormalize_roi(roi: ROI, frame_w: int, frame_h: int) -> tuple[int, int, int, int]:
    x = int(roi.x * frame_w)
    y = int(roi.y * frame_h)
    w = int(roi.w * frame_w)
    h = int(roi.h * frame_h)
    return x, y, w, h


def crop_roi(frame, roi: ROI | dict | list):
    import numpy as np

    h, w = frame.shape[:2]
    if isinstance(roi, dict):
        roi = ROI(roi["x"], roi["y"], roi["w"], roi["h"])
    elif isinstance(roi, (list, tuple)):
        roi = ROI(*roi)
    x, y, rw, rh = denormalize_roi(roi, w, h)
    x = max(0, min(x, w - 1))
    y = max(0, min(y, h - 1))
    rw = max(1, min(rw, w - x))
    rh = max(1, min(rh, h - y))
    return frame[y : y + rh, x : x + rw].copy()


def roi_center(roi: ROI, frame_w: int, frame_h: int) -> tuple[int, int]:
    x, y, w, h = denormalize_roi(roi, frame_w, frame_h)
    return x + w // 2, y + h // 2
