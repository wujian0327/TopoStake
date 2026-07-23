#!/usr/bin/env python3
"""Plot independent panels for the adaptive participation experiment."""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
from typing import Any

os.environ.setdefault("MPLCONFIGDIR", "/tmp/topostake-matplotlib")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = (
    ROOT / "experiments" / "configs" / "frozen_v1_adaptive_participation_pilot.yaml"
)
DEFAULT_OUTPUT = ROOT / "figures" / "frozen_v1_adaptive_participation"
SERIES = {
    "pos": ("PoS", "#666666", ":", "^"),
    "topostake_eta0": ("Fee-only", "#0072B2", "--", "s"),
    "topostake": ("Full TopoStake", "#E69F00", "-", "o"),
}
REFERENCE_INITIAL_ACTIVE = 0.5
REFERENCE_COST_MULTIPLIER = 2.0


def load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml  # type: ignore

        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except ModuleNotFoundError:
        return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def number(value: Any) -> float:
    return float(value)


def configure_style() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 8.5,
            "axes.labelsize": 8.5,
            "legend.fontsize": 7.2,
            "xtick.labelsize": 7.5,
            "ytick.labelsize": 7.5,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )


def save_figure(fig: Any, output: Path) -> list[Path]:
    output.parent.mkdir(parents=True, exist_ok=True)
    paths = []
    for suffix in ("pdf", "png"):
        path = output.with_suffix(f".{suffix}")
        fig.savefig(path, dpi=300, bbox_inches="tight", facecolor="white")
        paths.append(path)
    plt.close(fig)
    return paths


def style_axis(axis: Any) -> None:
    axis.grid(axis="y", color="#E6E6E6", linewidth=0.7)
    axis.set_axisbelow(True)


def plot_trajectory(rows: list[dict[str, str]], output: Path) -> list[Path]:
    fig, axis = plt.subplots(figsize=(3.45, 2.6))
    for protocol, (label, color, linestyle, marker) in SERIES.items():
        selected = sorted(
            (
                row
                for row in rows
                if row["protocol_label"] == protocol
                and abs(
                    number(row["initial_active_fraction"])
                    - REFERENCE_INITIAL_ACTIVE
                )
                < 1e-12
                and abs(
                    number(row["cost_median_multiplier"])
                    - REFERENCE_COST_MULTIPLIER
                )
                < 1e-12
            ),
            key=lambda row: number(row["epoch"]),
        )
        x = [number(row["epoch"]) for row in selected]
        y = [100.0 * number(row["active_stake_share"]) for row in selected]
        ci = [100.0 * number(row["ci95"]) for row in selected]
        axis.plot(
            x,
            y,
            color=color,
            linestyle=linestyle,
            linewidth=1.4,
            marker=marker,
            markevery=max(1, len(x) // 8),
            markersize=3.0,
            markerfacecolor="white",
            label=label,
        )
        axis.fill_between(
            x,
            [value - spread for value, spread in zip(y, ci)],
            [value + spread for value, spread in zip(y, ci)],
            color=color,
            alpha=0.12,
            linewidth=0,
        )
    axis.set_xlabel("Epoch")
    axis.set_ylabel("Active-stake share (%)")
    axis.set_ylim(0, 100)
    axis.legend(frameon=False, loc="best")
    style_axis(axis)
    fig.subplots_adjust(bottom=0.19, left=0.19, right=0.98, top=0.97)
    return save_figure(fig, output / "adaptive_participation_a")


def plot_steady_state(rows: list[dict[str, str]], output: Path) -> list[Path]:
    fig, axis = plt.subplots(figsize=(3.45, 2.6))
    for protocol, (label, color, linestyle, marker) in SERIES.items():
        selected = sorted(
            (
                row
                for row in rows
                if row["protocol_label"] == protocol
                and abs(
                    number(row["initial_active_fraction"])
                    - REFERENCE_INITIAL_ACTIVE
                )
                < 1e-12
            ),
            key=lambda row: number(row["cost_median_multiplier"]),
        )
        x = [number(row["cost_median_multiplier"]) for row in selected]
        y = [100.0 * number(row["steady_active_stake_share"]) for row in selected]
        ci = [100.0 * number(row["steady_active_stake_share_ci95"]) for row in selected]
        axis.errorbar(
            x,
            y,
            yerr=ci,
            color=color,
            linestyle=linestyle,
            linewidth=1.4,
            marker=marker,
            markersize=4.0,
            markerfacecolor="white",
            capsize=2.2,
            label=label,
        )
    axis.set_xlabel("Median relay-cost multiplier")
    axis.set_ylabel("Steady active-stake share (%)")
    axis.set_xticks([1, 2, 3])
    axis.set_yticks([0, 20, 40, 60, 80, 100])
    axis.set_ylim(0, 100)
    style_axis(axis)
    fig.subplots_adjust(bottom=0.19, left=0.19, right=0.98, top=0.97)
    return save_figure(fig, output / "adaptive_participation_b")


def plot_latency(rows: list[dict[str, str]], output: Path) -> list[Path]:
    fig, axis = plt.subplots(figsize=(3.45, 2.6))
    for protocol, (label, color, linestyle, marker) in SERIES.items():
        selected = sorted(
            (
                row
                for row in rows
                if row["protocol_label"] == protocol
                and abs(
                    number(row["initial_active_fraction"])
                    - REFERENCE_INITIAL_ACTIVE
                )
                < 1e-12
            ),
            key=lambda row: number(row["cost_median_multiplier"]),
        )
        x = [number(row["cost_median_multiplier"]) for row in selected]
        y = [number(row["restricted_mean_inclusion_latency_s"]) for row in selected]
        ci = [
            number(row["restricted_mean_inclusion_latency_s_ci95"])
            for row in selected
        ]
        axis.errorbar(
            x,
            y,
            yerr=ci,
            color=color,
            linestyle=linestyle,
            linewidth=1.4,
            marker=marker,
            markersize=4.0,
            markerfacecolor="white",
            capsize=2.2,
            label=label,
        )
    axis.set_xlabel("Median relay-cost multiplier")
    axis.set_ylabel("Restricted mean time to inclusion (s)")
    axis.set_xticks([1, 2, 3])
    axis.set_ylim(bottom=0)
    axis.legend(frameon=False, loc="best")
    style_axis(axis)
    fig.subplots_adjust(bottom=0.19, left=0.19, right=0.98, top=0.97)
    return save_figure(fig, output / "adaptive_participation_c")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    spec = load_yaml(args.config.resolve())
    suite = str(spec["suite"])
    prefix = ROOT / "results" / "processed" / suite
    groups = read_csv(prefix.with_name(prefix.name + "_groups.csv"))
    trajectory = read_csv(prefix.with_name(prefix.name + "_trajectory.csv"))
    configure_style()
    outputs = []
    outputs.extend(plot_trajectory(trajectory, args.output_dir))
    outputs.extend(plot_steady_state(groups, args.output_dir))
    outputs.extend(plot_latency(groups, args.output_dir))
    print("Generated: " + ", ".join(str(path) for path in outputs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
