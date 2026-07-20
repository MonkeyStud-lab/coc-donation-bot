from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from coc_bot.config import BotConfig, save_calibrated
from coc_bot.vision.rois import normalize_roi


def save_template(frame: np.ndarray, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), frame)


def crop_by_coords(frame: np.ndarray, coords: tuple[int, int, int, int]) -> np.ndarray:
    x, y, w, h = coords
    return frame[y : y + h, x : x + w].copy()


def sample_center_color(frame: np.ndarray, coords: tuple[int, int, int, int]) -> list[int]:
    crop = crop_by_coords(frame, coords)
    cy, cx = crop.shape[0] // 2, crop.shape[1] // 2
    bgr = crop[cy, cx].tolist()
    return [int(v) for v in bgr]


def prompt_roi(label: str) -> tuple[int, int, int, int]:
    print(f"\n--- {label} ---")
    print("Enter ROI as: x y width height (pixels)")
    while True:
        raw = input("> ").strip()
        parts = raw.split()
        if len(parts) == 4:
            try:
                return tuple(int(p) for p in parts)  # type: ignore[return-value]
            except ValueError:
                pass
        print("Invalid input. Example: 100 200 800 600")


def prompt_point(label: str) -> tuple[int, int]:
    print(f"\n--- {label} ---")
    print("Enter tap point as: x y")
    while True:
        raw = input("> ").strip()
        parts = raw.split()
        if len(parts) == 2:
            try:
                return int(parts[0]), int(parts[1])
            except ValueError:
                pass
        print("Invalid input. Example: 540 960")


def prompt_yes_no(label: str) -> bool:
    raw = input(f"{label} [y/N]: ").strip().lower()
    return raw in ("y", "yes")
