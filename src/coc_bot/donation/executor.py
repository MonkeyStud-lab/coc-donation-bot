from __future__ import annotations

import time

from loguru import logger

from coc_bot.adb.capture import ScreenCapture
from coc_bot.adb.input import InputController
from coc_bot.config import BotConfig
from coc_bot.donation.inventory import InventoryParser, InventorySlot
from coc_bot.vision.matcher import TemplateMatcher
from coc_bot.vision.screens import ScreenClassifier


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
        self.inventory_parser = InventoryParser(config)
        self.classifier = ScreenClassifier(config, self.matcher)

    def donate_for_request(
        self,
        *,
        is_specific: bool = True,
        max_rounds: int = 20,
    ) -> bool:
        """Donate for the current donation panel using colored slot detection."""
        frame = self.capture.screenshot()
        if not self.classifier.is_donation_panel(frame):
            logger.warning(
                "Not on donation panel, detected screen: {}",
                self.classifier.classify(frame).value,
            )
            self._close_panel()
            return False

        if is_specific:
            logger.info("Specific request — donating colored slots until first grey per row")
            donated_any = self._donate_specific_by_colored_slots(max_rounds=max_rounds)
            self._close_panel()
            return donated_any

        if self.config.donate_open_requests:
            logger.info("Open request — donating all colored slots (bars may scroll)")
            donated_any = self._donate_open_request()
            self._close_panel()
            return donated_any

        logger.info("Open/generic request — skipping donation (specific requests only)")
        self._close_panel()
        return False

    def _donate_specific_by_colored_slots(self, max_rounds: int = 20) -> bool:
        """Donate every colored slot up to the first grey per row."""
        donated_any = False
        for _round in range(max_rounds):
            frame = self.capture.screenshot()
            if not self.classifier.is_donation_panel(frame):
                break
            slots = self.inventory_parser.parse_slots(frame, stop_at_grey=True)
            if not slots:
                logger.warning("No colored slots at start of troop/spell bars")
                break
            if not self._tap_colored_slots(slots):
                break
            donated_any = True
            time.sleep(0.4)
        return donated_any

    def _tap_colored_slots(self, slots: list[InventorySlot]) -> bool:
        if not slots:
            return False
        for slot in slots:
            logger.info("Tapping colored slot {} x{} at {}", slot.unit_id, slot.quantity, slot.center)
            for _ in range(slot.quantity):
                self.input.tap(*slot.center)
        return True

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
            slots = self.inventory_parser.parse_bar_slots(frame, bar_roi_key)
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
