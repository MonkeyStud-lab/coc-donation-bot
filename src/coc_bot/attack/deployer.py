from __future__ import annotations

import time

import numpy as np
from loguru import logger

from coc_bot.adb.input import InputController
from coc_bot.config import BotConfig
from coc_bot.vision.rois import ROI, denormalize_roi


class EdgeDeployer:
    """Deploy the active army along one vertical edge of the battlefield."""

    def __init__(self, config: BotConfig, input_ctrl: InputController) -> None:
        self.config = config
        self.input = input_ctrl

    def deploy_points(self, frame: np.ndarray, side: str | None = None) -> list[tuple[int, int]]:
        """Build a vertical tap ladder on the left or right edge."""
        h, w = frame.shape[:2]
        side = (side or self.config.farm_deploy_side).strip().lower()
        if side not in ("left", "right"):
            side = "left"

        if "deploy_strip" in self.config.rois:
            x, y, rw, rh = denormalize_roi(ROI(*self.config.rois["deploy_strip"]), w, h)
            cx = x + rw // 2
            taps = 8
            points: list[tuple[int, int]] = []
            for i in range(taps):
                ty = y + int(rh * (0.08 + 0.84 * i / max(1, taps - 1)))
                points.append((cx, ty))
            return points

        nx = 0.08 if side == "left" else 0.92
        cx = int(w * nx)
        taps = 10
        return [
            (cx, int(h * (0.22 + 0.56 * i / max(1, taps - 1))))
            for i in range(taps)
        ]

    def dump_army_along_edge(
        self,
        frame: np.ndarray,
        *,
        side: str | None = None,
        passes: int = 2,
        tap_pause: float = 0.12,
    ) -> int:
        """
        Tap along one edge to dump the preset army (e-drags assumed selected).

        Returns the number of taps performed.
        """
        points = self.deploy_points(frame, side=side)
        total = 0
        for pass_i in range(passes):
            ordered = points if pass_i % 2 == 0 else list(reversed(points))
            for x, y in ordered:
                logger.debug("Deploy tap ({}, {})", x, y)
                self.input.tap(x, y)
                total += 1
                if tap_pause > 0:
                    time.sleep(tap_pause)
        logger.info(
            "Deployed along {} edge — {} taps ({} passes)",
            side or self.config.farm_deploy_side,
            total,
            passes,
        )
        return total
