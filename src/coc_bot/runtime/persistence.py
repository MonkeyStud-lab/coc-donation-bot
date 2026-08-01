from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class RuntimeState:
    session_started_at: str
    active_seconds: float
    last_break_seconds: int
    cycle_count: int
    break_until: str | None = None
    last_farm_at: str | None = None  # UTC ISO timestamp of last successful farm
    # Rolled wait until the next auto farm (base interval ± variance); None = roll on read.
    next_farm_interval_seconds: int | None = None
    # Rolled session length before break (base limit ± variance); None = roll on read.
    next_session_limit_seconds: int | None = None

    @classmethod
    def fresh(cls) -> RuntimeState:
        now = datetime.now(timezone.utc).isoformat()
        return cls(session_started_at=now, active_seconds=0.0, last_break_seconds=0, cycle_count=0)

    @classmethod
    def from_dict(cls, data: dict) -> RuntimeState:
        raw_next = data.get("next_farm_interval_seconds")
        next_interval: int | None
        try:
            next_interval = int(raw_next) if raw_next is not None else None
        except (TypeError, ValueError):
            next_interval = None
        if next_interval is not None and next_interval < 60:
            next_interval = None

        raw_limit = data.get("next_session_limit_seconds")
        next_limit: int | None
        try:
            next_limit = int(raw_limit) if raw_limit is not None else None
        except (TypeError, ValueError):
            next_limit = None
        if next_limit is not None and next_limit < 60:
            next_limit = None

        return cls(
            session_started_at=data.get("session_started_at", datetime.now(timezone.utc).isoformat()),
            active_seconds=float(data.get("active_seconds", 0)),
            last_break_seconds=int(data.get("last_break_seconds", 0)),
            cycle_count=int(data.get("cycle_count", 0)),
            break_until=data.get("break_until"),
            last_farm_at=data.get("last_farm_at"),
            next_farm_interval_seconds=next_interval,
            next_session_limit_seconds=next_limit,
        )


def load_runtime_state(path: Path) -> RuntimeState:
    if not path.exists():
        return RuntimeState.fresh()
    with open(path, encoding="utf-8") as f:
        return RuntimeState.from_dict(json.load(f))


def save_runtime_state(path: Path, state: RuntimeState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(asdict(state), f, indent=2)
