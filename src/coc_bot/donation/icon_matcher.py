"""Match donation-panel slot crops to unit IDs via bundled game icons."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from loguru import logger

from coc_bot.config import BotConfig
from coc_bot.game_data import UnitStats, load_units
from coc_bot.vision.matcher import TemplateMatcher


class IconMatcher:
    """Template-match a slot crop against bundled icons under data/icons/."""

    def __init__(
        self,
        config: BotConfig,
        matcher: TemplateMatcher | None = None,
        icons_dir: Path | None = None,
    ) -> None:
        self.config = config
        self.matcher = matcher or TemplateMatcher(
            threshold=max(0.55, config.template_threshold - 0.2),
            scale_range=[0.7, 0.85, 1.0, 1.15, 1.3],
        )
        root = Path(__file__).resolve().parents[3]
        self.icons_dir = icons_dir or (root / "data" / "icons")
        self.units = load_units()
        self._templates: dict[str, np.ndarray] | None = None

    def available(self) -> bool:
        return self.icons_dir.exists() and any(self.icons_dir.rglob("*.*"))

    def _load_templates(self) -> dict[str, np.ndarray]:
        if self._templates is not None:
            return self._templates
        templates: dict[str, np.ndarray] = {}
        if not self.icons_dir.exists():
            logger.debug("Icon pack missing at {}", self.icons_dir)
            self._templates = templates
            return templates

        for path in sorted(self.icons_dir.rglob("*")):
            if path.suffix.lower() not in {".png", ".webp", ".jpg", ".jpeg"}:
                continue
            unit_id = path.stem
            # data/icons/spells/rage_spell.webp → rage_spell
            # data/icons/troops/yeti.png → yeti
            img = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if img is None or img.size == 0:
                continue
            templates[unit_id] = img

        logger.info("Loaded {} unit icons from {}", len(templates), self.icons_dir)
        self._templates = templates
        return templates

    def match_slot(
        self,
        cell: np.ndarray,
        *,
        preferred_categories: set[str] | None = None,
    ) -> tuple[str, float] | None:
        """Return (unit_id, confidence) for the best matching icon, or None."""
        templates = self._load_templates()
        if not templates or cell.size == 0:
            return None

        best_id: str | None = None
        best_conf = -1.0
        for unit_id, template in templates.items():
            stats = self.units.get(unit_id)
            if preferred_categories and stats is not None:
                if stats.category not in preferred_categories:
                    continue
            # Resize template toward slot size for better match.
            th, tw = cell.shape[:2]
            scaled = template
            if template.shape[0] > th * 1.5 or template.shape[1] > tw * 1.5:
                scale = min(th / template.shape[0], tw / template.shape[1]) * 0.85
                nw = max(8, int(template.shape[1] * scale))
                nh = max(8, int(template.shape[0] * scale))
                scaled = cv2.resize(template, (nw, nh), interpolation=cv2.INTER_AREA)
            if scaled.shape[0] >= cell.shape[0] or scaled.shape[1] >= cell.shape[1]:
                continue
            match = self.matcher.find(cell, scaled)
            if match is not None and match.confidence > best_conf:
                best_conf = match.confidence
                best_id = unit_id

        if best_id is None:
            return None
        return best_id, best_conf

    def resolve_category(self, unit_id: str, default: str) -> str:
        stats: UnitStats | None = self.units.get(unit_id)
        if stats is None:
            return default
        return stats.category
