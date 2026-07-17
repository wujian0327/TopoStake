import sys
import unittest
from pathlib import Path


EXPERIMENTS = Path(__file__).resolve().parents[1]
if str(EXPERIMENTS) not in sys.path:
    sys.path.insert(0, str(EXPERIMENTS))

from run_sustained_outage import assignment_for, closest_prefix
from sustained_outage_report import (
    effective_weight_epoch,
    group_weight_series,
    paired_rows,
    relay_attempts_by_epoch,
    relay_attempts_during_outage,
)


class SustainedOutageAssignmentTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            {
                "validator_id": str(index),
                "economic_stake": str(stake),
                "bonus": str(bonus),
                "normalized_score": str(score),
            }
            for index, stake, bonus, score in [
                (0, 0.40, 0.1, 0.1),
                (1, 0.30, 0.8, 0.8),
                (2, 0.20, 0.7, 0.7),
                (3, 0.10, 0.2, 0.2),
            ]
        ]

    def test_closest_prefix_does_not_overshoot_when_previous_is_closer(self):
        chosen = closest_prefix(self.rows, 0.50)
        self.assertEqual([row["validator_id"] for row in chosen], ["0"])

    def test_high_score_selection_uses_fixed_score_order(self):
        assignment = assignment_for(self.rows, "high-score", 0.50, 7)
        self.assertEqual(assignment["validator_ids"], [1, 2])
        self.assertAlmostEqual(assignment["realized_stake_fraction"], 0.50)

    def test_random_assignment_is_seed_deterministic(self):
        left = assignment_for(self.rows, "random", 0.40, 123)
        right = assignment_for(list(reversed(self.rows)), "random", 0.40, 123)
        self.assertEqual(left["validator_ids"], right["validator_ids"])
        self.assertEqual(left["assignment_sha256"], right["assignment_sha256"])

    def test_pairing_preserves_directional_miss_delta(self):
        common = {
            "seed_index": 0,
            "selection": "random",
            "target_stake_fraction": 0.25,
            "realized_stake_fraction": 0.24,
            "assignment_sha256": "same",
            "duty_slot_keys": [(10, 0)],
            "steady_group_weight": 0.2,
            "expected_miss_rate": 0.22,
            "chain_growth_ratio": 0.8,
            "steady_p95_inclusion_latency_s": 2.0,
        }
        eta0 = dict(
            common,
            protocol_label="topostake_eta0",
            miss_rate=0.25,
            expected_miss_rate=0.24,
        )
        full = dict(
            common,
            protocol_label="topostake",
            miss_rate=0.20,
            expected_miss_rate=0.20,
        )
        pair = paired_rows([eta0, full])[0]
        self.assertAlmostEqual(pair["miss_rate_improvement"], 0.05)
        self.assertAlmostEqual(pair["expected_miss_rate_improvement"], 0.04)

    def test_node_metric_weight_is_applied_in_following_epoch(self):
        rows = [
            {
                "epoch": "9",
                "validator_id": "1",
                "normalized_proposer_weight": "0.25",
                "bonus": "0.4",
            },
            {
                "epoch": "10",
                "validator_id": "1",
                "normalized_proposer_weight": "0.20",
                "bonus": "0.3",
            },
        ]
        weights, bonuses = group_weight_series(rows, {1}, 10, 12)
        self.assertEqual(effective_weight_epoch(9), 10)
        self.assertEqual(weights, {10: 0.25, 11: 0.20})
        self.assertEqual(bonuses, {10: [0.4], 11: [0.3]})

    def test_relay_audit_includes_first_outage_epoch(self):
        rows = [
            {"epoch": "9", "validator_id": "1", "relay_forward_attempts": "7"},
            {"epoch": "10", "validator_id": "1", "relay_forward_attempts": "2"},
            {"epoch": "11", "validator_id": "1", "relay_forward_attempts": "3"},
            {"epoch": "12", "validator_id": "1", "relay_forward_attempts": "5"},
        ]
        self.assertEqual(relay_attempts_by_epoch(rows, {1}, 10, 12), {10: 2, 11: 3})
        self.assertEqual(relay_attempts_during_outage(rows, {1}, 10, 12), 5)


if __name__ == "__main__":
    unittest.main()
