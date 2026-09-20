"""
Frame recorder — Phase 0 of the perception project.

Dumps screenshots (plus what the current heuristic classifier thought they
were) to ``data/frames/<session>/`` so they can be labeled and used to train a
UI detector. Zero cost when not enabled.

Selection policy per frame:
  * always save when the classifier said UNKNOWN (these are the gaps),
  * always save when the screen verdict changed from the previous frame,
  * otherwise save every ``every_n``-th frame,
  * skip near-duplicates of the last saved frame (unless unknown/changed).

Layout::

    data/frames/20260919_2210/
        session.json      # resolution, git commit, config hash, start time
        index.jsonl       # one line per saved frame: seq, ts, screen, mode, reason, ...
        000001.png
        000002.png

Usage::

    python -m coc_bot --record            # GUI or --no-gui
    python -m coc_bot --record --record-every 5

Hook points (already wired):
  * ``ScreenCapture.screenshot`` -> ``on_frame(frame)``
  * ``ScreenClassifier.classify`` -> ``note_classification(frame, screen, mode)``
"""

from __future__ import annotations

import hashlib
import json
import queue
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
from loguru import logger


@dataclass
class _Pending:
    frame: np.ndarray
    seq: int
    ts: float
    verdicts: list[tuple[str, str]] = field(default_factory=list)  # (screen, mode)

    def final_screen(self) -> str:
        """Prefer the first non-unknown verdict; else unknown; else 'none' (never classified)."""
        if not self.verdicts:
            return "none"
        for screen, _ in self.verdicts:
            if screen != "unknown":
                return screen
        return "unknown"

    def modes(self) -> list[str]:
        seen: list[str] = []
        for _, mode in self.verdicts:
            if mode not in seen:
                seen.append(mode)
        return seen


class FrameRecorder:
    """Selective screenshot dumper with an async PNG writer."""

    def __init__(
        self,
        root_dir: Path,
        *,
        every_n: int = 10,
        max_frames: int | None = None,
        dedupe_threshold: float = 2.0,
        session_name: str | None = None,
        extra_meta: dict | None = None,
    ) -> None:
        self.every_n = max(1, int(every_n))
        self.max_frames = max_frames
        self.dedupe_threshold = float(dedupe_threshold)
        stamp = session_name or datetime.now().strftime("%Y%m%d_%H%M")
        self.session_dir = root_dir / stamp
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self.session_dir / "index.jsonl"

        self._seq = 0
        self._saved = 0
        self._pending: _Pending | None = None
        self._last_screen: str | None = None
        self._last_saved_thumb: np.ndarray | None = None
        self._lock = threading.Lock()

        self._queue: queue.Queue[tuple[Path, np.ndarray, dict] | None] = queue.Queue(maxsize=64)
        self._writer = threading.Thread(target=self._writer_loop, name="frame-recorder", daemon=True)
        self._writer.start()
        self._closed = False

        self._write_session_meta(extra_meta or {})
        logger.info(
            "Frame recorder ON → {} (every_n={}, max_frames={})",
            self.session_dir,
            self.every_n,
            self.max_frames,
        )

    # ------------------------------------------------------------------ hooks

    def on_frame(self, frame: np.ndarray) -> None:
        """Called by ScreenCapture for every screenshot. Flushes the previous frame."""
        with self._lock:
            if self._pending is not None:
                self._decide_and_enqueue(self._pending)
            self._seq += 1
            self._pending = _Pending(frame=frame, seq=self._seq, ts=time.time())

    def note_classification(self, frame: np.ndarray, screen: str, mode: str) -> None:
        """Called by ScreenClassifier. Only counts if it's the frame we're holding."""
        with self._lock:
            p = self._pending
            if p is None or p.frame is not frame:
                return
            p.verdicts.append((screen, mode))

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            if self._pending is not None:
                self._decide_and_enqueue(self._pending)
                self._pending = None
        self._queue.put(None)
        self._writer.join(timeout=10.0)
        logger.info("Frame recorder OFF — {} frame(s) saved to {}", self._saved, self.session_dir)

    # --------------------------------------------------------------- internals

    def _decide_and_enqueue(self, p: _Pending) -> None:
        if self.max_frames is not None and self._saved >= self.max_frames:
            return
        screen = p.final_screen()
        reasons: list[str] = []
        if screen == "unknown":
            reasons.append("unknown")
        if self._last_screen is not None and screen != self._last_screen and screen != "none":
            reasons.append("screen_change")
        if p.seq % self.every_n == 0:
            reasons.append("periodic")
        prev_screen = self._last_screen
        if screen != "none":
            self._last_screen = screen
        if not reasons:
            return

        thumb = self._thumb(p.frame)
        if reasons == ["periodic"] and self._last_saved_thumb is not None:
            diff = float(np.mean(cv2.absdiff(thumb, self._last_saved_thumb)))
            if diff < self.dedupe_threshold:
                return
        self._last_saved_thumb = thumb

        h, w = p.frame.shape[:2]
        self._saved += 1
        name = f"{p.seq:06d}.png"
        record = {
            "seq": p.seq,
            "file": name,
            "ts": datetime.fromtimestamp(p.ts, tz=timezone.utc).isoformat(),
            "screen": screen,
            "prev_screen": prev_screen,
            "modes": p.modes(),
            "verdicts": [{"screen": s, "mode": m} for s, m in p.verdicts],
            "reason": reasons,
            "width": w,
            "height": h,
        }
        try:
            self._queue.put_nowait((self.session_dir / name, p.frame, record))
        except queue.Full:
            logger.warning("Frame recorder queue full — dropping frame {}", p.seq)
            self._saved -= 1

    @staticmethod
    def _thumb(frame: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return cv2.resize(gray, (64, 36), interpolation=cv2.INTER_AREA).astype(np.int16)

    def _writer_loop(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            path, frame, record = item
            try:
                ok = cv2.imwrite(str(path), frame)
                if not ok:
                    logger.warning("Frame recorder: imwrite failed for {}", path)
                    continue
                with open(self._index_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record) + "\n")
            except Exception as exc:  # noqa: BLE001
                logger.warning("Frame recorder write failed: {}", exc)

    def _write_session_meta(self, extra: dict) -> None:
        meta = {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "every_n": self.every_n,
            "max_frames": self.max_frames,
            "git_commit": _git_commit(),
            **extra,
        }
        try:
            (self.session_dir / "session.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        except OSError as exc:
            logger.warning("Could not write session.json: {}", exc)


def _git_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return out.stdout.strip() or None
    except (OSError, subprocess.TimeoutExpired):
        return None


def config_fingerprint(config) -> str:
    """Short hash of the calibration so sessions can be grouped by calibration."""
    try:
        payload = json.dumps(
            {
                "w": config.frame_width,
                "h": config.frame_height,
                "rois": config.rois,
                "tap_points": config.tap_points,
                "templates": config.templates,
            },
            sort_keys=True,
            default=str,
        )
    except Exception:  # noqa: BLE001
        return "unknown"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:10]


# ------------------------------------------------------------ global singleton

_active: FrameRecorder | None = None


def start(recorder: FrameRecorder) -> None:
    global _active
    _active = recorder


def stop() -> None:
    global _active
    if _active is not None:
        _active.close()
    _active = None


def active() -> FrameRecorder | None:
    return _active


def on_frame(frame: np.ndarray) -> None:
    rec = _active
    if rec is not None:
        rec.on_frame(frame)


def note_classification(frame: np.ndarray, screen, mode) -> None:
    rec = _active
    if rec is None:
        return
    screen_s = getattr(screen, "value", str(screen))
    mode_s = getattr(mode, "value", str(mode)) if mode is not None else "any"
    rec.note_classification(frame, screen_s, mode_s)
