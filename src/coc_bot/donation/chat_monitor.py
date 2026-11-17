from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass

import cv2
import numpy as np
from loguru import logger

from coc_bot.adb.capture import ScreenCapture
from coc_bot.adb.input import InputController
from coc_bot.config import BotConfig
from coc_bot.donation.capacity_parser import RequestCapacity, RequestCapacityParser
from coc_bot.donation.request_parser import RequestKind, RequestParser
from coc_bot.vision.matcher import MatchResult, TemplateMatcher
from coc_bot.vision.ocr import read_short_label


@dataclass
class DonateRequest:
    button_match: MatchResult
    signature: str
    is_specific: bool = False  # True = pure specific (Phase 1 colored-slot path)
    kind: RequestKind = RequestKind.OPEN
    capacity: RequestCapacity | None = None
    first_seen: float | None = None
    card_header: str | None = None
    full_capacity_read: bool = False


class ChatMonitor:
    """Scan clan chat for donation request buttons."""

    def __init__(
        self,
        config: BotConfig,
        capture: ScreenCapture,
        input_ctrl: InputController,
        matcher: TemplateMatcher | None = None,
        *,
        debug: bool = False,
    ) -> None:
        self.config = config
        self.capture = capture
        self.input = input_ctrl
        self.matcher = matcher or TemplateMatcher(threshold=config.donate_button_threshold)
        self.request_parser = RequestParser(config, debug=debug)
        self.capacity_parser = RequestCapacityParser(config)
        self._handled: dict[str, float] = {}
        self._seen: dict[str, tuple[float, float]] = {}
        self._donate_template: np.ndarray | None = None

    def _load_donate_button(self) -> np.ndarray | None:
        if self._donate_template is not None:
            return self._donate_template
        rel = self.config.templates.get("donate_button")
        if not rel:
            return None
        path = self.config.templates_dir / rel
        if not path.exists():
            return None
        img = cv2.imread(str(path), cv2.IMREAD_COLOR)
        self._donate_template = img
        return img

    def _prune_handled(self) -> None:
        now = time.time()
        expired = [k for k, until in self._handled.items() if now >= until]
        for k in expired:
            del self._handled[k]
        self._seen = {key: times for key, times in self._seen.items() if now-times[1] < 3600}

    @staticmethod
    def _card_header(frame, button):
        from coc_bot.donation.capacity_parser import find_message_bubble
        box = find_message_bubble(frame, button)
        if box is None:
            return None
        x, y, right, bottom = box
        header = frame[y:y+(bottom-y)//3, x:x+(right-x)*2//3]
        if not header.size or header.std() < 10:
            return None
        return hashlib.blake2s(header.tobytes(), digest_size=12).hexdigest()

    def find_donate_request(self, frame: np.ndarray | None = None) -> DonateRequest | None:
        self._prune_handled()
        observed_at = time.time()
        if frame is None:
            frame = self.capture.screenshot()
        template = self._load_donate_button()
        if template is None:
            logger.warning("Donate button template not configured")
            return None

        h, w = frame.shape[:2]
        search = frame
        if "chat_requests" in self.config.rois:
            from coc_bot.vision.rois import crop_roi

            search = crop_roi(frame, self.config.rois["chat_requests"])

        matches = self.matcher.find_all(
            search,
            template,
            threshold=self.config.donate_button_threshold,
            max_matches=5,
        )
        if not matches:
            return None

        offset_y = 0
        offset_x = 0
        if "chat_requests" in self.config.rois:
            from coc_bot.vision.rois import denormalize_roi, ROI

            ox, oy, _, _ = denormalize_roi(ROI(*self.config.rois["chat_requests"]), w, h)
            offset_x, offset_y = ox, oy

        # Chat is chronological from top to bottom. Serve the oldest visible
        # request before a newer card can take the donor away from it.
        for match in sorted(matches, key=lambda m: m.y):
            abs_y = match.y + offset_y
            abs_x = match.x + offset_x
            # Different request cards can reuse the same position. Use card
            # artwork and capacity context above the button, away from its age.
            card = frame[max(0, abs_y-match.height):abs_y,
                         max(0, abs_x-3*match.width):abs_x+match.width]
            sig = hashlib.blake2s(card.tobytes(), digest_size=8).hexdigest()
            if sig in self._handled:
                continue
            adjusted = MatchResult(
                x=abs_x,
                y=abs_y,
                confidence=match.confidence,
                width=match.width,
                height=match.height,
            )
            # Trade Offer uses the same green pill — OCR the label so we only tap Donate.
            if not self._match_is_donate_button(frame, adjusted):
                continue
            capacity = None
            full_capacity_read = False
            if self.config.parse_request_capacity:
                capacity = self.capacity_parser.parse(frame, adjusted)
                full_capacity_read = capacity is not None
                if capacity is None:
                    capacity = self.capacity_parser.parse(frame, adjusted, fast=True)
            kind = self.request_parser.classify(frame, adjusted, capacity)
            is_specific = kind == RequestKind.SPECIFIC
            if kind == RequestKind.SPECIFIC:
                logger.info("Specific request detected (requested unit icons in chat)")
            elif kind == RequestKind.HYBRID:
                logger.info("Hybrid request detected (some icons + open remainder)")
            else:
                logger.debug("Open/generic request (capacity bars only — no unit icon row)")
            if capacity is not None:
                logger.info(
                    "Request capacity troops={}/{} spells={}/{} siege={}/{}",
                    capacity.troop_remaining,
                    capacity.troop_total,
                    capacity.spell_remaining,
                    capacity.spell_total,
                    capacity.siege_remaining,
                    capacity.siege_total,
                )
            header = self._card_header(frame, adjusted)
            now = time.time()
            key = header or sig
            first = self._seen.get(key, (observed_at, now))[0]
            self._seen[key] = (first, now)
            return DonateRequest(
                first_seen=first, card_header=header, full_capacity_read=full_capacity_read,
                button_match=adjusted,
                signature=sig,
                is_specific=is_specific,
                kind=kind,
                capacity=capacity,
            )

        return None

    def _match_is_donate_button(self, frame: np.ndarray, match: MatchResult) -> bool:
        """
        Confirm a green-button template hit is Donate, not Trade Offer.

        Order: clear Trade OCR → reject; clear Donate OCR → accept; then card
        context (capacity bars = donate, “Trade Offer” header = trade). Never
        reject on inconclusive OCR alone — that was skipping real Donate taps.
        """
        h, w = frame.shape[:2]
        x0 = max(0, match.x)
        y0 = max(0, match.y)
        x1 = min(w, match.x + match.width)
        y1 = min(h, match.y + match.height)
        if x1 <= x0 or y1 <= y0:
            return False
        crop = frame[y0:y1, x0:x1]
        label = read_short_label(crop, stop_check=self.input.client.stop_check)
        has_trade = bool(label and "trade" in label)
        has_donate = bool(label and "donat" in label)
        if has_trade and not has_donate:
            logger.info(
                "Skipping green button at ({}, {}) — OCR read Trade ({!r})",
                match.center[0],
                match.center[1],
                label,
            )
            return False
        if has_donate:
            logger.debug(
                "Green button at ({}, {}) OCR Donate ({!r})",
                match.center[0],
                match.center[1],
                label,
            )
            return True

        # Context: troop/spell capacity fractions only exist on donate requests.
        if self.config.parse_request_capacity:
            capacity = self.capacity_parser.parse(frame, match, fast=True)
            if capacity is not None:
                logger.debug(
                    "Green button at ({}, {}) accepted — request capacity visible",
                    match.center[0],
                    match.center[1],
                )
                return True

        if self._looks_like_trade_offer_card(frame, match):
            logger.info(
                "Skipping green button at ({}, {}) — Trade Offer card nearby",
                match.center[0],
                match.center[1],
            )
            return False

        logger.info(
            "Green button at ({}, {}) OCR inconclusive ({!r}) — accepting template match",
            match.center[0],
            match.center[1],
            label,
        )
        return True

    def _looks_like_trade_offer_card(self, frame: np.ndarray, match: MatchResult) -> bool:
        """True when the message card left of the button looks like a Trade Offer."""
        h, w = frame.shape[:2]
        # Header sits above/left of the green pill on Trade Offer rows.
        x1 = max(0, match.x)
        x0 = max(0, match.x - int(match.width * 3.5))
        y0 = max(0, match.y - int(match.height * 1.8))
        y1 = min(h, match.y + match.height)
        if x1 <= x0 or y1 <= y0:
            return False
        region = frame[y0:y1, x0:x1]
        text = read_short_label(region, stop_check=self.input.client.stop_check)
        if text is None:
            return False
        return "tradeoffer" in text or ("trade" in text and "offer" in text)

    def mark_handled(self, request: DonateRequest) -> None:
        self._handled[request.signature] = time.time() + self.config.handled_request_ttl_seconds
        self._seen.pop(request.card_header or request.signature, None)

    def retry_later(self, request):
        self._handled[request.signature] = time.time() + min(10, self.config.handled_request_ttl_seconds)

    def verified_fill(self, request):
        if not request.full_capacity_read or not request.card_header or not request.capacity or not request.capacity.has_remaining:
            return False
        for _ in range(2):
            frame = self.capture.screenshot()
            if self._card_header(frame, request.button_match) != request.card_header:
                return False
            after = self.capacity_parser.parse(frame, request.button_match)
            if (after is None or after.has_remaining or not after.troop_total
                    or after.troop_total != request.capacity.troop_total
                    or after.spell_total != request.capacity.spell_total
                    or after.siege_total != request.capacity.siege_total):
                return False
        return True

    def open_donation(self, request: DonateRequest) -> None:
        cx, cy = request.button_match.center
        logger.info("Opening donation panel at ({}, {}), conf={:.2f}", cx, cy, request.button_match.confidence)
        self.input.tap(cx, cy)
