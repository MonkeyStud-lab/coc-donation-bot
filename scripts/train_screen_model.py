#!/usr/bin/env python3
"""Train an experimental screen classifier from reviewed Label Studio screens.

Uses existing OpenCV / NumPy dependencies; no GPU, ADB, or object labels needed.
Reports leave-session-out results before fitting the prototype to all examples.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from urllib.parse import parse_qs, urlparse

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from coc_bot.vision.screen_model import FEATURE_VERSION, ScreenModel, screen_features


def fit(features, targets):
    mean = features.mean(axis=0)
    scale = np.maximum(features.std(axis=0), 0.05)
    samples = np.column_stack(((features - mean) / scale, np.ones(len(features)))).astype(np.float32)
    counts = np.bincount(targets)
    # Balanced regularized least squares. Solve in sample space (56x56 for
    # the seed) rather than constructing a huge feature-space matrix.
    balance = np.sqrt(len(targets) / (len(counts) * counts[targets])).astype(np.float32)
    samples *= balance[:, None]
    responses = np.eye(len(counts), dtype=np.float32)[targets] * balance[:, None]
    gram = samples @ samples.T + np.eye(len(samples), dtype=np.float32)
    weights = samples.T @ np.linalg.solve(gram, responses)
    return weights, mean, scale


def validate_sessions(features, targets, sessions, labels):
    results = []
    for session in sorted(set(sessions)):
        held = np.asarray([s == session for s in sessions])
        train = ~held
        available = sorted(set(targets[train].tolist()))
        # A model cannot predict a category absent from its training sessions.
        # List those explicitly rather than presenting them as validated.
        eligible = held & np.isin(targets, available)
        unavailable = sorted(set(targets[held].tolist()) - set(available))
        row = {"held_out_session": session, "held_out_frames": int(held.sum()),
               "unvalidated_labels": [labels[i] for i in unavailable],
               "evaluated_frames": int(eligible.sum()), "correct": 0, "confusions": []}
        if len(available) >= 2 and eligible.any():
            remap = {old: new for new, old in enumerate(available)}
            weights, mean, scale = fit(features[train], np.asarray([remap[t] for t in targets[train]], dtype=np.int32))
            samples = np.column_stack(((features[eligible] - mean) / scale, np.ones(int(eligible.sum()))))
            predicted = np.asarray([available[int(a)] for a in np.argmax(samples @ weights, axis=1)])
            expected = targets[eligible]
            row["correct"] = int((predicted == expected).sum())
            confusion = Counter((labels[e], labels[p]) for e, p in zip(expected, predicted) if e != p)
            row["confusions"] = [{"expected": e, "predicted": p, "count": n} for (e, p), n in confusion.items()]
        else:
            row["evaluated_frames"] = 0
        results.append(row)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--output", type=Path, default=ROOT / "data/models/screens.npz")
    args = parser.parse_args()
    if args.output.suffix != ".npz":
        parser.error("--output must end in .npz (metadata uses the matching .json name)")
    tasks = json.loads(args.tasks.read_text(encoding="utf-8"))
    rows = []
    seen = set()
    for task in tasks:
        annotations = [a for a in task.get("annotations", []) if not a.get("was_cancelled")]
        choices = [r["value"]["choices"] for a in annotations for r in a["result"]
                   if r["type"] == "choices" and r["from_name"] == "screen"]
        if len(choices) != 1 or len(choices[0]) != 1:
            raise ValueError("Every task needs exactly one reviewed screen label")
        relative = parse_qs(urlparse(task["data"]["image"]).query)["d"][0]
        path = (args.data_dir / relative).resolve()
        if not path.is_relative_to(args.data_dir.resolve()) or path in seen:
            raise ValueError(f"Outside data directory or duplicate example: {relative}")
        seen.add(path)
        frame = cv2.imread(str(path))
        if frame is None:
            raise ValueError(f"Missing screenshot: {path}")
        session = task["data"].get("session", Path(relative).parent.name)
        rows.append((screen_features(frame), choices[0][0], session))
    labels = sorted({label for _, label, _ in rows})
    if len(labels) < 2:
        raise ValueError("Need at least two different screen categories")
    features = np.stack([f for f, _, _ in rows])
    targets = np.asarray([labels.index(label) for _, label, _ in rows], dtype=np.int32)
    validation = validate_sessions(features, targets, [s for _, _, s in rows], labels)
    weights, mean, scale = fit(features, targets)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(suffix=".npz", dir=args.output.parent)
    os.close(fd)
    temporary = Path(temp_name)
    try:
        np.savez_compressed(temporary, weights=weights, mean=mean, scale=scale)
        metadata = {"feature_version": FEATURE_VERSION, "labels": labels,
                    "method": "balanced_ridge_classifier", "feature_count": len(mean),
                    "model_sha256": hashlib.sha256(temporary.read_bytes()).hexdigest(),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "frames": len(rows), "class_counts": dict(Counter(label for _, label, _ in rows)),
                    "tasks_sha256": hashlib.sha256(args.tasks.read_bytes()).hexdigest(),
                    "validation": validation, "use": "observation_only",
                    "limitations": ["Small AI-reviewed seed, not human-verified ground truth.",
                                    "Unseen classes and screens are not handled reliably.",
                                    "No trained detector for individual buttons or objects."]}
        os.replace(temporary, args.output)
        metadata_path = args.output.with_suffix(".json")
        fd, temp_meta = tempfile.mkstemp(suffix=".json", dir=args.output.parent)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(metadata, handle, indent=2)
        try:
            os.replace(temp_meta, metadata_path)
        finally:
            Path(temp_meta).unlink(missing_ok=True)
        # Loading checks hashes, feature dimensions, and model validity.
        reloaded = ScreenModel(args.output)
        assert len(reloaded.labels) == len(labels)
    finally:
        temporary.unlink(missing_ok=True)
    print(json.dumps({"model": str(args.output), "frames": len(rows), "class_counts": metadata["class_counts"],
                      "validation": validation, "use": "observation_only"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
