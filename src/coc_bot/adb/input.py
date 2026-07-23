from __future__ import annotations

import os
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
        # Screencap size of the last mapped frame (width, height).
        self._frame_size: tuple[int, int] | None = None
        self._touch_size: tuple[int, int] | None = None
        self._touch_size_checked = False
        # Opt-in: COC_BOT_SCALE_TAPS=1 when screencap pixels truly differ from wm size.
        # Default off — Waydroid often reports a wrong wm size and scaling misses taps.
        self._scale_taps = os.environ.get("COC_BOT_SCALE_TAPS", "").strip().lower() in (
            "1",
            "true",
            "yes",
        )

    def set_frame_size(self, width: int, height: int) -> None:
        """Tell the input layer the current screencap resolution for optional tap scaling."""
        self._frame_size = (int(width), int(height))

    def _ensure_touch_size(self) -> None:
        if self._touch_size_checked:
            return
        self._touch_size_checked = True
        self._touch_size = self.client.wm_size()
        if (
            self._scale_taps
            and self._touch_size
            and self._frame_size
            and self._touch_size != self._frame_size
        ):
            logger.warning(
                "Scaling taps: screencap {}x{} → touch {}x{} (COC_BOT_SCALE_TAPS=1)",
                self._frame_size[0],
                self._frame_size[1],
                self._touch_size[0],
                self._touch_size[1],
            )
        elif self._touch_size and self._frame_size and self._touch_size != self._frame_size:
            logger.warning(
                "screencap {}x{} != wm size {}x{} — using screencap coords (set COC_BOT_SCALE_TAPS=1 to scale)",
                self._frame_size[0],
                self._frame_size[1],
                self._touch_size[0],
                self._touch_size[1],
            )

    def _to_touch(self, x: int, y: int) -> tuple[int, int]:
        """Optionally map screencap pixels to wm size (disabled by default)."""
        self._ensure_touch_size()
        if not self._scale_taps:
            return x, y
        if not self._frame_size or not self._touch_size:
            return x, y
        fw, fh = self._frame_size
        tw, th = self._touch_size
        if fw <= 0 or fh <= 0 or (fw, fh) == (tw, th):
            return x, y
        return int(round(x * tw / fw)), int(round(y * th / fh))

    def _sleep(self) -> None:
        lo, hi = self.delay_ms
        time.sleep(random.uniform(lo, hi) / 1000.0)

    def tap(self, x: int, y: int, *, jitter: int | None = None) -> None:
        j = self.jitter_px if jitter is None else max(0, int(jitter))
        tx = x + (random.randint(-j, j) if j else 0)
        ty = y + (random.randint(-j, j) if j else 0)
        tx, ty = self._to_touch(tx, ty)
        if self.dry_run:
            logger.info("[DRY-RUN] tap ({}, {})", tx, ty)
        else:
            self.client.run_shell(f"input tap {tx} {ty}")
        self._sleep()

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        x1, y1 = self._to_touch(x1, y1)
        x2, y2 = self._to_touch(x2, y2)
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
