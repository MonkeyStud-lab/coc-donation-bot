from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger


def setup_logging(debug: bool = False, log_file: Path | None = None) -> None:
    logger.remove()
    level = "DEBUG" if debug else "INFO"
    logger.add(sys.stderr, level=level, format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {message}")
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        logger.add(log_file, level=level, rotation="10 MB", retention="7 days")
