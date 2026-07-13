#!/usr/bin/env python3
"""Render frozen-v1 path-evidence microbenchmark figures and a LaTeX table."""

from __future__ import annotations

import argparse
import csv
import math
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/topostake-matplotlib")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUMMARY = ROOT / "results" / "processed" / "frozen_v1_evidence_benchmark_summary.csv"
DEFAULT_FIGURE = ROOT / "figures" / "frozen_v1_evidence_overhead"
DEFAULT_TABLE = ROOT / "results" / "processed" / "frozen_v1_evidence_benchmark_table.tex"

COLORS = {
    "construct_path": "#0072B2",
    "verify_individual": "#D55E00",
    "aggregate_only": "#009E73",
    "verify_aggregate_cold": "#CC79A7",
}
LABELS = {
    "construct_path": "Construct path",
    "verify_individual": "Verify individual proofs",
    "aggregate_only": "Aggregate signatures",
    "verify_aggregate_cold": "Verify aggregate (cold)",
}
MARKERS = {
    "construct_path": "o",
    "verify_individual": "s",
    "aggregate_only": "^",
    "verify_aggregate_cold": "D",
}


def read_summary(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise SystemExit(f"Evidence benchmark summary not found: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    valid = [
        row
        for row in rows
        if row.get("protocol_version") == "frozen-v1"
        and row.get("all_checks_passed", "").lower() == "true"
    ]
    if not valid:
        raise SystemExit(f"No passing frozen-v1 benchmark rows in {path}")
    return valid


def numeric(row: dict[str, str], field: str) -> float:
    try:
        value = float(row[field])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"invalid {field!r} in benchmark row: {row}") from error
    if not math.isfinite(value):
        raise ValueError(f"non-finite {field!r} in benchmark row: {row}")
    return value


def operation_rows(rows: list[dict[str, str]], operation: str) -> list[dict[str, str]]:
    return sorted(
        (row for row in rows if row.get("operation") == operation),
        key=lambda row: numeric(row, "hops"),
    )


def configure_style() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 8.5,
            "axes.labelsize": 8.5,
            "axes.titlesize": 9.0,
            "legend.fontsize": 7.5,
            "xtick.labelsize": 7.5,
            "ytick.labelsize": 7.5,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "savefig.bbox": "tight",
        }
    )


def render_figure(rows: list[dict[str, str]], stem: Path) -> list[Path]:
    configure_style()
    for suffix in ("pdf", "png"):
        legacy = stem.with_suffix(f".{suffix}")
        if legacy.exists():
            legacy.unlink()
    outputs = []
    fig, timing = plt.subplots(figsize=(3.45, 2.55))
    for operation in LABELS:
        selected = operation_rows(rows, operation)
        if not selected:
            continue
        timing.plot(
            [numeric(row, "hops") for row in selected],
            [numeric(row, "median_us") / 1_000.0 for row in selected],
            color=COLORS[operation],
            marker=MARKERS[operation],
            linewidth=1.25,
            markersize=4,
            label=LABELS[operation],
        )
    timing.set_xlabel("Path length (hops)")
    timing.set_ylabel("Median runtime (ms)")
    timing.set_title("Cold-path cryptographic cost")
    timing.set_xticks([1, 2, 4, 8, 16])
    timing.set_yscale("log")
    timing.grid(axis="y", color="#E6E6E6", linewidth=0.7)
    timing.legend(frameon=False, loc="best")
    fig.subplots_adjust(bottom=0.20, left=0.19, right=0.97, top=0.88)
    for suffix in ("pdf", "png"):
        output = stem.with_name(f"{stem.name}_a").with_suffix(f".{suffix}")
        output.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output, dpi=300, facecolor="white")
        outputs.append(output)
    plt.close(fig)

    fig, sizes = plt.subplots(figsize=(3.45, 2.55))
    base = operation_rows(rows, "verify_aggregate_cold")
    for field, label, color, marker in [
        ("evidence_bytes", "Path fields (hex/text)", "#0072B2", "o"),
        ("json_bytes", "JSON encoding", "#D55E00", "s"),
        ("compressed_bytes", "Compressed JSON", "#009E73", "^"),
    ]:
        sizes.plot(
            [numeric(row, "hops") for row in base],
            [numeric(row, field) for row in base],
            color=color,
            marker=marker,
            linewidth=1.25,
            markersize=4,
            label=label,
        )
    sizes.set_xlabel("Path length (hops)")
    sizes.set_ylabel("Encoded evidence (bytes)")
    sizes.set_title("Simulator evidence encoding")
    sizes.set_xticks([1, 2, 4, 8, 16])
    sizes.grid(axis="y", color="#E6E6E6", linewidth=0.7)
    sizes.legend(frameon=False, loc="best")
    fig.subplots_adjust(bottom=0.20, left=0.19, right=0.97, top=0.88)
    for suffix in ("pdf", "png"):
        output = stem.with_name(f"{stem.name}_b").with_suffix(f".{suffix}")
        output.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output, dpi=300, facecolor="white")
        outputs.append(output)
    plt.close(fig)
    return outputs


def render_table(rows: list[dict[str, str]], path: Path) -> None:
    indexed = {
        (row["operation"], int(numeric(row, "hops"))): row
        for row in rows
    }
    hops = sorted(
        int(numeric(row, "hops"))
        for row in operation_rows(rows, "verify_aggregate_cold")
    )
    lines = [
        r"\begin{tabular}{r|rrrr|r}",
        r"\hline",
        r"Hops & Construct & Individual verify & Aggregate & Aggregate verify & JSON bytes \\",
        r"\hline",
    ]
    for hop in hops:
        values = [
            numeric(indexed[(operation, hop)], "median_us") / 1_000.0
            for operation in (
                "construct_path",
                "verify_individual",
                "aggregate_only",
                "verify_aggregate_cold",
            )
        ]
        evidence_bytes = int(numeric(indexed[("verify_aggregate_cold", hop)], "json_bytes"))
        lines.append(
            f"{hop} & "
            + " & ".join(f"{value:.3f}" for value in values)
            + f" & {evidence_bytes} \\\\"
        )
    lines.extend([r"\hline", r"\end{tabular}"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--figure", type=Path, default=DEFAULT_FIGURE)
    parser.add_argument("--table", type=Path, default=DEFAULT_TABLE)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rows = read_summary(args.summary)
    figures = render_figure(rows, args.figure)
    render_table(rows, args.table)
    print(
        "Generated frozen-v1 evidence artifacts: "
        + ", ".join(str(path) for path in [*figures, args.table])
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
