#!/usr/bin/env python3
"""Audit and summarize paired sustained-outage simulator results."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List

from run_experiments import PROCESSED_ROOT, RAW_ROOT, ROOT, load_yaml, read_json, write_json


def read_csv(path: Path) -> List[Dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def truth(value: str) -> bool:
    return value.strip().lower() == "true"


def mean(values: Iterable[float]) -> float:
    materialized = list(values)
    return statistics.fmean(materialized) if materialized else 0.0


def summarize_run(run_dir: Path) -> Dict[str, Any]:
    meta = read_json(run_dir / "experiment_meta.json")
    summary = read_json(run_dir / "run_summary.json")
    epochs = read_csv(run_dir / "epoch_metrics.csv")
    nodes = read_csv(run_dir / "node_epoch_metrics.csv")
    duties = read_csv(run_dir / "proposer_duties.csv")
    outage_ids = {int(value) for value in meta["outage_validator_ids"].split(",") if value}
    start = int(meta["outage_start_epoch"])
    duration = int(meta["outage_duration_epochs"])
    end = start + duration if duration else int(meta["max_epochs"])
    steady_start = max(start, end - min(5, duration or 5))
    outage_duties = [
        row for row in duties if start <= int(row["epoch"]) < end
    ]
    group_duties = [row for row in outage_duties if truth(row["outage_group"])]
    misses = [row for row in outage_duties if not truth(row["block_produced"])]
    scheduled_misses = [
        row for row in group_duties if row["failure_reason"] == "scheduled_outage"
    ]
    outage_epochs = [row for row in epochs if start <= int(row["epoch"]) < end]
    steady_epochs = [row for row in epochs if steady_start <= int(row["epoch"]) < end]
    group_nodes = [
        row
        for row in nodes
        if int(row["validator_id"]) in outage_ids
        and start <= int(row["epoch"]) < end
    ]
    weights_by_epoch: Dict[int, float] = defaultdict(float)
    bonuses_by_epoch: Dict[int, List[float]] = defaultdict(list)
    for row in group_nodes:
        epoch = int(row["epoch"])
        weights_by_epoch[epoch] += float(row["normalized_proposer_weight"])
        bonuses_by_epoch[epoch].append(float(row["bonus"]))
    stake_total = sum(
        float(row["economic_stake"])
        for row in nodes
        if int(row["epoch"]) == start and int(row["validator_id"]) in outage_ids
    )
    all_stake = sum(
        float(row["economic_stake"])
        for row in nodes
        if int(row["epoch"]) == start
    )
    relay_attempts = sum(
        int(row["relay_forward_attempts"])
        for row in group_nodes
        if int(row["epoch"]) > start
    )
    completed = int(summary.get("completed_epochs", -1)) >= int(meta["max_epochs"])
    return {
        "run_id": meta["run_id"],
        "output_dir": str(run_dir),
        "protocol_label": meta["protocol_label"],
        "seed_index": int(meta["seed_index"]),
        "selection": meta["outage_selection"],
        "target_stake_fraction": float(meta["outage_target_stake_fraction"]),
        "realized_stake_fraction": stake_total / all_stake if all_stake else 0.0,
        "outage_validator_count": len(outage_ids),
        "assignment_sha256": meta["outage_assignment_sha256"],
        "completed": completed,
        "outage_slots": len(outage_duties),
        "group_selected_slots": len(group_duties),
        "scheduled_missed_slots": len(scheduled_misses),
        "miss_rate": len(misses) / len(outage_duties) if outage_duties else 0.0,
        "chain_growth_ratio": 1.0 - len(misses) / len(outage_duties) if outage_duties else 0.0,
        "group_miss_enforcement": len(scheduled_misses) == len(group_duties),
        "outage_relay_attempts_after_start": relay_attempts,
        "initial_group_weight": weights_by_epoch.get(start, 0.0),
        "steady_group_weight": mean(
            value for epoch, value in weights_by_epoch.items() if epoch >= steady_start
        ),
        "end_group_bonus": mean(bonuses_by_epoch.get(end - 1, [])),
        "mean_p95_inclusion_latency_s": mean(
            float(row["p95_inclusion_latency_s"]) for row in outage_epochs
        ),
        "steady_p95_inclusion_latency_s": mean(
            float(row["p95_inclusion_latency_s"]) for row in steady_epochs
        ),
        "bound_violations": sum(truth(row["bound_violation"]) for row in epochs),
        "eta0_weight_error": max(
            [abs(value - (stake_total / all_stake if all_stake else 0.0)) for value in weights_by_epoch.values()]
            or [0.0]
        ),
        # node_epoch_metrics.csv stores each validator weight with six decimal
        # places. Summing a coalition therefore accumulates serialization
        # error; scale the audit tolerance with the number of selected rows.
        "eta0_weight_tolerance": max(1e-6, (len(outage_ids) + 2) * 1e-6),
        "duty_slot_keys": sorted((int(row["epoch"]), int(row["slot"])) for row in duties),
    }


def write_csv(path: Path, rows: List[Dict[str, Any]], excluded: set[str] | None = None) -> None:
    excluded = excluded or set()
    fields = [key for key in rows[0] if key not in excluded] if rows else []
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row[key] for key in fields})


def paired_rows(runs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    groups: Dict[tuple[Any, ...], Dict[str, Dict[str, Any]]] = defaultdict(dict)
    for run in runs:
        key = (run["seed_index"], run["selection"], run["target_stake_fraction"])
        groups[key][run["protocol_label"]] = run
    pairs = []
    for key, variants in sorted(groups.items()):
        if "topostake_eta0" not in variants or "topostake" not in variants:
            continue
        eta0 = variants["topostake_eta0"]
        full = variants["topostake"]
        pairs.append(
            {
                "seed_index": key[0],
                "selection": key[1],
                "target_stake_fraction": key[2],
                "realized_stake_fraction": full["realized_stake_fraction"],
                "assignment_match": eta0["assignment_sha256"] == full["assignment_sha256"],
                "duty_slots_match": eta0["duty_slot_keys"] == full["duty_slot_keys"],
                "eta0_miss_rate": eta0["miss_rate"],
                "full_miss_rate": full["miss_rate"],
                "miss_rate_improvement": eta0["miss_rate"] - full["miss_rate"],
                "eta0_steady_group_weight": eta0["steady_group_weight"],
                "full_steady_group_weight": full["steady_group_weight"],
                "weight_share_reduction": eta0["steady_group_weight"] - full["steady_group_weight"],
                "eta0_chain_growth_ratio": eta0["chain_growth_ratio"],
                "full_chain_growth_ratio": full["chain_growth_ratio"],
                "chain_growth_improvement": full["chain_growth_ratio"] - eta0["chain_growth_ratio"],
                "p95_latency_delta_s": full["steady_p95_inclusion_latency_s"] - eta0["steady_p95_inclusion_latency_s"],
            }
        )
    return pairs


def markdown_summary(pairs: List[Dict[str, Any]], acceptance: Dict[str, Any]) -> str:
    grouped: Dict[tuple[str, float], List[Dict[str, Any]]] = defaultdict(list)
    for pair in pairs:
        grouped[(pair["selection"], pair["target_stake_fraction"])].append(pair)
    lines = [
        "# Sustained-outage simulator summary",
        "",
        "Positive deltas mean full TopoStake reduced missed slots or improved chain growth relative to eta=0.",
        "",
        "| Selection | Target stake | Seeds | Miss-rate improvement | Chain-growth improvement | Weight-share reduction | Positive pairs |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for (selection, target), rows in sorted(grouped.items()):
        improvements = [row["miss_rate_improvement"] for row in rows]
        lines.append(
            f"| {selection} | {target:.0%} | {len(rows)} | {mean(improvements):.4f} | "
            f"{mean(row['chain_growth_improvement'] for row in rows):.4f} | "
            f"{mean(row['weight_share_reduction'] for row in rows):.4f} | "
            f"{sum(value > 0 for value in improvements)}/{len(rows)} |"
        )
    lines.extend(["", "Acceptance: " + ("PASS" if acceptance["pass"] else "FAIL"), ""])
    for name, value in acceptance["checks"].items():
        lines.append(f"- {name}: {'pass' if value else 'FAIL'}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    spec = load_yaml((ROOT / args.config).resolve())
    run_root = RAW_ROOT / spec["suite"] / "sustained_outage"
    runs = [summarize_run(path) for path in sorted(run_root.iterdir()) if path.is_dir()]
    pairs = paired_rows(runs)
    checks = {
        "all_runs_complete": bool(runs) and all(run["completed"] for run in runs),
        "all_pairs_present": len(pairs) * 2 == len(runs),
        "paired_assignments_match": all(pair["assignment_match"] for pair in pairs),
        "paired_duty_slots_match": all(pair["duty_slots_match"] for pair in pairs),
        "scheduled_outage_enforced": all(run["group_miss_enforcement"] for run in runs),
        "outage_relays_silent": all(run["outage_relay_attempts_after_start"] == 0 for run in runs),
        "eta0_weight_equals_stake": all(
            run["eta0_weight_error"] <= run["eta0_weight_tolerance"]
            for run in runs
            if run["protocol_label"] == "topostake_eta0"
        ),
        "no_weight_envelope_violation": all(run["bound_violations"] == 0 for run in runs),
    }
    acceptance = {
        "pass": all(checks.values()),
        "checks": checks,
        "directional_diagnostic": {
            "positive_miss_rate_pairs": sum(pair["miss_rate_improvement"] > 0 for pair in pairs),
            "total_pairs": len(pairs),
            "max_eta0_weight_error": max(
                (
                    run["eta0_weight_error"]
                    for run in runs
                    if run["protocol_label"] == "topostake_eta0"
                ),
                default=0.0,
            ),
            "max_eta0_weight_tolerance": max(
                (
                    run["eta0_weight_tolerance"]
                    for run in runs
                    if run["protocol_label"] == "topostake_eta0"
                ),
                default=0.0,
            ),
        },
    }
    out = PROCESSED_ROOT / spec["suite"]
    write_csv(out / "sustained_outage_runs.csv", runs, {"duty_slot_keys"})
    write_csv(out / "sustained_outage_paired.csv", pairs)
    write_json(out / "sustained_outage_acceptance.json", acceptance)
    (out / "sustained_outage_summary.md").write_text(markdown_summary(pairs, acceptance))
    print(json.dumps(acceptance, indent=2))
    return 0 if acceptance["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
