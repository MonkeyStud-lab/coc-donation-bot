#!/usr/bin/env python3
"""
Offline / live dry-run for Phase 2 fill planning.

Usage:
  # Synthetic budget check (no ADB / EasyOCR):
  python scripts/test_fill_plan.py

  # Live: OCR capacity from clan chat + plan from current panel (open Donate first):
  python scripts/test_fill_plan.py --live

  # Offline screenshot of clan chat with Donate button visible:
  python scripts/test_fill_plan.py --chat-image path/to/chat.png
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from coc_bot.config import DonationLimits, load_config
from coc_bot.donation.capacity_parser import RequestCapacity, RequestCapacityParser
from coc_bot.donation.fill_planner import FillPlanner
from coc_bot.donation.inventory import InventoryParser, InventorySlot
from coc_bot.donation.request_parser import RequestParser
from coc_bot.vision.matcher import MatchResult, TemplateMatcher


def _synthetic_check() -> int:
    planner = FillPlanner()
    capacity = RequestCapacity(
        troop_remaining=35,
        troop_total=35,
        spell_remaining=1,
        spell_total=1,
        siege_remaining=1,
        siege_total=1,
    )
    donor = DonationLimits(troop_housing=40, spell_housing=4, siege_count=2)
    tb, sb, gb = planner.initial_budgets(capacity, donor)
    print(f"Budgets for Think-a-Little style open request (clan L8 caps 40/4/2):")
    print(f"  troop={tb} (min(35,40)) spell={sb} siege={gb}")
    assert tb == 35 and sb == 1 and gb == 1

    slots = [
        InventorySlot("yeti", 1, (100, 100), "troop"),
        InventorySlot("wizard", 1, (150, 100), "troop"),
        InventorySlot("barbarian", 1, (200, 100), "troop"),
        InventorySlot("log_launcher", 1, (900, 100), "siege"),
        InventorySlot("rage_spell", 1, (100, 200), "spell"),
    ]
    # Smaller clan perk to prove capping.
    tight = DonationLimits(troop_housing=20, spell_housing=2, siege_count=1)
    plan = planner.plan(slots, capacity=capacity, donor_limits=tight)
    print(f"\nGreedy plan under troop_housing=20:")
    for tap in plan.taps:
        print(f"  - {tap.unit_id} ({tap.category}) cost={tap.cost} @ {tap.center}")
    print(f"  remaining troop={plan.troop_budget} spell={plan.spell_budget} siege={plan.siege_budget}")

    used_troop = 20 - plan.troop_budget
    assert used_troop <= 20
    assert plan.siege_budget == 0  # donated 1 siege
    # Yeti(18) should be preferred over wizard(4)/barb(1) when it fits.
    troop_taps = [t for t in plan.taps if t.category == "troop"]
    assert troop_taps and troop_taps[0].unit_id == "yeti"
    print("\nSynthetic fill-plan checks OK.")
    return 0


def _classify_offline(image_path: Path) -> int:
    import cv2

    config = load_config()
    frame = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if frame is None:
        print(f"Could not read image: {image_path}")
        return 1

    matcher = TemplateMatcher(threshold=config.donate_button_threshold)
    template_rel = config.templates.get("donate_button")
    if not template_rel:
        print("donate_button template not calibrated — pass --donate-xy x,y")
        return 1
    template = cv2.imread(str(config.templates_dir / template_rel), cv2.IMREAD_COLOR)
    match = matcher.find(frame, template, threshold=config.donate_button_threshold)
    if match is None and "chat_requests" in config.rois:
        from coc_bot.vision.rois import crop_roi, denormalize_roi, ROI

        h, w = frame.shape[:2]
        search = crop_roi(frame, config.rois["chat_requests"])
        local = matcher.find(search, template, threshold=config.donate_button_threshold)
        if local is not None:
            ox, oy, _, _ = denormalize_roi(ROI(*config.rois["chat_requests"]), w, h)
            match = MatchResult(
                x=local.x + ox,
                y=local.y + oy,
                confidence=local.confidence,
                width=local.width,
                height=local.height,
            )
    if match is None:
        print("Donate button not found in image")
        return 1

    capacity = RequestCapacityParser(config).parse(frame, match)
    kind = RequestParser(config, debug=True).classify(frame, match, capacity)
    print(f"Donate @ {match.center} conf={match.confidence:.2f}")
    print(f"Kind: {kind.value}")
    if capacity is None:
        print("Capacity: OCR failed / incomplete")
    else:
        print(
            f"Capacity: troops={capacity.troop_remaining}/{capacity.troop_total} "
            f"spells={capacity.spell_remaining}/{capacity.spell_total} "
            f"siege={capacity.siege_remaining}/{capacity.siege_total}"
        )
        donor = config.donor_limits()
        tb, sb, gb = FillPlanner().initial_budgets(capacity, donor)
        print(f"Budgets (clan L{config.clan_level}): troop={tb} spell={sb} siege={gb}")
    return 0


def _live() -> int:
    from coc_bot.adb.capture import ScreenCapture
    from coc_bot.adb.client import AdbClient
    from coc_bot.vision.screens import ScreenClassifier

    config = load_config()
    if not config.calibrated:
        print("Run calibration first.")
        return 1

    client = AdbClient(device=config.adb_device)
    client.ensure_connected()
    capture = ScreenCapture(client)
    matcher = TemplateMatcher(threshold=config.template_threshold)
    classifier = ScreenClassifier(config, matcher)
    inventory = InventoryParser(config, matcher=matcher)
    planner = FillPlanner()

    print("Leave clan chat visible. Prefer ONLY an open request on screen")
    print("(e.g. Think a Little) — the bot reads the bottom-most Donate button.")
    print("Move the terminal off the chat panel if it covers Donate.")
    input("Press Enter to capture...")

    frame = capture.screenshot()
    screen = classifier.classify(frame)
    print(f"Screen: {screen.value}")

    if screen.value == "donation_panel":
        slots = inventory.parse_slots(frame, identify=True)
        print(f"Identified slots: {len(slots)}")
        for slot in slots:
            print(f"  - {slot.unit_id} ({slot.category}) @ {slot.center}")
        # Assume open request needing full clan perk if no chat OCR.
        capacity = RequestCapacity(35, 35, 1, 1, 1, 1)
        plan = planner.plan(slots, capacity=capacity, donor_limits=config.donor_limits())
        print(f"\nFill plan ({len(plan.taps)} taps):")
        for tap in plan.taps:
            print(f"  - {tap.unit_id} ({tap.category}) cost={tap.cost}")
        print(
            f"Remaining budgets troop={plan.troop_budget} "
            f"spell={plan.spell_budget} siege={plan.siege_budget}"
        )
        return 0

    # Clan chat — try capacity + classify via ChatMonitor path.
    from coc_bot.adb.input import InputController
    from coc_bot.donation.chat_monitor import ChatMonitor

    monitor = ChatMonitor(config, capture, InputController(client, dry_run=True), matcher, debug=True)
    request = monitor.find_donate_request(frame)
    if request is None:
        print("No Donate request found")
        return 1
    print(f"Request kind={request.kind.value} specific={request.is_specific}")
    if request.capacity:
        c = request.capacity
        print(
            f"Capacity (remaining/total) troops={c.troop_remaining}/{c.troop_total} "
            f"spells={c.spell_remaining}/{c.spell_total} "
            f"siege={c.siege_remaining}/{c.siege_total}"
        )
        tb, sb, gb = planner.initial_budgets(c, config.donor_limits())
        print(f"Fill budgets (clan L{config.clan_level}): troop={tb} spell={sb} siege={gb}")
    else:
        print("Capacity OCR returned None")
        # Save crop for debugging OCR.
        debug_dir = config.data_dir / "debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        import cv2

        path = debug_dir / "capacity_ocr_fail.png"
        cv2.imwrite(str(path), frame)
        print(f"Saved full frame to {path} for debugging")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 2 fill-plan dry-run / verification")
    parser.add_argument("--live", action="store_true", help="Capture from ADB device")
    parser.add_argument("--chat-image", type=Path, help="Offline clan-chat screenshot")
    args = parser.parse_args()

    if args.live:
        raise SystemExit(_live())
    if args.chat_image:
        raise SystemExit(_classify_offline(args.chat_image))
    raise SystemExit(_synthetic_check())


if __name__ == "__main__":
    main()
