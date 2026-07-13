from __future__ import annotations

import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "experiments"))

from frozen_devnet_acceptance import artifact_checks, static_checks  # noqa: E402
from run_frozen_devnet_smoke import enrich_irrecoverable_costs  # noqa: E402


def sample(value: float, **labels: str) -> dict:
    return {"metric": labels, "value": str(value)}


def base_summary() -> dict:
    return {
        "beacon_before_measurement": {"finalized_epoch": 3},
        "beacon_after": {"finalized_epoch": 4, "head_slot": 32},
        "peer_graph": {"matches_target": True},
        "blocks": {"records": []},
        "geth_topostake_status": [
            {
                "dynamic_relay_epoch": True,
                "relay_epoch": 4,
                "seconds_per_slot": 3,
                "slots_per_epoch": 8,
            }
        ],
        "prometheus": {
            "topostake_fee_conservation_violation": [sample(0)],
            "topostake_fee_settlement_amount_wei": [sample(1)],
            "topostake_epoch_score_scaled": [sample(0)],
            "topostake_evidence_epoch_invalid_paths": [sample(0)],
        },
    }


class FrozenDevnetAcceptanceTests(unittest.TestCase):
    def test_static_profile_matches_golden_vectors(self) -> None:
        failures = [item for item in static_checks() if not item.passed]
        self.assertEqual(failures, [])

    def test_baseline_artifact_has_no_topostake_effects(self) -> None:
        failures = [item for item in artifact_checks(base_summary(), "baseline") if not item.passed]
        self.assertEqual(failures, [])

    def test_topostake_artifact_satisfies_frozen_envelope(self) -> None:
        summary = base_summary()
        summary["blocks"]["records"] = [
            {
                "slot": 32,
                "epoch": 4,
                "path_len": 3,
                "path": [0, 1, 2],
                "irrecoverable_cost_wei": 21_000_000_000_000,
            }
        ]
        summary["prometheus"].update(
            {
                "topostake_evidence_epoch_valid_paths": [sample(1)],
                "topostake_epoch_score_scaled": [sample(100)],
                "topostake_proposer_score_scaled": [sample(100)],
                "topostake_selection_score_epoch": [
                    sample(2, slot="32", proposer_epoch="4"),
                    sample(2, slot="33", proposer_epoch="4"),
                ],
                "topostake_proposer_weight_scaled": [
                    sample(32_000_000_000_000_000_000, slot="32", proposer_epoch="4", validator_index="0"),
                    sample(32_000_000_000_000_000_000, slot="33", proposer_epoch="4", validator_index="0"),
                ],
                "topostake_selected_proposer": [
                    sample(1, slot="32", proposer_epoch="4", validator_index="0"),
                    sample(1, slot="33", proposer_epoch="4", validator_index="0"),
                ],
            }
        )
        failures = [item for item in artifact_checks(summary, "topostake") if not item.passed]
        self.assertEqual(failures, [])

    def test_fee_only_requires_fee_settlement_but_no_bonus(self) -> None:
        summary = base_summary()
        summary["blocks"]["records"] = [
            {
                "slot": 32,
                "epoch": 4,
                "path_len": 2,
                "path": [0, 1],
                "irrecoverable_cost_wei": 1,
            }
        ]
        summary["prometheus"].update(
            {
                "topostake_evidence_epoch_valid_paths": [sample(1)],
                "topostake_epoch_score_scaled": [sample(1)],
                "topostake_proposer_score_scaled": [sample(1)],
                "topostake_selection_score_epoch": [sample(2, proposer_epoch="4")],
                "topostake_proposer_weight_scaled": [
                    sample(
                        32_000_000_000_000_000_000,
                        instance="cl-1",
                        slot="32",
                        proposer_epoch="4",
                        validator_index="0",
                    )
                ],
                "topostake_selected_proposer": [
                    sample(1, slot="32", proposer_epoch="4", validator_index="0")
                ],
            }
        )
        failures = [item for item in artifact_checks(summary, "fee_only") if not item.passed]
        self.assertEqual(failures, [])

        summary["prometheus"]["topostake_fee_settlement_amount_wei"] = [sample(0)]
        by_name = {item.name: item for item in artifact_checks(summary, "fee_only")}
        self.assertFalse(by_name["fee-settlement-positive"].passed)

    def test_stale_evidence_is_allowed_only_when_excluded_from_credit(self) -> None:
        summary = base_summary()
        summary["blocks"]["records"] = [
            {
                "slot": 32,
                "epoch": 3,
                "path_len": 3,
                "path": [0, 1, 2],
                "irrecoverable_cost_wei": 1,
            }
        ]
        summary["prometheus"]["topostake_evidence_epoch_valid_paths"] = [sample(1)]
        summary["prometheus"]["topostake_evidence_epoch_invalid_paths"] = [sample(1)]
        by_name = {item.name: item for item in artifact_checks(summary, "pathobs")}
        self.assertTrue(by_name["evidence-epoch-not-future"].passed)
        self.assertTrue(by_name["stale-evidence-no-credit"].passed)

        summary["prometheus"]["topostake_evidence_epoch_invalid_paths"] = [sample(0)]
        by_name = {item.name: item for item in artifact_checks(summary, "pathobs")}
        self.assertFalse(by_name["stale-evidence-no-credit"].passed)

    def test_future_epoch_evidence_is_rejected_by_acceptance(self) -> None:
        summary = base_summary()
        summary["blocks"]["records"] = [
            {
                "slot": 32,
                "epoch": 5,
                "path_len": 2,
                "path": [0, 1],
                "irrecoverable_cost_wei": 1,
            }
        ]
        summary["prometheus"]["topostake_evidence_epoch_valid_paths"] = [sample(1)]
        by_name = {item.name: item for item in artifact_checks(summary, "pathobs")}
        self.assertFalse(by_name["evidence-epoch-not-future"].passed)

    def test_live_block_cost_is_copied_into_artifact(self) -> None:
        summary = base_summary()
        summary["endpoints"] = {"cl_apis": ["http://cl.test"]}
        summary["blocks"]["records"] = [
            {"slot": 32, "record_index": 0, "tx_hash": "0xabc", "epoch": 4}
        ]
        beacon_payload = {
            "data": {
                "message": {
                    "body": {
                        "topostake_evidence_records": [
                            {
                                "tx_hash": "0xabc",
                                "epoch": 4,
                                "irrecoverable_cost_wei": "21000",
                            }
                        ]
                    }
                }
            }
        }

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps(beacon_payload).encode()

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "summary.json"
            path.write_text(json.dumps(summary))
            with patch("urllib.request.urlopen", return_value=Response()):
                enrich_irrecoverable_costs(path)
            enriched = json.loads(path.read_text())

        self.assertEqual(enriched["blocks"]["records"][0]["irrecoverable_cost_wei"], 21_000)
        self.assertEqual(enriched["blocks"]["irrecoverable_cost_sum_wei"], 21_000)

    def test_cross_node_proposer_divergence_is_rejected(self) -> None:
        summary = base_summary()
        summary["blocks"]["records"] = [
            {
                "slot": 32,
                "epoch": 4,
                "path_len": 2,
                "path": [0, 1],
                "irrecoverable_cost_wei": 1,
            }
        ]
        summary["prometheus"].update(
            {
                "topostake_evidence_epoch_valid_paths": [sample(1)],
                "topostake_epoch_score_scaled": [sample(1)],
                "topostake_proposer_score_scaled": [sample(1)],
                "topostake_selection_score_epoch": [sample(2, proposer_epoch="4")],
                "topostake_proposer_weight_scaled": [
                    sample(32_000_000_000_000_000_000, instance="cl-1", slot="32", proposer_epoch="4", validator_index="0"),
                    sample(32_000_000_000_000_000_000, instance="cl-2", slot="32", proposer_epoch="4", validator_index="0"),
                ],
                "topostake_selected_proposer": [
                    sample(1, instance="cl-1", slot="32", proposer_epoch="4", validator_index="0"),
                    sample(1, instance="cl-2", slot="32", proposer_epoch="4", validator_index="1"),
                ],
            }
        )
        by_name = {item.name: item for item in artifact_checks(summary, "topostake")}
        self.assertFalse(by_name["cross-node-proposer-consistency"].passed)


if __name__ == "__main__":
    unittest.main()
