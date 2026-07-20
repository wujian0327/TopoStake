import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "experiments"))

from organic_capture_report import (  # noqa: E402
    PAIR_METRICS,
    aggregate_run,
    group_rows,
    mean_ci,
    paired_rows,
)


class OrganicCaptureReportTests(unittest.TestCase):
    def test_small_sample_ci_uses_student_t(self) -> None:
        mean, ci, count = mean_ci([1.0, 2.0, 3.0])
        self.assertEqual(count, 3)
        self.assertEqual(mean, 2.0)
        self.assertAlmostEqual(ci, 4.303 / (3.0**0.5))

    def test_aggregate_uses_ratio_of_epoch_totals(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / "runner_status.json").write_text('{"status":"ok"}')
            (output / "run_summary.json").write_text('{"completed_epochs":2}')
            (output / "run_config.json").write_text('{"git_commit_sha":"test"}')
            (output / "epoch_metrics.csv").write_text(
                "epoch,included_tx,organic_included_tx,organic_valid_path_count,"
                "organic_relay_reward,adversary_organic_relay_reward,"
                "organic_raw_contribution,adversary_organic_raw_contribution,"
                "adversary_real_stake_share,adversary_score_share,"
                "adversary_proposer_weight_share,theoretical_proposer_weight_bound,"
                "bound_violation\n"
                "0,10,8,7,1,0.5,2,1,0.2,0.3,0.25,0.28,false\n"
                "1,20,18,16,9,1.5,18,3,0.2,0.4,0.30,0.28,false\n"
            )
            (output / "node_epoch_metrics.csv").write_text(
                "epoch,validator_id,adversarial\n"
                "0,a,true\n0,b,false\n1,a,true\n1,b,false\n"
            )
            result = aggregate_run(
                {
                    "output_dir": str(output),
                    "suite": "test",
                    "protocol_version": "frozen-v1",
                    "experiment": "organic_traffic_capture",
                    "run_id": "test-run",
                    "seed_index": 0,
                    "adversary_stake_fraction": 0.2,
                    "adversary_placement": "random",
                    "attack_mode": "max-score",
                    "warmup_epochs": 0,
                    "max_epochs": 2,
                }
            )
            self.assertTrue(result["complete"])
            self.assertAlmostEqual(result["organic_traffic_fraction"], 26.0 / 30.0)
            self.assertAlmostEqual(result["organic_valid_path_rate"], 23.0 / 26.0)
            self.assertAlmostEqual(
                result["adversary_organic_relay_reward_share"], 2.0 / 10.0
            )
            self.assertAlmostEqual(
                result["adversary_organic_raw_contribution_share"], 4.0 / 20.0
            )
            self.assertAlmostEqual(result["organic_relay_capture_amplification"], 1.0)
            self.assertAlmostEqual(result["score_share_lift"], 0.15)

    def test_pairs_match_mode_within_seed_stake_and_placement(self) -> None:
        base = {
            "complete": True,
            "seed_index": 0,
            "adversary_stake_fraction": 0.1,
            "adversary_placement": "random",
        }
        baseline = {**base, "attack_mode": "none"}
        stress = {**base, "attack_mode": "max-score"}
        for metric in PAIR_METRICS:
            baseline[metric] = 0.1
            stress[metric] = 0.2
        pairs = paired_rows([baseline, stress])
        self.assertEqual(len(pairs), len(PAIR_METRICS))
        self.assertTrue(all(abs(row["difference"] - 0.1) < 1e-12 for row in pairs))
        groups = group_rows([baseline, stress], pairs)
        self.assertTrue(
            any(row["series"] == "max-score-minus-none:random" for row in groups)
        )


if __name__ == "__main__":
    unittest.main()
