#!/usr/bin/env python3
"""Plot Prompt 41/42 devnet bar charts."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CSV = ROOT / "results" / "processed" / "devnet_prompt41_42_summary.csv"
FIGURES = ROOT / "figures"
MODES = ["PoS-Beacon", "PoS+PathObs", "TopoStake"]
COLORS = {
    "PoS-Beacon": "#4C78A8",
    "PoS+PathObs": "#F58518",
    "TopoStake": "#54A24B",
}


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open() as handle:
        return list(csv.DictReader(handle))


def as_float(row: dict[str, str], key: str) -> float:
    try:
        return float(row.get(key, "") or 0.0)
    except ValueError:
        return 0.0


def find_row(rows: Iterable[dict[str, str]], **filters: object) -> dict[str, str] | None:
    for row in rows:
        if all(str(row.get(key)) == str(value) for key, value in filters.items()):
            return row
    return None


def grouped_bars(
    categories: list[object],
    values_by_mode: dict[str, list[float]],
    *,
    ylabel: str,
    xlabel: str,
    output: Path,
    ylim: tuple[float, float] | None = None,
    percent: bool = False,
    na_baseline: bool = False,
) -> None:
    fig, ax = plt.subplots(figsize=(4.8, 3.0))
    x = np.arange(len(categories))
    width = 0.24
    offsets = np.linspace(-width, width, len(MODES))
    for offset, mode in zip(offsets, MODES):
        values = values_by_mode[mode]
        kwargs = {
            "width": width,
            "label": mode,
            "color": COLORS[mode],
            "edgecolor": "black",
            "linewidth": 0.45,
        }
        if na_baseline and mode == "PoS-Beacon":
            kwargs["hatch"] = "///"
            kwargs["alpha"] = 0.45
        bars = ax.bar(x + offset, values, **kwargs)
        if na_baseline and mode == "PoS-Beacon":
            for bar in bars:
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    max(0.02, bar.get_height() + 0.02),
                    "N/A",
                    ha="center",
                    va="bottom",
                    fontsize=7,
                    rotation=90,
                )
    ax.set_xticks(x)
    ax.set_xticklabels([str(category).upper() if str(category) in {"er", "ba"} else str(category).title() for category in categories])
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    if percent:
        ax.yaxis.set_major_formatter(lambda value, _pos: f"{value * 100:.0f}%")
    if ylim:
        ax.set_ylim(*ylim)
    else:
        ymax = max((max(values) for values in values_by_mode.values() if values), default=1.0)
        ax.set_ylim(0, ymax * 1.18 if ymax > 0 else 1)
    ax.grid(axis="y", linestyle="--", linewidth=0.5, alpha=0.35)
    ax.legend(frameon=False, fontsize=8, ncol=1)
    fig.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {output}")


def plot_prompt41(rows: list[dict[str, str]]) -> None:
    categories = ["linear", "er", "ba"]
    p41 = [row for row in rows if row.get("prompt") == "prompt41" and row.get("status") == "ok"]
    ratio = {mode: [] for mode in MODES}
    delay = {mode: [] for mode in MODES}
    path = {mode: [] for mode in MODES}
    for topology in categories:
        for mode in MODES:
            row = find_row(p41, topology=topology, mode_label=mode)
            ratio[mode].append(as_float(row or {}, "achieved_ratio"))
            delay[mode].append(as_float(row or {}, "p95_inclusion_delay_seconds"))
            path[mode].append(0.0 if mode == "PoS-Beacon" else as_float(row or {}, "avg_path_len"))
    grouped_bars(
        categories,
        ratio,
        ylabel="Achieved load (%)",
        xlabel="Topology",
        output=FIGURES / "devnet_topology_achieved_ratio.pdf",
        ylim=(0, 1.12),
        percent=True,
    )
    grouped_bars(
        categories,
        delay,
        ylabel="p95 delay (s)",
        xlabel="Topology",
        output=FIGURES / "devnet_topology_delay.pdf",
    )
    grouped_bars(
        categories,
        path,
        ylabel="Average path length",
        xlabel="Topology",
        output=FIGURES / "devnet_topology_path_length.pdf",
        na_baseline=True,
    )


def plot_prompt42(rows: list[dict[str, str]]) -> None:
    p42 = [row for row in rows if row.get("prompt") == "prompt42" and row.get("status") == "ok"]
    loads = [60, 120, 180, 240, 300]
    ratio = {mode: [] for mode in MODES}
    for load in loads:
        for mode in MODES:
            row = find_row(p42, figure="load", offered_tx_per_slot=load, mode_label=mode)
            ratio[mode].append(as_float(row or {}, "achieved_ratio"))
    grouped_bars(
        loads,
        ratio,
        ylabel="Achieved load (%)",
        xlabel="Offered load (tx/slot)",
        output=FIGURES / "devnet_load_achieved_ratio_bar.pdf",
        ylim=(0, 1.12),
        percent=True,
    )

    nodes = [4, 8, 12, 16]
    delay = {mode: [] for mode in MODES}
    path = {mode: [] for mode in MODES}
    for node_count in nodes:
        for mode in MODES:
            row = find_row(p42, figure="nodes", nodes=node_count, mode_label=mode)
            delay[mode].append(as_float(row or {}, "p95_inclusion_delay_seconds"))
            path[mode].append(0.0 if mode == "PoS-Beacon" else as_float(row or {}, "avg_path_len"))
    grouped_bars(
        nodes,
        delay,
        ylabel="p95 delay (s)",
        xlabel="Number of nodes",
        output=FIGURES / "devnet_nodes_delay_bar.pdf",
    )
    grouped_bars(
        nodes,
        path,
        ylabel="Average path length",
        xlabel="Number of nodes",
        output=FIGURES / "devnet_nodes_path_length_bar.pdf",
        na_baseline=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    args = parser.parse_args()
    rows = load_rows(args.csv)
    plot_prompt41(rows)
    plot_prompt42(rows)


if __name__ == "__main__":
    main()
