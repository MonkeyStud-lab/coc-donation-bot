"""Bounded, read-only observation of newly saved collector frames. No ADB or taps."""
import argparse
from datetime import datetime, timezone
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys
import time

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from coc_bot.vision.screen_model import ScreenModel


def read_new_rows(handle):
    """Leave an unfinished final JSONL line for the next poll."""
    while True:
        position = handle.tell()
        line = handle.readline()
        if not line or not line.endswith('\n'):
            handle.seek(position)
            return
        try:
            row = json.loads(line)
            if isinstance(row, dict):
                yield row
        except ValueError:
            continue


def watch(collection, model_path, output, duration=3600, backfill=0):
    collection = collection.resolve()
    model = ScreenModel(model_path)
    output.mkdir(parents=True, exist_ok=False)
    logger = logging.getLogger('screen-watch-' + str(output))
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(output / 'observations.jsonl', maxBytes=5_000_000, backupCount=2)
    logger.addHandler(handler)
    summary = {'model_id': model.model_id, 'started_at': datetime.now(timezone.utc).isoformat(),
               'use': 'observation_only', 'source': 'saved collector frames, not every live video frame',
               'processed': 0, 'disagreements': 0, 'errors': 0, 'running': True,
               'comparison_is_ground_truth': False, 'duration_seconds': duration}

    def observe(row, backfilled=False):
        try:
            path = (collection / row['file']).resolve()
            if not path.is_relative_to(collection):
                raise ValueError('Collector image outside collection root')
            frame = cv2.imread(str(path))
            if frame is None:
                raise ValueError('Collector image unavailable')
            start = time.perf_counter()
            prediction = model.predict(frame)
            latency = (time.perf_counter() - start) * 1000
            hint = row.get('screen_hint', 'unknown')
            event = {'observed_at': datetime.now(timezone.utc).isoformat(),
                     'file': row['file'], 'session': row.get('session'), 'captured_at': row.get('ts'),
                     'model': prediction, 'collector_hint': hint, 'hint_inherited': row.get('screen_inherited'),
                     'different': prediction != hint, 'backfill': backfilled, 'inference_ms': round(latency, 2)}
            logger.info(json.dumps(event))
            summary['processed'] += 1
            summary['disagreements'] += prediction != hint
        except (OSError, ValueError, KeyError, cv2.error) as exc:
            summary['errors'] += 1
            logger.info(json.dumps({'error': str(exc), 'file': row.get('file')}))

    try:
        with (collection / 'catalog.jsonl').open(encoding='utf-8') as handle:
            if backfill:
                from collections import deque
                for row in deque(read_new_rows(handle), maxlen=backfill):
                    observe(row, True)
            else:
                # Scan complete rows so a partially written tail is not skipped.
                for _ in read_new_rows(handle):
                    pass
            deadline = time.monotonic() + duration
            while time.monotonic() < deadline:
                if (collection / 'catalog.jsonl').stat().st_size < handle.tell():
                    handle.seek(0)
                for row in read_new_rows(handle):
                    observe(row)
                temp = output / 'status.tmp'
                temp.write_text(json.dumps(summary, indent=2), encoding='utf-8')
                temp.replace(output / 'status.json')
                time.sleep(min(5, max(0, deadline - time.monotonic())))
    finally:
        summary['running'] = False
        summary['finished_at'] = datetime.now(timezone.utc).isoformat()
        (output / 'status.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
        handler.close()
        logger.removeHandler(handler)
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--collection', type=Path, required=True)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--duration', type=float, default=3600)
    parser.add_argument('--backfill', type=int, default=0)
    args = parser.parse_args()
    if args.duration <= 0 or args.backfill < 0:
        parser.error('Duration must be positive and backfill must be nonnegative')
    print(json.dumps(watch(args.collection, args.model, args.output, args.duration, args.backfill)))
