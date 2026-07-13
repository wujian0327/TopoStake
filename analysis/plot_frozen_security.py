#!/usr/bin/env python3
"""Generate paper-ready figures for the frozen-v1 simulator evaluation.

The script accepts an incomplete matrix while experiments are running. Only
successful, complete runs are used, and every figure records the number of
available seeds. Re-running the same command after all 20 seeds finish replaces
the preliminary figures without changing the plotting code.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Sequence

os.environ.setdefault("MPLCONFIGDIR", "/tmp/topostake-matplotlib")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNS = ROOT / "results" / "processed" / "frozen_v1_security_main_runs.csv"
DEFAULT_PAIRED = ROOT / "results" / "processed" / "frozen_v1_security_main_paired.csv"
DEFAULT_FIXED_PADDING = ROOT / "results" / "processed" / "frozen_v1_padding_fixed_path.csv"
DEFAULT_OUTPUT = ROOT / "figures" / "frozen_v1_security"

BLUE = "#0072B2"
ORANGE = "#E69F00"
GREEN = "#009E73"
RED = "#D55E00"
PURPLE = "#CC79A7"
GRAY = "#666666"
LIGHT_GRAY = "#B5B5B5"
PROFILE_COLORS = {"active": BLUE, "normal": GREEN, "lazy": RED}
PROTOCOL_STYLES = {
    "topostake": ("TopoStake", "o", "-"),
    "topostake_eta0": (r"$\eta=0$", "s", "--"),
}


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def as_float(value: Any, default: float = math.nan) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def complete_runs(rows: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    truthy = {"1", "true", "yes"}
    return [
        row
        for row in rows
        if row.get("status") == "ok"
        and str(row.get("complete", "")).lower() in truthy
        and str(row.get("finite_metrics", "true")).lower() in truthy
    ]


def mean_ci(values: Iterable[float]) -> tuple[float, float, int]:
    clean = [value for value in values if math.isfinite(value)]
    if not clean:
        return math.nan, 0.0, 0
    if len(clean) == 1:
        return clean[0], 0.0, 1
    return (
        statistics.mean(clean),
        1.96 * statistics.stdev(clean) / math.sqrt(len(clean)),
        len(clean),
    )


def grouped_stats(
    rows: Iterable[dict[str, str]],
    keys: Sequence[str],
    metric: str,
) -> dict[tuple[str, ...], tuple[float, float, int]]:
    buckets: dict[tuple[str, ...], list[float]] = defaultdict(list)
    for row in rows:
        value = as_float(row.get(metric))
        if math.isfinite(value):
            buckets[tuple(row.get(key, "") for key in keys)].append(value)
    return {key: mean_ci(values) for key, values in buckets.items()}


def configure_style() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 8.5,
            "axes.labelsize": 8.5,
            "axes.titlesize": 9.0,
            "legend.fontsize": 7.5,
            "xtick.labelsize": 7.5,
            "ytick.labelsize": 7.5,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": False,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "savefig.bbox": "tight",
        }
    )


def style_axis(ax: Axes, grid: bool = True) -> None:
    if grid:
        ax.grid(axis="y", color="#E6E6E6", linewidth=0.7, zorder=0)
    ax.tick_params(direction="out", length=3)


def add_panel_labels(axes: Sequence[Axes]) -> None:
    for index, ax in enumerate(axes):
        ax.text(
            -0.14,
            1.06,
            f"({chr(ord('a') + index)})",
            transform=ax.transAxes,
            fontsize=9,
            fontweight="bold",
            va="bottom",
        )


def add_seed_note(fig: Figure, seed_count: int, expected_seeds: int) -> None:
    qualifier = "Preliminary; " if seed_count < expected_seeds else ""
    fig.text(
        0.995,
        0.005,
        f"{qualifier}n={seed_count} independent seeds; 95% CIs where shown",
        ha="right",
        va="bottom",
        fontsize=6.5,
        color=GRAY,
    )


def save_figure(fig: Figure, output_dir: Path, stem: str) -> list[str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[str] = []
    for suffix in ("pdf", "png"):
        path = output_dir / f"{stem}.{suffix}"
        fig.savefig(path, dpi=300, facecolor="white")
        outputs.append(str(path))
    plt.close(fig)
    return outputs


def figure_relay_participation(
    rows: list[dict[str, str]], output_dir: Path, seed_count: int, expected_seeds: int
) -> list[str]:
    selected = [row for row in rows if row.get("experiment") == "relay_participation"]
    if not selected:
        return []
    metrics = [
        ("focal_relay_reward_per_stake", "Relay reward / stake", "Economic return"),
        ("focal_raw_contribution_total", "Raw contribution", "Credited propagation"),
        ("focal_bonus_mean", "Mean bonus", "Score-to-bonus effect"),
        ("focal_proposer_weight_mean", "Mean proposer weight", "Consensus influence"),
    ]
    profiles = ["active", "normal", "lazy"]
    protocols = ["topostake", "topostake_eta0"]
    fig, axes_grid = plt.subplots(2, 2, figsize=(7.15, 4.55))
    axes = list(axes_grid.flat)
    for ax, (metric, ylabel, title) in zip(axes, metrics):
        stats = grouped_stats(selected, ["protocol_label", "relay_profile"], metric)
        for protocol_index, protocol in enumerate(protocols):
            label, marker, line_style = PROTOCOL_STYLES[protocol]
            offset = -0.08 if protocol_index == 0 else 0.08
            xs, ys, cis = [], [], []
            for profile_index, profile in enumerate(profiles):
                mean, ci, n = stats.get((protocol, profile), (math.nan, 0.0, 0))
                if n:
                    xs.append(profile_index + offset)
                    ys.append(mean)
                    cis.append(ci)
            ax.errorbar(
                xs,
                ys,
                yerr=cis,
                label=label,
                color=BLUE if protocol == "topostake" else ORANGE,
                marker=marker,
                linestyle=line_style,
                linewidth=1.25,
                markersize=4.5,
                capsize=2.5,
                zorder=3,
            )
        ax.set_xticks(range(len(profiles)), [profile.capitalize() for profile in profiles])
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        style_axis(ax)
        if metric == "focal_relay_reward_per_stake":
            ax.ticklabel_format(axis="y", style="sci", scilimits=(-2, 2))
    axes[0].legend(frameon=False, ncol=2, loc="upper right")
    add_panel_labels(axes)
    add_seed_note(fig, seed_count, expected_seeds)
    fig.subplots_adjust(wspace=0.31, hspace=0.40, bottom=0.12)
    return save_figure(fig, output_dir, "frozen_relay_participation")


def figure_score_floor(
    rows: list[dict[str, str]], output_dir: Path, seed_count: int, expected_seeds: int
) -> list[str]:
    selected = [row for row in rows if row.get("experiment") == "score_floor_sensitivity"]
    if not selected:
        return []
    fig, axes = plt.subplots(1, 2, figsize=(7.15, 2.55))
    specifications = [
        ("adversary_damped_score_mass_mean", "Adversarial damped score mass", "Score-floor damping"),
        (None, "Bound lift above stake share", "Score-dependent influence lift"),
    ]
    rates = sorted({as_float(row.get("tx_rate")) for row in selected})
    colors = [BLUE, GREEN, ORANGE, RED]
    markers = ["o", "s", "^", "D"]
    for ax, (metric, ylabel, title) in zip(axes, specifications):
        for rate, color, marker in zip(rates, colors, markers):
            points: list[tuple[float, float, float]] = []
            for kappa in sorted(
                {as_float(row.get("topostake_score_floor_kappa")) for row in selected}
            ):
                values = []
                for row in selected:
                    if as_float(row.get("tx_rate")) != rate:
                        continue
                    if as_float(row.get("topostake_score_floor_kappa")) != kappa:
                        continue
                    if metric is None:
                        value = as_float(row.get("score_dependent_proposer_weight_bound_mean")) - as_float(
                            row.get("adversary_real_stake_share_mean")
                        )
                    else:
                        value = as_float(row.get(metric))
                    if math.isfinite(value):
                        values.append(value)
                mean, ci, n = mean_ci(values)
                if n:
                    points.append((kappa, mean, ci))
            ax.errorbar(
                [point[0] for point in points],
                [point[1] for point in points],
                yerr=[point[2] for point in points],
                color=color,
                marker=marker,
                markersize=4,
                linewidth=1.2,
                capsize=2.5,
                label=f"{rate:g} tx/s",
            )
        ax.set_xscale("log")
        ax.set_xticks([0.1, 1.0, 10.0], ["0.1", "1", "10"])
        ax.set_xlabel(r"Score floor $\kappa$")
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        style_axis(ax)
    axes[0].legend(frameon=False, ncol=2, loc="best")
    add_panel_labels(axes)
    add_seed_note(fig, seed_count, expected_seeds)
    fig.subplots_adjust(wspace=0.32, bottom=0.22)
    return save_figure(fig, output_dir, "frozen_score_floor")


def paired_metric(
    rows: list[dict[str, str]], experiment: str, metric: str
) -> list[tuple[float, float, float, float]]:
    points = []
    for row in rows:
        if row.get("experiment") != experiment or row.get("metric") != metric:
            continue
        x = as_float(row.get("scenario_value"))
        mean = as_float(row.get("mean_difference"))
        low = as_float(row.get("ci95_low"))
        high = as_float(row.get("ci95_high"))
        if all(math.isfinite(value) for value in (x, mean, low, high)):
            points.append((x, mean, mean - low, high - mean))
    return sorted(points)


def plot_paired_line(
    ax: Axes,
    points: list[tuple[float, float, float, float]],
    label: str,
    color: str,
    marker: str,
) -> None:
    if not points:
        return
    ax.errorbar(
        [point[0] for point in points],
        [point[1] for point in points],
        yerr=[
            [point[2] for point in points],
            [point[3] for point in points],
        ],
        color=color,
        marker=marker,
        linewidth=1.25,
        markersize=4.5,
        capsize=2.5,
        label=label,
    )


def figure_flooding(
    paired: list[dict[str, str]], output_dir: Path, seed_count: int, expected_seeds: int
) -> list[str]:
    if not any(row.get("experiment") == "flooding_cost_to_influence" for row in paired):
        return []
    fig, axes_grid = plt.subplots(2, 2, figsize=(7.15, 4.55))
    axes = list(axes_grid.flat)
    plot_paired_line(
        axes[0],
        paired_metric(paired, "flooding_cost_to_influence", "adversary_fee_spent"),
        "Irrecoverable fee",
        BLUE,
        "o",
    )
    plot_paired_line(
        axes[0],
        paired_metric(paired, "flooding_cost_to_influence", "adversary_net_income"),
        "Net income",
        RED,
        "s",
    )
    panels = [
        (1, "adversary_damped_score_mass_mean", "Change in damped score mass", "Purchased score"),
        (2, "adversary_proposer_weight_share_mean", "Change in proposer-weight share", "Consensus influence"),
        (3, "p95_inclusion_latency_s_pooled", "Change in pooled p95 latency (s)", "Network stress"),
    ]
    for index, metric, ylabel, title in panels:
        plot_paired_line(
            axes[index],
            paired_metric(paired, "flooding_cost_to_influence", metric),
            "Paired change",
            [GREEN, PURPLE, ORANGE][index - 1],
            ["^", "D", "o"][index - 1],
        )
        axes[index].set_ylabel(ylabel)
        axes[index].set_title(title)
    axes[0].set_ylabel("Paired economic change")
    axes[0].set_title("Attack cost and profitability")
    axes[0].legend(frameon=False, loc="best")
    for ax in axes:
        ax.axhline(0.0, color=LIGHT_GRAY, linewidth=0.8, zorder=0)
        ax.set_xlabel("Attack traffic multiplier")
        style_axis(ax)
    add_panel_labels(axes)
    add_seed_note(fig, seed_count, expected_seeds)
    fig.subplots_adjust(wspace=0.32, hspace=0.42, bottom=0.13)
    return save_figure(fig, output_dir, "frozen_flooding")


def figure_padding(
    rows: list[dict[str, str]],
    fixed_rows: list[dict[str, str]],
    output_dir: Path,
    seed_count: int,
    expected_seeds: int,
) -> tuple[list[str], str | None]:
    selected = [row for row in rows if row.get("experiment") == "path_padding_end_to_end"]
    if not selected:
        return [], "No completed path_padding_end_to_end runs"
    has_fixed = bool(fixed_rows)
    fig, axes_array = plt.subplots(1, 2 if has_fixed else 1, figsize=(7.15 if has_fixed else 3.6, 2.65))
    axes = list(axes_array) if has_fixed else [axes_array]
    ax = axes[0]
    stats = grouped_stats(selected, ["topostake_target_depth", "padding_identities"], "adversary_credit_share")
    depth_colors = {2.0: BLUE, 4.0: GREEN, 8.0: ORANGE}
    for depth in sorted({as_float(row.get("topostake_target_depth")) for row in selected}):
        points = []
        for padding in sorted({as_float(row.get("padding_identities")) for row in selected}):
            mean, ci, n = stats.get((f"{depth:g}", f"{padding:g}"), (math.nan, 0.0, 0))
            if not n:
                mean, ci, n = stats.get((str(depth), str(padding)), (math.nan, 0.0, 0))
            if n:
                points.append((padding, mean, ci))
        ax.errorbar(
            [point[0] for point in points],
            [point[1] for point in points],
            yerr=[point[2] for point in points],
            color=depth_colors.get(depth, GRAY),
            marker={2.0: "o", 4.0: "s", 8.0: "^"}.get(depth, "o"),
            linewidth=1.2,
            markersize=4,
            capsize=2.5,
            label=fr"$D={depth:g}$",
        )
    ax.set_xlabel("Inserted identities")
    ax.set_ylabel("Observed adversarial credit share")
    ax.set_title("End-to-end network stress")
    ax.legend(frameon=False, ncol=3, loc="best")
    style_axis(ax)

    warning = None
    if has_fixed:
        ax = axes[1]
        fixed_buckets: dict[tuple[float, float], list[float]] = defaultdict(list)
        for row in fixed_rows:
            depth = as_float(row.get("depth", row.get("target_depth")))
            inserted = as_float(row.get("inserted_identities"))
            ratio = as_float(row.get("max_ratio", row.get("credit_ratio")))
            if all(math.isfinite(value) for value in (depth, inserted, ratio)):
                fixed_buckets[(depth, inserted)].append(ratio)
        for depth in sorted({key[0] for key in fixed_buckets}):
            points = [
                (inserted, max(fixed_buckets[(depth, inserted)]))
                for inserted in sorted({key[1] for key in fixed_buckets if key[0] == depth})
            ]
            ax.plot(
                [point[0] for point in points],
                [point[1] for point in points],
                color=depth_colors.get(depth, GRAY),
                marker={2.0: "o", 4.0: "s", 8.0: "^"}.get(depth, "o"),
                linewidth=1.2,
                markersize=4,
                label=fr"$D={depth:g}$",
            )
        ax.axhline(1.0, color=RED, linestyle="--", linewidth=1.0, label="Non-amplification limit")
        ax.set_xlabel("Inserted identities")
        ax.set_ylabel("Maximum padded/base credit")
        ax.set_title("Fixed-path theorem check")
        ax.legend(frameon=False, ncol=2, loc="best")
        style_axis(ax)
    else:
        warning = "Fixed-path CSV absent; generated end-to-end padding panel only"
    add_panel_labels(axes)
    add_seed_note(fig, seed_count, expected_seeds)
    fig.subplots_adjust(wspace=0.30, bottom=0.22)
    return save_figure(fig, output_dir, "frozen_padding"), warning


def figure_proposer_envelope(
    rows: list[dict[str, str]], output_dir: Path, seed_count: int, expected_seeds: int
) -> list[str]:
    selected = [row for row in rows if row.get("experiment") == "proposer_influence_envelope"]
    if not selected:
        return []
    fig, axes = plt.subplots(1, 2, figsize=(7.15, 2.75))
    placements = ["random", "high-degree", "high-betweenness"]
    markers = {"random": "o", "high-degree": "s", "high-betweenness": "^"}
    eta_colors = {0.25: BLUE, 0.5: RED}
    for ax, x_field, y_field, title, x_label, y_label in [
        (
            axes[0],
            "score_dependent_proposer_weight_bound_mean",
            "adversary_proposer_weight_share_mean",
            "Observed weight vs. score-dependent bound",
            "Score-dependent bound",
            "Observed proposer-weight share",
        ),
        (
            axes[1],
            "theoretical_proposer_weight_bound_mean",
            "score_dependent_proposer_weight_bound_mean",
            "Score-dependent bound vs. cap envelope",
            "Score-independent cap bound",
            "Score-dependent bound",
        ),
    ]:
        plotted_labels: set[str] = set()
        finite_points: list[tuple[float, float]] = []
        for row in selected:
            x = as_float(row.get(x_field))
            y = as_float(row.get(y_field))
            eta = as_float(row.get("eta"))
            placement = row.get("adversary_placement", "")
            if not all(math.isfinite(value) for value in (x, y, eta)):
                continue
            finite_points.append((x, y))
            label = fr"$\eta={eta:g}$, {placement}"
            ax.scatter(
                [x],
                [y],
                color=eta_colors.get(eta, GRAY),
                marker=markers.get(placement, "o"),
                s=20,
                alpha=0.72,
                edgecolors="none",
                label=label if label not in plotted_labels else None,
                zorder=3,
            )
            plotted_labels.add(label)
        if finite_points:
            lower = min(min(x, y) for x, y in finite_points)
            upper = max(max(x, y) for x, y in finite_points)
            margin = max((upper - lower) * 0.06, 0.002)
            ax.plot([lower - margin, upper + margin], [lower - margin, upper + margin], "--", color=GRAY, linewidth=0.9)
            ax.set_xlim(lower - margin, upper + margin)
            ax.set_ylim(lower - margin, upper + margin)
        ax.set_xlabel(x_label)
        ax.set_ylabel(y_label)
        ax.set_title(title)
        style_axis(ax)
    handles, labels = axes[1].get_legend_handles_labels()
    fig.legend(handles, labels, frameon=False, ncol=3, loc="lower center", bbox_to_anchor=(0.5, 0.04))
    add_panel_labels(axes)
    add_seed_note(fig, seed_count, expected_seeds)
    fig.subplots_adjust(wspace=0.32, bottom=0.31)
    return save_figure(fig, output_dir, "frozen_proposer_envelope")


def figure_relay_network_stress(
    rows: list[dict[str, str]], output_dir: Path, seed_count: int, expected_seeds: int
) -> list[str]:
    selected = [row for row in rows if row.get("experiment") == "relay_network_stress"]
    if not selected:
        return []
    fig, axes = plt.subplots(1, 2, figsize=(7.15, 2.5))
    panels = [
        ("p95_inclusion_latency_s_pooled", "Pooled p95 inclusion latency (s)", "End-to-end latency"),
        ("credit_ineligible_path_rate", "Credit-ineligible path rate", "Evidence eligibility"),
    ]
    profiles = ["active", "lazy"]
    for ax, (metric, ylabel, title) in zip(axes, panels):
        stats = grouped_stats(selected, ["relay_profile"], metric)
        means, cis = [], []
        for profile in profiles:
            mean, ci, _ = stats.get((profile,), (math.nan, 0.0, 0))
            means.append(mean)
            cis.append(ci)
        ax.bar(
            range(len(profiles)),
            means,
            yerr=cis,
            color=[PROFILE_COLORS[profile] for profile in profiles],
            width=0.62,
            capsize=3,
            zorder=3,
        )
        ax.set_xticks(range(len(profiles)), [profile.capitalize() for profile in profiles])
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        style_axis(ax)
    add_panel_labels(axes)
    add_seed_note(fig, seed_count, expected_seeds)
    fig.subplots_adjust(wspace=0.32, bottom=0.20)
    return save_figure(fig, output_dir, "frozen_relay_network_stress")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, default=DEFAULT_RUNS)
    parser.add_argument("--paired", type=Path, default=DEFAULT_PAIRED)
    parser.add_argument("--fixed-padding", type=Path, default=DEFAULT_FIXED_PADDING)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--expected-seeds", type=int, default=20)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    configure_style()
    all_runs = read_csv(args.runs)
    runs = complete_runs(all_runs)
    paired = read_csv(args.paired)
    fixed_padding = read_csv(args.fixed_padding)
    if not runs:
        raise SystemExit(f"No successful complete runs found in {args.runs}")

    seeds = sorted({row.get("seed_index", "") for row in runs})
    outputs: list[str] = []
    outputs.extend(figure_relay_participation(runs, args.output_dir, len(seeds), args.expected_seeds))
    outputs.extend(figure_score_floor(runs, args.output_dir, len(seeds), args.expected_seeds))
    outputs.extend(figure_flooding(paired, args.output_dir, len(seeds), args.expected_seeds))
    padding_outputs, padding_warning = figure_padding(
        runs, fixed_padding, args.output_dir, len(seeds), args.expected_seeds
    )
    outputs.extend(padding_outputs)
    outputs.extend(figure_proposer_envelope(runs, args.output_dir, len(seeds), args.expected_seeds))
    outputs.extend(figure_relay_network_stress(runs, args.output_dir, len(seeds), args.expected_seeds))

    warnings = [padding_warning] if padding_warning else []
    manifest = {
        "protocol_version": "frozen-v1",
        "runs_input": str(args.runs),
        "paired_input": str(args.paired),
        "fixed_padding_input": str(args.fixed_padding),
        "successful_complete_runs": len(runs),
        "available_seed_indices": seeds,
        "available_seed_count": len(seeds),
        "expected_seed_count": args.expected_seeds,
        "preliminary": len(seeds) < args.expected_seeds,
        "confidence_intervals": "normal-approximation 95% CI across independent seeds",
        "outputs": outputs,
        "warnings": warnings,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output_dir / "figure_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(
        f"Generated {len(outputs)} figure files from {len(runs)} complete runs "
        f"across {len(seeds)} seeds; manifest={manifest_path}"
    )
    for warning in warnings:
        print(f"WARNING: {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
