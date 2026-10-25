"""The optional research model must not rewrite unrelated screen decisions."""
import unittest
from unittest.mock import Mock

from screen_settings_refinement import SettingsRefinement


class SettingsRefinementTests(unittest.TestCase):
    def test_unrelated_screens_never_invoke_refinement(self):
        for label in ("home", "clan_chat", "donation_panel", "battle", "battle_results",
                      "upgrade_menu", "upgrade_confirmation", "upgrade_in_progress",
                      "loading", "settings", "unknown"):
            with self.subTest(label=label):
                baseline = Mock(); baseline.predict.return_value = label
                optional = Mock(); optional.predict.side_effect = AssertionError("must not run")
                self.assertEqual(SettingsRefinement(baseline, optional).predict(object()), label)
                optional.predict.assert_not_called()

    def test_only_settings_can_refine_a_popup(self):
        for label in ("popup", "loading", "home", "battle_results", "upgrade_confirmation",
                      "settings", "unknown", None):
            with self.subTest(label=label):
                frame = object()
                baseline = Mock(); baseline.predict.return_value = "popup"
                optional = Mock(); optional.predict.return_value = label
                result = SettingsRefinement(baseline, optional).predict(frame)
                self.assertEqual(result, "settings" if label == "settings" else "popup")
                baseline.predict.assert_called_once_with(frame)
                optional.predict.assert_called_once_with(frame)

    def test_optional_failure_keeps_baseline(self):
        baseline = Mock(); baseline.predict.return_value = "popup"
        optional = Mock(); optional.predict.side_effect = ValueError("invalid inference")
        self.assertEqual(SettingsRefinement(baseline, optional).predict(object()), "popup")

    def test_baseline_failure_is_not_fabricated_as_a_screen(self):
        baseline = Mock(); baseline.predict.side_effect = ValueError("missing baseline")
        optional = Mock()
        with self.assertRaises(ValueError):
            SettingsRefinement(baseline, optional).predict(object())
        optional.predict.assert_not_called()
