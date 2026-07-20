from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from coc_bot.config import BotConfig
from coc_bot.vision.matcher import TemplateMatcher
from coc_bot.vision.ocr import QuantityOCR
from coc_bot.vision.rois import crop_roi, denormalize_roi, ROI


@dataclass
class RequestedUnit:
    unit_id: str
    quantity: int


class RequestParser:
    """Parse requested units from the donation panel header."""

    def __init__(self, config: BotConfig, matcher: TemplateMatcher | None = None) -> None:
        self.config = config
        self.matcher = matcher or TemplateMatcher(threshold=config.template_threshold)
        self.ocr = QuantityOCR(confidence_threshold=config.ocr_confidence_threshold)
        self._unit_templates: dict[str, np.ndarray] = {}

    def _load_unit_template(self, unit_id: str) -> np.ndarray | None:
        if unit_id in self._unit_templates:
            return self._unit_templates[unit_id]
        rel = self.config.unit_templates.get(unit_id)
        if not rel:
            return None
        path = self.config.templates_dir / rel
        if not path.exists():
            return None
        img = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if img is not None:
            self._unit_templates[unit_id] = img
        return img

    def parse(self, frame: np.ndarray) -> list[RequestedUnit]:
        if "request_header" not in self.config.rois:
            return self._parse_full_bar(frame)

        header = crop_roi(frame, self.config.rois["request_header"])
        return self._match_units_in_region(header)

    def _parse_full_bar(self, frame: np.ndarray) -> list[RequestedUnit]:
        results: list[RequestedUnit] = []
        for roi_key in ("request_header", "donation_troop_bar"):
            if roi_key in self.config.rois:
                region = crop_roi(frame, self.config.rois[roi_key])
                results.extend(self._match_units_in_region(region))
        return results

    def _match_units_in_region(self, region: np.ndarray) -> list[RequestedUnit]:
        requested: list[RequestedUnit] = []
        grid = self.config.grid.get("request", {})
        cols = int(grid.get("cols", 6))
        slot_w = int(grid.get("slot_width", region.shape[1] // max(cols, 1)))
        slot_h = int(grid.get("slot_height", region.shape[0]))

        for col in range(cols):
            x0 = col * slot_w
            if x0 + slot_w > region.shape[1]:
                break
            slot = region[0:slot_h, x0 : x0 + slot_w]
            unit_id = self._identify_unit(slot)
            if unit_id is None:
                continue
            qty = self._read_quantity(slot)
            if qty <= 0:
                qty = 1
            requested.append(RequestedUnit(unit_id=unit_id, quantity=qty))
        return requested

    def _identify_unit(self, slot: np.ndarray) -> str | None:
        best_id = None
        best_conf = 0.0
        icon = slot[: int(slot.shape[0] * 0.75), :]
        for unit_id in self.config.unit_templates:
            template = self._load_unit_template(unit_id)
            if template is None:
                continue
            match = self.matcher.find(icon, template, threshold=self.config.template_threshold - 0.05)
            if match and match.confidence > best_conf:
                best_conf = match.confidence
                best_id = unit_id
        return best_id

    def _read_quantity(self, slot: np.ndarray) -> int:
        h, w = slot.shape[:2]
        badge = slot[int(h * 0.65) :, int(w * 0.55) :]
        qty = self.ocr.read_quantity(badge)
        return qty if qty is not None else 1
