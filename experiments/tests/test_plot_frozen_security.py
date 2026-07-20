from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "analysis"))

from plot_frozen_security import (  # noqa: E402
    complete_runs,
    grouped_stats,
    mean_ci,
    paired_metric,
)


class FrozenSecurityPlotTests(unittest.TestCase):
    def test_complete_runs_excludes_matrix_placeholders(self) -> None:
        rows = [
            {"status": "ok", "complete": "True", "finite_metrics": "True"},
            {"status": "missing", "complete": "False", "finite_metrics": "True"},
            {"status": "ok", "complete": "True", "finite_metrics": "False"},
        ]
        self.assertEqual(len(complete_runs(rows)), 1)

    def test_mean_ci_is_across_independent_values(self) -> None:
        mean, ci, count = mean_ci([1.0, 2.0, 3.0])
        self.assertEqual(count, 3)
        self.assertAlmostEqual(mean, 2.0)
        self.assertAlmostEqual(ci, 1.96 / math.sqrt(3))

    def test_grouped_stats_keeps_focal_profiles_separate(self) -> None:
        rows = [
            {"protocol_label": "topostake", "relay_profile": "active", "metric": "3"},
            {"protocol_label": "topostake", "relay_profile": "active", "metric": "5"},
            {"protocol_label": "topostake", "relay_profile": "lazy", "metric": "1"},
        ]
        stats = grouped_stats(rows, ["protocol_label", "relay_profile"], "metric")
        self.assertEqual(stats[("topostake", "active")][0], 4.0)
        self.assertEqual(stats[("topostake", "lazy")][0], 1.0)

    def test_paired_metric_uses_reported_asymmetric_ci(self) -> None:
        rows = [
            {
                "experiment": "flooding_cost_to_influence",
                "metric": "adversary_net_income",
                "scenario_value": "5",
                "mean_difference": "-0.4",
                "ci95_low": "-0.7",
                "ci95_high": "-0.2",
            }
        ]
        self.assertEqual(
            paired_metric(rows, "flooding_cost_to_influence", "adversary_net_income"),
            [(5.0, -0.4, 0.29999999999999993, 0.2)],
        )


if __name__ == "__main__":
    unittest.main()
