from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "analysis"))

from plot_frozen_devnet import (  # noqa: E402
    EXPECTED_VARIANTS,
    paired_summaries,
    read_runs,
    render_figures,
    render_table,
    verification_summaries,
)


def devnet_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for variant in EXPECTED_VARIANTS:
        for load in (8, 32, 64):
            for seed in range(5):
                baseline_tps = load / 3.0 * 0.98
                evidence = variant != "baseline"
                rows.append(
                    {
                        "suite": "frozen_v1_devnet_main",
                        "run_id": f"{variant}-{load}-{seed}",
                        "variant": variant,
                        "load_tx_per_slot": load,
                        "seed": seed,
                        "status": "ok",
                        "acceptance_passed": True,
                        "measurement_quality_passed": True,
                        "error": "",
                        "inclusion_throughput_tps": baseline_tps
                        * (0.99 if evidence else 1.0),
                        "p95_inclusion_delay_seconds": 5.0 if evidence else 4.0,
                        "cpu_mean_percent": 80.0 if evidence else 50.0,
                        "memory_max_bytes": (1_100 if evidence else 1_000) * 1024 * 1024,
                        "network_rx_delta_bytes": (120 if evidence else 100) * 1024 * 1024,
                        "network_tx_delta_bytes": (150 if evidence else 100) * 1024 * 1024,
                        "block_ssz_mean_bytes": 1_000 + (load * 10 if evidence else 0),
                        "block_ssz_count": 40,
                        "success_count": load * 10,
                        "evidence_verify_mean_seconds": load / 10_000 if evidence else 0.0,
                        "evidence_verify_p95_seconds": load / 5_000 if evidence else 0.0,
                    }
                )
    return rows


class FrozenDevnetPlotTests(unittest.TestCase):
    def write_rows(self, path: Path, rows: list[dict[str, object]]) -> None:
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    def test_formal_matrix_is_validated_and_paired_by_seed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "devnet.csv"
            self.write_rows(path, devnet_rows())
            rows = read_runs(path)
            summaries = paired_summaries(rows)
            throughput = next(
                row
                for row in summaries
                if row["comparison"] == "topostake-vs-baseline"
                and row["load_tx_per_slot"] == 8
                and row["metric"] == "throughput_change_percent"
            )
            block_bytes = next(
                row
                for row in summaries
                if row["comparison"] == "topostake-vs-baseline"
                and row["load_tx_per_slot"] == 8
                and row["metric"] == "additional_block_bytes_per_tx"
            )
            self.assertEqual(throughput["n"], 5)
            self.assertAlmostEqual(float(throughput["mean"]), -1.0)
            self.assertAlmostEqual(float(throughput["ci95"]), 0.0)
            self.assertAlmostEqual(float(block_bytes["mean"]), 40.0)

    def test_duplicate_run_key_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "devnet.csv"
            rows = devnet_rows()
            rows.append(dict(rows[0]))
            self.write_rows(path, rows)
            with self.assertRaises(SystemExit):
                read_runs(path)

    def test_each_panel_is_a_separate_file_and_table_is_generated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "devnet.csv"
            self.write_rows(path, devnet_rows())
            rows = read_runs(path)
            summaries = [*paired_summaries(rows), *verification_summaries(rows)]
            outputs = render_figures(summaries, root / "figures")
            self.assertEqual(len(outputs), 14)
            self.assertTrue(all(path.suffix in {".pdf", ".png"} for path in outputs))
            self.assertEqual(len({path.stem for path in outputs}), 7)
            table = root / "table.tex"
            render_table(summaries, table)
            contents = table.read_text()
            self.assertIn("8 & -1.00 & +1.00", contents)
            self.assertIn("& 1.6", contents)


if __name__ == "__main__":
    unittest.main()
