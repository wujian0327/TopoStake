#!/usr/bin/env python3
"""Render the three-panel TRAIL adaptive relay-participation figure set."""

from __future__ import annotations

import argparse
import csv
import math
import os
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

os.environ.setdefault("MPLCONFIGDIR", "/tmp/trail-matplotlib")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.stats import t as student_t


ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "results" / "processed" / "trail_relay_participation_runs.csv"
EPOCHS = ROOT / "results" / "processed" / "trail_relay_participation_epochs.csv"
OUTPUT = ROOT / "figures" / "trail_participation"
LEFT_MARGIN = 0.16
MECHANISMS = ("PoS", "Fee-only", "Full TRAIL")
STYLES = {
    "PoS": {"color": "#6B6B6B", "marker": "^", "linestyle": ":"},
    "Fee-only": {"color": "#0072B2", "marker": "s", "linestyle": "--"},
    "Full TRAIL": {"color": "#D55E00", "marker": "o", "linestyle": "-"},
}


def truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def mean_ci95(values: Iterable[float]) -> tuple[float, float, int]:
    sample = [float(value) for value in values]
    if len(sample) != 20 or not all(math.isfinite(value) for value in sample):
        raise ValueError(f"expected 20 finite values, got {len(sample)}")
    critical = float(student_t.ppf(0.975, len(sample) - 1))
    return (
        statistics.mean(sample),
        critical * statistics.stdev(sample) / math.sqrt(len(sample)),
        len(sample),
    )


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


def decorate(ax: Any) -> None:
    ax.grid(axis="y", color="#E6E6E6", linewidth=0.7, zorder=0)
    ax.spines["left"].set_linewidth(0.9)
    ax.spines["bottom"].set_linewidth(0.9)
    ax.tick_params(width=0.8, length=3)
    ax.legend(
        frameon=True,
        framealpha=0.9,
        facecolor="white",
        edgecolor="#D0D0D0",
        borderpad=0.35,
        handletextpad=0.5,
    )


def save(fig: Any, stem: str, output: Path) -> tuple[Path, Path]:
    output.mkdir(parents=True, exist_ok=True)
    pdf = output / f"{stem}.pdf"
    png = output / f"{stem}.png"
    fig.savefig(pdf)
    fig.savefig(png, dpi=300)
    plt.close(fig)
    return pdf, png


def panel_a(epoch_rows: list[dict[str, str]], output: Path) -> tuple[Path, Path]:
    selected = [row for row in epoch_rows if float(row["cost_multiplier"]) == 2.0]
    grouped: dict[tuple[str, int], list[float]] = defaultdict(list)
    for row in selected:
        grouped[(row["mechanism"], int(row["epoch"]))].append(
            100.0 * float(row["active_relay_stake_share"])
        )
    fig, ax = plt.subplots(figsize=(3.45, 2.55))
    for mechanism in MECHANISMS:
        style = STYLES[mechanism]
        epochs = list(range(200))
        points = [mean_ci95(grouped[(mechanism, epoch)]) for epoch in epochs]
        means = [point[0] for point in points]
        cis = [point[1] for point in points]
        ax.fill_between(
            epochs,
            [mean - ci for mean, ci in zip(means, cis)],
            [mean + ci for mean, ci in zip(means, cis)],
            color=style["color"],
            alpha=0.12,
            linewidth=0,
            zorder=1,
        )
        ax.plot(
            epochs,
            means,
            color=style["color"],
            linestyle=style["linestyle"],
            marker=style["marker"],
            markevery=20,
            markerfacecolor="white",
            markeredgewidth=0.9,
            linewidth=1.2,
            markersize=3.8,
            label=mechanism,
            zorder=2,
        )
    ax.set_xlabel("Epoch")
    ax.set_ylabel("Active relay stake (%)")
    ax.set_xlim(0, 200)
    ax.set_xticks([0, 50, 100, 150, 200])
    ax.set_ylim(bottom=0.0, top=100.0)
    decorate(ax)
    fig.subplots_adjust(bottom=0.18, left=LEFT_MARGIN, right=0.97, top=0.97)
    return save(fig, "trail_relay_participation_a", output)


def grouped_runs(run_rows: list[dict[str, str]], field: str) -> dict[tuple[str, float], tuple[float, float, int]]:
    grouped: dict[tuple[str, float], list[float]] = defaultdict(list)
    for row in run_rows:
        if not truthy(row["valid"]):
            raise ValueError(f"invalid run supplied to plotting: {row['run_id']}")
        value = float(row[field])
        if field == "steady_active_relay_stake_share":
            value *= 100.0
        grouped[(row["mechanism"], float(row["cost_multiplier"]))].append(value)
    return {key: mean_ci95(values) for key, values in grouped.items()}


def cost_panel(
    run_rows: list[dict[str, str]],
    output: Path,
    *,
    field: str,
    ylabel: str,
    stem: str,
    ymax: float | None = None,
) -> tuple[Path, Path]:
    points = grouped_runs(run_rows, field)
    fig, ax = plt.subplots(figsize=(3.45, 2.55))
    costs = [1.0, 2.0, 3.0]
    offsets = {"PoS": -0.035, "Fee-only": 0.0, "Full TRAIL": 0.035}
    for mechanism in MECHANISMS:
        style = STYLES[mechanism]
        means = [points[(mechanism, cost)][0] for cost in costs]
        cis = [points[(mechanism, cost)][1] for cost in costs]
        x = [cost + offsets[mechanism] for cost in costs]
        ax.errorbar(
            x,
            means,
            yerr=cis,
            color=style["color"],
            linestyle=style["linestyle"],
            marker=style["marker"],
            markerfacecolor="white",
            markeredgewidth=1.0,
            linewidth=1.2,
            markersize=4.5,
            capsize=2.5,
            label=mechanism,
            zorder=2,
        )
    ax.set_xlabel(r"Median relay cost / $C_{\mathrm{ref}}$")
    ax.set_ylabel(ylabel)
    ax.set_xticks(costs, [r"$1\times$", r"$2\times$", r"$3\times$"])
    ax.set_xlim(0.8, 3.2)
    ax.set_ylim(bottom=0.0, top=ymax)
    decorate(ax)
    fig.subplots_adjust(bottom=0.18, left=LEFT_MARGIN, right=0.97, top=0.97)
    return save(fig, stem, output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, default=RUNS)
    parser.add_argument("--epochs", type=Path, default=EPOCHS)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT)
    args = parser.parse_args()
    configure_style()
    runs = read_csv(args.runs)
    epochs = read_csv(args.epochs)
    if len(runs) != 180 or len(epochs) != 180 * 200:
        raise ValueError(f"expected 180 runs and 36000 epoch rows; got {len(runs)} and {len(epochs)}")
    outputs = [
        *panel_a(epochs, args.output_dir),
        *cost_panel(
            runs,
            args.output_dir,
            field="steady_active_relay_stake_share",
            ylabel="Active relay stake (%)",
            stem="trail_relay_participation_b",
            ymax=100.0,
        ),
        *cost_panel(
            runs,
            args.output_dir,
            field="restricted_mean_inclusion_time_s",
            ylabel="Inclusion time (s)",
            stem="trail_relay_participation_c",
        ),
    ]
    for path in outputs:
        print(path.relative_to(ROOT))


if __name__ == "__main__":
    main()
