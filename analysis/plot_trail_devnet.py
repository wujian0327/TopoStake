#!/usr/bin/env python3
"""Render TRAIL real-client performance panels from the frozen 75-run devnet sweep."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

os.environ.setdefault("MPLCONFIGDIR", "/tmp/trail-matplotlib")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.stats import t as student_t


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments"))

from run_frozen_devnet_experiments import summarize_resources  # noqa: E402


DEFAULT_INPUT = ROOT / "results" / "raw" / "frozen_v1_devnet_main"
DEFAULT_OUTPUT = ROOT / "figures" / "trail_devnet"
DEFAULT_TABLE = DEFAULT_OUTPUT / "trail_devnet_high_load_table.tex"

VARIANTS = ("baseline", "pathobs", "fee_only", "bonus_only", "topostake")
SELECTED_VARIANTS = ("baseline", "topostake")
LOADS = (8, 32, 64)
SEEDS = frozenset(range(5))
OFFERED_LOADS = {8: 8.0 / 3.0, 32: 32.0 / 3.0, 64: 64.0 / 3.0}
RUN_RE = re.compile(
    r"^(baseline|pathobs|fee_only|bonus_only|topostake)_ba_n8_load(8|32|64)_seed([0-4])$"
)

GRAY = "#666666"
ORANGE = "#D55E00"
LIGHT_GRAY = "#B8B8B8"


@dataclass(frozen=True)
class Run:
    variant: str
    load_tx_per_slot: int
    seed: int
    run_dir: Path
    summary: dict[str, Any]


@dataclass(frozen=True)
class Point:
    offered_load: float
    mean: float
    ci95: float


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def percentile(values: list[float], pct: float) -> float:
    if not values:
        raise ValueError("cannot compute a percentile of an empty sample")
    ordered = sorted(values)
    rank = pct / 100.0 * (len(ordered) - 1)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    fraction = rank - low
    return ordered[low] * (1.0 - fraction) + ordered[high] * fraction


def finite_scalars(value: Any) -> bool:
    if isinstance(value, dict):
        return all(finite_scalars(item) for item in value.values())
    if isinstance(value, list):
        return all(finite_scalars(item) for item in value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return math.isfinite(float(value))
    return True


def load_runs(input_dir: Path) -> list[Run]:
    runs: list[Run] = []
    for run_dir in sorted(path for path in input_dir.iterdir() if path.is_dir()):
        match = RUN_RE.fullmatch(run_dir.name)
        if match is None:
            raise ValueError(f"unexpected run directory: {run_dir}")
        variant, load, seed = match.groups()
        summary = read_json(run_dir / "summary.json")
        status = read_json(run_dir / "runner_status.json")
        acceptance = read_json(run_dir / "acceptance.json")
        formal = summary.get("formal_experiment", {})
        if status.get("status") != "ok" or status.get("error") not in (None, ""):
            raise ValueError(f"failed run: {run_dir}")
        if not acceptance.get("passed") or not formal.get("acceptance", {}).get("passed"):
            raise ValueError(f"acceptance failure: {run_dir}")
        if not formal.get("measurement_quality", {}).get("passed"):
            raise ValueError(f"measurement-quality failure: {run_dir}")
        if not finite_scalars(summary):
            raise ValueError(f"non-finite raw metric: {run_dir}")
        runs.append(
            Run(
                variant=variant,
                load_tx_per_slot=int(load),
                seed=int(seed),
                run_dir=run_dir,
                summary=summary,
            )
        )

    if len(runs) != 75:
        raise ValueError(f"expected 75 formal devnet runs; found {len(runs)}")
    keys = [(run.variant, run.load_tx_per_slot, run.seed) for run in runs]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate (variant, load, seed) run")
    for variant in VARIANTS:
        for load in LOADS:
            seeds = {
                run.seed
                for run in runs
                if run.variant == variant and run.load_tx_per_slot == load
            }
            if seeds != SEEDS:
                raise ValueError(
                    f"seed mismatch for variant={variant}, load={load}: {sorted(seeds)}"
                )
    commits = {
        str(run.summary.get("build_provenance", {}).get("source_commit"))
        for run in runs
    }
    if commits != {"503d60471d86daea5b7ea42170dc5964e93cb9fa"}:
        raise ValueError(f"unexpected source revisions: {sorted(commits)}")
    return runs


def inclusion_throughput(run: Run) -> float:
    workload = run.summary["workload"]
    txs = workload["txs"]
    included = [tx for tx in txs if int(tx.get("status", 0)) == 1]
    if len(included) != int(workload["tx_count"]):
        raise ValueError(f"not every measurement transaction was included: {run.run_dir}")
    elapsed = max(float(tx["included_block_timestamp"]) for tx in included) - min(
        float(tx["send_unix"]) for tx in txs
    )
    value = len(included) / elapsed
    if not math.isclose(
        value,
        float(workload["inclusion_throughput_tps"]),
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise ValueError(f"throughput recomputation mismatch: {run.run_dir}")
    return value


def p95_inclusion_time(run: Run) -> float:
    values = [
        float(tx["inclusion_delay_seconds"])
        for tx in run.summary["workload"]["txs"]
        if int(tx.get("status", 0)) == 1
    ]
    value = percentile(values, 95.0)
    recorded = float(run.summary["workload"]["inclusion_delay_seconds"]["p95"])
    if not math.isclose(value, recorded, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError(f"p95 recomputation mismatch: {run.run_dir}")
    return value


Metric = Callable[[Run], float]


def summarize(runs: list[Run], metric: Metric) -> dict[str, list[Point]]:
    grouped: dict[tuple[str, int], list[float]] = defaultdict(list)
    for run in runs:
        if run.variant in SELECTED_VARIANTS:
            grouped[(run.variant, run.load_tx_per_slot)].append(metric(run))
    result: dict[str, list[Point]] = {}
    for variant in SELECTED_VARIANTS:
        points: list[Point] = []
        for load in LOADS:
            values = grouped[(variant, load)]
            if len(values) != 5 or not all(math.isfinite(value) for value in values):
                raise ValueError(f"expected five finite values for {variant}, load={load}")
            critical = float(student_t.ppf(0.975, df=len(values) - 1))
            points.append(
                Point(
                    offered_load=OFFERED_LOADS[load],
                    mean=statistics.mean(values),
                    ci95=critical * statistics.stdev(values) / math.sqrt(len(values)),
                )
            )
        result[variant] = points
    return result


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


def decorate(axis: Any) -> None:
    axis.grid(axis="y", color="#E6E6E6", linewidth=0.7, zorder=0)
    axis.spines["left"].set_linewidth(0.9)
    axis.spines["bottom"].set_linewidth(0.9)
    axis.tick_params(width=0.8, length=3)
    axis.legend(
        frameon=True,
        framealpha=0.92,
        facecolor="white",
        edgecolor="#D0D0D0",
        borderpad=0.35,
        handletextpad=0.5,
    )


def save(fig: Any, output_dir: Path, stem: str) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    pdf = output_dir / f"{stem}.pdf"
    png = output_dir / f"{stem}.png"
    fig.savefig(pdf, facecolor="white")
    fig.savefig(png, dpi=300, facecolor="white")
    plt.close(fig)
    return pdf, png


def plot_metric(
    points: dict[str, list[Point]],
    output_dir: Path,
    *,
    ylabel: str,
    stem: str,
    offered_reference: bool,
) -> tuple[Path, Path]:
    fig, axis = plt.subplots(figsize=(3.45, 2.55))
    if offered_reference:
        axis.plot(
            [0.0, 23.0],
            [0.0, 23.0],
            color=LIGHT_GRAY,
            linestyle="--",
            linewidth=1.0,
            label="Offered load",
            zorder=1,
        )
    styles = {
        "baseline": {
            "label": "Ethereum PoS",
            "color": GRAY,
            "linestyle": "--",
            "marker": "^",
            "markerfacecolor": "white",
        },
        "topostake": {
            "label": "Full TRAIL",
            "color": ORANGE,
            "linestyle": "-",
            "marker": "o",
            "markerfacecolor": ORANGE,
        },
    }
    for variant in SELECTED_VARIANTS:
        style = styles[variant]
        series = points[variant]
        axis.errorbar(
            [point.offered_load for point in series],
            [point.mean for point in series],
            yerr=[point.ci95 for point in series],
            color=style["color"],
            linestyle=style["linestyle"],
            marker=style["marker"],
            markerfacecolor=style["markerfacecolor"],
            markeredgecolor=style["color"],
            markeredgewidth=1.0,
            linewidth=1.2,
            markersize=4.7,
            capsize=2.5,
            label=style["label"],
            zorder=3,
        )
    ticks = [OFFERED_LOADS[load] for load in LOADS]
    axis.set_xticks(ticks, ["2.667", "10.667", "21.333"])
    axis.set_xlim(0.0, 23.0)
    axis.set_ylim(bottom=0.0, top=23.0 if offered_reference else 6.0)
    axis.set_xlabel("Offered load (tx/s)")
    axis.set_ylabel(ylabel)
    decorate(axis)
    fig.subplots_adjust(left=0.18, right=0.97, bottom=0.20, top=0.97)
    return save(fig, output_dir, stem)


def resource_value(run: Run, field: str) -> float:
    resources = summarize_resources(run.run_dir / "resources.jsonl")
    if resources.get("node_count") != 8:
        raise ValueError(f"expected eight complete EL/CL node streams: {run.run_dir}")
    return float(resources[field])


def high_load_table(runs: list[Run], path: Path) -> dict[str, tuple[float | None, float]]:
    selected = {
        variant: [
            run
            for run in runs
            if run.variant == variant and run.load_tx_per_slot == 64
        ]
        for variant in SELECTED_VARIANTS
    }
    if any(len(values) != 5 for values in selected.values()):
        raise ValueError("high-load table requires five PoS and five Full TRAIL runs")

    def mean_for(variant: str, metric: Callable[[Run], float]) -> float:
        values = [metric(run) for run in selected[variant]]
        if not all(math.isfinite(value) for value in values):
            raise ValueError(f"non-finite high-load table value for {variant}")
        return statistics.mean(values)

    metrics: list[tuple[str, Callable[[Run], float], int]] = [
        ("CPU/node (\\%)", lambda run: resource_value(run, "per_node_cpu_mean_percent"), 3),
        (
            "Peak memory/node (MiB)",
            lambda run: resource_value(run, "per_node_memory_peak_mean_bytes") / 1048576.0,
            2,
        ),
        (
            "Network/node (MiB/run)",
            lambda run: (
                resource_value(run, "per_node_network_rx_delta_mean_bytes")
                + resource_value(run, "per_node_network_tx_delta_mean_bytes")
            )
            / 1048576.0,
            2,
        ),
        (
            "Mean block size (KiB)",
            lambda run: statistics.mean(
                float(sample["bytes"])
                for sample in run.summary["formal_experiment"]["block_sizes"]["samples"]
            )
            / 1024.0,
            3,
        ),
    ]
    values: dict[str, tuple[float | None, float]] = {}
    rows: list[str] = []
    for label, metric, decimals in metrics:
        pos = mean_for("baseline", metric)
        trail = mean_for("topostake", metric)
        values[label] = (pos, trail)
        rows.append(f"{label} & {pos:.{decimals}f} & {trail:.{decimals}f} \\\\")
    verification = mean_for(
        "topostake",
        lambda run: 1000.0
        * float(
            run.summary["formal_experiment"]["prometheus"][
                "evidence_verify_p95_seconds"
            ]
        ),
    )
    values["p95 verification (ms)"] = (None, verification)
    rows.append(f"p95 verification (ms) & -- & {verification:.3f} \\\\")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\\begin{tabular}{lrr}\n"
        "\\toprule\n"
        "Metric & PoS & Full TRAIL \\\\\n"
        "\\midrule\n"
        + "\n".join(rows)
        + "\n\\bottomrule\n"
        "\\end{tabular}\n",
        encoding="utf-8",
    )
    return values


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--table", type=Path, default=DEFAULT_TABLE)
    args = parser.parse_args()

    runs = load_runs(args.input_dir)
    configure_style()
    outputs = [
        *plot_metric(
            summarize(runs, inclusion_throughput),
            args.output_dir,
            ylabel="Inclusion throughput (tx/s)",
            stem="trail_devnet_throughput",
            offered_reference=True,
        ),
        *plot_metric(
            summarize(runs, p95_inclusion_time),
            args.output_dir,
            ylabel="p95 inclusion time (s)",
            stem="trail_devnet_latency",
            offered_reference=False,
        ),
    ]
    table = high_load_table(runs, args.table)
    print(f"Validated {len(runs)} raw runs and wrote:")
    for output in outputs:
        print(output)
    print(args.table)
    print(json.dumps(table, indent=2))


if __name__ == "__main__":
    main()
