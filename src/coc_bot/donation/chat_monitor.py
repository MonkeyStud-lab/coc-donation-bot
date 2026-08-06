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
from coc_bot.vision.ocr import is_donate_button_label


@dataclass
class DonateRequest:
    button_match: MatchResult
    signature: str
    is_specific: bool = False  # True = pure specific (Phase 1 colored-slot path)
    kind: RequestKind = RequestKind.OPEN
    capacity: RequestCapacity | None = None


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
        ttl = self.config.handled_request_ttl_seconds
        expired = [k for k, ts in self._handled.items() if now - ts > ttl]
        for k in expired:
            del self._handled[k]

    def find_donate_request(self, frame: np.ndarray | None = None) -> DonateRequest | None:
        self._prune_handled()
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

        for match in sorted(matches, key=lambda m: m.y, reverse=True):
            abs_y = match.y + offset_y
            abs_x = match.x + offset_x
            sig = hashlib.md5(f"{abs_x}:{abs_y}".encode()).hexdigest()[:12]
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
            if self.config.parse_request_capacity:
                capacity = self.capacity_parser.parse(frame, adjusted)
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
            return DonateRequest(
                button_match=adjusted,
                signature=sig,
                is_specific=is_specific,
                kind=kind,
                capacity=capacity,
            )

        return None

    def _match_is_donate_button(self, frame: np.ndarray, match: MatchResult) -> bool:
        """
        Confirm a green-button template hit says Donate (not Trade).

        Uses tesseract on the button crop. If OCR is unavailable, keep the
        template match (legacy behavior).
        """
        h, w = frame.shape[:2]
        x0 = max(0, match.x)
        y0 = max(0, match.y)
        x1 = min(w, match.x + match.width)
        y1 = min(h, match.y + match.height)
        if x1 <= x0 or y1 <= y0:
            return False
        crop = frame[y0:y1, x0:x1]
        verdict = is_donate_button_label(crop)
        if verdict is None:
            logger.debug(
                "Donate button OCR unavailable — accepting template match at ({}, {})",
                match.center[0],
                match.center[1],
            )
            return True
        if not verdict:
            logger.info(
                "Skipping green button at ({}, {}) — OCR is not Donate (likely Trade)",
                match.center[0],
                match.center[1],
            )
            return False
        return True

    def mark_handled(self, request: DonateRequest) -> None:
        self._handled[request.signature] = time.time()

    def open_donation(self, request: DonateRequest) -> None:
        cx, cy = request.button_match.center
        logger.info("Opening donation panel at ({}, {}), conf={:.2f}", cx, cy, request.button_match.confidence)
        self.input.tap(cx, cy)
        self.mark_handled(request)
