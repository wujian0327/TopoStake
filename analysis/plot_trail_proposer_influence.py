#!/usr/bin/env python3
"""Plot TRAIL proposer influence against the stake-only analytical bound.

This figure intentionally uses the realized normalized coalition stake and
normalized proposer-weight share from each completed simulator run.  It does
not use score-dependent bounds or finite proposer-election frequencies.
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import statistics
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

os.environ.setdefault("MPLCONFIGDIR", "/tmp/trail-matplotlib")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "results" / "processed" / "trail_proposer_influence_runs.csv"
DEFAULT_OUTPUT = ROOT / "figures" / "trail_security"
DEFAULT_PDF = DEFAULT_OUTPUT / "trail_proposer_influence.pdf"
DEFAULT_PNG = DEFAULT_OUTPUT / "trail_proposer_influence.png"

BLUE = "#0072B2"
RED = "#D55E00"
GREEN = "#009E73"
GRAY = "#666666"
LIGHT_GRAY = "#B5B5B5"

ETA_COLORS = {0.25: BLUE, 0.5: RED, 1.0: GREEN}
EXPECTED_ETAS = set(ETA_COLORS)
PLACEMENT_MARKERS = {
    "random": ("o", "Random"),
    "high-degree": ("s", "Degree"),
    "high-betweenness": ("^", "Betweenness"),
}

# The formal matrix has 20 independent seeds per scenario (19 degrees of
# freedom). Keeping the exact critical value local avoids adding SciPy as a
# plotting dependency and prevents a partial matrix from silently producing a
# differently defined paper figure.
EXPECTED_GROUP_SIZE = 20
EXPECTED_RUNS_PER_ETA = 240
EXPECTED_TOTAL_RUNS = EXPECTED_RUNS_PER_ETA * len(EXPECTED_ETAS)
T_975_DF19 = 2.093024054408263

REQUIRED_FIELDS = {
    "experiment",
    "status",
    "complete",
    "finite_metrics",
    "seed_index",
    "adversary_stake_fraction",
    "adversary_real_stake_share_mean",
    "eta",
    "adversary_placement",
    "adversary_proposer_weight_share_mean",
}


@dataclass(frozen=True)
class Run:
    seed_index: str
    target_stake: float
    stake: float
    eta: float
    placement: str
    proposer_share: float


@dataclass(frozen=True)
class Point:
    stake: float
    proposer_share: float
    ci95: float
    eta: float
    placement: str
    n: int


def truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes"}


def finite_float(row: dict[str, str], field: str) -> float:
    try:
        value = float(row[field])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid {field!r} value: {row.get(field)!r}") from exc
    if not math.isfinite(value):
        raise ValueError(f"non-finite {field!r} value: {row.get(field)!r}")
    return value


def proposer_bound(stake: float, eta: float) -> float:
    """U(a, eta) = a(1 + eta) / (1 + a eta)."""
    return stake * (1.0 + eta) / (1.0 + stake * eta)


def read_runs(path: Path) -> list[Run]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = REQUIRED_FIELDS.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path} is missing required fields: {sorted(missing)}")
        rows = list(reader)

    selected: list[Run] = []
    for row in rows:
        if row["experiment"] != "proposer_influence_envelope":
            continue
        if row["status"] != "ok" or not truthy(row["complete"]) or not truthy(
            row["finite_metrics"]
        ):
            continue
        placement = row["adversary_placement"]
        if placement not in PLACEMENT_MARKERS:
            raise ValueError(f"unknown coalition placement: {placement!r}")
        run = Run(
            seed_index=row["seed_index"],
            target_stake=finite_float(row, "adversary_stake_fraction"),
            stake=finite_float(row, "adversary_real_stake_share_mean"),
            eta=finite_float(row, "eta"),
            placement=placement,
            proposer_share=finite_float(row, "adversary_proposer_weight_share_mean"),
        )
        if not 0.0 <= run.stake <= 1.0:
            raise ValueError(f"coalition normalized stake is outside [0, 1]: {run.stake}")
        if not 0.0 <= run.proposer_share <= 1.0:
            raise ValueError(
                f"coalition normalized proposer share is outside [0, 1]: {run.proposer_share}"
            )
        selected.append(run)

    if not selected:
        raise ValueError(f"no complete proposer_influence_envelope runs found in {path}")
    return selected


def grouped_points(runs: Iterable[Run]) -> list[Point]:
    groups: dict[tuple[float, float, str], list[Run]] = defaultdict(list)
    for run in runs:
        # target_stake identifies the frozen experimental scenario; the plotted
        # x value and analytical bound use each run's realized normalized stake.
        groups[(run.target_stake, run.eta, run.placement)].append(run)

    points: list[Point] = []
    for (_, eta, placement), group in sorted(groups.items()):
        if len(group) != EXPECTED_GROUP_SIZE:
            raise ValueError(
                f"expected {EXPECTED_GROUP_SIZE} seeds for eta={eta:g}, "
                f"placement={placement}, target_stake={group[0].target_stake:g}; "
                f"found {len(group)}"
            )
        seed_indices = {run.seed_index for run in group}
        if len(seed_indices) != len(group):
            raise ValueError(
                f"duplicate seed indices for eta={eta:g}, placement={placement}, "
                f"target_stake={group[0].target_stake:g}"
            )
        shares = [run.proposer_share for run in group]
        ci95 = T_975_DF19 * statistics.stdev(shares) / math.sqrt(len(shares))
        points.append(
            Point(
                stake=statistics.mean(run.stake for run in group),
                proposer_share=statistics.mean(shares),
                ci95=ci95,
                eta=eta,
                placement=placement,
                n=len(group),
            )
        )
    return points


def configure_style() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 8.5,
            "axes.labelsize": 8.5,
            "legend.fontsize": 6.4,
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


def render(points: list[Point], pdf: Path, png: Path) -> None:
    configure_style()
    etas = sorted({point.eta for point in points})
    if set(etas) != EXPECTED_ETAS:
        raise ValueError(
            f"expected eta values {sorted(EXPECTED_ETAS)}; found {etas}"
        )
    unknown_etas = [eta for eta in etas if eta not in ETA_COLORS]
    if unknown_etas:
        raise ValueError(f"no repository-style color configured for eta={unknown_etas}")

    # Match the repository's standard single-panel paper figure proportions.
    fig, ax = plt.subplots(figsize=(3.45, 2.55))

    # Threshold references are drawn first and kept visually subordinate.
    ax.axvline(1.0 / 3.0, color=LIGHT_GRAY, linestyle="--", linewidth=0.9, zorder=0)
    ax.axhline(0.5, color=LIGHT_GRAY, linestyle="--", linewidth=0.9, zorder=0)
    ax.grid(axis="y", color="#E6E6E6", linewidth=0.7, zorder=0)

    x_min = 0.04
    x_max = 0.345
    curve_max = 1.0 / 3.0
    curve_x = [x_min + (curve_max - x_min) * index / 240 for index in range(241)]
    for eta in etas:
        color = ETA_COLORS[eta]
        ax.plot(
            curve_x,
            [proposer_bound(stake, eta) for stake in curve_x],
            color=color,
            linewidth=1.25,
            zorder=1,
        )
        for placement, (marker, _) in PLACEMENT_MARKERS.items():
            selected = sorted(
                (
                    point
                    for point in points
                    if point.eta == eta and point.placement == placement
                ),
                key=lambda point: point.stake,
            )
            ax.errorbar(
                [point.stake for point in selected],
                [point.proposer_share for point in selected],
                yerr=[point.ci95 for point in selected],
                color=color,
                marker=marker,
                markerfacecolor="white",
                markeredgecolor=color,
                markeredgewidth=0.9,
                linestyle="none",
                markersize=4.5,
                elinewidth=0.9,
                capsize=2.2,
                zorder=3,
            )

    ax.set_xlim(x_min, x_max)
    ax.set_ylim(0.04, 0.52)
    ax.set_xticks(
        [0.05, 0.1, 0.2, 0.3, 1.0 / 3.0],
        ["0.05", "0.1", "0.2", "0.3", r"$1/3$"],
    )
    ax.set_yticks([0.1, 0.2, 0.3, 0.4, 0.5])
    ax.set_xlabel("Coalition stake", fontsize=9.5)
    ax.set_ylabel("Proposer share", fontsize=9.5)
    ax.tick_params(direction="out", length=3)

    eta_handles = [
        Line2D(
            [],
            [],
            color=ETA_COLORS[eta],
            linewidth=1.25,
            label=fr"$\eta={eta:g}$",
        )
        for eta in etas
    ]
    placement_handles = [
        Line2D(
            [],
            [],
            color=GRAY,
            marker=marker,
            markerfacecolor="white",
            markeredgewidth=0.9,
            linestyle="none",
            markersize=4.7,
            label=label,
        )
        for marker, label in PLACEMENT_MARKERS.values()
    ]
    ax.legend(
        handles=eta_handles + placement_handles,
        frameon=True,
        framealpha=0.92,
        facecolor="white",
        edgecolor="#D0D0D0",
        ncol=2,
        loc="upper left",
        borderpad=0.25,
        columnspacing=0.6,
        handlelength=1.35,
        handletextpad=0.32,
        labelspacing=0.22,
        fontsize=7.0,
    )

    fig.subplots_adjust(bottom=0.18, left=0.155, right=0.97, top=0.97)
    pdf.parent.mkdir(parents=True, exist_ok=True)
    png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(pdf, facecolor="white")
    fig.savefig(png, dpi=300, facecolor="white")
    plt.close(fig)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    parser.add_argument("--png", type=Path, default=DEFAULT_PNG)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    runs = read_runs(args.input)
    if len(runs) != EXPECTED_TOTAL_RUNS:
        raise ValueError(
            f"expected {EXPECTED_TOTAL_RUNS} complete runs; found {len(runs)}"
        )
    run_keys = {
        (run.target_stake, run.eta, run.placement, run.seed_index) for run in runs
    }
    if len(run_keys) != len(runs):
        raise ValueError("duplicate (target stake, eta, placement, seed) run keys")
    for eta in EXPECTED_ETAS:
        eta_count = sum(run.eta == eta for run in runs)
        if eta_count != EXPECTED_RUNS_PER_ETA:
            raise ValueError(
                f"expected {EXPECTED_RUNS_PER_ETA} runs for eta={eta:g}; "
                f"found {eta_count}"
            )
    points = grouped_points(runs)
    render(points, args.pdf, args.png)

    evaluated = [
        (
            run.proposer_share,
            run.proposer_share - proposer_bound(run.stake, run.eta),
        )
        for run in runs
    ]
    maximum_share = max(share for share, _ in evaluated)
    maximum_excess = max(excess for _, excess in evaluated)
    violations = sum(excess > 0.0 for _, excess in evaluated)
    print(f"input={args.input}")
    print(f"runs={len(runs)} groups={len(points)} seeds_per_group={EXPECTED_GROUP_SIZE}")
    print(f"maximum_observed_proposer_share={maximum_share:.12g}")
    print(f"maximum_observed_minus_bound={maximum_excess:.12g}")
    print(f"bound_violations={violations}")
    print(f"pdf={args.pdf}")
    print(f"png={args.png}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
