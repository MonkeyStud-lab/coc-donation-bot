"""Bounded, sequence-numbered activity history for reconnecting interfaces."""
from collections import deque
from datetime import datetime, timezone
import threading


class EventHistory:
    def __init__(self, capacity=500):
        self._entries = deque(maxlen=capacity)
        self._sequence = 0
        self._lock = threading.Lock()

    def append(self, level, text):
        with self._lock:
            self._sequence += 1
            self._entries.append({"id": self._sequence, "level": level,
                                  "text": str(text)[:4000],
                                  "at": datetime.now(timezone.utc).isoformat()})

    def since(self, cursor=0):
        with self._lock:
            first = self._entries[0]["id"] if self._entries else self._sequence + 1
            return {"cursor": self._sequence, "reset": cursor < first - 1,
                    "entries": [dict(e) for e in self._entries if e["id"] > cursor]}
