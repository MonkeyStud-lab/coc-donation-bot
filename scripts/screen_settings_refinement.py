"""Offline, observation-only refinement of generic popups into Settings.

Use a separately trained screen model to resolve this one ambiguity. The
baseline retains every other prediction. This is not wired into navigation,
does not authorize closing a screen, and does not change ScreenModel's format.
Both models must be evaluated together on unchanged per-image regression sets.
"""
from __future__ import annotations

from typing import Protocol, Any


class Predictor(Protocol):
    def predict(self, frame: Any) -> str: ...


def refine_settings_prediction(baseline: str, refinement: str) -> str:
    """Only resolve generic popup -> settings; never rewrite another class."""
    if baseline == "popup" and refinement == "settings":
        return "settings"
    return baseline


class SettingsRefinement:
    """Two frozen predictors; a failed optional refinement preserves baseline."""

    def __init__(self, baseline: Predictor, refinement: Predictor):
        self.baseline = baseline
        self.refinement = refinement

    def predict(self, frame: Any) -> str:
        baseline = self.baseline.predict(frame)
        if baseline != "popup":
            return baseline
        try:
            refinement = self.refinement.predict(frame)
        except Exception:
            return baseline
        return refine_settings_prediction(baseline, refinement)
