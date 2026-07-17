#!/usr/bin/env python3
"""Render paper-ready frozen-v1 devnet figures from the formal 75-run matrix."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Iterable

os.environ.setdefault("MPLCONFIGDIR", "/tmp/topostake-matplotlib")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.axes import Axes


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "results" / "processed" / "frozen_v1_devnet_main.csv"
DEFAULT_OUTPUT = ROOT / "figures" / "frozen_v1_devnet"
DEFAULT_DATA = ROOT / "results" / "processed" / "frozen_v1_devnet_main_figure_data.csv"
DEFAULT_TABLE = ROOT / "results" / "processed" / "frozen_v1_devnet_main_table.tex"

MIB = 1024.0 * 1024.0
BASELINE = "baseline"
EVIDENCE_VARIANTS = ("pathobs", "fee_only", "bonus_only", "topostake")
EXPECTED_VARIANTS = (BASELINE, *EVIDENCE_VARIANTS)
TRUTHY = {"1", "true", "yes"}

COLORS = {
    "pathobs": "#0072B2",
    "fee_only": "#D55E00",
    "bonus_only": "#009E73",
    "topostake": "#CC79A7",
}
MARKERS = {"pathobs": "o", "fee_only": "s", "bonus_only": "^", "topostake": "D"}
LABELS = {
    "pathobs": "Path obs.",
    "fee_only": "Fee only",
    "bonus_only": "Bonus only",
    "topostake": "Full",
}
OFFSETS = {"pathobs": -0.18, "fee_only": -0.06, "bonus_only": 0.06, "topostake": 0.18}

# These four independent panels are the compact main-paper row.  The remaining
# resource and verification panels are still emitted for the table/appendix.
PRIMARY_FIGURE_STEMS = (
    "frozen_devnet_performance_a",
    "frozen_devnet_performance_b",
    "frozen_devnet_resources_a",
    "frozen_devnet_evidence_a",
)
FOUR_UP_FIGSIZE = (3.0, 2.25)

FIGURE_CONTENTS = {
    "frozen_devnet_performance_a": "paired inclusion-throughput change versus baseline",
    "frozen_devnet_performance_b": "paired p95 inclusion-latency change versus baseline",
    "frozen_devnet_resources_a": "paired aggregate CPU change versus baseline",
    "frozen_devnet_resources_b": "paired aggregate memory change versus baseline",
    "frozen_devnet_resources_c": "paired aggregate network-traffic change versus baseline",
    "frozen_devnet_evidence_a": "paired additional serialized block bytes per included transaction",
    "frozen_devnet_evidence_b": "TopoStake block-level inline-evidence verification time",
}

# Two-sided 95% Student-t critical values indexed by the number of observations.
T95 = {
    2: 12.706,
    3: 4.303,
    4: 3.182,
    5: 2.776,
    6: 2.571,
    7: 2.447,
    8: 2.365,
    9: 2.306,
    10: 2.262,
    11: 2.228,
    12: 2.201,
    13: 2.179,
    14: 2.160,
    15: 2.145,
    16: 2.131,
    17: 2.120,
    18: 2.110,
    19: 2.101,
    20: 2.093,
    21: 2.086,
    22: 2.080,
    23: 2.074,
    24: 2.069,
    25: 2.064,
    26: 2.060,
    27: 2.056,
    28: 2.052,
    29: 2.048,
    30: 2.045,
}


def truthy(value: Any) -> bool:
    return str(value).strip().lower() in TRUTHY


def numeric(row: dict[str, str], field: str) -> float:
    try:
        value = float(row[field])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"invalid {field!r} in devnet row: {row}") from error
    if not math.isfinite(value):
        raise ValueError(f"non-finite {field!r} in devnet row: {row}")
    return value


def read_runs(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise SystemExit(f"Frozen devnet CSV not found: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise SystemExit(f"Frozen devnet CSV is empty: {path}")

    rejected = [
        row.get("run_id", "unknown")
        for row in rows
        if row.get("status") != "ok"
        or not truthy(row.get("acceptance_passed"))
        or not truthy(row.get("measurement_quality_passed"))
        or str(row.get("error", "")).strip().lower() not in {"", "nan"}
    ]
    if rejected:
        raise SystemExit(
            "Devnet figures require passing protocol and measurement gates; "
            f"rejected runs={','.join(rejected[:5])}"
        )

    keys = [
        (row.get("variant"), int(numeric(row, "load_tx_per_slot")), int(numeric(row, "seed")))
        for row in rows
    ]
    if len(keys) != len(set(keys)):
        raise SystemExit("Duplicate (variant, load, seed) rows in frozen devnet CSV")
    variants = {row.get("variant") for row in rows}
    if variants != set(EXPECTED_VARIANTS):
        raise SystemExit(f"Expected variants {EXPECTED_VARIANTS}, found {sorted(variants)}")

    combinations: dict[tuple[str, int], set[int]] = defaultdict(set)
    for variant, load, seed in keys:
        combinations[(str(variant), load)].add(seed)
    seed_sets = set(tuple(sorted(seeds)) for seeds in combinations.values())
    if len(seed_sets) != 1:
        raise SystemExit("Every variant/load combination must use the same seed set")
    return rows


def t95(n: int) -> float:
    if n < 2:
        return 0.0
    if n in T95:
        return T95[n]
    return 1.96


def mean_ci95(values: Iterable[float]) -> tuple[float, float, int]:
    clean = [value for value in values if math.isfinite(value)]
    if not clean:
        return math.nan, 0.0, 0
    if len(clean) == 1:
        return clean[0], 0.0, 1
    return (
        statistics.mean(clean),
        t95(len(clean)) * statistics.stdev(clean) / math.sqrt(len(clean)),
        len(clean),
    )


def index_runs(rows: list[dict[str, str]]) -> dict[tuple[str, int, int], dict[str, str]]:
    return {
        (
            str(row["variant"]),
            int(numeric(row, "load_tx_per_slot")),
            int(numeric(row, "seed")),
        ): row
        for row in rows
    }


def bytes_per_included_tx(row: dict[str, str]) -> float:
    included = numeric(row, "success_count")
    if included <= 0.0:
        return math.nan
    return (
        numeric(row, "block_ssz_mean_bytes")
        * numeric(row, "block_ssz_count")
        / included
    )


Metric = Callable[[dict[str, str], dict[str, str]], float]


PAIRED_METRICS: dict[str, tuple[str, Metric]] = {
    "throughput_change_percent": (
        "%",
        lambda row, ref: 100.0
        * (numeric(row, "inclusion_throughput_tps") - numeric(ref, "inclusion_throughput_tps"))
        / numeric(ref, "inclusion_throughput_tps"),
    ),
    "p95_latency_change_seconds": (
        "s",
        lambda row, ref: numeric(row, "p95_inclusion_delay_seconds")
        - numeric(ref, "p95_inclusion_delay_seconds"),
    ),
    "aggregate_cpu_change_percentage_points": (
        "percentage points",
        lambda row, ref: numeric(row, "cpu_mean_percent") - numeric(ref, "cpu_mean_percent"),
    ),
    "aggregate_memory_change_mib": (
        "MiB",
        lambda row, ref: (numeric(row, "memory_max_bytes") - numeric(ref, "memory_max_bytes"))
        / MIB,
    ),
    "aggregate_network_change_mib": (
        "MiB",
        lambda row, ref: (
            numeric(row, "network_rx_delta_bytes")
            + numeric(row, "network_tx_delta_bytes")
            - numeric(ref, "network_rx_delta_bytes")
            - numeric(ref, "network_tx_delta_bytes")
        )
        / MIB,
    ),
    "additional_block_bytes_per_tx": (
        "bytes/tx",
        lambda row, ref: bytes_per_included_tx(row) - bytes_per_included_tx(ref),
    ),
}


def paired_summaries(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    indexed = index_runs(rows)
    loads = sorted({int(numeric(row, "load_tx_per_slot")) for row in rows})
    seeds = sorted({int(numeric(row, "seed")) for row in rows})
    summaries: list[dict[str, Any]] = []
    for reference, variants in [
        (BASELINE, EVIDENCE_VARIANTS),
        ("pathobs", ("fee_only", "bonus_only", "topostake")),
    ]:
        for variant in variants:
            for load in loads:
                for metric, (unit, calculate) in PAIRED_METRICS.items():
                    values = [
                        calculate(indexed[(variant, load, seed)], indexed[(reference, load, seed)])
                        for seed in seeds
                    ]
                    mean, ci, n = mean_ci95(values)
                    summaries.append(
                        {
                            "comparison": f"{variant}-vs-{reference}",
                            "reference": reference,
                            "variant": variant,
                            "load_tx_per_slot": load,
                            "metric": metric,
                            "unit": unit,
                            "n": n,
                            "mean": mean,
                            "ci95": ci,
                            "ci95_low": mean - ci,
                            "ci95_high": mean + ci,
                        }
                    )
    return summaries


def verification_summaries(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    selected = [row for row in rows if row.get("variant") == "topostake"]
    summaries: list[dict[str, Any]] = []
    for load in sorted({int(numeric(row, "load_tx_per_slot")) for row in selected}):
        at_load = [row for row in selected if int(numeric(row, "load_tx_per_slot")) == load]
        for metric, field in [
            ("evidence_verify_mean_ms", "evidence_verify_mean_seconds"),
            ("evidence_verify_p95_ms", "evidence_verify_p95_seconds"),
        ]:
            mean, ci, n = mean_ci95(numeric(row, field) * 1_000.0 for row in at_load)
            summaries.append(
                {
                    "comparison": "topostake-absolute",
                    "reference": "",
                    "variant": "topostake",
                    "load_tx_per_slot": load,
                    "metric": metric,
                    "unit": "ms",
                    "n": n,
                    "mean": mean,
                    "ci95": ci,
                    "ci95_low": mean - ci,
                    "ci95_high": mean + ci,
                }
            )
    return summaries


def configure_style() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 11.0,
            "axes.labelsize": 11.0,
            "axes.titlesize": 11.0,
            "legend.fontsize": 8.5,
            "xtick.labelsize": 9.5,
            "ytick.labelsize": 9.5,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            # Fixed canvases keep separately rendered panels aligned in LaTeX.
            "savefig.bbox": None,
        }
    )


def save_figure(fig: Any, stem: Path) -> list[Path]:
    outputs = []
    stem.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("pdf", "png"):
        output = stem.with_suffix(f".{suffix}")
        fig.savefig(output, dpi=300, facecolor="white")
        outputs.append(output)
    plt.close(fig)
    return outputs


def finish_axis(
    fig: Any,
    axis: Axes,
    loads: list[int],
    *,
    show_legend: bool,
) -> None:
    axis.set_xticks(range(len(loads)), [str(load) for load in loads])
    axis.set_xlabel("Load (tx/slot)")
    axis.grid(axis="y", color="#E6E6E6", linewidth=0.7)
    axis.axhline(0.0, color="#666666", linewidth=0.9, linestyle="--", zorder=1)
    if show_legend:
        axis.legend(
            frameon=False,
            ncol=2,
            loc="best",
            columnspacing=0.8,
            handletextpad=0.4,
        )
    fig.subplots_adjust(bottom=0.24, left=0.25, right=0.97, top=0.97)


def plot_paired_metric(
    summaries: list[dict[str, Any]],
    metric: str,
    ylabel: str,
    stem: Path,
    *,
    show_legend: bool,
) -> list[Path]:
    selected = [
        row
        for row in summaries
        if row["metric"] == metric and row["reference"] == BASELINE
    ]
    loads = sorted({int(row["load_tx_per_slot"]) for row in selected})
    fig, axis = plt.subplots(figsize=FOUR_UP_FIGSIZE)
    for variant in EVIDENCE_VARIANTS:
        by_load = {int(row["load_tx_per_slot"]): row for row in selected if row["variant"] == variant}
        x = [index + OFFSETS[variant] for index in range(len(loads))]
        axis.errorbar(
            x,
            [float(by_load[load]["mean"]) for load in loads],
            yerr=[float(by_load[load]["ci95"]) for load in loads],
            color=COLORS[variant],
            marker=MARKERS[variant],
            linestyle="none",
            markersize=4.5,
            capsize=2.5,
            linewidth=1.1,
            label=LABELS[variant],
        )
    axis.set_ylabel(ylabel)
    finish_axis(fig, axis, loads, show_legend=show_legend)
    return save_figure(fig, stem)


def plot_verification(
    summaries: list[dict[str, Any]], stem: Path
) -> list[Path]:
    selected = [row for row in summaries if row["comparison"] == "topostake-absolute"]
    loads = sorted({int(row["load_tx_per_slot"]) for row in selected})
    fig, axis = plt.subplots(figsize=FOUR_UP_FIGSIZE)
    styles = [
        ("evidence_verify_mean_ms", "Mean", "#0072B2", "o", -0.08),
        ("evidence_verify_p95_ms", "p95", "#D55E00", "s", 0.08),
    ]
    for metric, label, color, marker, offset in styles:
        by_load = {
            int(row["load_tx_per_slot"]): row
            for row in selected
            if row["metric"] == metric
        }
        axis.errorbar(
            [index + offset for index in range(len(loads))],
            [float(by_load[load]["mean"]) for load in loads],
            yerr=[float(by_load[load]["ci95"]) for load in loads],
            color=color,
            marker=marker,
            linestyle="none",
            markersize=4.5,
            capsize=2.5,
            linewidth=1.1,
            label=label,
        )
    axis.set_ylabel("Verification time (ms)")
    finish_axis(fig, axis, loads, show_legend=True)
    return save_figure(fig, stem)


def render_figures(
    summaries: list[dict[str, Any]], output_dir: Path
) -> list[Path]:
    configure_style()
    specs = [
        (
            "throughput_change_percent",
            "Throughput $\\Delta$ (%)",
            "frozen_devnet_performance_a",
        ),
        (
            "p95_latency_change_seconds",
            "p95 delay $\\Delta$ (s)",
            "frozen_devnet_performance_b",
        ),
        (
            "aggregate_cpu_change_percentage_points",
            "CPU $\\Delta$ (pp)",
            "frozen_devnet_resources_a",
        ),
        (
            "aggregate_memory_change_mib",
            "Memory $\\Delta$ (MiB)",
            "frozen_devnet_resources_b",
        ),
        (
            "aggregate_network_change_mib",
            "Network $\\Delta$ (MiB)",
            "frozen_devnet_resources_c",
        ),
        (
            "additional_block_bytes_per_tx",
            "Block bytes $\\Delta$ / tx",
            "frozen_devnet_evidence_a",
        ),
    ]
    outputs: list[Path] = []
    for metric, ylabel, filename in specs:
        outputs.extend(
            plot_paired_metric(
                summaries,
                metric,
                ylabel,
                output_dir / filename,
                show_legend=(
                    filename == PRIMARY_FIGURE_STEMS[0]
                    or filename not in PRIMARY_FIGURE_STEMS
                ),
            )
        )
    outputs.extend(
        plot_verification(summaries, output_dir / "frozen_devnet_evidence_b")
    )
    return outputs


def write_figure_data(rows: list[dict[str, Any]], path: Path) -> None:
    fields = [
        "comparison",
        "reference",
        "variant",
        "load_tx_per_slot",
        "metric",
        "unit",
        "n",
        "mean",
        "ci95",
        "ci95_low",
        "ci95_high",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def summary_value(
    summaries: list[dict[str, Any]], load: int, metric: str
) -> tuple[float, float]:
    row = next(
        row
        for row in summaries
        if row["comparison"] == "topostake-vs-baseline"
        and int(row["load_tx_per_slot"]) == load
        and row["metric"] == metric
    )
    return float(row["mean"]), float(row["ci95"])


def verification_value(
    summaries: list[dict[str, Any]], load: int, metric: str
) -> tuple[float, float]:
    row = next(
        row
        for row in summaries
        if row["comparison"] == "topostake-absolute"
        and int(row["load_tx_per_slot"]) == load
        and row["metric"] == metric
    )
    return float(row["mean"]), float(row["ci95"])


def render_table(summaries: list[dict[str, Any]], path: Path) -> None:
    loads = sorted(
        {
            int(row["load_tx_per_slot"])
            for row in summaries
            if row["comparison"] == "topostake-vs-baseline"
        }
    )
    lines = [
        r"\begin{tabular}{r|rrrrrr}",
        r"\hline",
        r"Load & $\Delta$TPS (\%) & $\Delta$p95 (s) & $\Delta$CPU (pp) & $\Delta$Mem (MiB) & $\Delta$B/tx & Verify p95 (ms) \\",
        r"\hline",
    ]
    for load in loads:
        throughput, _ = summary_value(summaries, load, "throughput_change_percent")
        latency, _ = summary_value(summaries, load, "p95_latency_change_seconds")
        cpu, _ = summary_value(summaries, load, "aggregate_cpu_change_percentage_points")
        memory, _ = summary_value(summaries, load, "aggregate_memory_change_mib")
        block_bytes, _ = summary_value(summaries, load, "additional_block_bytes_per_tx")
        verify, _ = verification_value(summaries, load, "evidence_verify_p95_ms")
        lines.append(
            f"{load} & {throughput:+.2f} & {latency:+.2f} & {cpu:+.1f} & "
            f"{memory:+.1f} & {block_bytes:+.1f} & {verify:.1f} \\\\"
        )
    lines.extend([r"\hline", r"\end{tabular}"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_manifest(
    path: Path,
    source: Path,
    rows: list[dict[str, str]],
    outputs: list[Path],
    data_path: Path,
    table_path: Path,
) -> None:
    payload = {
        "suite": "frozen_v1_devnet_main",
        "source": str(source),
        "row_count": len(rows),
        "variants": sorted({str(row["variant"]) for row in rows}),
        "loads_tx_per_slot": sorted({int(numeric(row, "load_tx_per_slot")) for row in rows}),
        "seeds": sorted({int(numeric(row, "seed")) for row in rows}),
        "statistics": "paired two-sided 95% Student-t interval; seed is the pairing unit",
        "resource_scope": "aggregate EL+CL user-service containers on one physical host",
        "figure_contents": FIGURE_CONTENTS,
        "primary_four_panel_row": list(PRIMARY_FIGURE_STEMS),
        "figures": [str(output) for output in outputs],
        "figure_data": str(data_path),
        "latex_table": str(table_path),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--figure-data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--table", type=Path, default=DEFAULT_TABLE)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rows = read_runs(args.input)
    summaries = [*paired_summaries(rows), *verification_summaries(rows)]
    write_figure_data(summaries, args.figure_data)
    render_table(summaries, args.table)
    outputs = render_figures(summaries, args.output_dir)
    manifest = args.output_dir / "figure_manifest.json"
    write_manifest(
        manifest,
        args.input,
        rows,
        outputs,
        args.figure_data,
        args.table,
    )
    print(
        f"Generated {len(outputs)} frozen-v1 devnet figure files from {len(rows)} runs; "
        f"manifest={manifest}"
    )
    return 0



if __name__ == "__main__":
    raise SystemExit(main())
