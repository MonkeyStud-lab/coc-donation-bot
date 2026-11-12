"""Artwork reuse must not reuse live counts or weaken recognition guards."""
from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

import cv2
import numpy as np

from coc_bot.adb.client import AdbStopped
from coc_bot.attack.army import ArmyCard, UnitCatalog, _portrait_features, read_badge
from coc_bot.control.attack_observation import load_recent_references
from coc_bot.runtime.processes import ProcessStopped


class PortraitReuseTests(TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.catalog = UnitCatalog(Path(temporary.name))
        self.image = np.random.default_rng(42).integers(0, 255, (160, 130, 3), dtype=np.uint8)
        self.card = ArmyCard('one', (0, 0, 130, 160), 'reviewed', 'hero', 1, confirmed=True)
        _portrait_features.cache_clear()
        self.addCleanup(_portrait_features.cache_clear)

    def test_repeated_artwork_is_reused_across_catalogs_without_duplicate_matches(self):
        self.catalog.add_references(self.image, [self.card])
        expected = self.catalog.identify_reference(self.image)
        with patch('coc_bot.attack.army.cv2.SIFT_create', side_effect=AssertionError('recomputed')):
            for _ in range(10):
                self.catalog.add_references(self.image.copy(), [self.card])
            other = UnitCatalog(Path('missing-icons'))
            other.add_references(self.image.copy(), [replace(self.card, quantity=0)])
        self.assertEqual(len(self.catalog.references), 1)
        self.assertEqual(self.catalog.identify_reference(self.image), expected)
        self.assertEqual(other.identify_reference(self.image)[0], 'reviewed')

    def test_same_portrait_with_competing_names_remains_ambiguous(self):
        self.catalog.add_references(self.image, [self.card, replace(self.card, unit_id='different')])
        self.assertEqual(len(self.catalog.references), 2)
        self.assertIsNone(self.catalog.identify_reference(self.image))

    def test_changed_artwork_masks_and_removed_references_do_not_use_stale_entries(self):
        self.catalog.add_references(self.image, [self.card])
        self.catalog.add_references(self.image, [self.card], picker=True)
        self.assertEqual(len(self.catalog.references), 2)
        changed = self.image.copy()
        changed[30:80, 30:80] = 0
        self.catalog.add_references(changed, [self.card])
        self.assertEqual(len(self.catalog.references), 3)
        self.catalog.references = []
        self.catalog.add_references(self.image, [self.card])
        self.assertEqual(len(self.catalog.references), 1)

    def test_cached_artwork_does_not_promote_unreviewed_cards(self):
        self.catalog.add_references(self.image, [self.card])
        self.catalog.references = []
        self.catalog.add_references(self.image, [replace(self.card, confirmed=False)])
        self.assertEqual(self.catalog.references, [])

    def test_large_portraits_are_not_retained_and_bad_bounds_are_ignored(self):
        image = cv2.resize(self.image, (601, 601))
        self.catalog.add_references(image, [replace(self.card, box=(0, 0, 601, 601))])
        self.assertEqual(_portrait_features.cache_info().currsize, 0)
        count = len(self.catalog.references)
        for box in ((-1, 0, 130, 160), (0, 0, 0, 160), (1, 0, 130, 160)):
            self.catalog.add_references(self.image, [replace(self.card, box=box)])
        self.assertEqual(len(self.catalog.references), count)


def badge(*, wide=False):
    cell = np.full((150, 150, 3), (180, 90, 40), np.uint8)
    cv2.line(cell, (14, 18), (27, 32), (255, 255, 255), 5)
    cv2.line(cell, (27, 18), (14, 32), (255, 255, 255), 5)
    cv2.rectangle(cell, (33, 14), (46 if wide else 39, 33), (255, 255, 255), -1)
    return cell


class LazyBadgeOcrTests(TestCase):
    def test_native_and_absent_badges_do_not_search_for_ocr_or_create_files(self):
        with patch('coc_bot.attack.army.shutil.which', side_effect=AssertionError('OCR lookup')), \
                patch('coc_bot.attack.army.tempfile.TemporaryDirectory', side_effect=AssertionError('file IO')):
            self.assertEqual(read_badge(badge()), 1)
            self.assertIsNone(read_badge(np.zeros((150, 150, 3), np.uint8)))
            self.assertIsNone(read_badge(np.zeros((0, 0, 3), np.uint8)))

    def test_missing_optional_ocr_keeps_unknown_digit_unknown(self):
        with patch('coc_bot.attack.army.shutil.which', return_value=None), \
                patch('coc_bot.upgrades.digits.read_digits', return_value=None), \
                patch('coc_bot.attack.army.run_process') as process:
            self.assertIsNone(read_badge(badge(wide=True)))
        process.assert_not_called()

    def test_unknown_glyph_still_uses_bounded_interruptible_ocr(self):
        with patch('coc_bot.attack.army.shutil.which', return_value='test-tesseract'), \
                patch('coc_bot.upgrades.digits.read_digits', return_value=None), \
                patch('coc_bot.attack.army.run_process', return_value=SimpleNamespace(stdout='3')) as process:
            self.assertEqual(read_badge(badge(wide=True)), 3)
            self.assertEqual(process.call_args.args[0][0], 'test-tesseract')
            self.assertEqual(process.call_args.kwargs['timeout'], 1.5)
            self.assertFalse(Path(process.call_args.args[0][1]).exists())
            process.side_effect = ProcessStopped('stop')
            with self.assertRaises(AdbStopped):
                read_badge(badge(wide=True))

    def test_stop_is_honored_before_native_recognition(self):
        with self.assertRaises(AdbStopped):
            read_badge(badge(), stop_check=lambda: True)


class OptionalObservationTests(TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.card = ArmyCard('one', (0, 0, 130, 160), 'reviewed', 'hero', 1, confirmed=True)
        self.report = dict(page='army_confirmation', device='test', captured_at=950,
                           cards=[self.card.to_dict()])
        self.image = np.zeros((160, 130, 3), np.uint8)
        self.save('a', self.report)

    def save(self, name, report, image=True):
        folder = self.root/'debug/attack-observations'/(name*32)
        folder.mkdir(parents=True, exist_ok=True)
        (folder/'report.json').write_text(json.dumps(report), encoding='utf-8')
        if image:
            cv2.imwrite(str(folder/'frame.png'), self.image)

    def test_malformed_newer_reports_cannot_block_valid_artwork(self):
        invalid = [None, [], 1, {'captured_at': 999}]
        invalid += [self.report | {'captured_at': value} for value in (None, '999', True, float('nan'), float('inf'), 10**400, 1001, 1)]
        invalid += [self.report | {'captured_at': 999, 'cards': value} for value in (
            None, {}, [None], [{}], [self.card.to_dict() | {'box': [0]}],
            [self.card.to_dict() | {'box': [-1, 0, 130, 160]}],
            [self.card.to_dict() | {'confirmed': 'false'}],
            [self.card.to_dict() | {'unit_id': ['invalid']}])]
        for report in invalid:
            with self.subTest(report=report), patch('coc_bot.control.attack_observation.time.time', return_value=1000):
                self.save('b', report)
                catalog = Mock()
                load_recent_references(self.root, catalog, 'test')
                catalog.add_references.assert_called_once()
                self.assertEqual(catalog.add_references.call_args.args[1][0].unit_id, 'reviewed')

    def test_unreadable_optional_report_directory_is_ignored(self):
        with patch.object(Path, 'iterdir', side_effect=PermissionError('unreadable')):
            catalog = Mock()
            load_recent_references(self.root, catalog, 'test')
            catalog.add_references.assert_not_called()

    def test_missing_image_falls_back_but_foreign_or_old_reports_are_not_used(self):
        self.save('b', self.report | {'captured_at': 999}, image=False)
        with patch('coc_bot.control.attack_observation.time.time', return_value=1000):
            catalog = Mock()
            load_recent_references(self.root, catalog, 'test')
            catalog.add_references.assert_called_once()
            catalog.reset_mock()
            load_recent_references(self.root, catalog, 'other-device')
            catalog.add_references.assert_not_called()
            load_recent_references(self.root, catalog, 'test', max_age=10)
            catalog.add_references.assert_not_called()
