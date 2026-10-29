from __future__ import annotations

from collections.abc import Callable

from loguru import logger

from coc_bot.adb.capture import ScreenCapture
from coc_bot.adb.input import InputController
from coc_bot.config import BotConfig
from coc_bot.donation.capacity_parser import RequestCapacity
from coc_bot.donation.inventory import InventoryParser, InventorySlot
from coc_bot.donation.layout import DonationLayout, DonationLayoutSession
from coc_bot.donation.request_parser import RequestKind
from coc_bot.stop import interrupted_sleep
from coc_bot.vision.matcher import TemplateMatcher
from coc_bot.vision.screens import BotMode, ScreenClassifier, ScreenType


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
        self._nav = None  # lazily built Navigator (shared chat-chrome helpers)

    def _navigator(self):
        if self._nav is None:
            from coc_bot.donation.navigator import Navigator

            self._nav = Navigator(self.config, self.capture, self.input, self.matcher)
        self._nav.stop_check = self.stop_check
        return self._nav

    def _stopping(self) -> bool:
        return bool(self.stop_check and self.stop_check())

    def _prepare_layout(self, frame) -> bool:
        """Choose geometry once per request; do not replace saved calibration."""
        self.inventory_parser.layout_session = None
        layout = DonationLayout.detect(frame)
        if layout is None:
            return True  # Unsupported variant: preserve the calibrated workflow.
        if self._stopping():
            return False
        confirmed = DonationLayout.detect(self.capture.screenshot())
        if self._stopping() or not layout.agrees(confirmed):
            logger.info("Donation panel changed during automatic layout check — waiting for a stable panel")
            return False
        self.inventory_parser.layout_session = DonationLayoutSession(confirmed)
        logger.info("Donation grids located automatically (7 columns, 2 troop rows, 1 spell row)")
        return True

    def _panel_visible(self, frame) -> bool:
        session = self.inventory_parser.layout_session
        if session is not None:
            return session.observe(frame) is not None
        return self.classifier.is_donation_panel(frame)

    def _resource_panel_visible(self, frame) -> bool:
        if self.inventory_parser.layout_session is not None:
            return self._panel_visible(frame)
        return self.classifier.classify(frame, mode=BotMode.DONATE) == ScreenType.DONATION_PANEL

    def _ensure_elixir_resource(self) -> bool:
        """Select elixir precisely and require visible confirmation before any donation."""
        from coc_bot.donation.resource_mode import elixir_is_selected
        if self._stopping():
            return False
        session = self.inventory_parser.layout_session
        point = self.config.tap_points.get("donation_elixir_button")
        if (not self.config.templates.get("donation_elixir_selected")
                or not self.config.rois.get("donation_elixir_selected")):
            logger.warning("Donation skipped: capture the Selected elixir indicator in Setup → Donation panel.")
            return False
        if session is None and (not point or len(point) < 2 or self.config.frame_width <= 0
                                or self.config.frame_height <= 0):
            logger.warning("Donation skipped: this layout needs an Elixir resource button tap in Setup → Donation panel.")
            return False
        frame = self.capture.screenshot()
        if self._stopping() or not self._resource_panel_visible(frame):
            return False
        if elixir_is_selected(self.config, frame):
            return True
        h, w = frame.shape[:2]
        if session is not None:
            x, y = session.layout.elixir_center
        else:
            x = round(point[0] * w / self.config.frame_width)
            y = round(point[1] * h / self.config.frame_height)
        if not (0 <= x < w and 0 <= y < h):
            logger.warning("Elixir tap lies outside the screen; recalibrate it.")
            return False
        self.input.tap(x, y, jitter=0)
        if interrupted_sleep(.28, self.stop_check):
            return False
        confirmed = self.capture.screenshot()
        if self._stopping():
            return False
        if (self._resource_panel_visible(confirmed)
                and elixir_is_selected(self.config, confirmed)):
            return True
        logger.warning("Elixir selection could not be confirmed — donation skipped to avoid spending gems.")
        return False

    def donate_for_request(
        self,
        *,
        is_specific: bool = True,
        kind: RequestKind | None = None,
        capacity: RequestCapacity | None = None,
        max_rounds: int = 20,
    ) -> bool:
        """Donate for the current donation panel using colored slot detection."""
        self._quality_open=False
        if self._stopping():
            return False
        frame = self.capture.screenshot()
        if not self._prepare_layout(frame):
            return False
        if not self._panel_visible(frame):
            logger.warning(
                "Not on donation panel, detected screen: {}",
                self.classifier.classify(frame, mode=BotMode.DONATE).value,
            )
            self._finish_donation()
            return False

        # CoC can leave "gems" selected on Donation Resource — force elixir first.
        if not self._ensure_elixir_resource():
            self._finish_donation()
            return False

        resolved_kind = kind
        if resolved_kind is None:
            resolved_kind = RequestKind.SPECIFIC if is_specific else RequestKind.OPEN
        if resolved_kind==RequestKind.SPECIFIC:
            visible=self.inventory_parser.parse_bar_slots(self.capture.screenshot(),'donation_troop_bar',identify=False)
            if len(visible)>=5:
                logger.info('Broad troop choice confirms open capacity — applying quality policy')
                resolved_kind=RequestKind.OPEN
            elif self.inventory_parser.layout_session is None:
                logger.warning('Donation geometry is unverified; refusing old coordinates')
                self._finish_donation();return False

        if resolved_kind == RequestKind.SPECIFIC:
            logger.info(
                "Specific request — clear visible troop+spell slots, then scroll bars"
            )
            donated_any = self._donate_open_colored_scroll()
            if not self._stopping():
                self._finish_donation()
            return donated_any

        if not self.config.donate_open_requests:
            logger.info("Open/generic request — skipping donation (specific requests only)")
            self._finish_donation()
            return False

        self._quality_open=True
        donated_any=self._donate_quality(capacity)
        if not self._stopping():self._finish_donation()
        self._quality_open=False
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
            if self.inventory_parser.layout_session is None and bar_key not in self.config.rois:
                continue
            if self._clear_colored_current_view(bar_key):
                made = True

        logger.info("Donation scroll pass — reveal off-screen slots per bar")
        for bar_key in self.BAR_KEYS:
            if self._stopping():
                return made
            if self.inventory_parser.layout_session is None and bar_key not in self.config.rois:
                continue
            if self._scroll_and_clear_bar(bar_key):
                made = True
        return made

    def _donate_quality(self, capacity):
        from coc_bot.donation.quality import HOUSING,composition
        made=False
        remaining=capacity.troop_remaining if capacity else None
        for _ in range(6):
            found=set()
            frame=self.capture.screenshot()
            if self._stopping() or not self._panel_visible(frame):return made
            visible={s.unit_id for s in self.inventory_parser.parse_bar_slots(frame,'donation_troop_bar',identify=True)}
            if visible&{'dragon','electro_dragon'}:
                approved=visible&HOUSING.keys()
                self._quality_targets=composition(remaining,approved) if remaining is not None else {next(u for u in HOUSING if u in approved and u!='archer'):1}
                self._quality_spent=0
                made=self._clear_colored_current_view('donation_troop_bar') or made
                if remaining is not None:remaining=max(0,remaining-self._quality_spent)
                if not self._panel_visible(self.capture.screenshot()):return made
            # Survey all pages before selecting: a small visible troop must not
            # consume space needed by a stronger troop further along the bar.
            maximum=self._max_scrolls_for_bar('donation_troop_bar')
            for page in range(maximum+1):
                frame=self.capture.screenshot()
                if self._stopping() or not self._panel_visible(frame):return made
                found.update(s.unit_id for s in self.inventory_parser.parse_bar_slots(frame,'donation_troop_bar',identify=True))
                if page<maximum and not self._scroll_bar('donation_troop_bar',scroll_i=page,max_scrolls=maximum):return made
            allowed=found&HOUSING.keys()
            if not allowed:
                self._quality_targets={};self._quality_spent=0
                made=self._clear_colored_current_view('donation_spell_bar') or made
                made=self._scroll_and_clear_bar('donation_spell_bar') or made
                break
            if remaining is None and allowed=={'archer'}:break
            targets=composition(remaining,allowed) if remaining is not None else {next(u for u in HOUSING if u in allowed and u!='archer'):1}
            if not targets:break
            self._quality_targets=targets
            # Return to the beginning using the same verified panel geometry.
            for _ in range(maximum):
                frame=self.capture.screenshot()
                if self._stopping() or not self._panel_visible(frame):return made
                line=self.inventory_parser.bar_swipe_line(frame,'donation_troop_bar')
                if not line:break
                x1,y,x2,_=line;self.input.swipe(x2,y,x1,y,duration_ms=self.BAR_SWIPE_MS)
                if interrupted_sleep(self.AFTER_BAR_SCROLL_S,self.stop_check):return made
            self._quality_spent=0
            before=sum(targets.values())
            made=self._donate_open_colored_scroll() or made
            if remaining is not None:remaining=max(0,remaining-self._quality_spent)
            if sum(targets.values())==before:break
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
            if self._stopping() or not self._panel_visible(frame):
                return made

            slots = self.inventory_parser.parse_bar_slots(
                frame, bar_roi_key, identify=getattr(self,'_quality_open',False)
            )
            if getattr(self,'_quality_open',False):
                slots=[s for s in slots if not s.unit_id.startswith(('troop_slot_','spell_slot_')) and
                       (s.category in ('spell','siege') or getattr(self,'_quality_targets',{}).get(s.unit_id,0)>0)]
            if not slots:
                break

            logger.info(
                "{}: found {} colored slot(s) — tapping",
                bar_roi_key,
                len(slots),
            )
            made = self._tap_colored_slots(slots) or made
            session = self.inventory_parser.layout_session
            if session is not None and not session.valid:
                return made
            if interrupted_sleep(self.AFTER_TAP_BATCH_S, self.stop_check):
                return made
        return made

    def _scroll_bar(self, bar_roi_key: str, *, scroll_i: int, max_scrolls: int) -> bool:
        """Swipe the bar right. Returns False if stop requested or panel is gone."""
        frame = self.capture.screenshot()
        if self._stopping() or not self._panel_visible(frame):
            return False
        line = self.inventory_parser.bar_swipe_line(frame, bar_roi_key)
        if line is None or self._stopping():
            return False
        x1, y1, x2, y2 = line
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
        if getattr(self,'_quality_open',False):return self._tap_automatic_slots(slots)
        if self.inventory_parser.layout_session is not None:
            return self._tap_automatic_slots(slots)
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

    def _tap_automatic_slots(self, slots: list[InventorySlot]) -> bool:
        """Never reuse a batch of coordinates after the donation panel closes.

        Return whether input was sent, not proof that capacity was filled.
        Eligibility, current geometry and resource mode are rechecked per tap.
        """
        from coc_bot.donation.resource_mode import elixir_is_selected
        made = False
        session = self.inventory_parser.layout_session
        for slot in slots:
            for _ in range(slot.quantity):
                if self._stopping():
                    return made
                frame = self.capture.screenshot()
                if self._stopping() or not self._panel_visible(frame):
                    return made
                if not elixir_is_selected(self.config, frame):
                    if session is not None:session.valid = False
                    logger.warning("Donation stopped: selected elixir indicator is no longer confirmed")
                    return made
                key = 'donation_spell_bar' if slot.category == 'spell' else 'donation_troop_bar'
                current = self.inventory_parser.parse_bar_slots(frame, key, identify=getattr(self,'_quality_open',False))
                target = next((s for s in current if s.unit_id == slot.unit_id), None)
                if target is None:
                    continue  # The request may have been filled by another donor.
                if getattr(self,'_quality_open',False) and target.category=='troop':
                    from coc_bot.donation.quality import HOUSING
                    if self._quality_targets.get(target.unit_id,0)<=0 or target.unit_id not in HOUSING:continue
                if self._stopping():
                    return made
                self.input.tap(*target.center, jitter=0)
                if getattr(self,'_quality_open',False) and target.category=='troop':
                    self._quality_targets[target.unit_id]-=1
                    self._quality_spent+=HOUSING[target.unit_id]
                made = True
                if interrupted_sleep(self.BETWEEN_SLOTS_S, self.stop_check):
                    return made
        return made

    def _finish_donation(self) -> None:
        """Close the donation panel, then leave Chat Groups if a miss opened it."""
        self._close_panel()
        self._dismiss_global_chat_if_open()

    def _dismiss_global_chat_if_open(self) -> None:
        """
        After a donate fill, recover if we accidentally opened Chat Groups.

        Chat Groups is identified by the title template/OCR. Returning to clan chat
        requires tapping the swords/shield tab (not BACK).
        """
        if self._stopping():
            return
        frame = self.capture.screenshot()
        if not self.classifier.is_global_chat(frame):
            return

        # Shared with Navigator._return_from_global_chat so both paths use the same
        # lookup order and template threshold.
        point = self._navigator().clan_chat_tab_point(frame)
        if point is None:
            logger.warning(
                "Chat Groups open after donate, but clan_chat_tab is not calibrated — "
                "cannot switch back (Setup → Optional UI → Clan chat tab)"
            )
            return
        logger.warning(
            "Chat Groups open after donate — tapping clan chat tab (swords) at ({}, {})",
            point[0],
            point[1],
        )
        self.input.tap(point[0], point[1], jitter=0)
        interrupted_sleep(0.45, self.stop_check)

    def _close_panel(self) -> None:
        self._navigator().close_donation_panel()
