from __future__ import annotations

import random
import time

from loguru import logger

from coc_bot.adb.client import AdbClient


class InputController:
    """Send taps and swipes via ADB with human-like jitter."""

    def __init__(
        self,
        client: AdbClient,
        jitter_px: int = 6,
        delay_ms: tuple[int, int] = (120, 350),
        dry_run: bool = False,
    ) -> None:
        self.client = client
        self.jitter_px = jitter_px
        self.delay_ms = delay_ms
        self.dry_run = dry_run

    def _sleep(self) -> None:
        lo, hi = self.delay_ms
        time.sleep(random.uniform(lo, hi) / 1000.0)

    def tap(self, x: int, y: int) -> None:
        j = self.jitter_px
        tx = x + random.randint(-j, j)
        ty = y + random.randint(-j, j)
        if self.dry_run:
            logger.info("[DRY-RUN] tap ({}, {})", tx, ty)
        else:
            self.client.run_shell(f"input tap {tx} {ty}")
        self._sleep()

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        if self.dry_run:
            logger.info("[DRY-RUN] swipe ({},{}) -> ({},{}), {}ms", x1, y1, x2, y2, duration_ms)
        else:
            self.client.run_shell(f"input swipe {x1} {y1} {x2} {y2} {duration_ms}")
        self._sleep()

    def back(self) -> None:
        if self.dry_run:
            logger.info("[DRY-RUN] keyevent BACK")
        else:
            self.client.run_shell("input keyevent KEYCODE_BACK")
        self._sleep()

    def scroll_up(self, cx: int, cy: int, distance: int = 400) -> None:
        self.swipe(cx, cy, cx, cy - distance, duration_ms=350)

    def scroll_down(self, cx: int, cy: int, distance: int = 400) -> None:
        self.swipe(cx, cy, cx, cy + distance, duration_ms=350)

    def pinch_zoom_out(
        self,
        width: int,
        height: int,
        *,
        repeats: int = 3,
        duration_ms: int = 280,
    ) -> None:
        """
        Pinch-in (fingers move together) to zoom out the village / battlefield.

        Uses two concurrent ADB swipes toward the screen center. Works on most
        Waydroid / Android builds; repeats a few times to reach max zoom-out.
        """
        if width <= 0 or height <= 0:
            logger.warning("pinch_zoom_out skipped — invalid size {}x{}", width, height)
            return

        cx, cy = width // 2, height // 2
        # Keep the gesture on the map, away from bottom army / top resource UI.
        span = int(min(width, height) * 0.28)
        x1, y1 = cx - span, cy - span
        x2, y2 = cx + span, cy + span

        for i in range(max(1, repeats)):
            if self.dry_run:
                logger.info(
                    "[DRY-RUN] pinch zoom-out #{}/{} toward ({}, {})",
                    i + 1,
                    repeats,
                    cx,
                    cy,
                )
            else:
                # Parallel swipes approximate a two-finger pinch-in.
                cmd = (
                    f"input swipe {x1} {y1} {cx} {cy} {duration_ms} & "
                    f"input swipe {x2} {y2} {cx} {cy} {duration_ms} & "
                    f"wait"
                )
                logger.info("Pinch zoom-out {}/{} (span={})", i + 1, repeats, span)
                self.client.run_shell(cmd)
            time.sleep(0.35)
        self._sleep()
