#!/usr/bin/env python3
"""Offline tests for the observation-only screen prototype (no ADB calls)."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import Mock

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from coc_bot.config import load_config
from coc_bot.vision import screen_model
from coc_bot.vision.screens import ScreenClassifier, ScreenType


def main():
    with tempfile.TemporaryDirectory(prefix="screen-model-test-") as directory:
        root = Path(directory)
        tasks = []
        examples = {}
        for session in ("session_a", "session_b"):
            for label, color in (("home", (30, 150, 20)), ("shop", (180, 180, 180)),
                                 ("clash_pass", (20, 200, 240))):
                if session == "session_b" and label == "clash_pass":
                    continue
                for n in range(2):
                    frame = np.full((180, 320, 3), color, dtype=np.uint8)
                    cv2.putText(frame, label, (20, 100 + n), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 3)
                    relative = f"frames/{session}/{label}_{n}.png"
                    path = root / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    assert cv2.imwrite(str(path), frame)
                    examples[label] = frame
                    tasks.append({"data": {"image": f"/data/local-files/?d={relative}", "session": session},
                                  "annotations": [{"result": [{"type": "choices", "from_name": "screen",
                                                              "value": {"choices": [label]}}]}]})
        export = root / "tasks.json"
        export.write_text(json.dumps(tasks), encoding="utf-8")
        model_path = root / "screens.npz"
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/train_screen_model.py"), "--tasks", str(export),
             "--data-dir", str(root), "--output", str(model_path)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        report = json.loads(result.stdout)
        assert report["frames"] == 10 and report["use"] == "observation_only"
        held_a = next(r for r in report["validation"] if r["held_out_session"] == "session_a")
        assert held_a["unvalidated_labels"] == ["clash_pass"]
        model = screen_model.ScreenModel(model_path)
        for label, frame in examples.items():
            assert model.predict(frame) == label
            assert model.predict(cv2.resize(frame, (640, 360))) == label

        screen_model.enable_observer(model_path)
        screen_model._observer.model.predict = Mock(return_value="shop")
        classifier = ScreenClassifier(load_config())
        classifier._classify = lambda frame, mode: ScreenType.HOME
        assert classifier.classify(examples["home"]) == ScreenType.HOME
        screen_model._observer.model.predict.assert_called_once()
        # Rate limit comparisons, and never use the model's label as the result.
        assert classifier.classify(examples["home"]) == ScreenType.HOME
        screen_model._observer.model.predict.assert_called_once()

        bad = Mock()
        bad.predict.side_effect = ValueError("test inference failure")
        screen_model._observer = screen_model.ScreenObserver(bad)
        assert classifier.classify(examples["home"]) == ScreenType.HOME
        assert screen_model._observer._failed

        # A missing or mismatched model is optional and cannot prevent startup.
        screen_model.enable_observer(root / "missing.npz")
        assert screen_model._observer is None
        metadata_path = model_path.with_suffix(".json")
        metadata = json.loads(metadata_path.read_text())
        metadata["model_sha256"] = "invalid"
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
        screen_model.enable_observer(model_path)
        assert screen_model._observer is None
        assert classifier.classify(examples["home"]) == ScreenType.HOME
    print("verify_screen_model: OK (training, session isolation, reload, observer safety)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
