#!/usr/bin/env python
"""
Pre-annotate recorded frames with today's heuristics for Label Studio.

Turns the labeling job from "draw every box" into "fix the wrong ones".

Inputs
  data/frames/<session>/        from `python -m coc_bot --record`
  data/labels.yaml              class schema + calibration-key -> class map
  data/calibrated.yaml          current templates / tap points / ROIs

Outputs
  <out>/label_config.xml        Label Studio labeling interface (import once)
  <out>/tasks.json              Label Studio tasks with `predictions` (import)
  <out>/summary.txt             what got pre-annotated, per class

Usage
  # 1. Emit the labeling config and tasks for every session:
  python scripts/preannotate.py --out data/labelstudio

  # 2. Only some sessions, and only frames the heuristics called unknown:
  python scripts/preannotate.py --session 20260919_2210 --only-unknown

  # 3. In Label Studio: create project -> Labeling Setup -> Code -> paste
  #    label_config.xml. Settings -> Cloud Storage -> Local files, absolute
  #    path = <repo>/data/frames, then Import tasks.json.
  #    (Set LABEL_STUDIO_LOCAL_FILES_SERVING_ENABLED=true and
  #     LABEL_STUDIO_LOCAL_FILES_DOCUMENT_ROOT=<repo>/data before starting it.)

Image URLs in tasks.json use Label Studio's local-files scheme:
  /data/local-files/?d=frames/<session>/<file>
Pass --image-root to change the prefix if your document root differs.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from coc_bot.config import load_config  # noqa: E402
from coc_bot.vision.matcher import TemplateMatcher  # noqa: E402
from coc_bot.vision.rois import ROI, denormalize_roi  # noqa: E402

MODEL_VERSION = "heuristic-v0"
# Box drawn around a tap point that has no template (fraction of frame height).
TAP_BOX_FRAC = 0.045


# --------------------------------------------------------------------- schema


def load_schema(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        schema = yaml.safe_load(f)
    flat: list[str] = []
    for group in schema["classes"].values():
        flat.extend(group)
    schema["_flat_classes"] = flat
    return schema


def label_config_xml(schema: dict) -> str:
    """Label Studio interface: rectangle labels + one screen choice per frame."""
    rects = "\n".join(f'    <Label value="{c}"/>' for c in schema["_flat_classes"])
    screens = "\n".join(f'    <Choice value="{s}"/>' for s in schema["screens"])
    return f"""<View>
  <Header value="Screen"/>
  <Choices name="screen" toName="image" choice="single" showInline="true">
{screens}
  </Choices>
  <Header value="UI elements — label what you would TAP or what IDENTIFIES the screen"/>
  <Image name="image" value="$image" zoom="true" zoomControl="true"/>
  <RectangleLabels name="label" toName="image" strokeWidth="2" canRotate="false">
{rects}
  </RectangleLabels>
</View>
"""


# ------------------------------------------------------------ pre-annotation


class HeuristicAnnotator:
    """Run the current calibration-based detectors over a frame -> boxes."""

    def __init__(self, schema: dict) -> None:
        self.schema = schema
        self.config = load_config()
        self.matcher = TemplateMatcher(threshold=self.config.template_threshold)
        self.templates: dict[str, np.ndarray] = {}
        for key in schema["from_calibration"]["templates"]:
            rel = self.config.templates.get(key)
            if not rel:
                continue
            p = self.config.templates_dir / rel
            if not p.exists():
                p = self.config.data_dir.parent / rel
            img = cv2.imread(str(p), cv2.IMREAD_COLOR) if p.exists() else None
            if img is not None:
                self.templates[key] = img
        self.calib_w = int(self.config.frame_width or 0)
        self.calib_h = int(self.config.frame_height or 0)

    # ---- helpers

    def _scale(self, x: float, y: float, w: int, h: int) -> tuple[float, float]:
        if self.calib_w > 0 and self.calib_h > 0 and (self.calib_w != w or self.calib_h != h):
            return x * w / self.calib_w, y * h / self.calib_h
        return x, y

    def _same_resolution(self, w: int, h: int) -> bool:
        return self.calib_w == w and self.calib_h == h

    # ---- detectors

    def annotate(self, frame: np.ndarray) -> list[dict]:
        h, w = frame.shape[:2]
        boxes: list[dict] = []
        boxes += self._from_templates(frame)
        boxes += self._from_tap_points(w, h)
        boxes += self._from_rois(w, h)
        boxes += self._from_blobs(frame)
        return boxes

    def _from_templates(self, frame: np.ndarray) -> list[dict]:
        out: list[dict] = []
        mapping = self.schema["from_calibration"]["templates"]
        for key, tpl in self.templates.items():
            cls = mapping[key]
            if key == "donate_button":
                matches = self.matcher.find_all(
                    frame, tpl, threshold=self.config.donate_button_threshold, max_matches=6
                )
            else:
                m = self.matcher.find(frame, tpl)
                matches = [m] if m else []
            for m in matches:
                out.append(_box(cls, m.x, m.y, m.width, m.height, float(m.confidence), f"template:{key}"))
        return out

    def _from_tap_points(self, w: int, h: int) -> list[dict]:
        out: list[dict] = []
        mapping = self.schema["from_calibration"]["tap_points"]
        size = max(24, int(h * TAP_BOX_FRAC))
        for key, cls in mapping.items():
            pt = self.config.tap_points.get(key)
            if not pt or len(pt) < 2:
                continue
            # Tap points are only meaningful on the screen they belong to; they
            # will be wrong on other screens. Low score so reviewers look twice.
            x, y = self._scale(float(pt[0]), float(pt[1]), w, h)
            out.append(_box(cls, x - size / 2, y - size / 2, size, size, 0.30, f"tap_point:{key}"))
        return out

    def _from_rois(self, w: int, h: int) -> list[dict]:
        out: list[dict] = []
        mapping = self.schema["from_calibration"]["rois"]
        for key, cls in mapping.items():
            raw = self.config.rois.get(key)
            if not raw or len(raw) < 4:
                continue
            x, y, rw, rh = denormalize_roi(ROI(*raw), w, h)
            out.append(_box(cls, x, y, rw, rh, 0.30, f"roi:{key}"))
        return out

    def _from_blobs(self, frame: np.ndarray) -> list[dict]:
        """Colour-blob finders that exist today (Attack! chip, orange < tab)."""
        out: list[dict] = []
        h, w = frame.shape[:2]
        size = max(28, int(h * TAP_BOX_FRAC))
        try:
            from coc_bot.attack.navigator import AttackNavigator

            nav = AttackNavigator(self.config, None, None, self.matcher, None)  # type: ignore[arg-type]
            blob = nav._find_attack_button_blob(frame)  # noqa: SLF001
            if blob is not None:
                bx, by = blob
                out.append(_box("btn_attack", bx - size, by - size / 2, size * 2, size, 0.60, "blob:attack"))
        except Exception:  # noqa: BLE001
            pass
        try:
            from coc_bot.donation.navigator import Navigator

            dnav = Navigator(self.config, None, None, self.matcher)  # type: ignore[arg-type]
            tab = dnav.find_close_chat_tab(frame)
            if tab is not None:
                tx, ty = tab
                out.append(_box("btn_close_chat", tx - size / 2, ty - size, size, size * 2, 0.60, "blob:close_chat"))
        except Exception:  # noqa: BLE001
            pass
        return out


def _box(cls: str, x: float, y: float, w: float, h: float, score: float, source: str) -> dict:
    return {"cls": cls, "x": float(x), "y": float(y), "w": float(w), "h": float(h), "score": score, "source": source}


def _dedupe(boxes: list[dict], iou_thresh: float = 0.6) -> list[dict]:
    """Same class + heavy overlap → keep the higher score."""
    boxes = sorted(boxes, key=lambda b: -b["score"])
    kept: list[dict] = []
    for b in boxes:
        if any(k["cls"] == b["cls"] and _iou(k, b) > iou_thresh for k in kept):
            continue
        kept.append(b)
    return kept


def _iou(a: dict, b: dict) -> float:
    ax2, ay2 = a["x"] + a["w"], a["y"] + a["h"]
    bx2, by2 = b["x"] + b["w"], b["y"] + b["h"]
    iw = max(0.0, min(ax2, bx2) - max(a["x"], b["x"]))
    ih = max(0.0, min(ay2, by2) - max(a["y"], b["y"]))
    inter = iw * ih
    union = a["w"] * a["h"] + b["w"] * b["h"] - inter
    return inter / union if union > 0 else 0.0


# ----------------------------------------------------------- Label Studio io


def ls_result(boxes: list[dict], screen_tag: str, w: int, h: int) -> list[dict]:
    result: list[dict] = []
    for i, b in enumerate(boxes):
        x = max(0.0, min(100.0, b["x"] / w * 100))
        y = max(0.0, min(100.0, b["y"] / h * 100))
        bw = max(0.0, min(100.0 - x, b["w"] / w * 100))
        bh = max(0.0, min(100.0 - y, b["h"] / h * 100))
        if bw <= 0 or bh <= 0:
            continue
        result.append(
            {
                "id": f"pre{i}",
                "from_name": "label",
                "to_name": "image",
                "type": "rectanglelabels",
                "original_width": w,
                "original_height": h,
                "image_rotation": 0,
                "score": b["score"],
                "value": {
                    "x": x,
                    "y": y,
                    "width": bw,
                    "height": bh,
                    "rotation": 0,
                    "rectanglelabels": [b["cls"]],
                },
            }
        )
    result.append(
        {
            "id": "prescreen",
            "from_name": "screen",
            "to_name": "image",
            "type": "choices",
            "value": {"choices": [screen_tag]},
        }
    )
    return result


def iter_frames(frames_root: Path, sessions: list[str] | None):
    for session_dir in sorted(frames_root.iterdir()):
        if not session_dir.is_dir():
            continue
        if sessions and session_dir.name not in sessions:
            continue
        index = session_dir / "index.jsonl"
        if not index.exists():
            continue
        with open(index, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                rec["_session"] = session_dir.name
                rec["_path"] = session_dir / rec["file"]
                yield rec


# ------------------------------------------------------------------- main


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--frames", type=Path, default=ROOT / "data" / "frames")
    ap.add_argument("--labels", type=Path, default=ROOT / "data" / "labels.yaml")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "labelstudio")
    ap.add_argument("--session", action="append", help="Only these session folder names (repeatable)")
    ap.add_argument("--only-unknown", action="store_true", help="Only frames the heuristics called unknown")
    ap.add_argument("--limit", type=int, default=None, help="Stop after N frames")
    ap.add_argument(
        "--image-root",
        default="/data/local-files/?d=frames",
        help="URL prefix for images in tasks.json (Label Studio local-files scheme)",
    )
    ap.add_argument("--no-heuristics", action="store_true", help="Tasks only, no pre-annotations")
    args = ap.parse_args()

    schema = load_schema(args.labels)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "label_config.xml").write_text(label_config_xml(schema), encoding="utf-8")

    annotator = None if args.no_heuristics else HeuristicAnnotator(schema)
    screen_map = schema["screen_from_heuristic"]

    tasks: list[dict] = []
    per_class: Counter[str] = Counter()
    per_source: Counter[str] = Counter()
    per_screen: Counter[str] = Counter()
    n_frames = 0
    n_missing = 0

    for rec in iter_frames(args.frames, args.session):
        if args.only_unknown and rec.get("screen") != "unknown":
            continue
        if args.limit is not None and n_frames >= args.limit:
            break
        path: Path = rec["_path"]
        if not path.exists():
            n_missing += 1
            continue
        frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if frame is None:
            n_missing += 1
            continue
        h, w = frame.shape[:2]
        n_frames += 1

        screen_tag = screen_map.get(rec.get("screen", "none"), "other")
        per_screen[screen_tag] += 1

        boxes: list[dict] = []
        if annotator is not None:
            boxes = _dedupe(annotator.annotate(frame))
            for b in boxes:
                per_class[b["cls"]] += 1
                per_source[b["source"].split(":")[0]] += 1

        task = {
            "data": {
                "image": f"{args.image_root}/{rec['_session']}/{rec['file']}",
                "session": rec["_session"],
                "seq": rec["seq"],
                "heuristic_screen": rec.get("screen"),
                "reason": ",".join(rec.get("reason", [])),
                "resolution": f"{w}x{h}",
            },
            "predictions": [
                {
                    "model_version": MODEL_VERSION,
                    "score": float(np.mean([b["score"] for b in boxes])) if boxes else 0.0,
                    "result": ls_result(boxes, screen_tag, w, h),
                }
            ],
        }
        tasks.append(task)

    (args.out / "tasks.json").write_text(json.dumps(tasks, indent=1), encoding="utf-8")

    lines = [
        f"frames: {n_frames} (missing/unreadable: {n_missing})",
        "",
        "frame screen tags (from heuristic verdict):",
        *(f"  {k:18s} {v}" for k, v in per_screen.most_common()),
        "",
        "pre-annotated boxes per class:",
        *(f"  {k:26s} {v}" for k, v in per_class.most_common()),
        "",
        "boxes per source:",
        *(f"  {k:12s} {v}" for k, v in per_source.most_common()),
        "",
        "classes in schema with ZERO pre-annotations (you will draw these from scratch):",
        *(f"  {c}" for c in schema["_flat_classes"] if per_class[c] == 0),
    ]
    (args.out / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\nwrote {args.out / 'label_config.xml'}\nwrote {args.out / 'tasks.json'} ({len(tasks)} tasks)")


if __name__ == "__main__":
    main()
