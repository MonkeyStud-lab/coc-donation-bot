#!/usr/bin/env python3
"""
Draw the troop/spell slot grid on a screenshot and save to data/calibrated.yaml.

Usage:
  python scripts/pick_grid.py              # ADB screenshot, pick troop then spell grid
  python scripts/pick_grid.py --troop-only
  python scripts/pick_grid.py ~/screen.png

Controls (same as pick_coordinates.py):
  2 clicks — top-left and bottom-right of the full slot grid (all visible rows/columns)
  r — new screenshot   c — clear   q — quit
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import cv2

from pick_coordinates import load_frame_from_adb, load_frame_from_path

from coc_bot.calibration.picker import InteractivePicker
from coc_bot.config import load_config, save_calibrated
from coc_bot.vision.rois import ROI, denormalize_roi, normalize_roi


def _roi_from_points(points: list[tuple[int, int]]) -> tuple[int, int, int, int] | None:
    if len(points) != 2:
        return None
    x1, y1 = points[0]
    x2, y2 = points[1]
    return min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1)


def _grid_relative_to_bar(
    grid_roi: tuple[int, int, int, int],
    bar_roi_key: str,
    config,
    frame_w: int,
    frame_h: int,
) -> dict:
    gx, gy, gw, gh = grid_roi
    if bar_roi_key not in config.rois:
        nr = normalize_roi(gx, gy, gw, gh, frame_w, frame_h)
        return {"cols": 0, "rows": 0, "x": nr.x, "y": nr.y, "w": nr.w, "h": nr.h}

    bx, by, bw, bh = denormalize_roi(ROI(*config.rois[bar_roi_key]), frame_w, frame_h)
    if bw <= 0 or bh <= 0:
        raise ValueError(f"Invalid bar ROI: {bar_roi_key}")

    return {
        "x": (gx - bx) / bw,
        "y": (gy - by) / bh,
        "w": gw / bw,
        "h": gh / bh,
    }


def _pick_grid(label: str, frame) -> tuple[int, int, int, int] | None:
    try:
        import tkinter as tk
    except ImportError:
        print("tkinter required: sudo apt install python3-tk")
        sys.exit(1)

    print(f"\n=== {label} ===")
    print("Draw a box around ALL visible slot cells (top-left click, then bottom-right), then Confirm.")
    root = tk.Tk()
    picker = InteractivePicker(root, frame, mode="roi", title=f"Grid: {label}")
    picker.set_refresh_callback(load_frame_from_adb)
    root.mainloop()
    if picker.result is not None and len(picker.result) == 4:
        return picker.result  # type: ignore[return-value]
    return _roi_from_points(picker.points)


def _prompt_int(label: str, default: int) -> int:
    raw = input(f"{label} [{default}]: ").strip()
    return int(raw) if raw else default


def main() -> None:
    parser = argparse.ArgumentParser(description="Draw donation panel slot grids")
    parser.add_argument("image", nargs="?", help="Screenshot path (default: ADB capture)")
    parser.add_argument("--troop-only", action="store_true")
    parser.add_argument("--spell-only", action="store_true")
    args = parser.parse_args()

    config = load_config()
    if not config.calibrated:
        print("Run calibration first (at least donation_panel step for bar ROIs).")
        sys.exit(1)

    if args.image:
        frame = load_frame_from_path(Path(args.image).expanduser())
    else:
        print("Open the donation panel on device, then continue.")
        input("Press Enter to capture screenshot...")
        frame = load_frame_from_adb()

    fh, fw = frame.shape[:2]
    grid = dict(config.grid or {})

    bars = []
    if not args.spell_only:
        bars.append(("donation_troop_bar", "troop_bar", "Troop+siege grid", 7, 2))
    if not args.troop_only:
        bars.append(("donation_spell_bar", "spell_bar", "Spell grid", 5, 1))

    for bar_roi_key, grid_key, title, default_cols, default_rows in bars:
        if bar_roi_key not in config.rois:
            print(f"\nWARNING: {bar_roi_key} not calibrated — run --step donation_panel first.")
            continue
        roi = _pick_grid(title, frame)
        if roi is None:
            print(f"Skipped {grid_key} (no rectangle drawn).")
            continue
        cols = _prompt_int("Columns (slots per row)", default_cols)
        rows = _prompt_int("Rows", default_rows)
        rel = _grid_relative_to_bar(roi, bar_roi_key, config, fw, fh)
        rel["cols"] = cols
        rel["rows"] = rows
        grid[grid_key] = rel
        print(f"Saved {grid_key}: {cols}x{rows} grid, region x={rel['x']:.3f} y={rel['y']:.3f} w={rel['w']:.3f} h={rel['h']:.3f} (within bar ROI)")

    if not grid:
        print("Nothing saved.")
        sys.exit(1)

    config.grid = grid
    save_calibrated(config)
    print("\nSaved data/calibrated.yaml — run: python scripts/test_inventory.py")


if __name__ == "__main__":
    main()
