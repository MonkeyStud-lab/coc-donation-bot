from __future__ import annotations

import shutil
import subprocess
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
        Start Clash of Clans.

        Tries several methods because Waydroid often ignores a lone monkey launch.
        """
        pkg = self.config.coc_package
        logger.info("Launching {}", pkg)

        # 1) Host-side Waydroid launcher (most reliable on Ubuntu)
        if shutil.which("waydroid"):
            try:
                subprocess.run(  # noqa: S603
                    ["waydroid", "app", "launch", pkg],
                    check=False,
                    timeout=45,
                    capture_output=True,
                    text=True,
                )
                logger.info("Issued: waydroid app launch {}", pkg)
            except (OSError, subprocess.TimeoutExpired) as exc:
                logger.warning("waydroid app launch failed: {}", exc)

        time.sleep(0.8)

        # 2) Resolve launcher activity and am start
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
            self.client.run_shell(
                f"am start -a android.intent.action.MAIN "
                f"-c android.intent.category.LAUNCHER {pkg}",
                check=False,
            )
            logger.info("Issued am start for package {}", pkg)

        # 3) Monkey fallback
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

        # Must see the process before treating any frame as "ready".
        while time.time() < deadline:
            if self.is_running():
                logger.info("Clash process is running")
                break
            time.sleep(1.0)
        else:
            logger.warning("Clash process never appeared (pidof empty)")
            return False

        process_since = time.time()
        saw_loading = False
        from coc_bot.vision.matcher import TemplateMatcher

        matcher = TemplateMatcher(threshold=0.75)

        while time.time() < deadline:
            frame = self.capture.screenshot()
            if loading_template is not None:
                match = matcher.find(frame, loading_template)
                if match is not None:
                    saw_loading = True
                    logger.debug("Loading screen visible")
                    time.sleep(1.5)
                    continue
                if saw_loading:
                    logger.info("Loading screen cleared")
                    return True
                # Process up but no loading template — wait a few seconds then accept busy frame.
                if time.time() - process_since >= 6.0:
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    if float(np.std(gray)) > 25.0:
                        logger.info("Game looks loaded (no loading template match)")
                        return True
            else:
                if time.time() - process_since < 5.0:
                    time.sleep(1.0)
                    continue
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                if float(np.std(gray)) > 25.0:
                    logger.info("Frame variance suggests game is loaded")
                    return True
            time.sleep(1.5)

        logger.warning("Game load timeout reached")
        return False
