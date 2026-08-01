"""Copy recent logs and export a debug bundle for troubleshooting."""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path

from coc_bot.calibration.wizard import STEP_IDS, STEPS, CalibrationWizard
from coc_bot.config import load_config, project_root


def export_debug_bundle(log_lines: list[str]) -> Path:
    """
    Write a folder under ``data/debug/export_TIMESTAMP/`` with logs + status.

    Returns the export directory path.
    """
    root = project_root()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = root / "data" / "debug" / f"export_{stamp}"
    out.mkdir(parents=True, exist_ok=True)

    (out / "activity.log").write_text("\n".join(log_lines[-500:]) + "\n", encoding="utf-8")

    config = load_config()
    adb_text = ""
    try:
        result = subprocess.run(
            ["adb", "devices", "-l"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        adb_text = (result.stdout or "") + (result.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as exc:
        adb_text = f"(adb devices failed: {exc})\n"
    (out / "adb_devices.txt").write_text(adb_text, encoding="utf-8")

    try:
        wizard = CalibrationWizard(config)
        status = wizard.step_status()
    except Exception as exc:  # noqa: BLE001
        status = {sid: False for sid in STEP_IDS}
        status_note = f"status error: {exc}"
    else:
        status_note = ""

    lines = [
        f"export_utc={stamp}",
        f"adb_device={config.adb_device}",
        f"theme={config.gui_theme}",
        f"timing_preset={config.gui_timing_preset}",
        f"dev_options={config.gui_dev_options}",
        f"calibrated={config.calibrated}",
        f"farm_calibrated={config.farm_calibrated}",
        f"frame={config.frame_width}x{config.frame_height}",
        status_note,
        "",
        "calibration_steps:",
    ]
    for sid in STEP_IDS:
        step = STEPS[sid]
        ok = bool(status.get(sid))
        lines.append(f"  {sid}: {'ok' if ok else 'missing'} — {step.title}")
    (out / "status.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out
