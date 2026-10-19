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
import hashlib
import json
import os
import re
import sys
import tempfile
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
MAX_ICON_BYTES = 3 * 1024 * 1024
CORE_ICONS = {"troops/electro_dragon.webp", "spells/rage_spell.webp"}


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
            data = resp.read(MAX_ICON_BYTES + 1)
            return data if len(data) <= MAX_ICON_BYTES else None
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


def valid_icon(data: bytes) -> bool:
    """Only decodable alpha-masked artwork can seed the army catalog."""
    import cv2
    import numpy as np

    if not data or len(data) > MAX_ICON_BYTES:
        return False
    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)
    return bool(image is not None and image.ndim == 3 and image.shape[2] == 4
                and 16 <= min(image.shape[:2]) <= max(image.shape[:2]) <= 2048
                and np.count_nonzero(image[:, :, 3] > 100) >= 100)


def write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        # These are public reference assets, built as root but read by the
        # unprivileged app user. Keep private profile backups restricted elsewhere.
        os.chmod(name, 0o644)
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def sync_icons(units: dict[str, dict], *, force: bool = False,
               require_core: bool = False) -> int:
    """Download icons for known units into data/icons/{category}/{unit_id}.webp."""
    if not units:
        units = load_units_yaml()
    if not units:
        print("No units available for icon sync.", file=sys.stderr)
        return 1

    downloaded = 0
    skipped = 0
    missing = 0
    manifest = {}
    for unit_id, info in sorted(units.items()):
        category = str(info.get("category", "troop"))
        if not re.fullmatch(r"[a-z0-9_]+", unit_id) or category not in ("troop", "siege", "spell"):
            raise ValueError("Invalid icon identity or category")
        out_dir = ICONS_DIR / ("spells" if category == "spell" else "troops")
        out_path = out_dir / f"{unit_id}.webp"
        key = out_path.relative_to(ICONS_DIR).as_posix()
        if out_path.is_file() and not force and valid_icon(out_path.read_bytes()):
            skipped += 1
            manifest[key] = hashlib.sha256(out_path.read_bytes()).hexdigest()
            continue
        data = None
        for url in icon_urls_for(unit_id, category):
            data = fetch_bytes(url)
            if data and valid_icon(data):
                break
            data = None
        if data is None:
            missing += 1
            continue
        write_atomic(out_path, data)
        manifest[key] = hashlib.sha256(data).hexdigest()
        downloaded += 1
        print(f"  icon {unit_id} -> {out_path.relative_to(ROOT)}")

    print(f"Icons: downloaded={downloaded} skipped={skipped} missing={missing} -> {ICONS_DIR}")
    write_atomic(ICONS_DIR / "manifest.json", json.dumps({
        "source": ASSETS_BASE, "files": manifest,
        "missing_core": sorted(CORE_ICONS - manifest.keys()),
    }, indent=2).encode("utf-8"))
    if require_core and CORE_ICONS - manifest.keys():
        print("Required automatic-attack artwork is unavailable: " +
              ", ".join(sorted(CORE_ICONS - manifest.keys())), file=sys.stderr)
        return 1
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
    parser.add_argument("--require-core-icons", action="store_true",
                        help="Fail when Electro Dragon or Rage artwork is missing/invalid")
    args = parser.parse_args()

    if args.icons_only:
        raise SystemExit(sync_icons({}, force=args.force, require_core=args.require_core_icons))

    code = sync(force=args.force)
    if args.icons:
        units = load_units_yaml()
        icon_code = sync_icons(units, force=args.force, require_core=args.require_core_icons)
        if code == 0:
            code = icon_code
    raise SystemExit(code)


if __name__ == "__main__":
    main()
