"""Fresh-image artwork provisioning; no network or game input."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
from unittest import TestCase, skipIf
from unittest.mock import patch

import cv2
import numpy as np


def load_script():
    path = Path(__file__).resolve().parents[1] / 'scripts/sync_game_data.py'
    spec = importlib.util.spec_from_file_location('asset_sync_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ProvisioningTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.module = load_script()
        self.module.ROOT = self.root
        self.module.ICONS_DIR = self.root / 'data/icons'
        self.units = {'electro_dragon': {'category': 'troop'},
                      'rage_spell': {'category': 'spell'}}
        frame = np.full((32, 32, 4), 255, np.uint8)
        self.icon = cv2.imencode('.png', frame)[1].tobytes()

    def test_core_artwork_is_validated_and_manifest_records_seed_hashes(self):
        with patch.object(self.module, 'fetch_bytes', return_value=self.icon):
            self.assertEqual(self.module.sync_icons(self.units, require_core=True), 0)
        manifest = json.loads((self.module.ICONS_DIR / 'manifest.json').read_text())
        self.assertEqual(set(manifest['files']), self.module.CORE_ICONS)
        self.assertEqual(manifest['missing_core'], [])

    def test_missing_or_html_core_download_fails_image_provisioning(self):
        with patch.object(self.module, 'fetch_bytes', return_value=b'<html>unavailable</html>'):
            self.assertEqual(self.module.sync_icons(self.units, require_core=True), 1)
        self.assertFalse((self.module.ICONS_DIR / 'troops/electro_dragon.webp').exists())

    def test_existing_valid_artwork_is_not_downloaded_again(self):
        with patch.object(self.module, 'fetch_bytes', return_value=self.icon):
            self.module.sync_icons(self.units, require_core=True)
        with patch.object(self.module, 'fetch_bytes') as fetch:
            self.assertEqual(self.module.sync_icons(self.units, require_core=True), 0)
            fetch.assert_not_called()

    def test_invalid_existing_core_is_repaired_without_publishing_partial_bytes(self):
        target = self.module.ICONS_DIR / 'troops/electro_dragon.webp'
        target.parent.mkdir(parents=True)
        target.write_bytes(b'partial')
        with patch.object(self.module, 'fetch_bytes', return_value=self.icon):
            self.assertEqual(self.module.sync_icons(self.units, require_core=True), 0)
        self.assertEqual(target.read_bytes(), self.icon)
        self.assertFalse(list(self.module.ICONS_DIR.rglob('*.tmp')))

    def test_failed_atomic_replace_preserves_old_artwork_and_removes_staging(self):
        target = self.root / 'icon.webp'
        target.write_bytes(b'old')
        with patch.object(self.module.os, 'replace', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.module.write_atomic(target, self.icon)
        self.assertEqual(target.read_bytes(), b'old')
        self.assertFalse(list(self.root.glob('*.tmp')))

    @skipIf(os.name == 'nt', 'POSIX image ownership/mode check runs on Linux')
    def test_public_assets_are_readable_by_the_nonroot_image_user(self):
        target = self.root / 'icon.webp'
        self.module.write_atomic(target, self.icon)
        self.assertEqual(target.stat().st_mode & 0o777, 0o644)

    def test_rgb_or_transparent_artwork_cannot_seed_the_alpha_catalog(self):
        for frame in (np.full((32, 32, 3), 255, np.uint8), np.zeros((32, 32, 4), np.uint8)):
            self.assertFalse(self.module.valid_icon(cv2.imencode('.png', frame)[1].tobytes()))

    def test_path_like_unit_identity_cannot_escape_icon_root(self):
        with self.assertRaises(ValueError):
            self.module.sync_icons({'../../escape': {'category': 'troop'}})
