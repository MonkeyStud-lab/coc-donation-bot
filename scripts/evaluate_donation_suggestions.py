"""Evaluate donation setup suggestions on a private, hash-verified review batch.

Never trains on partial object boxes, changes calibration, or contacts Android.
The manifest is an array of {id,image,sha256,session,screen,boxes}; image paths
are relative to images/. Keep every non-panel screen as a negative example.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from coc_bot.vision.donation_calibration import suggest_donation


def iou(a, b):
    x, y = max(a[0], b[0]), max(a[1], b[1])
    right, bottom = min(a[0]+a[2], b[0]+b[2]), min(a[1]+a[3], b[1]+b[3])
    intersection = max(0, right-x) * max(0, bottom-y)
    return intersection / max(1, a[2]*a[3]+b[2]*b[3]-intersection)


def union(boxes):
    x, y = min(b[0] for b in boxes), min(b[1] for b in boxes)
    return [x, y, max(b[0]+b[2] for b in boxes)-x, max(b[1]+b[3] for b in boxes)-y]


def evaluate(batch, output):
    batch, output = Path(batch).resolve(), Path(output).resolve()
    rows = json.loads((batch / "manifest.json").read_text(encoding="utf-8"))
    if len({r['id'] for r in rows}) != len(rows):
        raise ValueError("Duplicate review IDs")
    if not rows or any(not r.get('session') or r.get('screen') in (None, 'unreviewed') for r in rows):
        raise ValueError("Every evaluation image needs a reviewed screen and session")
    if output.exists():
        raise ValueError("Choose a new output directory")
    results, counts = [], Counter()
    for row in rows:
        path = (batch / "images" / row['image']).resolve()
        if not path.is_relative_to(batch / "images"):
            raise ValueError("Image outside batch")
        if hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']:
            raise ValueError("Image changed: " + row['image'])
        frame = cv2.imread(str(path))
        if frame is None:
            raise ValueError("Unreadable image")
        result = suggest_donation(frame)
        panel = row['screen'] == 'donation_panel'
        counts[('positive' if panel else 'negative') + ('_accepted' if result['supported'] else '_refused')] += 1
        overlaps = {}
        targets = {'donation_elixir_button': 'resource_toggle_elixir',
                   'troop_bar': 'donation_troop_slot', 'spell_bar': 'donation_spell_slot'}
        for proposal in result['proposals']:
            label = targets.get(proposal['part'])
            boxes = [b['xywh'] for b in row.get('boxes', []) if b['label'] == label]
            if boxes:
                overlaps[proposal['part']] = round(iou(proposal['selection'], union(boxes)), 4)
        results.append({'id': row['id'], 'session': row['session'], 'screen': row['screen'],
                        'proposal': result, 'box_union_iou': overlaps})
    output.mkdir(parents=True)
    report = {'method': 'donation-reference-v1', 'scope': 'setup proposals only; never navigation',
              'frames': len(rows), 'sessions': len({r['session'] for r in rows}), 'counts': dict(counts),
              'reference_source_ids': [r['id'] for r in rows if r.get('reference_source')],
              'limits': ['One device and the inspected English layout; not a general object detector.',
                         'Reference-source and same-layout images are not independent generalization evidence.',
                         'Resized images are robustness checks, not additional recording sessions.',
                         'Partial object annotations remain unapproved for detector training.'],
              'results': results}
    (output / 'evaluation.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return {k: v for k, v in report.items() if k != 'results'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(evaluate(args.batch, args.output), indent=2))
