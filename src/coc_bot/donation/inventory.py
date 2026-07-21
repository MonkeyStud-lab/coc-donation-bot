from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from loguru import logger

from coc_bot.config import BotConfig
from coc_bot.vision.colors import SlotColorDetector
from coc_bot.vision.matcher import TemplateMatcher
from coc_bot.vision.rois import ROI, crop_roi, denormalize_roi


@dataclass
class InventorySlot:
    unit_id: str
    quantity: int
    center: tuple[int, int]
    category: str


class InventoryParser:
    """Parse donatable troops/spells/siege in the donation panel troop+spell bars."""

    BAR_CONFIGS = (
        ("donation_troop_bar", "troop_bar", "troop"),
        ("donation_spell_bar", "spell_bar", "spell"),
    )

    def __init__(self, config: BotConfig, matcher: TemplateMatcher | None = None) -> None:
        self.config = config
        self.matcher = matcher or TemplateMatcher(threshold=config.template_threshold)
        self.color_detector = SlotColorDetector(
            troop_color_bgr=config.colors.get("donatable_troop"),
            troop_grey_bgr=config.colors.get("disabled_troop"),
            spell_color_bgr=config.colors.get("donatable_spell"),
            spell_grey_bgr=config.colors.get("disabled_spell"),
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
        for slot in self.parse_slots(frame):
            inventory[slot.unit_id] = inventory.get(slot.unit_id, 0) + slot.quantity
        return inventory

    def parse_slots(
        self,
        frame: np.ndarray,
        *,
        require_unit_id: bool = True,
        stop_at_grey: bool = False,
        roi_keys: tuple[str, ...] | None = None,
    ) -> list[InventorySlot]:
        """Parse colored (donatable) slots currently visible in the troop/spell bars."""
        slots: list[InventorySlot] = []
        for bar_roi_key, grid_key, default_category in self.BAR_CONFIGS:
            if roi_keys is not None and bar_roi_key not in roi_keys:
                continue
            if bar_roi_key not in self.config.rois:
                continue
            slots.extend(
                self.parse_bar_slots(
                    frame,
                    bar_roi_key,
                    default_category=default_category,
                    require_unit_id=require_unit_id,
                    stop_at_grey=stop_at_grey,
                )
            )

        if not slots and not stop_at_grey:
            self._log_empty_inventory_hint(require_unit_id=require_unit_id)
        return slots

    def parse_bar_slots(
        self,
        frame: np.ndarray,
        bar_roi_key: str,
        *,
        default_category: str | None = None,
        require_unit_id: bool = True,
        stop_at_grey: bool = False,
    ) -> list[InventorySlot]:
        if bar_roi_key not in self.config.rois:
            return []

        if default_category is None:
            default_category = "troop" if bar_roi_key == "donation_troop_bar" else "spell"

        is_donatable = (
            self.color_detector.is_donatable_troop
            if default_category == "troop"
            else self.color_detector.is_donatable_spell
        )
        grid_key = "troop_bar" if bar_roi_key == "donation_troop_bar" else "spell_bar"
        bar = crop_roi(frame, self.config.rois[bar_roi_key])
        grid = self.config.grid.get(grid_key, {})
        bar, x_off, y_off = self._crop_bar_to_grid(bar, grid)
        return self._walk_bar(
            bar,
            is_donatable,
            grid,
            frame,
            bar_roi_key,
            default_category,
            require_unit_id=require_unit_id,
            stop_at_grey=stop_at_grey,
            bar_x_offset=x_off,
            bar_y_offset=y_off,
        )

    @staticmethod
    def _crop_bar_to_grid(bar: np.ndarray, grid: dict) -> tuple[np.ndarray, int, int]:
        """Use drawn grid region (x,y,w,h relative to bar ROI) when present."""
        if not all(k in grid for k in ("x", "y", "w", "h")):
            return bar, 0, 0
        bh, bw = bar.shape[:2]
        x0 = int(grid["x"] * bw)
        y0 = int(grid["y"] * bh)
        x1 = int((grid["x"] + grid["w"]) * bw)
        y1 = int((grid["y"] + grid["h"]) * bh)
        x0 = max(0, min(x0, bw - 1))
        y0 = max(0, min(y0, bh - 1))
        x1 = max(x0 + 1, min(x1, bw))
        y1 = max(y0 + 1, min(y1, bh))
        return bar[y0:y1, x0:x1].copy(), x0, y0

    def bar_swipe_line(self, frame: np.ndarray, bar_roi_key: str) -> tuple[int, int, int, int]:
        """Return (x1, y, x2, y) to scroll the bar toward the right (reveal more units)."""
        fh, fw = frame.shape[:2]
        bar_x, bar_y, bar_w, bar_h = denormalize_roi(ROI(*self.config.rois[bar_roi_key]), fw, fh)
        cy = bar_y + bar_h // 2
        x1 = bar_x + int(bar_w * 0.78)
        x2 = bar_x + int(bar_w * 0.22)
        return x1, cy, x2, cy

    def _log_empty_inventory_hint(self, *, require_unit_id: bool) -> None:
        has_color_refs = bool(self.config.colors.get("donatable_troop")) or bool(
            self.config.colors.get("disabled_troop")
        )
        unit_tpl_count = len(self.config.unit_templates)
        troop_roi = "donation_troop_bar" in self.config.rois
        spell_roi = "donation_spell_bar" in self.config.rois

        logger.warning(
            "No colored donatable slots detected (troop_bar={}, spell_bar={}, color_calibrated={}, unit_templates={})",
            troop_roi,
            spell_roi,
            has_color_refs,
            unit_tpl_count,
        )
        if not (troop_roi and spell_roi):
            logger.warning("Run: python scripts/calibrate.py --step donation_panel")
        if not has_color_refs:
            logger.warning("Run: python scripts/calibrate.py --step slot_colors")
        if require_unit_id and unit_tpl_count == 0:
            logger.warning("Run: python scripts/calibrate.py --step units")
        elif require_unit_id and unit_tpl_count > 0:
            logger.warning(
                "Unit templates exist but none matched — recalibrate units/grid or lower template_threshold"
            )

    def _walk_bar(
        self,
        bar: np.ndarray,
        is_donatable,
        grid: dict,
        frame: np.ndarray,
        roi_key: str,
        default_category: str,
        *,
        require_unit_id: bool = True,
        stop_at_grey: bool = False,
        bar_x_offset: int = 0,
        bar_y_offset: int = 0,
    ) -> list[InventorySlot]:
        slots: list[InventorySlot] = []
        cols = int(grid.get("cols", 6 if default_category == "troop" else 4))
        rows = int(grid.get("rows", 1))
        slot_w = int(grid.get("slot_width", bar.shape[1] // max(cols, 1)))
        slot_h = int(grid.get("slot_height", bar.shape[0] // max(rows, 1)))

        fh, fw = frame.shape[:2]
        bar_x, bar_y, _, _ = denormalize_roi(ROI(*self.config.rois[roi_key]), fw, fh)
        bar_x += bar_x_offset
        bar_y += bar_y_offset

        for row in range(rows):
            row_had_colored = False
            for col in range(cols):
                x0 = col * slot_w
                y0 = row * slot_h
                if x0 + slot_w > bar.shape[1] or y0 + slot_h > bar.shape[0]:
                    continue
                cell = bar[y0 : y0 + slot_h, x0 : x0 + slot_w]
                if not SlotColorDetector.has_icon(cell):
                    continue
                if not is_donatable(cell):
                    if stop_at_grey and row_had_colored:
                        break
                    continue
                row_had_colored = True
                unit_id = self._identify_unit(cell)
                if unit_id is None:
                    if require_unit_id:
                        continue
                    unit_id = f"{default_category}_slot_{row}_{col}"
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
        """Donation bar slots show elixir cost, not stack size — always 1 per tap."""
        return 1

    def find_slot_for_unit(self, slots: list[InventorySlot], unit_id: str) -> InventorySlot | None:
        for slot in slots:
            if slot.unit_id == unit_id and slot.quantity > 0:
                return slot
        return None
