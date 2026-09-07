#!/usr/bin/env python3
"""Recompute and plot the TRAIL sustained-outage evaluation from raw runs.

Only ``frozen_v1_sustained_outage_main_v2`` is read.  The script validates the
complete 3 eta x 3 outage targets x 20 seeds matrix, writes new processed CSVs,
and renders three title-free paper figures.  It never runs the simulator or
reads older outage suites.
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
from scipy.stats import t as student_t


ROOT = Path(__file__).resolve().parents[1]
RAW_ROOT = (
    ROOT
    / "results"
    / "raw"
    / "frozen_v1_sustained_outage_main_v2"
    / "sustained_outage"
)
PROCESSED = ROOT / "results" / "processed"
OUTPUT = ROOT / "figures" / "trail_outage"

RUNS_CSV = PROCESSED / "trail_outage_runs.csv"
EPOCHS_CSV = PROCESSED / "trail_outage_epochs.csv"
GROUPS_CSV = PROCESSED / "trail_outage_groups.csv"

EXPECTED_TARGETS = (0.1, 0.2, 0.3)
EXPECTED_ETAS = (0.0, 0.5, 1.0)
EXPECTED_SEEDS = tuple(range(20))
EXPECTED_BETA = 0.8
EXPECTED_START = 30
EXPECTED_END = 130
EXPECTED_RUNS = 180
EXPECTED_EPOCHS = 130
EXPECTED_DUTIES = 649
EXPECTED_OUTAGE_DUTIES = 500
# Epochs 0--1 precede score-root activation.  At effective epoch 2 one run in
# the 20% condition still has zero total network score, so the common n=20
# score-share trajectory begins at epoch 3 rather than imputing an undefined
# ratio.
FIRST_COMPLETE_SCORE_EPOCH = 3

BLUE = "#0072B2"
ORANGE = "#D55E00"
GREEN = "#009E73"
GRAY = "#666666"
LIGHT_GRAY = "#B5B5B5"
GRID_GRAY = "#E6E6E6"

ETA_STYLES = {
    0.0: {
        "label": r"$\eta=0$",
        "color": GRAY,
        "linestyle": ":",
        "marker": "^",
        "fill": "white",
    },
    0.5: {
        "label": r"$\eta=0.5$",
        "color": ORANGE,
        "linestyle": "-",
        "marker": "o",
        "fill": ORANGE,
    },
    1.0: {
        "label": r"$\eta=1$",
        "color": GREEN,
        "linestyle": "--",
        "marker": "s",
        "fill": "white",
    },
}

TARGET_STYLES = {
    0.1: {
        "label": "10% offline stake",
        "color": BLUE,
        "linestyle": "-",
        "marker": "o",
        "fill": BLUE,
    },
    0.2: {
        "label": "20% offline stake",
        "color": ORANGE,
        "linestyle": "--",
        "marker": "s",
        "fill": "white",
    },
    0.3: {
        "label": "30% offline stake",
        "color": GREEN,
        "linestyle": "-.",
        "marker": "^",
        "fill": "white",
    },
}

REQUIRED_FILES = (
    "run_config.json",
    "experiment_meta.json",
    "runner_status.json",
    "run_summary.json",
    "epoch_metrics.csv",
    "node_epoch_metrics.csv",
    "proposer_duties.csv",
    "graph.json",
)


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def finite(value: Any, field: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"non-finite {field}: {value!r}")
    return result


def sha256_json(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def mean_ci95(values: Iterable[float]) -> tuple[float, float, int]:
    sample = [float(value) for value in values]
    if not sample or not all(math.isfinite(value) for value in sample):
        raise ValueError("confidence interval requires finite observations")
    mean = statistics.fmean(sample)
    if len(sample) == 1:
        return mean, 0.0, 1
    halfwidth = (
        float(student_t.ppf(0.975, len(sample) - 1))
        * statistics.stdev(sample)
        / math.sqrt(len(sample))
    )
    return mean, halfwidth, len(sample)


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def protocol_for_eta(eta: float) -> str:
    return {0.0: "topostake_eta0", 0.5: "topostake", 1.0: "topostake_eta1"}[eta]


def canonical_graph_hash(path: Path) -> str:
    edges = [tuple(sorted(edge)) for edge in read_json(path)]
    return sha256_json(sorted(edges))


def canonical_config(config: dict[str, Any]) -> dict[str, Any]:
    result = json.loads(json.dumps(config))
    result["reward_reinvestment_rate"] = result.get("reward_reinvestment_rate", 0.0)
    result.pop("run_id", None)
    result.pop("output_dir", None)
    result["topostake_config"].pop("eta", None)
    return result


def load_run(run_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    missing = [name for name in REQUIRED_FILES if not (run_dir / name).is_file()]
    if missing:
        raise ValueError(f"{run_dir} is missing {missing}")

    meta = read_json(run_dir / "experiment_meta.json")
    config_record = read_json(run_dir / "run_config.json")
    config = config_record["config"]
    status = read_json(run_dir / "runner_status.json")
    summary = read_json(run_dir / "run_summary.json")
    epoch_metrics = read_csv(run_dir / "epoch_metrics.csv")
    node_metrics = read_csv(run_dir / "node_epoch_metrics.csv")
    duties = read_csv(run_dir / "proposer_duties.csv")

    eta = finite(meta["eta"], "eta")
    target = finite(meta["outage_target_stake_fraction"], "target stake")
    seed = int(meta["seed_value"])
    if eta not in EXPECTED_ETAS or target not in EXPECTED_TARGETS or seed not in EXPECTED_SEEDS:
        raise ValueError(f"unexpected matrix condition in {run_dir}")
    if meta["protocol_label"] != protocol_for_eta(eta):
        raise ValueError(f"protocol/eta mismatch in {run_dir}")
    if not math.isclose(finite(meta["beta"], "beta"), EXPECTED_BETA):
        raise ValueError(f"unexpected beta in {run_dir}")
    if int(meta["node_num"]) != 100 or int(meta["outage_start_epoch"]) != EXPECTED_START:
        raise ValueError(f"unexpected validator count or outage start in {run_dir}")
    if int(meta["outage_duration_epochs"]) != 100 or int(meta["max_epochs"]) != EXPECTED_EPOCHS:
        raise ValueError(f"unexpected outage duration or epoch count in {run_dir}")
    if meta["outage_selection"] != "random" or not truthy(meta["outage_common_slot_randomness"]):
        raise ValueError(f"unexpected outage selection/randomness in {run_dir}")
    if status.get("status") != "ok" or int(summary.get("completed_epochs", -1)) != EXPECTED_EPOCHS:
        raise ValueError(f"incomplete run: {run_dir}")
    if status.get("exit_code") not in (None, 0):
        raise ValueError(f"nonzero exit status in {run_dir}")
    if len(epoch_metrics) != EXPECTED_EPOCHS or len(node_metrics) != 100 * EXPECTED_EPOCHS:
        raise ValueError(f"unexpected epoch/node row count in {run_dir}")
    if len(duties) != EXPECTED_DUTIES:
        raise ValueError(f"unexpected proposer duty count in {run_dir}: {len(duties)}")

    outage_ids = {
        int(value) for value in str(meta["outage_validator_ids"]).split(",") if value
    }
    initial_rows = [row for row in node_metrics if int(row["epoch"]) == 0]
    initial_stakes = sorted(
        (int(row["validator_id"]), finite(row["economic_stake"], "economic_stake"))
        for row in initial_rows
    )
    actual_stake = sum(value for validator, value in initial_stakes if validator in outage_ids) / sum(
        value for _, value in initial_stakes
    )
    recorded_stake = finite(meta["outage_realized_stake_fraction"], "realized stake")
    if abs(actual_stake - recorded_stake) > 2e-6:
        raise ValueError(f"realized outage stake mismatch in {run_dir}")

    rows_by_metric_epoch: dict[int, list[dict[str, str]]] = defaultdict(list)
    for row in node_metrics:
        rows_by_metric_epoch[int(row["epoch"])].append(row)

    epoch_rows: list[dict[str, Any]] = []
    for epoch in range(EXPECTED_EPOCHS):
        # Metrics emitted at the end of e freeze the state used in e+1.
        # Epoch zero precedes any activated score and is stake weighted.
        source_epoch = epoch - 1
        if source_epoch < 0:
            group_weight = actual_stake
            score_share: float | None = None
        else:
            nodes = rows_by_metric_epoch[source_epoch]
            if len(nodes) != 100:
                raise ValueError(f"missing node snapshot {source_epoch} in {run_dir}")
            group_weight = sum(
                finite(row["normalized_proposer_weight"], "proposer weight")
                for row in nodes
                if int(row["validator_id"]) in outage_ids
            )
            score_total = sum(finite(row["normalized_score"], "score") for row in nodes)
            score_share = None
            if score_total > 0.0:
                score_share = sum(
                    finite(row["normalized_score"], "score")
                    for row in nodes
                    if int(row["validator_id"]) in outage_ids
                ) / score_total
        if not 0.0 <= group_weight <= 1.0 + 1e-6:
            raise ValueError(f"invalid proposer-weight share in {run_dir}")
        if score_share is not None and not 0.0 <= score_share <= 1.0 + 1e-6:
            raise ValueError(f"invalid score share in {run_dir}")
        epoch_rows.append(
            {
                "run_id": meta["run_id"],
                "protocol_label": meta["protocol_label"],
                "eta": eta,
                "beta": EXPECTED_BETA,
                "offline_stake_target": target,
                "seed_value": seed,
                "epoch": epoch,
                "outage_active": epoch >= EXPECTED_START,
                "outage_group_score_share": "" if score_share is None else score_share,
                "outage_group_proposer_weight_share": group_weight,
            }
        )

    pre_duties = [row for row in duties if int(row["epoch"]) < EXPECTED_START]
    outage_duties = [row for row in duties if EXPECTED_START <= int(row["epoch"]) < EXPECTED_END]
    if len(pre_duties) != 149 or len(outage_duties) != EXPECTED_OUTAGE_DUTIES:
        raise ValueError(f"unexpected phase duty count in {run_dir}")
    missed = [row for row in outage_duties if not truthy(row["block_produced"])]
    if any(row["failure_reason"] != "scheduled_outage" for row in missed):
        raise ValueError(f"non-outage missed duty in {run_dir}")

    generated = [int(row["generated_tx"]) for row in epoch_metrics]
    rng_seeds = {
        field: int(meta[field])
        for field in (
            "graph_seed",
            "wallet_seed",
            "workload_seed",
            "election_seed",
            "failure_seed",
            "attack_seed",
        )
    }
    run_row = {
        "run_id": meta["run_id"],
        "protocol_label": meta["protocol_label"],
        "eta": eta,
        "beta": EXPECTED_BETA,
        "offline_stake_target": target,
        "actual_offline_stake_share": actual_stake,
        "offline_validator_count": len(outage_ids),
        "seed_value": seed,
        "outage_start_epoch": EXPECTED_START,
        "outage_end_epoch_exclusive": EXPECTED_END,
        "pre_outage_duties": len(pre_duties),
        "outage_duties": len(outage_duties),
        "outage_missed_duties": len(missed),
        "outage_missed_slot_rate": len(missed) / len(outage_duties),
        "git_commit_sha": config_record["git_commit_sha"],
        "assignment_sha256": meta["outage_assignment_sha256"],
        "graph_sha256": canonical_graph_hash(run_dir / "graph.json"),
        "initial_stake_sha256": sha256_json(initial_stakes),
        "rng_seed_sha256": sha256_json(rng_seeds),
        "generated_tx_total": sum(generated),
        "generated_tx_by_epoch_sha256": sha256_json(generated),
        "complete": True,
        "finite_metrics": True,
    }
    audit = {
        "config": canonical_config(config),
        "outage_ids": tuple(sorted(outage_ids)),
        "actual_stake": actual_stake,
        "assignment": meta["outage_assignment_sha256"],
        "graph": run_row["graph_sha256"],
        "stakes": run_row["initial_stake_sha256"],
        "rng": run_row["rng_seed_sha256"],
        "generated_total": run_row["generated_tx_total"],
        "generated_epochs": run_row["generated_tx_by_epoch_sha256"],
    }
    return run_row, epoch_rows, audit


def load_and_validate(raw_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not raw_root.is_dir():
        raise FileNotFoundError(raw_root)
    run_rows: list[dict[str, Any]] = []
    epoch_rows: list[dict[str, Any]] = []
    audits: dict[tuple[float, int, float], dict[str, Any]] = {}
    for run_dir in sorted(path for path in raw_root.iterdir() if path.is_dir()):
        run, epochs, audit = load_run(run_dir)
        key = (float(run["offline_stake_target"]), int(run["seed_value"]), float(run["eta"]))
        if key in audits:
            raise ValueError(f"duplicate matrix key: {key}")
        audits[key] = audit
        run_rows.append(run)
        epoch_rows.extend(epochs)

    expected_keys = {
        (target, seed, eta)
        for target in EXPECTED_TARGETS
        for seed in EXPECTED_SEEDS
        for eta in EXPECTED_ETAS
    }
    if len(run_rows) != EXPECTED_RUNS or set(audits) != expected_keys:
        missing = sorted(expected_keys - set(audits))
        extra = sorted(set(audits) - expected_keys)
        raise ValueError(f"incomplete 180-run matrix; missing={missing}, extra={extra}")

    shared_fields = ("config", "outage_ids", "actual_stake", "assignment", "graph", "stakes", "rng", "generated_total")
    epoch_workload_mismatches = []
    for target in EXPECTED_TARGETS:
        for seed in EXPECTED_SEEDS:
            variants = [audits[(target, seed, eta)] for eta in EXPECTED_ETAS]
            for field in shared_fields:
                if not all(variant[field] == variants[0][field] for variant in variants[1:]):
                    raise ValueError(f"pairing mismatch for {field}, target={target}, seed={seed}")
            if not all(
                variant["generated_epochs"] == variants[0]["generated_epochs"]
                for variant in variants[1:]
            ):
                epoch_workload_mismatches.append((target, seed))
    if epoch_workload_mismatches != [(0.1, 1)]:
        raise ValueError(f"unexpected epoch workload mismatches: {epoch_workload_mismatches}")
    return run_rows, epoch_rows


def group_statistics(
    run_rows: list[dict[str, Any]], epoch_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []

    score_groups: dict[tuple[float, int], list[float]] = defaultdict(list)
    for row in epoch_rows:
        if (
            float(row["eta"]) != 0.5
            or int(row["epoch"]) < FIRST_COMPLETE_SCORE_EPOCH
            or row["outage_group_score_share"] == ""
        ):
            continue
        score_groups[(float(row["offline_stake_target"]), int(row["epoch"]))].append(
            100.0 * float(row["outage_group_score_share"])
        )
    for (target, epoch), values in sorted(score_groups.items()):
        mean, ci, n = mean_ci95(values)
        if n != 20:
            raise ValueError(f"score group target={target}, epoch={epoch} has n={n}")
        output.append(
            {
                "figure": "score_dynamics",
                "metric": "outage_group_score_share_percent",
                "eta": 0.5,
                "offline_stake_target": target,
                "epoch": epoch,
                "mean": mean,
                "ci95_halfwidth": ci,
                "n": n,
            }
        )

    weight_groups: dict[tuple[float, int], list[float]] = defaultdict(list)
    for row in epoch_rows:
        if float(row["offline_stake_target"]) != 0.2:
            continue
        weight_groups[(float(row["eta"]), int(row["epoch"]))].append(
            100.0 * float(row["outage_group_proposer_weight_share"])
        )
    for (eta, epoch), values in sorted(weight_groups.items()):
        mean, ci, n = mean_ci95(values)
        if n != 20:
            raise ValueError(f"weight group eta={eta}, epoch={epoch} has n={n}")
        output.append(
            {
                "figure": "weight_dynamics",
                "metric": "outage_group_proposer_weight_share_percent",
                "eta": eta,
                "offline_stake_target": 0.2,
                "epoch": epoch,
                "mean": mean,
                "ci95_halfwidth": ci,
                "n": n,
            }
        )

    missed_groups: dict[tuple[float, float], list[float]] = defaultdict(list)
    for row in run_rows:
        missed_groups[(float(row["eta"]), float(row["offline_stake_target"]))].append(
            100.0 * float(row["outage_missed_slot_rate"])
        )
    for (eta, target), values in sorted(missed_groups.items()):
        mean, ci, n = mean_ci95(values)
        if n != 20:
            raise ValueError(f"missed-slot group eta={eta}, target={target} has n={n}")
        output.append(
            {
                "figure": "missed_slots",
                "metric": "outage_missed_slot_rate_percent",
                "eta": eta,
                "offline_stake_target": target,
                "epoch": "",
                "mean": mean,
                "ci95_halfwidth": ci,
                "n": n,
            }
        )
    return output


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
    axis.grid(axis="y", color=GRID_GRAY, linewidth=0.7, zorder=0.5)
    axis.spines["left"].set_linewidth(0.9)
    axis.spines["bottom"].set_linewidth(0.9)
    axis.tick_params(width=0.8, length=3)


def outage_context(axis: Any, ymax: float) -> None:
    axis.axvspan(EXPECTED_START, EXPECTED_END - 1, color=LIGHT_GRAY, alpha=0.16, zorder=0)
    axis.axvline(EXPECTED_START, color=LIGHT_GRAY, linestyle="--", linewidth=1.0, zorder=1)
    axis.text(
        EXPECTED_START + 2,
        ymax * 0.965,
        "Outage onset",
        color=GRAY,
        fontsize=7.0,
        ha="left",
        va="top",
        zorder=5,
    )


def legend(axis: Any, *, loc: str) -> None:
    axis.legend(
        loc=loc,
        frameon=True,
        framealpha=0.92,
        facecolor="white",
        edgecolor="#D0D0D0",
        borderpad=0.35,
        handlelength=2.0,
        handletextpad=0.5,
        labelspacing=0.3,
    )


def save(fig: Any, output: Path) -> tuple[Path, Path]:
    output.parent.mkdir(parents=True, exist_ok=True)
    pdf = output.with_suffix(".pdf")
    png = output.with_suffix(".png")
    fig.savefig(pdf, facecolor="white")
    fig.savefig(png, dpi=300, facecolor="white")
    plt.close(fig)
    return pdf, png


def plot_score(groups: list[dict[str, Any]], output: Path) -> tuple[Path, Path]:
    fig, axis = plt.subplots(figsize=(3.45, 2.55))
    ymax = 34.0
    outage_context(axis, ymax)
    for target in EXPECTED_TARGETS:
        style = TARGET_STYLES[target]
        rows = sorted(
            (
                row
                for row in groups
                if row["figure"] == "score_dynamics"
                and math.isclose(float(row["offline_stake_target"]), target)
            ),
            key=lambda row: int(row["epoch"]),
        )
        x = [int(row["epoch"]) for row in rows]
        y = [float(row["mean"]) for row in rows]
        ci = [float(row["ci95_halfwidth"]) for row in rows]
        axis.fill_between(
            x,
            [value - error for value, error in zip(y, ci)],
            [value + error for value, error in zip(y, ci)],
            color=style["color"],
            alpha=0.11,
            linewidth=0,
            zorder=2,
        )
        axis.plot(
            x,
            y,
            color=style["color"],
            linestyle=style["linestyle"],
            marker=style["marker"],
            markerfacecolor=style["fill"],
            markeredgecolor=style["color"],
            markeredgewidth=0.9,
            markevery=10,
            linewidth=1.2,
            markersize=3.6,
            label=style["label"],
            zorder=3,
        )
    axis.set_xlabel("Epoch")
    axis.set_ylabel("Outage-group score share (%)")
    axis.set_xlim(0, 129)
    axis.set_xticks([0, 30, 60, 90, 120])
    axis.set_ylim(0, ymax)
    decorate(axis)
    legend(axis, loc="upper right")
    fig.subplots_adjust(left=0.15, right=0.97, bottom=0.19, top=0.96)
    return save(fig, output / "trail_outage_score_dynamics")


def plot_weight(groups: list[dict[str, Any]], output: Path) -> tuple[Path, Path]:
    fig, axis = plt.subplots(figsize=(3.45, 2.55))
    ymax = 22.0
    outage_context(axis, ymax)
    for eta in EXPECTED_ETAS:
        style = ETA_STYLES[eta]
        rows = sorted(
            (
                row
                for row in groups
                if row["figure"] == "weight_dynamics"
                and math.isclose(float(row["eta"]), eta)
            ),
            key=lambda row: int(row["epoch"]),
        )
        x = [int(row["epoch"]) for row in rows]
        y = [float(row["mean"]) for row in rows]
        ci = [float(row["ci95_halfwidth"]) for row in rows]
        axis.fill_between(
            x,
            [value - error for value, error in zip(y, ci)],
            [value + error for value, error in zip(y, ci)],
            color=style["color"],
            alpha=0.11,
            linewidth=0,
            zorder=2,
        )
        axis.plot(
            x,
            y,
            color=style["color"],
            linestyle=style["linestyle"],
            marker=style["marker"],
            markerfacecolor=style["fill"],
            markeredgecolor=style["color"],
            markeredgewidth=0.9,
            markevery=10,
            linewidth=1.2,
            markersize=3.8,
            label=style["label"],
            zorder=3,
        )
    axis.set_xlabel("Epoch")
    axis.set_ylabel("Outage-group weight (%)")
    axis.set_xlim(0, 129)
    axis.set_xticks([0, 30, 60, 90, 120])
    axis.set_ylim(0, ymax)
    decorate(axis)
    legend(axis, loc="lower left")
    fig.subplots_adjust(left=0.17, right=0.97, bottom=0.19, top=0.96)
    return save(fig, output / "trail_outage_weight_dynamics")


def plot_missed(groups: list[dict[str, Any]], output: Path) -> tuple[Path, Path]:
    fig, axis = plt.subplots(figsize=(3.45, 2.55))
    for eta in EXPECTED_ETAS:
        style = ETA_STYLES[eta]
        rows = sorted(
            (
                row
                for row in groups
                if row["figure"] == "missed_slots" and math.isclose(float(row["eta"]), eta)
            ),
            key=lambda row: float(row["offline_stake_target"]),
        )
        x = [100.0 * float(row["offline_stake_target"]) for row in rows]
        y = [float(row["mean"]) for row in rows]
        ci = [float(row["ci95_halfwidth"]) for row in rows]
        axis.errorbar(
            x,
            y,
            yerr=ci,
            color=style["color"],
            linestyle=style["linestyle"],
            marker=style["marker"],
            markerfacecolor=style["fill"],
            markeredgecolor=style["color"],
            markeredgewidth=1.0,
            linewidth=1.2,
            markersize=4.5,
            capsize=2.5,
            label=style["label"],
            zorder=3,
        )
    target_30 = {
        float(row["eta"]): float(row["mean"])
        for row in groups
        if row["figure"] == "missed_slots"
        and math.isclose(float(row["offline_stake_target"]), 0.3)
    }
    reduction = target_30[0.0] - target_30[1.0]
    axis.text(
        30.0,
        target_30[1.0] - 2.6,
        rf"${reduction:.2f}$ pp" "\n" r"below $\eta=0$",
        color=GRAY,
        fontsize=7.0,
        ha="center",
        va="top",
        zorder=4,
    )
    axis.set_xlabel("Offline stake target (%)")
    axis.set_ylabel("Missed-slot rate (%)")
    axis.set_xlim(8, 32)
    axis.set_ylim(0, 32)
    axis.set_xticks([10, 20, 30])
    axis.set_yticks([0, 10, 20, 30])
    decorate(axis)
    legend(axis, loc="upper left")
    fig.subplots_adjust(left=0.15, right=0.97, bottom=0.19, top=0.96)
    return save(fig, output / "trail_outage_missed_slots")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", type=Path, default=RAW_ROOT)
    parser.add_argument("--processed-dir", type=Path, default=PROCESSED)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT)
    args = parser.parse_args()

    run_rows, epoch_rows = load_and_validate(args.raw_root)
    groups = group_statistics(run_rows, epoch_rows)

    run_fields = list(run_rows[0])
    epoch_fields = list(epoch_rows[0])
    group_fields = [
        "figure",
        "metric",
        "eta",
        "offline_stake_target",
        "epoch",
        "mean",
        "ci95_halfwidth",
        "n",
    ]
    write_csv(args.processed_dir / RUNS_CSV.name, run_rows, run_fields)
    write_csv(args.processed_dir / EPOCHS_CSV.name, epoch_rows, epoch_fields)
    write_csv(args.processed_dir / GROUPS_CSV.name, groups, group_fields)

    configure_style()
    outputs = [
        *plot_score(groups, args.output_dir),
        *plot_weight(groups, args.output_dir),
        *plot_missed(groups, args.output_dir),
    ]
    print(f"validated runs: {len(run_rows)}")
    print(f"processed epoch rows: {len(epoch_rows)}")
    print(f"group rows: {len(groups)}")
    for path in (
        args.processed_dir / RUNS_CSV.name,
        args.processed_dir / EPOCHS_CSV.name,
        args.processed_dir / GROUPS_CSV.name,
        *outputs,
    ):
        print(path.relative_to(ROOT))


if __name__ == "__main__":
    main()
