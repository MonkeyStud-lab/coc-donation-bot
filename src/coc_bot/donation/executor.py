from __future__ import annotations

import time

import cv2
from loguru import logger

from coc_bot.adb.capture import ScreenCapture
from coc_bot.adb.input import InputController
from coc_bot.config import BotConfig
from coc_bot.donation.inventory import InventoryParser, InventorySlot
from coc_bot.donation.request_parser import RequestParser, RequestedUnit
from coc_bot.vision.matcher import TemplateMatcher
from coc_bot.vision.screens import ScreenClassifier, ScreenType


class DonationExecutor:
    """Execute partial donation fulfillment for troops, spells, and siege."""

    def __init__(
        self,
        config: BotConfig,
        capture: ScreenCapture,
        input_ctrl: InputController,
        matcher: TemplateMatcher | None = None,
    ) -> None:
        self.config = config
        self.capture = capture
        self.input = input_ctrl
        self.matcher = matcher or TemplateMatcher(threshold=config.template_threshold)
        self.request_parser = RequestParser(config, self.matcher)
        self.inventory_parser = InventoryParser(config, self.matcher)
        self.classifier = ScreenClassifier(config, self.matcher)

    def donate_for_request(self, max_rounds: int = 20) -> bool:
        """Donate as much as possible for the current open donation panel. Returns True if any donation made."""
        donated_any = False
        for round_num in range(max_rounds):
            frame = self.capture.screenshot()
            screen = self.classifier.classify(frame)
            if not self.classifier.is_donation_panel(frame):
                logger.warning(
                    "Not on donation panel (round {}), detected screen: {}",
                    round_num,
                    screen.value,
                )
                break

            requested = self.request_parser.parse(frame)
            if not requested:
                if self.config.donate_open_requests:
                    logger.info("Open request (no specific units) — donating from castle inventory")
                    made_donation = self._donate_open_request(slots := self.inventory_parser.parse_slots(frame))
                    if not made_donation:
                        logger.debug("No donatable inventory for open request")
                        break
                    donated_any = True
                    time.sleep(0.4)
                    continue
                logger.debug("No requested units detected")
                break

            slots = self.inventory_parser.parse_slots(frame)
            if not slots:
                logger.debug("No donatable inventory slots found")
                break

            made_donation = self._donate_round(requested, slots)
            if not made_donation:
                break
            donated_any = True
            time.sleep(0.4)

        self._close_panel()
        return donated_any

    def _donate_round(self, requested: list[RequestedUnit], slots: list[InventorySlot]) -> bool:
        inventory = {s.unit_id: s for s in slots}
        remaining = {r.unit_id: r.quantity for r in requested}
        made = False

        category_order = {cat: i for i, cat in enumerate(self.config.donation_order)}

        def _category_index(unit_id: str) -> int:
            info = self.config.units.get(unit_id)
            cat = info.category if info else "troop"
            return category_order.get(cat, 99)

        sorted_requests = sorted(requested, key=lambda r: _category_index(r.unit_id))

        for req in sorted_requests:
            need = remaining.get(req.unit_id, 0)
            if need <= 0:
                continue
            slot = self.inventory_parser.find_slot_for_unit(slots, req.unit_id)
            if slot is None or slot.quantity <= 0:
                continue

            donate_qty = min(need, slot.quantity)
            logger.info("Donating {} x {} (requested {})", donate_qty, req.unit_id, need)
            for _ in range(donate_qty):
                self.input.tap(*slot.center)
            remaining[req.unit_id] = need - donate_qty
            made = True

        return made

    def _donate_open_request(self, slots: list[InventorySlot]) -> bool:
        """Donate available castle units when the request does not specify troop types."""
        if not slots:
            return False
        made = False
        for slot in slots:
            if slot.quantity <= 0:
                continue
            logger.info("Open request: tapping {} x{} at {}", slot.unit_id, slot.quantity, slot.center)
            for _ in range(slot.quantity):
                self.input.tap(*slot.center)
            made = True
        return made

    def _close_panel(self) -> None:
        from coc_bot.donation.navigator import Navigator

        Navigator(self.config, self.capture, self.input, self.matcher).close_donation_panel()
