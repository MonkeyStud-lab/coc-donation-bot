#!/usr/bin/env python3
"""
Download troop/siege housing space and merge spell seed data into data/game/units.yaml.

NOTE: The coc.guide *website* may redirect-loop in a browser. These direct static
JSON URLs work from curl/Python (no homepage visit needed):

  https://coc.guide/static/json/characters.json
  https://coc.guide/static/json/supers.json

If download fails, the existing data/game/units.yaml is left unchanged.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "data" / "game" / "units.yaml"
SPELL_SEED = ROOT / "config" / "game_spells_seed.yaml"

# Direct static paths only — do not use https://coc.guide/ (homepage redirects).
SOURCES = {
    "characters": "https://coc.guide/static/json/characters.json",
    "supers": "https://coc.guide/static/json/supers.json",
}

TROOP_BUILDINGS = {"Barrack", "Barrack2", "Dark Elixir Barrack"}
SIEGE_BUILDINGS = {"SiegeWorkshop"}

USER_AGENT = "coc-donation-bot/0.1 (+https://github.com/MonkeyStud-lab/coc-donation-bot)"


def _slug(name: str) -> str:
    s = name.lower().replace("&", "and")
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    if s.startswith("siege_"):
        s = s.removeprefix("siege_")
    return s


def _first_int(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, list) and value:
        return int(value[0])
    if isinstance(value, (int, float)):
        return int(value)
    return None


def fetch_json(url: str, timeout: float = 30.0) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def _category_from_building(building: str | None) -> str | None:
    if building in TROOP_BUILDINGS:
        return "troop"
    if building in SIEGE_BUILDINGS:
        return "siege"
    return None


def parse_characters(characters: dict) -> dict[str, dict]:
    units: dict[str, dict] = {}
    for name, data in characters.items():
        if not isinstance(data, dict):
            continue
        buildings = data.get("ProductionBuilding") or []
        building = buildings[0] if buildings else None
        category = _category_from_building(building)
        if category is None:
            continue
        housing = _first_int(data.get("HousingSpace"))
        if housing is None:
            continue
        unit_id = _slug(name)
        units[unit_id] = {
            "name": name,
            "category": category,
            "housing": housing,
            "source": "characters.json",
        }
    return units


def parse_supers(supers: dict) -> dict[str, dict]:
    units: dict[str, dict] = {}
    for name, data in supers.items():
        if not isinstance(data, dict):
            continue
        housing = _first_int(data.get("HousingSpace"))
        if housing is None:
            continue
        unit_id = _slug(name)
        if unit_id.startswith("super_"):
            pass
        elif not unit_id.startswith("super"):
            unit_id = f"super_{unit_id}"
        units[unit_id] = {
            "name": name,
            "category": "troop",
            "housing": housing,
            "source": "supers.json",
        }
    return units


def load_spell_seed() -> dict[str, dict]:
    if not SPELL_SEED.exists():
        return {}
    with open(SPELL_SEED, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    spells = raw.get("spells", {})
    out: dict[str, dict] = {}
    for unit_id, info in spells.items():
        out[unit_id] = {
            "name": info["name"],
            "category": info.get("category", "spell"),
            "housing": int(info["housing"]),
            "source": "game_spells_seed.yaml",
        }
    return out


def merge_units(*parts: dict[str, dict]) -> dict[str, dict]:
    merged: dict[str, dict] = {}
    for part in parts:
        merged.update(part)
    return merged


def sync(force: bool = False) -> int:
    if OUT_PATH.exists() and not force:
        print(f"Output exists: {OUT_PATH}")
        print("Use --force to overwrite.")

    units: dict[str, dict] = {}
    errors: list[str] = []

    for label, url in SOURCES.items():
        try:
            print(f"Fetching {label}: {url}")
            payload = fetch_json(url)
            if label == "characters":
                units = merge_units(units, parse_characters(payload))
            elif label == "supers":
                units = merge_units(units, parse_supers(payload))
            print(f"  OK ({len(payload)} entries raw)")
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            msg = f"Failed {label} from {url}: {exc}"
            print(f"  ERROR: {msg}", file=sys.stderr)
            errors.append(msg)

    units = merge_units(units, load_spell_seed())

    if not units:
        print("No unit data collected — leaving existing file unchanged.", file=sys.stderr)
        return 1

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sources": list(SOURCES.values()) + [str(SPELL_SEED.relative_to(ROOT))],
        "note": "Siege donation uses count limits, not housing. housing=1 in game files.",
        "units": dict(sorted(units.items())),
    }
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(payload, f, default_flow_style=False, sort_keys=False)

    troops = sum(1 for u in units.values() if u["category"] == "troop")
    spells = sum(1 for u in units.values() if u["category"] == "spell")
    siege = sum(1 for u in units.values() if u["category"] == "siege")
    print(f"Wrote {len(units)} units -> {OUT_PATH}")
    print(f"  troops={troops} spells={spells} siege={siege}")
    if errors:
        print(f"Completed with {len(errors)} download warning(s).", file=sys.stderr)
    return 0 if not errors else 2


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync CoC unit housing data into data/game/units.yaml")
    parser.add_argument("--force", action="store_true", help="Overwrite existing units.yaml")
    args = parser.parse_args()
    raise SystemExit(sync(force=args.force))


if __name__ == "__main__":
    main()
