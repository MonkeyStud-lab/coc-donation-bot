from copy import deepcopy
from pathlib import Path
import sys
from unittest import TestCase

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from compare_screen_evaluations import compare


class ScreenEvaluationGateTests(TestCase):
    def setUp(self):
        self.data = [{"id": str(i), "screen": label, "session": "held-day",
                      "sha256": str(i) * 64} for i, label in enumerate(("home", "popup", "battle"), 1)]
        self.baseline = {"predictions": [
            {"id": d["id"], "session": d["session"], "expected": d["screen"],
             "predicted": d["screen"] if i != 2 else "popup"}
            for i, d in enumerate(self.data)]}

    def test_improvement_without_regression_passes(self):
        candidate = deepcopy(self.baseline)
        candidate["predictions"][2]["predicted"] = "battle"
        result = compare(self.baseline, candidate, self.data, self.data)
        self.assertTrue(result["improves_without_regressions"])
        self.assertEqual(result["after_correct_on_baseline_cases"], 3)

    def test_equal_total_with_new_error_is_rejected(self):
        candidate = deepcopy(self.baseline)
        candidate["predictions"][0]["predicted"] = "popup"
        candidate["predictions"][2]["predicted"] = "battle"
        result = compare(self.baseline, candidate, self.data, self.data)
        self.assertFalse(result["passes_regression_gate"])
        self.assertEqual(len(result["regressions"]), 1)

    def test_omitting_a_hard_case_does_not_pass(self):
        candidate = {"predictions": self.baseline["predictions"][:2]}
        self.assertFalse(compare(self.baseline, candidate, self.data, self.data)["passes_regression_gate"])

    def test_changed_image_label_or_group_cannot_reuse_benchmark_identity(self):
        for field, value in (("sha256", "changed"), ("session", "different-day"), ("screen", "shop")):
            with self.subTest(field=field):
                changed = deepcopy(self.data)
                changed[0][field] = value
                candidate = deepcopy(self.baseline)
                if field == "session": candidate["predictions"][0]["session"] = value
                if field == "screen": candidate["predictions"][0]["expected"] = value
                with self.assertRaises(ValueError):
                    compare(self.baseline, candidate, self.data, changed)

    def test_correct_flag_is_not_trusted(self):
        candidate = deepcopy(self.baseline)
        candidate["predictions"][0].update(predicted="popup", correct=True)
        self.assertFalse(compare(self.baseline, candidate, self.data, self.data)["passes_regression_gate"])

    def test_additional_cases_are_reported_separately(self):
        extra = {"id": "4", "screen": "home", "session": "new-creator", "sha256": "4"*64}
        candidate = deepcopy(self.baseline)
        candidate["predictions"].append({"id": "4", "expected": "home", "predicted": "home", "session": "new-creator"})
        result = compare(self.baseline, candidate, self.data, self.data + [extra])
        self.assertEqual(result["common_cases"], 3)
        self.assertEqual(result["additional_cases"], 1)
        self.assertFalse(result["improves_without_regressions"])

    def test_duplicate_prediction_rejected(self):
        candidate = deepcopy(self.baseline)
        candidate["predictions"].append(candidate["predictions"][0])
        with self.assertRaises(ValueError):
            compare(self.baseline, candidate, self.data, self.data)

    def test_abstention_is_not_counted_as_correct(self):
        candidate = deepcopy(self.baseline)
        candidate["predictions"][0]["predicted"] = "unknown"
        self.assertFalse(compare(self.baseline, candidate, self.data, self.data)["passes_regression_gate"])
