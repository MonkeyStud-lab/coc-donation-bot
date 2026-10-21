"""Verify the selected resource at its calibrated location, never across the panel."""
from __future__ import annotations

import cv2
import numpy as np


def _selection_matches(crop: np.ndarray, template: np.ndarray) -> bool:
    difference = np.abs(crop - template)
    # A thin selection border can occupy less than 10% of the image; checking
    # only the mean/90th percentile would accidentally accept its removal.
    return bool(float(difference.mean()) <= 10
                and float(np.percentile(difference, 90)) <= 25
                and float(np.percentile(difference, 99)) <= 45)


def elixir_is_selected(config, frame) -> bool:
    relative = config.templates.get("donation_elixir_selected")
    roi = config.rois.get("donation_elixir_selected")
    if not relative or not roi or len(roi) != 4:
        return False
    path = (config.templates_dir / relative).resolve()
    if not path.is_relative_to(config.templates_dir.resolve()):
        return False
    template = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if template is None or template.size == 0:
        return False
    h, w = frame.shape[:2]
    x, y, rw, rh = roi
    if not (0 <= x < 1 and 0 <= y < 1 and rw > 0 and rh > 0 and x + rw <= 1.001 and y + rh <= 1.001):
        return False
    crop = frame[round(y*h):round((y+rh)*h), round(x*w):round((x+rw)*w)]
    if crop.size == 0:
        return False
    crop = cv2.resize(crop, (template.shape[1], template.shape[0]), interpolation=cv2.INTER_AREA)
    # Compare colors as well as shapes: icon-only correlation ignores selection fill.
    observed = crop.astype(np.float32)
    reference = template.astype(np.float32)
    if _selection_matches(observed, reference):
        return True

    # Some captures scale the brightness of the entire game. Correct only one
    # common exposure factor, preserving relative colors, fill and borders.
    # Flat/obscured references cannot provide evidence for this fallback.
    if (cv2.cvtColor(template, cv2.COLOR_BGR2GRAY).std() < 20
            or cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).std() < 10):
        return False
    usable = (reference > 35) & (observed > 20)
    if np.count_nonzero(usable) < max(64, reference.size * .3):
        return False
    gain = float(np.median(observed[usable] / reference[usable]))
    if not np.isfinite(gain) or not .65 <= gain <= 1.35:
        return False
    # Keep the exact-match error limits, including the 99th percentile. Matching
    # the elixir icon alone must never confirm a gem-selected button.
    return _selection_matches(observed / gain, reference)
