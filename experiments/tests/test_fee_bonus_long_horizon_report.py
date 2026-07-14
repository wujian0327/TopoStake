import math
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "experiments"))

from fee_bonus_long_horizon_report import (  # noqa: E402
    PAIR_METRICS,
    aggregate_run,
    gini,
    mean_ci,
    paired_rows,
    spearman,
)


class FeeBonusLongHorizonReportTests(unittest.TestCase):
    def test_gini(self) -> None:
        self.assertEqual(gini([1.0, 1.0, 1.0]), 0.0)
        self.assertAlmostEqual(gini([0.0, 0.0, 1.0]), 2.0 / 3.0)

    def test_spearman_with_ties(self) -> None:
        self.assertAlmostEqual(spearman([1, 2, 3], [10, 20, 30]), 1.0)
        self.assertAlmostEqual(spearman([1, 2, 3], [30, 20, 10]), -1.0)
        self.assertTrue(math.isfinite(spearman([1, 1, 1], [2, 3, 4])))

    def test_small_sample_ci_uses_student_t(self) -> None:
        mean, ci, n = mean_ci([1.0, 2.0, 3.0])
        self.assertEqual(n, 3)
        self.assertEqual(mean, 2.0)
        self.assertAlmostEqual(ci, 4.303 / math.sqrt(3.0))

    def test_paired_rows_match_seed_and_fraction(self) -> None:
        base = {
            "complete": True,
            "seed_index": 0,
            "lazy_fraction": 0.25,
        }
        fee = {**base, "protocol_label": "topostake_eta0"}
        full = {**base, "protocol_label": "topostake"}
        for metric in PAIR_METRICS:
            fee[metric] = 1.0
            full[metric] = 1.5
        paired = paired_rows([fee, full])
        self.assertTrue(paired)
        self.assertTrue(all(row["difference"] == 0.5 for row in paired))

    def test_aggregate_run_reads_forward_work_and_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / "runner_status.json").write_text('{"status":"ok"}')
            (output / "run_summary.json").write_text('{"completed_epochs":2}')
            (output / "run_config.json").write_text('{"git_commit_sha":"test"}')
            (output / "epoch_metrics.csv").write_text(
                "epoch,generated_tx,throughput,bound_violation\n"
                "0,1,1.0,false\n1,1,1.0,false\n"
            )
            (output / "node_epoch_metrics.csv").write_text(
                "epoch,validator_id,relay_profile,economic_stake,relay_reward,"
                "proposer_reward,relay_forward_attempts,degree,betweenness\n"
                "0,0,active,1,1,2,10,3,0.2\n"
                "0,1,lazy,1,0,1,2,1,0.0\n"
                "1,0,active,1,1,2,11,3,0.2\n"
                "1,1,lazy,1,0,1,3,1,0.0\n"
            )
            (output / "inclusion_samples.csv").write_text(
                "tx_hash,created_slot,latency_s,evidence_eligible\n"
                "a,0,1.0,true\nb,1,2.0,false\n"
            )
            result = aggregate_run(
                {
                    "output_dir": str(output),
                    "suite": "test",
                    "protocol_version": "frozen-v1",
                    "experiment": "fee_bonus_long_horizon",
                    "run_id": "test-run",
                    "protocol_label": "topostake",
                    "seed_index": 0,
                    "lazy_fraction": 0.5,
                    "warmup_epochs": 0,
                    "slot_per_epoch": 5,
                    "max_epochs": 2,
                }
            )
            self.assertTrue(result["complete"])
            self.assertEqual(result["relay_forward_attempts"], 26.0)
            self.assertEqual(result["credit_eligible_rate"], 0.5)
            self.assertEqual(result["observed_lazy_fraction"], 0.5)
            self.assertTrue(result["profile_comparison_available"])
            self.assertEqual(result["active_proposer_reward_per_stake"], 4.0)
            self.assertEqual(result["lazy_proposer_reward_per_stake"], 2.0)
            self.assertEqual(result["active_total_reward_per_stake"], 6.0)
            self.assertEqual(result["lazy_total_reward_per_stake"], 2.0)
            self.assertEqual(result["participation_reward_premium_per_stake"], 4.0)
            self.assertEqual(result["participation_forward_premium_per_stake"], 16.0)
            self.assertEqual(result["participation_break_even_cost_per_forward"], 0.25)


if __name__ == "__main__":
    unittest.main()
