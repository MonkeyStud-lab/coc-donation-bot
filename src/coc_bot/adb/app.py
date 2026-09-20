from __future__ import annotations

import re
import shutil
import subprocess
import time
from collections.abc import Callable

import cv2
import numpy as np
from loguru import logger

from coc_bot.adb.capture import ScreenCapture
from coc_bot.adb.client import AdbClient, validate_package_name
from coc_bot.config import BotConfig
from coc_bot.stop import interrupted_sleep

# ``pkg/.Activity`` or ``pkg/pkg.Activity`` — nothing else may reach ``am start -n``.
_ACTIVITY_RE = re.compile(r"^[A-Za-z][\w.]*/[\w.$]+$")


class AppController:
    """Force-stop and relaunch Clash of Clans."""

    def __init__(self, client: AdbClient, config: BotConfig, capture: ScreenCapture) -> None:
        self.client = client
        self.config = config
        self.capture = capture
        # Optional cooperative stop hook so long game-load waits can be interrupted.
        self.stop_check: Callable[[], bool] | None = None

    def _pkg(self) -> str:
        return validate_package_name(self.config.coc_package)

    def _stopped(self) -> bool:
        return bool(self.stop_check and self.stop_check())

    def force_stop(self) -> None:
        pkg = self._pkg()
        logger.info("Force-stopping {}", pkg)
        self.client.run_shell(f"am force-stop {pkg}", check=False)

    def is_running(self) -> bool:
        pkg = self._pkg()
        result = self.client.run_shell(f"pidof {pkg}", check=False)
        return bool((result.stdout or "").strip())

    def launch(self) -> None:
        """
        Start Clash of Clans inside the Waydroid Android UI.

        Uses ADB only (am start / monkey). Avoids `waydroid app launch`, which
        opens CoC as a separate Linux window/dock icon instead of inside
        show-full-ui.
        """
        pkg = self._pkg()
        logger.info("Launching {} inside Waydroid session", pkg)

        # Make sure the full Android UI window is up (not multi-window app mode).
        if shutil.which("waydroid"):
            try:
                subprocess.Popen(  # noqa: S603
                    ["waydroid", "show-full-ui"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                logger.info("Ensured waydroid show-full-ui")
                time.sleep(1.5)
            except OSError as exc:
                logger.warning("Could not run show-full-ui: {}", exc)

        resolve = self.client.run_shell(
            f"cmd package resolve-activity --brief {pkg}",
            check=False,
        )
        activity = ""
        for line in (resolve.stdout or "").splitlines():
            line = line.strip()
            # Only accept a clean ``pkg/Activity`` token — this string is passed
            # straight into the device shell.
            if line.startswith(pkg + "/") and _ACTIVITY_RE.match(line):
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

        self.client.run_shell(
            f"monkey -p {pkg} -c android.intent.category.LAUNCHER 1",
            check=False,
        )
        # Live Replay only appears right after opening Clash (e.g. post-break).
        from coc_bot.vision.screens import ScreenClassifier

        ScreenClassifier.arm_live_replay_watch()

    def wait_until_ready(
        self,
        loading_template: np.ndarray | None = None,
        timeout_seconds: int | None = None,
    ) -> bool:
        timeout = timeout_seconds or self.config.game_load_timeout_seconds
        deadline = time.time() + timeout
        logger.info("Waiting for game to load (timeout {}s)...", timeout)

        def sleep(seconds: float) -> bool:
            """Interruptible sleep; True means Stop was requested."""
            return interrupted_sleep(seconds, self.stop_check)

        # Must see the process before treating any frame as "ready".
        while time.time() < deadline:
            if self._stopped():
                logger.info("Stop requested while waiting for Clash process")
                return False
            if self.is_running():
                logger.info("Clash process is running")
                break
            if sleep(1.0):
                return False
        else:
            logger.warning("Clash process never appeared (pidof empty)")
            return False

        process_since = time.time()
        saw_loading = False
        from coc_bot.vision.matcher import TemplateMatcher

        matcher = TemplateMatcher(threshold=0.75)

        while time.time() < deadline:
            if self._stopped():
                logger.info("Stop requested while waiting for game load")
                return False
            frame = self.capture.screenshot()
            if loading_template is not None:
                match = matcher.find(frame, loading_template)
                if match is not None:
                    saw_loading = True
                    logger.debug("Loading screen visible")
                    if sleep(1.5):
                        return False
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
                    if sleep(1.0):
                        return False
                    continue
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                if float(np.std(gray)) > 25.0:
                    logger.info("Frame variance suggests game is loaded")
                    return True
            if sleep(1.5):
                return False

        logger.warning("Game load timeout reached")
        return False
