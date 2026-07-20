#!/usr/bin/env python3
"""Run paired sustained-outage experiments with seed-specific fixed assignments."""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import random
from pathlib import Path
from typing import Any, Dict, Iterable, List

from run_experiments import (
    PROCESSED_ROOT,
    RAW_ROOT,
    ROOT,
    append_failed_log,
    build_if_needed,
    command_for_run,
    load_yaml,
    protocol_cli,
    run_one,
    seed_bundle,
    slug,
    write_json,
)


def closest_prefix(rows: List[Dict[str, Any]], target: float) -> List[Dict[str, Any]]:
    """Choose the ordered prefix whose realized stake share is closest to target."""
    total = sum(float(row["economic_stake"]) for row in rows)
    if total <= 0 or target <= 0:
        return []
    selected: List[Dict[str, Any]] = []
    selected_stake = 0.0
    for row in rows:
        candidate = selected_stake + float(row["economic_stake"])
        if selected and abs(selected_stake / total - target) <= abs(candidate / total - target):
            break
        selected.append(row)
        selected_stake = candidate
        if selected_stake / total >= target:
            break
    return selected


def calibration_rows(output_dir: Path, warmup_epochs: int) -> List[Dict[str, Any]]:
    path = output_dir / "node_epoch_metrics.csv"
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise RuntimeError(f"no calibration rows in {path}")
    epoch = min(warmup_epochs - 1, max(int(row["epoch"]) for row in rows))
    selected = [row for row in rows if int(row["epoch"]) == epoch]
    if not selected:
        raise RuntimeError(f"calibration epoch {epoch} missing in {path}")
    return selected


def assignment_for(
    rows: List[Dict[str, Any]], selection: str, target: float, failure_seed: int
) -> Dict[str, Any]:
    ordered = list(rows)
    if selection == "random":
        ordered.sort(key=lambda row: int(row["validator_id"]))
        random.Random(failure_seed ^ 0x4F5554414745).shuffle(ordered)
    elif selection == "high-score":
        ordered.sort(
            key=lambda row: (
                -float(row["bonus"]),
                -float(row["normalized_score"]),
                int(row["validator_id"]),
            )
        )
    else:
        raise ValueError(f"unknown outage selection: {selection}")
    chosen = closest_prefix(ordered, target)
    ids = sorted(int(row["validator_id"]) for row in chosen)
    total_stake = sum(float(row["economic_stake"]) for row in rows)
    selected_stake = sum(float(row["economic_stake"]) for row in chosen)
    identity = ",".join(str(value) for value in ids)
    return {
        "selection": selection,
        "target_stake_fraction": target,
        "realized_stake_fraction": selected_stake / total_stake if total_stake else 0.0,
        "validator_ids": ids,
        "validator_ids_csv": identity,
        "assignment_sha256": hashlib.sha256(identity.encode()).hexdigest(),
    }


def base_run(spec: Dict[str, Any], seed_value: int) -> Dict[str, Any]:
    run = dict(spec["defaults"])
    run.update(seed_bundle(seed_value))
    run["suite"] = spec["suite"]
    run["protocol_version"] = spec.get("protocol_version", "frozen-v1")
    run["seed_value"] = seed_value
    run["seed_index"] = list(map(int, spec["seeds"])).index(seed_value)
    return run


def calibration_runs(spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    warmup = int(spec["outage"]["warmup_epochs"])
    runs = []
    for seed_value in map(int, spec["seeds"]):
        run = base_run(spec, seed_value)
        run.update(protocol_cli(spec["outage"].get("calibration_protocol", "topostake")))
        run.update(
            experiment="outage_calibration",
            max_epochs=warmup,
            warmup_epochs=warmup,
            run_id=f"outage-calibration_seed{run['seed_index']}",
        )
        run["output_dir"] = str(
            RAW_ROOT / spec["suite"] / "outage_calibration" / run["run_id"]
        )
        runs.append(run)
    return runs


def build_assignments(
    spec: Dict[str, Any], calibrations: Iterable[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    conditions = spec["outage"]
    assignments = []
    for run in calibrations:
        rows = calibration_rows(Path(run["output_dir"]), int(conditions["warmup_epochs"]))
        for selection in conditions["selections"]:
            for fraction in conditions["stake_fractions"]:
                assignment = assignment_for(
                    rows, str(selection), float(fraction), int(run["failure_seed"])
                )
                assignment.update(
                    seed_index=run["seed_index"], seed_value=run["seed_value"]
                )
                assignments.append(assignment)
    return assignments


def experiment_runs(
    spec: Dict[str, Any], assignments: Iterable[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    conditions = spec["outage"]
    warmup = int(conditions["warmup_epochs"])
    duration = int(conditions["duration_epochs"])
    runs = []
    for assignment in assignments:
        for protocol in conditions["protocols"]:
            run = base_run(spec, int(assignment["seed_value"]))
            run.update(protocol_cli(str(protocol)))
            run.update(
                experiment="sustained_outage",
                max_epochs=warmup + duration,
                warmup_epochs=warmup,
                outage_start_epoch=warmup,
                outage_duration_epochs=duration,
                outage_validator_ids=assignment["validator_ids_csv"],
                outage_common_slot_randomness=True,
                outage_selection=assignment["selection"],
                outage_target_stake_fraction=assignment["target_stake_fraction"],
                outage_realized_stake_fraction=assignment["realized_stake_fraction"],
                outage_assignment_sha256=assignment["assignment_sha256"],
            )
            run_id = (
                f"sustained-outage_{slug(run['protocol_label'])}_seed{run['seed_index']}_"
                f"{slug(assignment['selection'])}_q{slug(assignment['target_stake_fraction'])}"
            )
            run["run_id"] = run_id
            run["output_dir"] = str(
                RAW_ROOT / spec["suite"] / "sustained_outage" / run_id
            )
            runs.append(run)
    return runs


def execute(
    binary: str,
    runs: List[Dict[str, Any]],
    timeout: int,
    force: bool,
    max_parallel: int,
) -> List[Dict[str, Any]]:
    statuses = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_parallel) as executor:
        futures = [
            executor.submit(run_one, binary, run, timeout, force) for run in runs
        ]
        for future in concurrent.futures.as_completed(futures):
            status = future.result()
            statuses.append(status)
            print(f"[{status['status']}] {status['run_id']}")
    append_failed_log(statuses)
    return statuses


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--max-parallel", type=int)
    parser.add_argument("--timeout-seconds", type=int)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-build", action="store_true")
    args = parser.parse_args()

    spec_path = (ROOT / args.config).resolve()
    spec = load_yaml(spec_path)
    binary = spec.get("binary", "target/release/topostake")
    timeout = args.timeout_seconds or int(spec.get("timeout_seconds", 1200))
    max_parallel = args.max_parallel or int(spec.get("max_parallel", 2))
    calibrations = calibration_runs(spec)
    if args.dry_run:
        for run in calibrations:
            print(" ".join(command_for_run(binary, run)))
        print("# paired outage runs are materialized after calibration assignments")
        return 0

    build_if_needed(spec, args.no_build)
    calibration_status = execute(binary, calibrations, timeout, args.force, max_parallel)
    if any(status["status"] != "ok" for status in calibration_status):
        return 1

    assignments = build_assignments(spec, calibrations)
    assignment_path = PROCESSED_ROOT / spec["suite"] / "outage_assignments.json"
    write_json(assignment_path, {"assignments": assignments})
    runs = experiment_runs(spec, assignments)
    print(f"Materialized {len(runs)} paired outage runs from {len(assignments)} assignments")
    statuses = execute(binary, runs, timeout, args.force, max_parallel)
    return 1 if any(status["status"] != "ok" for status in statuses) else 0


if __name__ == "__main__":
    raise SystemExit(main())
