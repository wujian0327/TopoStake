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
    rows: list[dict[str, str]], metric: str, ylabel: str, title: str, output: Path
) -> None:
    selected = [
        row
        for row in rows
        if row.get("metric") == metric and row.get("series") in LABELS
    ]
    if not selected:
        raise ValueError(f"no grouped rows for {metric}")
    fig, axis = plt.subplots(figsize=(3.45, 2.55))
    for series in ("topostake_eta0", "topostake"):
        points = sorted(
            (number(row["lazy_fraction"]), number(row["mean"]), number(row["ci95"]))
            for row in selected
            if row["series"] == series
        )
        axis.errorbar(
            [100.0 * point[0] for point in points],
            [point[1] for point in points],
            yerr=[point[2] for point in points],
            color=COLORS[series],
            marker=MARKERS[series],
            linewidth=1.2,
            markersize=4.5,
            capsize=2.5,
            label=LABELS[series],
        )
    axis.set_xlabel("Lazy relayers (%)")
    axis.set_ylabel(ylabel)
    axis.set_title(title)
    axis.set_xticks([0, 25, 50, 75])
    axis.grid(axis="y", color="#E6E6E6", linewidth=0.7)
    axis.legend(frameon=False, loc="best")
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
    configure_style()
    specifications = [
        (
            "p95_inclusion_latency_s_pooled",
            "Pooled p95 latency (s)",
            "Long-horizon inclusion latency",
            "fee_bonus_long_horizon_a",
        ),
        (
            "credit_eligible_rate",
            "Credit-eligible path rate",
            "Accepted propagation evidence",
            "fee_bonus_long_horizon_b",
        ),
        (
            "relay_reward_per_stake_gini",
            "Relay reward/stake Gini",
            "Relay-reward concentration",
            "fee_bonus_long_horizon_c",
        ),
        (
            "top_degree_quartile_relay_reward_share",
            "Top-degree-quartile reward share",
            "Topology-linked reward capture",
            "fee_bonus_long_horizon_d",
        ),
        (
            "break_even_relay_cost_per_forward",
            "Reward per forward attempt",
            "Immediate relay-cost break-even point",
            "fee_bonus_long_horizon_e",
        ),
        (
            "forward_attempts_per_included_tx",
            "Forward attempts / included tx",
            "Relay work",
            "fee_bonus_long_horizon_f",
        ),
    ]
    for metric, ylabel, title, stem in specifications:
        render_metric(rows, metric, ylabel, title, args.output_dir / stem)
    print(f"generated {len(specifications) * 2} files from {groups_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
