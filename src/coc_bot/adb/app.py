from __future__ import annotations

import time

import cv2
import numpy as np
from loguru import logger

from coc_bot.adb.capture import ScreenCapture
from coc_bot.adb.client import AdbClient
from coc_bot.config import BotConfig


class AppController:
    """Force-stop and relaunch Clash of Clans."""

    def __init__(self, client: AdbClient, config: BotConfig, capture: ScreenCapture) -> None:
        self.client = client
        self.config = config
        self.capture = capture

    def force_stop(self) -> None:
        pkg = self.config.coc_package
        logger.info("Force-stopping {}", pkg)
        self.client.run_shell(f"am force-stop {pkg}")

    def launch(self) -> None:
        pkg = self.config.coc_package
        logger.info("Launching {}", pkg)
        self.client.run_shell(
            f"monkey -p {pkg} -c android.intent.category.LAUNCHER 1",
            check=False,
        )

    def wait_until_ready(
        self,
        loading_template: np.ndarray | None = None,
        timeout_seconds: int | None = None,
    ) -> bool:
        timeout = timeout_seconds or self.config.game_load_timeout_seconds
        deadline = time.time() + timeout
        logger.info("Waiting for game to load (timeout {}s)...", timeout)

        while time.time() < deadline:
            frame = self.capture.screenshot()
            if loading_template is not None:
                from coc_bot.vision.matcher import TemplateMatcher

                matcher = TemplateMatcher(threshold=0.75)
                match = matcher.find(frame, loading_template)
                if match is None:
                    logger.info("Loading screen cleared")
                    return True
            else:
                # Without loading template, wait a fixed period then assume ready
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                if float(np.std(gray)) > 25.0:
                    logger.info("Frame variance suggests game is loaded")
                    return True
            time.sleep(2.0)

        logger.warning("Game load timeout reached")
        return False
