from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from coc_bot.calibration.picker import pick_interactive


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


def _typed_roi(label: str) -> tuple[int, int, int, int]:
    print(f"\n--- {label} (typed fallback) ---")
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


def _typed_point(label: str) -> tuple[int, int]:
    print(f"\n--- {label} (typed fallback) ---")
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


def prompt_roi(
    label: str,
    frame: np.ndarray | None = None,
    *,
    refresh_cb=None,
    return_frame: bool = False,
):
    """
    Pick an ROI via screenshot popup (preferred) or typed coordinates.

    Pass ``frame`` when the wizard already captured the correct screen so the
    picker shows that exact image. If ``return_frame`` is True, returns
    ``(roi, frame_used)``.
    """
    result, used = pick_interactive(frame, label, mode="roi", refresh_cb=refresh_cb)
    if result is not None and len(result) == 4:
        x, y, w, h = (int(v) for v in result)
        if w > 0 and h > 0:
            print(f"Selected ROI: {x} {y} {w} {h}")
            roi = (x, y, w, h)
            if return_frame:
                return roi, used if used is not None else frame
            return roi
        print("ROI was empty — try again or type coordinates.")
    else:
        print("Picker cancelled or unavailable.")
    roi = _typed_roi(label)
    if return_frame:
        return roi, used if used is not None else frame
    return roi


def prompt_point(
    label: str,
    frame: np.ndarray | None = None,
    *,
    refresh_cb=None,
) -> tuple[int, int]:
    """Pick a tap point via screenshot popup (preferred) or typed coordinates."""
    result, _used = pick_interactive(frame, label, mode="point", refresh_cb=refresh_cb)
    if result is not None and len(result) == 2:
        x, y = int(result[0]), int(result[1])
        print(f"Selected point: {x} {y}")
        return x, y
    print("Picker cancelled or unavailable.")
    return _typed_point(label)


def prompt_yes_no(label: str) -> bool:
    raw = input(f"{label} [y/N]: ").strip().lower()
    return raw in ("y", "yes")
