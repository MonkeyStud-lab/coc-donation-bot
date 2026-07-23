#!/usr/bin/env python3
"""Run the calibration wizard (thin wrapper around the package CLI)."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from coc_bot.calibration.wizard import main

if __name__ == "__main__":
    main()
