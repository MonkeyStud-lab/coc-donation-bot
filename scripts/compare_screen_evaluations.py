"""Compare screen-model batches on identical cases; never deploy a model.

Historical evaluations reused for development are regression checks, not an
untouched estimate of future accuracy. Additional candidate cases are reported
separately so changing the denominator cannot conceal a regression.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _index(rows: list[dict], name: str) -> dict[str, dict]:
    indexed = {}
    for row in rows:
        key = row["id"]
        if not isinstance(key, str) or not key or key in indexed:
            raise ValueError(f"Invalid or duplicate {name} ID: {key!r}")
        indexed[key] = row
    return indexed


def compare(baseline: dict, candidate: dict, baseline_data: list[dict],
            candidate_data: list[dict]) -> dict:
    """Fail closed on changed images/labels/groups, omitted cases, or regressions."""
    old = _index(baseline["predictions"], "baseline prediction")
    new = _index(candidate["predictions"], "candidate prediction")
    old_data = _index(baseline_data, "baseline dataset")
    new_data = _index(candidate_data, "candidate dataset")
    if not old:
        raise ValueError("Baseline has no evaluated cases")
    for predictions, data in ((old, old_data), (new, new_data)):
        for key, row in predictions.items():
            source = data.get(key)
            if (not source or not source.get("sha256") or not source.get("session")
                    or row["expected"] != source["screen"]
                    or row["session"] != source["session"]):
                raise ValueError(f"Prediction does not match its dataset: {key}")
            if not isinstance(row.get("predicted"), str) or not row["predicted"]:
                raise ValueError(f"Missing predicted label: {key}")
    for key in old:
        if key in new:
            for field in ("sha256", "screen", "session"):
                if old_data[key][field] != new_data[key][field]:
                    raise ValueError(f"Changed benchmark {field}: {key}")
    missing = sorted(set(old) - set(new))
    common = sorted(set(old) & set(new))
    regressions, improvements = [], []
    per_class = {}
    for key in common:
        before, after = old[key], new[key]
        was_correct = before["predicted"] == before["expected"]
        is_correct = after["predicted"] == after["expected"]
        counts = per_class.setdefault(before["expected"],
                                      {"cases": 0, "before_correct": 0, "after_correct": 0})
        counts["cases"] += 1
        counts["before_correct"] += int(was_correct)
        counts["after_correct"] += int(is_correct)
        change = {"id": key, "expected": before["expected"],
                  "before": before["predicted"], "after": after["predicted"]}
        if was_correct and not is_correct:
            regressions.append(change)
        elif not was_correct and is_correct:
            improvements.append(change)
    added = [new[k] for k in sorted(set(new) - set(old))]
    passes = not missing and not regressions
    return {
        "passes_regression_gate": passes,
        "improves_without_regressions": passes and bool(improvements),
        "baseline_cases": len(old), "common_cases": len(common),
        "before_correct": sum(r["predicted"] == r["expected"] for r in old.values()),
        "after_correct_on_baseline_cases": sum(new[k]["predicted"] == new[k]["expected"] for k in common),
        "missing_cases": missing, "regressions": regressions, "improvements": improvements,
        "per_class": per_class,
        "additional_cases": len(added),
        "additional_correct": sum(r["predicted"] == r["expected"] for r in added),
        "use": "offline_regression_check_only",
        "limitations": ["No guarantee against regressions on unseen images.",
                        "Requires independently generated, leakage-controlled evaluation reports.",
                        "Passing does not authorize gameplay or deploy a model."],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("baseline", "candidate", "baseline-data", "candidate-data", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    read = lambda p: json.loads(p.read_text(encoding="utf-8"))
    report = compare(read(args.baseline), read(args.candidate),
                     read(args.baseline_data), read(args.candidate_data))
    # Exclusive creation keeps prior batch decisions reviewable.
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
    print(json.dumps(report, indent=2))
    return 0 if report["passes_regression_gate"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
