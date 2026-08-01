"""In-app Setup calibration using InteractivePicker (tap / ROI / template crop)."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import cv2
import numpy as np
from loguru import logger
from tkinter import messagebox

from coc_bot.adb.capture import ScreenCapture
from coc_bot.adb.client import AdbClient, AdbError
from coc_bot.calibration.picker import InteractivePicker
from coc_bot.calibration.wizard import CalibrationPart, STEPS
from coc_bot.config import BotConfig, load_config, save_calibrated


def _capture_frame(config: BotConfig) -> np.ndarray:
    client = AdbClient(device=config.adb_device)
    client.ensure_connected()
    return ScreenCapture(client).screenshot()


def pick_on_master(
    master,
    frame: np.ndarray,
    *,
    mode: str,
    title: str,
    refresh_cb: Callable[[], np.ndarray] | None = None,
) -> tuple[tuple[int, ...] | None, np.ndarray]:
    """Open InteractivePicker as a modal Toplevel; return (selection, frame_used)."""
    import tkinter as tk

    win = tk.Toplevel(master)
    win.transient(master)
    picker = InteractivePicker(win, frame, mode=mode, title=title)  # type: ignore[arg-type]
    if refresh_cb is not None:
        picker.set_refresh_callback(refresh_cb)
    win.grab_set()
    master.wait_window(win)
    return picker.result, picker.frame_bgr


def _try_auto_point(config: BotConfig, frame: np.ndarray, part: CalibrationPart) -> tuple[int, int] | None:
    """Cheap template auto-suggest for a few well-known tap keys."""
    from coc_bot.vision.matcher import TemplateMatcher

    template_key = {
        "attack_button": "attack_button",
        "donate_button": "donate_button",
        "return_home": "return_home",
        "unranked_battle": "unranked_battle",
    }.get(part.key)
    if not template_key:
        return None
    rel = config.templates.get(template_key)
    if not rel:
        return None
    path = config.templates_dir / rel
    if not path.is_file():
        return None
    try:
        template = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if template is None:
            return None
        matcher = TemplateMatcher(threshold=max(0.70, config.template_threshold - 0.05))
        match = matcher.find(frame, template)
        if match is None:
            return None
        return int(match.center[0]), int(match.center[1])
    except Exception:  # noqa: BLE001
        return None


def _save_template_crop(
    config: BotConfig,
    frame: np.ndarray,
    roi: tuple[int, int, int, int],
    part: CalibrationPart,
) -> None:
    x, y, w, h = roi
    crop = frame[y : y + h, x : x + w]
    if crop.size == 0:
        raise ValueError("Empty crop")
    rel = config.templates.get(part.key) or f"ui/{part.key}.png"
    out = config.templates_dir / rel
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), crop)
    config.templates[part.key] = rel.replace("\\", "/")
    logger.info("Saved template {} → {}", part.key, out)


def calibrate_part_in_app(master, step_id: str, part_key: str) -> str:
    """
    Run in-app calibration for one part.

    Returns a short status message for the UI.
    Raises ValueError / AdbError on failure or cancel.
    """
    step = STEPS.get(step_id)
    if step is None:
        raise ValueError(f"Unknown step: {step_id}")
    part = next((p for p in step.parts if p.key == part_key), None)
    if part is None:
        raise ValueError(f"Unknown part: {part_key}")

    if part.kind == "meta":
        raise ValueError("Use the deploy sequence editor for this part.")
    if part.kind in ("grid", "color") or part.key in ("slot_colors",):
        raise ValueError("Use Classic terminal calibrator for this part.")

    config = load_config()
    try:
        frame = _capture_frame(config)
    except AdbError as exc:
        raise AdbError(f"ADB screenshot failed: {exc}") from exc

    def refresh() -> np.ndarray:
        return _capture_frame(load_config())

    # Ensure frame size recorded.
    h, w = frame.shape[:2]
    if config.frame_width <= 0 or config.frame_height <= 0:
        config.frame_width = w
        config.frame_height = h

    if part.kind == "tap":
        suggested = _try_auto_point(config, frame, part)
        if suggested is not None:
            if messagebox.askyesno(
                "Detected point",
                f"Found a match for “{part.label}” at {suggested[0]}, {suggested[1]}.\n\n"
                "Use this point?",
                parent=master,
            ):
                config.tap_points[part.key] = [suggested[0], suggested[1]]
                save_calibrated(config)
                return f"Saved {part.key} tap {suggested} (auto-detect)"

        result, _used = pick_on_master(
            master,
            frame,
            mode="point",
            title=f"Calibrate: {part.label}",
            refresh_cb=refresh,
        )
        if result is None or len(result) < 2:
            raise ValueError("Calibration cancelled")
        config.tap_points[part.key] = [int(result[0]), int(result[1])]
        save_calibrated(config)
        return f"Saved {part.key} tap ({result[0]}, {result[1]})"

    if part.kind in ("roi", "template"):
        result, used = pick_on_master(
            master,
            frame,
            mode="roi",
            title=f"Calibrate: {part.label}",
            refresh_cb=refresh,
        )
        if result is None or len(result) < 4:
            raise ValueError("Calibration cancelled")
        x, y, rw, rh = (int(result[0]), int(result[1]), int(result[2]), int(result[3]))
        if part.kind == "roi" or part.key.endswith("_bar") or "roi" in part.description.lower():
            config.rois[part.key] = [x, y, rw, rh]
        if part.kind == "template" or part.key in (
            "home",
            "clan_chat",
            "donation_panel",
            "loading",
            "popup_dismiss",
            "popup",
            "attack_button",
            "donate_button",
            "return_home",
        ):
            _save_template_crop(config, used, (x, y, rw, rh), part)
            # Also store tap at center for button-like templates when useful.
            if part.key in ("attack_button", "donate_button", "return_home", "unranked_battle"):
                config.tap_points.setdefault(part.key, [x + rw // 2, y + rh // 2])
        elif part.kind == "roi":
            pass
        else:
            # Heuristic: ROI parts that are also templates in wizard.
            if part.key in config.templates or part.kind == "template":
                _save_template_crop(config, used, (x, y, rw, rh), part)
        save_calibrated(config)
        return f"Saved {part.key} region ({x},{y} {rw}×{rh})"

    raise ValueError(f"Unsupported part kind for in-app calibration: {part.kind}")


def part_supports_in_app(part: CalibrationPart) -> bool:
    """True for tap / ROI / template parts that the in-app picker can handle."""
    return part.kind in ("tap", "roi", "template")
