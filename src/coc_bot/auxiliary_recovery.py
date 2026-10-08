"""Bounded, interruptible closing of recognized Shop / Clash Pass pages."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
from loguru import logger

from coc_bot.adb.input import InputController
from coc_bot.vision.screens import ScreenClassifier


class AuxiliaryRecovery:
    """One recovery operation; callers must capture again after each close tap."""

    def __init__(
        self,
        classifier: ScreenClassifier,
        input_ctrl: InputController,
        stopping: Callable[[], bool],
    ) -> None:
        self.classifier = classifier
        self.input = input_ctrl
        self.stopping = stopping
        self.attempts = 0

    def close(self, frame: np.ndarray) -> bool:
        page = self.classifier.auxiliary_page(frame)
        if page is None or self.stopping():
            return False
        if page.close is None:
            logger.warning(
                "Recognized {} but its close button is obscured or unverified — "
                "dismiss the covering dialog manually", page.screen,
            )
            return False
        if self.attempts >= 3:
            logger.warning("{} did not close after 3 attempts — stopping recovery", page.screen)
            return False
        # Stop takes priority even if requested during image matching.
        if self.stopping():
            return False
        x, y = page.close
        logger.info("Closing {} via verified X at ({}, {})", page.screen, x, y)
        self.input.tap(x, y, jitter=0)
        self.attempts += 1
        return True
