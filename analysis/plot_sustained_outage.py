#!/usr/bin/env python3
"""Render separate paper figures for the paired sustained-outage evaluation."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

os.environ.setdefault("MPLCONFIGDIR", "/tmp/topostake-matplotlib")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "results" / "processed"
DEFAULT_CONFIG = ROOT / "experiments" / "configs" / "frozen_v1_sustained_outage_main.yaml"
DEFAULT_OUTPUT = ROOT / "figures" / "frozen_v1_sustained_outage"
BLUE = "#0072B2"
ORANGE = "#E69F00"
GRAY = "#666666"
T95 = {
    2: 12.706,
    3: 4.303,
    4: 3.182,
    5: 2.776,
    6: 2.571,
    7: 2.447,
    8: 2.365,
    9: 2.306,
    10: 2.262,
    11: 2.228,
    12: 2.201,
    13: 2.179,
    14: 2.160,
    15: 2.145,
    16: 2.131,
    17: 2.120,
    18: 2.110,
    19: 2.101,
    20: 2.093,
    21: 2.086,
    22: 2.080,
    23: 2.074,
    24: 2.069,
    25: 2.064,
    26: 2.060,
    27: 2.056,
    28: 2.052,
    29: 2.048,
    30: 2.045,
}


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


def mean_ci(values: Iterable[float]) -> tuple[float, float, int]:
    materialized = list(values)
    if not materialized:
        return math.nan, 0.0, 0
    if len(materialized) == 1:
        return materialized[0], 0.0, 1
    count = len(materialized)
    return (
        statistics.fmean(materialized),
        T95.get(count, 1.96)
        * statistics.stdev(materialized)
        / math.sqrt(count),
        count,
    )


def configure_style() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 8.5,
            "axes.labelsize": 8.5,
            "axes.titlesize": 9.0,
            "legend.fontsize": 6.8,
            "xtick.labelsize": 7.5,
            "ytick.labelsize": 7.5,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            # Independently rendered panels align when LaTeX assembles them.
            "savefig.bbox": None,
        }
    )


def save_figure(fig: Any, output: Path) -> list[Path]:
    output.parent.mkdir(parents=True, exist_ok=True)
    outputs = []
    for suffix in ("pdf", "png"):
        path = output.with_suffix(f".{suffix}")
        fig.savefig(path, dpi=300, facecolor="white")
        outputs.append(path)
    plt.close(fig)
    return outputs


def grouped_run_metric(
    rows: list[dict[str, str]],
    metric: str,
    selection: str,
    protocol_label: str,
    scale: float = 100.0,
) -> dict[float, list[float]]:
    grouped: dict[float, list[float]] = defaultdict(list)
    for row in rows:
        if row["selection"] != selection or row["protocol_label"] != protocol_label:
            continue
        grouped[number(row["target_stake_fraction"])].append(
            scale * number(row[metric])
        )
    return dict(grouped)


def grouped_pair_metric(
    rows: list[dict[str, str]],
    metric: str,
    selection: str,
    scale: float = 100.0,
) -> dict[float, list[float]]:
    grouped: dict[float, list[float]] = defaultdict(list)
    for row in rows:
        if row["selection"] == selection:
            grouped[number(row["target_stake_fraction"])].append(
                scale * number(row[metric])
            )
    return dict(grouped)


def series_points(
    grouped: dict[float, list[float]],
) -> list[tuple[float, float, float]]:
    points = []
    for target, values in grouped.items():
        mean, ci, count = mean_ci(values)
        if count:
            points.append((100.0 * target, mean, ci))
    return sorted(points)


def render_weight_share(
    runs: list[dict[str, str]], selection: str, output: Path
) -> list[Path]:
    fee_only = grouped_run_metric(
        runs, "steady_group_weight", selection, "topostake_eta0"
    )
    full_onset = grouped_run_metric(
        runs, "initial_group_weight", selection, "topostake"
    )
    full_steady = grouped_run_metric(
        runs, "steady_group_weight", selection, "topostake"
    )
    if not fee_only or not full_onset or not full_steady:
        raise ValueError("sustained-outage run pairs are incomplete")

    fig, axis = plt.subplots(figsize=(3.45, 2.55))
    for grouped, color, linestyle, marker, label in (
        (fee_only, GRAY, "--", "s", r"Fee-only ($\eta{=}0$)"),
        (full_onset, ORANGE, "--", "^", r"Full onset ($\eta{=}0.5$)"),
        (full_steady, BLUE, "-", "o", r"Full steady ($\eta{=}0.5$)"),
    ):
        points = series_points(grouped)
        axis.errorbar(
            [point[0] for point in points],
            [point[1] for point in points],
            yerr=[point[2] for point in points],
            color=color,
            marker=marker,
            markerfacecolor="white",
            markeredgecolor=color,
            linestyle=linestyle,
            linewidth=1.2,
            markersize=4.5,
            capsize=2.5,
            label=label,
        )
    axis.set_xlabel("Outage-group stake target (%)")
    axis.set_ylabel("Offline-group proposer share (%)")
    axis.set_xticks([10, 25, 40])
    axis.set_xlim(7, 43)
    axis.set_ylim(5, 45)
    axis.grid(axis="y", color="#E6E6E6", linewidth=0.7)
    axis.legend(
        frameon=False,
        loc="upper center",
        bbox_to_anchor=(0.5, 1.20),
        ncol=2,
        columnspacing=0.7,
        handlelength=1.4,
    )
    fig.subplots_adjust(bottom=0.20, left=0.22, right=0.97, top=0.78)
    return save_figure(fig, output)


def render_missed_slot_rate(
    pairs: list[dict[str, str]], selection: str, output: Path
) -> list[Path]:
    fee_only = grouped_pair_metric(pairs, "eta0_miss_rate", selection)
    full = grouped_pair_metric(pairs, "full_miss_rate", selection)
    reduction = grouped_pair_metric(pairs, "miss_rate_improvement", selection)
    if not fee_only or not full or not reduction:
        raise ValueError("no sustained-outage paired rows")

    fig, axis = plt.subplots(figsize=(3.45, 2.55))
    plotted: dict[str, list[tuple[float, float, float]]] = {}
    for name, grouped, offset, color, linestyle, marker, label in (
        ("fee_only", fee_only, -0.45, GRAY, "--", "s", r"Fee-only ($\eta{=}0$)"),
        ("full", full, 0.45, BLUE, "-", "o", r"Full TopoStake ($\eta{=}0.5$)"),
    ):
        points = series_points(grouped)
        plotted[name] = points
        axis.errorbar(
            [point[0] + offset for point in points],
            [point[1] for point in points],
            yerr=[point[2] for point in points],
            color=color,
            marker=marker,
            markerfacecolor="white",
            markeredgecolor=color,
            linestyle=linestyle,
            linewidth=1.2,
            markersize=4.5,
            capsize=2.5,
            label=label,
        )
    fee_by_target = {point[0]: point for point in plotted["fee_only"]}
    full_by_target = {point[0]: point for point in plotted["full"]}
    for target, values in sorted(reduction.items()):
        x = 100.0 * target
        reduction_mean, _ci, count = mean_ci(values)
        if not count or x not in fee_by_target or x not in full_by_target:
            continue
        fee_point = fee_by_target[x]
        full_point = full_by_target[x]
        label = (
            f"{reduction_mean:.1f} pp lower"
            if reduction_mean >= 0
            else f"{-reduction_mean:.1f} pp higher"
        )
        y = max(fee_point[1] + fee_point[2], full_point[1] + full_point[2]) + 1.0
        axis.text(x, y, label, fontsize=6.5, color="#333333", ha="center", va="bottom")
    axis.set_xlabel("Outage-group stake target (%)")
    axis.set_ylabel("Missed-slot rate during outage (%)")
    axis.set_xticks([10, 25, 40])
    axis.set_xlim(7, 43)
    axis.set_ylim(0, 48)
    axis.grid(axis="y", color="#E6E6E6", linewidth=0.7)
    axis.legend(
        frameon=False,
        loc="upper center",
        bbox_to_anchor=(0.5, 1.20),
        ncol=2,
        columnspacing=0.8,
        handlelength=1.4,
    )
    fig.subplots_adjust(bottom=0.20, left=0.22, right=0.97, top=0.78)
    return save_figure(fig, output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--runs", type=Path)
    parser.add_argument("--pairs", type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    spec = load_yaml(args.config.resolve())
    processed = PROCESSED / str(spec["suite"])
    runs_path = args.runs or processed / "sustained_outage_runs.csv"
    pairs_path = args.pairs or processed / "sustained_outage_paired.csv"
    configure_style()
    runs = read_csv(runs_path)
    pairs = read_csv(pairs_path)
    outputs = []
    for selection, suffix in (("random", "random"), ("high-score", "high_score")):
        outputs.extend(
            render_weight_share(
                runs,
                selection,
                args.output_dir / f"sustained_outage_weight_{suffix}",
            )
        )
        outputs.extend(
            render_missed_slot_rate(
                pairs,
                selection,
                args.output_dir / f"sustained_outage_missed_slots_{suffix}",
            )
        )
    print("Generated: " + ", ".join(str(path) for path in outputs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
