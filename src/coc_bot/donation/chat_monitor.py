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
from coc_bot.vision.matcher import MatchResult, TemplateMatcher


@dataclass
class DonateRequest:
    button_match: MatchResult
    signature: str


class ChatMonitor:
    """Scan clan chat for donation request buttons."""

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
        self.matcher = matcher or TemplateMatcher(threshold=config.donate_button_threshold)
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
        frame = frame or self.capture.screenshot()
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
            sig = hashlib.md5(f"{match.x + offset_x}:{abs_y}".encode()).hexdigest()[:12]
            if sig in self._handled:
                continue
            adjusted = MatchResult(
                x=match.x + offset_x,
                y=abs_y,
                confidence=match.confidence,
                width=match.width,
                height=match.height,
            )
            return DonateRequest(button_match=adjusted, signature=sig)

        return None

    def open_donation(self, request: DonateRequest) -> None:
        cx, cy = request.button_match.center
        logger.info("Opening donation panel at ({}, {}), conf={:.2f}", cx, cy, request.button_match.confidence)
        self.input.tap(cx, cy)
        self._handled[request.signature] = time.time()
