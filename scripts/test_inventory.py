#!/usr/bin/env python3
"""Diagnose donation-panel slot detection (open the panel before running)."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from coc_bot.adb.capture import ScreenCapture
from coc_bot.adb.client import AdbClient
from coc_bot.config import load_config
from coc_bot.donation.inventory import InventoryParser
from coc_bot.vision.matcher import TemplateMatcher
from coc_bot.vision.screens import ScreenClassifier


def main() -> None:
    config = load_config()
    if not config.calibrated:
        print("Run calibration first.")
        sys.exit(1)

    client = AdbClient(device=config.adb_device)
    client.ensure_connected()
    capture = ScreenCapture(client)
    matcher = TemplateMatcher(threshold=config.template_threshold)
    classifier = ScreenClassifier(config, matcher)
    inventory = InventoryParser(config, matcher)

    print("Open a donation request panel (tap Donate), then continue.")
    print("(Requested troops are read from clan chat, not this panel — this tests slot detection only.)")
    input("Press Enter to capture and analyze...")

    frame = capture.screenshot()
    screen = classifier.classify(frame)
    print(f"\nScreen: {screen.value}")
    if screen.value != "donation_panel":
        print("WARNING: donation panel not detected — results may be wrong.")

    slots_open = inventory.parse_slots(frame, require_unit_id=False)
    slots_specific = inventory.parse_slots(frame, require_unit_id=False, stop_at_grey=True)

    print(f"\nColored slots (open request — full visible grid): {len(slots_open)}")
    for slot in slots_open:
        print(f"  - {slot.unit_id} x{slot.quantity} @ {slot.center} ({slot.category})")

    print(f"\nColored slots (specific request — until first grey): {len(slots_specific)}")
    for slot in slots_specific:
        print(f"  - {slot.unit_id} x{slot.quantity} @ {slot.center} ({slot.category})")

    print("\nCalibration checklist:")
    print(f"  donation_troop_bar ROI: {'yes' if 'donation_troop_bar' in config.rois else 'NO'}")
    print(f"  donation_spell_bar ROI: {'yes' if 'donation_spell_bar' in config.rois else 'NO'}")
    print(f"  colored troop sample: {'yes' if config.colors.get('donatable_troop') else 'NO'}")
    print(f"  grey troop sample: {'yes' if config.colors.get('disabled_troop') else 'NO'}")
    print(f"  colored spell sample: {'yes' if config.colors.get('donatable_spell') else 'NO'}")
    print(f"  grey spell sample: {'yes' if config.colors.get('disabled_spell') else 'NO'}")
    print(f"  unit templates: {len(config.unit_templates)}")
    grid = config.grid or {}
    troop = grid.get("troop_bar", {})
    spell = grid.get("spell_bar", {})
    print(f"  visible troop grid: {troop.get('cols', '?')} cols x {troop.get('rows', '?')} rows")
    print(f"  visible spell grid: {spell.get('cols', '?')} cols x {spell.get('rows', '?')} rows")

    if not slots_open:
        print("\nNo colored slots found — run:")
        print("  python scripts/calibrate.py --step donation_panel")
        print("  python scripts/calibrate.py --step slot_colors")
        print("  python scripts/calibrate.py --step grid")
        sys.exit(1)

    print("\nColored slot detection looks OK for the current bar view.")


if __name__ == "__main__":
    main()
