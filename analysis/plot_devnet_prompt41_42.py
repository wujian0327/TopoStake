#!/usr/bin/env python3
"""Plot Prompt 41/42 devnet bar charts."""

from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path
from typing import Iterable

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CSV = ROOT / "results" / "processed" / "devnet_prompt41_42_summary.csv"
FIGURES = ROOT / "figures"
MODES = ["PoS-Beacon", "PoS+PathObs", "TopoStake"]
COLORS = {
    "PoS-Beacon": "#2ca02c",
    "PoS+PathObs": "#ff7f0e",
    "TopoStake": "#1f77b4",
}
MARKERS = {"PoS-Beacon": "o", "PoS+PathObs": "s", "TopoStake": "^"}
LINESTYLES = {"PoS-Beacon": "--", "PoS+PathObs": "--", "TopoStake": "-"}


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
    modes: list[str] | None = None,
) -> None:
    plot_modes = modes or MODES
    fig, ax = plt.subplots(figsize=(4.8, 3.2))
    x = np.arange(len(categories))
    width = 0.32 if len(plot_modes) == 2 else 0.24
    offsets = np.linspace(-width / 2, width / 2, len(plot_modes)) if len(plot_modes) == 2 else np.linspace(-width, width, len(plot_modes))
    for offset, mode in zip(offsets, plot_modes):
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
                    fontsize=9,
                    rotation=90,
                )
    ax.set_xticks(x)
    ax.set_xticklabels([str(category).upper() if str(category) in {"er", "ba"} else str(category).title() for category in categories])
    ax.set_xlabel(xlabel, fontsize=15)
    ax.set_ylabel(ylabel, fontsize=15)
    if percent:
        ax.yaxis.set_major_formatter(lambda value, _pos: f"{value * 100:.0f}%")
    if ylim:
        ax.set_ylim(*ylim)
    else:
        ymax = max((max(values) for values in values_by_mode.values() if values), default=1.0)
        ax.set_ylim(0, ymax * 1.18 if ymax > 0 else 1)
    ax.tick_params(axis="both", labelsize=13)
    ax.grid(True, alpha=0.25)
    ax.legend(frameon=False, fontsize=12, loc="upper center", ncol=len(plot_modes))
    fig.subplots_adjust(left=0.20, right=0.98, top=0.96, bottom=0.18)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, bbox_inches="tight")
    png_output = output.with_suffix(".png")
    fig.savefig(png_output, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {output}")
    print(f"wrote {png_output}")


def line_plot(
    x_values: list[int],
    values_by_mode: dict[str, list[float]],
    *,
    ylabel: str,
    xlabel: str,
    output: Path,
    percent: bool = False,
    ylim: tuple[float, float] | None = None,
    modes: list[str] | None = None,
    reference_one: bool = True,
) -> None:
    plot_modes = modes or MODES
    fig, ax = plt.subplots(figsize=(4.8, 3.2))
    for mode in plot_modes:
        ax.plot(
            x_values,
            values_by_mode[mode],
            marker=MARKERS.get(mode, "o"),
            markersize=5.5,
            linewidth=1.8,
            linestyle=LINESTYLES.get(mode, "-"),
            label=mode,
            color=COLORS[mode],
        )
    if reference_one:
        ax.axhline(1.0, color="#555555", linestyle="--", linewidth=0.8, alpha=0.7)
    ax.set_xlabel(xlabel, fontsize=15)
    ax.set_ylabel(ylabel, fontsize=15)
    ax.set_xticks(x_values)
    if percent:
        ax.yaxis.set_major_formatter(lambda value, _pos: f"{value * 100:.0f}%")
    if ylim:
        ax.set_ylim(*ylim)
    else:
        all_values = [value for values in values_by_mode.values() for value in values]
        ymin = min(all_values, default=0.0)
        ymax = max(all_values, default=1.0)
        pad = max(0.02, (ymax - ymin) * 0.2)
        ax.set_ylim(max(0.0, ymin - pad), ymax + pad)
    ax.tick_params(axis="both", labelsize=13)
    ax.grid(True, alpha=0.25)
    ax.legend(frameon=False, fontsize=12)
    fig.subplots_adjust(left=0.18, right=0.98, top=0.97, bottom=0.18)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output)
    png_output = output.with_suffix(".png")
    fig.savefig(png_output, dpi=300)
    plt.close(fig)
    print(f"wrote {output}")
    print(f"wrote {png_output}")


def percent_line_plot(
    x_values: list[int],
    values_by_mode: dict[str, list[float]],
    *,
    ylabel: str,
    xlabel: str,
    output: Path,
    modes: list[str],
) -> None:
    fig, ax = plt.subplots(figsize=(4.8, 3.2))
    for mode in modes:
        ax.plot(
            x_values,
            values_by_mode[mode],
            marker=MARKERS.get(mode, "o"),
            markersize=5.5,
            linewidth=1.8,
            linestyle=LINESTYLES.get(mode, "-"),
            label=mode,
            color=COLORS[mode],
        )
    ax.set_xlabel(xlabel, fontsize=15)
    ax.set_ylabel(ylabel, fontsize=15)
    ax.set_xticks(x_values)
    ax.yaxis.set_major_formatter(lambda value, _pos: f"{value * 100:.0f}%")
    all_values = [value for values in values_by_mode.values() for value in values]
    ymin = min(all_values, default=0.0)
    ymax = max(all_values, default=1.0)
    pad = max(0.02, (ymax - ymin) * 0.35)
    ax.set_ylim(min(0.70, max(0.0, ymin - pad)), 1.0)
    ax.tick_params(axis="both", labelsize=13)
    ax.grid(True, alpha=0.25)
    ax.legend(frameon=False, fontsize=12, loc="lower left")
    fig.subplots_adjust(left=0.18, right=0.98, top=0.97, bottom=0.18)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output)
    png_output = output.with_suffix(".png")
    fig.savefig(png_output, dpi=300)
    plt.close(fig)
    print(f"wrote {output}")
    print(f"wrote {png_output}")


def plot_prompt41(rows: list[dict[str, str]]) -> None:
    categories = ["linear", "er", "ba"]
    p41 = [row for row in rows if row.get("prompt") == "prompt41" and row.get("status") == "ok"]
    ratio = {mode: [] for mode in MODES}
    delay_modes = ["PoS-Beacon", "TopoStake"]
    delay = {mode: [] for mode in delay_modes}
    path_modes = ["PoS+PathObs", "TopoStake"]
    path = {mode: [] for mode in path_modes}
    for topology in categories:
        for mode in MODES:
            row = find_row(p41, topology=topology, mode_label=mode)
            ratio[mode].append(as_float(row or {}, "achieved_ratio"))
            if mode in delay_modes:
                delay[mode].append(as_float(row or {}, "p95_inclusion_delay_seconds"))
            if mode in path_modes:
                path[mode].append(as_float(row or {}, "avg_path_len"))
    grouped_bars(
        categories,
        ratio,
        ylabel="Achieved tx/slot (% offered)",
        xlabel="Topology",
        output=FIGURES / "devnet_topology_achieved_ratio.pdf",
        ylim=(0, 1.12),
        percent=True,
    )
    grouped_bars(
        categories,
        delay,
        ylabel="p95 inclusion delay (s)",
        xlabel="Topology",
        output=FIGURES / "devnet_topology_delay.pdf",
    )
    grouped_bars(
        categories,
        path,
        ylabel="Average path length",
        xlabel="Topology",
        output=FIGURES / "devnet_topology_path_length.pdf",
    )


def plot_prompt42(rows: list[dict[str, str]]) -> None:
    p42 = [row for row in rows if row.get("prompt") == "prompt42" and row.get("status") == "ok"]
    loads = [32, 64, 128, 160]
    load_modes = ["PoS-Beacon", "TopoStake"]
    ratio = {mode: [] for mode in load_modes}
    for load in loads:
        for mode in load_modes:
            row = find_row(p42, figure="load", offered_tx_per_slot=load, mode_label=mode)
            ratio[mode].append(as_float(row or {}, "included_ratio"))
    grouped_bars(
        loads,
        ratio,
        ylabel="Included tx ratio",
        xlabel="Offered load (tx/slot)",
        output=FIGURES / "devnet_load_included_ratio_bar.pdf",
        ylim=(0, 1.12),
        percent=True,
        modes=load_modes,
    )

    tps_rows = [row for row in p42 if row.get("figure") == "load_tps"]
    tps_loads = sorted(
        {
            int(as_float(row, "offered_tps"))
            for row in tps_rows
            if as_float(row, "offered_tps") > 0
        }
    )
    if tps_loads:
        window_ratio = {mode: [] for mode in load_modes}
        for load in tps_loads:
            for mode in load_modes:
                row = find_row(tps_rows, offered_tps=float(load), mode_label=mode)
                if row is None:
                    row = find_row(tps_rows, offered_tps=load, mode_label=mode)
                window_ratio[mode].append(as_float(row or {}, "window_achieved_ratio"))
        percent_line_plot(
            tps_loads,
            window_ratio,
            ylabel="Window achieved ratio",
            xlabel="Offered load (tx/s)",
            output=FIGURES / "devnet_load_window_achieved_ratio_line.pdf",
            modes=load_modes,
        )

    achieved_loads = [32, 64, 128, 160, 192, 224, 256, 288]
    achieved = {mode: [] for mode in load_modes}
    for load in achieved_loads:
        for mode in load_modes:
            row = find_row(p42, figure="load", offered_tx_per_slot=load, mode_label=mode)
            achieved[mode].append(as_float(row or {}, "achieved_ratio"))
    line_plot(
        achieved_loads,
        achieved,
        ylabel="Achieved ratio",
        xlabel="Offered load (tx/slot)",
        output=FIGURES / "devnet_load_achieved_ratio_line.pdf",
        ylim=(0.94, 1.06),
        percent=True,
        modes=load_modes,
    )

    nodes = [6, 9, 12, 16]
    path_modes = ["PoS+PathObs", "TopoStake"]
    path = {mode: [] for mode in path_modes}
    for node_count in nodes:
        for mode in path_modes:
            row = find_row(p42, figure="nodes", nodes=node_count, mode_label=mode)
            path[mode].append(as_float(row or {}, "avg_path_len"))
    grouped_bars(
        nodes,
        path,
        ylabel="Avg. path length",
        xlabel="Number of nodes",
        output=FIGURES / "devnet_nodes_path_length_bar.pdf",
        modes=path_modes,
    )
    line_plot(
        nodes,
        path,
        ylabel="Avg. path length",
        xlabel="Number of nodes",
        output=FIGURES / "devnet_nodes_path_length_line.pdf",
        modes=path_modes,
        reference_one=False,
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
