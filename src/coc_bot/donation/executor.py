from __future__ import annotations

import time

from loguru import logger

from coc_bot.adb.capture import ScreenCapture
from coc_bot.adb.input import InputController
from coc_bot.config import BotConfig
from coc_bot.donation.capacity_parser import RequestCapacity
from coc_bot.donation.fill_planner import FillPlanner
from coc_bot.donation.icon_matcher import IconMatcher
from coc_bot.donation.inventory import InventoryParser, InventorySlot
from coc_bot.donation.request_parser import RequestKind
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
        self.icon_matcher = IconMatcher(config, matcher=self.matcher)
        self.inventory_parser = InventoryParser(config, matcher=self.matcher, icon_matcher=self.icon_matcher)
        self.classifier = ScreenClassifier(config, self.matcher)
        self.fill_planner = FillPlanner()

    def donate_for_request(
        self,
        *,
        is_specific: bool = True,
        kind: RequestKind | None = None,
        capacity: RequestCapacity | None = None,
        max_rounds: int = 20,
    ) -> bool:
        """Donate for the current donation panel using colored slot detection / smart fill."""
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
            logger.info("Specific request — donating colored slots until first grey per row")
            donated_any = self._donate_specific_by_colored_slots(max_rounds=max_rounds)
            self._close_panel()
            return donated_any

        if not self.config.donate_open_requests:
            logger.info("Open/generic request — skipping donation (specific requests only)")
            self._close_panel()
            return False

        if capacity is None:
            logger.warning(
                "Open/hybrid request missing capacity OCR — skipping to avoid over-donation"
            )
            self._close_panel()
            return False

        if resolved_kind == RequestKind.HYBRID:
            logger.info("Hybrid request — specific colored slots first, then budget-aware fill")
            donated_any = self._donate_hybrid(capacity=capacity, max_rounds=max_rounds)
            self._close_panel()
            return donated_any

        logger.info("Open request — budget-aware fill (troop bar through siege, then spells)")
        donated_any = self._donate_open_budgeted(capacity=capacity)
        self._close_panel()
        return donated_any

    def _donate_specific_by_colored_slots(self, max_rounds: int = 20) -> bool:
        """Donate every colored slot up to the first grey per row."""
        donated_any = False
        for _round in range(max_rounds):
            frame = self.capture.screenshot()
            if not self.classifier.is_donation_panel(frame):
                break
            slots = self.inventory_parser.parse_slots(frame, stop_at_grey=True, identify=False)
            if not slots:
                logger.warning("No colored slots at start of troop/spell bars")
                break
            if not self._tap_colored_slots(slots):
                break
            donated_any = True
            time.sleep(0.4)
        return donated_any

    def _donate_hybrid(
        self,
        *,
        capacity: RequestCapacity | None,
        max_rounds: int = 20,
    ) -> bool:
        donor = self.config.donor_limits()
        troop_b, spell_b, siege_b = self.fill_planner.initial_budgets(capacity, donor)

        # Specific portion first (stop at grey) — identify icons so we can debit budgets.
        donated_any = False
        for _round in range(max_rounds):
            frame = self.capture.screenshot()
            if not self.classifier.is_donation_panel(frame):
                break
            slots = self.inventory_parser.parse_slots(frame, stop_at_grey=True, identify=True)
            if not slots:
                break
            if not self._tap_colored_slots(slots):
                break
            donated_any = True
            troop_b, spell_b, siege_b = self.fill_planner.deduct_specific_slots(
                slots, troop_b, spell_b, siege_b
            )
            time.sleep(0.4)
            if troop_b <= 0 and spell_b <= 0 and siege_b <= 0:
                return donated_any

        if troop_b > 0 or spell_b > 0 or siege_b > 0:
            if self._donate_open_budgeted(
                capacity=capacity,
                troop_budget=troop_b,
                spell_budget=spell_b,
                siege_budget=siege_b,
            ):
                donated_any = True
        return donated_any

    def _tap_colored_slots(self, slots: list[InventorySlot]) -> bool:
        if not slots:
            return False
        for slot in slots:
            logger.info("Tapping colored slot {} x{} at {}", slot.unit_id, slot.quantity, slot.center)
            for _ in range(slot.quantity):
                self.input.tap(*slot.center)
        return True

    def _donate_open_budgeted(
        self,
        *,
        capacity: RequestCapacity | None,
        troop_budget: int | None = None,
        spell_budget: int | None = None,
        siege_budget: int | None = None,
    ) -> bool:
        """Budget-aware open fill: scroll troop bar (incl. siege), then spell bar."""
        donor = self.config.donor_limits()
        if troop_budget is None or spell_budget is None or siege_budget is None:
            troop_budget, spell_budget, siege_budget = self.fill_planner.initial_budgets(
                capacity, donor
            )
        logger.info(
            "Open fill budgets: troop={} spell={} siege={} (clan L{})",
            troop_budget,
            spell_budget,
            siege_budget,
            self.config.clan_level,
        )

        made = False
        # Troop + siege share donation_troop_bar.
        if "donation_troop_bar" in self.config.rois and (troop_budget > 0 or siege_budget > 0):
            t_made, troop_budget, _spell, siege_budget = self._donate_budgeted_bar(
                "donation_troop_bar",
                troop_budget=troop_budget,
                spell_budget=0,
                siege_budget=siege_budget,
                allow_spells=False,
            )
            made = made or t_made

        if "donation_spell_bar" in self.config.rois and spell_budget > 0:
            s_made, _tb, spell_budget, _sg = self._donate_budgeted_bar(
                "donation_spell_bar",
                troop_budget=0,
                spell_budget=spell_budget,
                siege_budget=0,
                allow_spells=True,
            )
            made = made or s_made

        logger.info(
            "Open fill done (made={}) remaining troop={} spell={} siege={}",
            made,
            troop_budget,
            spell_budget,
            siege_budget,
        )
        return made

    def _donate_budgeted_bar(
        self,
        bar_roi_key: str,
        *,
        troop_budget: int,
        spell_budget: int,
        siege_budget: int,
        allow_spells: bool,
    ) -> tuple[bool, int, int, int]:
        max_scrolls = self.config.bar_max_scroll_attempts
        max_tap_rounds = max_scrolls * 4 + 8
        tapped: set[tuple[int, int]] = set()
        made = False
        donor = self.config.donor_limits()
        scrolls = 0
        idle_passes = 0

        for _round in range(max_tap_rounds):
            if troop_budget <= 0 and siege_budget <= 0 and (not allow_spells or spell_budget <= 0):
                break

            frame = self.capture.screenshot()
            slots = self.inventory_parser.parse_bar_slots(frame, bar_roi_key, identify=True)
            fresh = [slot for slot in slots if slot.center not in tapped]

            plan = self.fill_planner.plan(
                fresh,
                capacity=None,
                donor_limits=donor,
                troop_budget=troop_budget,
                spell_budget=spell_budget if allow_spells else 0,
                siege_budget=siege_budget,
            )

            if not plan.empty:
                idle_passes = 0
                for tap in plan.taps:
                    logger.info(
                        "Budget tap {} ({}) cost={} at {}",
                        tap.unit_id,
                        tap.category,
                        tap.cost,
                        tap.center,
                    )
                    self.input.tap(*tap.center)
                    tapped.add(tap.center)
                    made = True
                    if tap.category == "siege":
                        siege_budget = max(0, siege_budget - tap.cost)
                    elif tap.category == "spell":
                        spell_budget = max(0, spell_budget - tap.cost)
                    else:
                        troop_budget = max(0, troop_budget - tap.cost)
                    time.sleep(0.25)
                time.sleep(0.15)
                continue

            # Nothing fits in this view — scroll for more (siege at far right of troop bar).
            if scrolls >= max_scrolls:
                break
            idle_passes += 1
            if idle_passes > 2 and not fresh:
                break
            x1, y1, x2, y2 = self.inventory_parser.bar_swipe_line(frame, bar_roi_key)
            logger.debug(
                "Scrolling {} for more units ({}/{})",
                bar_roi_key,
                scrolls + 1,
                max_scrolls,
            )
            self.input.swipe(x1, y1, x2, y2, duration_ms=280)
            scrolls += 1
            time.sleep(0.35)

        return made, troop_budget, spell_budget, siege_budget

    def _close_panel(self) -> None:
        from coc_bot.donation.navigator import Navigator

        Navigator(self.config, self.capture, self.input, self.matcher).close_donation_panel()
