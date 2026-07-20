#!/usr/bin/env python3
"""Run the bot in dry-run (detect-only) mode."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from coc_bot.main import main

if __name__ == "__main__":
    sys.argv.extend(["--dry-run", "--debug-save-frames"])
    main()
