"""Read-only donation setup proposals from generic, visible interface anchors.

This is a conservative reference localizer, not the learned screen classifier or
a general object detector. It never reads saved calibration or issues game input.
Only the inspected English 7-column, two-troop-row/one-spell-row layout is offered.
"""
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np


PARTS = frozenset({"donation_panel", "donation_elixir_button",
                   "donation_troop_bar", "donation_spell_bar", "troop_bar", "spell_bar"})
# Reference geometry in pixels; located relative to the visible title, never
# absolute screenshot coordinates. Partial cards at the right edge are excluded.
REFERENCE = {
    "title": (768, 110, 405, 43),
    "troops": (744, 211, 178, 27),
    "spells": (744, 612, 177, 28),
    "gem": (1547, 97, 65, 75),
}
REGIONS = {
    "donation_panel": REFERENCE["title"],
    "donation_elixir_button": (1219, 88, 226, 96),
    "donation_troop_bar": (753, 252, 913, 327),
    "donation_spell_bar": (753, 657, 913, 159),
    "troop_bar": (753, 252, 913, 327),
    "spell_bar": (753, 657, 913, 159),
}


@lru_cache(maxsize=4)
def _reference(name):
    return cv2.imread(str(Path(__file__).with_name("assets") / f"donation_{name}.png"),
                      cv2.IMREAD_GRAYSCALE)


def suggest_donation(frame):
    """Return proposals in original pixels, or an explicit abstention.

    Correlation scores describe reference similarity, not calibrated probability.
    Missing/obscured anchors, dimming, clipped proposed areas and unsupported
    layouts cause abstention. The user must still check every proposed outline.
    """
    empty = {"supported": False, "method": "donation-reference-v1", "proposals": [],
             "message": "No supported donation panel found. Open a donation panel, or draw the area manually."}
    if (not isinstance(frame, np.ndarray) or frame.dtype != np.uint8 or frame.ndim != 3
            or frame.shape[2] != 3):
        return empty
    height, width = frame.shape[:2]
    if height < 360 or width < 640 or not 1.55 <= width / height <= 2.05:
        return empty
    ratio = 960 / width
    small = cv2.resize(frame, (960, round(height * ratio)), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    title = _reference("title")
    if title is None:
        return empty
    best = None
    for zoom in (.85, .925, 1., 1.075, 1.15):
        scale = 960 / 1853 * zoom
        template = cv2.resize(title, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        # Search only where a full panel can fit. Later checks establish identity.
        search = gray[:round(gray.shape[0] * .65)]
        if min(template.shape) < 5 or any(a > b for a, b in zip(template.shape, search.shape)):
            continue
        _, score, _, (tx, ty) = cv2.minMaxLoc(cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED))
        if score < .86:
            continue
        ox, oy = tx - REFERENCE["title"][0] * scale, ty - REFERENCE["title"][1] * scale

        def transform(box):
            x, y, w, h = box
            return (round(ox + x * scale), round(oy + y * scale), round(w * scale), round(h * scale))

        scores = [float(score)]
        for name in ("troops", "spells", "gem"):
            x, y, w, h = transform(REFERENCE[name])
            ref = _reference(name)
            if ref is None:
                break
            ref = cv2.resize(ref, (w, h), interpolation=cv2.INTER_AREA)
            x1, y1, x2, y2 = max(0, x-4), max(0, y-4), min(960, x+w+4), min(gray.shape[0], y+h+4)
            crop = gray[y1:y2, x1:x2]
            if crop.shape[0] < h or crop.shape[1] < w:
                break
            scores.append(float(cv2.minMaxLoc(cv2.matchTemplate(crop, ref, cv2.TM_CCOEFF_NORMED))[1]))
        if len(scores) != 4 or min(scores) < .82:
            continue
        x, y, w, h = transform(REFERENCE["title"])
        crop = gray[y:y+h, x:x+w]
        # Normalized correlation alone also matches a darkened page behind a popup.
        if crop.size == 0 or float((crop > 215).mean()) < .15:
            continue
        proposals = []
        valid = True
        for part, rect in REGIONS.items():
            x, y, w, h = transform(rect)
            selection = [round(x / ratio), round(y / ratio), round(w / ratio), round(h / ratio)]
            a, b, rw, rh = selection
            if a < 0 or b < 0 or rw < 4 or rh < 4 or a+rw > width or b+rh > height:
                valid = False
                break
            proposal = {"part": part, "selection": selection}
            if part in ("troop_bar", "spell_bar"):
                proposal.update(cols=7, rows=2 if part == "troop_bar" else 1)
            proposals.append(proposal)
        if not valid:
            continue
        candidate = {"supported": True, "method": "donation-reference-v1",
                     "reference_similarity": round(min(scores), 4), "proposals": proposals,
                     "message": "Suggested area — check the outline before saving. Resource selection and slot colors still need manual verification."}
        if best is None or candidate["reference_similarity"] > best["reference_similarity"]:
            best = candidate
    return best or empty
