from __future__ import annotations

import random
import time
from collections.abc import Callable

import numpy as np
from loguru import logger

from coc_bot.adb.input import InputController
from coc_bot.config import BotConfig
from coc_bot.stop import interrupted_sleep


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
        self.stop_check: Callable[[], bool] | None = None

    def _stopping(self) -> bool:
        return bool(self.stop_check and self.stop_check())

    def _sleep(self, seconds: float) -> bool:
        return interrupted_sleep(seconds, self.stop_check)

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
        reveals the right edge. Count may be fractional (e.g. 1.25 = one full
        swipe plus a quarter-length swipe).
        """
        h, w = frame.shape[:2]
        side = self._resolve_side(side)
        total = max(0.0, float(self.config.farm_pan_swipes))
        if total <= 0:
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

        full = int(total)
        frac = total - full
        logger.info(
            "Panning camera toward {} edge — {:.2f} swipe(s) ({},{}) -> ({},{})",
            side,
            total,
            x1,
            y,
            x2,
            y,
        )
        for i in range(full):
            if self._stopping():
                return
            self.input.swipe(x1, y, x2, y, duration_ms=duration_ms)
            if self._sleep(settle):
                return
            logger.debug("Pan swipe {}/{} done", i + 1, total)

        if frac >= 0.05:
            if self._stopping():
                return
            # Partial swipe: same start, shorter travel = less camera movement.
            x2_frac = int(round(x1 + (x2 - x1) * frac))
            dur = max(120, int(duration_ms * frac))
            self.input.swipe(x1, y, x2_frac, y, duration_ms=dur)
            if self._sleep(settle):
                return
            logger.debug("Pan fractional swipe {:.2f} done ({},{}) -> ({},{})", frac, x1, y, x2_frac, y)

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
        """Troop/hero cards sit on the bottom army bar during battle (not the top HUD)."""
        h, w = frame.shape[:2]
        return int(w * nx), int(h * 0.93)

    def select_edrag_slot(self, frame: np.ndarray) -> None:
        """Tap the first troop card (e-drags expected as the active army)."""
        point = self.config.tap_points.get("edrag_slot") or self.config.tap_points.get("troop_slot_0")
        if point:
            self.input.tap(int(point[0]), int(point[1]))
        else:
            x, y = self._army_bar_point(frame, 0.10)
            logger.info("Selecting e-drag slot at bottom bar ({}, {})", x, y)
            self.input.tap(x, y)
        time.sleep(0.25)

    def select_siege_slot(self, frame: np.ndarray) -> bool:
        """Tap the siege machine card on the bottom army bar. Returns False if disabled."""
        if not self.config.farm_deploy_siege:
            return False
        point = self.config.tap_points.get("siege_slot")
        if point:
            self.input.tap(int(point[0]), int(point[1]), jitter=0)
        else:
            # Typical spot after heroes / before spells on a filled army bar.
            x, y = self._army_bar_point(frame, 0.48)
            logger.info("Selecting siege slot at fallback ({}, {})", x, y)
            self.input.tap(x, y, jitter=0)
        time.sleep(0.30)
        return True

    def select_rage_slot(self, frame: np.ndarray) -> bool:
        """Tap the rage spell card on the bottom army bar. Returns False if disabled."""
        if not self.config.farm_deploy_rage:
            return False
        count = max(0, int(self.config.farm_rage_count))
        if count <= 0:
            return False
        point = self.config.tap_points.get("rage_slot") or self.config.tap_points.get("spell_slot")
        if point:
            self.input.tap(int(point[0]), int(point[1]), jitter=0)
        else:
            # Spells sit toward the right of the army bar after siege/heroes.
            x, y = self._army_bar_point(frame, 0.82)
            logger.info("Selecting rage slot at fallback ({}, {})", x, y)
            self.input.tap(x, y, jitter=0)
        time.sleep(0.30)
        return True

    def rage_drop_points(
        self,
        frame: np.ndarray,
        troop_points: list[tuple[int, int]],
        *,
        side: str | None = None,
    ) -> list[tuple[int, int]]:
        """
        Spread rage drops deep into the base, well past the troop column.

        Positions are jittered each attack so drops are not a perfect grid.
        For a left-edge deploy that means well to the right of the troops.
        """
        if not troop_points:
            return []
        count = max(0, int(self.config.farm_rage_count))
        if count <= 0:
            return []

        h, w = frame.shape[:2]
        side = self._resolve_side(side)
        troop_x = troop_points[0][0]
        # Base inward depth + small random offset (still toward the village).
        inward_frac = float(self.config.farm_rage_inward_frac)
        inward_frac += random.uniform(-0.03, 0.04)
        inward_frac = max(0.08, min(0.40, inward_frac))
        inward = int(w * inward_frac)
        rx_base = troop_x + inward if side == "left" else troop_x - inward
        rx_base = max(int(w * 0.08), min(int(w * 0.92), rx_base))

        # Vertical span with slight random margins.
        y0 = int(h * random.uniform(0.10, 0.16))
        y1 = int(h * random.uniform(0.70, 0.78))
        if y1 <= y0 + 40:
            y0, y1 = int(h * 0.12), int(h * 0.74)

        # Jitter scales with resolution — keep drops on the playfield.
        x_jitter = max(12, int(w * 0.035))
        y_jitter = max(10, int(h * 0.025))

        points: list[tuple[int, int]] = []
        for i in range(count):
            if count == 1:
                y = (y0 + y1) // 2
            else:
                y = int(y0 + (y1 - y0) * i / (count - 1))
            x = rx_base + random.randint(-x_jitter, x_jitter)
            y = y + random.randint(-y_jitter, y_jitter)
            x = max(int(w * 0.06), min(int(w * 0.94), x))
            y = max(int(h * 0.08), min(int(h * 0.80), y))
            points.append((x, y))

        # Don't always drop top→bottom in the same order.
        if count > 1 and random.random() < 0.45:
            points.reverse()
        elif count > 2 and random.random() < 0.25:
            random.shuffle(points)

        logger.info(
            "Rage drop points side={} base_x={} (troop_x={} inward={}) "
            "y={}-{} count={} jitter=±{}/±{}",
            side,
            rx_base,
            troop_x,
            inward,
            y0,
            y1,
            count,
            x_jitter,
            y_jitter,
        )
        return points

    def hero_slot_points(self, frame: np.ndarray) -> list[tuple[int, int]]:
        """Return up to 4 hero card centers on the bottom army bar."""
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
        y = int(h * 0.93)
        xs = [0.52, 0.58, 0.64, 0.70][:count]
        logger.info("Using default bottom-bar hero slot x positions {}", xs)
        return [(int(w * nx), y) for nx in xs]

    def dump_army_along_edge(
        self,
        frame: np.ndarray,
        *,
        side: str | None = None,
        tap_pause: float = 0.10,
    ) -> int:
        """
        Pan to the deploy edge, dump e-drags, then rage, then siege + heroes.

        Returns total map taps (not including army-bar selection taps).
        """
        side = self._resolve_side(side)
        self.pan_to_deploy_side(frame, side=side)
        if self._stopping():
            return 0
        points = self.deploy_points(frame, side=side)
        if not points:
            logger.warning("No deploy points — skipping dump")
            return 0

        self.select_edrag_slot(frame)
        if self._stopping():
            return 0

        edrag_taps = max(len(points), int(self.config.farm_edrag_deploy_taps))
        total = 0
        passes = 2
        for pass_i in range(passes):
            ordered = points if pass_i % 2 == 0 else list(reversed(points))
            for x, y in ordered:
                if self._stopping():
                    return total
                self.input.tap(x, y)
                total += 1
                if tap_pause > 0 and self._sleep(tap_pause):
                    return total
                if total >= edrag_taps and pass_i > 0:
                    break
            if total >= edrag_taps:
                break

        while total < edrag_taps:
            if self._stopping():
                return total
            x, y = points[total % len(points)]
            self.input.tap(x, y)
            total += 1
            if tap_pause > 0 and self._sleep(tap_pause):
                return total

        logger.info("Deployed e-drags along {} — {} map taps", side, total)

        # Rage right after dragons so the push is already on the map.
        rage_dropped = 0
        if not self._stopping() and self.select_rage_slot(frame):
            # One select arms all remaining rages — keep tapping the map.
            if self._sleep(0.35):
                return total
            rage_points = self.rage_drop_points(frame, points, side=side)
            logger.info(
                "Dropping {} rage spell(s) on the base (single slot select)",
                len(rage_points),
            )
            for i, (rx, ry) in enumerate(rage_points):
                if self._stopping():
                    return total
                logger.info("Deploying rage {}/{} at ({}, {})", i + 1, len(rage_points), rx, ry)
                self.input.tap(rx, ry)
                total += 1
                rage_dropped += 1
                if self._sleep(random.uniform(0.12, 0.28)):
                    return total

        # Siege: select card, drop once near mid-edge.
        if not self._stopping() and self.select_siege_slot(frame):
            sx, sy = points[len(points) // 2]
            logger.info("Deploying siege at ({}, {})", sx, sy)
            self.input.tap(sx, sy)
            total += 1
            if self._sleep(0.35):
                return total

        heroes = self.hero_slot_points(frame)
        place_idxs = [
            int(i * (len(points) - 1) / max(1, len(heroes) - 1)) if len(heroes) > 1 else len(points) // 2
            for i in range(len(heroes))
        ]
        activate = bool(self.config.farm_activate_hero_abilities)
        for hero_i, (hx, hy) in enumerate(heroes):
            if self._stopping():
                return total
            logger.info("Deploying hero {} via slot ({}, {})", hero_i + 1, hx, hy)
            self.input.tap(hx, hy, jitter=0)
            if self._sleep(0.30):
                return total
            px, py = points[place_idxs[hero_i]]
            self.input.tap(px, py)
            total += 1
            if self._sleep(0.40):
                return total
            # Ability: tap the same hero icon again after they are on the map.
            if activate:
                logger.info("Activating hero {} ability (re-tap slot)", hero_i + 1)
                self.input.tap(hx, hy, jitter=0)
                if self._sleep(0.35):
                    return total

        logger.info(
            "Army dump complete — {} map taps, {} heroes (abilities={}), siege={}, rage={}",
            total,
            len(heroes),
            activate,
            self.config.farm_deploy_siege,
            rage_dropped,
        )
        return total
