import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "experiments"))

from organic_capture_report import PAIR_METRICS  # noqa: E402
from topology_scale_report import (  # noqa: E402
    graph_profile,
    group_rows,
    paired_rows,
)


class TopologyScaleReportTests(unittest.TestCase):
    def test_pairs_do_not_mix_node_count_or_topology(self) -> None:
        runs = []
        for node_num in (100, 1000):
            for topology in ("ba", "eth_empirical"):
                common = {
                    "complete": True,
                    "node_num": node_num,
                    "topology": topology,
                    "seed_index": 0,
                    "adversary_stake_fraction": 0.3,
                    "adversary_placement": "high-degree",
                }
                baseline = {**common, "attack_mode": "none"}
                stress = {**common, "attack_mode": "max-score"}
                for metric in PAIR_METRICS:
                    baseline[metric] = node_num / 10_000.0
                    stress[metric] = node_num / 10_000.0 + 0.05
                baseline["score_dependent_proposer_weight_bound"] = 0.4
                baseline["theoretical_proposer_weight_bound"] = 0.5
                stress["score_dependent_proposer_weight_bound"] = 0.4
                stress["theoretical_proposer_weight_bound"] = 0.5
                runs.extend((baseline, stress))

        pairs = paired_rows(runs)
        self.assertEqual(len(pairs), 4 * len(PAIR_METRICS))
        self.assertEqual(
            {(row["node_num"], row["topology"]) for row in pairs},
            {
                (100, "ba"),
                (100, "eth_empirical"),
                (1000, "ba"),
                (1000, "eth_empirical"),
            },
        )
        self.assertTrue(all(abs(row["difference"] - 0.05) < 1e-12 for row in pairs))
        groups = group_rows(runs, pairs)
        self.assertTrue(
            any(
                row["node_num"] == 1000
                and row["topology"] == "eth_empirical"
                for row in groups
            )
        )

    def test_graph_profile_checks_connectivity_and_degree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "graph.json"
            path.write_text(
                json.dumps([["a", "b"], ["b", "c"], ["c", "d"]]),
                encoding="utf-8",
            )
            profile = graph_profile(path, 4)
        self.assertTrue(profile["connected"])
        self.assertEqual(profile["edge_count"], 3)
        self.assertEqual(profile["average_degree"], 1.5)
        self.assertEqual(profile["max_degree"], 2)


if __name__ == "__main__":
    unittest.main()
