"""Load synced game unit metadata (housing space, category)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class UnitStats:
    unit_id: str
    name: str
    category: str  # troop, spell, siege
    housing: int


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def load_units(path: Path | None = None) -> dict[str, UnitStats]:
    root = _project_root()
    path = path or root / "data" / "game" / "units.yaml"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}
    units: dict[str, UnitStats] = {}
    for unit_id, info in (raw.get("units") or {}).items():
        units[unit_id] = UnitStats(
            unit_id=unit_id,
            name=str(info.get("name", unit_id)),
            category=str(info.get("category", "troop")),
            housing=int(info.get("housing", 1)),
        )
    return units


def housing_for(unit_id: str, units: dict[str, UnitStats] | None = None) -> int | None:
    units = units if units is not None else load_units()
    stats = units.get(unit_id)
    return stats.housing if stats else None
