#!/usr/bin/env python3
"""Render frozen-v1 organic-traffic path-capture stress figures."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
from pathlib import Path
from typing import Any, Callable

os.environ.setdefault("MPLCONFIGDIR", "/tmp/topostake-matplotlib")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D


ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "results" / "processed"
DEFAULT_CONFIG = ROOT / "experiments" / "configs" / "frozen_v1_organic_capture_pilot.yaml"
DEFAULT_OUTPUT = ROOT / "figures" / "frozen_v1_organic_capture"
MODES = ("none", "max-score")
PLACEMENTS = ("random", "high-degree")
COLORS = {"none": "#777777", "max-score": "#D55E00"}
MARKERS = {"random": "o", "high-degree": "s"}
LINESTYLES = {"random": "-", "high-degree": "--"}
GAIN_COLORS = {
    "adversary_score_share": "#D55E00",
    "adversary_proposer_weight_share": "#0072B2",
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


def interval_errors(row: dict[str, str]) -> tuple[float, float]:
    mean = number(row["mean"])
    return (
        max(0.0, mean - number(row["ci95_low"])),
        max(0.0, number(row["ci95_high"]) - mean),
    )


def configure_style() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 8.5,
            "axes.labelsize": 8.5,
            "axes.titlesize": 9.0,
            "legend.fontsize": 6.5,
            "xtick.labelsize": 7.5,
            "ytick.labelsize": 7.5,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "savefig.bbox": None,
        }
    )


def save_figure(fig: Any, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("pdf", "svg", "png"):
        fig.savefig(output.with_suffix(f".{suffix}"), dpi=300, facecolor="white")


def render_metric(
    rows: list[dict[str, str]],
    metric: str,
    ylabel: str,
    _title: str,
    output: Path,
    reference: Callable[[float], float],
    reference_label: str,
    scale: float = 1.0,
) -> None:
    fig, axis = plt.subplots(figsize=(3.45, 2.45))
    found = False
    for mode in MODES:
        for placement in PLACEMENTS:
            series = f"{mode}:{placement}"
            points = sorted(
                (
                    number(row["adversary_stake_fraction"]),
                    scale * number(row["mean"]),
                    *(scale * value for value in interval_errors(row)),
                )
                for row in rows
                if row.get("metric") == metric and row.get("series") == series
            )
            if not points:
                continue
            found = True
            mode_label = "Base" if mode == "none" else "Stress"
            placement_label = "random" if placement == "random" else "high-deg."
            axis.errorbar(
                [100.0 * point[0] for point in points],
                [point[1] for point in points],
                yerr=(
                    [point[2] for point in points],
                    [point[3] for point in points],
                ),
                color=COLORS[mode],
                marker=MARKERS[placement],
                linestyle=LINESTYLES[placement],
                linewidth=1.1,
                markersize=4.0,
                capsize=2.2,
                label=f"{mode_label}, {placement_label}",
            )
    if not found:
        plt.close(fig)
        raise ValueError(f"no grouped rows for {metric}")
    xs = [10.0, 20.0, 30.0]
    axis.plot(
        xs,
        [scale * reference(x / 100.0) for x in xs],
        color="#222222",
        linewidth=0.9,
        linestyle=":",
        label=reference_label,
    )
    axis.set_xlabel("Coalition stake (%)")
    axis.set_ylabel(ylabel)
    axis.set_xticks(xs)
    axis.set_ylim(bottom=0.0)
    axis.grid(axis="y", color="#E6E6E6", linewidth=0.7)
    axis.legend(
        frameon=True,
        facecolor="white",
        edgecolor="none",
        framealpha=0.9,
        loc="center",
        bbox_to_anchor=(0.55, 0.52),
        ncol=2,
        columnspacing=0.8,
        handlelength=1.8,
    )
    fig.subplots_adjust(bottom=0.19, left=0.20, right=0.97, top=0.97)
    save_figure(fig, output)
    plt.close(fig)


def paired_points(
    rows: list[dict[str, str]], metric: str, placement: str, scale: float = 100.0
) -> list[tuple[float, float, float, float]]:
    series = f"max-score-minus-none:{placement}"
    return sorted(
        (
            number(row["adversary_stake_fraction"]),
            scale * number(row["mean"]),
            *(scale * value for value in interval_errors(row)),
        )
        for row in rows
        if row.get("metric") == metric and row.get("series") == series
    )


def render_paired_capture(rows: list[dict[str, str]], output: Path) -> None:
    fig, axis = plt.subplots(figsize=(3.45, 2.45))
    metric = "adversary_organic_relay_reward_share"
    for placement in PLACEMENTS:
        points = paired_points(rows, metric, placement)
        if not points:
            plt.close(fig)
            raise ValueError(f"no paired grouped rows for {metric}:{placement}")
        label = "Random" if placement == "random" else "High degree"
        axis.errorbar(
            [100.0 * point[0] for point in points],
            [point[1] for point in points],
            yerr=([point[2] for point in points], [point[3] for point in points]),
            color="#D55E00",
            marker=MARKERS[placement],
            markerfacecolor="white" if placement == "high-degree" else "#D55E00",
            linestyle=LINESTYLES[placement],
            linewidth=1.2,
            markersize=4.2,
            capsize=2.2,
            label=label,
        )
    axis.axhline(0.0, color="#333333", linewidth=0.8, linestyle=":")
    axis.set_xlabel("Coalition stake target (%)")
    axis.set_ylabel("Reward-share gain (pp)")
    axis.set_xticks([10.0, 20.0, 30.0])
    axis.grid(axis="y", color="#E6E6E6", linewidth=0.7)
    axis.legend(
        frameon=True,
        facecolor="white",
        edgecolor="none",
        framealpha=0.9,
        loc="upper left",
    )
    fig.subplots_adjust(bottom=0.19, left=0.20, right=0.97, top=0.97)
    save_figure(fig, output)
    plt.close(fig)


def render_score_to_proposer_gain(rows: list[dict[str, str]], output: Path) -> None:
    fig, axis = plt.subplots(figsize=(3.45, 2.45))
    metrics = (
        "adversary_score_share",
        "adversary_proposer_weight_share",
    )
    for metric in metrics:
        for placement in PLACEMENTS:
            points = paired_points(rows, metric, placement)
            if not points:
                plt.close(fig)
                raise ValueError(f"no paired grouped rows for {metric}:{placement}")
            axis.errorbar(
                [100.0 * point[0] for point in points],
                [point[1] for point in points],
                yerr=(
                    [point[2] for point in points],
                    [point[3] for point in points],
                ),
                color=GAIN_COLORS[metric],
                marker=MARKERS[placement],
                markerfacecolor=(
                    "white" if placement == "high-degree" else GAIN_COLORS[metric]
                ),
                linestyle=LINESTYLES[placement],
                linewidth=1.2,
                markersize=4.2,
                capsize=2.2,
                label="_nolegend_",
            )
    axis.axhline(0.0, color="#333333", linewidth=0.8, linestyle=":")
    axis.set_xlabel("Coalition stake target (%)")
    axis.set_ylabel("Stress gain (pp)")
    axis.set_xticks([10.0, 20.0, 30.0])
    axis.grid(axis="y", color="#E6E6E6", linewidth=0.7)
    legend_handles = [
        Line2D([0], [0], color=GAIN_COLORS["adversary_score_share"], label="Score"),
        Line2D(
            [0],
            [0],
            color=GAIN_COLORS["adversary_proposer_weight_share"],
            label="Proposer weight",
        ),
        Line2D(
            [0],
            [0],
            color="#666666",
            marker=MARKERS["random"],
            linestyle=LINESTYLES["random"],
            label="Random",
        ),
        Line2D(
            [0],
            [0],
            color="#666666",
            marker=MARKERS["high-degree"],
            markerfacecolor="white",
            linestyle=LINESTYLES["high-degree"],
            label="High degree",
        ),
    ]
    axis.legend(
        handles=legend_handles,
        frameon=True,
        facecolor="white",
        edgecolor="none",
        framealpha=0.9,
        loc="center",
        bbox_to_anchor=(0.52, 0.27),
        ncol=2,
        columnspacing=1.0,
        handlelength=2.0,
    )
    fig.subplots_adjust(bottom=0.19, left=0.20, right=0.97, top=0.97)
    save_figure(fig, output)
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
    render_metric(
        rows,
        "adversary_organic_relay_reward_share",
        "Relay reward share (%)",
        "",
        args.output_dir / "organic_capture_a",
        lambda stake: stake,
        "Stake",
        scale=100.0,
    )
    render_paired_capture(rows, args.output_dir / "organic_capture_b")
    render_score_to_proposer_gain(rows, args.output_dir / "organic_capture_c")
    print(f"generated 9 files from {groups_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
