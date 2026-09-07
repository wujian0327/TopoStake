#!/usr/bin/env python3
"""Validate and summarize the merged TRAIL relay-participation raw suite."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from scipy.stats import t as student_t

from adaptive_participation_report import cohort_inclusion_metrics
from run_experiments import ROOT


MECHANISMS = {
    "pos": "PoS",
    "topostake_eta0": "Fee-only",
    "topostake": "Full TRAIL",
}
MECHANISM_ORDER = tuple(MECHANISMS.values())
COSTS = (1.0, 2.0, 3.0)
SEEDS = tuple(range(100, 120))
EXPECTED_EPOCHS = 200
ANALYSIS_START = 100
FOLLOWUP_EPOCHS = 10
VALIDATORS = 100
RAW_ROOT = ROOT / "results/raw/frozen_v1_adaptive_participation_main"
PROCESSED = ROOT / "results/processed"
REQUIRED_FILES = (
    "experiment_meta.json",
    "run_config.json",
    "runner_status.json",
    "run_summary.json",
    "adaptive_relay_metrics.csv",
    "epoch_metrics.csv",
    "node_epoch_metrics.csv",
    "generation_samples.csv",
    "inclusion_samples.csv",
    "graph.json",
)


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot read JSON {path}: {exc}") from exc


def read_csv(path: Path) -> list[dict[str, str]]:
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))
    except OSError as exc:
        raise ValueError(f"cannot read CSV {path}: {exc}") from exc


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty CSV {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def finite(value: Any, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {field}: {value!r}") from exc
    if not math.isfinite(result):
        raise ValueError(f"non-finite {field}: {value!r}")
    return result


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def key_from_meta(meta: dict[str, Any]) -> tuple[str, float, int]:
    return (
        str(meta.get("protocol_label")),
        finite(meta.get("adaptive_cost_median_multiplier"), "cost multiplier"),
        int(meta.get("seed_value", -1)),
    )


def expected_keys() -> set[tuple[str, float, int]]:
    return {
        (protocol, cost, seed)
        for protocol in MECHANISMS
        for cost in COSTS
        for seed in SEEDS
    }


def discover_runs(raw_root: Path) -> dict[tuple[str, float, int], Path]:
    if not raw_root.is_dir():
        raise ValueError(f"raw root does not exist: {raw_root}")
    selected: dict[tuple[str, float, int], Path] = {}
    for meta_path in sorted(raw_root.rglob("experiment_meta.json")):
        meta = read_json(meta_path)
        key = key_from_meta(meta)
        if key not in expected_keys():
            continue
        if key in selected:
            raise ValueError(f"duplicate logical run {key}: {selected[key]} and {meta_path.parent}")
        missing = [name for name in REQUIRED_FILES if not (meta_path.parent / name).is_file()]
        if missing:
            raise ValueError(f"{meta_path.parent} missing required files: {missing}")
        selected[key] = meta_path.parent
    missing_keys = sorted(expected_keys() - set(selected))
    extra_keys = sorted(set(selected) - expected_keys())
    if missing_keys or extra_keys or len(selected) != 180:
        raise ValueError(
            f"condition coverage mismatch: found={len(selected)}, "
            f"missing={missing_keys}, extra={extra_keys}"
        )
    return selected


def mean_ci95(values: Iterable[float]) -> dict[str, float | int]:
    sample = [finite(value, "sample value") for value in values]
    if len(sample) < 2:
        raise ValueError("Student t CI requires at least two observations")
    mean = statistics.mean(sample)
    half = (
        float(student_t.ppf(0.975, len(sample) - 1))
        * statistics.stdev(sample)
        / math.sqrt(len(sample))
    )
    return {
        "mean": mean,
        "ci95": half,
        "ci95_low": mean - half,
        "ci95_high": mean + half,
        "n": len(sample),
    }


def welch_ci95(first: Iterable[float], second: Iterable[float]) -> dict[str, float | int]:
    x = [finite(value, "Welch sample") for value in first]
    y = [finite(value, "Welch sample") for value in second]
    if len(x) < 2 or len(y) < 2:
        raise ValueError("Welch CI requires at least two observations per sample")
    vx = statistics.variance(x)
    vy = statistics.variance(y)
    ax = vx / len(x)
    ay = vy / len(y)
    se = math.sqrt(ax + ay)
    if se == 0.0:
        df = math.inf
        half = 0.0
    else:
        df = (ax + ay) ** 2 / (
            ax * ax / (len(x) - 1) + ay * ay / (len(y) - 1)
        )
        half = float(student_t.ppf(0.975, df)) * se
    difference = statistics.mean(x) - statistics.mean(y)
    return {
        "mean_difference": difference,
        "ci95": half,
        "ci95_low": difference - half,
        "ci95_high": difference + half,
        "n_first": len(x),
        "n_second": len(y),
        "welch_df": df,
    }


def summarize_run(
    key: tuple[str, float, int], run_dir: Path
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    protocol, multiplier, seed = key
    mechanism = MECHANISMS[protocol]
    meta = read_json(run_dir / "experiment_meta.json")
    status = read_json(run_dir / "runner_status.json")
    summary = read_json(run_dir / "run_summary.json")
    run_config = read_json(run_dir / "run_config.json")
    adaptive = read_csv(run_dir / "adaptive_relay_metrics.csv")
    epoch_metrics = read_csv(run_dir / "epoch_metrics.csv")
    nodes = read_csv(run_dir / "node_epoch_metrics.csv")
    generated = read_csv(run_dir / "generation_samples.csv")
    inclusion = read_csv(run_dir / "inclusion_samples.csv")
    problems: list[str] = []

    if status.get("status") != "ok":
        problems.append("runner_status")
    completed_epochs = int(summary.get("completed_epochs", -1))
    if completed_epochs != EXPECTED_EPOCHS:
        problems.append("completed_epochs")
    if sorted(int(row.get("epoch", -1)) for row in adaptive) != list(range(EXPECTED_EPOCHS)):
        problems.append("adaptive_epoch_coverage")
    if len(epoch_metrics) != EXPECTED_EPOCHS:
        problems.append("epoch_metric_coverage")
    node_counts = Counter(int(row.get("epoch", -1)) for row in nodes)
    if set(node_counts) != set(range(EXPECTED_EPOCHS)) or any(
        node_counts[epoch] != VALIDATORS for epoch in range(EXPECTED_EPOCHS)
    ):
        problems.append("node_epoch_coverage")

    epoch0 = sorted(
        (row for row in nodes if int(row["epoch"]) == 0),
        key=lambda row: int(row["validator_id"]),
    )
    active0 = [row for row in epoch0 if row["relay_profile"] == "active"]
    lazy0 = [row for row in epoch0 if row["relay_profile"] == "lazy"]
    if len(active0) != 50 or len(lazy0) != 50:
        problems.append("initial_50_50")

    total_stake = sum(finite(row["economic_stake"], "economic_stake") for row in epoch0)
    initial_active_stake = (
        sum(finite(row["economic_stake"], "economic_stake") for row in active0)
        / total_stake
    )
    for raw in adaptive:
        finite(raw["active_fraction"], "active_fraction")
        finite(raw["active_stake_share"], "active_stake_share")
    for raw in nodes:
        finite(raw["economic_stake"], "economic_stake")
        finite(raw["relay_cost_per_forward"], "relay_cost_per_forward")

    steady = [
        row
        for row in adaptive
        if ANALYSIS_START <= int(row["epoch"]) < EXPECTED_EPOCHS
    ]
    if len(steady) != EXPECTED_EPOCHS - ANALYSIS_START:
        problems.append("steady_epoch_coverage")
    steady_active_stake = statistics.mean(
        finite(row["active_stake_share"], "active_stake_share") for row in steady
    )
    steady_active_fraction = statistics.mean(
        finite(row["active_fraction"], "active_fraction") for row in steady
    )

    rmst = cohort_inclusion_metrics(
        generated,
        inclusion,
        warmup_epochs=ANALYSIS_START,
        max_epochs=EXPECTED_EPOCHS,
        slots_per_epoch=int(meta["slot_per_epoch"]),
        slot_duration_s=finite(meta["slot_duration"], "slot_duration"),
        followup_epochs=int(meta["adaptive_followup_epochs"]),
    )
    rmst_value = finite(
        rmst["restricted_mean_inclusion_latency_s"],
        "restricted mean inclusion time",
    )

    config = run_config.get("config", {})
    consensus = str(config.get("consensus", ""))
    eta = finite(config.get("topostake_config", {}).get("eta", 0.0), "eta")
    if mechanism == "PoS" and consensus != "POS":
        problems.append("mechanism_config")
    if mechanism == "Fee-only" and (consensus != "TopoStake" or eta != 0.0):
        problems.append("mechanism_config")
    if mechanism == "Full TRAIL" and (consensus != "TopoStake" or eta != 0.5):
        problems.append("mechanism_config")

    background_generated = int(summary.get("generated_tx", -1))
    if background_generated < 0:
        problems.append("background_transaction_count")

    row = {
        "run_id": str(meta.get("run_id", run_dir.name)),
        "mechanism": mechanism,
        "protocol_label": protocol,
        "cost_multiplier": multiplier,
        "seed_value": seed,
        "raw_source": str(run_dir.relative_to(ROOT)),
        "status": status.get("status", "missing"),
        "complete": completed_epochs == EXPECTED_EPOCHS,
        "finite_metrics": True,
        "valid": not problems,
        "problems": "|".join(problems),
        "completed_epochs": completed_epochs,
        "steady_epoch_first": ANALYSIS_START,
        "steady_epoch_last": EXPECTED_EPOCHS - 1,
        "steady_epoch_count": len(steady),
        "initial_active_validators": len(active0),
        "initial_lazy_validators": len(lazy0),
        "initial_active_relay_stake_share": initial_active_stake,
        "steady_active_validator_fraction": steady_active_fraction,
        "steady_active_relay_stake_share": steady_active_stake,
        "restricted_mean_inclusion_time_s": rmst_value,
        "inclusion_generation_epoch_first": ANALYSIS_START,
        "inclusion_generation_epoch_last": EXPECTED_EPOCHS - FOLLOWUP_EPOCHS - 1,
        "inclusion_followup_window_epochs": int(meta["adaptive_followup_epochs"]),
        "inclusion_followup_window_s": rmst["followup_horizon_s"],
        "inclusion_cohort_generated_tx": rmst["cohort_generated_tx"],
        "inclusion_cohort_included_tx": rmst["cohort_included_tx"],
        "inclusion_within_horizon_rate": rmst["inclusion_within_horizon_rate"],
        "background_transactions_generated": background_generated,
        "background_generation_samples_recorded": len(generated),
        "node_num": int(meta["node_num"]),
        "tx_rate": finite(meta["tx_rate"], "tx_rate"),
        "workload_seed": int(meta["workload_seed"]),
        "run_revision": meta.get("run_revision", ""),
        "git_commit_sha": run_config.get("git_commit_sha", ""),
        "git_source_diff_sha256": run_config.get("git_source_diff_sha256", ""),
        "run_config_sha256": file_hash(run_dir / "run_config.json"),
    }
    epoch_rows = [
        {
            "run_id": row["run_id"],
            "mechanism": mechanism,
            "cost_multiplier": multiplier,
            "seed_value": seed,
            "epoch": int(raw["epoch"]),
            "active_validator_fraction": finite(raw["active_fraction"], "active_fraction"),
            "active_relay_stake_share": finite(raw["active_stake_share"], "active_stake_share"),
        }
        for raw in adaptive
    ]
    return row, epoch_rows


def blank_group_row(row_type: str, mechanism: str, cost: float, n: Any) -> dict[str, Any]:
    return {
        "row_type": row_type,
        "mechanism": mechanism,
        "cost_multiplier": cost,
        "n": n,
        "active_relay_stake_mean": "",
        "active_relay_stake_ci95": "",
        "active_relay_stake_ci95_low": "",
        "active_relay_stake_ci95_high": "",
        "restricted_mean_inclusion_time_s_mean": "",
        "restricted_mean_inclusion_time_s_ci95": "",
        "restricted_mean_inclusion_time_s_ci95_low": "",
        "restricted_mean_inclusion_time_s_ci95_high": "",
        "background_transactions_mean": "",
        "background_transactions_ci95": "",
        "background_transactions_ci95_low": "",
        "background_transactions_ci95_high": "",
        "background_transactions_min": "",
        "background_transactions_max": "",
        "full_minus_fee_active_stake_mean": "",
        "full_minus_fee_active_stake_ci95": "",
        "full_minus_fee_active_stake_ci95_low": "",
        "full_minus_fee_active_stake_ci95_high": "",
        "full_minus_fee_inclusion_time_s_mean": "",
        "full_minus_fee_inclusion_time_s_ci95": "",
        "full_minus_fee_inclusion_time_s_ci95_low": "",
        "full_minus_fee_inclusion_time_s_ci95_high": "",
        "welch_df_active_stake": "",
        "welch_df_inclusion_time": "",
    }


def interval(mean: float, low: float, high: float, *, scale: float = 1.0, digits: int = 3, unit: str = "") -> str:
    return (
        f"{scale * mean:.{digits}f}{unit} "
        f"[{scale * low:.{digits}f}, {scale * high:.{digits}f}]"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", type=Path, default=RAW_ROOT)
    args = parser.parse_args()
    raw_root = args.raw_root.resolve()
    selected = discover_runs(raw_root)

    run_rows: list[dict[str, Any]] = []
    epoch_rows: list[dict[str, Any]] = []
    for key, run_dir in sorted(selected.items()):
        row, epochs = summarize_run(key, run_dir)
        run_rows.append(row)
        epoch_rows.extend(epochs)
    invalid = [row for row in run_rows if not row["valid"]]
    if invalid:
        raise ValueError(
            "invalid runs: "
            + repr([(row["run_id"], row["problems"]) for row in invalid])
        )
    if len(run_rows) != 180 or len(epoch_rows) != 36_000:
        raise ValueError(
            f"unexpected output grain: {len(run_rows)} runs, {len(epoch_rows)} epochs"
        )

    grouped: dict[tuple[str, float], list[dict[str, Any]]] = defaultdict(list)
    for row in run_rows:
        grouped[(row["mechanism"], float(row["cost_multiplier"]))].append(row)

    group_rows: list[dict[str, Any]] = []
    for mechanism in MECHANISM_ORDER:
        for cost in COSTS:
            sample = grouped[(mechanism, cost)]
            if len(sample) != 20:
                raise ValueError(f"expected 20 runs for {(mechanism, cost)}")
            active = mean_ci95(row["steady_active_relay_stake_share"] for row in sample)
            inclusion = mean_ci95(row["restricted_mean_inclusion_time_s"] for row in sample)
            workload = mean_ci95(row["background_transactions_generated"] for row in sample)
            output = blank_group_row("mechanism", mechanism, cost, 20)
            output.update({
                "active_relay_stake_mean": active["mean"],
                "active_relay_stake_ci95": active["ci95"],
                "active_relay_stake_ci95_low": active["ci95_low"],
                "active_relay_stake_ci95_high": active["ci95_high"],
                "restricted_mean_inclusion_time_s_mean": inclusion["mean"],
                "restricted_mean_inclusion_time_s_ci95": inclusion["ci95"],
                "restricted_mean_inclusion_time_s_ci95_low": inclusion["ci95_low"],
                "restricted_mean_inclusion_time_s_ci95_high": inclusion["ci95_high"],
                "background_transactions_mean": workload["mean"],
                "background_transactions_ci95": workload["ci95"],
                "background_transactions_ci95_low": workload["ci95_low"],
                "background_transactions_ci95_high": workload["ci95_high"],
                "background_transactions_min": min(row["background_transactions_generated"] for row in sample),
                "background_transactions_max": max(row["background_transactions_generated"] for row in sample),
            })
            group_rows.append(output)

    for cost in COSTS:
        full = grouped[("Full TRAIL", cost)]
        fee = grouped[("Fee-only", cost)]
        active = welch_ci95(
            (row["steady_active_relay_stake_share"] for row in full),
            (row["steady_active_relay_stake_share"] for row in fee),
        )
        inclusion = welch_ci95(
            (row["restricted_mean_inclusion_time_s"] for row in full),
            (row["restricted_mean_inclusion_time_s"] for row in fee),
        )
        output = blank_group_row(
            "welch_full_vs_fee", "Full TRAIL - Fee-only", cost, "20 + 20"
        )
        output.update({
            "full_minus_fee_active_stake_mean": active["mean_difference"],
            "full_minus_fee_active_stake_ci95": active["ci95"],
            "full_minus_fee_active_stake_ci95_low": active["ci95_low"],
            "full_minus_fee_active_stake_ci95_high": active["ci95_high"],
            "full_minus_fee_inclusion_time_s_mean": inclusion["mean_difference"],
            "full_minus_fee_inclusion_time_s_ci95": inclusion["ci95"],
            "full_minus_fee_inclusion_time_s_ci95_low": inclusion["ci95_low"],
            "full_minus_fee_inclusion_time_s_ci95_high": inclusion["ci95_high"],
            "welch_df_active_stake": active["welch_df"],
            "welch_df_inclusion_time": inclusion["welch_df"],
        })
        group_rows.append(output)

    initial_values = [float(row["initial_active_relay_stake_share"]) for row in run_rows]
    commits = Counter(str(row["git_commit_sha"]) for row in run_rows)
    revisions = Counter(str(row["run_revision"]) for row in run_rows)
    analysis_commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    worktree_status = subprocess.check_output(
        ["git", "status", "--short"], cwd=ROOT, text=True
    ).splitlines()
    audit = {
        "raw_root": str(raw_root.relative_to(ROOT)),
        "observed_runs": len(run_rows),
        "unique_condition_runs": len(selected),
        "valid_runs": len(run_rows),
        "failed_runs": 0,
        "duplicate_keys": 0,
        "missing_keys": 0,
        "nan_or_inf_runs": 0,
        "epoch_rows": len(epoch_rows),
        "completed_epochs_per_run": EXPECTED_EPOCHS,
        "initial_active_validators_per_run": 50,
        "initial_lazy_validators_per_run": 50,
        "steady_state_epochs": "100-199",
        "runs_per_configuration": 20,
        "analysis_independence": "independent runs per configuration; not paired",
        "group_ci": "two-sided 95% Student t, df=19",
        "mechanism_difference_ci": "two-sided 95% Welch two-sample t",
        "initial_active_relay_stake_mean": statistics.mean(initial_values),
        "initial_active_relay_stake_min": min(initial_values),
        "initial_active_relay_stake_max": max(initial_values),
        "git_commit_counts": dict(commits),
        "run_revision_counts": dict(revisions),
        "analysis_git_commit": analysis_commit,
        "analysis_worktree_clean": not bool(worktree_status),
        "analysis_report_script_sha256": file_hash(Path(__file__)),
        "plot_script_sha256": file_hash(
            ROOT / "analysis/plot_trail_relay_participation.py"
        ),
        "workload_generation_code_review": (
            "Background Poisson sampling uses tx_rate, slot_duration, and "
            "workload_seed and contains no consensus/mechanism branch. "
            "Nonblocking enqueue success can make realized counts differ."
        ),
    }

    write_csv(PROCESSED / "trail_relay_participation_runs.csv", run_rows)
    write_csv(PROCESSED / "trail_relay_participation_epochs.csv", epoch_rows)
    write_csv(PROCESSED / "trail_relay_participation_groups.csv", group_rows)
    (PROCESSED / "trail_relay_participation_consistency.json").write_text(
        json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    report = [
        "# TRAIL relay-participation results",
        "",
        "## Data and methods",
        "",
        "- Raw source: `results/raw/frozen_v1_adaptive_participation_main/`.",
        "- Completeness: 180/180 valid runs, with 20 runs per configuration; no duplicate, missing, failed, NaN, or Inf runs.",
        "- Each run completed 200 epochs and initialized 50 active and 50 lazy validators.",
        "- Active relay stake is averaged within each run over epochs 100--199, then summarized over 20 independent runs with a two-sided 95% Student's t interval.",
        "- Restricted mean inclusion time uses transactions generated in epochs 100--189, with a complete 10-epoch (50 s) follow-up; transactions not included within the horizon are assigned 50 s.",
        "- Mechanism contrasts use independent-sample Full TRAIL minus Fee-only differences with two-sided 95% Welch t intervals. No paired intervals are calculated.",
        "- Background generation uses the same Poisson model and parameters for every mechanism; there is no mechanism branch in background sampling. Successfully queued counts can vary because enqueueing is nonblocking.",
        "",
        "## Configuration summaries",
        "",
        "| Mechanism | Cost | Runs | Active relay stake, mean [95% CI] | Restricted mean inclusion time, mean [95% CI] | Background transactions, mean [95% CI] (range) |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in group_rows:
        if row["row_type"] != "mechanism":
            continue
        report.append(
            f"| {row['mechanism']} | {float(row['cost_multiplier']):g}x | 20 | "
            f"{interval(float(row['active_relay_stake_mean']), float(row['active_relay_stake_ci95_low']), float(row['active_relay_stake_ci95_high']), scale=100, unit='%')} | "
            f"{interval(float(row['restricted_mean_inclusion_time_s_mean']), float(row['restricted_mean_inclusion_time_s_ci95_low']), float(row['restricted_mean_inclusion_time_s_ci95_high']), digits=4, unit=' s')} | "
            f"{interval(float(row['background_transactions_mean']), float(row['background_transactions_ci95_low']), float(row['background_transactions_ci95_high']), digits=1)} "
            f"({row['background_transactions_min']}--{row['background_transactions_max']}) |"
        )
    report.extend([
        "",
        "## Welch Full TRAIL versus Fee-only contrasts",
        "",
        "| Cost | Active relay stake: Full minus Fee-only [95% CI] | Inclusion time: Full minus Fee-only [95% CI] |",
        "|---:|---:|---:|",
    ])
    for row in group_rows:
        if row["row_type"] != "welch_full_vs_fee":
            continue
        report.append(
            f"| {float(row['cost_multiplier']):g}x | "
            f"{interval(float(row['full_minus_fee_active_stake_mean']), float(row['full_minus_fee_active_stake_ci95_low']), float(row['full_minus_fee_active_stake_ci95_high']), scale=100, unit=' pp')} | "
            f"{interval(float(row['full_minus_fee_inclusion_time_s_mean']), float(row['full_minus_fee_inclusion_time_s_ci95_low']), float(row['full_minus_fee_inclusion_time_s_ci95_high']), digits=4, unit=' s')} |"
        )
    report.extend([
        "",
        "## Initial active relay stake",
        "",
        f"Across 180 run records: mean {100 * statistics.mean(initial_values):.3f}%, minimum {100 * min(initial_values):.3f}%, maximum {100 * max(initial_values):.3f}%.",
        "",
        "## Provenance",
        "",
        f"- Simulator commit counts: {dict(commits)}.",
        f"- Run revision counts: {dict(revisions)}.",
        f"- Processing code: commit `{analysis_commit}`; report script SHA-256 `{file_hash(Path(__file__))}`; plot script SHA-256 `{file_hash(ROOT / 'analysis/plot_trail_relay_participation.py')}`.",
        "- The two simulator commits have identical `src/` trees; the later commit expands the PoS cost matrix and updates analysis code.",
        "- Historical run configs record commit SHA but not a working-tree diff fingerprint. The 20 recovered PoS runs additionally have `pos_missing_provenance.json` containing rebuilt-binary and config hashes.",
    ])
    (PROCESSED / "trail_relay_participation_report.md").write_text(
        "\n".join(report) + "\n", encoding="utf-8"
    )
    print(json.dumps(audit, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
