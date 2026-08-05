"""In-app Setup calibration using InteractivePicker (all part kinds)."""

from __future__ import annotations

from typing import Callable

import cv2
import numpy as np
from loguru import logger
from tkinter import messagebox, simpledialog

from coc_bot.adb.capture import ScreenCapture
from coc_bot.adb.client import AdbClient, AdbError
from coc_bot.calibration.grid_math import (
    GRID_BAR_ROI_KEYS,
    GRID_DEFAULTS,
    build_grid_entry,
)
from coc_bot.calibration.picker import InteractivePicker
from coc_bot.calibration.template_capture import sample_center_color
from coc_bot.calibration.wizard import CalibrationPart, STEPS, part_is_configured
from coc_bot.config import BotConfig, load_config, save_calibrated
from coc_bot.gui.calib_instructions import format_part_instruction
from coc_bot.vision.rois import normalize_roi

# Taps that benefit from an image crop + center tap (wizard-style).
_TEMPLATE_TAP_KEYS = frozenset(
    {
        "open_chat",
        "close_chat",
        "attack_button",
        "unranked_battle",
        "find_match",
        "return_home",
        "donate_button",
        "donation_elixir_button",
    }
)


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
        "open_chat": "open_chat",
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


def _normalized_roi(
    coords: tuple[int, int, int, int], frame_w: int, frame_h: int
) -> list[float]:
    nr = normalize_roi(*coords, frame_w, frame_h)
    return [nr.x, nr.y, nr.w, nr.h]


def _prompt_grid_counts(master, grid_key: str, config: BotConfig) -> tuple[int, int] | None:
    """Ask for columns/rows; return None if cancelled."""
    defaults = GRID_DEFAULTS.get(grid_key, (7, 1))
    current = dict((config.grid or {}).get(grid_key) or {})
    default_cols = int(current.get("cols") or defaults[0])
    default_rows = int(current.get("rows") or defaults[1])
    cols = simpledialog.askinteger(
        "Grid columns",
        f"Columns for {grid_key} (slots per row):",
        parent=master,
        initialvalue=default_cols,
        minvalue=1,
        maxvalue=20,
    )
    if cols is None:
        return None
    rows = simpledialog.askinteger(
        "Grid rows",
        f"Rows for {grid_key}:",
        parent=master,
        initialvalue=default_rows,
        minvalue=1,
        maxvalue=10,
    )
    if rows is None:
        return None
    return int(cols), int(rows)


def _ensure_frame_size(config: BotConfig, frame: np.ndarray) -> None:
    h, w = frame.shape[:2]
    if config.frame_width <= 0 or config.frame_height <= 0:
        config.frame_width = w
        config.frame_height = h


def _calibrate_frame_size(master, config: BotConfig, frame: np.ndarray) -> str:
    h, w = frame.shape[:2]
    if config.frame_width > 0 and config.frame_height > 0:
        if not messagebox.askyesno(
            "Screen size",
            f"Current size is {config.frame_width}×{config.frame_height}.\n"
            f"Screenshot is {w}×{h}.\n\nUpdate screen size?",
            parent=master,
        ):
            return f"Kept frame size {config.frame_width}×{config.frame_height}"
    config.frame_width = w
    config.frame_height = h
    save_calibrated(config)
    return f"Saved screen size {w}×{h}"


def _calibrate_color(
    master,
    config: BotConfig,
    frame: np.ndarray,
    part: CalibrationPart,
    refresh: Callable[[], np.ndarray],
) -> str:
    result, used = pick_on_master(
        master,
        frame,
        mode="roi",
        title=f"Color: {part.label}",
        refresh_cb=refresh,
    )
    if result is None or len(result) < 4:
        raise ValueError("Calibration cancelled")
    roi = (int(result[0]), int(result[1]), int(result[2]), int(result[3]))
    bgr = sample_center_color(used, roi)
    config.colors[part.key] = bgr
    save_calibrated(config)
    return f"Saved {part.key} color BGR {bgr}"


def _calibrate_grid(
    master,
    config: BotConfig,
    frame: np.ndarray,
    part: CalibrationPart,
    refresh: Callable[[], np.ndarray],
) -> str:
    bar_key = GRID_BAR_ROI_KEYS.get(part.key)
    if not bar_key or bar_key not in config.rois:
        raise ValueError(
            f"Calibrate the donation panel bar area ({bar_key or part.key}) first "
            "(Setup → Donation panel)."
        )
    result, used = pick_on_master(
        master,
        frame,
        mode="roi",
        title=f"Grid: {part.label}",
        refresh_cb=refresh,
    )
    if result is None or len(result) < 4:
        raise ValueError("Calibration cancelled")
    roi = (int(result[0]), int(result[1]), int(result[2]), int(result[3]))
    counts = _prompt_grid_counts(master, part.key, config)
    if counts is None:
        raise ValueError("Calibration cancelled")
    cols, rows = counts
    fh, fw = used.shape[:2]
    entry = build_grid_entry(roi, part.key, config, fw, fh, cols, rows)
    grid = dict(config.grid or {})
    grid[part.key] = entry
    config.grid = grid
    save_calibrated(config)
    return (
        f"Saved {part.key} grid {cols}×{rows} "
        f"(x={entry['x']:.3f} y={entry['y']:.3f} w={entry['w']:.3f} h={entry['h']:.3f})"
    )


def _calibrate_tap(
    master,
    config: BotConfig,
    frame: np.ndarray,
    part: CalibrationPart,
    refresh: Callable[[], np.ndarray],
) -> str:
    # Prefer crop+center for bubble/button taps when user wants an image.
    if part.key in _TEMPLATE_TAP_KEYS:
        use_crop = messagebox.askyesno(
            part.label,
            f"How do you want to teach “{part.label}”?\n\n"
            "Yes (recommended) = draw a box around it "
            "(saves a picture and taps the center).\n"
            "No = click once in the center of it.",
            parent=master,
        )
        if use_crop:
            result, used = pick_on_master(
                master,
                frame,
                mode="roi",
                title=f"Calibrate: {part.label}",
                refresh_cb=refresh,
            )
            if result is None or len(result) < 4:
                raise ValueError("Calibration cancelled")
            x, y, rw, rh = (
                int(result[0]),
                int(result[1]),
                int(result[2]),
                int(result[3]),
            )
            _save_template_crop(config, used, (x, y, rw, rh), part)
            cx, cy = x + rw // 2, y + rh // 2
            config.tap_points[part.key] = [cx, cy]
            save_calibrated(config)
            return f"Saved {part.key} template + tap ({cx}, {cy})"

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


def _calibrate_roi_or_template(
    master,
    config: BotConfig,
    frame: np.ndarray,
    part: CalibrationPart,
    refresh: Callable[[], np.ndarray],
) -> str:
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
    fh, fw = used.shape[:2]

    if part.kind == "roi" or part.key.endswith("_bar"):
        config.rois[part.key] = _normalized_roi((x, y, rw, rh), fw, fh)
        if part.key == "donation_troop_bar":
            config.rois.pop("donation_siege_bar", None)

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
        "open_chat",
        "unranked_battle",
    ):
        _save_template_crop(config, used, (x, y, rw, rh), part)
        if part.key in (
            "attack_button",
            "donate_button",
            "return_home",
            "unranked_battle",
            "open_chat",
        ):
            config.tap_points.setdefault(part.key, [x + rw // 2, y + rh // 2])
        if part.key == "donate_button":
            config.rois.pop("request_header", None)

    save_calibrated(config)
    return f"Saved {part.key} region ({x},{y} {rw}×{rh})"


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

    if part.key == "deploy_sequence":
        raise ValueError("Use the farm deploy sequence editor for this part.")

    prep = format_part_instruction(step_id, part.key)
    if not messagebox.askokcancel(
        "Get Clash ready",
        f"{prep}\n\n"
        "Click OK when Clash looks right — the bot will take a screenshot next.\n"
        "Cancel to stop.",
        parent=master,
    ):
        raise ValueError("Calibration cancelled")

    config = load_config()
    try:
        frame = _capture_frame(config)
    except AdbError as exc:
        raise AdbError(f"ADB screenshot failed: {exc}") from exc

    def refresh() -> np.ndarray:
        return _capture_frame(load_config())

    _ensure_frame_size(config, frame)

    if part.key == "frame_width" or (part.kind == "meta" and part.key == "frame_width"):
        return _calibrate_frame_size(master, config, frame)

    if part.kind == "color":
        return _calibrate_color(master, config, frame, part, refresh)

    if part.kind == "grid":
        return _calibrate_grid(master, config, frame, part, refresh)

    if part.kind == "tap":
        return _calibrate_tap(master, config, frame, part, refresh)

    if part.kind in ("roi", "template"):
        return _calibrate_roi_or_template(master, config, frame, part, refresh)

    if part.kind == "meta":
        raise ValueError(f"Unsupported meta part for in-app calibration: {part.key}")

    raise ValueError(f"Unsupported part kind for in-app calibration: {part.kind}")


def part_supports_in_app(part: CalibrationPart) -> bool:
    """True for every Setup part that can be calibrated in the GUI."""
    if part.key == "deploy_sequence":
        return True  # Handled by farm deploy editor in the app.
    if part.kind == "meta":
        return part.key == "frame_width"
    return part.kind in ("tap", "roi", "template", "color", "grid")


def should_calibrate_part(master, part: CalibrationPart, config: BotConfig | None = None) -> bool:
    """Ask before optional parts; always True for required parts."""
    if part.key == "deploy_sequence":
        return False  # Caller opens the deploy editor separately.
    if not part.optional:
        return True
    config = config or load_config()
    already = part_is_configured(config, part)
    prompt = (
        f"“{part.label}” is already set. Recalibrate this optional item?"
        if already
        else f"Calibrate optional “{part.label}”?"
    )
    return bool(messagebox.askyesno("Optional calibration", prompt, parent=master))
