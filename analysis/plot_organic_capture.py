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


ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "results" / "processed"
DEFAULT_CONFIG = ROOT / "experiments" / "configs" / "frozen_v1_organic_capture_pilot.yaml"
DEFAULT_OUTPUT = ROOT / "figures" / "frozen_v1_organic_capture"
MODES = ("none", "max-score")
PLACEMENTS = ("random", "high-degree")
COLORS = {"none": "#777777", "max-score": "#D55E00"}
MARKERS = {"random": "o", "high-degree": "s"}
LINESTYLES = {"random": "-", "high-degree": "--"}


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


def render_metric(
    rows: list[dict[str, str]],
    metric: str,
    ylabel: str,
    title: str,
    output: Path,
    reference: Callable[[float], float],
    reference_label: str,
) -> None:
    fig, axis = plt.subplots(figsize=(3.45, 2.55))
    found = False
    for mode in MODES:
        for placement in PLACEMENTS:
            series = f"{mode}:{placement}"
            points = sorted(
                (
                    number(row["adversary_stake_fraction"]),
                    number(row["mean"]),
                    *interval_errors(row),
                )
                for row in rows
                if row.get("metric") == metric and row.get("series") == series
            )
            if not points:
                continue
            found = True
            mode_label = "Baseline" if mode == "none" else "Capture stress"
            placement_label = "random" if placement == "random" else "high degree"
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
        [reference(x / 100.0) for x in xs],
        color="#222222",
        linewidth=0.9,
        linestyle=":",
        label=reference_label,
    )
    axis.set_xlabel("Coalition stake (%)")
    axis.set_ylabel(ylabel)
    axis.set_title(title)
    axis.set_xticks(xs)
    axis.grid(axis="y", color="#E6E6E6", linewidth=0.7)
    axis.legend(frameon=False, loc="best", ncol=1)
    fig.subplots_adjust(bottom=0.18, left=0.20, right=0.97, top=0.88)
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
    defaults = config.get("defaults", {})
    c = number(defaults.get("eta", 0.0)) * number(defaults.get("bonus_cap", 0.0))
    configure_style()
    render_metric(
        rows,
        "adversary_organic_relay_reward_share",
        "Coalition share of organic relay reward",
        "User-funded relay-reward capture",
        args.output_dir / "organic_capture_a",
        lambda stake: stake,
        "Stake share",
    )
    render_metric(
        rows,
        "adversary_organic_raw_contribution_share",
        "Coalition share of organic contribution",
        "User-funded score-input capture",
        args.output_dir / "organic_capture_b",
        lambda stake: stake,
        "Stake share",
    )
    render_metric(
        rows,
        "adversary_proposer_weight_share",
        "Coalition proposer-weight share",
        "Bounded consensus influence",
        args.output_dir / "organic_capture_c",
        lambda stake: stake * (1.0 + c) / (1.0 + stake * c),
        "Protocol envelope",
    )
    print(f"generated 6 files from {groups_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
