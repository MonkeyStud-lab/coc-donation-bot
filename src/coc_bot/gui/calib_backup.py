"""Backup and restore calibration YAML + template images."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from coc_bot.config import project_root

# Folder names under data/calibration_backups/ — keep filesystem-safe.
_BACKUP_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


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


def clear_live_calibration(root: Path | None = None) -> None:
    """
    Remove live ``calibrated.yaml`` and empty ``templates/``.

    Used by Dev first-launch preview after stashing a backup. Safe if missing.
    """
    root = root or project_root()
    yaml_path = calibrated_yaml_path(root)
    tmpl_path = templates_dir(root)
    if yaml_path.is_file():
        yaml_path.unlink()
    if tmpl_path.is_dir():
        shutil.rmtree(tmpl_path)
    tmpl_path.mkdir(parents=True, exist_ok=True)


def get_backup(stamp: str, root: Path | None = None) -> CalibrationBackup | None:
    """Return a backup by folder name, or ``None`` if missing."""
    path = backups_root(root) / stamp
    if not path.is_dir() or not (path / "calibrated.yaml").is_file():
        return None
    return CalibrationBackup(path=path, stamp=stamp)


def restore_backup(
    backup: CalibrationBackup,
    root: Path | None = None,
    *,
    safety_snapshot: bool = True,
) -> None:
    """
    Replace live ``calibrated.yaml`` and ``templates/`` from ``backup``.

    Creates a safety snapshot of the current live files first (best-effort)
    under ``data/calibration_backups/pre_restore_<stamp>/`` so a bad restore
    is still recoverable, unless ``safety_snapshot`` is False.
    """
    root = root or project_root()
    if not backup.has_yaml():
        raise FileNotFoundError(f"Backup missing calibrated.yaml: {backup.path}")

    if safety_snapshot:
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


def normalize_backup_name(raw: str) -> str:
    """Validate and normalize a backup folder name; raise ValueError if invalid."""
    name = str(raw or "").strip().replace(" ", "_")
    if not name:
        raise ValueError("Name cannot be empty.")
    if name in (".", "..") or "/" in name or "\\" in name:
        raise ValueError("Name cannot contain path separators.")
    if not _BACKUP_NAME_RE.match(name):
        raise ValueError(
            "Use letters, numbers, dots, dashes, or underscores (max 80 chars)."
        )
    return name


def rename_backup(backup: CalibrationBackup, new_name: str) -> CalibrationBackup:
    """Rename a backup folder. Raises ValueError / OSError on failure."""
    stamp = normalize_backup_name(new_name)
    if stamp == backup.stamp:
        return backup
    dest = backup.path.parent / stamp
    if dest.exists():
        raise ValueError(f"A backup named “{stamp}” already exists.")
    backup.path.rename(dest)
    return CalibrationBackup(path=dest, stamp=stamp)


def delete_backup(backup: CalibrationBackup) -> None:
    """Permanently delete a backup folder."""
    if not backup.path.is_dir():
        raise FileNotFoundError(f"Backup not found: {backup.path}")
    # Safety: only delete folders that look like our backups (contain calibrated.yaml).
    if not backup.has_yaml():
        raise ValueError(f"Refusing to delete folder without calibrated.yaml: {backup.path}")
    if backup.path.parent.resolve() != backups_root().resolve():
        raise ValueError(f"Refusing to delete outside backups directory: {backup.path}")
    shutil.rmtree(backup.path)
