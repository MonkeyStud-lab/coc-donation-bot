import tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from coc_bot.accounts.store import read,write
from coc_bot.builder_base.tutorials import recover


class DefenseTutorialTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.r=Mock();self.r.config=SimpleNamespace(data_dir=Path(self.temp.name),account_tag='#PYLQG')
        self.r.reader.battle.return_value=False;self.r.reader.result_button.return_value=None
        self.r.reader.daily_reward_close.return_value=None
        self.r.reader.daily_reward_claim.return_value=None
        self.path=self.r.config.data_dir/'builder_base/defense_tutorial.json'

    def test_generic_speech_without_the_owned_first_defense_anchor_is_untouched(self):
        self.r.reader.find.return_value=None
        self.assertFalse(recover(self.r,object()))
        self.r.tap.assert_not_called();self.assertFalse(self.path.exists())

    def test_foreign_tutorial_checkpoint_never_receives_input(self):
        write(self.path,{'account':'#OTHER','phase':'opening_cart'})
        with self.assertRaises(ValueError):recover(self.r,object())
        self.r.tap.assert_not_called();self.r.frame.assert_not_called()

    def test_daily_calendar_only_uses_its_verified_close_target(self):
        self.r.reader.daily_reward_close.return_value=(1565,150)
        self.assertTrue(recover(self.r,object()))
        self.r.tap.assert_called_once_with((1565,150))
        self.r.reader.find.assert_not_called()
        self.assertFalse(self.path.exists())

    def test_mandatory_free_reward_is_journaled_and_bounded(self):
        self.r.reader.daily_reward_close.return_value=(1565,150)
        self.r.reader.daily_reward_claim.return_value=(670,440)
        self.r.record={'phase':'leaving_results'}
        self.assertTrue(recover(self.r,object()))
        self.assertEqual(self.r.record['daily_reward']['attempts'],1)
        self.r.tap.assert_called_once_with((670,440))
        self.assertTrue(recover(self.r,object()))
        self.r.tap.reset_mock()
        with self.assertRaisesRegex(ValueError,'needs inspection'):recover(self.r,object())
        self.r.tap.assert_not_called()

    def test_first_defense_anchor_records_one_nonspending_cart_tap(self):
        self.r.reader.find.side_effect=[True,(925,470),True,(925,470)]
        def tapped(point):self.assertEqual(read(self.path)['cart_taps'],1)
        self.r.tap.side_effect=tapped
        self.assertTrue(recover(self.r,object()))
        self.r.tap.assert_called_once_with((925,470))

    def test_repeated_stuck_cart_is_bounded(self):
        write(self.path,{'account':'#PYLQG','phase':'opening_cart','cart_taps':2})
        self.r.reader.find.side_effect=[True,(925,470),True,(925,470)]
        with self.assertRaisesRegex(ValueError,'did not open'):recover(self.r,object())
        self.r.tap.assert_not_called()
