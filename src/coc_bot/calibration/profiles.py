"""Named interface snapshots and non-destructive calibration checks."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from coc_bot.control.backups import create_backup, normalize_backup_name, rename_backup, backups_root


def save_interface_profile(name, config):
    label = normalize_backup_name(name)
    folder = "profile_" + label
    if (backups_root() / folder).exists():
        raise ValueError("That profile already exists. Rename or delete it from Setup first.")
    backup = rename_backup(create_backup(), folder)
    (backup.path / "profile.json").write_text(json.dumps({
        "schema": 1, "label": label,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "frame": [config.frame_width, config.frame_height],
        "purpose": "Game interface version / screen layout",
    }, indent=2), encoding="utf-8")
    return backup


def check_calibration(config, actual_size=None):
    from coc_bot.calibration.schema import STEPS, part_is_configured
    issues = []
    if config.frame_width <= 0 or config.frame_height <= 0:
        issues.append("Screen size is missing. Complete Screen size in Setup.")
    for key, point in config.tap_points.items():
        if len(point) != 2 or not (0 <= point[0] < config.frame_width and 0 <= point[1] < config.frame_height):
            issues.append(f"{key}: tap is outside the calibrated screen.")
    for key, roi in config.rois.items():
        if len(roi) != 4 or not (0 <= roi[0] < 1 and 0 <= roi[1] < 1 and roi[2] > 0 and roi[3] > 0 and roi[0]+roi[2] <= 1.001 and roi[1]+roi[3] <= 1.001):
            issues.append(f"{key}: screen area is invalid.")
    for key, relative in config.templates.items():
        path = (config.templates_dir / relative).resolve()
        if not path.is_relative_to(config.templates_dir.resolve()) or not path.is_file():
            issues.append(f"{key}: reference image is missing or outside the template folder.")
    for step in STEPS.values():
        if step.step_id == "farm":
            continue
        for part in step.parts:
            if not part.optional and not part_is_configured(config, part):
                issues.append(f"Missing: {step.title} → {part.label}.")
    if actual_size and tuple(actual_size) != (config.frame_width, config.frame_height):
        issues.append(f"Latest screenshot is {actual_size[0]}×{actual_size[1]}; calibration was made at {config.frame_width}×{config.frame_height}. Verify it before running.")
    return issues
