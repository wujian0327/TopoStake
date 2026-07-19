#!/usr/bin/env python3
"""Add per-node resource metrics to an existing frozen-v1 devnet CSV."""

from __future__ import annotations

import argparse
import csv
import os
import tempfile
from pathlib import Path
from typing import Any

from run_frozen_devnet_experiments import summarize_resources


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "results" / "processed" / "frozen_v1_devnet_main.csv"
DEFAULT_RAW_ROOT = ROOT / "results" / "raw" / "frozen_v1_devnet_main"

PER_NODE_FIELDS = (
    "node_count",
    "per_node_cpu_mean_percent",
    "per_node_memory_peak_mean_bytes",
    "per_node_network_rx_delta_mean_bytes",
    "per_node_network_tx_delta_mean_bytes",
)


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise SystemExit(f"missing processed devnet CSV: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise SystemExit(f"empty processed devnet CSV: {path}")
    return rows


def enrich_rows(
    rows: list[dict[str, str]], raw_root: Path
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    missing: list[Path] = []
    for original in rows:
        row: dict[str, Any] = dict(original)
        if str(row.get("status", "")) != "ok":
            enriched.append(row)
            continue
        resource_path = raw_root / str(row.get("run_id", "")) / "resources.jsonl"
        if not resource_path.exists():
            missing.append(resource_path)
            enriched.append(row)
            continue
        summary = summarize_resources(resource_path)
        if int(summary.get("node_count", 0)) <= 0:
            raise SystemExit(f"no complete EL+CL node samples in {resource_path}")
        for field in PER_NODE_FIELDS:
            row[field] = summary[field]
        enriched.append(row)
    if missing:
        preview = "\n".join(str(path) for path in missing[:5])
        suffix = "" if len(missing) <= 5 else f"\n... and {len(missing) - 5} more"
        raise SystemExit(
            f"missing resources.jsonl for {len(missing)} completed runs:\n{preview}{suffix}"
        )
    return enriched


def write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = sorted({field for row in rows for field in row})
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        Path(temporary).replace(path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    parser.add_argument(
        "--output",
        type=Path,
        help="Output CSV; defaults to replacing --input atomically.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = args.output or args.input
    rows = enrich_rows(read_rows(args.input), args.raw_root)
    write_rows(output, rows)
    print(f"Wrote per-node resource metrics for {len(rows)} runs to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
