#!/usr/bin/env python3
"""Plot Prompt 41 topology comparison figures."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CSV = ROOT / "results" / "processed" / "devnet_prompt41_42_summary.csv"
FIGURES = ROOT / "figures"
TOPOLOGIES = ["linear", "er", "ba"]
TOPOLOGY_LABELS = {"linear": "Linear", "er": "ER", "ba": "BA"}
COLORS = {
    "PoS-Beacon": "#2ca02c",
    "PoS+PathObs": "#ff7f0e",
    "TopoStake": "#1f77b4",
}


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def as_float(row: dict[str, str], key: str) -> float:
    try:
        return float(row.get(key, "") or 0.0)
    except ValueError:
        return 0.0


def tx_completion_ratio(row: dict[str, str]) -> float:
    tx_success = as_float(row, "tx_success")
    tx_count = as_float(row, "tx_count")
    return tx_success / tx_count if tx_count > 0 else 0.0


def prompt41_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        row
        for row in rows
        if row.get("prompt") == "prompt41"
        and row.get("status") == "ok"
        and row.get("nodes") == "10"
        and row.get("offered_tx_per_slot") == "32"
    ]


def find_row(rows: list[dict[str, str]], topology: str, mode_label: str) -> dict[str, str]:
    matches = [
        row
        for row in rows
        if row.get("topology") == topology and row.get("mode_label") == mode_label
    ]
    if not matches:
        raise SystemExit(f"missing row for topology={topology}, mode={mode_label}")
    return matches[-1]


def save_figure(fig: plt.Figure, stem: str) -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    for suffix in ("pdf", "png"):
        path = FIGURES / f"{stem}.{suffix}"
        fig.savefig(path)
        print(f"wrote {path}")


def grouped_bars(
    *,
    values_by_label: dict[str, list[float]],
    ylabel: str,
    stem: str,
    ylim: tuple[float, float] | None = None,
    percent_axis: bool = False,
    legend_inside: bool = False,
    show_value_labels: bool = True,
) -> None:
    labels = [TOPOLOGY_LABELS[topology] for topology in TOPOLOGIES]
    x = np.arange(len(labels))
    width = 0.32
    offsets = np.linspace(-width / 2, width / 2, len(values_by_label))

    fig, ax = plt.subplots(figsize=(4.8, 3.2))
    for offset, (label, values) in zip(offsets, values_by_label.items()):
        bars = ax.bar(
            x + offset,
            values,
            width=width,
            label=label,
            color=COLORS[label],
            edgecolor="black",
            linewidth=0.5,
        )
        if show_value_labels:
            for bar, value in zip(bars, values):
                text = f"{value * 100:.1f}%" if percent_axis else f"{value:.2f}"
                text_y = bar.get_height() - 0.035 if percent_axis else bar.get_height()
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    text_y,
                    text,
                    ha="center",
                    va="top" if percent_axis else "bottom",
                    fontsize=9,
                    color="white" if percent_axis else "black",
                )

    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_xlabel("Topology", fontsize=15)
    ax.set_ylabel(ylabel, fontsize=15)
    if percent_axis:
        ax.yaxis.set_major_formatter(lambda value, _pos: f"{value * 100:.0f}%")
    if ylim is not None:
        ax.set_ylim(*ylim)
    else:
        max_value = max(max(values) for values in values_by_label.values())
        ax.set_ylim(0, max_value * 1.22)
    ax.tick_params(axis="both", labelsize=13)
    ax.grid(True, alpha=0.25)
    if legend_inside:
        ax.legend(frameon=False, fontsize=12, loc="upper center", ncol=len(values_by_label))
    else:
        ax.legend(
            frameon=False,
            fontsize=12,
            loc="upper center",
            bbox_to_anchor=(0.5, 1.18),
            ncol=len(values_by_label),
        )
    fig.subplots_adjust(left=0.14, right=0.98, top=0.96, bottom=0.18)
    save_figure(fig, stem)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    args = parser.parse_args()

    rows = prompt41_rows(load_rows(args.csv))
    completion = {
        "PoS-Beacon": [
            tx_completion_ratio(find_row(rows, topology, "PoS-Beacon"))
            for topology in TOPOLOGIES
        ],
        "TopoStake": [
            tx_completion_ratio(find_row(rows, topology, "TopoStake"))
            for topology in TOPOLOGIES
        ],
    }
    delay = {
        "PoS-Beacon": [
            as_float(find_row(rows, topology, "PoS-Beacon"), "p95_inclusion_delay_seconds")
            for topology in TOPOLOGIES
        ],
        "TopoStake": [
            as_float(find_row(rows, topology, "TopoStake"), "p95_inclusion_delay_seconds")
            for topology in TOPOLOGIES
        ],
    }
    path_length = {
        "PoS+PathObs": [
            as_float(find_row(rows, topology, "PoS+PathObs"), "avg_path_len")
            for topology in TOPOLOGIES
        ],
        "TopoStake": [
            as_float(find_row(rows, topology, "TopoStake"), "avg_path_len")
            for topology in TOPOLOGIES
        ],
    }

    grouped_bars(
        values_by_label=completion,
        ylabel="Included tx ratio",
        stem="devnet_topology_included_ratio",
        ylim=(0, 1.20),
        percent_axis=True,
        legend_inside=True,
        show_value_labels=False,
    )
    grouped_bars(
        values_by_label=delay,
        ylabel="p95 inclusion delay (s)",
        stem="devnet_topology_delay",
        legend_inside=True,
    )
    grouped_bars(
        values_by_label=path_length,
        ylabel="Avg. path length",
        stem="devnet_topology_path_length",
        legend_inside=True,
    )


if __name__ == "__main__":
    main()
