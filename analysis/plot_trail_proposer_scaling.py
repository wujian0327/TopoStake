#!/usr/bin/env python3
"""Plot TRAIL proposer-bound utilization across validator-set sizes.

The script reads the frozen per-validator, per-epoch simulator output.  For
each run it recomputes the realized coalition stake and normalized coalition
proposer-weight share, then evaluates

    U(a, eta) = a(1 + eta) / (1 + a eta)
    rho       = f_A^W / U(a, eta).

Legacy score-dependent bounds, envelope-utilization columns, and sampled
proposer-election frequencies are intentionally not used.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import statistics
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/trail-matplotlib")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = (
    ROOT / "results" / "raw" / "frozen_v1_security_main" / "proposer_envelope_scale"
)
DEFAULT_OUTPUT = ROOT / "figures" / "trail_security"

EXPECTED_NETWORK_SIZES = {100, 250, 500}
EXPECTED_PLACEMENTS = {"random", "high-degree", "high-betweenness"}
EXPECTED_SEEDS = set(range(20))
EXPECTED_TX_RATE = 5
EXPECTED_TARGET_STAKE = 0.2
EXPECTED_ETA = 1.0
EXPECTED_TOTAL_RUNS = 180
T_975_DF19 = 2.093024054408263

BLUE = "#0072B2"
ORANGE = "#D55E00"
GREEN = "#009E73"
GRAY = "#666666"

PLACEMENT_STYLE = {
    "random": (BLUE, "o", "Random"),
    "high-degree": (ORANGE, "s", "High degree"),
    "high-betweenness": (GREEN, "^", "High betweenness"),
}


@dataclass(frozen=True)
class Run:
    network_size: int
    placement: str
    seed: int
    actual_stake: float
    proposer_share: float
    ratio: float


@dataclass(frozen=True)
class Point:
    network_size: int
    placement: str
    mean: float
    ci95: float
    n: int


def read_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def truthy(value: str | None) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def analytical_bound(stake: float, eta: float) -> float:
    return stake * (1.0 + eta) / (1.0 + stake * eta)


def close(actual: float, expected: float, *, tolerance: float = 2e-6) -> bool:
    return math.isclose(actual, expected, rel_tol=0.0, abs_tol=tolerance)


def recompute_run(run_dir: Path, metadata: dict) -> tuple[float, float]:
    warmup = int(metadata.get("warmup_epochs", 0))
    by_epoch: dict[int, list[dict[str, str]]] = defaultdict(list)
    node_path = run_dir / "node_epoch_metrics.csv"
    with node_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            epoch = int(row["epoch"])
            if epoch >= warmup:
                by_epoch[epoch].append(row)
    if not by_epoch:
        raise ValueError(f"no usable node rows after warmup in {node_path}")

    stakes: list[float] = []
    shares: list[float] = []
    for epoch, rows in sorted(by_epoch.items()):
        total_stake = sum(float(row["economic_stake"]) for row in rows)
        coalition_stake = sum(
            float(row["economic_stake"])
            for row in rows
            if truthy(row["adversarial"])
        )
        total_weight = sum(float(row["normalized_proposer_weight"]) for row in rows)
        coalition_weight = sum(
            float(row["normalized_proposer_weight"])
            for row in rows
            if truthy(row["adversarial"])
        )
        if total_stake <= 0.0 or total_weight <= 0.0:
            raise ValueError(f"non-positive denominator in {run_dir}, epoch {epoch}")
        stakes.append(coalition_stake / total_stake)
        shares.append(coalition_weight / total_weight)

    actual_stake = statistics.mean(stakes)
    proposer_share = statistics.mean(shares)
    if not all(math.isfinite(value) for value in (actual_stake, proposer_share)):
        raise ValueError(f"non-finite recomputed metric in {run_dir}")

    # Cross-check the simulator's per-epoch aggregate fields without using any
    # of its legacy analytical-bound or envelope-utilization columns.
    aggregate_stakes: list[float] = []
    aggregate_shares: list[float] = []
    with (run_dir / "epoch_metrics.csv").open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if int(row["epoch"]) >= warmup:
                aggregate_stakes.append(float(row["adversary_real_stake_share"]))
                aggregate_shares.append(float(row["adversary_proposer_weight_share"]))
    if len(aggregate_stakes) != len(stakes):
        raise ValueError(f"node/epoch row-count mismatch in {run_dir}")
    if not close(actual_stake, statistics.mean(aggregate_stakes)):
        raise ValueError(f"recomputed coalition stake disagrees with epoch metrics in {run_dir}")
    if not close(proposer_share, statistics.mean(aggregate_shares)):
        raise ValueError(f"recomputed proposer weight disagrees with epoch metrics in {run_dir}")
    return actual_stake, proposer_share


def load_runs(input_dir: Path) -> tuple[list[Run], str]:
    runs: list[Run] = []
    commits: set[str] = set()
    for metadata_path in sorted(input_dir.glob("*/experiment_meta.json")):
        metadata = read_json(metadata_path)
        if metadata.get("experiment") != "proposer_envelope_scale":
            continue
        if metadata.get("tx_rate") != EXPECTED_TX_RATE:
            continue
        if int(metadata.get("node_num", -1)) not in EXPECTED_NETWORK_SIZES:
            continue
        if not close(float(metadata.get("adversary_stake_fraction", math.nan)), EXPECTED_TARGET_STAKE):
            continue
        if not close(float(metadata.get("eta", math.nan)), EXPECTED_ETA):
            continue
        if metadata.get("adversary_placement") not in EXPECTED_PLACEMENTS:
            continue
        if metadata.get("topology") != "ba" or metadata.get("attack_mode") != "max-score":
            continue

        run_dir = metadata_path.parent
        status = read_json(run_dir / "runner_status.json")
        if (
            status.get("status") != "ok"
            or status.get("exit_code") != 0
            or status.get("completed_epochs") != status.get("expected_epochs")
        ):
            raise ValueError(f"incomplete run: {run_dir}")
        config = read_json(run_dir / "run_config.json")
        commits.add(str(config.get("git_commit_sha", "unknown")))

        actual_stake, proposer_share = recompute_run(run_dir, metadata)
        bound = analytical_bound(actual_stake, float(metadata["eta"]))
        ratio = proposer_share / bound
        if not math.isfinite(ratio):
            raise ValueError(f"non-finite ratio in {run_dir}")
        runs.append(
            Run(
                network_size=int(metadata["node_num"]),
                placement=str(metadata["adversary_placement"]),
                seed=int(metadata["seed_index"]),
                actual_stake=actual_stake,
                proposer_share=proposer_share,
                ratio=ratio,
            )
        )

    if len(runs) != EXPECTED_TOTAL_RUNS:
        raise ValueError(f"expected {EXPECTED_TOTAL_RUNS} selected runs; found {len(runs)}")
    if len(commits) != 1:
        raise ValueError(f"selected runs contain multiple code revisions: {sorted(commits)}")

    keys = [(run.network_size, run.placement, run.seed) for run in runs]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate (network size, placement, seed) conditions")
    for network_size in sorted(EXPECTED_NETWORK_SIZES):
        for placement in sorted(EXPECTED_PLACEMENTS):
            seeds = {
                run.seed
                for run in runs
                if run.network_size == network_size and run.placement == placement
            }
            if seeds != EXPECTED_SEEDS:
                raise ValueError(
                    f"seed mismatch for n={network_size}, placement={placement}: "
                    f"found {sorted(seeds)}"
                )
    return runs, next(iter(commits))


def summarize(runs: list[Run]) -> list[Point]:
    groups: dict[tuple[int, str], list[float]] = defaultdict(list)
    for run in runs:
        groups[(run.network_size, run.placement)].append(run.ratio)

    points: list[Point] = []
    for (network_size, placement), values in sorted(groups.items()):
        if len(values) != 20:
            raise ValueError(f"expected 20 ratios for n={network_size}, {placement}")
        points.append(
            Point(
                network_size=network_size,
                placement=placement,
                mean=statistics.mean(values),
                ci95=T_975_DF19 * statistics.stdev(values) / math.sqrt(len(values)),
                n=len(values),
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


def render(points: list[Point], output_dir: Path) -> tuple[Path, Path]:
    configure_style()
    fig, ax = plt.subplots(figsize=(3.45, 2.55))
    ax.grid(axis="y", color="#E6E6E6", linewidth=0.7, zorder=0)

    for placement in ("random", "high-degree", "high-betweenness"):
        selected = sorted(
            (point for point in points if point.placement == placement),
            key=lambda point: point.network_size,
        )
        color, marker, label = PLACEMENT_STYLE[placement]
        ax.errorbar(
            [point.network_size for point in selected],
            [point.mean for point in selected],
            yerr=[point.ci95 for point in selected],
            color=color,
            marker=marker,
            markerfacecolor="white",
            markeredgewidth=1.1,
            linewidth=1.2,
            markersize=4.8,
            capsize=2.5,
            label=label,
            zorder=3,
        )

    ax.axhline(
        1.0,
        color=GRAY,
        linestyle="--",
        linewidth=1.0,
        label="Analytical bound",
        zorder=1,
    )
    ax.set_xticks([100, 250, 500], ["100", "250", "500"])
    ax.set_xlabel("Validators", fontsize=9.5)
    ax.set_ylabel("Observed share / bound", fontsize=9.5)
    ax.set_ylim(0.0, 1.05)
    ax.spines["left"].set_linewidth(0.9)
    ax.spines["bottom"].set_linewidth(0.9)
    ax.tick_params(width=0.8, length=3)
    ax.legend(
        frameon=True,
        framealpha=0.9,
        facecolor="white",
        edgecolor="#D0D0D0",
        ncol=2,
        loc="lower right",
        borderpad=0.3,
        columnspacing=0.8,
        handletextpad=0.4,
        fontsize=7.0,
    )
    fig.subplots_adjust(bottom=0.18, left=0.155, right=0.97, top=0.97)

    output_dir.mkdir(parents=True, exist_ok=True)
    pdf = output_dir / "trail_proposer_scaling.pdf"
    png = output_dir / "trail_proposer_scaling.png"
    fig.savefig(pdf)
    fig.savefig(png, dpi=300)
    plt.close(fig)
    return pdf, png


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    runs, commit = load_runs(args.input_dir)
    points = summarize(runs)
    pdf, png = render(points, args.output_dir)

    print(f"selected runs: {len(runs)}")
    print(f"git commit: {commit}")
    for point in points:
        print(
            f"n={point.network_size:3d} placement={point.placement:16s} "
            f"mean={point.mean:.9f} ci95={point.ci95:.9f} runs={point.n}"
        )
    maximum = max(runs, key=lambda run: run.ratio)
    print(
        f"maximum ratio: {maximum.ratio:.9f} "
        f"(n={maximum.network_size}, placement={maximum.placement}, seed={maximum.seed})"
    )
    print(f"ratios above one: {sum(run.ratio > 1.0 for run in runs)}")
    print(f"pdf: {pdf}")
    print(f"png: {png}")


if __name__ == "__main__":
    main()
