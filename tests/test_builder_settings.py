import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from coc_bot.config import load_config, project_root
from coc_bot.control.settings import save_settings, revision


class BuilderSettingsTests(unittest.TestCase):
    def setUp(self):
        root = project_root()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        shutil.copytree(root/'config', self.home/'config')
        self.env = patch.dict(os.environ, {
            'COC_BOT_HOME': str(self.home),
            'COC_BOT_CONFIG': str(self.home/'data/calibrated.yaml'),
        })
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_collection_and_research_settings_roundtrip_independently(self):
        values = {'builder_base_collect_resources': True, 'builder_base_research_enabled': True,
                  'builder_base_attacks_enabled': False, 'builder_base_upgrades_enabled': False,
                  'builder_base_builders_reserved': 3, 'builder_base_elixir_reserve': 250_000}
        save_settings(values, revision())
        config = load_config()
        for key, value in values.items():
            self.assertEqual(getattr(config, key), value)

    def test_invalid_builder_settings_never_persist(self):
        before = revision()
        for values in ({'builder_base_builders_reserved': 4}, {'builder_base_elixir_reserve': -1},
                       {'builder_base_collect_resources': 'yes'}, {'builder_base_research_enabled': 1}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                save_settings(values, revision())
        self.assertEqual(before, revision())


if __name__ == '__main__':
    unittest.main()
