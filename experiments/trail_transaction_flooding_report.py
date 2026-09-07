#!/usr/bin/env python3
"""Validate and summarize the isolated TRAIL transaction-flooding sweep."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from scipy.stats import t as student_t

from run_experiments import ROOT, expand_runs, load_yaml


METRICS = [
    "attack_tx_submitted",
    "attack_tx_included",
    "attack_fee_paid",
    "attack_irrecoverable_cost_paid",
    "attack_certified_path_cost",
    "attack_proposer_fee_recovery",
    "attack_relay_fee_recovery",
    "attack_coalition_raw_contribution",
    "attack_direct_net_cost",
    "adversary_proposer_weight_share_mean",
    "adversary_real_stake_share",
]
ATTACK_ZERO_FIELDS = METRICS[:9]
TOLERANCE = 1e-9
# epoch_metrics.csv stores six decimals while run_summary.json stores full
# precision; this tolerance is only for cross-file serialization agreement.
CSV_ROUNDTRIP_TOLERANCE = 5.1e-7


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def file_hash(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def graph_hash(graph: Any) -> str:
    """Hash an undirected edge set independent of HashMap/serialization order."""
    if not isinstance(graph, list):
        return ""
    edges = sorted(tuple(sorted((str(edge[0]), str(edge[1])))) for edge in graph)
    return canonical_hash(edges)


def finite_number(value: Any) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"non-finite value: {value!r}")
    return number


def mean_ci95(values: Iterable[float]) -> tuple[float, float, float, float]:
    sample = list(values)
    mean = statistics.mean(sample)
    if len(sample) < 2:
        return mean, 0.0, mean, mean
    critical = float(student_t.ppf(0.975, df=len(sample) - 1))
    half_width = critical * statistics.stdev(sample) / math.sqrt(len(sample))
    return mean, half_width, mean - half_width, mean + half_width


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def summarize_run(run: dict[str, Any]) -> dict[str, Any]:
    output_dir = Path(run["output_dir"])
    summary = read_json(output_dir / "run_summary.json")
    status = read_json(output_dir / "runner_status.json")
    run_config = read_json(output_dir / "run_config.json")
    epochs = read_csv(output_dir / "epoch_metrics.csv")
    nodes = read_csv(output_dir / "node_epoch_metrics.csv")
    expected_epochs = int(run["max_epochs"])
    completed_epochs = int(summary.get("completed_epochs", -1))
    warmup = int(run.get("warmup_epochs", 0))
    steady_epochs = [row for row in epochs if int(row["epoch"]) >= warmup]
    finite_metrics = True
    metric_values: dict[str, float] = {}
    try:
        for metric in METRICS[:9]:
            metric_values[metric] = finite_number(summary[metric])
        proposer_values = [
            finite_number(row["adversary_proposer_weight_share"])
            for row in steady_epochs
        ]
        stake_values = [
            finite_number(row["adversary_real_stake_share"])
            for row in steady_epochs
        ]
        if len(steady_epochs) != expected_epochs - warmup:
            raise ValueError("wrong steady epoch count")
        metric_values["adversary_proposer_weight_share_mean"] = statistics.mean(
            proposer_values
        )
        metric_values["adversary_real_stake_share"] = statistics.mean(stake_values)
        for metric in (
            "adversary_proposer_weight_share_mean",
            "adversary_real_stake_share",
        ):
            if (
                abs(metric_values[metric] - finite_number(summary[metric]))
                > CSV_ROUNDTRIP_TOLERANCE
            ):
                raise ValueError(f"raw summary disagrees with epoch data for {metric}")
    except (KeyError, TypeError, ValueError, statistics.StatisticsError):
        finite_metrics = False
        for metric in METRICS:
            metric_values.setdefault(metric, math.nan)

    epoch0_nodes = sorted(
        (
            row["validator_id"],
            row["economic_stake"],
            row["adversarial"],
        )
        for row in nodes
        if row.get("epoch") == "0"
    )
    graph = read_json(output_dir / "graph.json")
    complete = completed_epochs == expected_epochs
    ok = status.get("status") == "ok" and complete and finite_metrics
    row: dict[str, Any] = {
        "run_id": run["run_id"],
        "seed": int(run["seed_value"]),
        "multiplier": float(run["attack_tx_rate_multiplier"]),
        "status": status.get("status", "missing"),
        "complete": complete,
        "finite_metrics": finite_metrics,
        "valid": ok,
        "completed_epochs": completed_epochs,
        "expected_epochs": expected_epochs,
        "coalition_identity_hash": summary.get("coalition_identity_hash", ""),
        "background_workload_hash": summary.get("background_workload_hash", ""),
        "validator_stake_hash": canonical_hash(epoch0_nodes) if epoch0_nodes else "",
        "network_topology_hash": graph_hash(graph),
        "run_config_sha256": file_hash(output_dir / "run_config.json"),
        "git_commit_sha": run_config.get("git_commit_sha", ""),
        "git_source_diff_sha256": run_config.get("git_source_diff_sha256", ""),
        "graph_seed": run.get("graph_seed"),
        "wallet_seed": run.get("wallet_seed"),
        "workload_seed": run.get("workload_seed"),
        "election_seed": run.get("election_seed"),
        "failure_seed": run.get("failure_seed"),
        "attack_seed": run.get("attack_seed"),
    }
    row.update(metric_values)
    return row


def paired_violations(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    fields = [
        "coalition_identity_hash",
        "adversary_real_stake_share",
        "validator_stake_hash",
        "network_topology_hash",
        "background_workload_hash",
        "graph_seed",
        "wallet_seed",
        "workload_seed",
        "election_seed",
        "failure_seed",
    ]
    by_seed: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_seed[int(row["seed"])].append(row)
    for seed, group in sorted(by_seed.items()):
        for field in fields:
            values = [row[field] for row in group]
            equal = (
                max(values) - min(values) <= TOLERANCE
                if field == "adversary_real_stake_share" and all(math.isfinite(v) for v in values)
                else len(set(values)) == 1
            )
            if not equal:
                violations.append({"seed": seed, "field": field, "values": values})
    return violations


def invariant_report(rows: list[dict[str, Any]], fee: float, g_ref: float) -> dict[str, Any]:
    checks: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        submitted = row["attack_tx_submitted"]
        fee_paid = row["attack_fee_paid"]
        irrecoverable = row["attack_irrecoverable_cost_paid"]
        total_recovery = row["attack_proposer_fee_recovery"] + row["attack_relay_fee_recovery"]
        certified = row["attack_certified_path_cost"]
        raw = row["attack_coalition_raw_contribution"]
        direct = row["attack_direct_net_cost"]
        checks["attack_fee_paid_identity"].append(abs(fee_paid - fee * submitted))
        checks["attack_irrecoverable_cost_identity"].append(
            abs(irrecoverable - fee * submitted)
        )
        checks["attack_fee_recovery_upper_bound"].append(max(0.0, total_recovery - fee_paid))
        checks["raw_contribution_lower_bound"].append(max(0.0, g_ref * raw - certified))
        checks["certified_cost_upper_bound"].append(max(0.0, certified - irrecoverable))
        checks["direct_net_cost_lower_bound"].append(max(0.0, irrecoverable - direct))
        checks["direct_net_cost_identity"].append(
            abs(direct - (fee_paid + irrecoverable - total_recovery))
        )
        checks["included_submission_upper_bound"].append(
            max(0.0, row["attack_tx_included"] - submitted)
        )
        if row["multiplier"] == 0.0:
            checks["zero_multiplier"].append(
                max(abs(row[field]) for field in ATTACK_ZERO_FIELDS)
            )
    return {
        name: {
            "max_deviation": max(values, default=0.0),
            "violation_count": sum(value > TOLERANCE for value in values),
        }
        for name, values in checks.items()
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", default="experiments/configs/trail_transaction_flooding.yaml"
    )
    parser.add_argument("--smoke", action="store_true", help="Validate seed 0 only")
    args = parser.parse_args()

    spec = load_yaml((ROOT / args.config).resolve())
    runs = expand_runs(spec, ["transaction_flooding"])
    if args.smoke:
        runs = [run for run in runs if int(run["seed_value"]) == 0]
    expected = 5 if args.smoke else 100
    if len(runs) != expected:
        raise SystemExit(f"expected {expected} configured runs, found {len(runs)}")

    rows = [summarize_run(run) for run in runs]
    valid_rows = [row for row in rows if row["valid"]]
    pairs = paired_violations(valid_rows)
    fee = float(spec["defaults"]["transaction_fee"])
    g_ref = float(spec["defaults"]["topostake_score_cost_reference"])
    invariants = invariant_report(valid_rows, fee, g_ref)

    groups: list[dict[str, Any]] = []
    by_multiplier: dict[float, list[dict[str, Any]]] = defaultdict(list)
    for row in valid_rows:
        by_multiplier[float(row["multiplier"])].append(row)
    for multiplier, group in sorted(by_multiplier.items()):
        result: dict[str, Any] = {"multiplier": multiplier, "n": len(group)}
        for metric in METRICS:
            mean, ci, low, high = mean_ci95(float(row[metric]) for row in group)
            result[f"{metric}_mean"] = mean
            result[f"{metric}_ci95"] = ci
            result[f"{metric}_ci95_low"] = low
            result[f"{metric}_ci95_high"] = high
        groups.append(result)

    suffix = "_smoke" if args.smoke else ""
    processed = ROOT / "results" / "processed"
    run_path = processed / f"trail_transaction_flooding{suffix}_runs.csv"
    group_path = processed / f"trail_transaction_flooding{suffix}_groups.csv"
    audit_path = processed / f"trail_transaction_flooding{suffix}_consistency.json"
    report_path = processed / f"trail_transaction_flooding{suffix}_report.md"
    run_fields = list(rows[0])
    group_fields = list(groups[0]) if groups else ["multiplier", "n"]
    write_csv(run_path, rows, run_fields)
    write_csv(group_path, groups, group_fields)
    audit = {
        "expected_runs": expected,
        "observed_runs": len(rows),
        "valid_runs": len(valid_rows),
        "failed_runs": len(rows) - len(valid_rows),
        "runs_per_multiplier": {
            str(key): len(value) for key, value in sorted(by_multiplier.items())
        },
        "tolerance": TOLERANCE,
        "confidence_interval": "two-sided 95% Student's t",
        "pairing_violation_count": len(pairs),
        "pairing_violations": pairs,
        "invariants": invariants,
        "all_invariants_pass": all(
            value["violation_count"] == 0 for value in invariants.values()
        ),
        "all_runs_valid": len(valid_rows) == expected,
    }
    audit_path.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n")
    report_lines = [
        "# TRAIL transaction-flooding consistency report",
        "",
        f"- Runs: {len(valid_rows)}/{expected} valid; {len(rows) - len(valid_rows)} failed",
        f"- Pairing violations: {len(pairs)}",
        f"- Numeric tolerance: {TOLERANCE:.1e}",
        "- Confidence intervals: two-sided 95% Student's t",
        f"- G_ref = g(p) = f(tx) = {fee:.1e}",
        "",
        "## Invariants",
        "",
        "| Check | Maximum deviation | Violations |",
        "|---|---:|---:|",
    ]
    for name, result in invariants.items():
        report_lines.append(
            f"| {name} | {result['max_deviation']:.12g} | {result['violation_count']} |"
        )
    report_lines.extend(
        [
            "",
            "## Group statistics",
            "",
            "Each cell is mean +/- 95% Student's t CI across seeds.",
            "",
            "| Multiplier | n | " + " | ".join(METRICS) + " |",
            "|---:|---:|" + "---:|" * len(METRICS),
        ]
    )
    for group in groups:
        cells = [
            f"{float(group[f'{metric}_mean']):.9g} +/- {float(group[f'{metric}_ci95']):.3g}"
            for metric in METRICS
        ]
        report_lines.append(
            f"| {group['multiplier']} | {group['n']} | " + " | ".join(cells) + " |"
        )
    report_path.write_text("\n".join(report_lines) + "\n")
    print(json.dumps(audit, indent=2, sort_keys=True))
    print(run_path.relative_to(ROOT))
    print(group_path.relative_to(ROOT))
    print(audit_path.relative_to(ROOT))
    print(report_path.relative_to(ROOT))
    return 0 if audit["all_runs_valid"] and not pairs and audit["all_invariants_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
