"""Bounded, interruptible closing of recognized Shop / Clash Pass pages."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
from loguru import logger

from coc_bot.adb.input import InputController
from coc_bot.vision.screens import ScreenClassifier
from coc_bot.vision import recorder


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
        self._previous = None
        self._previous_frame = None
        self._uncertain = 0

    def close(self, frame: np.ndarray) -> bool:
        page = self.classifier.auxiliary_page(frame)
        if page is None or self.stopping():
            return False
        # Recognition may finish just as Stop is requested.
        if self.stopping():
            return False
        if page.close is None:
            self._previous = None
            self._previous_frame = None
            self._uncertain += 1
            if self._uncertain < 3:
                logger.info('Uncertain {} close control — waiting for another screenshot', page.screen)
                return True  # caller sleeps and captures again; no input sent
            recorder.note_event("close_obscured", screen=page.screen)
            logger.warning(
                "Recognized {} but its close button is obscured or unverified — "
                "dismiss the covering dialog manually", page.screen,
            )
            return False
        if page.screen in ('shop', 'settings'):
            # A transient or conflicting frame must not cause input. Require
            # the same page/target on a separately captured second observation.
            key = (page.screen, page.close, frame.shape)
            if self._previous != key or self._previous_frame is frame:
                self._previous = key
                self._previous_frame = frame
                self._uncertain += 1
                if self._uncertain >= 3:
                    logger.warning('Page recognition did not settle — recovery paused without tapping')
                    return False
                return True
            self._previous = None
            self._previous_frame = None
        self._uncertain = 0
        if self.attempts >= 3:
            recorder.note_event("close_failed", screen=page.screen, attempts=self.attempts)
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
