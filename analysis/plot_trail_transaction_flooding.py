#!/usr/bin/env python3
"""Plot run-level flooding fee-recovery and contribution-cost ratios."""

from __future__ import annotations

import argparse
import csv
import math
import os
import statistics
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/trail-matplotlib")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.stats import t as student_t


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "results" / "processed" / "trail_transaction_flooding_runs.csv"
DEFAULT_OUTPUT = ROOT / "figures" / "trail_security"
EXPECTED_MULTIPLIERS = (0.5, 1.0, 2.0, 5.0)
EXPECTED_SEEDS = set(range(20))
G_REF = 1e-5

BLUE = "#0072B2"
ORANGE = "#D55E00"
LIGHT_GRAY = "#B8B8B8"


@dataclass(frozen=True)
class RunRatio:
    multiplier: float
    seed: int
    fee_recovery: float
    contribution_cost: float


@dataclass(frozen=True)
class Point:
    multiplier: float
    mean: float
    ci95: float
    n: int


def truthy(value: str | None) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def load_runs(path: Path) -> list[RunRatio]:
    runs: list[RunRatio] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            multiplier = float(row["multiplier"])
            if multiplier == 0.0:
                continue
            if multiplier not in EXPECTED_MULTIPLIERS:
                raise ValueError(f"unexpected multiplier {multiplier}")
            if not truthy(row["valid"]):
                raise ValueError(f"invalid run in selected data: {row['run_id']}")
            fee_paid = float(row["attack_fee_paid"])
            cost_paid = float(row["attack_irrecoverable_cost_paid"])
            if fee_paid <= 0.0 or cost_paid <= 0.0:
                raise ValueError(f"non-positive ratio denominator: {row['run_id']}")
            fee_recovery = (
                float(row["attack_proposer_fee_recovery"])
                + float(row["attack_relay_fee_recovery"])
            ) / fee_paid
            contribution_cost = (
                G_REF * float(row["attack_coalition_raw_contribution"]) / cost_paid
            )
            if not all(math.isfinite(value) for value in (fee_recovery, contribution_cost)):
                raise ValueError(f"non-finite ratio: {row['run_id']}")
            runs.append(
                RunRatio(
                    multiplier=multiplier,
                    seed=int(row["seed"]),
                    fee_recovery=fee_recovery,
                    contribution_cost=contribution_cost,
                )
            )

    if len(runs) != len(EXPECTED_MULTIPLIERS) * len(EXPECTED_SEEDS):
        raise ValueError(f"expected 80 nonzero-multiplier runs; found {len(runs)}")
    keys = [(run.multiplier, run.seed) for run in runs]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate (multiplier, seed) conditions")
    for multiplier in EXPECTED_MULTIPLIERS:
        seeds = {run.seed for run in runs if run.multiplier == multiplier}
        if seeds != EXPECTED_SEEDS:
            raise ValueError(
                f"seed mismatch for multiplier {multiplier}: found {sorted(seeds)}"
            )
    return runs


def summarize(runs: list[RunRatio], field: str) -> list[Point]:
    grouped: dict[float, list[float]] = defaultdict(list)
    for run in runs:
        grouped[run.multiplier].append(100.0 * float(getattr(run, field)))
    points: list[Point] = []
    for multiplier in EXPECTED_MULTIPLIERS:
        values = grouped[multiplier]
        if len(values) != 20:
            raise ValueError(f"expected 20 values for multiplier {multiplier}")
        critical = float(student_t.ppf(0.975, df=len(values) - 1))
        points.append(
            Point(
                multiplier=multiplier,
                mean=statistics.mean(values),
                ci95=critical * statistics.stdev(values) / math.sqrt(len(values)),
                n=len(values),
            )
        )
    return points


def configure_style() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 8.5,
            "axes.labelsize": 9.5,
            "legend.fontsize": 7.0,
            "xtick.labelsize": 7.5,
            "ytick.labelsize": 7.5,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": False,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "savefig.bbox": None,
        }
    )


def render(
    fee_points: list[Point], contribution_points: list[Point], output_dir: Path
) -> tuple[Path, Path]:
    configure_style()
    fig, ax = plt.subplots(figsize=(3.45, 2.55))
    ax.grid(axis="y", color="#E6E6E6", linewidth=0.7, zorder=0)
    ax.axvline(
        100.0,
        color=LIGHT_GRAY,
        linestyle="--",
        linewidth=1.0,
        zorder=1,
    )
    ax.text(
        100.0,
        0.965,
        "Background traffic",
        transform=ax.get_xaxis_transform(),
        color="#888888",
        fontsize=7.0,
        ha="left",
        va="top",
        zorder=2,
    )

    for points, color, marker, label in (
        (fee_points, BLUE, "o", "Fee recovery"),
        (contribution_points, ORANGE, "s", "Contribution / cost"),
    ):
        ax.errorbar(
            [100.0 * point.multiplier for point in points],
            [point.mean for point in points],
            yerr=[point.ci95 for point in points],
            color=color,
            marker=marker,
            markerfacecolor="white",
            markeredgewidth=1.1,
            linewidth=1.2,
            markersize=4.8,
            capsize=2.5,
            label=label,
            zorder=3,
        )

    traffic_rates = [100.0 * multiplier for multiplier in EXPECTED_MULTIPLIERS]
    ax.set_xticks(traffic_rates, ["50", "100", "200", "500"])
    ax.set_xlabel("Self-generated traffic (tx/s)")
    ax.set_ylabel("Ratio to paid amount (%)")
    ax.set_ylim(bottom=0.0)
    ax.margins(x=0.05)
    ax.spines["left"].set_linewidth(0.9)
    ax.spines["bottom"].set_linewidth(0.9)
    ax.tick_params(width=0.8, length=3)
    ax.legend(
        frameon=True,
        framealpha=0.9,
        facecolor="white",
        edgecolor="#D0D0D0",
        loc="upper right",
        borderpad=0.35,
        handletextpad=0.5,
        fontsize=7.0,
    )
    fig.subplots_adjust(bottom=0.18, left=0.17, right=0.97, top=0.97)

    output_dir.mkdir(parents=True, exist_ok=True)
    pdf = output_dir / "trail_transaction_flooding.pdf"
    png = output_dir / "trail_transaction_flooding.png"
    fig.savefig(pdf)
    fig.savefig(png, dpi=300)
    plt.close(fig)
    return pdf, png


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    runs = load_runs(args.input)
    fee_points = summarize(runs, "fee_recovery")
    contribution_points = summarize(runs, "contribution_cost")
    pdf, png = render(fee_points, contribution_points, args.output_dir)

    print(f"selected nonzero-multiplier runs: {len(runs)}")
    for label, points in (
        ("fee_recovery", fee_points),
        ("contribution_cost", contribution_points),
    ):
        for point in points:
            print(
                f"{label:18s} multiplier={point.multiplier:g} "
                f"mean={point.mean:.9f}% ci95={point.ci95:.9f}% n={point.n}"
            )
    print(f"pdf: {pdf}")
    print(f"png: {png}")


if __name__ == "__main__":
    main()
