from __future__ import annotations

import json
import os
import threading
import time
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

# Serialises writers across threads (bot loop + GUI status polling).
_SAVE_LOCK = threading.Lock()


@dataclass
class RuntimeState:
    session_started_at: str
    active_seconds: float
    last_farm_at: str | None = None  # UTC ISO timestamp of last successful farm
    # Read-only legacy fields retained for old saved-state compatibility.
    farm_paused_at: str | None = None
    next_farm_interval_seconds: int | None = None
    last_completed_attack_id: str | None = None

    @classmethod
    def fresh(cls) -> RuntimeState:
        now = datetime.now(timezone.utc).isoformat()
        return cls(session_started_at=now, active_seconds=0.0)

    @classmethod
    def from_dict(cls, data: dict) -> RuntimeState:
        raw_next = data.get("next_farm_interval_seconds")
        next_interval: int | None
        try:
            next_interval = int(raw_next) if raw_next is not None else None
        except (TypeError, ValueError,OverflowError):
            next_interval = None
        if next_interval is not None and next_interval < 60:
            next_interval = None

        active=float(data.get('active_seconds',0))
        if isinstance(data.get('active_seconds'),bool) or not math.isfinite(active) or active<0:
            raise ValueError('Invalid active runtime')
        for name in ('session_started_at','last_farm_at','farm_paused_at','last_completed_attack_id'):
            if data.get(name) is not None and not isinstance(data[name],str):raise ValueError('Invalid runtime text field')
        return cls(
            session_started_at=data.get("session_started_at", datetime.now(timezone.utc).isoformat()),
            active_seconds=active,
            last_farm_at=data.get("last_farm_at"),
            farm_paused_at=data.get("farm_paused_at"),
            next_farm_interval_seconds=next_interval,
            last_completed_attack_id=data.get('last_completed_attack_id'),
        )


def load_runtime_state(path: Path) -> RuntimeState:
    if not path.exists():
        return RuntimeState.fresh()
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        logger.warning("Could not read runtime state {}: {} — starting fresh", path, exc)
        return RuntimeState.fresh()
    if not raw:
        logger.warning("Runtime state {} is empty — starting fresh", path)
        return RuntimeState.fresh()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning(
            "Runtime state {} is corrupt ({}) — starting fresh",
            path,
            exc,
        )
        return RuntimeState.fresh()
    if not isinstance(data, dict):
        logger.warning("Runtime state {} is not a JSON object — starting fresh", path)
        return RuntimeState.fresh()
    try:
        return RuntimeState.from_dict(data)
    except (TypeError, ValueError,OverflowError) as exc:
        # e.g. ``"active_seconds": null`` — a corrupt field should not block startup.
        logger.warning("Runtime state {} has bad fields ({}) — starting fresh", path, exc)
        return RuntimeState.fresh()


def save_runtime_state(path: Path, state: RuntimeState) -> None:
    """
    Persist state atomically (temp file + rename) and never raise.

    A failed save must not take the bot loop down; the in-memory state is
    still authoritative and the next save will retry.
    """
    payload = json.dumps(asdict(state), indent=2)
    # Unique tmp per writer so two processes cannot clobber each other's temp file.
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    with _SAVE_LOCK:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(payload, encoding="utf-8")
            try:
                os.replace(tmp, path)
            except PermissionError:
                # Windows: target briefly locked by a concurrent reader — one retry.
                time.sleep(0.05)
                os.replace(tmp, path)
        except OSError as exc:
            logger.warning("Could not save runtime state {}: {}", path, exc)
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
