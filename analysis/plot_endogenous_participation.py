#!/usr/bin/env python3
"""Plot the calibrated endogenous relay-participation mean-field pilot."""

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
    ROOT / "experiments" / "configs" / "frozen_v1_endogenous_participation_pilot.yaml"
)
DEFAULT_OUTPUT = ROOT / "figures" / "frozen_v1_endogenous_participation"
BLUE = "#0072B2"
ORANGE = "#E69F00"
GRAY = "#666666"


def load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml  # type: ignore

        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except ModuleNotFoundError:
        return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--sweep", type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    spec = load_yaml(args.config.resolve())
    processed = ROOT / "results" / "processed" / str(spec["suite"])
    sweep_path = args.sweep or processed / "fixed_point_sweep.csv"
    rows = read_csv(sweep_path.resolve())
    if not rows:
        raise ValueError("empty endogenous-participation sweep")
    rows.sort(key=lambda row: float(row["cost_multiplier"]))
    x = [float(row["cost_multiplier"]) for row in rows]

    configure_style()
    active_fig, active_axis = plt.subplots(figsize=(3.45, 2.6))
    for prefix, color, marker, label in (
        ("fee_only", BLUE, "s", "Fee-only"),
        ("full", ORANGE, "o", "Full TopoStake"),
    ):
        y = [100.0 * float(row[f"{prefix}_active_fraction"]) for row in rows]
        low = [100.0 * float(row[f"{prefix}_ci_low"]) for row in rows]
        high = [100.0 * float(row[f"{prefix}_ci_high"]) for row in rows]
        active_axis.plot(
            x,
            y,
            color=color,
            linewidth=1.4,
            marker=marker,
            markevery=max(1, len(x) // 8),
            markersize=3.2,
            markerfacecolor="white",
            label=label,
        )
        active_axis.fill_between(x, low, high, color=color, alpha=0.14, linewidth=0)
    active_axis.axhline(
        0.0, color=GRAY, linestyle=":", linewidth=1.0, label="PoS reduced form"
    )
    active_axis.set_ylabel("Endogenous active validators (%)")
    active_axis.set_ylim(-2, 102)
    active_axis.legend(loc="best", frameon=False)

    gain_fig, gain_axis = plt.subplots(figsize=(3.45, 2.6))

    gain = [100.0 * float(row["participation_gain"]) for row in rows]
    gain_low = [100.0 * float(row["gain_ci_low"]) for row in rows]
    gain_high = [100.0 * float(row["gain_ci_high"]) for row in rows]
    gain_axis.plot(x, gain, color=ORANGE, linewidth=1.5)
    gain_axis.fill_between(
        x, gain_low, gain_high, color=ORANGE, alpha=0.16, linewidth=0
    )
    threshold = 100.0 * float(spec["go_no_go"]["minimum_participation_gain"])
    gain_axis.axhline(
        threshold,
        color=GRAY,
        linestyle="--",
        linewidth=1.0,
        label=f"Go threshold ({threshold:.0f} pp)",
    )
    gain_axis.set_ylabel("Full-minus-fee active gain (pp)")
    gain_axis.set_ylim(bottom=0)
    gain_axis.legend(loc="best", frameon=False)

    regimes = {
        str(name): float(value)
        for name, value in spec["cost_model"]["regime_multipliers"].items()
    }
    for axis in (active_axis, gain_axis):
        axis.set_xscale("log", base=2)
        axis.set_xlim(min(x), max(x))
        axis.set_xlabel("Median relay cost / fee-only reference")
        axis.grid(axis="y", color="#E6E6E6", linewidth=0.7)
        for multiplier in regimes.values():
            axis.axvline(multiplier, color="#BBBBBB", linewidth=0.7, alpha=0.8)
    active_fig.subplots_adjust(bottom=0.20, left=0.19, right=0.98, top=0.97)
    gain_fig.subplots_adjust(bottom=0.20, left=0.19, right=0.98, top=0.97)
    outputs = []
    outputs.extend(
        save_figure(
            active_fig,
            args.output_dir / "endogenous_participation_mean_field_a",
        )
    )
    outputs.extend(
        save_figure(
            gain_fig,
            args.output_dir / "endogenous_participation_mean_field_b",
        )
    )
    print("Generated: " + ", ".join(str(path) for path in outputs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
