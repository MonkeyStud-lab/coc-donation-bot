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

    @classmethod
    def fresh(cls) -> RuntimeState:
        now = datetime.now(timezone.utc).isoformat()
        return cls(session_started_at=now, active_seconds=0.0, last_break_seconds=0, cycle_count=0)

    @classmethod
    def from_dict(cls, data: dict) -> RuntimeState:
        return cls(
            session_started_at=data.get("session_started_at", datetime.now(timezone.utc).isoformat()),
            active_seconds=float(data.get("active_seconds", 0)),
            last_break_seconds=int(data.get("last_break_seconds", 0)),
            cycle_count=int(data.get("cycle_count", 0)),
            break_until=data.get("break_until"),
            last_farm_at=data.get("last_farm_at"),
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
