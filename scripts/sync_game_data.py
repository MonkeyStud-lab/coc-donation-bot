#!/usr/bin/env python3
"""
Download troop/siege housing space and merge spell seed data into data/game/units.yaml.
Optionally download unit icons from ClashKing CDN into data/icons/.

NOTE: The coc.guide *website* may redirect-loop in a browser. These direct static
JSON URLs work from curl/Python (no homepage visit needed):

  https://coc.guide/static/json/characters.json
  https://coc.guide/static/json/supers.json

Icon CDN (ClashKingAssets):
  https://assets.clashk.ing/troops/{unit_id}/icon.webp
  https://assets.clashk.ing/spells/{unit_id}.webp

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
ICONS_DIR = ROOT / "data" / "icons"
SPELL_SEED = ROOT / "config" / "game_spells_seed.yaml"

# Direct static paths only — do not use https://coc.guide/ (homepage redirects).
SOURCES = {
    "characters": "https://coc.guide/static/json/characters.json",
    "supers": "https://coc.guide/static/json/supers.json",
}

ASSETS_BASE = "https://assets.clashk.ing"

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


def fetch_bytes(url: str, timeout: float = 30.0) -> bytes | None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if getattr(resp, "status", 200) >= 400:
                return None
            return resp.read()
    except (urllib.error.URLError, TimeoutError):
        return None


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


def load_units_yaml() -> dict[str, dict]:
    if not OUT_PATH.exists():
        return {}
    with open(OUT_PATH, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return raw.get("units") or {}


def icon_urls_for(unit_id: str, category: str) -> list[str]:
    """Candidate CDN URLs for a unit icon (first hit wins)."""
    urls: list[str] = []
    if category == "spell":
        urls.append(f"{ASSETS_BASE}/spells/{unit_id}.webp")
        if unit_id.endswith("_spell"):
            urls.append(f"{ASSETS_BASE}/spells/{unit_id.removesuffix('_spell')}.webp")
    else:
        # Troops and siege machines live under /troops/{id}/icon.webp
        urls.append(f"{ASSETS_BASE}/troops/{unit_id}/icon.webp")
    return urls


def sync_icons(units: dict[str, dict], *, force: bool = False) -> int:
    """Download icons for known units into data/icons/{category}/{unit_id}.webp."""
    if not units:
        units = load_units_yaml()
    if not units:
        print("No units available for icon sync.", file=sys.stderr)
        return 1

    downloaded = 0
    skipped = 0
    missing = 0
    for unit_id, info in sorted(units.items()):
        category = str(info.get("category", "troop"))
        out_dir = ICONS_DIR / ("spells" if category == "spell" else "troops")
        out_path = out_dir / f"{unit_id}.webp"
        if out_path.exists() and not force:
            skipped += 1
            continue
        data = None
        for url in icon_urls_for(unit_id, category):
            data = fetch_bytes(url)
            if data:
                break
        if not data:
            missing += 1
            continue
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(data)
        downloaded += 1
        print(f"  icon {unit_id} -> {out_path.relative_to(ROOT)}")

    print(f"Icons: downloaded={downloaded} skipped={skipped} missing={missing} -> {ICONS_DIR}")
    return 0 if downloaded or skipped else 1


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
    parser = argparse.ArgumentParser(
        description="Sync CoC unit housing data and optional icons"
    )
    parser.add_argument("--force", action="store_true", help="Overwrite existing units.yaml / icons")
    parser.add_argument(
        "--icons",
        action="store_true",
        help="Download unit icons from ClashKing CDN into data/icons/",
    )
    parser.add_argument(
        "--icons-only",
        action="store_true",
        help="Only download icons (uses existing units.yaml)",
    )
    args = parser.parse_args()

    if args.icons_only:
        raise SystemExit(sync_icons({}, force=args.force))

    code = sync(force=args.force)
    if args.icons:
        units = load_units_yaml()
        icon_code = sync_icons(units, force=args.force)
        if code == 0:
            code = icon_code
    raise SystemExit(code)


if __name__ == "__main__":
    main()
