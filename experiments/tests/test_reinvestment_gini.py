from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "experiments"))
sys.path.insert(0, str(ROOT / "analysis"))

from plot_reinvestment_gini import render  # noqa: E402
from reinvestment_gini_report import (  # noqa: E402
    endpoint_pairs,
    gini,
    grouped_rows,
    stake_gini_trajectory,
)
from run_experiments import expand_runs  # noqa: E402


class ReinvestmentGiniTests(unittest.TestCase):
    def test_trajectory_includes_initial_and_post_epoch_state(self) -> None:
        rows = [
            {
                "epoch": "0",
                "validator_id": "0",
                "economic_stake": "1.0",
                "proposer_reward": "1.0",
                "relay_reward": "0.0",
            },
            {
                "epoch": "0",
                "validator_id": "1",
                "economic_stake": "1.0",
                "proposer_reward": "0.0",
                "relay_reward": "0.0",
            },
            {
                "epoch": "1",
                "validator_id": "0",
                "economic_stake": "1.5",
                "proposer_reward": "0.0",
                "relay_reward": "0.0",
            },
            {
                "epoch": "1",
                "validator_id": "1",
                "economic_stake": "1.0",
                "proposer_reward": "0.0",
                "relay_reward": "1.0",
            },
        ]
        points, continuity = stake_gini_trajectory(rows, 0.5)
        self.assertEqual([point["epoch"] for point in points], [0, 1, 2])
        self.assertAlmostEqual(points[0]["stake_gini"], 0.0)
        self.assertAlmostEqual(points[1]["stake_gini"], gini([1.5, 1.0]))
        self.assertAlmostEqual(points[2]["stake_gini"], 0.0)
        self.assertEqual(continuity, 0.0)

    def test_endpoint_pair_direction_is_full_minus_fee_only(self) -> None:
        rows = []
        for protocol, final in (
            ("pos", 0.61),
            ("topostake_eta0", 0.62),
            ("topostake", 0.64),
        ):
            rows.extend(
                [
                    {
                        "seed_index": 0,
                        "protocol_label": protocol,
                        "epoch": 0,
                        "stake_gini": 0.6,
                    },
                    {
                        "seed_index": 0,
                        "protocol_label": protocol,
                        "epoch": 1000,
                        "stake_gini": final,
                    },
                ]
            )
        pair = endpoint_pairs(rows)[0]
        self.assertAlmostEqual(pair["full_minus_fee_only"], 0.02)
        self.assertAlmostEqual(pair["full_minus_pos"], 0.03)

    def test_main_config_is_the_fixed_60_run_matrix(self) -> None:
        spec = json.loads(
            (ROOT / "experiments/configs/frozen_v1_reinvestment_gini_main.yaml").read_text()
        )
        runs = expand_runs(spec)
        self.assertEqual(len(runs), 60)
        self.assertEqual(
            {run["protocol_label"] for run in runs},
            {"pos", "topostake_eta0", "topostake"},
        )
        self.assertTrue(all(run["reward_reinvestment_rate"] == 0.5 for run in runs))
        self.assertTrue(all(run["max_epochs"] == 1000 for run in runs))
        self.assertTrue(all(run["stake_gini"] == 0.6 for run in runs))
        self.assertTrue(all(run["topology"] == "ba" for run in runs))

    def test_three_protocol_plot_is_written(self) -> None:
        rows = []
        for protocol, offset in (
            ("pos", 0.0),
            ("topostake_eta0", 0.01),
            ("topostake", 0.02),
        ):
            for epoch in (0, 500, 1000):
                mean = 0.6 + offset * epoch / 1000.0
                rows.append(
                    {
                        "protocol_label": protocol,
                        "epoch": str(epoch),
                        "n": "20",
                        "mean": str(mean),
                        "ci95_low": str(mean - 0.002),
                        "ci95_high": str(mean + 0.002),
                    }
                )
        # Exercise grouping separately so malformed run-level inputs fail tests.
        grouped_rows(
            {
                "protocol_label": row["protocol_label"],
                "epoch": int(row["epoch"]),
                "stake_gini": float(row["mean"]),
            }
            for row in rows
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "reinvestment_gini"
            render(rows, output)
            self.assertTrue(output.with_suffix(".pdf").exists())
            self.assertTrue(output.with_suffix(".png").exists())
            self.assertTrue(output.with_suffix(".svg").exists())


if __name__ == "__main__":
    unittest.main()
