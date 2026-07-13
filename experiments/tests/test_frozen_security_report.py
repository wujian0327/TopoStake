from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "experiments"))

from frozen_security_report import (  # noqa: E402
    PAIR_METRICS,
    SCENARIO_FIELDS,
    paired_differences,
    validation,
)
from run_experiments import expand_runs, load_yaml  # noqa: E402


def synthetic_run(seed: int, padding: int, contribution: float) -> dict[str, object]:
    row: dict[str, object] = {field: "" for field in SCENARIO_FIELDS}
    row.update(
        {
            "suite": "test",
            "protocol_version": "frozen-v1",
            "experiment": "padding_non_amplification",
            "protocol_label": "topostake",
            "protocol": "topostake",
            "padding_identities": padding,
            "seed_value": seed,
            "complete": True,
            "bound_violation_count": 0,
            "max_score_bound_excess": 0.0,
            "max_cap_bound_excess": 0.0,
            "max_bound_order_excess": 0.0,
            "invalid_path_count": 0,
            "finite_metrics": True,
            "adversary_raw_contribution_total": contribution,
        }
    )
    for metric in PAIR_METRICS:
        row.setdefault(metric, 0.0)
    return row


class FrozenSecurityReportTests(unittest.TestCase):
    def test_security_configs_expand_to_unique_runs(self) -> None:
        expected = {
            "frozen_v1_security_pilot.yaml": 32,
            "frozen_v1_security_main.yaml": 1120,
        }
        for filename, count in expected.items():
            spec = load_yaml(ROOT / "experiments" / "configs" / filename)
            runs = expand_runs(spec)
            self.assertEqual(len(runs), count)
            self.assertEqual(len({run["run_id"] for run in runs}), count)
            self.assertTrue(all(run["protocol_version"] == "frozen-v1" for run in runs))

    def test_padding_comparison_is_paired_by_seed(self) -> None:
        rows = [
            synthetic_run(0, 0, 10.0),
            synthetic_run(0, 8, 8.0),
            synthetic_run(1, 0, 12.0),
            synthetic_run(1, 8, 9.0),
        ]
        pairs = [
            row
            for row in paired_differences(rows)
            if row["metric"] == "adversary_raw_contribution_total"
        ]
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["n_pairs"], 2)
        self.assertAlmostEqual(float(pairs[0]["mean_difference"]), -2.5)

    def test_deterministic_envelope_checks_are_per_run(self) -> None:
        rows = [synthetic_run(0, 0, 10.0), synthetic_run(1, 0, 12.0)]
        checks = {item["name"]: item for item in validation(rows, expected_seeds=2)}
        self.assertTrue(checks["run-completeness"]["passed"])
        self.assertTrue(checks["seed-coverage"]["passed"])
        self.assertTrue(checks["score-dependent-proposer-bound"]["passed"])
        one_seed = {item["name"]: item for item in validation(rows[:1], expected_seeds=2)}
        self.assertFalse(one_seed["seed-coverage"]["passed"])
        rows[1]["max_cap_bound_excess"] = 0.01
        checks = {item["name"]: item for item in validation(rows, expected_seeds=2)}
        self.assertFalse(checks["score-independent-proposer-cap"]["passed"])


if __name__ == "__main__":
    unittest.main()
