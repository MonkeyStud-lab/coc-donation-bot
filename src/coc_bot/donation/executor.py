from __future__ import annotations

import time
from collections.abc import Callable

from loguru import logger

from coc_bot.adb.capture import ScreenCapture
from coc_bot.adb.input import InputController
from coc_bot.config import BotConfig
from coc_bot.donation.capacity_parser import RequestCapacity
from coc_bot.donation.inventory import InventoryParser, InventorySlot
from coc_bot.donation.request_parser import RequestKind
from coc_bot.stop import interrupted_sleep
from coc_bot.vision.matcher import TemplateMatcher
from coc_bot.vision.screens import ScreenClassifier


class DonationExecutor:
    """Execute donation fulfillment via colored-slot detection."""

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
        self.inventory_parser = InventoryParser(config, matcher=self.matcher)
        self.classifier = ScreenClassifier(config, self.matcher)
        self.stop_check: Callable[[], bool] | None = None

    def _stopping(self) -> bool:
        return bool(self.stop_check and self.stop_check())

    def donate_for_request(
        self,
        *,
        is_specific: bool = True,
        kind: RequestKind | None = None,
        capacity: RequestCapacity | None = None,
        max_rounds: int = 20,
    ) -> bool:
        """Donate for the current donation panel using colored slot detection."""
        del capacity  # reserved for a later smart-fill mode; unused in simple path
        if self._stopping():
            return False
        frame = self.capture.screenshot()
        if not self.classifier.is_donation_panel(frame):
            logger.warning(
                "Not on donation panel, detected screen: {}",
                self.classifier.classify(frame).value,
            )
            self._close_panel()
            return False

        resolved_kind = kind
        if resolved_kind is None:
            resolved_kind = RequestKind.SPECIFIC if is_specific else RequestKind.OPEN

        if resolved_kind == RequestKind.SPECIFIC:
            logger.info(
                "Specific request — tapping all colored slots (scroll troop/spell bars)"
            )
            donated_any = self._donate_open_colored_scroll()
            if not self._stopping():
                self._close_panel()
            return donated_any

        if not self.config.donate_open_requests:
            logger.info("Open/generic request — skipping donation (specific requests only)")
            self._close_panel()
            return False

        if resolved_kind == RequestKind.HYBRID:
            logger.info("Hybrid request — tapping all colored slots (scroll bars)")
            donated_any = self._donate_open_colored_scroll()
            if not self._stopping():
                self._close_panel()
            return donated_any

        logger.info("Open request — tapping colored slots (scroll troop bar incl. siege, then spells)")
        donated_any = self._donate_open_colored_scroll()
        if not self._stopping():
            self._close_panel()
        return donated_any

    def _donate_open_colored_scroll(self) -> bool:
        """Tap every colored slot, scrolling each bar a limited number of times."""
        made = False
        for bar_key in self.BAR_KEYS:
            if bar_key not in self.config.rois:
                continue
            if self._donate_colored_bar(bar_key):
                made = True
        return made

    def _max_scrolls_for_bar(self, bar_roi_key: str) -> int:
        if bar_roi_key == "donation_spell_bar":
            return self.config.spell_bar_max_scroll_attempts
        return self.config.bar_max_scroll_attempts

    def _donate_colored_bar(self, bar_roi_key: str) -> bool:
        """
        On each view: tap every colored slot (re-scan until none left), then scroll.

        Never scrolls while colored icons are still visible. Stops after enough
        consecutive empty views (spells: 1, troops: 2 so siege can still appear).
        """
        max_scrolls = self._max_scrolls_for_bar(bar_roi_key)
        empty_limit = 1 if bar_roi_key == "donation_spell_bar" else 2
        made = False
        empty_streak = 0

        for scroll_i in range(max_scrolls + 1):
            if self._stopping():
                return made
            tapped_this_view = False
            # Exhaust colored slots on the current view before any swipe.
            for _ in range(15):
                if self._stopping():
                    return made
                frame = self.capture.screenshot()
                if not self.classifier.is_donation_panel(frame):
                    return made

                slots = self.inventory_parser.parse_bar_slots(
                    frame, bar_roi_key, identify=False
                )
                if not slots:
                    break

                logger.info(
                    "{}: found {} colored slot(s) — tapping before scroll",
                    bar_roi_key,
                    len(slots),
                )
                self._tap_colored_slots(slots)
                made = True
                tapped_this_view = True
                if interrupted_sleep(0.4, self.stop_check):
                    return made

            if tapped_this_view:
                empty_streak = 0
            else:
                empty_streak += 1

            if scroll_i >= max_scrolls:
                break
            if empty_streak >= empty_limit and scroll_i > 0:
                logger.info(
                    "{}: {} empty view(s) — done scrolling this bar",
                    bar_roi_key,
                    empty_streak,
                )
                break

            frame = self.capture.screenshot()
            if not self.classifier.is_donation_panel(frame):
                break
            x1, y1, x2, y2 = self.inventory_parser.bar_swipe_line(frame, bar_roi_key)
            logger.info(
                "Scrolling {} toward right ({}/{}) after clearing colored slots",
                bar_roi_key,
                scroll_i + 1,
                max_scrolls,
            )
            self.input.swipe(x1, y1, x2, y2, duration_ms=280)
            if interrupted_sleep(0.45, self.stop_check):
                return made

        return made

    def _tap_colored_slots(self, slots: list[InventorySlot]) -> bool:
        if not slots:
            return False
        for slot in slots:
            if self._stopping():
                return True
            logger.info("Tapping colored slot {} x{} at {}", slot.unit_id, slot.quantity, slot.center)
            for _ in range(slot.quantity):
                if self._stopping():
                    return True
                self.input.tap(*slot.center)
            if interrupted_sleep(0.15, self.stop_check):
                return True
        return True

    def _close_panel(self) -> None:
        from coc_bot.donation.navigator import Navigator

        Navigator(self.config, self.capture, self.input, self.matcher).close_donation_panel()
