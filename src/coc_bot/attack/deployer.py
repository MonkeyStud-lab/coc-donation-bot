from __future__ import annotations

import time

import cv2
import numpy as np
from loguru import logger

from coc_bot.adb.input import InputController
from coc_bot.config import BotConfig
from coc_bot.vision.rois import ROI, denormalize_roi


class EdgeDeployer:
    """
    Deploy troops/heroes into the grass outside the defending village.

    CoC only accepts taps in the deployable ring around the base — not at the
    far screen edge and not inside buildings.
    """

    def __init__(self, config: BotConfig, input_ctrl: InputController) -> None:
        self.config = config
        self.input = input_ctrl

    def find_village_bbox(self, frame: np.ndarray) -> tuple[int, int, int, int] | None:
        """
        Approximate the defending village as a bounding box (x, y, w, h).

        Uses edge density in the playfield (excludes army bar / top UI).
        """
        h, w = frame.shape[:2]
        y0, y1 = int(h * 0.06), int(h * 0.78)
        x0, x1 = int(w * 0.04), int(w * 0.96)
        crop = frame[y0:y1, x0:x1]
        if crop.size == 0:
            return None

        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(gray, 35, 110)
        # Buildings create dense edges; dilate into one blob.
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (21, 21))
        blob = cv2.dilate(edges, kernel, iterations=2)
        blob = cv2.morphologyEx(blob, cv2.MORPH_CLOSE, kernel, iterations=2)

        contours, _ = cv2.findContours(blob, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None

        # Prefer a large central contour (the base), not tiny UI noise.
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
            # Reward size; lightly penalize far-from-center blobs.
            dist = ((bcx - cx0) ** 2 + (bcy - cy0) ** 2) ** 0.5
            score = area - dist * 40
            if score > best_score:
                best_score = score
                best = (bx + x0, by + y0, bw, bh)

        return best

    def deploy_points(self, frame: np.ndarray, side: str | None = None) -> list[tuple[int, int]]:
        """Vertical tap ladder in the deployable grass on one side of the village."""
        h, w = frame.shape[:2]
        side = (side or self.config.farm_deploy_side).strip().lower()
        if side not in ("left", "right"):
            side = "left"

        taps = max(8, int(self.config.farm_edrag_deploy_taps))

        if "deploy_strip" in self.config.rois:
            x, y, rw, rh = denormalize_roi(ROI(*self.config.rois["deploy_strip"]), w, h)
            cx = x + rw // 2
            return [
                (cx, y + int(rh * (0.08 + 0.84 * i / max(1, taps - 1))))
                for i in range(taps)
            ]

        village = self.find_village_bbox(frame)
        # Stay above the army bar and below top chrome.
        y_min, y_max = int(h * 0.14), int(h * 0.72)

        if village is not None:
            vx, vy, vw, vh = village
            # Offset outward from the village edge into the grass ring.
            gap = max(28, int(w * 0.035))
            if side == "left":
                cx = max(int(w * 0.06), vx - gap)
            else:
                cx = min(int(w * 0.94), vx + vw + gap)
            # Prefer the vertical span of the village (deployable along that side).
            y0 = max(y_min, vy - int(h * 0.02))
            y1 = min(y_max, vy + vh + int(h * 0.02))
            if y1 - y0 < int(h * 0.2):
                y0, y1 = y_min, y_max
            logger.info(
                "Village bbox=({}, {}, {}, {}) — deploy {} x={} y={}-{}",
                vx,
                vy,
                vw,
                vh,
                side,
                cx,
                y0,
                y1,
            )
            return [
                (cx, int(y0 + (y1 - y0) * i / max(1, taps - 1)))
                for i in range(taps)
            ]

        # Fallback: inset from screen edge (still inside typical map, not UI).
        logger.warning("Village edge not found — using inset screen-edge fallback")
        nx = 0.14 if side == "left" else 0.86
        cx = int(w * nx)
        return [
            (cx, int(h * (0.20 + 0.50 * i / max(1, taps - 1))))
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
            # Left side of the battle army bar — first troop card.
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

        # Default: heroes sit mid-right on the landscape army bar.
        # Spread 4 slots across ~0.50–0.70 of screen width.
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
        # Walk the line multiple times so all 11 e-drags leave the bar.
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

        # Extra taps if we still need more for 11 dragons.
        while total < edrag_taps:
            x, y = points[total % len(points)]
            self.input.tap(x, y)
            total += 1
            if tap_pause > 0:
                time.sleep(tap_pause)

        logger.info(
            "Deployed e-drags along {} village edge — {} map taps",
            side or self.config.farm_deploy_side,
            total,
        )

        # Fresh frame for hero bar (icons don't move, but be safe).
        hero_frame = frame
        heroes = self.hero_slot_points(hero_frame)
        # Place heroes spaced along the same edge.
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
