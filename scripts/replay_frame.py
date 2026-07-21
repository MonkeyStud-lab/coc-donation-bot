#!/usr/bin/env python3
"""Offline vision testing against a saved screenshot."""

import argparse
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from coc_bot.config import load_config
from coc_bot.donation.inventory import InventoryParser
from coc_bot.donation.request_parser import RequestParser
from coc_bot.vision.matcher import MatchResult, TemplateMatcher
from coc_bot.vision.screens import ScreenClassifier


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay vision pipeline on a saved frame")
    parser.add_argument("image", type=Path, help="Path to PNG/JPG screenshot")
    parser.add_argument("--annotate", action="store_true", help="Save annotated output")
    args = parser.parse_args()

    config = load_config()
    frame = cv2.imread(str(args.image))
    if frame is None:
        print(f"Failed to load: {args.image}")
        sys.exit(1)

    matcher = TemplateMatcher(threshold=config.template_threshold)
    classifier = ScreenClassifier(config, matcher)
    screen = classifier.classify(frame)
    print(f"Screen: {screen.value}")

    req_parser = RequestParser(config)
    inv_parser = InventoryParser(config)
    inventory = inv_parser.parse(frame)
    print(f"Colored inventory slots ({len(inventory)} positions):")
    for unit_id, qty in inventory.items():
        print(f"  - {unit_id}: {qty}")

    donate_tpl = config.templates.get("donate_button")
    if donate_tpl:
        path = config.templates_dir / donate_tpl
        if path.exists():
            template = cv2.imread(str(path))
            match = matcher.find(frame, template, threshold=config.donate_button_threshold)
            if match:
                print(f"Donate button: ({match.center[0]}, {match.center[1]}) conf={match.confidence:.2f}")
                adjusted = MatchResult(
                    x=match.x,
                    y=match.y,
                    confidence=match.confidence,
                    width=match.width,
                    height=match.height,
                )
                is_specific = req_parser.has_requested_icons_in_chat(frame, adjusted)
                print(f"Specific request icons in chat: {is_specific}")
                if args.annotate:
                    cv2.rectangle(
                        frame,
                        (match.x, match.y),
                        (match.x + match.width, match.y + match.height),
                        (0, 255, 0),
                        2,
                    )

    if args.annotate:
        out = args.image.with_stem(args.image.stem + "_annotated")
        cv2.imwrite(str(out), frame)
        print(f"Saved: {out}")


if __name__ == "__main__":
    main()
