from __future__ import annotations

import csv
import math
import statistics
import sys
import tempfile
import unittest
from pathlib import Path


EXPERIMENTS = Path(__file__).resolve().parents[1]
ANALYSIS = EXPERIMENTS.parent / "analysis"
if str(EXPERIMENTS) not in sys.path:
    sys.path.insert(0, str(EXPERIMENTS))
if str(ANALYSIS) not in sys.path:
    sys.path.insert(0, str(ANALYSIS))

from adaptive_participation_report import (  # noqa: E402
    benefit_accounting_counts,
    cohort_inclusion_metrics,
    grouped_rows,
    grouped_post_adaptation_drifts,
    mean_ci,
    merge_processed_parts,
    paired_rows,
    percentile,
    post_adaptation_stats,
    requires_initialization_robustness,
)
from run_experiments import command_for_run, expand_runs, load_yaml  # noqa: E402
from plot_adaptive_participation import (  # noqa: E402
    plot_latency,
    plot_steady_state,
    plot_trajectory,
)


class AdaptiveParticipationTests(unittest.TestCase):
    def test_initialization_robustness_only_applies_to_multi_initial_pilot(
        self,
    ) -> None:
        self.assertTrue(requires_initialization_robustness("full_pilot"))
        self.assertFalse(requires_initialization_robustness("sensitivity"))
        self.assertFalse(requires_initialization_robustness("holdout"))
        self.assertFalse(requires_initialization_robustness("stability_probe"))

    def test_multi_cost_plots_are_generated_independently(self) -> None:
        groups = []
        trajectory = []
        for protocol_index, protocol in enumerate(
            ("pos", "topostake_eta0", "topostake")
        ):
            for cost in (1.0, 2.0, 3.0):
                groups.append(
                    {
                        "protocol_label": protocol,
                        "initial_active_fraction": "0.5",
                        "cost_median_multiplier": str(cost),
                        "steady_active_stake_share": str(
                            0.2 + 0.2 * protocol_index - 0.02 * cost
                        ),
                        "steady_active_stake_share_ci95": "0.01",
                        "restricted_mean_inclusion_latency_s": str(
                            4.0 - protocol_index + 0.1 * cost
                        ),
                        "restricted_mean_inclusion_latency_s_ci95": "0.05",
                    }
                )
            for epoch in range(3):
                trajectory.append(
                    {
                        "protocol_label": protocol,
                        "initial_active_fraction": "0.5",
                        "cost_median_multiplier": "2.0",
                        "epoch": str(epoch),
                        "active_stake_share": str(
                            0.2 + 0.2 * protocol_index + 0.01 * epoch
                        ),
                        "ci95": "0.01",
                    }
                )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            generated = []
            generated.extend(plot_trajectory(trajectory, output))
            generated.extend(plot_steady_state(groups, output))
            generated.extend(plot_latency(groups, output))
            self.assertEqual(len(generated), 6)
            self.assertTrue(all(path.exists() for path in generated))

    def test_missing_counterfactual_is_not_an_accounting_error(self) -> None:
        counts = benefit_accounting_counts(
            [
                {
                    "update_applied": "true",
                    "observed_benefit_per_forward": "",
                    "active_expected_reward_per_stake": "1.0",
                    "lazy_expected_reward_per_stake": "",
                    "active_forward_attempts_per_stake": "4.0",
                    "lazy_forward_attempts_per_stake": "",
                }
            ]
        )
        self.assertEqual(counts["attempts"], 1)
        self.assertEqual(counts["observed"], 0)
        self.assertEqual(counts["unavailable"], 1)
        self.assertEqual(counts["errors"], 0)

    def test_observed_benefit_is_reconstructed_from_components(self) -> None:
        counts = benefit_accounting_counts(
            [
                {
                    "update_applied": "true",
                    "observed_benefit_per_forward": "0.1",
                    "active_expected_reward_per_stake": "0.8",
                    "lazy_expected_reward_per_stake": "0.4",
                    "active_forward_attempts_per_stake": "5.0",
                    "lazy_forward_attempts_per_stake": "1.0",
                }
            ]
        )
        self.assertEqual(counts["observed"], 1)
        self.assertEqual(counts["unavailable"], 0)
        self.assertEqual(counts["errors"], 0)

    def test_accounting_mismatch_is_rejected(self) -> None:
        counts = benefit_accounting_counts(
            [
                {
                    "update_applied": "true",
                    "observed_benefit_per_forward": "0.2",
                    "active_expected_reward_per_stake": "0.8",
                    "lazy_expected_reward_per_stake": "0.4",
                    "active_forward_attempts_per_stake": "5.0",
                    "lazy_forward_attempts_per_stake": "1.0",
                }
            ]
        )
        self.assertEqual(counts["errors"], 1)

    def test_runner_emits_history_only_agent_flags(self) -> None:
        run = {
            "protocol": "topostake",
            "run_id": "adaptive-test",
            "output_dir": "results/adaptive-test",
            "adaptive_relay_participation": True,
            "adaptive_initial_active_fraction": 0.5,
            "adaptive_cost_reference": 1.4e-7,
            "adaptive_cost_median_multiplier": 1.0,
            "adaptive_exploration_fraction": 0.05,
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
        index = command.index("--adaptive-exploration-fraction")
        self.assertEqual(command[index + 1], "0.05")

    def test_post_adaptation_stability_uses_half_window_drift(self) -> None:
        drift, spread = post_adaptation_stats([0.4, 0.6, 0.5, 0.5])
        self.assertAlmostEqual(drift, 0.0)
        self.assertGreater(spread, 0.0)

    def test_grouped_drift_uses_seed_averaged_trajectory(self) -> None:
        rows = [
            {
                "protocol_label": "topostake",
                "initial_active_fraction": "0.5",
                "cost_median_multiplier": "2.0",
                "epoch": str(epoch),
                "active_stake_share": str(value),
            }
            for epoch, value in enumerate((0.2, 0.4, 0.5, 0.5, 0.6, 0.6))
        ]
        drifts = grouped_post_adaptation_drifts(rows, analysis_start_epoch=2)
        self.assertAlmostEqual(
            drifts["topostake@initial=0.5@cost=2"], 0.1
        )

    def test_stability_probe_expands_to_24_unique_runs(self) -> None:
        config = (
            EXPERIMENTS
            / "configs"
            / "frozen_v1_adaptive_participation_stability_probe.yaml"
        )
        runs = expand_runs(load_yaml(config))
        self.assertEqual(len(runs), 24)
        self.assertEqual(len({run["run_id"] for run in runs}), 24)
        self.assertEqual(
            {run["protocol_label"] for run in runs},
            {"topostake_eta0", "topostake"},
        )
        self.assertEqual({run["max_epochs"] for run in runs}, {300})
        self.assertEqual({run["warmup_epochs"] for run in runs}, {200})

    def test_holdout_expands_to_180_runs_with_disjoint_seeds(self) -> None:
        config = (
            EXPERIMENTS
            / "configs"
            / "frozen_v1_adaptive_participation_main.yaml"
        )
        runs = expand_runs(load_yaml(config))
        self.assertEqual(len(runs), 180)
        self.assertEqual(len({run["run_id"] for run in runs}), 180)
        self.assertEqual({run["seed_value"] for run in runs}, set(range(100, 120)))
        self.assertEqual({run["adaptive_initial_active_fraction"] for run in runs}, {0.5})
        self.assertEqual({run["max_epochs"] for run in runs}, {200})
        self.assertEqual({run["warmup_epochs"] for run in runs}, {100})
        self.assertEqual(
            sum(run["protocol_label"] == "pos" for run in runs),
            60,
        )
        self.assertEqual(
            {
                run["adaptive_cost_median_multiplier"]
                for run in runs
            },
            {1.0, 2.0, 3.0},
        )

    def test_sensitivity_expands_to_40_one_factor_runs(self) -> None:
        config = (
            EXPERIMENTS
            / "configs"
            / "frozen_v1_adaptive_participation_sensitivity.yaml"
        )
        runs = expand_runs(load_yaml(config))
        self.assertEqual(len(runs), 40)
        self.assertEqual(len({run["run_id"] for run in runs}), 40)
        self.assertEqual({run["seed_value"] for run in runs}, set(range(200, 205)))
        by_experiment = {}
        for run in runs:
            by_experiment.setdefault(run["experiment"], run)
        self.assertEqual(
            by_experiment["frozen_baseline"]["adaptive_update_fraction"], 0.10
        )
        self.assertEqual(
            by_experiment["faster_updates"]["adaptive_update_fraction"], 0.20
        )
        self.assertEqual(
            by_experiment["lower_hysteresis"]["adaptive_switching_hysteresis"],
            0.05,
        )
        self.assertEqual(
            by_experiment["lower_exploration"]["adaptive_exploration_fraction"],
            0.025,
        )

    def test_pair_direction_is_full_minus_fee_only(self) -> None:
        common = {
            "experiment": "test",
            "complete": True,
            "seed_index": 0,
            "seed_value": 100,
            "initial_active_fraction": 0.5,
            "cost_median_multiplier": 1.0,
            "adaptive_update_fraction": 0.10,
            "adaptive_switching_hysteresis": 0.10,
            "adaptive_exploration_fraction": 0.05,
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
                    "experiment": "test",
                    "complete": True,
                    "protocol_label": "topostake",
                    "initial_active_fraction": 0.5,
                    "cost_median_multiplier": 1.0,
                    "adaptive_update_fraction": 0.10,
                    "adaptive_switching_hysteresis": 0.10,
                    "adaptive_exploration_fraction": 0.05,
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

    def test_holdout_ci_uses_student_t_for_twenty_pairs(self) -> None:
        mean, ci, count = mean_ci(range(20))
        expected = 2.093 * statistics.stdev(range(20)) / math.sqrt(20)
        self.assertEqual(count, 20)
        self.assertAlmostEqual(mean, 9.5)
        self.assertAlmostEqual(ci, expected)

    def test_processed_parts_merge_by_seed_value_and_pool_trajectory(self) -> None:
        trajectory_fields = [
            "experiment",
            "protocol_label",
            "initial_active_fraction",
            "cost_median_multiplier",
            "adaptive_update_fraction",
            "adaptive_switching_hysteresis",
            "adaptive_exploration_fraction",
            "epoch",
            "active_stake_share",
            "ci95",
            "n",
        ]
        run_fields = [
            "experiment",
            "protocol_label",
            "seed_index",
            "seed_value",
            "initial_active_fraction",
            "cost_median_multiplier",
            "adaptive_update_fraction",
            "adaptive_benefit_ema_alpha",
            "adaptive_switching_hysteresis",
            "adaptive_exploration_fraction",
            "complete",
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_paths = []
            trajectory_paths = []
            for part, (seed_value, mean) in enumerate(((100, 0.4), (101, 0.6))):
                run_path = root / f"runs-{part}.csv"
                trajectory_path = root / f"trajectory-{part}.csv"
                with run_path.open("w", newline="", encoding="utf-8") as handle:
                    writer = csv.DictWriter(handle, fieldnames=run_fields)
                    writer.writeheader()
                    writer.writerow(
                        {
                            "experiment": "holdout",
                            "protocol_label": "topostake",
                            "seed_index": 0,
                            "seed_value": seed_value,
                            "initial_active_fraction": 0.5,
                            "cost_median_multiplier": 2.0,
                            "adaptive_update_fraction": 0.1,
                            "adaptive_benefit_ema_alpha": 0.25,
                            "adaptive_switching_hysteresis": 0.1,
                            "adaptive_exploration_fraction": 0.05,
                            "complete": True,
                        }
                    )
                with trajectory_path.open(
                    "w", newline="", encoding="utf-8"
                ) as handle:
                    writer = csv.DictWriter(handle, fieldnames=trajectory_fields)
                    writer.writeheader()
                    writer.writerow(
                        {
                            "experiment": "holdout",
                            "protocol_label": "topostake",
                            "initial_active_fraction": 0.5,
                            "cost_median_multiplier": 2.0,
                            "adaptive_update_fraction": 0.1,
                            "adaptive_switching_hysteresis": 0.1,
                            "adaptive_exploration_fraction": 0.05,
                            "epoch": 0,
                            "active_stake_share": mean,
                            "ci95": 0.0,
                            "n": 2,
                        }
                    )
                run_paths.append(run_path)
                trajectory_paths.append(trajectory_path)
            expected = [
                {
                    "experiment": "holdout",
                    "protocol_label": "topostake",
                    "seed_value": seed_value,
                    "adaptive_initial_active_fraction": 0.5,
                    "adaptive_cost_median_multiplier": 2.0,
                    "adaptive_update_fraction": 0.1,
                    "adaptive_benefit_ema_alpha": 0.25,
                    "adaptive_switching_hysteresis": 0.1,
                    "adaptive_exploration_fraction": 0.05,
                }
                for seed_value in (100, 101)
            ]
            runs, trajectories = merge_processed_parts(
                run_paths, trajectory_paths, expected
            )
            self.assertEqual([row["seed_index"] for row in runs], [0, 1])
            self.assertEqual(trajectories[0]["n"], 4)
            self.assertAlmostEqual(
                trajectories[0]["active_stake_share"], 0.5
            )
            self.assertGreater(trajectories[0]["ci95"], 0.0)

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
