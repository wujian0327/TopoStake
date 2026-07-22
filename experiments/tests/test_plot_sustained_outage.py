from __future__ import annotations

import math
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "analysis"))

from plot_sustained_outage import (  # noqa: E402
    grouped_run_metric,
    mean_ci,
    render_adaptation,
    render_eta_sweep,
    render_missed_slot_rate,
    render_weight_share,
    trailing_means,
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
                for target in (0.10, 0.20, 0.30):
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
        rows = []
        for seed in range(3):
            for selection in ("random", "high-score"):
                for target in (0.10, 0.20, 0.30):
                    improvement = (
                        0.01 + 0.001 * seed
                        if selection == "random"
                        else -0.002 * seed
                    )
                    rows.append(
                        {
                            "seed_index": str(seed),
                            "selection": selection,
                            "target_stake_fraction": str(target),
                            "eta0_miss_rate": str(target),
                            "full_miss_rate": str(target - improvement),
                            "miss_rate_improvement": str(improvement),
                        }
                    )
        return rows

    def epoch_pairs(self) -> list[dict[str, str]]:
        rows = []
        for seed in range(3):
            for target in (0.10, 0.20, 0.30):
                for epoch in range(5):
                    rows.append(
                        {
                            "seed_index": str(seed),
                            "selection": "random",
                            "target_stake_fraction": str(target),
                            "epoch_since_outage": str(epoch),
                            "weight_share_reduction": str(
                                target * epoch / 100.0
                            ),
                        }
                    )
        return rows

    def eta_pairs(self) -> list[dict[str, str]]:
        rows = []
        for seed in range(3):
            for eta in (0.25, 0.5, 0.75, 1.0):
                rows.append(
                    {
                        "seed_index": str(seed),
                        "selection": "random",
                        "target_stake_fraction": "0.2",
                        "eta": str(eta),
                        "steady_expected_miss_rate_improvement": str(0.02 * eta),
                        "miss_rate_improvement": str(0.018 * eta),
                    }
                )
        return rows

    def test_grouped_run_metric_selects_protocol(self) -> None:
        grouped = grouped_run_metric(
            self.runs(), "steady_group_weight", "random", "topostake"
        )
        self.assertEqual(len(grouped[0.10]), 3)
        self.assertAlmostEqual(grouped[0.10][0], 9.0)

    def test_adaptation_smoothing_is_trailing_and_seed_local(self) -> None:
        values = {0: 0.0, 1: 1.0, 2: 2.0, 3: 3.0}
        self.assertEqual(
            trailing_means(values, window=3),
            {0: 0.0, 1: 0.5, 2: 1.0, 3: 2.0},
        )

    def test_panels_are_independent_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            for selection, suffix in (("random", "random"), ("high-score", "high")):
                render_weight_share(
                    self.runs(), selection, output / f"weight_{suffix}"
                )
                render_missed_slot_rate(
                    self.pairs(), selection, output / f"miss_{suffix}"
                )
            render_adaptation(
                self.epoch_pairs(), "random", output / "adaptation_random"
            )
            render_eta_sweep(
                self.eta_pairs(), "random", output / "eta_sweep_random"
            )
            for stem in ("weight_random", "weight_high", "miss_random", "miss_high"):
                self.assertTrue((output / f"{stem}.pdf").exists())
                self.assertTrue((output / f"{stem}.png").exists())
            self.assertTrue((output / "adaptation_random.pdf").exists())
            self.assertTrue((output / "adaptation_random.png").exists())
            self.assertTrue((output / "eta_sweep_random.pdf").exists())
            self.assertTrue((output / "eta_sweep_random.png").exists())


if __name__ == "__main__":
    unittest.main()
