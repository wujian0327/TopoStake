#!/usr/bin/env python3
"""Summarize the history-only adaptive relay-participation experiment."""

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

from run_experiments import PROCESSED_ROOT, ROOT, expand_runs, load_yaml


PROTOCOLS = ("pos", "topostake_eta0", "topostake")
T95 = {2: 12.706, 3: 4.303, 4: 3.182, 5: 2.776}


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def percentile(values: Iterable[float], probability: float) -> float:
    ordered = sorted(value for value in values if math.isfinite(value))
    if not ordered:
        return 0.0
    position = probability * (len(ordered) - 1)
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def cohort_inclusion_metrics(
    generated: list[dict[str, str]],
    inclusion: list[dict[str, str]],
    *,
    warmup_epochs: int,
    max_epochs: int,
    slots_per_epoch: int,
    slot_duration_s: float,
    followup_epochs: int,
) -> dict[str, float | int]:
    """Measure a generated-tx cohort with complete, fixed follow-up.

    Transactions not included within the follow-up horizon receive the horizon
    value.  This prevents survivor-only inclusion latency from looking
    artificially small when forwarding is weak.
    """

    slots_per_epoch = max(slots_per_epoch, 1)
    followup_slots = max(followup_epochs * slots_per_epoch, 1)
    final_slot = max(max_epochs * slots_per_epoch - 1, 0)
    earliest_slot = max(warmup_epochs, 0) * slots_per_epoch
    latest_slot = final_slot - followup_slots
    generated_by_hash: dict[str, int] = {}
    for row in generated:
        tx_hash = str(row.get("tx_hash", "")).strip()
        if not tx_hash:
            continue
        created_slot = (
            int(number(row.get("created_epoch"))) * slots_per_epoch
            + int(number(row.get("created_slot")))
        )
        if earliest_slot <= created_slot <= latest_slot:
            generated_by_hash.setdefault(tx_hash, created_slot)

    included_by_hash: dict[str, tuple[int, float]] = {}
    for row in inclusion:
        tx_hash = str(row.get("tx_hash", "")).strip()
        if tx_hash not in generated_by_hash:
            continue
        included_slot = int(number(row.get("included_slot")))
        latency_s = max(number(row.get("latency_s")), 0.0)
        prior = included_by_hash.get(tx_hash)
        if prior is None or included_slot < prior[0]:
            included_by_hash[tx_hash] = (included_slot, latency_s)

    horizon_s = followup_slots * max(slot_duration_s, 0.0)
    bounded_latencies = []
    completed_latencies = []
    included_count = 0
    for tx_hash, created_slot in generated_by_hash.items():
        inclusion_sample = included_by_hash.get(tx_hash)
        if (
            inclusion_sample is not None
            and inclusion_sample[0] - created_slot <= followup_slots
        ):
            included_count += 1
            latency_s = min(inclusion_sample[1], horizon_s)
            bounded_latencies.append(latency_s)
            completed_latencies.append(latency_s)
        else:
            bounded_latencies.append(horizon_s)

    generated_count = len(generated_by_hash)
    return {
        "cohort_generated_tx": generated_count,
        "cohort_included_tx": included_count,
        "inclusion_within_horizon_rate": (
            included_count / generated_count if generated_count else 0.0
        ),
        "completed_p95_inclusion_latency_s": percentile(completed_latencies, 0.95),
        "timeout_adjusted_p95_latency_s": percentile(bounded_latencies, 0.95),
        "restricted_mean_inclusion_latency_s": (
            statistics.mean(bounded_latencies) if bounded_latencies else 0.0
        ),
        "followup_horizon_s": horizon_s,
    }


def mean_ci(values: Iterable[float]) -> tuple[float, float, int]:
    clean = [value for value in values if math.isfinite(value)]
    if not clean:
        return 0.0, 0.0, 0
    if len(clean) == 1:
        return clean[0], 0.0, 1
    critical = T95.get(len(clean), 1.96)
    return (
        statistics.mean(clean),
        critical * statistics.stdev(clean) / math.sqrt(len(clean)),
        len(clean),
    )


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else ["empty"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def aggregate_run(run: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    output_dir = Path(run["output_dir"])
    status = read_json(output_dir / "runner_status.json")
    summary = read_json(output_dir / "run_summary.json")
    adaptive = read_csv(output_dir / "adaptive_relay_metrics.csv")
    epochs = read_csv(output_dir / "epoch_metrics.csv")
    nodes = read_csv(output_dir / "node_epoch_metrics.csv")
    inclusion = read_csv(output_dir / "inclusion_samples.csv")
    generated = read_csv(output_dir / "generation_samples.csv")
    expected_epochs = int(run.get("max_epochs", 0))
    warmup = int(run.get("warmup_epochs", 0))
    inclusion_metrics = cohort_inclusion_metrics(
        generated,
        inclusion,
        warmup_epochs=warmup,
        max_epochs=expected_epochs,
        slots_per_epoch=int(number(run.get("slot_per_epoch"), 1)),
        slot_duration_s=number(run.get("slot_duration"), 1.0),
        followup_epochs=int(number(run.get("adaptive_followup_epochs"), 10)),
    )
    hysteresis = number(run.get("adaptive_switching_hysteresis"), 0.05)
    steady_adaptive = [row for row in adaptive if int(number(row.get("epoch"))) >= warmup]
    steady_nodes = [row for row in nodes if int(number(row.get("epoch"))) >= warmup]
    steady_epochs = [row for row in epochs if int(number(row.get("epoch"))) >= warmup]
    steady_inclusion = [
        row for row in inclusion if int(number(row.get("epoch"))) >= warmup
    ]
    first_epoch = min((int(number(row.get("epoch"))) for row in nodes), default=0)
    initial_nodes = [
        row for row in nodes if int(number(row.get("epoch"))) == first_epoch
    ]
    cost_assignment = "|".join(
        f"{row.get('validator_id')}:{number(row.get('relay_cost_per_forward')):.12f}"
        for row in sorted(initial_nodes, key=lambda item: str(item.get("validator_id")))
    )
    profile_assignment = "|".join(
        f"{row.get('validator_id')}:{row.get('relay_profile')}"
        for row in sorted(initial_nodes, key=lambda item: str(item.get("validator_id")))
    )

    consistency = []
    for row in steady_nodes:
        cost = number(row.get("relay_cost_per_forward"), math.nan)
        benefit = number(row.get("estimated_relay_benefit_per_forward"), math.nan)
        if not math.isfinite(cost) or not math.isfinite(benefit) or cost <= 0.0:
            continue
        if row.get("relay_profile") == "active":
            consistency.append(benefit >= cost * (1.0 - hysteresis))
        elif row.get("relay_profile") == "lazy":
            consistency.append(benefit <= cost * (1.0 + hysteresis))

    active_stake = [number(row.get("active_stake_share")) for row in steady_adaptive]
    active_fraction = [number(row.get("active_fraction")) for row in steady_adaptive]
    tail = active_stake[-10:]
    complete = (
        status.get("status") == "ok"
        and int(number(summary.get("completed_epochs"), -1)) >= expected_epochs
        and len(adaptive) >= expected_epochs
        and len(epochs) >= expected_epochs
        and int(inclusion_metrics["cohort_generated_tx"]) > 0
    )
    benefit_accounting_errors = 0
    for row in adaptive:
        if not truthy(row.get("update_applied")):
            continue
        work_premium = number(row.get("active_forward_attempts_per_stake")) - number(
            row.get("lazy_forward_attempts_per_stake")
        )
        if work_premium <= 0.0:
            continue
        reconstructed = (
            number(row.get("active_expected_reward_per_stake"))
            - number(row.get("lazy_expected_reward_per_stake"))
        ) / work_premium
        if abs(reconstructed - number(row.get("observed_benefit_per_forward"))) > max(
            1e-12, 1e-6 * abs(reconstructed)
        ):
            benefit_accounting_errors += 1
    output = {
        "suite": run.get("suite", ""),
        "experiment": run.get("experiment", ""),
        "run_id": run.get("run_id", ""),
        "protocol_label": run.get("protocol_label", ""),
        "seed_index": int(number(run.get("seed_index"))),
        "initial_active_fraction": number(run.get("adaptive_initial_active_fraction")),
        "cost_median_multiplier": number(run.get("adaptive_cost_median_multiplier"), 1.0),
        "status": status.get("status", "missing"),
        "complete": complete,
        "cost_assignment_hash": hashlib.sha256(cost_assignment.encode()).hexdigest(),
        "initial_profile_hash": hashlib.sha256(profile_assignment.encode()).hexdigest(),
        "steady_epoch_count": len(steady_adaptive),
        "steady_active_fraction": statistics.mean(active_fraction)
        if active_fraction
        else 0.0,
        "steady_active_stake_share": statistics.mean(active_stake)
        if active_stake
        else 0.0,
        "final_active_stake_share": active_stake[-1] if active_stake else 0.0,
        "tail_active_stake_range": max(tail) - min(tail) if tail else 1.0,
        "p95_inclusion_latency_s": percentile(
            [number(row.get("latency_s")) for row in steady_inclusion], 0.95
        ),
        **inclusion_metrics,
        "utility_consistency_share": (
            sum(consistency) / len(consistency) if consistency else 0.0
        ),
        "switches_to_active": sum(
            int(number(row.get("switched_to_active"))) for row in adaptive
        ),
        "switches_to_lazy": sum(
            int(number(row.get("switched_to_lazy"))) for row in adaptive
        ),
        "benefit_update_count": sum(
            truthy(row.get("update_applied"))
            and str(row.get("observed_benefit_per_forward", "")).strip() != ""
            for row in adaptive
        ),
        "benefit_accounting_error_count": benefit_accounting_errors,
        "bound_violation_count": sum(
            truthy(row.get("bound_violation")) for row in steady_epochs
        ),
    }
    trajectory = [
        {
            "protocol_label": run.get("protocol_label", ""),
            "seed_index": int(number(run.get("seed_index"))),
            "initial_active_fraction": number(
                run.get("adaptive_initial_active_fraction")
            ),
            "cost_median_multiplier": number(
                run.get("adaptive_cost_median_multiplier"), 1.0
            ),
            "epoch": int(number(row.get("epoch"))),
            "active_fraction": number(row.get("active_fraction")),
            "active_stake_share": number(row.get("active_stake_share")),
            "smoothed_benefit_per_forward": number(
                row.get("smoothed_benefit_per_forward")
            ),
            "update_applied": truthy(row.get("update_applied")),
        }
        for row in adaptive
    ]
    return output, trajectory


def grouped_rows(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for key in sorted(
        {
            (
                row["protocol_label"],
                row["initial_active_fraction"],
                row["cost_median_multiplier"],
            )
            for row in runs
            if row["complete"]
        }
    ):
        protocol, initial, cost = key
        selected = [
            row
            for row in runs
            if row["complete"]
            and row["protocol_label"] == protocol
            and row["initial_active_fraction"] == initial
            and row["cost_median_multiplier"] == cost
        ]
        values: dict[str, list[float]] = {
            metric: [number(row[metric]) for row in selected]
            for metric in (
                "steady_active_fraction",
                "steady_active_stake_share",
                "inclusion_within_horizon_rate",
                "completed_p95_inclusion_latency_s",
                "timeout_adjusted_p95_latency_s",
                "restricted_mean_inclusion_latency_s",
                "utility_consistency_share",
            )
        }
        row: dict[str, Any] = {
            "protocol_label": protocol,
            "initial_active_fraction": initial,
            "cost_median_multiplier": cost,
        }
        for metric, metric_values in values.items():
            mean, ci, count = mean_ci(metric_values)
            row[metric] = mean
            row[f"{metric}_ci95"] = ci
            row[f"{metric}_n"] = count
        output.append(row)
    return output


def grouped_trajectory(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, float, float, int], list[float]] = defaultdict(list)
    for row in rows:
        groups[
            (
                str(row["protocol_label"]),
                number(row["initial_active_fraction"]),
                number(row["cost_median_multiplier"]),
                int(number(row["epoch"])),
            )
        ].append(number(row["active_stake_share"]))
    output = []
    for (protocol, initial, cost, epoch), values in sorted(groups.items()):
        mean, ci, count = mean_ci(values)
        output.append(
            {
                "protocol_label": protocol,
                "initial_active_fraction": initial,
                "cost_median_multiplier": cost,
                "epoch": epoch,
                "active_stake_share": mean,
                "ci95": ci,
                "n": count,
            }
        )
    return output


def paired_rows(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    index = {
        (
            row["seed_index"],
            row["initial_active_fraction"],
            row["cost_median_multiplier"],
            row["protocol_label"],
        ): row
        for row in runs
        if row["complete"]
    }
    output = []
    for seed, initial, cost, protocol in sorted(index):
        if protocol != "topostake":
            continue
        full = index[(seed, initial, cost, protocol)]
        fee = index.get((seed, initial, cost, "topostake_eta0"))
        if fee is None:
            continue
        output.append(
            {
                "seed_index": seed,
                "initial_active_fraction": initial,
                "cost_median_multiplier": cost,
                "active_stake_gain": number(full["steady_active_stake_share"])
                - number(fee["steady_active_stake_share"]),
                "inclusion_rate_gain": number(
                    full["inclusion_within_horizon_rate"]
                )
                - number(fee["inclusion_within_horizon_rate"]),
                "restricted_mean_latency_reduction_s": number(
                    fee["restricted_mean_inclusion_latency_s"]
                )
                - number(full["restricted_mean_inclusion_latency_s"]),
            }
        )
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--allow-incomplete", action="store_true")
    args = parser.parse_args()
    config_path = (ROOT / args.config).resolve()
    spec = load_yaml(config_path)
    expected = expand_runs(spec)
    runs = []
    trajectory = []
    for expected_run in expected:
        run, samples = aggregate_run(expected_run)
        runs.append(run)
        trajectory.extend(samples)
    groups = grouped_rows(runs)
    trajectories = grouped_trajectory(trajectory)
    pairs = paired_rows(runs)
    suite = str(spec.get("suite", config_path.stem))
    prefix = PROCESSED_ROOT / suite
    write_csv(prefix.with_name(prefix.name + "_runs.csv"), runs)
    write_csv(prefix.with_name(prefix.name + "_groups.csv"), groups)
    write_csv(prefix.with_name(prefix.name + "_trajectory.csv"), trajectories)
    write_csv(prefix.with_name(prefix.name + "_paired.csv"), pairs)

    gains_by_initial: dict[float, list[float]] = defaultdict(list)
    for row in pairs:
        gains_by_initial[number(row["initial_active_fraction"])].append(
            number(row["active_stake_gain"])
        )
    passing_initials = sum(
        statistics.mean(values) >= 0.10 for values in gains_by_initial.values()
    )
    inclusion_by_initial: dict[float, list[float]] = defaultdict(list)
    latency_by_initial: dict[float, list[float]] = defaultdict(list)
    for row in pairs:
        inclusion_by_initial[number(row["initial_active_fraction"])].append(
            number(row["inclusion_rate_gain"])
        )
        latency_by_initial[number(row["initial_active_fraction"])].append(
            number(row["restricted_mean_latency_reduction_s"])
        )
    improving_end_to_end_initials = sum(
        statistics.mean(latency_by_initial[initial]) > 0.0
        and statistics.mean(inclusion_by_initial[initial]) >= 0.0
        for initial in latency_by_initial
    )
    complete = [row for row in runs if row["complete"]]
    utility_rows = [
        row
        for row in complete
        if row["protocol_label"] in {"topostake_eta0", "topostake"}
    ]
    initialization_spreads = {}
    for protocol in ("topostake_eta0", "topostake"):
        values = [
            number(row["steady_active_stake_share"])
            for row in groups
            if row["protocol_label"] == protocol
        ]
        initialization_spreads[protocol] = max(values) - min(values) if values else 1.0
    paired_cost_hashes: dict[tuple[int, float, float], set[str]] = defaultdict(set)
    paired_profile_hashes: dict[tuple[int, float, float], set[str]] = defaultdict(set)
    for row in complete:
        key = (
            row["seed_index"],
            row["initial_active_fraction"],
            row["cost_median_multiplier"],
        )
        paired_cost_hashes[key].add(str(row["cost_assignment_hash"]))
        paired_profile_hashes[key].add(str(row["initial_profile_hash"]))
    pairing_mismatches = sum(
        len(hashes) != 1 for hashes in paired_cost_hashes.values()
    ) + sum(len(hashes) != 1 for hashes in paired_profile_hashes.values())
    checks = {
        "run_completeness": len(complete) == len(expected),
        "paired_cost_and_initial_strategy": bool(complete)
        and pairing_mismatches == 0,
        "historical_benefit_updates": bool(complete)
        and all(number(row["benefit_update_count"]) > 0 for row in complete),
        "benefit_accounting": sum(
            int(number(row["benefit_accounting_error_count"])) for row in complete
        )
        == 0,
        "broad_participation_gain": passing_initials >= 2,
        "initialization_robustness": all(
            spread <= 0.10 for spread in initialization_spreads.values()
        ),
        "end_to_end_inclusion_direction": improving_end_to_end_initials >= 2,
        "utility_consistency": bool(utility_rows)
        and statistics.mean(
            number(row["utility_consistency_share"]) for row in utility_rows
        )
        >= 0.80,
        "proposer_security_envelope": sum(
            int(number(row["bound_violation_count"])) for row in complete
        )
        == 0,
    }
    acceptance = {
        "suite": suite,
        "pass": all(checks.values()),
        "checks": checks,
        "diagnostics": {
            "expected_runs": len(expected),
            "complete_runs": len(complete),
            "initial_conditions_with_at_least_10pp_gain": passing_initials,
            "required_initial_conditions": 2,
            "initial_conditions_with_better_bounded_inclusion": (
                improving_end_to_end_initials
            ),
            "initialization_spreads": initialization_spreads,
            "pairing_mismatches": pairing_mismatches,
        },
    }
    acceptance_path = prefix.with_name(prefix.name + "_acceptance.json")
    acceptance_path.write_text(json.dumps(acceptance, indent=2) + "\n", encoding="utf-8")
    summary_lines = [
        "# History-only adaptive participation pilot",
        "",
        "Validators update Active/Lazy strategies from completed-window public reward and forwarding observations. The model uses fixed calibrated costs and no future proposer draws; it is behavioral evidence, not an equilibrium proof.",
        "",
        "| Protocol | Initial active | Steady active stake | Included within horizon | Restricted mean | Utility-consistent |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in groups:
        summary_lines.append(
            f"| {row['protocol_label']} | {number(row['initial_active_fraction']):.0%} | "
            f"{number(row['steady_active_stake_share']):.1%} | "
            f"{number(row['inclusion_within_horizon_rate']):.1%} | "
            f"{number(row['restricted_mean_inclusion_latency_s']):.2f}s | "
            f"{number(row['utility_consistency_share']):.1%} |"
        )
    summary_lines.extend(
        [
            "",
            "Pilot acceptance: **" + ("PASS" if acceptance["pass"] else "FAIL") + "**",
            "",
        ]
    )
    for name, passed in checks.items():
        summary_lines.append(f"- {name}: {'pass' if passed else 'FAIL'}")
    summary_path = prefix.with_name(prefix.name + "_summary.md")
    summary_path.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    print(json.dumps(acceptance, indent=2))
    return 0 if acceptance["pass"] or args.allow_incomplete else 1


if __name__ == "__main__":
    raise SystemExit(main())
