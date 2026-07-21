from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from coc_bot.config import BotConfig
from coc_bot.vision.colors import SlotColorDetector
from coc_bot.vision.matcher import TemplateMatcher
from coc_bot.vision.ocr import QuantityOCR
from coc_bot.vision.rois import crop_roi


@dataclass
class InventorySlot:
    unit_id: str
    quantity: int
    center: tuple[int, int]
    category: str


class InventoryParser:
    """Parse available castle troops/spells/siege in the donation panel."""

    def __init__(self, config: BotConfig, matcher: TemplateMatcher | None = None) -> None:
        self.config = config
        self.matcher = matcher or TemplateMatcher(threshold=config.template_threshold)
        self.ocr = QuantityOCR(confidence_threshold=config.ocr_confidence_threshold)
        self.color_detector = SlotColorDetector(
            troop_color_bgr=config.colors.get("donatable_troop"),
            spell_color_bgr=config.colors.get("donatable_spell"),
        )
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

    def parse(self, frame: np.ndarray) -> dict[str, int]:
        inventory: dict[str, int] = {}
        slots = self.parse_slots(frame)
        for slot in slots:
            inventory[slot.unit_id] = inventory.get(slot.unit_id, 0) + slot.quantity
        return inventory

    def parse_slots(self, frame: np.ndarray) -> list[InventorySlot]:
        slots: list[InventorySlot] = []
        # Troops and siege machines share the same bar in CoC's donation panel.
        bar_configs = [
            ("donation_troop_bar", self.color_detector.is_donatable_troop),
            ("donation_spell_bar", self.color_detector.is_donatable_spell),
        ]
        for roi_key, is_donatable in bar_configs:
            if roi_key not in self.config.rois:
                continue
            bar = crop_roi(frame, self.config.rois[roi_key])
            grid_key = "troop_bar" if roi_key == "donation_troop_bar" else "spell_bar"
            grid = self.config.grid.get(grid_key, {})
            default_category = "troop" if roi_key == "donation_troop_bar" else "spell"
            slots.extend(
                self._walk_bar(bar, is_donatable, grid, frame, roi_key, default_category)
            )
        return slots

    def _walk_bar(
        self,
        bar: np.ndarray,
        is_donatable,
        grid: dict,
        frame: np.ndarray,
        roi_key: str,
        default_category: str,
    ) -> list[InventorySlot]:
        from coc_bot.vision.rois import ROI, denormalize_roi

        slots: list[InventorySlot] = []
        cols = int(grid.get("cols", 8 if default_category == "troop" else 5))
        rows = int(grid.get("rows", 1))
        slot_w = int(grid.get("slot_width", bar.shape[1] // max(cols, 1)))
        slot_h = int(grid.get("slot_height", bar.shape[0] // max(rows, 1)))

        fh, fw = frame.shape[:2]
        bar_x, bar_y, _, _ = denormalize_roi(ROI(*self.config.rois[roi_key]), fw, fh)

        for row in range(rows):
            for col in range(cols):
                x0 = col * slot_w
                y0 = row * slot_h
                if x0 + slot_w > bar.shape[1] or y0 + slot_h > bar.shape[0]:
                    continue
                cell = bar[y0 : y0 + slot_h, x0 : x0 + slot_w]
                if not is_donatable(cell):
                    continue
                unit_id = self._identify_unit(cell)
                if unit_id is None:
                    continue
                info = self.config.units.get(unit_id)
                category = info.category if info else default_category
                qty = self._read_quantity(cell)
                cx = bar_x + x0 + slot_w // 2
                cy = bar_y + y0 + slot_h // 2
                slots.append(
                    InventorySlot(unit_id=unit_id, quantity=qty, center=(cx, cy), category=category)
                )
        return slots

    def _identify_unit(self, cell: np.ndarray) -> str | None:
        best_id = None
        best_conf = 0.0
        icon = cell[: int(cell.shape[0] * 0.75), :]
        for unit_id in self.config.unit_templates:
            template = self._load_unit_template(unit_id)
            if template is None:
                continue
            match = self.matcher.find(icon, template, threshold=self.config.template_threshold - 0.05)
            if match and match.confidence > best_conf:
                best_conf = match.confidence
                best_id = unit_id
        return best_id

    def _read_quantity(self, cell: np.ndarray) -> int:
        h, w = cell.shape[:2]
        badge = cell[int(h * 0.65) :, int(w * 0.55) :]
        qty = self.ocr.read_quantity(badge)
        return qty if qty is not None else 1

    def find_slot_for_unit(self, slots: list[InventorySlot], unit_id: str) -> InventorySlot | None:
        for slot in slots:
            if slot.unit_id == unit_id and slot.quantity > 0:
                return slot
        return None
