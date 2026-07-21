#!/usr/bin/env python3
"""Run the calibration wizard (full, menu, or single steps)."""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from coc_bot.calibration.wizard import STEP_IDS, CalibrationWizard, print_step_menu


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Calibrate CoC donation bot (full run or individual steps)",
    )
    parser.add_argument(
        "--step",
        action="append",
        dest="steps",
        choices=STEP_IDS,
        metavar="STEP",
        help=f"Run one step only (repeatable). Choices: {', '.join(STEP_IDS)}",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run all steps in order (same as legacy full calibration)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List steps and whether each appears configured",
    )
    args = parser.parse_args()

    wizard = CalibrationWizard()

    if args.list:
        print_step_menu(wizard.step_status())
        return

    if args.steps:
        wizard.run_steps(args.steps)
        return

    if args.all:
        wizard.run_steps(STEP_IDS)
        return

    # Interactive menu
    wizard.run_interactive()


if __name__ == "__main__":
    main()
