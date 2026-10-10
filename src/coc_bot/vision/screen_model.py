"""Experimental CPU screen classifier. Predictions never authorize actions."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import threading
import time

import cv2
from loguru import logger
import numpy as np


FEATURE_VERSION = 1


def screen_features(frame: np.ndarray) -> np.ndarray:
    """Small spatial color and edge features; independent of capture resolution."""
    hsv = cv2.cvtColor(cv2.resize(frame, (32, 18)), cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv /= np.array([180, 255, 255], dtype=np.float32)
    gray = cv2.cvtColor(cv2.resize(frame, (64, 48)), cv2.COLOR_BGR2GRAY)
    dx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    dy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    magnitude, angle = cv2.cartToPolar(dx, dy, angleInDegrees=True)
    # Nine unsigned edge directions in each 8x8 cell. Use basic OpenCV APIs
    # rather than optional HOG / ml modules absent from some installations.
    bins = ((angle % 180) / 20).astype(np.int32)
    yy, xx = np.indices(gray.shape)
    cells = (yy // 8) * 8 + xx // 8
    edges = np.bincount((cells * 9 + bins).ravel(), weights=magnitude.ravel(), minlength=48 * 9).reshape(48, 9)
    edges /= np.maximum(np.linalg.norm(edges, axis=1, keepdims=True), 1e-6)
    return np.concatenate((hsv.ravel(), edges.ravel())).astype(np.float32)


class ScreenModel:
    def __init__(self, path: Path) -> None:
        metadata = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
        if metadata["feature_version"] != FEATURE_VERSION:
            raise ValueError("Unsupported screen model feature version")
        if hashlib.sha256(path.read_bytes()).hexdigest() != metadata["model_sha256"]:
            raise ValueError("Screen model and metadata do not match; retrain the model")
        self.labels = metadata["labels"]
        self.model_id = metadata["model_sha256"][:16]
        with np.load(path, allow_pickle=False) as archive:
            self.mean = archive["mean"]
            self.scale = archive["scale"]
            self.weights = archive["weights"]
        if not np.isfinite(self.mean).all() or not np.isfinite(self.scale).all() or (self.scale <= 0).any():
            raise ValueError("Invalid feature scaling in screen model")
        if (self.mean.ndim != 1 or self.scale.shape != self.mean.shape
                or self.weights.shape != (len(self.mean) + 1, len(self.labels))
                or not np.isfinite(self.weights).all()):
            raise ValueError("Invalid or incompatible screen model")

    def predict(self, frame: np.ndarray) -> str:
        feature = screen_features(frame)
        sample = np.append((feature - self.mean) / self.scale, 1.0)
        return self.labels[int(np.argmax(sample @ self.weights))]


class ScreenObserver:
    """Rate-limited comparison only; failures disable the observer, not the bot."""

    def __init__(self, model: ScreenModel) -> None:
        self.model = model
        self._lock = threading.Lock()
        self._last = 0.0
        self._failed = False

    def note(self, frame: np.ndarray, screen: str) -> None:
        if not self._lock.acquire(blocking=False):
            return
        try:
            now = time.monotonic()
            if self._failed or now - self._last < 5.0:
                return
            self._last = now
            prediction = self.model.predict(frame)
            from coc_bot.vision import recorder

            recorder.note_model(frame, prediction, getattr(self.model, "model_id", "unknown"))
            logger.info(
                "Screen observer (no actions): model={} rules={} agree={}",
                prediction, screen, prediction == screen,
            )
        except Exception:  # Model errors must not disrupt existing navigation.
            self._failed = True
            logger.exception("Screen observer disabled after an inference error")
        finally:
            self._lock.release()


_observer: ScreenObserver | None = None


def enable_observer(path: Path) -> None:
    global _observer
    _observer = None
    try:
        _observer = ScreenObserver(ScreenModel(path))
        logger.info("Experimental screen observer enabled (predictions cannot control the bot)")
    except Exception as exc:
        logger.warning("Screen observer unavailable; continuing with existing rules: {}", exc)


def note_observation(frame: np.ndarray, screen: str) -> None:
    if _observer is not None:
        _observer.note(frame, screen)
