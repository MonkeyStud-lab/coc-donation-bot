from __future__ import annotations

import time

import cv2
import numpy as np
from loguru import logger

from coc_bot.adb.input import InputController
from coc_bot.config import BotConfig


class EdgeDeployer:
    """
    Deploy troops/heroes just outside the defending village.

    Does NOT depend on grass/snow scenery. Order of strategies:
      1. CoC red deployment boundary (same UI color on every biome)
      2. Building-edge blob (village shape, scenery-agnostic)
      3. Fixed playfield geometry (always available)
    """

    def __init__(self, config: BotConfig, input_ctrl: InputController) -> None:
        self.config = config
        self.input = input_ctrl

    def _playfield(self, frame: np.ndarray) -> tuple[int, int, int, int]:
        """Return (x0, y0, x1, y1) map area excluding army bar / top chrome."""
        h, w = frame.shape[:2]
        return int(w * 0.04), int(h * 0.08), int(w * 0.96), int(h * 0.76)

    def find_red_deploy_line_x(self, frame: np.ndarray, side: str) -> int | None:
        """
        Find the X of CoC's red deployment ring on the left or right side.

        The ring color is UI chrome, so it stays red across village themes.
        """
        h, w = frame.shape[:2]
        x0, y0, x1, y1 = self._playfield(frame)
        crop = frame[y0:y1, x0:x1]
        if crop.size == 0:
            return None

        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        # Red wraps HSV hue; keep saturation high so dirt/roofs are ignored.
        mask1 = cv2.inRange(hsv, (0, 120, 80), (10, 255, 255))
        mask2 = cv2.inRange(hsv, (170, 120, 80), (180, 255, 255))
        red = cv2.bitwise_or(mask1, mask2)
        red = cv2.morphologyEx(
            red, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        )

        # Column scores: how much red in each x.
        col = red.mean(axis=0)  # 0–255
        if float(col.max()) < 8:
            return None

        # Search only the outer half of the playfield for this side.
        mid = len(col) // 2
        if side == "left":
            region = col[:mid]
            # Peak nearest the village (rightmost strong red in left half).
            thresh = max(12.0, float(region.max()) * 0.45)
            idxs = np.where(region >= thresh)[0]
            if len(idxs) == 0:
                return None
            local_x = int(idxs.max())
        else:
            region = col[mid:]
            thresh = max(12.0, float(region.max()) * 0.45)
            idxs = np.where(region >= thresh)[0]
            if len(idxs) == 0:
                return None
            local_x = mid + int(idxs.min())

        return x0 + local_x

    def find_village_bbox(self, frame: np.ndarray) -> tuple[int, int, int, int] | None:
        """
        Approximate the defending village as a bounding box (x, y, w, h).

        Uses building edge density — not grass/snow color — so themes matter less.
        """
        h, w = frame.shape[:2]
        x0, y0, x1, y1 = self._playfield(frame)
        crop = frame[y0:y1, x0:x1]
        if crop.size == 0:
            return None

        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(gray, 35, 110)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (21, 21))
        blob = cv2.dilate(edges, kernel, iterations=2)
        blob = cv2.morphologyEx(blob, cv2.MORPH_CLOSE, kernel, iterations=2)

        contours, _ = cv2.findContours(blob, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None

        best = None
        best_score = -1.0
        crop_h, crop_w = crop.shape[:2]
        cx0, cy0 = crop_w / 2, crop_h / 2
        min_area = crop_w * crop_h * 0.04
        for cnt in contours:
            area = float(cv2.contourArea(cnt))
            if area < min_area:
                continue
            bx, by, bw, bh = cv2.boundingRect(cnt)
            bcx, bcy = bx + bw / 2, by + bh / 2
            dist = ((bcx - cx0) ** 2 + (bcy - cy0) ** 2) ** 0.5
            score = area - dist * 40
            if score > best_score:
                best_score = score
                best = (bx + x0, by + y0, bw, bh)

        return best

    def deploy_points(self, frame: np.ndarray, side: str | None = None) -> list[tuple[int, int]]:
        """Vertical tap ladder just outside the base on one side (scenery-independent)."""
        h, w = frame.shape[:2]
        side = (side or self.config.farm_deploy_side).strip().lower()
        if side not in ("left", "right"):
            side = "left"

        taps = max(8, int(self.config.farm_edrag_deploy_taps))
        y_min, y_max = int(h * 0.16), int(h * 0.70)
        method = "geometry"
        cx: int | None = None
        village = self.find_village_bbox(frame)

        # 1) Red deployment ring (theme-independent UI).
        red_x = self.find_red_deploy_line_x(frame, side)
        if red_x is not None:
            # Place slightly OUTSIDE the red line (away from buildings).
            pad = max(18, int(w * 0.012))
            cx = red_x - pad if side == "left" else red_x + pad
            method = "red_line"

        # 2) Building blob edge + outward gap.
        if cx is None and village is not None:
            vx, _vy, vw, _vh = village
            gap = max(32, int(w * 0.04))
            cx = vx - gap if side == "left" else vx + vw + gap
            method = "village_bbox"

        # 3) Fixed geometry: playfield center ± fraction (never depends on pixels/theme).
        if cx is None:
            play_cx = w // 2
            half = int(w * 0.22)
            cx = play_cx - half if side == "left" else play_cx + half
            method = "geometry"

        cx = int(max(int(w * 0.05), min(int(w * 0.95), cx)))

        if village is not None:
            _vx, vy, _vw, vh = village
            y0 = max(y_min, vy - int(h * 0.02))
            y1 = min(y_max, vy + vh + int(h * 0.02))
            if y1 - y0 < int(h * 0.2):
                y0, y1 = y_min, y_max
        else:
            y0, y1 = y_min, y_max

        logger.info(
            "Deploy line method={} side={} x={} y={}-{} village={}",
            method,
            side,
            cx,
            y0,
            y1,
            village,
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
        Select e-drags, spam along the village edge, then deploy each hero.

        Returns total map taps (not including army-bar selection taps).
        """
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

        logger.info(
            "Deployed e-drags along {} — {} map taps",
            side or self.config.farm_deploy_side,
            total,
        )

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
