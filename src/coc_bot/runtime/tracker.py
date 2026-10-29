from __future__ import annotations

import random
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from coc_bot.config import BotConfig
from coc_bot.runtime.persistence import load_runtime_state, save_runtime_state


def roll_session_limit_seconds(base: int, variance: int) -> int:
    """Pick a session length in [base-variance, base+variance], never below 60s."""
    base = max(60, int(base))
    variance = max(0, int(variance))
    if variance <= 0:
        return base
    lo = max(60, base - variance)
    hi = base + variance
    if hi < lo:
        return lo
    return random.randint(lo, hi)


def format_duration_short(seconds: float) -> str:
    """Compact countdown like 2h 15m / 12m 5s / 40s."""
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def break_status_line(tracker: RuntimeTracker) -> str:
    """Short Home-tab line for time until the next session break."""
    state = tracker.state
    if state.break_until:
        try:
            until = datetime.fromisoformat(state.break_until)
        except ValueError:
            until = None
        if until is not None:
            now = datetime.now(timezone.utc)
            if until.tzinfo is None:
                until = until.replace(tzinfo=timezone.utc)
            left = (until - now).total_seconds()
            if left > 0:
                return f"Break: in progress — resumes in {format_duration_short(left)}"
    remaining = tracker.peek_remaining_seconds()
    if remaining <= 0:
        return "Break: due on next check"
    return f"Break: next in {format_duration_short(remaining)}"


class RuntimeTracker:
    """Track active donation-loop runtime with persisted state."""

    def __init__(self, config: BotConfig, state_path: Path | None = None) -> None:
        self.config = config
        self.state_path = state_path or config.data_dir / "runtime_state.json"
        self.state = load_runtime_state(self.state_path)
        self._loop_start: float | None = None
        self._paused = False
        # The bot loop ticks this tracker while the GUI thread polls it for
        # countdown text; every read-modify-write on ``state`` goes through here.
        self._lock = threading.RLock()

    @property
    def active_seconds(self) -> float:
        return self.state.active_seconds

    @property
    def limit_reached(self) -> bool:
        with self._lock:
            return self.state.active_seconds >= self.effective_session_limit_seconds()

    def start_loop_timing(self) -> None:
        with self._lock:
            if self._loop_start is None:
                self._loop_start = time.monotonic()

    def pause(self) -> None:
        with self._lock:
            self._flush()
            self._paused = True
            self._loop_start = None

    def resume(self) -> None:
        with self._lock:
            self._paused = False
            self._loop_start = time.monotonic()

    def _flush(self) -> None:
        with self._lock:
            if self._loop_start is None or self._paused:
                return
            now = time.monotonic()
            elapsed = now - self._loop_start
            self.state.active_seconds += elapsed
            self._loop_start = now
            save_runtime_state(self.state_path, self.state)

    def tick(self) -> None:
        self._flush()

    def reset_after_break(self, break_seconds: int) -> None:
        with self._lock:
            self._flush()
            self.state.active_seconds = 0.0
            self.state.last_break_seconds = break_seconds
            self.state.cycle_count += 1
            self.state.break_until = None
            rolled = self._roll_next_session_limit()
            self.state.next_session_limit_seconds = rolled
            save_runtime_state(self.state_path, self.state)
            self._loop_start = time.monotonic()
        base = max(60, int(self.config.session_limit_seconds))
        variance = max(0, int(self.config.session_limit_variance_seconds))
        logger.info(
            "Runtime reset after break ({}s). Cycle count: {}. Next session limit {}s "
            "(base {}s ± {}s)",
            break_seconds,
            self.state.cycle_count,
            rolled,
            base,
            variance,
        )

    def set_break_until(self, iso_timestamp: str, break_seconds: int | None = None) -> None:
        with self._lock:
            self.state.break_until = iso_timestamp
            if break_seconds is not None:
                self.state.last_break_seconds = break_seconds
            save_runtime_state(self.state_path, self.state)

    def _roll_next_session_limit(self) -> int:
        return roll_session_limit_seconds(
            self.config.session_limit_seconds,
            self.config.session_limit_variance_seconds,
        )

    def effective_session_limit_seconds(self) -> int:
        """
        Session length used for the current run before a forced break.

        Persists a rolled value so status and limit checks stay aligned until
        the next break re-rolls it.
        """
        with self._lock:
            stored = self.state.next_session_limit_seconds
            if stored is not None and int(stored) >= 60:
                return int(stored)
            rolled = self._roll_next_session_limit()
            self.state.next_session_limit_seconds = rolled
            save_runtime_state(self.state_path, self.state)
            logger.debug(
                "Rolled session limit target {}s (base {} ± {})",
                rolled,
                max(60, int(self.config.session_limit_seconds)),
                max(0, int(self.config.session_limit_variance_seconds)),
            )
            return rolled

    def remaining_seconds(self) -> float:
        """Flush elapsed loop time to disk, then return seconds until the session limit."""
        with self._lock:
            self._flush()
            return max(0.0, self.effective_session_limit_seconds() - self.state.active_seconds)

    def peek_remaining_seconds(self) -> float:
        """
        Read-only variant for status displays (GUI thread).

        Accounts for un-flushed loop time without mutating ``state`` or writing
        the state file, so it is safe to call while the bot thread is ticking.
        """
        with self._lock:
            active = self.state.active_seconds
            if self._loop_start is not None and not self._paused:
                active += time.monotonic() - self._loop_start
            return max(0.0, self.effective_session_limit_seconds() - active)


    def mark_farm_success(self, *, attack_id=None) -> None:
        """Record that a farm battle was fought (success or post-deploy leave fail)."""
        with self._lock:
            if attack_id and self.state.last_completed_attack_id == attack_id:
                return
            previous=(self.state.last_farm_at,self.state.farm_paused_at,
                      self.state.next_farm_interval_seconds,self.state.last_completed_attack_id)
            self.state.last_farm_at = datetime.now(timezone.utc).isoformat()
            self.state.farm_paused_at = None
            self.state.next_farm_interval_seconds = None
            if attack_id:
                from dataclasses import asdict
                from coc_bot.attack.recovery import atomic_json
                self.state.last_completed_attack_id = attack_id
                try:
                    atomic_json(self.state_path, asdict(self.state))
                except OSError:
                    (self.state.last_farm_at,self.state.farm_paused_at,
                     self.state.next_farm_interval_seconds,self.state.last_completed_attack_id)=previous
                    raise
            else:
                save_runtime_state(self.state_path, self.state)
        # Legacy interval fields remain readable for old state files. Normal
        # automation schedules its next attack from verified storage demand.
        logger.info("Recorded farm completion at {} — refill follows resource levels", self.state.last_farm_at)
