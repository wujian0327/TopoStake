from __future__ import annotations

import sys
import unittest
from pathlib import Path


EXPERIMENTS = Path(__file__).resolve().parents[1]
if str(EXPERIMENTS) not in sys.path:
    sys.path.insert(0, str(EXPERIMENTS))

from adaptive_participation_report import (  # noqa: E402
    cohort_inclusion_metrics,
    grouped_rows,
    paired_rows,
    percentile,
)
from run_experiments import command_for_run  # noqa: E402


class AdaptiveParticipationTests(unittest.TestCase):
    def test_runner_emits_history_only_agent_flags(self) -> None:
        run = {
            "protocol": "topostake",
            "run_id": "adaptive-test",
            "output_dir": "results/adaptive-test",
            "adaptive_relay_participation": True,
            "adaptive_initial_active_fraction": 0.5,
            "adaptive_cost_reference": 1.4e-7,
            "adaptive_cost_median_multiplier": 1.0,
            "graph_seed": 1,
            "wallet_seed": 2,
            "workload_seed": 3,
            "election_seed": 4,
            "failure_seed": 5,
            "attack_seed": 6,
        }
        command = command_for_run("target/release/topostake", run)
        self.assertIn("--adaptive-relay-participation", command)
        self.assertEqual(command.count("--adaptive-relay-participation"), 1)
        index = command.index("--adaptive-initial-active-fraction")
        self.assertEqual(command[index + 1], "0.5")

    def test_pair_direction_is_full_minus_fee_only(self) -> None:
        common = {
            "complete": True,
            "seed_index": 0,
            "initial_active_fraction": 0.5,
            "cost_median_multiplier": 1.0,
            "inclusion_within_horizon_rate": 0.7,
            "restricted_mean_inclusion_latency_s": 5.0,
        }
        rows = [
            {
                **common,
                "protocol_label": "topostake_eta0",
                "steady_active_stake_share": 0.4,
            },
            {
                **common,
                "protocol_label": "topostake",
                "steady_active_stake_share": 0.7,
                "inclusion_within_horizon_rate": 0.8,
                "restricted_mean_inclusion_latency_s": 3.0,
            },
        ]
        pair = paired_rows(rows)[0]
        self.assertAlmostEqual(pair["active_stake_gain"], 0.3)
        self.assertAlmostEqual(pair["inclusion_rate_gain"], 0.1)
        self.assertAlmostEqual(pair["restricted_mean_latency_reduction_s"], 2.0)

    def test_grouped_rows_keep_initial_conditions_separate(self) -> None:
        rows = []
        for seed, value in ((0, 0.6), (1, 0.8)):
            rows.append(
                {
                    "complete": True,
                    "protocol_label": "topostake",
                    "initial_active_fraction": 0.5,
                    "cost_median_multiplier": 1.0,
                    "steady_active_fraction": value,
                    "steady_active_stake_share": value,
                    "inclusion_within_horizon_rate": 0.9,
                    "completed_p95_inclusion_latency_s": 2.0,
                    "timeout_adjusted_p95_latency_s": 2.0,
                    "restricted_mean_inclusion_latency_s": 1.5,
                    "utility_consistency_share": 0.9,
                }
            )
        grouped = grouped_rows(rows)
        self.assertEqual(len(grouped), 1)
        self.assertAlmostEqual(grouped[0]["steady_active_stake_share"], 0.7)
        self.assertEqual(grouped[0]["steady_active_stake_share_n"], 2)

    def test_percentile_interpolates(self) -> None:
        self.assertAlmostEqual(percentile([1.0, 3.0], 0.5), 2.0)

    def test_cohort_metrics_penalize_transactions_missing_at_horizon(self) -> None:
        generated = [
            {"tx_hash": "a", "created_epoch": "2", "created_slot": "0"},
            {"tx_hash": "b", "created_epoch": "2", "created_slot": "1"},
            {"tx_hash": "late", "created_epoch": "9", "created_slot": "4"},
        ]
        inclusion = [
            {
                "tx_hash": "a",
                "included_slot": "12",
                "latency_s": "2.0",
            }
        ]
        metrics = cohort_inclusion_metrics(
            generated,
            inclusion,
            warmup_epochs=2,
            max_epochs=10,
            slots_per_epoch=5,
            slot_duration_s=1.0,
            followup_epochs=2,
        )
        self.assertEqual(metrics["cohort_generated_tx"], 2)
        self.assertEqual(metrics["cohort_included_tx"], 1)
        self.assertAlmostEqual(metrics["inclusion_within_horizon_rate"], 0.5)
        self.assertAlmostEqual(metrics["restricted_mean_inclusion_latency_s"], 6.0)
        self.assertAlmostEqual(metrics["timeout_adjusted_p95_latency_s"], 9.6)


if __name__ == "__main__":
    unittest.main()
