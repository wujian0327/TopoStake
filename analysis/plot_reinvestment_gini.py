#!/usr/bin/env python3
"""Render the three-protocol long-term stake-Gini trajectory."""

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
DEFAULT_CONFIG = ROOT / "experiments" / "configs" / "frozen_v1_reinvestment_gini_main.yaml"
DEFAULT_OUTPUT = ROOT / "figures" / "frozen_v1_reinvestment_gini" / "reinvestment_gini"
PROTOCOL_STYLE = {
    "pos": ("PoS", "#666666", ":"),
    "topostake_eta0": ("Fee-only", "#E69F00", "--"),
    "topostake": ("Full TopoStake", "#0072B2", "-"),
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


def configure_style() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 8.5,
            "axes.labelsize": 8.5,
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


def render(rows: list[dict[str, str]], output: Path) -> list[Path]:
    fig, axis = plt.subplots(figsize=(3.45, 2.55))
    for protocol, (label, color, linestyle) in PROTOCOL_STYLE.items():
        points = sorted(
            (
                int(row["epoch"]),
                number(row["mean"]),
                number(row["ci95_low"]),
                number(row["ci95_high"]),
            )
            for row in rows
            if row["protocol_label"] == protocol
        )
        if not points:
            plt.close(fig)
            raise ValueError(f"missing grouped trajectory for {protocol}")
        epochs = [point[0] for point in points]
        means = [point[1] for point in points]
        axis.fill_between(
            epochs,
            [point[2] for point in points],
            [point[3] for point in points],
            color=color,
            alpha=0.13,
            linewidth=0,
        )
        axis.plot(
            epochs,
            means,
            color=color,
            linestyle=linestyle,
            linewidth=1.35,
            label=label,
        )
        axis.plot(epochs[-1], means[-1], marker="o", color=color, markersize=3.0)

    axis.set_xlabel("Epoch")
    axis.set_ylabel("Stake Gini coefficient")
    axis.set_xlim(left=0)
    axis.grid(axis="y", color="#E6E6E6", linewidth=0.7)
    axis.legend(
        loc="best",
        frameon=True,
        facecolor="white",
        edgecolor="none",
        framealpha=0.9,
        handlelength=2.1,
    )
    fig.subplots_adjust(bottom=0.19, left=0.21, right=0.97, top=0.97)
    output.parent.mkdir(parents=True, exist_ok=True)
    outputs = []
    for suffix in ("pdf", "png", "svg"):
        path = output.with_suffix(f".{suffix}")
        fig.savefig(path, dpi=300, facecolor="white")
        outputs.append(path)
    plt.close(fig)
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG.relative_to(ROOT)))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    spec = load_yaml((ROOT / args.config).resolve())
    grouped = PROCESSED / str(spec["suite"]) / "reinvestment_gini_groups.csv"
    configure_style()
    outputs = render(read_csv(grouped), args.output)
    print("\n".join(str(path.relative_to(ROOT)) for path in outputs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
