from __future__ import annotations

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
from coc_bot.vision.screens import BotMode, ScreenClassifier


class DonationExecutor:
    """Execute donation fulfillment via colored-slot detection."""

    BAR_KEYS = ("donation_troop_bar", "donation_spell_bar")
    # Settles after UI reacts; kept short so fills stay snappy (ADB tap delay is separate).
    AFTER_TAP_BATCH_S = 0.18
    AFTER_BAR_SCROLL_S = 0.20
    BETWEEN_SLOTS_S = 0.05
    BAR_SWIPE_MS = 200

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
                self.classifier.classify(frame, mode=BotMode.DONATE).value,
            )
            self._close_panel()
            return False

        resolved_kind = kind
        if resolved_kind is None:
            resolved_kind = RequestKind.SPECIFIC if is_specific else RequestKind.OPEN

        if resolved_kind == RequestKind.SPECIFIC:
            logger.info(
                "Specific request — clear visible troop+spell slots, then scroll bars"
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
            logger.info(
                "Hybrid request — clear visible troop+spell slots, then scroll bars"
            )
            donated_any = self._donate_open_colored_scroll()
            if not self._stopping():
                self._close_panel()
            return donated_any

        logger.info(
            "Open request — clear visible troop+spell slots, then scroll for siege/etc."
        )
        donated_any = self._donate_open_colored_scroll()
        if not self._stopping():
            self._close_panel()
        return donated_any

    def _donate_open_colored_scroll(self) -> bool:
        """
        Faster fill order:

        1. First pass — exhaust colored slots currently visible on *all* bars
           (troops/siege row and spells) with no scrolling.
        2. Second pass — scroll each bar and clear newly revealed slots (siege, etc.).
        """
        made = False

        logger.info("Donation first pass — visible colored slots on all bars")
        for bar_key in self.BAR_KEYS:
            if self._stopping():
                return made
            if bar_key not in self.config.rois:
                continue
            if self._clear_colored_current_view(bar_key):
                made = True

        logger.info("Donation scroll pass — reveal off-screen slots per bar")
        for bar_key in self.BAR_KEYS:
            if self._stopping():
                return made
            if bar_key not in self.config.rois:
                continue
            if self._scroll_and_clear_bar(bar_key):
                made = True
        return made

    def _max_scrolls_for_bar(self, bar_roi_key: str) -> int:
        if bar_roi_key == "donation_spell_bar":
            return self.config.spell_bar_max_scroll_attempts
        return self.config.bar_max_scroll_attempts

    def _clear_colored_current_view(self, bar_roi_key: str) -> bool:
        """Tap every colored slot on the current bar view (re-scan until none left)."""
        made = False
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
                "{}: found {} colored slot(s) — tapping",
                bar_roi_key,
                len(slots),
            )
            self._tap_colored_slots(slots)
            made = True
            if interrupted_sleep(self.AFTER_TAP_BATCH_S, self.stop_check):
                return made
        return made

    def _scroll_bar(self, bar_roi_key: str, *, scroll_i: int, max_scrolls: int) -> bool:
        """Swipe the bar right. Returns False if stop requested or panel is gone."""
        frame = self.capture.screenshot()
        if not self.classifier.is_donation_panel(frame):
            return False
        x1, y1, x2, y2 = self.inventory_parser.bar_swipe_line(frame, bar_roi_key)
        logger.info(
            "Scrolling {} toward right ({}/{})",
            bar_roi_key,
            scroll_i + 1,
            max_scrolls,
        )
        self.input.swipe(x1, y1, x2, y2, duration_ms=self.BAR_SWIPE_MS)
        if interrupted_sleep(self.AFTER_BAR_SCROLL_S, self.stop_check):
            return False
        return True

    def _scroll_and_clear_bar(self, bar_roi_key: str) -> bool:
        """
        Scroll a bar and clear colored slots after each swipe.

        Stops after enough consecutive empty views (spells: 1, troops: 3 so siege
        past a gap still appears). The initial on-screen view was already cleared
        in the first pass.
        """
        max_scrolls = self._max_scrolls_for_bar(bar_roi_key)
        if max_scrolls <= 0:
            return False
        empty_limit = 1 if bar_roi_key == "donation_spell_bar" else 3
        made = False
        empty_streak = 0

        for scroll_i in range(max_scrolls):
            if self._stopping():
                return made
            if not self._scroll_bar(bar_roi_key, scroll_i=scroll_i, max_scrolls=max_scrolls):
                return made

            if self._clear_colored_current_view(bar_roi_key):
                made = True
                empty_streak = 0
            else:
                empty_streak += 1
                if empty_streak >= empty_limit:
                    logger.info(
                        "{}: {} empty view(s) after scroll — done this bar",
                        bar_roi_key,
                        empty_streak,
                    )
                    break

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
            if interrupted_sleep(self.BETWEEN_SLOTS_S, self.stop_check):
                return True
        return True

    def _close_panel(self) -> None:
        from coc_bot.donation.navigator import Navigator

        Navigator(self.config, self.capture, self.input, self.matcher).close_donation_panel()
