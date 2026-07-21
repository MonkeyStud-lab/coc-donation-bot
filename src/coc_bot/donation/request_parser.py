from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from coc_bot.config import BotConfig
from coc_bot.vision.matcher import MatchResult, TemplateMatcher
from coc_bot.vision.ocr import QuantityOCR


@dataclass
class RequestedUnit:
    unit_id: str
    quantity: int


class RequestParser:
    """Parse requested units from the clan chat donation message (not the donation panel)."""

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

    def parse_from_chat(self, frame: np.ndarray, donate_button: MatchResult) -> list[RequestedUnit]:
        """
        Read requested troop/spell icons from the chat message above the Donate button.

        Returns an empty list for open/generic requests (no specific units shown in chat).
        """
        region = self._chat_message_region(frame, donate_button)
        if region.size == 0:
            return []
        return self._match_units_in_region(region)

    def _chat_message_region(self, frame: np.ndarray, donate_button: MatchResult) -> np.ndarray:
        """Crop the chat message bubble sitting above a Donate button."""
        h, w = frame.shape[:2]
        bx, by = donate_button.x, donate_button.y
        bw, bh = donate_button.width, donate_button.height

        msg_h = max(int(bh * 6), 80)
        y0 = max(0, by - msg_h)
        y1 = max(0, by - int(bh * 0.25))
        x0 = max(0, bx - bw * 2)
        x1 = min(w, bx + bw * 10)

        if y1 <= y0 or x1 <= x0:
            return np.array([])

        return frame[y0:y1, x0:x1].copy()

    def _match_units_in_region(self, region: np.ndarray) -> list[RequestedUnit]:
        if not self.config.unit_templates:
            return []

        requested: list[RequestedUnit] = []
        cols = 8
        slot_w = max(1, region.shape[1] // cols)
        slot_h = region.shape[0]

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
