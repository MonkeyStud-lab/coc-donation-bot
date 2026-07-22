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
        self.client.run_shell(f"am force-stop {pkg}", check=False)

    def is_running(self) -> bool:
        pkg = self.config.coc_package
        result = self.client.run_shell(f"pidof {pkg}", check=False)
        return bool((result.stdout or "").strip())

    def launch(self) -> None:
        """
        Start Clash of Clans inside the existing Waydroid Android UI via ADB.

        Does not use `waydroid app launch` (separate dock window) or spam
        multiple start methods — that left CoC laggy compared to opening it
        manually from the Waydroid home screen.
        """
        pkg = self.config.coc_package
        logger.info("Launching {} via ADB (single start)", pkg)

        resolve = self.client.run_shell(
            f"cmd package resolve-activity --brief {pkg}",
            check=False,
        )
        activity = ""
        for line in (resolve.stdout or "").splitlines():
            line = line.strip()
            if line.startswith(pkg) and "/" in line:
                activity = line

        if activity:
            self.client.run_shell(
                f"am start -a android.intent.action.MAIN "
                f"-c android.intent.category.LAUNCHER -n {activity}",
                check=False,
            )
            logger.info("Issued am start -n {}", activity)
        else:
            # One fallback only (same idea as tapping the icon once).
            self.client.run_shell(
                f"monkey -p {pkg} -c android.intent.category.LAUNCHER 1",
                check=False,
            )
            logger.info("Issued monkey launch for {}", pkg)

    def wait_until_ready(
        self,
        loading_template: np.ndarray | None = None,
        timeout_seconds: int | None = None,
    ) -> bool:
        """
        Wait for CoC to come up without hammering ADB screencap.

        Continuous screenshots during load make Waydroid/CoC feel laggy; prefer
        pidof + a quiet settle period, then at most a couple of frame checks.
        """
        del loading_template  # optional template checks were too screenshot-heavy
        timeout = timeout_seconds or self.config.game_load_timeout_seconds
        deadline = time.time() + timeout
        logger.info("Waiting for game process (timeout {}s, light checks)...", timeout)

        while time.time() < deadline:
            if self.is_running():
                logger.info("Clash process is running — settling without screencap spam")
                # Let the game finish loading undisturbed (similar to opening manually).
                settle = min(18.0, max(8.0, timeout * 0.2))
                time.sleep(settle)
                # One optional sanity check — not a tight poll loop.
                try:
                    frame = self.capture.screenshot()
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    if float(np.std(gray)) > 20.0:
                        logger.info("Game looks loaded after settle")
                        return True
                    logger.info("Process up; frame still quiet — waiting a bit more")
                    time.sleep(5.0)
                    return self.is_running()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Post-launch screenshot skipped: {}", exc)
                    return True
            time.sleep(2.0)

        logger.warning("Clash process never appeared (pidof empty)")
        return False
