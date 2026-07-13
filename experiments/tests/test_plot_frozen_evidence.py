from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "analysis"))

from plot_frozen_evidence import read_summary, render_table  # noqa: E402


FIELDS = [
    "protocol_version",
    "operation",
    "hops",
    "samples",
    "mean_us",
    "median_us",
    "p95_us",
    "stddev_us",
    "evidence_bytes",
    "json_bytes",
    "compressed_bytes",
    "signer_identities",
    "signature_bytes",
    "records_per_block",
    "work_units",
    "all_checks_passed",
]


def benchmark_rows() -> list[dict[str, object]]:
    rows = []
    for hops in (1, 2):
        for index, operation in enumerate(
            (
                "construct_path",
                "verify_individual",
                "aggregate_only",
                "verify_aggregate_cold",
            )
        ):
            rows.append(
                {
                    "protocol_version": "frozen-v1",
                    "operation": operation,
                    "hops": hops,
                    "samples": 10,
                    "mean_us": 100 * (index + 1) * hops,
                    "median_us": 90 * (index + 1) * hops,
                    "p95_us": 120 * (index + 1) * hops,
                    "stddev_us": 5,
                    "evidence_bytes": 192 + 42 * hops,
                    "json_bytes": 250 + 50 * hops,
                    "compressed_bytes": 180 + 20 * hops,
                    "signer_identities": hops + 1,
                    "signature_bytes": 96,
                    "records_per_block": 1,
                    "work_units": hops,
                    "all_checks_passed": True,
                }
            )
    return rows


class FrozenEvidencePlotTests(unittest.TestCase):
    def test_read_summary_filters_failed_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "summary.csv"
            rows = benchmark_rows()
            rows.append({**rows[0], "operation": "failed", "all_checks_passed": False})
            with path.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=FIELDS)
                writer.writeheader()
                writer.writerows(rows)
            self.assertEqual(len(read_summary(path)), len(rows) - 1)

    def test_latex_table_uses_milliseconds_and_evidence_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "table.tex"
            rows = [{key: str(value) for key, value in row.items()} for row in benchmark_rows()]
            render_table(rows, path)
            table = path.read_text()
            self.assertIn("1 & 0.090 & 0.180 & 0.270 & 0.360", table)
            self.assertIn("& 300", table)


if __name__ == "__main__":
    unittest.main()
