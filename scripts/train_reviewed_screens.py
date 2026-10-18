"""Train a private, observation-only screen baseline from an approved UI batch.

No ADB calls, bot configuration changes, or object-training labels are used.
Entire sessions are held out; visually similar training frames are then purged.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from coc_bot.vision.screen_model import FEATURE_VERSION, ScreenModel, screen_features
from train_screen_model import fit


def perceptual_hash(frame):
    gray = cv2.cvtColor(cv2.resize(frame, (32, 32)), cv2.COLOR_BGR2GRAY)
    values = cv2.dct(gray.astype(np.float32))[:8, :8].ravel()[1:]
    return values > np.median(values)


def load_batch(batch, ui_version):
    manifest = json.loads((batch / 'manifest.json').read_text(encoding='utf-8'))
    annotations = json.loads((batch / 'annotations.json').read_text(encoding='utf-8'))
    if len({r['id'] for r in manifest}) != len(manifest):
        raise ValueError('Duplicate manifest IDs')
    if len({r['id'] for r in annotations}) != len(annotations):
        raise ValueError('Duplicate annotation IDs')
    reviews = {r['id']: r for r in annotations}
    if set(reviews) != {r['id'] for r in manifest}:
        raise ValueError('Manifest and annotation IDs differ')
    rows, seen = [], set()
    for source in manifest:
        if source.get('ui_generation') != 'current' or source.get('ui_version') != ui_version:
            raise ValueError('Only the explicitly selected current UI version is accepted')
        path = (batch / 'images' / source['image']).resolve()
        if not path.is_relative_to((batch / 'images').resolve()):
            raise ValueError('Image outside batch')
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != source['sha256']:
            raise ValueError('Image hash mismatch: ' + source['image'])
        if digest in seen:
            raise ValueError('Exact duplicate image in training batch')
        seen.add(digest)
        frame = cv2.imread(str(path))
        if frame is None:
            raise ValueError('Unreadable image: ' + str(path))
        if not source.get('session'):
            raise ValueError('Missing recording session')
        review = reviews[source['id']]
        rows.append({'id': source['candidate_id'], 'screen': review['screen'],
                     'session': source['session'], 'sha256': digest, 'image': source['image'],
                     'source': source['source'], 'features': screen_features(frame),
                     'phash': perceptual_hash(frame)})
    if len({r['screen'] for r in rows}) < 2:
        raise ValueError('At least two screen classes are required')
    return rows


def held_out_split(sessions, hashes, held_session, distance=6):
    held = np.asarray([s == held_session for s in sessions])
    train = ~held
    for index in np.flatnonzero(train):
        if np.any(np.count_nonzero(hashes[held] != hashes[index], axis=1) <= distance):
            train[index] = False
    return train, held


def train(batch, output, ui_version, approval_note, distance=6):
    if not approval_note.strip():
        raise ValueError('Explicit screen-label approval is required')
    if output.exists():
        raise ValueError('Use a new output directory; existing models are preserved')
    rows = load_batch(batch, ui_version)
    labels = sorted({r['screen'] for r in rows})
    features = np.stack([r['features'] for r in rows])
    targets = np.asarray([labels.index(r['screen']) for r in rows])
    hashes = np.stack([r['phash'] for r in rows])
    sessions = [r['session'] for r in rows]
    folds, predictions = [], []
    for session in sorted(set(sessions)):
        training, held = held_out_split(sessions, hashes, session, distance)
        available = sorted(set(targets[training].tolist()))
        eligible = held & np.isin(targets, available)
        fold = {'held_out_session': session, 'held_out_frames': int(held.sum()),
                'training_frames': int(training.sum()),
                'purged_similar_training_frames': int((~held).sum() - training.sum()),
                'unvalidated_labels': sorted({r['screen'] for r, h in zip(rows, held) if h}
                                             - {labels[i] for i in available}),
                'evaluated_frames': 0, 'correct': 0}
        if len(available) >= 2 and eligible.any():
            remap = {old: new for new, old in enumerate(available)}
            weights, mean, scale = fit(features[training], np.asarray([remap[t] for t in targets[training]]))
            samples = np.column_stack(((features[eligible] - mean) / scale, np.ones(int(eligible.sum()))))
            predicted = [labels[available[int(p)]] for p in np.argmax(samples @ weights, axis=1)]
            for index, prediction in zip(np.flatnonzero(eligible), predicted):
                predictions.append({'id': rows[index]['id'], 'session': session,
                                    'expected': rows[index]['screen'], 'predicted': prediction,
                                    'correct': rows[index]['screen'] == prediction})
            fold['evaluated_frames'] = len(predicted)
            fold['correct'] = sum(rows[i]['screen'] == p for i, p in zip(np.flatnonzero(eligible), predicted))
        folds.append(fold)
    evaluated = len(predictions)
    correct = sum(p['correct'] for p in predictions)
    coverage = {}
    for label in labels:
        tested = [p for p in predictions if p['expected'] == label]
        coverage[label] = {'examples': sum(r['screen'] == label for r in rows),
                           'sessions': len({r['session'] for r in rows if r['screen'] == label}),
                           'evaluated': len(tested), 'correct': sum(p['correct'] for p in tested),
                           'recall': sum(p['correct'] for p in tested) / len(tested) if tested else None}
    output.mkdir(parents=True)
    weights, mean, scale = fit(features, targets)
    model_path = output / 'screens.npz'
    np.savez_compressed(model_path, weights=weights, mean=mean, scale=scale)
    approval = {'screen_human_confirmed': True, 'approval_note': approval_note,
                'approved_at': datetime.now(timezone.utc).isoformat(),
                'scope': 'Whole-screen labels only; partial object boxes are not approved for training',
                'objects_complete': False, 'object_training_ready': False,
                'annotations_sha256': hashlib.sha256((batch / 'annotations.json').read_bytes()).hexdigest(),
                'manifest_sha256': hashlib.sha256((batch / 'manifest.json').read_bytes()).hexdigest()}
    report = {'frames': len(rows), 'labels': labels, 'class_counts': dict(Counter(r['screen'] for r in rows)),
              'ui_version': ui_version, 'validation': folds, 'per_class': coverage,
              'evaluated': evaluated, 'correct': correct, 'accuracy': correct / evaluated if evaluated else None,
              'predictions': predictions, 'phash_distance': distance, 'use': 'observation_only',
              'limitations': ['Small single-device dataset; no reliable estimate for unvalidated classes.',
                              'Similarity purging is conservative and cannot prove every visual relation is removed.',
                              'No button detection or game control. Old UI excluded.']}
    metadata = {'feature_version': FEATURE_VERSION, 'labels': labels, 'feature_count': len(mean),
                'method': 'balanced_ridge_classifier', 'frames': len(rows), 'class_counts': report['class_counts'],
                'ui_version': ui_version, 'created_at': datetime.now(timezone.utc).isoformat(),
                'model_sha256': hashlib.sha256(model_path.read_bytes()).hexdigest(),
                'validation': folds, 'approval': approval, 'use': 'observation_only',
                'limitations': report['limitations']}
    (output / 'screens.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    (output / 'approval.json').write_text(json.dumps(approval, indent=2), encoding='utf-8')
    (output / 'evaluation.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    (output / 'dataset.json').write_text(json.dumps([{k: v for k, v in r.items() if k not in ('features', 'phash')}
                                                   for r in rows], indent=2), encoding='utf-8')
    ScreenModel(model_path)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--ui-version', required=True)
    parser.add_argument('--approval-note', required=True)
    args = parser.parse_args()
    result = train(args.batch.resolve(), args.output.resolve(), args.ui_version, args.approval_note)
    print(json.dumps({k: v for k, v in result.items() if k not in ('predictions', 'validation')}, indent=2))
