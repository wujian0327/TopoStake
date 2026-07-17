from __future__ import annotations

import math
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "analysis"))

from plot_sustained_outage import (  # noqa: E402
    mean_ci,
    paired_run_deltas,
    render_missed_slots,
    render_weight_response,
)


class SustainedOutagePlotTests(unittest.TestCase):
    def test_small_sample_ci_uses_student_t(self) -> None:
        mean, ci, count = mean_ci([1.0, 2.0, 3.0])
        self.assertEqual(count, 3)
        self.assertAlmostEqual(mean, 2.0)
        self.assertAlmostEqual(ci, 4.303 / math.sqrt(3))

    def runs(self) -> list[dict[str, str]]:
        rows = []
        for seed in range(3):
            for selection, initial_bonus in (("random", 0.0), ("high-score", 0.02)):
                for target in (0.10, 0.25, 0.40):
                    for protocol in ("topostake_eta0", "topostake"):
                        full = protocol == "topostake"
                        rows.append(
                            {
                                "seed_index": str(seed),
                                "selection": selection,
                                "target_stake_fraction": str(target),
                                "protocol_label": protocol,
                                "initial_group_weight": str(
                                    target + (initial_bonus if full else 0.0)
                                ),
                                "steady_group_weight": str(
                                    target - (0.01 if full else 0.0)
                                ),
                            }
                        )
        return rows

    def pairs(self) -> list[dict[str, str]]:
        return [
            {
                "seed_index": str(seed),
                "selection": selection,
                "target_stake_fraction": str(target),
                "miss_rate_improvement": str(
                    0.01 + 0.001 * seed if selection == "random" else -0.002 * seed
                ),
            }
            for seed in range(3)
            for selection in ("random", "high-score")
            for target in (0.10, 0.25, 0.40)
        ]

    def test_run_delta_uses_full_minus_eta0(self) -> None:
        deltas = paired_run_deltas(self.runs(), "steady_group_weight")
        self.assertEqual(len(deltas[("random", 0.10)]), 3)
        self.assertAlmostEqual(deltas[("random", 0.10)][0], -1.0)

    def test_panels_are_independent_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            render_weight_response(self.runs(), output / "weight")
            render_missed_slots(self.pairs(), output / "miss")
            for stem in ("weight", "miss"):
                self.assertTrue((output / f"{stem}.pdf").exists())
                self.assertTrue((output / f"{stem}.png").exists())


if __name__ == "__main__":
    unittest.main()
