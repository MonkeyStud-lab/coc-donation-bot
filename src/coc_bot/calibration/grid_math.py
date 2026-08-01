"""Helpers for donation-panel slot grid geometry (relative to bar ROIs)."""

from __future__ import annotations

from typing import Any

from coc_bot.config import BotConfig
from coc_bot.vision.rois import ROI, denormalize_roi, normalize_roi

# grid_key → donation bar ROI key in calibrated.yaml
GRID_BAR_ROI_KEYS: dict[str, str] = {
    "troop_bar": "donation_troop_bar",
    "spell_bar": "donation_spell_bar",
}

GRID_DEFAULTS: dict[str, tuple[int, int]] = {
    "troop_bar": (7, 2),
    "spell_bar": (5, 1),
}


def grid_relative_to_bar(
    grid_roi: tuple[int, int, int, int],
    bar_roi_key: str,
    config: BotConfig,
    frame_w: int,
    frame_h: int,
) -> dict[str, float]:
    """
    Express a pixel grid ROI as fractions of the bar ROI (or of the frame).

    Returns ``{x, y, w, h}`` without cols/rows.
    """
    gx, gy, gw, gh = grid_roi
    if bar_roi_key not in config.rois:
        nr = normalize_roi(gx, gy, gw, gh, frame_w, frame_h)
        return {"x": nr.x, "y": nr.y, "w": nr.w, "h": nr.h}

    bx, by, bw, bh = denormalize_roi(ROI(*config.rois[bar_roi_key]), frame_w, frame_h)
    if bw <= 0 or bh <= 0:
        raise ValueError(f"Invalid bar ROI: {bar_roi_key}")

    return {
        "x": (gx - bx) / bw,
        "y": (gy - by) / bh,
        "w": gw / bw,
        "h": gh / bh,
    }


def build_grid_entry(
    grid_roi: tuple[int, int, int, int],
    grid_key: str,
    config: BotConfig,
    frame_w: int,
    frame_h: int,
    cols: int,
    rows: int,
) -> dict[str, Any]:
    bar_key = GRID_BAR_ROI_KEYS.get(grid_key, "")
    rel = grid_relative_to_bar(grid_roi, bar_key, config, frame_w, frame_h)
    rel["cols"] = int(cols)
    rel["rows"] = int(rows)
    return rel
