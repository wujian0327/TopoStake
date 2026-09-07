#!/usr/bin/env python3
"""Audit, summarize, and plot TRAIL incentive-fairness experiments.

The script reads frozen raw runs directly.  Organic metrics are aggregated
after the configured warm-up, while the reinvestment trajectory is rebuilt
from validator stakes and epoch rewards.  Existing figures and raw data are
never modified.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

os.environ.setdefault("MPLCONFIGDIR", "/tmp/trail-matplotlib")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from scipy.stats import t as student_t


ROOT = Path(__file__).resolve().parents[1]
ORGANIC_ROOT = (
    ROOT
    / "results"
    / "raw"
    / "frozen_v1_organic_capture_main"
    / "organic_traffic_capture"
)
REINVESTMENT_ROOT = (
    ROOT
    / "results"
    / "raw"
    / "frozen_v1_reinvestment_gini_main"
    / "reinvestment_gini"
)
PROCESSED = ROOT / "results" / "processed"
OUTPUT = ROOT / "figures" / "trail_fairness"

EXPECTED_ORGANIC_REVISION = "organic-capture-v2-stable-assignment"
EXPECTED_REINVESTMENT_REVISION = "rq3-reinvestment-gini-xi1-v2"
EXPECTED_ORGANIC_COMMIT = "479986d382c43a82e2108732bc47a094f0b51124"
EXPECTED_REINVESTMENT_COMMIT = "d890a7ba2593b233181e8c4d64cea4777b1ec04e"
EXPECTED_STAKES = (0.1, 0.2, 0.3)
EXPECTED_PLACEMENTS = ("random", "high-degree")
EXPECTED_PROTOCOLS = ("pos", "topostake_eta0", "topostake")
EXPECTED_SEEDS = tuple(range(20))
TOLERANCE = 2e-6

BLUE = "#0072B2"
ORANGE = "#D55E00"
GREEN = "#009E73"
GRAY = "#666666"
LIGHT_GRAY = "#B5B5B5"
PLACEMENT_STYLE = {
    "random": {"label": "Random", "color": BLUE, "marker": "o", "linestyle": "-"},
    "high-degree": {
        "label": "High degree",
        "color": ORANGE,
        "marker": "s",
        "linestyle": "--",
    },
}
PROTOCOL_STYLE = {
    "pos": {"label": "PoS", "color": GRAY, "marker": "^", "linestyle": ":"},
    "topostake_eta0": {
        "label": "Fee-only TRAIL",
        "color": BLUE,
        "marker": "s",
        "linestyle": "--",
    },
    "topostake": {
        "label": "Full TRAIL",
        "color": ORANGE,
        "marker": "o",
        "linestyle": "-",
    },
}


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def finite(value: Any, field: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"non-finite {field}: {value!r}")
    return result


def mean_ci95(values: Iterable[float]) -> tuple[float, float, int]:
    sample = [float(value) for value in values]
    if len(sample) != 20 or not all(math.isfinite(value) for value in sample):
        raise ValueError(f"expected 20 finite observations, found {len(sample)}")
    mean = statistics.fmean(sample)
    ci = float(student_t.ppf(0.975, len(sample) - 1)) * statistics.stdev(sample) / math.sqrt(len(sample))
    return mean, ci, len(sample)


def sha256_json(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def canonical_graph_hash(path: Path) -> str:
    edges = [tuple(sorted(edge)) for edge in read_json(path)]
    return sha256_json(sorted(edges))


def initial_node_fingerprints(path: Path) -> tuple[str, str]:
    stakes: list[tuple[str, float]] = []
    coalition: list[str] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if int(row["epoch"]) != 0:
                break
            validator = row["validator_id"]
            stakes.append((validator, finite(row["economic_stake"], "economic_stake")))
            if truthy(row["adversarial"]):
                coalition.append(validator)
    if len(stakes) != 100:
        raise ValueError(f"expected 100 initial validators in {path}, found {len(stakes)}")
    return sha256_json(sorted(stakes)), sha256_json(sorted(coalition))


def proposer_bound(stake: float, eta: float) -> float:
    return stake * (1.0 + eta) / (1.0 + stake * eta)


def organic_run(run_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    meta = read_json(run_dir / "experiment_meta.json")
    config = read_json(run_dir / "run_config.json")
    status = read_json(run_dir / "runner_status.json")
    summary = read_json(run_dir / "run_summary.json")
    if meta.get("run_revision") != EXPECTED_ORGANIC_REVISION:
        raise ValueError(f"unexpected organic revision in {run_dir}")
    if config.get("git_commit_sha") != EXPECTED_ORGANIC_COMMIT:
        raise ValueError(f"unexpected organic source commit in {run_dir}")
    if status.get("status") != "ok" or status.get("exit_code") != 0:
        raise ValueError(f"failed organic run: {run_dir}")
    if int(summary.get("completed_epochs", -1)) != 40:
        raise ValueError(f"incomplete organic run: {run_dir}")

    warmup = int(meta["warmup_epochs"])
    totals = Counter()
    epoch_means: dict[str, list[float]] = defaultdict(list)
    generated: list[int] = []
    epoch_rows = 0
    max_bound_excess = -math.inf
    bound_exceeding_epochs = 0
    with (run_dir / "epoch_metrics.csv").open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            epoch_rows += 1
            generated.append(int(row["generated_tx"]))
            if int(row["epoch"]) < warmup:
                continue
            for field in (
                "organic_included_tx",
                "organic_valid_path_count",
                "organic_relay_reward",
                "adversary_organic_relay_reward",
                "organic_raw_contribution",
                "adversary_organic_raw_contribution",
            ):
                totals[field] += finite(row[field], field)
            for field in (
                "adversary_real_stake_share",
                "adversary_score_share",
                "adversary_proposer_weight_share",
            ):
                epoch_means[field].append(finite(row[field], field))
            stake = finite(row["adversary_real_stake_share"], "adversary_real_stake_share")
            observed = finite(row["adversary_proposer_weight_share"], "adversary_proposer_weight_share")
            excess = observed - proposer_bound(stake, float(meta["eta"]))
            max_bound_excess = max(max_bound_excess, excess)
            bound_exceeding_epochs += int(excess > 1e-9)
    if epoch_rows != 40 or any(len(values) != 30 for values in epoch_means.values()):
        raise ValueError(f"unexpected organic epoch coverage in {run_dir}")

    slot_files = list(run_dir.glob("slot_metrics_*.csv"))
    if len(slot_files) != 1:
        raise ValueError(f"expected one slot metrics file in {run_dir}")
    maximum_path = 0
    with slot_files[0].open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            maximum_path = max(maximum_path, int(row["max_path_length"]))

    stake_hash, coalition_hash = initial_node_fingerprints(run_dir / "node_epoch_metrics.csv")
    reward_share = totals["adversary_organic_relay_reward"] / totals["organic_relay_reward"]
    contribution_share = totals["adversary_organic_raw_contribution"] / totals["organic_raw_contribution"]
    stake_share = statistics.fmean(epoch_means["adversary_real_stake_share"])
    score_share = statistics.fmean(epoch_means["adversary_score_share"])
    proposer_share = statistics.fmean(epoch_means["adversary_proposer_weight_share"])
    seeds = {
        name: int(meta[name])
        for name in (
            "graph_seed",
            "wallet_seed",
            "workload_seed",
            "election_seed",
            "failure_seed",
            "attack_seed",
        )
    }
    row = {
        "run_id": meta["run_id"],
        "git_commit_sha": config["git_commit_sha"],
        "run_revision": meta["run_revision"],
        "seed_value": int(meta["seed_value"]),
        "target_stake": float(meta["adversary_stake_fraction"]),
        "placement": meta["adversary_placement"],
        "attack_mode": meta["attack_mode"],
        "usable_epochs": 40 - warmup,
        "actual_coalition_stake_share": stake_share,
        "coalition_relay_reward_share": reward_share,
        "coalition_raw_contribution_share": contribution_share,
        "contribution_reward_share_abs_error": abs(contribution_share - reward_share),
        "coalition_propagation_score_share": score_share,
        "coalition_proposer_weight_share": proposer_share,
        "proposer_bound": proposer_bound(stake_share, float(meta["eta"])),
        "proposer_bound_excess": proposer_share - proposer_bound(stake_share, float(meta["eta"])),
        "bound_exceeding_epochs": bound_exceeding_epochs,
        "maximum_included_path_hops": maximum_path,
        "graph_hash": canonical_graph_hash(run_dir / "graph.json"),
        "initial_stake_hash": stake_hash,
        "coalition_identity_hash": coalition_hash,
        "background_generated_tx_hash": sha256_json(generated),
        "rng_seed_hash": sha256_json(seeds),
    }
    audit = {**row, "max_epoch_bound_excess": max_bound_excess}
    return row, audit


def audit_organic(root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    audits: list[dict[str, Any]] = []
    for run_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        meta = read_json(run_dir / "experiment_meta.json")
        if meta.get("attack_mode") != "none":
            continue
        row, audit = organic_run(run_dir)
        runs.append(row)
        audits.append(audit)
    expected = {
        (seed, stake, placement)
        for seed in EXPECTED_SEEDS
        for stake in EXPECTED_STAKES
        for placement in EXPECTED_PLACEMENTS
    }
    observed = {
        (row["seed_value"], row["target_stake"], row["placement"])
        for row in runs
    }
    if len(runs) != 120 or observed != expected:
        raise ValueError(f"organic matrix mismatch: {len(runs)} runs, {len(observed)} keys")
    checks = {
        "runs": len(runs),
        "maximum_path_hops": max(row["maximum_included_path_hops"] for row in runs),
        "runs_over_16_hops": sum(row["maximum_included_path_hops"] > 16 for row in runs),
        "maximum_contribution_reward_share_error": max(
            row["contribution_reward_share_abs_error"] for row in runs
        ),
        "bound_exceeding_runs": sum(row["proposer_bound_excess"] > 1e-9 for row in runs),
        "bound_exceeding_epochs": sum(row["bound_exceeding_epochs"] for row in runs),
        "maximum_run_bound_excess": max(row["proposer_bound_excess"] for row in runs),
        "maximum_epoch_bound_excess": max(row["max_epoch_bound_excess"] for row in audits),
    }
    return runs, checks


def gini(values: Iterable[float]) -> float:
    ordered = sorted(max(0.0, value) for value in values)
    total = sum(ordered)
    if not ordered or total <= 0.0:
        return 0.0
    count = len(ordered)
    weighted = sum((index + 1) * value for index, value in enumerate(ordered))
    return 2.0 * weighted / (count * total) - (count + 1.0) / count


def reinvestment_run(run_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    meta = read_json(run_dir / "experiment_meta.json")
    config = read_json(run_dir / "run_config.json")
    status = read_json(run_dir / "runner_status.json")
    summary = read_json(run_dir / "run_summary.json")
    if meta.get("run_revision") != EXPECTED_REINVESTMENT_REVISION:
        raise ValueError(f"unexpected reinvestment revision in {run_dir}")
    if config.get("git_commit_sha") != EXPECTED_REINVESTMENT_COMMIT:
        raise ValueError(f"unexpected reinvestment source commit in {run_dir}")
    if float(meta.get("reward_reinvestment_rate", -1)) != 1.0:
        raise ValueError(f"reinvestment rate is not 1.0 in {run_dir}")
    if status.get("status") != "ok" or status.get("exit_code") != 0:
        raise ValueError(f"failed reinvestment run: {run_dir}")
    if int(summary.get("completed_epochs", -1)) != 1000:
        raise ValueError(f"incomplete reinvestment run: {run_dir}")

    rows: list[dict[str, Any]] = []
    current_epoch = -1
    current: list[dict[str, str]] = []
    previous_post: dict[str, float] | None = None
    maximum_continuity_error = 0.0

    def consume(epoch: int, node_rows: list[dict[str, str]]) -> dict[str, float]:
        nonlocal previous_post, maximum_continuity_error
        if len(node_rows) != 100:
            raise ValueError(f"epoch {epoch} in {run_dir} has {len(node_rows)} validators")
        pre = {row["validator_id"]: finite(row["economic_stake"], "economic_stake") for row in node_rows}
        if previous_post is not None:
            maximum_continuity_error = max(
                maximum_continuity_error,
                max(abs(pre[key] - previous_post[key]) for key in pre),
            )
        post = {
            row["validator_id"]: finite(row["economic_stake"], "economic_stake")
            + finite(row["proposer_reward"], "proposer_reward")
            + finite(row["relay_reward"], "relay_reward")
            for row in node_rows
        }
        if previous_post is None:
            rows.append(
                {
                    "run_id": meta["run_id"],
                    "protocol": meta["protocol_label"],
                    "seed_value": int(meta["seed_value"]),
                    "epoch": 0,
                    "stake_gini": gini(pre.values()),
                }
            )
        previous_post = post
        return post

    with (run_dir / "node_epoch_metrics.csv").open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            epoch = int(row["epoch"])
            if current_epoch == -1:
                current_epoch = epoch
            if epoch != current_epoch:
                post = consume(current_epoch, current)
                rows.append(
                    {
                        "run_id": meta["run_id"],
                        "protocol": meta["protocol_label"],
                        "seed_value": int(meta["seed_value"]),
                        "epoch": current_epoch + 1,
                        "stake_gini": gini(post.values()),
                    }
                )
                current_epoch = epoch
                current = []
            current.append(row)
    if current:
        post = consume(current_epoch, current)
        rows.append(
            {
                "run_id": meta["run_id"],
                "protocol": meta["protocol_label"],
                "seed_value": int(meta["seed_value"]),
                "epoch": current_epoch + 1,
                "stake_gini": gini(post.values()),
            }
        )
    if len(rows) != 1001 or maximum_continuity_error > TOLERANCE:
        raise ValueError(
            f"invalid reinvestment trajectory in {run_dir}: points={len(rows)}, "
            f"continuity_error={maximum_continuity_error}"
        )
    audit = {
        "run_id": meta["run_id"],
        "protocol": meta["protocol_label"],
        "seed_value": int(meta["seed_value"]),
        "git_commit_sha": config["git_commit_sha"],
        "run_revision": meta["run_revision"],
        "reward_reinvestment_rate": float(meta["reward_reinvestment_rate"]),
        "points": len(rows),
        "maximum_stake_continuity_error": maximum_continuity_error,
        "initial_stake_gini": rows[0]["stake_gini"],
        "final_stake_gini": rows[-1]["stake_gini"],
    }
    return rows, audit


def audit_reinvestment(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    trajectory: list[dict[str, Any]] = []
    audits: list[dict[str, Any]] = []
    for run_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        rows, audit = reinvestment_run(run_dir)
        trajectory.extend(rows)
        audits.append(audit)
    expected = {(protocol, seed) for protocol in EXPECTED_PROTOCOLS for seed in EXPECTED_SEEDS}
    observed = {(row["protocol"], row["seed_value"]) for row in audits}
    if len(audits) != 60 or observed != expected:
        raise ValueError(f"reinvestment matrix mismatch: {len(audits)} runs")
    checks = {
        "runs": len(audits),
        "trajectory_rows": len(trajectory),
        "maximum_stake_continuity_error": max(
            row["maximum_stake_continuity_error"] for row in audits
        ),
        "continuity_violations_at_tolerance": sum(
            row["maximum_stake_continuity_error"] > TOLERANCE for row in audits
        ),
    }
    return trajectory, audits, checks


def grouped_organic(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for placement in EXPECTED_PLACEMENTS:
        for target in EXPECTED_STAKES:
            selected = [
                row for row in runs if row["placement"] == placement and row["target_stake"] == target
            ]
            xmean, xci, _ = mean_ci95(row["actual_coalition_stake_share"] for row in selected)
            for panel, metric in (
                ("reward_concentration", "coalition_relay_reward_share"),
                ("score_proposer_shares", "coalition_propagation_score_share"),
                ("score_proposer_shares", "coalition_proposer_weight_share"),
            ):
                mean, ci, count = mean_ci95(row[metric] for row in selected)
                output.append(
                    {
                        "panel": panel,
                        "placement": placement,
                        "target_stake": target,
                        "metric": metric,
                        "n": count,
                        "mean_actual_stake_share": xmean,
                        "ci95_actual_stake_share": xci,
                        "mean": mean,
                        "ci95": ci,
                    }
                )
    return output


def grouped_reinvestment(trajectory: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, int], list[float]] = defaultdict(list)
    for row in trajectory:
        grouped[(row["protocol"], row["epoch"])].append(row["stake_gini"])
    output = []
    for (protocol, epoch), values in sorted(grouped.items()):
        mean, ci, count = mean_ci95(values)
        output.append(
            {
                "protocol": protocol,
                "epoch": epoch,
                "n": count,
                "mean": mean,
                "ci95": ci,
                "ci95_low": mean - ci,
                "ci95_high": mean + ci,
            }
        )
    return output


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def configure_style() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 8.5,
            "axes.labelsize": 9.5,
            "axes.titlesize": 9.0,
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


def decorate(axis: Any, *, legend: bool = True) -> None:
    axis.grid(axis="y", color="#E6E6E6", linewidth=0.7, zorder=0)
    axis.spines["left"].set_linewidth(0.9)
    axis.spines["bottom"].set_linewidth(0.9)
    axis.tick_params(width=0.8, length=3)
    if legend:
        axis.legend(
            frameon=True,
            framealpha=0.9,
            facecolor="white",
            edgecolor="#D0D0D0",
            borderpad=0.35,
            handletextpad=0.5,
        )


def save(fig: Any, stem: str, output: Path) -> tuple[Path, Path]:
    output.mkdir(parents=True, exist_ok=True)
    pdf = output / f"{stem}.pdf"
    png = output / f"{stem}.png"
    fig.savefig(pdf, facecolor="white")
    fig.savefig(png, dpi=300, facecolor="white")
    plt.close(fig)
    return pdf, png


def plot_group_series(
    axis: Any,
    groups: list[dict[str, Any]],
    panel: str,
    metric: str,
    *,
    yscale: float = 1.0,
) -> None:
    for placement in EXPECTED_PLACEMENTS:
        style = PLACEMENT_STYLE[placement]
        points = sorted(
            (
                row["mean_actual_stake_share"] * 100.0,
                row["mean"] * yscale,
                row["ci95"] * yscale,
            )
            for row in groups
            if row["panel"] == panel and row["metric"] == metric and row["placement"] == placement
        )
        axis.errorbar(
            [point[0] for point in points],
            [point[1] for point in points],
            yerr=[point[2] for point in points],
            color=style["color"],
            marker=style["marker"],
            markerfacecolor="white" if placement == "high-degree" else style["color"],
            markeredgewidth=1.0,
            linestyle=style["linestyle"],
            linewidth=1.2,
            markersize=4.5,
            capsize=2.5,
            label=style["label"],
            zorder=2,
        )


def render_figures(
    organic_groups: list[dict[str, Any]],
    reinvestment_groups: list[dict[str, Any]],
    output: Path,
) -> list[Path]:
    configure_style()
    outputs: list[Path] = []

    fig, axis = plt.subplots(figsize=(3.45, 2.55))
    plot_group_series(
        axis,
        organic_groups,
        "reward_concentration",
        "coalition_relay_reward_share",
        yscale=100.0,
    )
    xlim = (5.0, 35.0)
    axis.plot(xlim, xlim, color=GRAY, linestyle=":", linewidth=1.0, label="Stake parity", zorder=1)
    axis.set_xlim(*xlim)
    axis.set_ylim(bottom=0.0)
    axis.set_xlabel("Coalition stake (%)")
    axis.set_ylabel("Relay-reward share (%)")
    decorate(axis)
    fig.subplots_adjust(left=0.16, right=0.97, bottom=0.20, top=0.97)
    outputs.extend(save(fig, "trail_reward_concentration", output))

    fig, axis = plt.subplots(figsize=(3.45, 2.55))
    response_style = {
        "coalition_propagation_score_share": (GREEN, "Score share", -0.3),
        "coalition_proposer_weight_share": (BLUE, "Proposer weight", 0.3),
    }
    for metric, (color, _, x_offset) in response_style.items():
        for placement in EXPECTED_PLACEMENTS:
            style = PLACEMENT_STYLE[placement]
            points = sorted(
                (
                    row["mean_actual_stake_share"] * 100.0 + x_offset,
                    row["mean"] * 100.0,
                    row["ci95"] * 100.0,
                )
                for row in organic_groups
                if row["panel"] == "score_proposer_shares"
                and row["metric"] == metric
                and row["placement"] == placement
            )
            axis.errorbar(
                [point[0] for point in points],
                [point[1] for point in points],
                yerr=[point[2] for point in points],
                color=color,
                marker=style["marker"],
                markerfacecolor="white" if placement == "high-degree" else color,
                markeredgewidth=1.0,
                linestyle=style["linestyle"],
                linewidth=1.2,
                markersize=4.3,
                capsize=2.3,
                label="_nolegend_",
                zorder=2,
            )
    axis.plot(xlim, xlim, color=GRAY, linestyle=":", linewidth=1.0, zorder=1)
    axis.set_xlim(4.5, 35.5)
    axis.set_ylim(bottom=0.0)
    axis.set_xlabel("Coalition stake (%)")
    axis.set_ylabel("Coalition share (%)")
    handles = [
        Line2D([0], [0], color=GREEN, linewidth=1.3, label="Score share"),
        Line2D([0], [0], color=BLUE, linewidth=1.3, label="Proposer weight"),
        Line2D([0], [0], color=GRAY, linestyle=":", linewidth=1.0, label="Stake parity"),
        Line2D([0], [0], color=GRAY, marker="o", linestyle="-", label="Random"),
        Line2D(
            [0],
            [0],
            color=GRAY,
            marker="s",
            markerfacecolor="white",
            linestyle="--",
            label="High degree",
        ),
    ]
    decorate(axis, legend=False)
    axis.legend(
        handles=handles,
        ncol=2,
        frameon=True,
        framealpha=0.9,
        facecolor="white",
        edgecolor="#D0D0D0",
        borderpad=0.3,
        columnspacing=0.8,
        handletextpad=0.45,
        loc="best",
    )
    fig.subplots_adjust(left=0.14, right=0.97, bottom=0.20, top=0.97)
    outputs.extend(save(fig, "trail_score_proposer_shares", output))

    fig, axis = plt.subplots(figsize=(3.45, 2.55))
    for protocol in EXPECTED_PROTOCOLS:
        style = PROTOCOL_STYLE[protocol]
        points = sorted(
            (row["epoch"], row["mean"], row["ci95_low"], row["ci95_high"])
            for row in reinvestment_groups
            if row["protocol"] == protocol
        )
        epochs = [point[0] for point in points]
        means = [point[1] for point in points]
        axis.fill_between(
            epochs,
            [point[2] for point in points],
            [point[3] for point in points],
            color=style["color"],
            alpha=0.12,
            linewidth=0,
            zorder=1,
        )
        axis.plot(
            epochs,
            means,
            color=style["color"],
            linestyle=style["linestyle"],
            marker=style["marker"],
            markevery=100,
            markerfacecolor="white" if protocol != "topostake" else style["color"],
            markeredgewidth=0.8,
            linewidth=1.2,
            markersize=3.5,
            label=style["label"],
            zorder=2,
        )
    axis.set_xlim(0, 1050)
    axis.set_xticks([0, 250, 500, 750, 1000])
    axis.set_xlabel("Epoch")
    axis.set_ylabel("Stake Gini")
    decorate(axis)
    fig.subplots_adjust(left=0.16, right=0.97, bottom=0.20, top=0.97)
    outputs.extend(save(fig, "trail_stake_concentration", output))
    return outputs


def report_text(
    organic_runs: list[dict[str, Any]],
    organic_groups: list[dict[str, Any]],
    reinvestment_audits: list[dict[str, Any]],
    reinvestment_groups: list[dict[str, Any]],
    organic_checks: dict[str, Any],
    reinvestment_checks: dict[str, Any],
) -> str:
    final = [row for row in reinvestment_groups if row["epoch"] == 1000]
    lines = [
        "# TRAIL Incentive Fairness consistency report",
        "",
        "## Acceptance",
        "",
        "- Organic baseline runs: 120/120; 20 per target-stake and placement configuration.",
        "- Reinvestment runs: 60/60; 20 per mechanism; 1001 trajectory points per run.",
        f"- Maximum observed included-path length: {organic_checks['maximum_path_hops']} hops; runs above 16: {organic_checks['runs_over_16_hops']}.",
        f"- Maximum contribution-share/reward-share error: {organic_checks['maximum_contribution_reward_share_error']:.12g}.",
        f"- Proposer-bound exceeding runs: {organic_checks['bound_exceeding_runs']}; exceeding epochs: {organic_checks['bound_exceeding_epochs']}.",
        f"- Maximum run-level proposer bound excess: {organic_checks['maximum_run_bound_excess']:.9g}.",
        f"- Maximum reinvestment continuity error: {reinvestment_checks['maximum_stake_continuity_error']:.12g}; violations at tolerance {TOLERANCE:g}: {reinvestment_checks['continuity_violations_at_tolerance']}.",
        "- Rerun required: no.",
        "",
        "## Metric definitions",
        "",
        "- Reward concentration: baseline coalition relay rewards divided by all organic-transaction relay rewards, after epochs 0--9 are excluded, plotted against realized normalized coalition economic stake.",
        "- Score and proposer shares: baseline coalition propagation-score share and normalized proposer-weight share, after epochs 0--9 are excluded, plotted against realized normalized coalition economic stake.",
        "- Stake concentration: Gini coefficient of economic stake after each epoch's proposer and relay rewards are fully reinvested; epoch 0 is the initial stake vector and epoch 1000 is post-settlement for epoch 999.",
        "",
        "## Organic grouped results",
        "",
        "| Panel/metric | Placement | Target stake | Mean actual stake | Mean | 95% CI half-width | n |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in sorted(
        organic_groups,
        key=lambda item: (
            item["panel"],
            item["metric"],
            EXPECTED_PLACEMENTS.index(item["placement"]),
            item["target_stake"],
        ),
    ):
        lines.append(
            f"| {row['panel']} / {row['metric']} | {PLACEMENT_STYLE[row['placement']]['label']} "
            f"| {row['target_stake']:.1f} | {row['mean_actual_stake_share']:.6f} "
            f"| {row['mean']:.6f} | {row['ci95']:.6f} | {row['n']} |"
        )
    lines.extend(
        [
        "",
        "## Final stake Gini (epoch 1000)",
        "",
        "| Mechanism | Mean | 95% CI | n |",
        "|---|---:|---:|---:|",
        ]
    )
    for row in sorted(final, key=lambda item: EXPECTED_PROTOCOLS.index(item["protocol"])):
        label = PROTOCOL_STYLE[row["protocol"]]["label"]
        lines.append(
            f"| {label} | {row['mean']:.6f} | [{row['ci95_low']:.6f}, {row['ci95_high']:.6f}] | {row['n']} |"
        )
    lines.extend(
        [
            "",
            "## Provenance",
            "",
            f"- Organic source commit: `{EXPECTED_ORGANIC_COMMIT}`; revision: `{EXPECTED_ORGANIC_REVISION}`.",
            f"- Reinvestment source commit: `{EXPECTED_REINVESTMENT_COMMIT}`; revision: `{EXPECTED_REINVESTMENT_REVISION}`; reinvestment rate: 1.0.",
            "- Confidence intervals are two-sided 95% Student's t intervals over 20 independent baseline runs (df=19).",
            "",
            "## Observed ranges",
            "",
            f"- Baseline relay-reward share: {min(row['coalition_relay_reward_share'] for row in organic_runs):.6f} to {max(row['coalition_relay_reward_share'] for row in organic_runs):.6f}.",
            f"- Baseline propagation-score share: {min(row['coalition_propagation_score_share'] for row in organic_runs):.6f} to {max(row['coalition_propagation_score_share'] for row in organic_runs):.6f}.",
            f"- Baseline proposer-weight share: {min(row['coalition_proposer_weight_share'] for row in organic_runs):.6f} to {max(row['coalition_proposer_weight_share'] for row in organic_runs):.6f}.",
            f"- Final run-level stake Gini: {min(row['final_stake_gini'] for row in reinvestment_audits):.6f} to {max(row['final_stake_gini'] for row in reinvestment_audits):.6f}.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--organic-root", type=Path, default=ORGANIC_ROOT)
    parser.add_argument("--reinvestment-root", type=Path, default=REINVESTMENT_ROOT)
    parser.add_argument("--processed-dir", type=Path, default=PROCESSED)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT)
    args = parser.parse_args()

    organic_runs, organic_checks = audit_organic(args.organic_root)
    reinvestment_trajectory, reinvestment_audits, reinvestment_checks = audit_reinvestment(
        args.reinvestment_root
    )
    organic_groups = grouped_organic(organic_runs)
    reinvestment_groups = grouped_reinvestment(reinvestment_trajectory)

    write_csv(args.processed_dir / "trail_incentive_fairness_organic_runs.csv", organic_runs)
    write_csv(args.processed_dir / "trail_incentive_fairness_organic_groups.csv", organic_groups)
    write_csv(
        args.processed_dir / "trail_incentive_fairness_reinvestment_runs.csv",
        reinvestment_audits,
    )
    write_csv(
        args.processed_dir / "trail_incentive_fairness_reinvestment_epochs.csv",
        reinvestment_trajectory,
    )
    write_csv(
        args.processed_dir / "trail_incentive_fairness_reinvestment_groups.csv",
        reinvestment_groups,
    )
    report = report_text(
        organic_runs,
        organic_groups,
        reinvestment_audits,
        reinvestment_groups,
        organic_checks,
        reinvestment_checks,
    )
    report_path = args.processed_dir / "trail_incentive_fairness_report.md"
    report_path.write_text(report, encoding="utf-8")
    outputs = render_figures(organic_groups, reinvestment_groups, args.output_dir)
    print(f"organic baseline runs={len(organic_runs)}")
    print(f"reinvestment runs={len(reinvestment_audits)}")
    for path in outputs:
        print(path.relative_to(ROOT))
    print(report_path.relative_to(ROOT))


if __name__ == "__main__":
    main()
