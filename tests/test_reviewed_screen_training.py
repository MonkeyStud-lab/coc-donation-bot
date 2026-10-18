import hashlib
import json
from pathlib import Path
import sys
import tempfile
from unittest import TestCase

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from train_reviewed_screens import held_out_split, load_batch, train


class ReviewedScreenTrainingTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.batch = self.root / 'batch'
        (self.batch / 'images').mkdir(parents=True)
        self.manifest, annotations = [], []
        for i, (screen, session, color) in enumerate([
                ('home', 'a', (10, 140, 30)), ('popup', 'a', (140, 20, 20)),
                ('home', 'b', (15, 135, 35)), ('popup', 'b', (135, 25, 25))], 1):
            path = self.batch / 'images' / f'{i}.png'
            frame = np.full((80, 100, 3), color, dtype=np.uint8)
            cv2.putText(frame, str(i), (15, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
            cv2.imwrite(str(path), frame)
            self.manifest.append({'id': i, 'candidate_id': str(i), 'image': path.name,
                                  'source': 'private/' + path.name, 'session': session,
                                  'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                                  'ui_generation': 'current', 'ui_version': 'test-ui'})
            annotations.append({'id': i, 'screen': screen, 'boxes': []})
        self.save_manifest()
        (self.batch / 'annotations.json').write_text(json.dumps(annotations))

    def save_manifest(self):
        (self.batch / 'manifest.json').write_text(json.dumps(self.manifest))

    def test_sessions_and_similar_frames_do_not_cross_evaluation_boundary(self):
        hashes = np.array([[0, 0, 0], [0, 0, 0], [1, 1, 1]], dtype=bool)
        training, held = held_out_split(['a', 'b', 'b'], hashes, 'a', distance=0)
        self.assertEqual(held.tolist(), [True, False, False])
        self.assertEqual(training.tolist(), [False, False, True])

    def test_legacy_or_mixed_ui_is_rejected(self):
        self.manifest[0]['ui_generation'] = 'pre_update'
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, 'current UI'):
            load_batch(self.batch, 'test-ui')

    def test_source_hash_mismatch_is_rejected(self):
        self.manifest[0]['sha256'] = 'changed'
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            load_batch(self.batch, 'test-ui')

    def test_approval_scope_and_no_overwrite(self):
        output = self.root / 'model'
        with self.assertRaisesRegex(ValueError, 'approval'):
            train(self.batch, output, 'test-ui', '')
        report = train(self.batch, output, 'test-ui', 'User approved screen labels')
        approval = json.loads((output / 'approval.json').read_text())
        self.assertEqual(report['use'], 'observation_only')
        self.assertTrue(approval['screen_human_confirmed'])
        self.assertFalse(approval['object_training_ready'])
        self.assertFalse(approval['objects_complete'])
        self.assertEqual(len(json.loads((output / 'dataset.json').read_text())), 4)
        with self.assertRaisesRegex(ValueError, 'existing models'):
            train(self.batch, output, 'test-ui', 'Approved')
