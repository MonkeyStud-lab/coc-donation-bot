"""Browser calibration on immutable captures, with transactional template saves."""
from collections import OrderedDict
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import shutil
import tempfile
import uuid
from pathlib import Path
import cv2
from coc_bot.config import load_config, project_root, save_calibrated
from coc_bot.calibration.schema import STEPS, part_is_configured
from coc_bot.calibration.instructions import format_part_instruction
from coc_bot.calibration.grid_math import build_grid_entry, GRID_BAR_ROI_KEYS
from coc_bot.control.settings import RevisionConflict
from coc_bot.calibration.transactions import calibration_locked

TEMPLATE_TAPS = {
    "open_chat", "close_chat", "clan_chat_tab", "attack_button", "unranked_battle",
    "find_match", "return_home", "donate_button", "donation_elixir_button",
}


def calibration_revision():
    data = project_root() / "data"
    digest = hashlib.sha256()
    path = data / "calibrated.yaml"
    if path.exists():
        digest.update(path.read_bytes())
    for path in sorted((data / "templates").rglob("*.png")):
        digest.update(str(path.relative_to(data)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def checklist():
    config = load_config()
    return {"revision": calibration_revision(),
            "steps": [{"id": step.step_id, "label": step.title,
                       "parts": [asdict(p) | {
                           "configured": part_is_configured(config, p),
                           "instructions": format_part_instruction(step.step_id, p.key),
                       } for p in step.parts]} for step in STEPS.values()]}


class Captures:
    """At most eight originals; expired IDs cannot accidentally save newer frames."""
    def __init__(self):
        self.frames = OrderedDict()

    def add(self, frame):
        ident = uuid.uuid4().hex
        h, w = frame.shape[:2]
        ok, png = cv2.imencode(".png", frame)
        if not ok:
            raise ValueError("Cannot encode screenshot")
        meta = {"id": ident, "width": w, "height": h,
                "at": datetime.now(timezone.utc).isoformat(),
                "revision": calibration_revision()}
        config = load_config()
        meta["taps"] = (config.farm_deploy_sequence or {}).get("taps", [])
        meta["jitter"] = max(0, min(40, config.farm_deploy_jitter_px))
        self.frames[ident] = (frame.copy(), png.tobytes(), meta)
        while len(self.frames) > 8:
            self.frames.popitem(last=False)
        return meta

    def get(self, ident):
        if ident not in self.frames:
            raise ValueError("Screenshot expired. Capture again.")
        return self.frames[ident]

    @calibration_locked
    def save(self, ident, key, selection, expected, cols=7, rows=1, jitter=6):
        frame, _png, meta = self.get(ident)
        if expected != meta["revision"] or expected != calibration_revision():
            raise RevisionConflict("Calibration changed. Capture a fresh screenshot.")
        part = next((p for s in STEPS.values() for p in s.parts if p.key == key), None)
        if part is None:
            raise ValueError("Unknown calibration part")
        config = load_config()
        w, h = meta["width"], meta["height"]
        if key != "frame_width" and config.frame_width and (
                config.frame_width != w or config.frame_height != h):
            raise ValueError("Screen size changed. Calibrate screen size first.")
        def point(raw):
            if len(raw) != 2 or any(type(v) is not int for v in raw):
                raise ValueError("Select a point")
            x, y = raw
            if not (0 <= x < w and 0 <= y < h):
                raise ValueError("Selection is outside the screenshot")
            return x, y
        roi = None
        if key == "deploy_sequence":
            if not selection or len(selection) > 500:
                raise ValueError("Choose between 1 and 500 taps")
            taps = [list(point(p)) for p in selection]
            if not 0 <= jitter <= 40:
                raise ValueError("Farm deploy jitter must be between 0 and 40")
            config.farm_deploy_sequence = {"side": config.farm_deploy_side,
                                          "pan_swipes": config.farm_pan_swipes,
                                          "taps": taps}
        elif key == "frame_width":
            config.frame_width, config.frame_height = w, h
        elif part.kind == "tap" and len(selection) == 2:
            config.tap_points[key] = list(point(selection))
        else:
            if len(selection) != 4 or any(type(v) is not int for v in selection):
                raise ValueError("Draw a box")
            x, y, rw, rh = selection
            if not (0 <= x < w and 0 <= y < h and rw > 0 and rh > 0
                    and x + rw <= w and y + rh <= h):
                raise ValueError("Box must fit inside the screenshot")
            roi = (x, y, rw, rh)
            if part.kind == "color":
                config.colors[key] = [int(v) for v in frame[y + rh//2, x + rw//2]]
            elif part.kind == "grid":
                bar = GRID_BAR_ROI_KEYS[key]
                if bar not in config.rois:
                    raise ValueError("Calibrate the donation bar area first.")
                if not (1 <= cols <= 20 and 1 <= rows <= 10):
                    raise ValueError("Invalid grid rows or columns")
                config.grid[key] = build_grid_entry(roi, key, config, w, h, cols, rows)
            elif part.kind == "roi" or key.endswith("_bar") or key == "donation_elixir_selected":
                config.rois[key] = [x/w, y/h, rw/w, rh/h]
                if key == "donation_troop_bar":
                    config.rois.pop("donation_siege_bar", None)
            if part.kind == "tap":
                config.tap_points[key] = [x + rw//2, y + rh//2]
        # Build a complete disposable backup and use the existing journaled
        # two-file transaction. Failure cannot leave YAML and templates mismatched.
        from coc_bot.control.backups import CalibrationBackup, restore_backup
        data = project_root() / "data"
        data.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="web-calibration-", dir=data) as temp:
            staging = Path(temp)
            if config.templates_dir.exists():
                shutil.copytree(config.templates_dir, staging / "templates")
            else:
                (staging / "templates").mkdir()
            if roi and (part.kind == "template" or key in TEMPLATE_TAPS):
                x, y, rw, rh = roi
                relative = f"ui/{key}.png"
                out = staging / "templates" / relative
                out.parent.mkdir(parents=True, exist_ok=True)
                if not cv2.imwrite(str(out), frame[y:y+rh, x:x+rw]):
                    raise ValueError("Cannot save template")
                config.templates[key] = relative
                if key in ("attack_button", "donate_button", "return_home",
                           "unranked_battle", "open_chat"):
                    config.tap_points[key] = [x + rw//2, y + rh//2]
                if key == "donate_button":
                    config.rois.pop("request_header", None)
            if not config.frame_width:
                config.frame_width, config.frame_height = w, h
            save_calibrated(config, staging / "calibrated.yaml")
            restore_backup(CalibrationBackup(staging, "web-editor"), safety_snapshot=True)
        if key == "deploy_sequence":
            from coc_bot.control.settings import save_settings, revision
            save_settings({"farm_deploy_jitter_px": jitter}, revision())
        return checklist()
