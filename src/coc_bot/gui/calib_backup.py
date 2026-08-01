"""Backup and restore calibration YAML + template images."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from coc_bot.config import project_root


@dataclass(frozen=True)
class CalibrationBackup:
    """One dated snapshot under ``data/calibration_backups/``."""

    path: Path
    stamp: str

    @property
    def label(self) -> str:
        return self.stamp

    def has_yaml(self) -> bool:
        return (self.path / "calibrated.yaml").is_file()


def backups_root(root: Path | None = None) -> Path:
    return (root or project_root()) / "data" / "calibration_backups"


def calibrated_yaml_path(root: Path | None = None) -> Path:
    return (root or project_root()) / "data" / "calibrated.yaml"


def templates_dir(root: Path | None = None) -> Path:
    return (root or project_root()) / "data" / "templates"


def list_backups(root: Path | None = None) -> list[CalibrationBackup]:
    """Return backups newest-first."""
    base = backups_root(root)
    if not base.is_dir():
        return []
    found: list[CalibrationBackup] = []
    for child in base.iterdir():
        if not child.is_dir():
            continue
        if not (child / "calibrated.yaml").is_file():
            continue
        found.append(CalibrationBackup(path=child, stamp=child.name))
    found.sort(key=lambda b: b.stamp, reverse=True)
    return found


def create_backup(root: Path | None = None, *, stamp_prefix: str = "") -> CalibrationBackup:
    """
    Copy ``calibrated.yaml`` and ``templates/`` into a new dated folder.

    Raises ``FileNotFoundError`` if there is nothing to back up.
    """
    root = root or project_root()
    yaml_src = calibrated_yaml_path(root)
    tmpl_src = templates_dir(root)
    if not yaml_src.is_file() and not (tmpl_src.is_dir() and any(tmpl_src.iterdir())):
        raise FileNotFoundError("No calibration files found to back up.")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    if stamp_prefix:
        stamp = f"{stamp_prefix}{stamp}"
    dest = backups_root(root) / stamp
    # Avoid clobbering if two backups land in the same second.
    if dest.exists():
        n = 2
        while True:
            alt = backups_root(root) / f"{stamp}_{n}"
            if not alt.exists():
                dest = alt
                stamp = dest.name
                break
            n += 1
    dest.mkdir(parents=True, exist_ok=False)

    if yaml_src.is_file():
        shutil.copy2(yaml_src, dest / "calibrated.yaml")
    if tmpl_src.is_dir():
        shutil.copytree(tmpl_src, dest / "templates")

    return CalibrationBackup(path=dest, stamp=stamp)


def restore_backup(backup: CalibrationBackup, root: Path | None = None) -> None:
    """
    Replace live ``calibrated.yaml`` and ``templates/`` from ``backup``.

    Creates a safety snapshot of the current live files first (best-effort)
    under ``data/calibration_backups/pre_restore_<stamp>/`` so a bad restore
    is still recoverable.
    """
    root = root or project_root()
    if not backup.has_yaml():
        raise FileNotFoundError(f"Backup missing calibrated.yaml: {backup.path}")

    # Safety copy of whatever is live now (ignore if empty / missing).
    try:
        create_backup(root, stamp_prefix="pre_restore_")
    except FileNotFoundError:
        pass
    except OSError:
        # Still proceed with restore; user explicitly asked to restore.
        pass

    yaml_dst = calibrated_yaml_path(root)
    tmpl_dst = templates_dir(root)
    yaml_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(backup.path / "calibrated.yaml", yaml_dst)

    tmpl_src = backup.path / "templates"
    if tmpl_dst.exists():
        shutil.rmtree(tmpl_dst)
    if tmpl_src.is_dir():
        shutil.copytree(tmpl_src, tmpl_dst)
    else:
        tmpl_dst.mkdir(parents=True, exist_ok=True)
