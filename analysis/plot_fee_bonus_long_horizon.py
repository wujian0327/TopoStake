#!/usr/bin/env python3
"""Render long-horizon Full TopoStake versus fee-only simulator figures."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
from pathlib import Path
from typing import Any

os.environ.setdefault("MPLCONFIGDIR", "/tmp/topostake-matplotlib")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "results" / "processed"
DEFAULT_CONFIG = ROOT / "experiments" / "configs" / "frozen_v1_fee_bonus_pilot.yaml"
DEFAULT_OUTPUT = ROOT / "figures" / "frozen_v1_fee_bonus"
COLORS = {"topostake_eta0": "#E69F00", "topostake": "#0072B2"}
MARKERS = {"topostake_eta0": "s", "topostake": "o"}
LABELS = {"topostake_eta0": r"Fee-only ($\eta=0$)", "topostake": "Full TopoStake"}


def load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml  # type: ignore

        return yaml.safe_load(path.read_text())
    except ModuleNotFoundError:
        return json.loads(path.read_text())


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def number(value: Any) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"non-finite plotting value: {value!r}")
    return result


def interval_errors(row: dict[str, str]) -> tuple[float, float]:
    mean = number(row["mean"])
    if row.get("ci95_low") not in {None, ""} and row.get("ci95_high") not in {
        None,
        "",
    }:
        return (
            max(0.0, mean - number(row["ci95_low"])),
            max(0.0, number(row["ci95_high"]) - mean),
        )
    ci = number(row["ci95"])
    return ci, ci


def configure_style() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 8.5,
            "axes.labelsize": 8.5,
            "axes.titlesize": 9.0,
            "legend.fontsize": 7.0,
            "xtick.labelsize": 7.5,
            "ytick.labelsize": 7.5,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "savefig.bbox": None,
        }
    )


def render_metric(
    rows: list[dict[str, str]],
    metric: str,
    ylabel: str,
    _title: str,
    output: Path,
    minimum_lazy_fraction: float = 0.0,
    series_order: tuple[str, ...] = ("topostake_eta0", "topostake"),
    show_legend: bool = True,
) -> None:
    selected = [
        row
        for row in rows
        if row.get("metric") == metric and row.get("series") in series_order
        and number(row["lazy_fraction"]) >= minimum_lazy_fraction
    ]
    if not selected:
        raise ValueError(f"no grouped rows for {metric}")
    fig, axis = plt.subplots(figsize=(3.45, 2.55))
    for series in series_order:
        points = sorted(
            (
                number(row["lazy_fraction"]),
                number(row["mean"]),
                *interval_errors(row),
            )
            for row in selected
            if row["series"] == series
        )
        axis.errorbar(
            [100.0 * point[0] for point in points],
            [point[1] for point in points],
            yerr=(
                [point[2] for point in points],
                [point[3] for point in points],
            ),
            color=COLORS[series],
            marker=MARKERS[series],
            linewidth=1.2,
            markersize=4.5,
            capsize=2.5,
            label=LABELS[series],
        )
    axis.set_xlabel("Lazy relayers (%)")
    axis.set_ylabel(ylabel)
    axis.set_xticks([0, 25, 50, 75])
    axis.grid(axis="y", color="#E6E6E6", linewidth=0.7)
    if show_legend:
        axis.legend(frameon=False, loc="best")
    fig.subplots_adjust(bottom=0.18, left=0.20, right=0.97, top=0.97)
    output.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("pdf", "png"):
        fig.savefig(output.with_suffix(f".{suffix}"), dpi=300, facecolor="white")
    plt.close(fig)


def render_paired_difference(
    rows: list[dict[str, str]],
    metric: str,
    ylabel: str,
    _title: str,
    output: Path,
) -> None:
    points = sorted(
        (
            number(row["lazy_fraction"]),
            number(row["mean"]),
            *interval_errors(row),
        )
        for row in rows
        if row.get("metric") == metric
        and row.get("series") == "full-minus-fee-only"
        and number(row["lazy_fraction"]) > 0.0
    )
    if not points:
        raise ValueError(f"no paired rows for {metric}")
    fig, axis = plt.subplots(figsize=(3.45, 2.55))
    axis.errorbar(
        [100.0 * point[0] for point in points],
        [point[1] for point in points],
        yerr=(
            [point[2] for point in points],
            [point[3] for point in points],
        ),
        color="#009E73",
        marker="D",
        linewidth=1.2,
        markersize=4.5,
        capsize=2.5,
    )
    axis.axhline(0.0, color="#666666", linewidth=0.9, linestyle="--")
    axis.set_xlabel("Lazy relayers (%)")
    axis.set_ylabel(ylabel)
    axis.set_xticks([25, 50, 75])
    axis.grid(axis="y", color="#E6E6E6", linewidth=0.7)
    fig.subplots_adjust(bottom=0.18, left=0.20, right=0.97, top=0.97)
    output.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("pdf", "png"):
        fig.savefig(output.with_suffix(f".{suffix}"), dpi=300, facecolor="white")
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--groups", type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    config = load_yaml(args.config.resolve())
    suite = str(config.get("suite", args.config.stem))
    groups_path = args.groups or PROCESSED / f"{suite}_groups.csv"
    rows = read_csv(groups_path)
    configure_style()
    specifications = [
        (
            "p95_inclusion_latency_s_pooled",
            "p95 latency (s)",
            "fee_bonus_long_horizon_a",
        ),
        (
            "credit_eligible_rate",
            "Eligible-path rate",
            "fee_bonus_long_horizon_b",
        ),
        (
            "relay_reward_per_stake_gini",
            "Reward/stake Gini",
            "fee_bonus_long_horizon_c",
        ),
        (
            "top_degree_quartile_relay_reward_share",
            "Top-degree reward share",
            "fee_bonus_long_horizon_d",
        ),
        (
            "participation_break_even_cost_per_forward",
            "Reward / extra forward",
            "fee_bonus_long_horizon_e",
            0.01,
        ),
        (
            "forward_attempts_per_included_tx",
            "Forwards / included tx",
            "fee_bonus_long_horizon_f",
            0.0,
        ),
        (
            "participation_reward_premium_per_stake",
            "Reward/stake premium",
            "fee_bonus_long_horizon_g",
            0.01,
        ),
        (
            "participation_weight_multiplier_premium",
            "Weight/stake premium",
            "fee_bonus_long_horizon_i",
            0.01,
        ),
    ]
    normalized_specs = [
        (*specification, 0.0) if len(specification) == 3 else specification
        for specification in specifications
    ]
    for metric, ylabel, stem, minimum_lazy_fraction in normalized_specs:
        latency_panel = metric == "p95_inclusion_latency_s_pooled"
        render_metric(
            rows,
            metric,
            ylabel,
            "",
            args.output_dir / stem,
            minimum_lazy_fraction,
            series_order=("topostake",)
            if latency_panel
            else ("topostake_eta0", "topostake"),
        )
    render_paired_difference(
        rows,
        "participation_reward_premium_per_stake",
        "Full-minus-fee-only premium",
        "",
        args.output_dir / "fee_bonus_long_horizon_h",
    )
    print(f"generated {(len(specifications) + 1) * 2} files from {groups_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
