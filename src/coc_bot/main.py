"""CLI entrypoint — keep imports light so the GUI splash can appear quickly."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from coc_bot.logging_utils import setup_logging


def __getattr__(name: str) -> Any:
    """Lazy re-export so ``from coc_bot.main import DonationBot`` still works."""
    if name == "DonationBot":
        from coc_bot.bot import DonationBot

        return DonationBot
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description="CoC Donation Bot (educational)")
    parser.add_argument("--dry-run", action="store_true", help="Skip donate taps; navigation still runs")
    parser.add_argument("--debug-save-frames", action="store_true", help="Save debug screenshots")
    parser.add_argument("--debug", action="store_true", help="Verbose logging")
    parser.add_argument(
        "--no-gui",
        action="store_true",
        help="Run the bot in the terminal only (no control window)",
    )
    parser.add_argument(
        "--record",
        action="store_true",
        help="Record screenshots + classifier verdicts to data/frames/<session>/ "
        "for perception training (see vision/recorder.py)",
    )
    parser.add_argument(
        "--record-every",
        type=int,
        default=10,
        metavar="N",
        help="With --record: also save every Nth frame (unknown/screen-change frames "
        "are always saved). Default 10.",
    )
    args = parser.parse_args()

    setup_logging(debug=args.debug, log_file=Path("data") / "bot.log")

    if args.no_gui:
        from loguru import logger

        from coc_bot.adb.client import AdbError
        from coc_bot.bot import DonationBot

        bot = DonationBot(
            dry_run=args.dry_run,
            debug_save_frames=args.debug_save_frames,
            debug=args.debug,
            record=args.record,
            record_every=args.record_every,
        )
        try:
            bot.run()
        except (AdbError, RuntimeError) as exc:
            logger.error("{}", exc)
            sys.exit(1)
        return

    from coc_bot.gui.bootstrap import run_gui

    run_gui(
        dry_run=args.dry_run,
        debug_save_frames=args.debug_save_frames,
        debug=args.debug,
        record=args.record,
        record_every=args.record_every,
    )


if __name__ == "__main__":
    main()
