from __future__ import annotations

import random
import time
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from coc_bot.config import BotConfig
from coc_bot.runtime.persistence import RuntimeState, load_runtime_state, save_runtime_state


def roll_farm_interval_seconds(base: int, variance: int) -> int:
    """Pick a wait in [base-variance, base+variance], never below 60s."""
    base = max(60, int(base))
    variance = max(0, int(variance))
    if variance <= 0:
        return base
    lo = max(60, base - variance)
    hi = base + variance
    if hi < lo:
        return lo
    return random.randint(lo, hi)


class RuntimeTracker:
    """Track active donation-loop runtime with persisted state."""

    def __init__(self, config: BotConfig, state_path: Path | None = None) -> None:
        self.config = config
        self.state_path = state_path or config.data_dir / "runtime_state.json"
        self.state = load_runtime_state(self.state_path)
        self._loop_start: float | None = None
        self._paused = False

    @property
    def active_seconds(self) -> float:
        return self.state.active_seconds

    @property
    def limit_reached(self) -> bool:
        return self.state.active_seconds >= self.config.session_limit_seconds

    def start_loop_timing(self) -> None:
        if self._loop_start is None:
            self._loop_start = time.monotonic()

    def pause(self) -> None:
        self._flush()
        self._paused = True
        self._loop_start = None

    def resume(self) -> None:
        self._paused = False
        self._loop_start = time.monotonic()

    def _flush(self) -> None:
        if self._loop_start is None or self._paused:
            return
        elapsed = time.monotonic() - self._loop_start
        self.state.active_seconds += elapsed
        self._loop_start = time.monotonic()
        save_runtime_state(self.state_path, self.state)

    def tick(self) -> None:
        self._flush()

    def reset_after_break(self, break_seconds: int) -> None:
        self._flush()
        self.state.active_seconds = 0.0
        self.state.last_break_seconds = break_seconds
        self.state.cycle_count += 1
        self.state.break_until = None
        save_runtime_state(self.state_path, self.state)
        self._loop_start = time.monotonic()
        logger.info(
            "Runtime reset after break ({}s). Cycle count: {}",
            break_seconds,
            self.state.cycle_count,
        )

    def set_break_until(self, iso_timestamp: str, break_seconds: int | None = None) -> None:
        self.state.break_until = iso_timestamp
        if break_seconds is not None:
            self.state.last_break_seconds = break_seconds
        save_runtime_state(self.state_path, self.state)

    def remaining_seconds(self) -> float:
        self._flush()
        return max(0.0, self.config.session_limit_seconds - self.state.active_seconds)

    def last_farm_at(self) -> datetime | None:
        raw = self.state.last_farm_at
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None

    def mark_farm_success(self) -> None:
        """Record that a farm battle was fought (success or post-deploy leave fail)."""
        self.state.last_farm_at = datetime.now(timezone.utc).isoformat()
        rolled = self._roll_next_farm_interval()
        self.state.next_farm_interval_seconds = rolled
        save_runtime_state(self.state_path, self.state)
        base = max(60, int(self.config.farm_interval_seconds))
        variance = max(0, int(self.config.farm_interval_variance_seconds))
        logger.info(
            "Recorded farm interval clock at {} — next wait {}s (base {}s ± {}s)",
            self.state.last_farm_at,
            rolled,
            base,
            variance,
        )

    def _roll_next_farm_interval(self) -> int:
        return roll_farm_interval_seconds(
            self.config.farm_interval_seconds,
            self.config.farm_interval_variance_seconds,
        )

    def effective_farm_interval_seconds(self) -> int:
        """
        Wait used for the current auto-farm countdown.

        Persists a rolled value so status text and due-checks stay aligned until
        the next fought farm re-rolls it.
        """
        stored = self.state.next_farm_interval_seconds
        if stored is not None and int(stored) >= 60:
            return int(stored)
        rolled = self._roll_next_farm_interval()
        self.state.next_farm_interval_seconds = rolled
        save_runtime_state(self.state_path, self.state)
        logger.debug(
            "Rolled farm interval target {}s (base {} ± {})",
            rolled,
            max(60, int(self.config.farm_interval_seconds)),
            max(0, int(self.config.farm_interval_variance_seconds)),
        )
        return rolled

    def seconds_since_last_farm(self) -> float | None:
        """Seconds since last fought farm battle, or None if never farmed."""
        last = self.last_farm_at()
        if last is None:
            return None
        now = datetime.now(timezone.utc)
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        return max(0.0, (now - last).total_seconds())
