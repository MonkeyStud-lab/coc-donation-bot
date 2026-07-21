from __future__ import annotations

import time

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

    BAR_KEYS = ("donation_troop_bar", "donation_spell_bar")

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
                    logger.info("Open request — donating all colored slots (bars may scroll)")
                    made_donation = self._donate_open_request()
                    if not made_donation:
                        logger.warning("No colored slots tapped for open request")
                        break
                    donated_any = True
                    time.sleep(0.4)
                    continue
                logger.debug("No requested units detected")
                break

            # Specific request: CoC sorts requested units to the front; grey slots follow.
            slots = self.inventory_parser.parse_slots(
                frame,
                require_unit_id=False,
                stop_at_grey=True,
            )
            if not slots:
                logger.warning("No colored slots at start of troop/spell bars")
                break

            made_donation = self._donate_round(requested, slots)
            if not made_donation:
                break
            donated_any = True
            time.sleep(0.4)

        self._close_panel()
        return donated_any

    def _donate_round(self, requested: list[RequestedUnit], slots: list[InventorySlot]) -> bool:
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

        if made:
            return True

        # CoC sorts requested units into the first colored slots — match by position when templates miss.
        colored = [s for s in slots if s.quantity > 0]
        if len(colored) >= len(sorted_requests):
            logger.info("Using slot order for specific request (unit templates did not match)")
            for req, slot in zip(sorted_requests, colored):
                donate_qty = min(req.quantity, slot.quantity)
                if donate_qty <= 0:
                    continue
                logger.info("Donating {} x {} via ordered slot @ {}", donate_qty, req.unit_id, slot.center)
                for _ in range(donate_qty):
                    self.input.tap(*slot.center)
                made = True

        return made

    def _donate_open_request(self) -> bool:
        """Donate every colored slot, scrolling troop/spell bars horizontally as needed."""
        made = False
        for bar_key in self.BAR_KEYS:
            if bar_key not in self.config.rois:
                continue
            if self._donate_colored_bar(bar_key):
                made = True
        return made

    def _donate_colored_bar(self, bar_roi_key: str) -> bool:
        max_scrolls = self.config.bar_max_scroll_attempts
        tapped: set[tuple[int, int]] = set()
        made = False

        for attempt in range(max_scrolls + 1):
            frame = self.capture.screenshot()
            slots = self.inventory_parser.parse_bar_slots(
                frame,
                bar_roi_key,
                require_unit_id=False,
            )
            fresh = [slot for slot in slots if slot.center not in tapped]
            if not fresh:
                if attempt == 0:
                    logger.debug("No colored slots visible in {}", bar_roi_key)
                break

            for slot in fresh:
                logger.info(
                    "Open request: tapping {} x{} at {}",
                    slot.unit_id,
                    slot.quantity,
                    slot.center,
                )
                for _ in range(slot.quantity):
                    self.input.tap(*slot.center)
                tapped.add(slot.center)
                made = True

            if attempt >= max_scrolls:
                break

            x1, y1, x2, y2 = self.inventory_parser.bar_swipe_line(frame, bar_roi_key)
            logger.debug(
                "Scrolling {} toward right ({},{}) -> ({},{}) [{}/{}]",
                bar_roi_key,
                x1,
                y1,
                x2,
                y2,
                attempt + 1,
                max_scrolls,
            )
            self.input.swipe(x1, y1, x2, y2, duration_ms=280)
            time.sleep(0.35)

        return made

    def _close_panel(self) -> None:
        from coc_bot.donation.navigator import Navigator

        Navigator(self.config, self.capture, self.input, self.matcher).close_donation_panel()
