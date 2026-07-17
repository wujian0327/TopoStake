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
from matplotlib.lines import Line2D


ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "results" / "processed"
DEFAULT_CONFIG = ROOT / "experiments" / "configs" / "frozen_v1_sustained_outage_main.yaml"
DEFAULT_OUTPUT = ROOT / "figures" / "frozen_v1_sustained_outage"
BLUE = "#0072B2"
ORANGE = "#E69F00"
COLORS = {"random": BLUE, "high-score": ORANGE}
LABELS = {"random": "Random", "high-score": "High-score"}
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


def paired_run_deltas(
    rows: list[dict[str, str]], metric: str
) -> dict[tuple[str, float], list[float]]:
    variants: dict[tuple[int, str, float], dict[str, dict[str, str]]] = defaultdict(dict)
    for row in rows:
        key = (
            int(row["seed_index"]),
            row["selection"],
            number(row["target_stake_fraction"]),
        )
        variants[key][row["protocol_label"]] = row
    deltas: dict[tuple[str, float], list[float]] = defaultdict(list)
    for (_seed, selection, target), protocols in variants.items():
        if "topostake" not in protocols or "topostake_eta0" not in protocols:
            continue
        deltas[(selection, target)].append(
            100.0
            * (
                number(protocols["topostake"][metric])
                - number(protocols["topostake_eta0"][metric])
            )
        )
    return dict(deltas)


def grouped_pair_metric(
    rows: list[dict[str, str]], metric: str, scale: float = 100.0
) -> dict[tuple[str, float], list[float]]:
    grouped: dict[tuple[str, float], list[float]] = defaultdict(list)
    for row in rows:
        grouped[(row["selection"], number(row["target_stake_fraction"]))].append(
            scale * number(row[metric])
        )
    return dict(grouped)


def render_weight_response(
    runs: list[dict[str, str]], output: Path
) -> list[Path]:
    initial = paired_run_deltas(runs, "initial_group_weight")
    steady = paired_run_deltas(runs, "steady_group_weight")
    if not initial or not steady:
        raise ValueError("sustained-outage run pairs are incomplete")

    fig, axis = plt.subplots(figsize=(3.45, 2.55))
    for selection in ("random", "high-score"):
        for grouped, linestyle, marker, facecolor in (
            (initial, "--", "^", COLORS[selection]),
            (steady, "-", "o", "white"),
        ):
            points = []
            for (candidate, target), values in grouped.items():
                if candidate != selection:
                    continue
                mean, ci, count = mean_ci(values)
                if count:
                    points.append((100.0 * target, mean, ci))
            points.sort()
            axis.errorbar(
                [point[0] for point in points],
                [point[1] for point in points],
                yerr=[point[2] for point in points],
                color=COLORS[selection],
                marker=marker,
                markerfacecolor=facecolor,
                markeredgecolor=COLORS[selection],
                linestyle=linestyle,
                linewidth=1.2,
                markersize=4.5,
                capsize=2.5,
            )
    axis.axhline(0.0, color="#666666", linewidth=0.9, linestyle="--")
    axis.set_xlabel("Outage-group stake target (%)")
    axis.set_ylabel("Offline-group weight shift (pp)\n" + r"TopoStake $-$ $\eta{=}0$")
    axis.set_title("Proposer-weight response", y=1.27)
    axis.set_xticks([10, 25, 40])
    axis.set_xlim(7, 43)
    axis.set_ylim(-2.45, 3.25)
    axis.grid(axis="y", color="#E6E6E6", linewidth=0.7)
    axis.legend(
        handles=[
            Line2D([0], [0], color=BLUE, linewidth=1.4, label="Random"),
            Line2D([0], [0], color=ORANGE, linewidth=1.4, label="High-score"),
            Line2D(
                [0],
                [0],
                color="#555555",
                linestyle="--",
                marker="^",
                markersize=4.0,
                label="Onset",
            ),
            Line2D(
                [0],
                [0],
                color="#555555",
                linestyle="-",
                marker="o",
                markerfacecolor="white",
                markersize=4.0,
                label="Steady",
            ),
        ],
        frameon=False,
        loc="upper center",
        bbox_to_anchor=(0.5, 1.14),
        ncol=4,
        columnspacing=0.65,
        handlelength=1.6,
    )
    fig.subplots_adjust(bottom=0.20, left=0.22, right=0.97, top=0.72)
    return save_figure(fig, output)


def render_missed_slots(
    pairs: list[dict[str, str]], output: Path
) -> list[Path]:
    grouped = grouped_pair_metric(pairs, "miss_rate_improvement")
    if not grouped:
        raise ValueError("no sustained-outage paired rows")

    fig, axis = plt.subplots(figsize=(3.45, 2.55))
    offsets = {"random": -0.7, "high-score": 0.7}
    markers = {"random": "o", "high-score": "s"}
    for selection in ("random", "high-score"):
        points = []
        for (candidate, target), values in grouped.items():
            if candidate != selection:
                continue
            mean, ci, count = mean_ci(values)
            if count:
                points.append((100.0 * target + offsets[selection], mean, ci))
        points.sort()
        axis.errorbar(
            [point[0] for point in points],
            [point[1] for point in points],
            yerr=[point[2] for point in points],
            color=COLORS[selection],
            marker=markers[selection],
            markerfacecolor="white",
            markeredgecolor=COLORS[selection],
            linewidth=1.2,
            markersize=4.5,
            capsize=2.5,
            label=LABELS[selection],
        )
    axis.axhline(0.0, color="#666666", linewidth=0.9, linestyle="--")
    axis.set_xlabel("Outage-group stake target (%)")
    axis.set_ylabel("Miss-rate improvement (pp)\n" + r"$\eta{=}0$ $-$ TopoStake")
    axis.set_title("Missed slots under sustained outage")
    axis.set_xticks([10, 25, 40])
    axis.set_xlim(7, 43)
    axis.set_ylim(-5.0, 6.5)
    axis.grid(axis="y", color="#E6E6E6", linewidth=0.7)
    axis.legend(frameon=False, loc="upper left")
    fig.subplots_adjust(bottom=0.20, left=0.22, right=0.97, top=0.87)
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
    outputs = render_weight_response(
        read_csv(runs_path), args.output_dir / "sustained_outage_weight_response"
    )
    outputs.extend(
        render_missed_slots(
            read_csv(pairs_path), args.output_dir / "sustained_outage_missed_slots"
        )
    )
    print("Generated: " + ", ".join(str(path) for path in outputs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
