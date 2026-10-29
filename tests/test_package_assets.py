"""Run against source and installed wheels/images to catch missing native data."""
from importlib import resources
from pathlib import Path
from unittest import TestCase


class PackageAssetsTests(TestCase):
    def test_every_native_recognition_asset_is_available_in_the_installed_package(self):
        source=Path(__file__).resolve().parents[1]/'src/coc_bot'
        checked=0
        for asset in source.rglob('assets/*'):
            if not asset.is_file() or asset.suffix not in ('.png','.npz','.js','.css'):continue
            package=asset.parent
            while package!=source and not (package/'__init__.py').is_file():package=package.parent
            module='coc_bot'+('.'+'.'.join(package.relative_to(source).parts) if package!=source else '')
            target=resources.files(module).joinpath(*asset.relative_to(package).parts)
            with self.subTest(asset=str(asset.relative_to(source))):self.assertTrue(target.is_file())
            checked+=1
        self.assertGreater(checked,100,'The source asset inventory is missing')
