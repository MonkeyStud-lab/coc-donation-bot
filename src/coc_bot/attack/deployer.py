from __future__ import annotations

import time

import numpy as np
from loguru import logger

from coc_bot.adb.input import InputController
from coc_bot.config import BotConfig


class EdgeDeployer:
    """
    Deploy troops/heroes just outside the defending village.

    Matchmaking always centers the camera on the base. The battlefield size is
    fixed, so we pan toward the deploy side with a fixed number of swipes, then
    tap a fixed screen column (no scenery / red-line vision).
    """

    def __init__(self, config: BotConfig, input_ctrl: InputController) -> None:
        self.config = config
        self.input = input_ctrl

    def _resolve_side(self, side: str | None) -> str:
        side = (side or self.config.farm_deploy_side).strip().lower()
        return side if side in ("left", "right") else "left"

    def pan_to_deploy_side(
        self,
        frame: np.ndarray,
        *,
        side: str | None = None,
    ) -> None:
        """
        Pan from the centered matchmaking view toward the deploy edge.

        Finger drag pulls the map: swipe right reveals the left edge; swipe left
        reveals the right edge. Swipe count is fixed (base space is fixed).
        """
        h, w = frame.shape[:2]
        side = self._resolve_side(side)
        count = max(0, int(self.config.farm_pan_swipes))
        if count == 0:
            logger.info("Camera pan skipped (farm_pan_swipes=0)")
            return

        # Horizontal drag across the middle of the playfield (avoid army bar / UI).
        y = int(h * 0.42)
        # Long swipe so each drag moves a useful chunk of the map.
        left_x = int(w * 0.28)
        right_x = int(w * 0.72)
        duration_ms = 280
        settle = 0.45

        if side == "left":
            # Finger moves right → map shifts right → left grass comes into view.
            x1, x2 = left_x, right_x
        else:
            x1, x2 = right_x, left_x

        logger.info(
            "Panning camera toward {} edge — {} swipe(s) ({},{}) -> ({},{})",
            side,
            count,
            x1,
            y,
            x2,
            y,
        )
        for i in range(count):
            self.input.swipe(x1, y, x2, y, duration_ms=duration_ms)
            time.sleep(settle)
            logger.debug("Pan swipe {}/{} done", i + 1, count)

    def deploy_points(self, frame: np.ndarray, side: str | None = None) -> list[tuple[int, int]]:
        """Vertical tap ladder on the visible deploy edge after panning."""
        h, w = frame.shape[:2]
        side = self._resolve_side(side)
        taps = max(8, int(self.config.farm_edrag_deploy_taps))

        # After panning, grass sits near that screen edge — keep taps on map, not UI.
        cx = int(w * 0.10) if side == "left" else int(w * 0.90)
        y0, y1 = int(h * 0.18), int(h * 0.68)

        logger.info(
            "Deploy ladder side={} x={} y={}-{} taps={}",
            side,
            cx,
            y0,
            y1,
            taps,
        )
        return [
            (cx, int(y0 + (y1 - y0) * i / max(1, taps - 1)))
            for i in range(taps)
        ]

    def _army_bar_point(self, frame: np.ndarray, nx: float) -> tuple[int, int]:
        h, w = frame.shape[:2]
        return int(w * nx), int(h * 0.91)

    def select_edrag_slot(self, frame: np.ndarray) -> None:
        """Tap the first troop card (e-drags expected as the active army)."""
        point = self.config.tap_points.get("edrag_slot") or self.config.tap_points.get("troop_slot_0")
        if point:
            self.input.tap(int(point[0]), int(point[1]))
        else:
            x, y = self._army_bar_point(frame, 0.10)
            logger.info("Selecting e-drag slot at fallback ({}, {})", x, y)
            self.input.tap(x, y)
        time.sleep(0.25)

    def hero_slot_points(self, frame: np.ndarray) -> list[tuple[int, int]]:
        """Return up to 4 hero card centers on the army bar."""
        count = max(0, min(4, int(self.config.farm_hero_count)))
        points: list[tuple[int, int]] = []
        for i in range(1, count + 1):
            key = f"hero_{i}"
            raw = self.config.tap_points.get(key)
            if raw:
                points.append((int(raw[0]), int(raw[1])))
        if len(points) >= count:
            return points[:count]

        h, w = frame.shape[:2]
        y = int(h * 0.91)
        xs = [0.52, 0.58, 0.64, 0.70][:count]
        logger.info("Using default hero slot x positions {}", xs)
        return [(int(w * nx), y) for nx in xs]

    def dump_army_along_edge(
        self,
        frame: np.ndarray,
        *,
        side: str | None = None,
        tap_pause: float = 0.10,
    ) -> int:
        """
        Pan to the deploy edge, select e-drags, spam the ladder, then place heroes.

        Returns total map taps (not including army-bar selection taps).
        """
        side = self._resolve_side(side)
        self.pan_to_deploy_side(frame, side=side)
        # Fresh frame not required for fixed geometry; keep original dims.
        points = self.deploy_points(frame, side=side)
        if not points:
            logger.warning("No deploy points — skipping dump")
            return 0

        self.select_edrag_slot(frame)

        edrag_taps = max(len(points), int(self.config.farm_edrag_deploy_taps))
        total = 0
        passes = 2
        for pass_i in range(passes):
            ordered = points if pass_i % 2 == 0 else list(reversed(points))
            for x, y in ordered:
                self.input.tap(x, y)
                total += 1
                if tap_pause > 0:
                    time.sleep(tap_pause)
                if total >= edrag_taps and pass_i > 0:
                    break
            if total >= edrag_taps:
                break

        while total < edrag_taps:
            x, y = points[total % len(points)]
            self.input.tap(x, y)
            total += 1
            if tap_pause > 0:
                time.sleep(tap_pause)

        logger.info("Deployed e-drags along {} — {} map taps", side, total)

        heroes = self.hero_slot_points(frame)
        place_idxs = [
            int(i * (len(points) - 1) / max(1, len(heroes) - 1)) if len(heroes) > 1 else len(points) // 2
            for i in range(len(heroes))
        ]
        for hero_i, (hx, hy) in enumerate(heroes):
            logger.info("Deploying hero {} via slot ({}, {})", hero_i + 1, hx, hy)
            self.input.tap(hx, hy)
            time.sleep(0.30)
            px, py = points[place_idxs[hero_i]]
            self.input.tap(px, py)
            total += 1
            time.sleep(0.35)

        logger.info("Army dump complete — {} map taps, {} heroes", total, len(heroes))
        return total
