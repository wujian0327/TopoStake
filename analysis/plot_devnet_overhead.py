#!/usr/bin/env python3
"""Plot devnet overhead figures from Kurtosis workload summaries."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Dict, List, Tuple

from plot_common import FIGURES, ROOT


RAW = ROOT / "results" / "raw" / "devnet_overhead"
MAX_LOAD_SWEEP_TPS = 120.0
Series = Dict[str, List[Tuple[float, float]]]
os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")


def load_summary(path: Path) -> dict:
    return json.loads(path.read_text())


def percentile(values: List[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = (len(ordered) - 1) * pct / 100.0
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    if lower == upper:
        return ordered[lower]
    weight = index - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def true_inclusion_delays(workload: dict) -> List[float]:
    delays = []
    for tx in workload.get("txs", []):
        if tx.get("status") != 1:
            continue
        if "included_block_timestamp" not in tx or "send_unix" not in tx:
            continue
        delays.append(max(0.0, float(tx["included_block_timestamp"]) - float(tx["send_unix"])))
    return delays


def p95_inclusion_delay_seconds(workload: dict) -> float:
    delays = true_inclusion_delays(workload)
    if delays:
        return percentile(delays, 95)
    return float(workload["inclusion_delay_seconds"]["p95"])


def seconds_per_slot(workload: dict) -> float:
    return float(workload.get("seconds_per_slot", 3.0))


def tx_per_slot(workload: dict) -> float:
    return float(workload["inclusion_throughput_tps"]) * seconds_per_slot(workload)


def protocol_label(run_id: str) -> str:
    if run_id.startswith("overhead-baseline-"):
        return "PoS-Beacon"
    if run_id.startswith("overhead-topostake-"):
        return "TopoStake"
    return run_id


def load_sweep_series(metric: str) -> Series:
    selected: Dict[str, Dict[float, Tuple[float, bool]]] = {"PoS-Beacon": {}, "TopoStake": {}}
    pattern = re.compile(r"^overhead-(baseline|topostake)-8node-ba-load(\d+)-180s-seed0(?:-rerun)?$")
    for summary in sorted(RAW.glob("overhead-*-8node-ba-load*-180s-seed0*/summary.json")):
        run_id = summary.parent.name
        match = pattern.match(run_id)
        if not match:
            continue
        offered_load_tps = float(match.group(2))
        if offered_load_tps > MAX_LOAD_SWEEP_TPS:
            continue
        data = load_summary(summary)
        workload = data["workload"]
        label = protocol_label(run_id)
        if metric == "throughput":
            value = float(workload["inclusion_throughput_tps"])
        elif metric == "throughput_ratio":
            value = 100.0 * float(workload["inclusion_throughput_tps"]) / offered_load_tps
        elif metric == "tx_per_slot":
            value = tx_per_slot(workload)
        elif metric == "p95_delay":
            value = p95_inclusion_delay_seconds(workload)
        else:
            raise ValueError(metric)
        x_value = offered_load_tps * seconds_per_slot(workload)
        is_rerun = run_id.endswith("-rerun")
        previous = selected[label].get(x_value)
        if previous is None or (is_rerun and not previous[1]):
            selected[label][x_value] = (value, is_rerun)
    series: Series = {
        label: [(x, value) for x, (value, _is_rerun) in points.items()]
        for label, points in selected.items()
    }
    for points in series.values():
        points.sort(key=lambda item: item[0])
    return {label: points for label, points in series.items() if points}


def node_sweep_series(metric: str) -> Series:
    selected: Dict[str, Dict[float, Tuple[float, bool]]] = {"PoS-Beacon": {}, "TopoStake": {}}
    pattern = re.compile(r"^overhead-(baseline|topostake)-(\d+)node-ba-load60-180s-seed0(?:-rerun)?$")
    for summary in sorted(RAW.glob("overhead-*-*node-ba-load60-180s-seed0*/summary.json")):
        run_id = summary.parent.name
        match = pattern.match(run_id)
        if not match:
            continue
        nodes = float(match.group(2))
        data = load_summary(summary)
        workload = data["workload"]
        label = protocol_label(run_id)
        if metric == "throughput":
            value = float(workload["inclusion_throughput_tps"])
        elif metric == "throughput_ratio":
            value = 100.0 * float(workload["inclusion_throughput_tps"]) / 60.0
        elif metric == "tx_per_slot":
            value = tx_per_slot(workload)
        elif metric == "p95_delay":
            value = p95_inclusion_delay_seconds(workload)
        else:
            raise ValueError(metric)
        is_rerun = run_id.endswith("-rerun")
        previous = selected[label].get(nodes)
        if previous is None or (is_rerun and not previous[1]):
            selected[label][nodes] = (value, is_rerun)
    series: Series = {
        label: [(x, value) for x, (value, _is_rerun) in points.items()]
        for label, points in selected.items()
    }
    for points in series.values():
        points.sort(key=lambda item: item[0])
    return {label: points for label, points in series.items() if points}


def write_line_pdf(
    path: Path,
    xlabel: str,
    ylabel: str,
    series: Series,
    xticks: List[float],
    ymin: float | None = None,
    y_top_padding: float = 0.08,
) -> bool:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print(f"warning: matplotlib is not available; skipped {path}")
        return False

    if not series:
        print(f"warning: no data available; skipped {path}")
        return False
    distinct_x = {point[0] for points in series.values() for point in points}
    if len(distinct_x) < 2:
        print(f"warning: fewer than two x-values; skipped {path}")
        return False

    colors = {"PoS-Beacon": "#2ca02c", "TopoStake": "#1f77b4"}
    markers = {"PoS-Beacon": "o", "TopoStake": "s"}
    linestyles = {"PoS-Beacon": "--", "TopoStake": "-"}

    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(4.8, 3.2))
    for label in ["PoS-Beacon", "TopoStake"]:
        points = series.get(label, [])
        if not points:
            continue
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        ax.plot(
            xs,
            ys,
            marker=markers[label],
            linewidth=1.8,
            markersize=5.5,
            linestyle=linestyles[label],
            color=colors[label],
            label=label,
        )

    ax.set_xlabel(xlabel, fontsize=15)
    ax.set_ylabel(ylabel, fontsize=15)
    ax.set_xticks(xticks)
    all_y = [point[1] for points in series.values() for point in points]
    if ymin is not None and all_y:
        ymax = max(all_y)
        span = max(ymax - ymin, 1.0)
        ax.set_ylim(bottom=ymin, top=ymax + span * y_top_padding)
    ax.tick_params(axis="both", labelsize=13)
    ax.grid(True, alpha=0.25)
    ax.legend(frameon=False, fontsize=13)
    fig.subplots_adjust(left=0.16, right=0.98, top=0.98, bottom=0.17, hspace=0.06)
    fig.savefig(path)
    fig.savefig(path.with_suffix(".png"), dpi=300)
    plt.close(fig)
    print(f"wrote {path}")
    print(f"wrote {path.with_suffix('.png')}")
    return True


def write_broken_y_line_pdf(
    path: Path,
    xlabel: str,
    ylabel: str,
    series: Series,
    xticks: List[float],
    lower_ylim: Tuple[float, float],
    upper_ylim: Tuple[float, float],
) -> bool:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print(f"warning: matplotlib is not available; skipped {path}")
        return False

    if not series:
        print(f"warning: no data available; skipped {path}")
        return False
    distinct_x = {point[0] for points in series.values() for point in points}
    if len(distinct_x) < 2:
        print(f"warning: fewer than two x-values; skipped {path}")
        return False

    colors = {"PoS-Beacon": "#2ca02c", "TopoStake": "#1f77b4"}
    markers = {"PoS-Beacon": "o", "TopoStake": "s"}
    linestyles = {"PoS-Beacon": "--", "TopoStake": "-"}

    path.parent.mkdir(parents=True, exist_ok=True)
    fig, (ax_top, ax_bottom) = plt.subplots(
        2,
        1,
        sharex=True,
        figsize=(4.8, 3.35),
        gridspec_kw={"height_ratios": [4.2, 1.0], "hspace": 0.05},
    )
    for ax in (ax_top, ax_bottom):
        for label in ["PoS-Beacon", "TopoStake"]:
            points = series.get(label, [])
            if not points:
                continue
            xs = [point[0] for point in points]
            ys = [point[1] for point in points]
            ax.plot(
                xs,
                ys,
                marker=markers[label],
                linewidth=1.8,
                markersize=5.5,
                linestyle=linestyles[label],
                color=colors[label],
                label=label,
            )
        ax.grid(True, alpha=0.25)
        ax.tick_params(axis="both", labelsize=13)

    ax_top.set_ylim(*upper_ylim)
    ax_bottom.set_ylim(*lower_ylim)
    ax_bottom.set_xticks(xticks)
    ax_bottom.set_xlabel(xlabel, fontsize=15)
    fig.text(0.035, 0.59, ylabel, va="center", rotation="vertical", fontsize=15)
    ax_top.legend(frameon=False, fontsize=13, loc="lower left")

    ax_top.spines["bottom"].set_visible(False)
    ax_bottom.spines["top"].set_visible(False)
    ax_top.tick_params(labeltop=False, bottom=False)
    ax_bottom.xaxis.tick_bottom()
    ax_top.set_yticks([80, 85, 90, 95, 100])
    ax_bottom.set_yticks([0])

    d = 0.012
    kwargs = dict(transform=ax_top.transAxes, color="k", clip_on=False, linewidth=1.0)
    ax_top.plot((-d, +d), (-d, +d), **kwargs)
    ax_top.plot((1 - d, 1 + d), (-d, +d), **kwargs)
    kwargs.update(transform=ax_bottom.transAxes)
    ax_bottom.plot((-d, +d), (1 - d, 1 + d), **kwargs)
    ax_bottom.plot((1 - d, 1 + d), (1 - d, 1 + d), **kwargs)

    fig.subplots_adjust(left=0.16, right=0.98, top=0.98, bottom=0.17, hspace=0.06)
    fig.savefig(path)
    fig.savefig(path.with_suffix(".png"), dpi=300)
    plt.close(fig)
    print(f"wrote {path}")
    print(f"wrote {path.with_suffix('.png')}")
    return True


def main() -> int:
    load_tps = load_sweep_series("tx_per_slot")
    load_delay = load_sweep_series("p95_delay")
    node_tps = node_sweep_series("tx_per_slot")
    node_delay = node_sweep_series("p95_delay")

    write_line_pdf(
        FIGURES / "devnet_tps_load.pdf",
        "Offered load (tx/slot)",
        "Achieved tx/slot",
        load_tps,
        [60, 120, 180, 240, 300, 360],
        ymin=0.0,
    )
    write_line_pdf(
        FIGURES / "devnet_delay_load.pdf",
        "Offered load (tx/slot)",
        "p95 delay (s)",
        load_delay,
        [60, 120, 180, 240, 300, 360],
        ymin=0.0,
    )
    write_line_pdf(
        FIGURES / "devnet_tps_nodes.pdf",
        "Number of nodes",
        "Achieved tx/slot",
        node_tps,
        sorted({point[0] for points in node_tps.values() for point in points}),
        ymin=0.0,
    )
    write_line_pdf(
        FIGURES / "devnet_delay_nodes.pdf",
        "Number of nodes",
        "p95 delay (s)",
        node_delay,
        sorted({point[0] for points in node_delay.values() for point in points}),
        ymin=0.0,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
