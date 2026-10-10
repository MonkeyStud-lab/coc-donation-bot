"""Offline checks for passive collection; no ADB, game or calibration writes."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from coc_bot.vision.collection import CollectionOptions, SmartFrameRecorder, fingerprint, near_duplicate, read_catalog


def frame(number):
    return np.random.default_rng(number).integers(0, 256, (180, 320, 3), dtype=np.uint8)


class CollectionChecks(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name) / "collection"
        self.options = replace(CollectionOptions(), reserve_free_bytes=0)
        self.recorders = []

    def tearDown(self):
        for recorder in self.recorders:
            recorder.close()
            recorder._worker.join(10)
            self.assertFalse(recorder._worker.is_alive())
        self.directory.cleanup()

    def recorder(self, options=None, **kwargs):
        result = SmartFrameRecorder(self.root, options=options or self.options, **kwargs)
        self.recorders.append(result)
        return result

    def submit(self, recorder, image, screen="home", model=None, event=None):
        recorder.on_frame(image)
        recorder.note_classification(image, screen, "home")
        if model:
            recorder.note_model(image, model, "test-model")
        if event:
            recorder.note_event(event, {"test": True})
        # Force the same flush the next capture would perform, then wait only in tests.
        with recorder._lock:
            if recorder._pending is not None:
                recorder._enqueue(recorder._pending)
            recorder._pending = None
        recorder._queue.join()

    def rows(self):
        return list(read_catalog(self.root))

    def test_duplicates_across_sessions_and_changed_verdicts(self):
        first = self.recorder()
        self.submit(first, frame(1), "unknown")
        self.submit(first, frame(1), "battle")
        first.close()
        first._worker.join(10)
        second = self.recorder()
        self.submit(second, frame(1), "shop")
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(second._stats["duplicates"], 1)

    def test_disagreement_metadata_and_action_order(self):
        rec = self.recorder()
        rec.note_action({"kind": "tap", "x": 50, "y": 60})
        self.submit(rec, frame(2), model="battle")
        row = self.rows()[0]
        self.assertIn("disagreement", row["reason"])
        self.assertEqual(row["action"]["x"], 50)
        self.assertEqual(row["model"]["model_id"], "test-model")
        self.assertFalse(row["labels_verified"])

    def test_failure_context_and_repeated_incidents(self):
        rec = self.recorder()
        for number in range(5):
            self.submit(rec, frame(number), event="open_failed" if number == 2 else None)
        self.assertEqual(len(self.rows()), 5)
        self.assertEqual(sum(bool(row["incident"]) for row in self.rows()), 3)
        refs = [json.loads(line) for line in (self.root / "incidents.jsonl").read_text().splitlines()]
        self.assertEqual([row["context"] for row in refs], ["before", "before"])
        self.submit(rec, frame(2), event="open_failed")
        self.assertEqual(len(self.rows()), 5)
        self.assertEqual(rec._stats["repeated_incidents"], 1)

    def test_daily_budget_survives_restart_and_reserves_critical_space(self):
        options = replace(self.options, daily_limit=3, ordinary_limit=1)
        rec = self.recorder(options)
        self.submit(rec, frame(1))
        self.submit(rec, frame(2))
        self.submit(rec, frame(3), "shop")
        rec.close()
        rec._worker.join(10)
        rec = self.recorder(options)
        self.submit(rec, frame(4), "battle")
        self.submit(rec, frame(5), "popup")
        self.assertEqual(len(self.rows()), 3)

    def test_storage_cap_preserves_existing_files(self):
        self.root.mkdir()
        protected = self.root / "existing.txt"
        protected.write_text("keep")
        rec = self.recorder(replace(self.options, storage_bytes=1024))
        self.submit(rec, frame(1))
        self.assertEqual(self.rows(), [])
        self.assertEqual(protected.read_text(), "keep")
        self.assertEqual(rec._pause, "Storage limit reached")

    def test_low_disk_pauses_only_collection(self):
        rec = self.recorder()
        with patch("coc_bot.vision.collection.shutil.disk_usage") as disk:
            disk.return_value.free = 0
            self.submit(rec, frame(1))
        self.assertEqual(self.rows(), [])
        self.assertEqual(rec._pause, "Low free disk space")

    def test_small_regional_change_is_retained(self):
        image = np.zeros((180, 320, 3), dtype=np.uint8)
        changed = image.copy()
        changed[:30, :80] = 255
        self.assertFalse(near_duplicate(fingerprint(changed), [fingerprint(image)]))
        self.assertTrue(near_duplicate(fingerprint(image), [fingerprint(image)]))

    def test_reviewed_seed_is_not_collected_again(self):
        data = Path(self.directory.name)
        cv2.imwrite(str(data / "seed.png"), frame(1))
        export = data / "tasks.json"
        export.write_text(json.dumps([{"data": {"image": "/data/local-files/?d=seed.png"}}]))
        rec = self.recorder(seed_export=export, data_dir=data)
        self.submit(rec, frame(1))
        self.assertEqual(self.rows(), [])
        self.assertEqual(rec._stats["seed_examples"], 1)

    def test_single_writer_and_memory_budget(self):
        rec = self.recorder(replace(self.options, memory_bytes=100))
        with self.assertRaises(RuntimeError):
            self.recorder()
        self.submit(rec, frame(1))
        self.assertEqual(rec._stats["memory_dropped"], 1)
        self.assertEqual(self.rows(), [])

    def test_corrupt_catalog_tail_and_gallery(self):
        rec = self.recorder()
        self.submit(rec, frame(1))
        rec.close()
        rec._worker.join(10)
        with (self.root / "catalog.jsonl").open("a") as handle:
            handle.write('{"broken":\n')
        self.assertEqual(len(self.rows()), 1)
        self.assertIn("not verified labels", (self.root / "review.html").read_text())

    def test_daily_quota_resets_on_next_utc_day(self):
        rec = self.recorder(replace(self.options, daily_limit=1))
        self.submit(rec, frame(1))
        self.submit(rec, frame(2))
        tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
        with patch("coc_bot.vision.collection.datetime", wraps=datetime) as clock:
            clock.now.return_value = tomorrow
            self.submit(rec, frame(3))
        self.assertEqual(len(self.rows()), 2)

    def test_write_failure_does_not_stop_capture_or_count_saved(self):
        rec = self.recorder()
        with patch("coc_bot.vision.collection.cv2.imencode", side_effect=OSError("test disk failure")):
            self.submit(rec, frame(1))
        self.assertEqual(rec._stats["saved"], 0)
        self.submit(rec, frame(2))
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(rec._stats["errors"], 1)

    def test_export_has_no_verified_annotations(self):
        from export_collection_tasks import export_tasks

        rec = self.recorder()
        self.submit(rec, frame(1))
        tasks = export_tasks(self.root)
        self.assertEqual(len(tasks), 1)
        self.assertNotIn("annotations", tasks[0])
        self.assertNotIn("predictions", tasks[0])


if __name__ == "__main__":
    unittest.main()
