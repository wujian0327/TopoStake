#!/usr/bin/env python3
"""Enumerate and plot TRAIL consecutive path-padding contribution ratios.

This is a deterministic calculation from the current path-budget and relay
position-weight formulas.  It does not read the legacy fixed-path CSV used by
``frozen_padding_b.pdf``.
"""

from __future__ import annotations

import argparse
import math
import os
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/trail-matplotlib")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "figures" / "trail_security"

DEPTHS = (2, 4, 8)
MAX_PATH_HOPS = 16
INSERTED_IDENTITIES = range(1, 15)

BLUE = "#0072B2"
ORANGE = "#D55E00"
GREEN = "#009E73"
GRAY = "#666666"

DEPTH_STYLE = {
    2: (BLUE, "o"),
    4: (ORANGE, "s"),
    8: (GREEN, "^"),
}


@dataclass(frozen=True)
class Maximum:
    depth: int
    inserted: int
    base_path_length: int
    ratio: float


def lambda_for_depth(depth: int) -> float:
    """lambda = (2D + 1) / (3D + 1)."""
    return (2.0 * depth + 1.0) / (3.0 * depth + 1.0)


def r_for_depth(depth: int) -> float:
    """r = D / (2D + 1)."""
    return depth / (2.0 * depth + 1.0)


def path_budget(depth: int, path_length: int) -> float:
    """B(m) = lambda^(m-1) min(1, D/m)."""
    if path_length < 2:
        raise ValueError("path length must be at least two")
    return lambda_for_depth(depth) ** (path_length - 1) * min(
        1.0, depth / path_length
    )


def first_relay_contribution(depth: int, path_length: int) -> float:
    """K_m = B(m) (1-r) / (1-r^(m-1))."""
    r = r_for_depth(depth)
    return path_budget(depth, path_length) * (1.0 - r) / (
        1.0 - r ** (path_length - 1)
    )


def replacement_ratio(depth: int, base_path_length: int, inserted: int) -> float:
    """Contribution ratio for replacing one relay by q+1 identities."""
    if inserted < 1 or base_path_length + inserted > MAX_PATH_HOPS:
        raise ValueError("replacement is outside the enumerated path range")
    r = r_for_depth(depth)
    geometric_sum = sum(r**position for position in range(inserted + 1))
    return (
        first_relay_contribution(depth, base_path_length + inserted)
        / first_relay_contribution(depth, base_path_length)
        * geometric_sum
    )


def enumerate_maxima() -> list[Maximum]:
    maxima: list[Maximum] = []
    for depth in DEPTHS:
        # The current parametrization deliberately satisfies lambda(1+r)=1.
        if not math.isclose(
            lambda_for_depth(depth) * (1.0 + r_for_depth(depth)),
            1.0,
            rel_tol=0.0,
            abs_tol=1e-15,
        ):
            raise AssertionError(f"invalid lambda/r identity for D={depth}")
        for inserted in INSERTED_IDENTITIES:
            candidates = [
                Maximum(
                    depth=depth,
                    inserted=inserted,
                    base_path_length=base_path_length,
                    ratio=replacement_ratio(depth, base_path_length, inserted),
                )
                for base_path_length in range(2, MAX_PATH_HOPS - inserted + 1)
            ]
            maxima.append(max(candidates, key=lambda item: item.ratio))
    return maxima


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


def render(maxima: list[Maximum], output_dir: Path) -> tuple[Path, Path]:
    configure_style()
    fig, ax = plt.subplots(figsize=(3.45, 2.55))
    ax.grid(axis="y", color="#E6E6E6", linewidth=0.7, zorder=0)

    for depth in DEPTHS:
        selected = [item for item in maxima if item.depth == depth]
        color, marker = DEPTH_STYLE[depth]
        ax.plot(
            [item.inserted for item in selected],
            [item.ratio for item in selected],
            color=color,
            marker=marker,
            markerfacecolor="white",
            markeredgewidth=1.0,
            linewidth=1.2,
            markersize=4.5,
            label=fr"$D={depth}$",
            zorder=3,
        )

    ax.axhline(
        1.0,
        color=GRAY,
        linestyle="--",
        linewidth=1.0,
        label="Non-amplification bound",
        zorder=1,
    )
    ax.set_xlim(0.7, 14.3)
    ax.set_ylim(0.0, 1.05)
    ax.set_xticks([1, 4, 7, 10, 14])
    ax.set_xlabel("Inserted identities")
    ax.set_ylabel("Maximum contribution ratio")
    ax.spines["left"].set_linewidth(0.9)
    ax.spines["bottom"].set_linewidth(0.9)
    ax.tick_params(width=0.8, length=3)
    ax.legend(
        frameon=True,
        framealpha=0.92,
        facecolor="white",
        edgecolor="#D0D0D0",
        ncol=2,
        loc="upper right",
        bbox_to_anchor=(0.99, 0.94),
        borderpad=0.3,
        columnspacing=0.75,
        handlelength=1.45,
        handletextpad=0.4,
        labelspacing=0.25,
    )
    fig.subplots_adjust(bottom=0.18, left=0.155, right=0.97, top=0.97)

    output_dir.mkdir(parents=True, exist_ok=True)
    pdf = output_dir / "trail_path_padding.pdf"
    png = output_dir / "trail_path_padding.png"
    fig.savefig(pdf, facecolor="white")
    fig.savefig(png, dpi=300, facecolor="white")
    plt.close(fig)
    return pdf, png


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    maxima = enumerate_maxima()
    pdf, png = render(maxima, args.output_dir)
    for depth in DEPTHS:
        overall = max(
            (item for item in maxima if item.depth == depth),
            key=lambda item: item.ratio,
        )
        print(
            f"D={depth} maximum={overall.ratio:.15f} "
            f"m={overall.base_path_length} q={overall.inserted}"
        )
    print(f"ratios above one: {sum(item.ratio > 1.0 for item in maxima)}")
    print(f"pdf: {pdf}")
    print(f"png: {png}")


if __name__ == "__main__":
    main()
