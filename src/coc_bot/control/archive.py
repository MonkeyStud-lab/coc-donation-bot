"""Bounded calibration exchange. No arbitrary archive paths are extracted."""
import io
from pathlib import Path, PurePosixPath
import math
import struct
import tempfile
import zipfile
import yaml
from coc_bot.control.backups import CalibrationBackup, backups_root, normalize_backup_name

LIMIT = 50 * 1024 * 1024


def validate_payload(payload, staging):
    if not isinstance(payload, dict):
        raise ValueError("Calibration must be a mapping")
    w, h = payload.get("frame_width"), payload.get("frame_height")
    if type(w) is not int or type(h) is not int or not (0 < w <= 8192 and 0 < h <= 8192):
        raise ValueError("Invalid calibration screen size")
    def mapping(key):
        value = payload.get(key, {})
        if not isinstance(value, dict) or len(value) > 200 or any(not isinstance(k, str) for k in value):
            raise ValueError(f"Invalid {key}")
        return value
    def point(p):
        if not isinstance(p, list) or len(p) != 2 or any(type(v) is not int for v in p):
            raise ValueError("Invalid calibration tap")
        if not (0 <= p[0] < w and 0 <= p[1] < h):
            raise ValueError("Calibration tap outside screen")
    for p in mapping("tap_points").values():
        point(p)
    for roi in mapping("rois").values():
        if (not isinstance(roi, list) or len(roi) != 4 or
                any(type(v) not in (int, float) or not math.isfinite(v) for v in roi) or
                not (0 <= roi[0] < 1 and 0 <= roi[1] < 1 and roi[2] > 0 and roi[3] > 0
                     and roi[0]+roi[2] <= 1.001 and roi[1]+roi[3] <= 1.001)):
            raise ValueError("Invalid calibration screen area")
    for color in mapping("colors").values():
        if not isinstance(color, list) or len(color) != 3 or any(type(v) is not int or not 0 <= v <= 255 for v in color):
            raise ValueError("Invalid calibration color")
    for grid in mapping("grid").values():
        if not isinstance(grid, dict):
            raise ValueError("Invalid calibration grid")
        if any(type(grid.get(k)) is not int or not 1 <= grid[k] <= 30 for k in ("rows", "cols")):
            raise ValueError("Invalid grid rows or columns")
        if any(type(grid.get(k)) not in (int, float) or not math.isfinite(grid[k]) or abs(grid[k]) > 10
               for k in ("x", "y", "w", "h")) or grid["w"] <= 0 or grid["h"] <= 0:
            raise ValueError("Invalid grid area")
    sequence = payload.get("farm_deploy_sequence", {})
    if not isinstance(sequence, dict):
        raise ValueError("Invalid farm sequence")
    taps = sequence.get("taps", [])
    if not isinstance(taps, list) or len(taps) > 500:
        raise ValueError("Invalid farm taps")
    for p in taps:
        point(p)
    for relative in mapping("templates").values():
        if not isinstance(relative, str):
            raise ValueError("Invalid template filename")
        path = (staging / "templates" / relative).resolve()
        if not path.is_relative_to((staging / "templates").resolve()) or not path.is_file():
            raise ValueError("Template missing or outside template folder")
    import cv2
    import numpy as np
    for path in (staging / "templates").rglob("*.png"):
        content = path.read_bytes()
        if len(content) < 24 or content[:8] != b'\x89PNG\r\n\x1a\n':
            raise ValueError("Invalid PNG template")
        iw, ih = struct.unpack(">II", content[16:24])
        if not (0 < iw <= 8192 and 0 < ih <= 8192 and iw*ih <= 16000000):
            raise ValueError("Template image is too large")
        if cv2.imdecode(np.frombuffer(content, dtype=np.uint8), cv2.IMREAD_COLOR) is None:
            raise ValueError("Unreadable PNG template")


def export_calibration(backup):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        files = [backup.path / "calibrated.yaml", *(backup.path / "templates").rglob("*.png")]
        if sum(p.stat().st_size for p in files) > LIMIT:
            raise ValueError("Calibration archive exceeds 50 MB")
        for path in files:
            if not path.resolve().is_relative_to(backup.path.resolve()):
                raise ValueError("Unsafe backup file")
            archive.write(path, path.relative_to(backup.path).as_posix())
    return output.getvalue()


def import_calibration(content, name):
    name = normalize_backup_name(name)
    base = backups_root()
    base.mkdir(parents=True, exist_ok=True)
    target = base / name
    if target.exists():
        raise ValueError("A calibration with that name already exists")
    if len(content) > LIMIT:
        raise ValueError("Calibration archive exceeds 50 MB")
    with tempfile.TemporaryDirectory(prefix="archive-", dir=base) as tmp:
        staging = Path(tmp)
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                members = archive.infolist()
                if len(members) > 1000 or sum(m.file_size for m in members) > LIMIT:
                    raise ValueError("Calibration archive is too large")
                seen = set()
                for member in members:
                    path = PurePosixPath(member.filename)
                    canonical = member.filename.casefold()
                    if (canonical in seen or path.is_absolute() or ".." in path.parts
                            or ":" in member.filename or "\x00" in member.filename
                            or "\\" in member.filename or (member.external_attr >> 16) & 0o170000 == 0o120000):
                        raise ValueError("Unsafe archive member")
                    seen.add(canonical)
                    if member.is_dir():
                        continue
                    if not (member.filename == "calibrated.yaml" or (
                            path.parts[0] == "templates" and path.suffix.lower() == ".png")):
                        raise ValueError("Archive may contain only calibration YAML and PNG templates")
                    destination = staging.joinpath(*path.parts)
                    if not destination.resolve().is_relative_to(staging.resolve()):
                        raise ValueError("Unsafe archive path")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(archive.read(member))
        except zipfile.BadZipFile as exc:
            raise ValueError("Choose a valid calibration ZIP") from exc
        if not (staging / "calibrated.yaml").is_file():
            raise ValueError("Calibration YAML is missing")
        yaml_path = staging / "calibrated.yaml"
        if yaml_path.stat().st_size > 100000:
            raise ValueError("Calibration YAML is too large")
        try:
            source = yaml_path.read_text(encoding="utf-8")
            for count, event in enumerate(yaml.parse(source)):
                if count > 10000 or isinstance(event, yaml.events.AliasEvent):
                    raise ValueError("Calibration YAML is too complex")
            payload = yaml.safe_load(source)
        except (yaml.YAMLError, UnicodeError) as exc:
            raise ValueError("Invalid calibration YAML") from exc
        validate_payload(payload, staging)
        # Importing never replaces active calibration. Restore is a separate action.
        staging.rename(target)
    return CalibrationBackup(target, name)
