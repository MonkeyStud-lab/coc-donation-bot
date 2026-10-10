"""Bounded, passive screenshot selection. Never authorizes game actions."""

from __future__ import annotations

import base64
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
import html
import math
import json
import os
from pathlib import Path
import queue
import random
import shutil
import threading
import time
import uuid
from urllib.parse import parse_qs, urlparse

import cv2
from loguru import logger
import numpy as np


@dataclass(frozen=True)
class CollectionOptions:
    daily_limit: int = 200
    storage_bytes: int = 5 * 1024**3
    ordinary_limit: int = 120
    per_screen_limit: int = 20
    incident_limit: int = 10
    memory_bytes: int = 64 * 1024**2
    reserve_free_bytes: int = 256 * 1024**2
    routine_probability: float = 0.02

    def __post_init__(self):
        if min(self.daily_limit, self.storage_bytes, self.memory_bytes, self.per_screen_limit) <= 0:
            raise ValueError("Collection limits must be positive")
        if min(self.ordinary_limit, self.incident_limit, self.reserve_free_bytes) < 0:
            raise ValueError("Collection quotas and free-space reserve cannot be negative")
        if not math.isfinite(self.routine_probability) or not 0 <= self.routine_probability <= 1:
            raise ValueError("Invalid collection sampling probability")


@dataclass
class Candidate:
    frame: np.ndarray
    seq: int
    ts: float
    phase: str
    action: dict
    verdicts: list[dict] = field(default_factory=list)
    model: dict | None = None
    events: list[dict] = field(default_factory=list)


def fingerprint(frame: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    # Regional comparisons stop a small but important UI change from being
    # drowned out by unchanged scenery. Fine text / animation changes average out.
    regions = (gray, gray[:max(1, h // 6)], gray[:, :max(1, w // 3)], gray[h * 3 // 4:])
    sizes = ((64, 36), (64, 8), (32, 24), (64, 12))
    return np.concatenate([cv2.resize(r, size, interpolation=cv2.INTER_AREA).ravel()
                           for r, size in zip(regions, sizes)])


def near_duplicate(fp: np.ndarray, history: list[np.ndarray]) -> bool:
    for offset in range(0, len(history), 128):
        differences = np.abs(np.stack(history[offset:offset + 128]).astype(np.int16) - fp.astype(np.int16))
        full = differences[:, :2304].mean(axis=1) < 2.5
        regional = np.column_stack([differences[:, a:b].mean(axis=1)
                                    for a, b in ((2304, 2816), (2816, 3584), (3584, 4352))])
        if (full & (regional.max(axis=1) < 5.0)).any():
            return True
    return False


def read_catalog(root: Path):
    path = root / "catalog.jsonl"
    if not path.exists():
        return
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                row = json.loads(line)
                if not isinstance(row, dict) or not all(key in row for key in
                        ("file", "reason", "screen_hint", "saved_day", "priority")):
                    continue
                if (not all(isinstance(row[key], str) for key in
                            ("file", "screen_hint", "saved_day", "priority"))
                        or not isinstance(row["reason"], list)):
                    continue
                image = (root / row["file"]).resolve()
                if image.is_relative_to(root.resolve()) and image.is_file():
                    yield row
            except (ValueError, KeyError, TypeError):
                # An interrupted last append must not disable navigation.
                continue


def write_gallery(root: Path) -> None:
    rows = deque(read_catalog(root), maxlen=600)
    groups = {"New appearances": [], "Disagreements": [], "Failures": [], "Ordinary examples": []}
    for row in rows:
        reasons = row["reason"]
        group = ("Failures" if row.get("incident") else "Disagreements" if "disagreement" in reasons
                 or "rule_conflict" in reasons else "Ordinary examples" if reasons == ["routine"] else "New appearances")
        path = html.escape(row["file"], quote=True)
        detail = html.escape(json.dumps({k: row.get(k) for k in
            ("screen_hint", "model", "phase", "action", "events", "ts", "incident", "reason")}, indent=2))
        groups[group].append(f'<article><a href="{path}"><img loading="lazy" src="{path}"></a>'
                             f'<h3>{html.escape(row["screen_hint"])}</h3><details><summary>Why saved / context</summary>'
                             f'<pre>{detail}</pre></details></article>')
    sections = ''.join(f'<h2>{name} ({len(items)})</h2><section>{"".join(reversed(items))}</section>'
                       for name, items in groups.items())
    body = '<!doctype html><meta charset="utf-8"><title>Screenshot review</title><style>' \
           'body{background:#171b24;color:#eee;font:16px system-ui;margin:28px}' \
           'section{display:grid;grid-template-columns:repeat(auto-fit,minmax(310px,1fr));gap:16px}' \
           'article{background:#252c38;padding:12px;border-radius:12px}img{width:100%;height:auto}' \
           'pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}a{color:#8ac7ff}</style>' \
           '<h1>Collected screenshots</h1><p>Predictions are suggestions, not verified labels. ' \
           'Showing the latest 600 saved examples. Screenshots stay on this computer.</p>' + sections
    temporary = root / "review.html.tmp"
    temporary.write_text(body, encoding="utf-8")
    os.replace(temporary, root / "review.html")


class SmartFrameRecorder:
    """Capture hooks only enqueue; expensive selection and PNG writing run off-loop."""

    def __init__(self, root_dir: Path, *, options: CollectionOptions | None = None, extra_meta=None,
                 seed_export: Path | None = None, data_dir: Path | None = None):
        self.root = root_dir
        self.seed_export = seed_export
        self.data_dir = data_dir
        self.options = options or CollectionOptions()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lease = (self.root / ".collector.lock").open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                self._lease.write(b"0")
                self._lease.flush()
                self._lease.seek(0)
                msvcrt.locking(self._lease.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._lease.close()
            raise RuntimeError("Another smart collector is still writing; collection disabled")
        self.session = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
        self.session_dir = self.root / "sessions" / self.session
        try:
            self.session_dir.mkdir(parents=True)
            (self.session_dir / "session.json").write_text(json.dumps({
                "started_at": datetime.now(timezone.utc).isoformat(), "policy": "smart-v1",
                "limits": vars(self.options), **(extra_meta or {}),
            }, indent=2), encoding="utf-8")
        except Exception:
            self._lease.close()
            raise
        self._lock = threading.Lock()
        self._queue = queue.Queue(maxsize=8)
        self._stop = threading.Event()
        self._pending = None
        self._seq = 0
        self._bytes = 0
        self._phase = "boot"
        self._action = {}
        self._events = deque(maxlen=8)
        self._stats = Counter()
        self._pause = None
        self._day_counts = Counter()
        self._ordinary_counts = Counter()
        self._screen_counts = Counter()
        self._incident_counts = Counter()
        self._history = deque(maxlen=4096)
        self._incident_history = deque(maxlen=128)
        self._recent = deque(maxlen=2)
        self._post = None
        self._last_hint = "unknown"
        self._last_status = 0.0
        self._worker = threading.Thread(target=self._work, name="smart-collector", daemon=True)
        self._worker.start()
        logger.info("Smart collection enabled → {} ({} images/day, {:.1f} GB)", self.root,
                    self.options.daily_limit, self.options.storage_bytes / 1024**3)

    def on_frame(self, frame):
        with self._lock:
            if self._stop.is_set():
                return
            if frame.nbytes * 5 > self.options.memory_bytes:
                self._stats["memory_dropped"] += 1
                return
            if self._pending is not None:
                self._enqueue(self._pending)
            self._seq += 1
            self._pending = Candidate(frame, self._seq, time.time(), self._phase, dict(self._action),
                                      events=list(self._events))
            self._events.clear()

    def _enqueue(self, item):
        # Leave room for two context frames, the worker frame, and current capture.
        if self._bytes + item.frame.nbytes * 5 > self.options.memory_bytes:
            self._stats["memory_dropped"] += 1
            return
        try:
            self._queue.put_nowait(item)
            self._bytes += item.frame.nbytes
            self._stats["queued"] += 1
        except queue.Full:
            self._stats["queue_dropped"] += 1

    def note_classification(self, frame, screen, mode):
        with self._lock:
            if self._pending is not None and self._pending.frame is frame:
                self._pending.verdicts.append({"screen": screen, "mode": mode})

    def note_model(self, frame, prediction, model_id):
        with self._lock:
            if self._pending is not None and self._pending.frame is frame:
                self._pending.model = {"screen": prediction, "model_id": model_id}

    def note_action(self, action):
        with self._lock:
            self._action = {"ts": time.time(), **action}
            # The pending screenshot preceded this action, not its result.

    def note_event(self, kind, details):
        event = {"kind": kind, "details": details, "ts": time.time()}
        with self._lock:
            if self._pending is not None:
                self._pending.events.append(event)
            else:
                self._events.append(event)

    def note_phase(self, phase):
        with self._lock:
            self._phase = phase

    def close(self):
        with self._lock:
            if self._stop.is_set():
                return
            if self._pending is not None:
                self._enqueue(self._pending)
                self._pending = None
            self._stop.set()
        # Never make Stop wait for a full screenshot-writing queue.
        self._worker.join(timeout=1.0)

    def _load_history(self):
        self._used_bytes = sum(p.stat().st_size for p in self.root.rglob("*") if p.is_file())
        if self.seed_export and self.data_dir and self.seed_export.is_file():
            try:
                tasks = json.loads(self.seed_export.read_text(encoding="utf-8"))
                for task in tasks[:4096]:
                    if self._stop.is_set():
                        break
                    relative = parse_qs(urlparse(task["data"]["image"]).query).get("d", [""])[0]
                    path = (self.data_dir / relative).resolve()
                    if not relative or not path.is_relative_to(self.data_dir.resolve()):
                        continue
                    frame = cv2.imread(str(path))
                    if frame is not None:
                        self._history.append(fingerprint(frame))
                        self._stats["seed_examples"] += 1
            except (ValueError, KeyError, TypeError, OSError) as exc:
                logger.warning("Reviewed screenshot seed skipped: {}", exc)
        for row in read_catalog(self.root):
            day = row["saved_day"]
            self._day_counts[day] += 1
            if row["priority"] == "ordinary":
                self._ordinary_counts[day] += 1
            if not row.get("incident"):
                self._screen_counts[(day, row["screen_hint"])] += 1
            try:
                fp = np.frombuffer(base64.b64decode(row["fingerprint"], validate=True), dtype=np.uint8)
                if len(fp) == 4352:
                    self._history.append(fp)
                    if row.get("incident") and row.get("context") == "trigger":
                        kind = row.get("incident_kind", "failure")
                        self._incident_history.append((kind, fp))
                        self._incident_counts[day] += 1
            except (ValueError, KeyError):
                continue

    def _work(self):
        try:
            self._load_history()
            while not self._stop.is_set() or not self._queue.empty():
                try:
                    item = self._queue.get(timeout=0.2)
                except queue.Empty:
                    self._status()
                    continue
                try:
                    self._select(item)
                except Exception as exc:
                    self._stats["errors"] += 1
                    logger.warning("Collection skipped a candidate (bot unaffected): {}", exc)
                finally:
                    with self._lock:
                        self._bytes -= item.frame.nbytes
                    self._queue.task_done()
                self._status()
        except Exception as exc:
            self._pause = f"Collection unavailable: {exc}"
            logger.warning("{}; bot continues normally", self._pause)
        finally:
            self._stop.set()
            try:
                self._status(force=True)
            except Exception:
                pass
            self._recent.clear()
            with self._lock:
                self._pending = None
                while not self._queue.empty():
                    self._queue.get_nowait()
                    self._queue.task_done()
                self._bytes = 0
            self._lease.close()

    def _select(self, item):
        self._stats["examined"] += 1
        labels = [v["screen"] for v in item.verdicts]
        hint = next((s for s in labels if s != "unknown"), labels[0] if labels else self._last_hint)
        inherited = not labels
        if labels:
            self._last_hint = hint
        fp = fingerprint(item.frame)
        day = datetime.now(timezone.utc).date().isoformat()
        failures = [e for e in item.events if e["kind"] not in ("action_confirmed",)]
        if failures:
            kind = failures[0]["kind"]
            repeated = near_duplicate(fp, [f for k, f in self._incident_history if k == kind])
            if repeated:
                self._stats["repeated_incidents"] += 1
            elif self._incident_counts[day] < self.options.incident_limit:
                self._incident_counts[day] += 1
                self._incident_history.append((kind, fp))
                incident = uuid.uuid4().hex[:12]
                for previous, previous_hint, previous_inherited, previous_fp in self._recent:
                    self._save(previous, previous_hint, previous_inherited, previous_fp,
                               ["failure_context"], "critical", incident, kind, "before")
                self._save(item, hint, inherited, fp, ["failure"], "critical", incident, kind, "trigger")
                self._post = (incident, kind, 2)
                self._recent.append((item, hint, inherited, fp))
                return
        if self._post:
            incident, kind, remaining = self._post
            self._save(item, hint, inherited, fp, ["failure_context"], "critical", incident, kind, "after")
            self._post = (incident, kind, remaining - 1) if remaining > 1 else None
            self._recent.append((item, hint, inherited, fp))
            return
        duplicate = near_duplicate(fp, list(self._history))
        if duplicate:
            self._stats["duplicates"] += 1
        else:
            reasons = []
            if "unknown" in labels:
                reasons.append("unknown")
            if len(set(labels)) > 1:
                reasons.append("rule_conflict")
            if item.model and labels and item.model["screen"] not in labels:
                reasons.append("disagreement")
            rare = hint in {"shop", "clash_pass", "popup", "battle", "battle_results", "attack_menu",
                            "matchmaking", "global_chat", "donation_panel"}
            if rare:
                reasons.append("rare_screen")
            priority = "critical" if reasons else "ordinary"
            if not reasons:
                reasons = ["routine"] if random.random() < self.options.routine_probability else ["new_appearance"]
            self._save(item, hint, inherited, fp, reasons, priority)
        self._recent.append((item, hint, inherited, fp))

    def _save(self, item, hint, inherited, fp, reasons, priority, incident=None, kind=None, context=None):
        day = datetime.now(timezone.utc).date().isoformat()
        path = self.session_dir / f"{item.seq:06d}.png"
        if path.exists():
            # Context links can reuse a frame already saved for another reason.
            self._append(self.root / "incidents.jsonl", {"incident": incident, "context": context,
                                                       "file": path.relative_to(self.root).as_posix()})
            return False
        if self._pause:
            self._stats["paused_dropped"] += 1
            return False
        if (self._day_counts[day] >= self.options.daily_limit
                or (priority == "ordinary" and self._ordinary_counts[day] >= min(self.options.ordinary_limit, self.options.daily_limit))
                or (not incident and self._screen_counts[(day, hint)] >= self.options.per_screen_limit)):
            self._stats["quota_dropped"] += 1
            return False
        ok, encoded = cv2.imencode(".png", item.frame)
        if not ok:
            raise OSError("Could not encode screenshot")
        # Reserve metadata / review-gallery headroom too. Never delete old data.
        required = encoded.nbytes + 32768
        if self._used_bytes + required > self.options.storage_bytes:
            self._pause = "Storage limit reached"
        elif shutil.disk_usage(self.root).free < self.options.reserve_free_bytes + required:
            self._pause = "Low free disk space"
        if self._pause:
            logger.warning("Smart collection paused: {}; bot continues normally", self._pause)
            return False
        h, w = item.frame.shape[:2]
        record = {"file": path.relative_to(self.root).as_posix(), "seq": item.seq, "session": self.session,
                  "ts": datetime.fromtimestamp(item.ts, timezone.utc).isoformat(), "saved_day": day,
                  "screen_hint": hint, "screen_inherited": inherited, "verdicts": item.verdicts,
                  "model": item.model, "phase": item.phase, "action": item.action, "events": item.events,
                  "reason": reasons, "priority": priority, "incident": incident, "incident_kind": kind,
                  "context": context, "width": w, "height": h,
                  "fingerprint": base64.b64encode(fp.tobytes()).decode("ascii"), "labels_verified": False}
        temporary = path.with_suffix(".png.tmp")
        try:
            temporary.write_bytes(encoded.tobytes())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        self._append(self.root / "catalog.jsonl", record)
        self._append(self.session_dir / "index.jsonl", {k: v for k, v in record.items() if k != "fingerprint"})
        self._used_bytes += required
        self._day_counts[day] += 1
        if priority == "ordinary":
            self._ordinary_counts[day] += 1
        if not incident:
            self._screen_counts[(day, hint)] += 1
        self._history.append(fp)
        self._stats["saved"] += 1
        self._stats[f"reason:{reasons[0]}"] += 1
        return True

    @staticmethod
    def _append(path, record):
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")

    def _status(self, force=False):
        if not force and time.monotonic() - self._last_status < 60:
            return
        self._last_status = time.monotonic()
        with self._lock:
            stats = dict(self._stats)
        report = {"session": self.session, "stats": stats, "paused": self._pause,
                  "approximate_storage_bytes": getattr(self, "_used_bytes", 0),
                  "daily_saved": dict(self._day_counts), "limits": vars(self.options)}
        temp = self.root / "status.json.tmp"
        temp.write_text(json.dumps(report, indent=2), encoding="utf-8")
        os.replace(temp, self.root / "status.json")
        # Only regenerate when the saved set changes; avoid rewriting while idle.
        if force or getattr(self, "_gallery_saved", -1) != self._stats["saved"]:
            write_gallery(self.root)
            self._gallery_saved = self._stats["saved"]
        if self._stats["examined"]:
            logger.info("Collection: {} saved, {} duplicates skipped, {} quota skips{}",
                        self._stats["saved"], self._stats["duplicates"], self._stats["quota_dropped"],
                        f"; paused: {self._pause}" if self._pause else "")
