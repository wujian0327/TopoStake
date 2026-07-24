from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "experiments"))

from frozen_security_report import (  # noqa: E402
    PAIR_METRICS,
    SCENARIO_FIELDS,
    aggregate_run,
    fixed_padding_check,
    group_runs,
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
            "experiment": "path_padding_end_to_end",
            "protocol_label": "topostake",
            "protocol": "topostake",
            "padding_identities": padding,
            "seed_value": seed,
            "git_commit_sha": "test-commit",
            "complete": True,
            "bound_violation_count": 0,
            "max_score_bound_excess": 0.0,
            "max_cap_bound_excess": 0.0,
            "max_bound_order_excess": 0.0,
            "credit_ineligible_path_count": 0,
            "credit_ineligible_path_rate": 0.0,
            "included_tx_total": 1,
            "generated_tx_total": 1,
            "cohort_included_tx_total": 1,
            "inclusion_ratio": 1.0,
            "inclusion_sample_duplicate_count": 0,
            "inclusion_latency_sample_coverage": 1.0,
            "evidence_accounting_mismatch": 0,
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
            "frozen_v1_security_pilot.yaml": 38,
            "frozen_v1_security_main.yaml": 1580,
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
        self.assertTrue(checks["run-revision-consistency"]["passed"])
        self.assertTrue(checks["score-dependent-proposer-bound"]["passed"])
        one_seed = {item["name"]: item for item in validation(rows[:1], expected_seeds=2)}
        self.assertFalse(one_seed["seed-coverage"]["passed"])
        rows[1]["max_cap_bound_excess"] = 0.01
        checks = {item["name"]: item for item in validation(rows, expected_seeds=2)}
        self.assertFalse(checks["score-independent-proposer-cap"]["passed"])
        rows[1]["git_commit_sha"] = "different-commit"
        checks = {item["name"]: item for item in validation(rows, expected_seeds=2)}
        self.assertFalse(checks["run-revision-consistency"]["passed"])

    def test_focal_relayer_isolation_is_validated(self) -> None:
        row = synthetic_run(0, 0, 10.0)
        row.update(
            {
                "experiment": "relay_participation",
                "relay_profile": "active",
                "relay_background_profile": "normal",
                "focal_relayer_count": 1,
                "usable_epoch_count": 4,
                "focal_node_rows": 4,
                "focal_profile_mismatch_count": 0,
                "background_profile_mismatch_count": 0,
                "inclusion_latency_sample_coverage": 1.0,
            }
        )
        checks = {item["name"]: item for item in validation([row], expected_seeds=1)}
        self.assertTrue(checks["focal-relayer-isolation"]["passed"])
        row["background_profile_mismatch_count"] = 1
        checks = {item["name"]: item for item in validation([row], expected_seeds=1)}
        self.assertFalse(checks["focal-relayer-isolation"]["passed"])

    def test_creation_cohort_accounting_rejects_overflow_and_duplicates(self) -> None:
        row = synthetic_run(0, 0, 10.0)
        checks = {item["name"]: item for item in validation([row], expected_seeds=1)}
        self.assertTrue(checks["creation-cohort-inclusion-accounting"]["passed"])
        row["inclusion_ratio"] = 1.01
        checks = {item["name"]: item for item in validation([row], expected_seeds=1)}
        self.assertFalse(checks["creation-cohort-inclusion-accounting"]["passed"])
        row["inclusion_ratio"] = 1.0
        row["inclusion_sample_duplicate_count"] = 1
        checks = {item["name"]: item for item in validation([row], expected_seeds=1)}
        self.assertFalse(checks["creation-cohort-inclusion-accounting"]["passed"])

    def test_group_rows_are_unique_and_skip_structural_nulls(self) -> None:
        rows = [synthetic_run(0, 0, 10.0), synthetic_run(1, 0, 12.0)]
        for row in rows:
            row["focal_bonus_mean"] = float("nan")
            row["focal_proposer_weight_mean"] = float("nan")
        groups = group_runs(rows)
        keys = [(row["experiment"], row["metric"]) for row in groups]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertNotIn(("path_padding_end_to_end", "focal_bonus_mean"), keys)
        self.assertNotIn(("path_padding_end_to_end", "focal_proposer_weight_mean"), keys)

    def test_fixed_padding_report_is_required_and_validated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "padding.json"
            self.assertFalse(fixed_padding_check(path)["passed"])
            path.write_text(
                json.dumps(
                    {
                        "passed": True,
                        "violations": 0,
                        "cases": 10,
                        "coalition_assignments": 20,
                        "maximum_ratio": 0.99,
                    }
                )
            )
            self.assertTrue(fixed_padding_check(path)["passed"])

    def test_credit_ineligible_rate_uses_included_transactions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / "runner_status.json").write_text(json.dumps({"status": "ok"}))
            (output / "run_summary.json").write_text(json.dumps({"completed_epochs": 1}))
            (output / "run_config.json").write_text(
                json.dumps({"git_commit_sha": "test-commit"})
            )
            (output / "epoch_metrics.csv").write_text(
                "epoch,generated_tx,included_tx,valid_path_count,invalid_path_count,"
                "adversary_proposer_weight_share,score_dependent_proposer_weight_bound,"
                "theoretical_proposer_weight_bound,bound_violation\n"
                "0,10,10,7,3,0.1,0.2,0.3,false\n"
            )
            (output / "node_epoch_metrics.csv").write_text(
                "epoch,focal_relayer,adversarial,raw_contribution,relay_reward,"
                "economic_stake,bonus,normalized_proposer_weight\n"
                "0,true,false,1.0,0.1,1.0,0.2,0.01\n"
            )
            (output / "inclusion_samples.csv").write_text(
                "included_epoch,tx_hash,created_slot,included_slot,latency_s,evidence_eligible\n"
                "0,a,0,1,1.0,true\n"
                "0,b,0,2,2.0,true\n"
                "0,c,0,3,3.0,false\n"
                "0,d,0,4,4.0,true\n"
                "0,e,0,5,5.0,true\n"
                "0,f,0,6,6.0,true\n"
                "0,g,0,7,7.0,true\n"
                "0,h,0,8,8.0,true\n"
                "0,i,0,9,9.0,true\n"
                "0,j,0,10,10.0,true\n"
            )
            run = {
                "output_dir": str(output),
                "run_id": "rate-test",
                "seed_index": 0,
                "seed_value": 0,
                "max_epochs": 1,
                "warmup_epochs": 0,
                "slot_per_epoch": 5,
            }
            result = aggregate_run(run)
            self.assertTrue(result["complete"])
            self.assertEqual(result["git_commit_sha"], "test-commit")
            self.assertEqual(result["evidence_accounting_mismatch"], 0)
            self.assertAlmostEqual(result["credit_ineligible_path_rate"], 0.3)
            self.assertEqual(result["cohort_included_tx_total"], 10)
            self.assertAlmostEqual(result["inclusion_ratio"], 1.0)
            self.assertEqual(result["inclusion_sample_duplicate_count"], 0)
            self.assertAlmostEqual(result["p50_inclusion_latency_s_pooled"], 5.5)
            self.assertAlmostEqual(result["p95_inclusion_latency_s_pooled"], 9.55)
            self.assertAlmostEqual(result["inclusion_latency_sample_coverage"], 1.0)
            self.assertAlmostEqual(result["focal_relay_reward_per_stake"], 0.1)

    def test_latency_cohort_is_selected_by_creation_slot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / "runner_status.json").write_text(json.dumps({"status": "ok"}))
            (output / "run_summary.json").write_text(json.dumps({"completed_epochs": 2}))
            (output / "run_config.json").write_text(
                json.dumps({"git_commit_sha": "test-commit"})
            )
            (output / "epoch_metrics.csv").write_text(
                "epoch,generated_tx,included_tx,valid_path_count,invalid_path_count,"
                "adversary_proposer_weight_share,score_dependent_proposer_weight_bound,"
                "theoretical_proposer_weight_bound,bound_violation\n"
                "0,3,0,0,0,0.1,0.2,0.3,false\n"
                "1,2,3,3,0,0.1,0.2,0.3,false\n"
            )
            (output / "node_epoch_metrics.csv").write_text(
                "epoch,focal_relayer,adversarial,raw_contribution,relay_reward,"
                "economic_stake,bonus,normalized_proposer_weight\n"
                "0,false,false,0,0,1,0,0.01\n"
                "1,false,false,0,0,1,0,0.01\n"
            )
            (output / "inclusion_samples.csv").write_text(
                "included_epoch,tx_hash,created_slot,included_slot,latency_s,evidence_eligible\n"
                "1,warmup-a,3,6,3.0,true\n"
                "1,warmup-b,4,6,2.0,true\n"
                "1,cohort-a,5,6,1.0,true\n"
            )
            run = {
                "output_dir": str(output),
                "run_id": "cohort-test",
                "seed_index": 0,
                "seed_value": 0,
                "max_epochs": 2,
                "warmup_epochs": 1,
                "slot_per_epoch": 5,
            }
            result = aggregate_run(run)
            self.assertEqual(result["included_tx_total"], 3)
            self.assertEqual(result["generated_tx_total"], 2)
            self.assertEqual(result["cohort_included_tx_total"], 1)
            self.assertAlmostEqual(result["inclusion_ratio"], 0.5)
            self.assertAlmostEqual(result["p95_inclusion_latency_s_pooled"], 1.0)


if __name__ == "__main__":
    unittest.main()
