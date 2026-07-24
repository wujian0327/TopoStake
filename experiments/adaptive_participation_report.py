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
    20: 2.093,
}
MIN_COUNTERFACTUAL_COVERAGE = 0.80
MAX_GROUP_POST_ADAPTATION_DRIFT = 0.05
MAX_P90_INDIVIDUAL_DRIFT = 0.10


def requires_initialization_robustness(acceptance_profile: str) -> bool:
    """Only the multi-initial-condition pilot has this acceptance dimension."""

    return acceptance_profile == "full_pilot"


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


def benefit_accounting_counts(
    rows: Iterable[dict[str, Any]],
) -> dict[str, int]:
    """Validate only updates with an observed Active/Lazy counterfactual.

    When either cohort is empty, the simulator deliberately leaves
    ``observed_benefit_per_forward`` blank and retains the prior EMA.  Such an
    update is unavailable for reconstruction rather than an accounting error.
    """

    attempts = 0
    observed = 0
    unavailable = 0
    errors = 0
    component_fields = (
        "active_expected_reward_per_stake",
        "lazy_expected_reward_per_stake",
        "active_forward_attempts_per_stake",
        "lazy_forward_attempts_per_stake",
    )
    for row in rows:
        if not truthy(row.get("update_applied")):
            continue
        attempts += 1
        observed_text = str(row.get("observed_benefit_per_forward", "")).strip()
        if not observed_text:
            unavailable += 1
            continue
        observed += 1
        if any(not str(row.get(field, "")).strip() for field in component_fields):
            errors += 1
            continue
        work_premium = number(row.get("active_forward_attempts_per_stake")) - number(
            row.get("lazy_forward_attempts_per_stake")
        )
        if work_premium <= 0.0:
            errors += 1
            continue
        reconstructed = (
            number(row.get("active_expected_reward_per_stake"))
            - number(row.get("lazy_expected_reward_per_stake"))
        ) / work_premium
        recorded = number(row.get("observed_benefit_per_forward"), math.nan)
        if not math.isfinite(recorded) or abs(reconstructed - recorded) > max(
            1e-12, 1e-6 * abs(reconstructed)
        ):
            errors += 1
    return {
        "attempts": attempts,
        "observed": observed,
        "unavailable": unavailable,
        "errors": errors,
    }


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


def post_adaptation_stats(values: Iterable[float]) -> tuple[float, float]:
    """Return half-window mean drift and standard deviation."""

    cleaned = [value for value in values if math.isfinite(value)]
    if len(cleaned) < 2:
        return 1.0, 0.0
    midpoint = len(cleaned) // 2
    first, second = cleaned[:midpoint], cleaned[midpoint:]
    drift = abs(statistics.mean(first) - statistics.mean(second))
    spread = statistics.stdev(cleaned)
    return drift, spread


def grouped_post_adaptation_drifts(
    trajectories: Iterable[dict[str, Any]],
    analysis_start_epoch: int,
) -> dict[str, float]:
    """Measure half-window drift on each seed-averaged condition trajectory."""

    grouped: dict[tuple[str, float, float], list[tuple[int, float]]] = defaultdict(
        list
    )
    for row in trajectories:
        epoch = int(number(row.get("epoch"), -1))
        protocol = str(row.get("protocol_label", ""))
        if (
            epoch < analysis_start_epoch
            or protocol not in {"topostake_eta0", "topostake"}
        ):
            continue
        key = (
            protocol,
            number(row.get("initial_active_fraction")),
            number(row.get("cost_median_multiplier"), 1.0),
        )
        grouped[key].append((epoch, number(row.get("active_stake_share"))))
    output = {}
    for (protocol, initial, cost), samples in sorted(grouped.items()):
        values = [value for _epoch, value in sorted(samples)]
        drift, _spread = post_adaptation_stats(values)
        output[f"{protocol}@initial={initial:g}@cost={cost:g}"] = drift
    return output


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


PROCESSED_RUN_FLOAT_FIELDS = (
    "initial_active_fraction",
    "cost_median_multiplier",
    "adaptive_update_fraction",
    "adaptive_benefit_ema_alpha",
    "adaptive_switching_hysteresis",
    "adaptive_exploration_fraction",
    "steady_active_fraction",
    "steady_active_stake_share",
    "final_active_stake_share",
    "tail_active_stake_range",
    "post_adaptation_active_stake_drift",
    "post_adaptation_active_stake_stddev",
    "p95_inclusion_latency_s",
    "inclusion_within_horizon_rate",
    "completed_p95_inclusion_latency_s",
    "timeout_adjusted_p95_latency_s",
    "restricted_mean_inclusion_latency_s",
    "followup_horizon_s",
    "utility_consistency_share",
)
PROCESSED_RUN_INT_FIELDS = (
    "seed_index",
    "seed_value",
    "steady_epoch_count",
    "cohort_generated_tx",
    "cohort_included_tx",
    "switches_to_active",
    "switches_to_lazy",
    "exploratory_decision_count",
    "benefit_update_attempt_count",
    "benefit_update_count",
    "benefit_counterfactual_unavailable_count",
    "benefit_accounting_error_count",
    "bound_violation_count",
)
MERGED_RUN_KEY_FIELDS = (
    "experiment",
    "protocol_label",
    "seed_value",
    "initial_active_fraction",
    "cost_median_multiplier",
    "adaptive_update_fraction",
    "adaptive_benefit_ema_alpha",
    "adaptive_switching_hysteresis",
    "adaptive_exploration_fraction",
)
TRAJECTORY_KEY_FIELDS = (
    "experiment",
    "protocol_label",
    "initial_active_fraction",
    "cost_median_multiplier",
    "adaptive_update_fraction",
    "adaptive_switching_hysteresis",
    "adaptive_exploration_fraction",
    "epoch",
)


def coerce_processed_run(row: dict[str, Any]) -> dict[str, Any]:
    output = dict(row)
    output["complete"] = truthy(row.get("complete"))
    for field in PROCESSED_RUN_FLOAT_FIELDS:
        output[field] = number(row.get(field))
    for field in PROCESSED_RUN_INT_FIELDS:
        output[field] = int(number(row.get(field)))
    return output


def expected_merged_run_key(run: dict[str, Any]) -> tuple[Any, ...]:
    return (
        str(run.get("experiment", "")),
        str(run.get("protocol_label", "")),
        int(number(run.get("seed_value"))),
        number(run.get("adaptive_initial_active_fraction")),
        number(run.get("adaptive_cost_median_multiplier"), 1.0),
        number(run.get("adaptive_update_fraction"), 0.10),
        number(run.get("adaptive_benefit_ema_alpha"), 0.25),
        number(run.get("adaptive_switching_hysteresis"), 0.10),
        number(run.get("adaptive_exploration_fraction"), 0.05),
    )


def processed_merged_run_key(run: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(run[field] for field in MERGED_RUN_KEY_FIELDS)


def pool_grouped_trajectories(
    paths: Iterable[Path],
) -> list[dict[str, Any]]:
    """Combine per-part trajectory means and confidence intervals exactly."""

    buckets: dict[tuple[Any, ...], list[tuple[float, float, int]]] = defaultdict(
        list
    )
    for path in paths:
        part_keys: set[tuple[Any, ...]] = set()
        for row in read_csv(path):
            key = (
                str(row.get("experiment", "")),
                str(row.get("protocol_label", "")),
                number(row.get("initial_active_fraction")),
                number(row.get("cost_median_multiplier"), 1.0),
                number(row.get("adaptive_update_fraction"), 0.10),
                number(row.get("adaptive_switching_hysteresis"), 0.10),
                number(row.get("adaptive_exploration_fraction"), 0.05),
                int(number(row.get("epoch"))),
            )
            if key in part_keys:
                raise ValueError(f"duplicate trajectory condition in {path}: {key}")
            part_keys.add(key)
            sample_count = int(number(row.get("n")))
            if sample_count < 2:
                raise ValueError(
                    f"trajectory condition needs at least two samples in {path}: {key}"
                )
            mean = number(row.get("active_stake_share"))
            confidence = number(row.get("ci95"))
            critical = T95.get(sample_count, 1.96)
            standard_deviation = (
                confidence * math.sqrt(sample_count) / critical
            )
            buckets[key].append((mean, standard_deviation, sample_count))

    output = []
    for key, summaries in sorted(buckets.items()):
        total_count = sum(count for _mean, _spread, count in summaries)
        combined_mean = sum(
            mean * count for mean, _spread, count in summaries
        ) / total_count
        sum_squares = sum(
            (count - 1) * spread**2 + count * (mean - combined_mean) ** 2
            for mean, spread, count in summaries
        )
        combined_spread = math.sqrt(sum_squares / (total_count - 1))
        confidence = (
            T95.get(total_count, 1.96)
            * combined_spread
            / math.sqrt(total_count)
        )
        row = dict(zip(TRAJECTORY_KEY_FIELDS, key))
        row.update(
            {
                "active_stake_share": combined_mean,
                "ci95": confidence,
                "n": total_count,
            }
        )
        output.append(row)
    return output


def merge_processed_parts(
    run_paths: Iterable[Path],
    trajectory_paths: Iterable[Path],
    expected: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    run_paths = list(run_paths)
    trajectory_paths = list(trajectory_paths)
    if len(run_paths) < 2 or len(run_paths) != len(trajectory_paths):
        raise ValueError(
            "processed merge requires matching --part-runs and "
            "--part-trajectory arguments for at least two parts"
        )

    expected_keys = {expected_merged_run_key(run) for run in expected}
    seed_indices = {
        seed_value: index
        for index, seed_value in enumerate(
            sorted({int(number(run.get("seed_value"))) for run in expected})
        )
    }
    runs = []
    actual_keys: set[tuple[Any, ...]] = set()
    for path in run_paths:
        for raw_row in read_csv(path):
            row = coerce_processed_run(raw_row)
            key = processed_merged_run_key(row)
            if key in actual_keys:
                raise ValueError(f"duplicate processed run across parts: {key}")
            actual_keys.add(key)
            if row["seed_value"] not in seed_indices:
                raise ValueError(
                    f"unexpected seed value {row['seed_value']} in {path}"
                )
            row["seed_index"] = seed_indices[row["seed_value"]]
            runs.append(row)

    missing = expected_keys - actual_keys
    extra = actual_keys - expected_keys
    if missing or extra:
        raise ValueError(
            f"processed parts do not match the frozen config: "
            f"missing={len(missing)}, extra={len(extra)}"
        )
    trajectories = pool_grouped_trajectories(trajectory_paths)
    return runs, trajectories


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
    post_adaptation_drift, post_adaptation_stddev = post_adaptation_stats(
        active_stake
    )
    complete = (
        status.get("status") == "ok"
        and int(number(summary.get("completed_epochs"), -1)) >= expected_epochs
        and len(adaptive) >= expected_epochs
        and len(epochs) >= expected_epochs
        and int(inclusion_metrics["cohort_generated_tx"]) > 0
    )
    benefit_accounting = benefit_accounting_counts(adaptive)
    output = {
        "suite": run.get("suite", ""),
        "experiment": run.get("experiment", ""),
        "run_id": run.get("run_id", ""),
        "protocol_label": run.get("protocol_label", ""),
        "seed_index": int(number(run.get("seed_index"))),
        "seed_value": int(number(run.get("seed_value"))),
        "initial_active_fraction": number(run.get("adaptive_initial_active_fraction")),
        "cost_median_multiplier": number(run.get("adaptive_cost_median_multiplier"), 1.0),
        "adaptive_update_fraction": number(
            run.get("adaptive_update_fraction"), 0.10
        ),
        "adaptive_benefit_ema_alpha": number(
            run.get("adaptive_benefit_ema_alpha"), 0.25
        ),
        "adaptive_switching_hysteresis": number(
            run.get("adaptive_switching_hysteresis"), 0.10
        ),
        "adaptive_exploration_fraction": number(
            run.get("adaptive_exploration_fraction"), 0.05
        ),
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
        "post_adaptation_active_stake_drift": post_adaptation_drift,
        "post_adaptation_active_stake_stddev": post_adaptation_stddev,
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
        "exploratory_decision_count": sum(
            int(number(row.get("exploratory_decisions"))) for row in adaptive
        ),
        "benefit_update_attempt_count": benefit_accounting["attempts"],
        "benefit_update_count": benefit_accounting["observed"],
        "benefit_counterfactual_unavailable_count": benefit_accounting["unavailable"],
        "benefit_accounting_error_count": benefit_accounting["errors"],
        "bound_violation_count": sum(
            truthy(row.get("bound_violation")) for row in steady_epochs
        ),
    }
    trajectory = [
        {
            "experiment": run.get("experiment", ""),
            "protocol_label": run.get("protocol_label", ""),
            "seed_index": int(number(run.get("seed_index"))),
            "seed_value": int(number(run.get("seed_value"))),
            "initial_active_fraction": number(
                run.get("adaptive_initial_active_fraction")
            ),
            "cost_median_multiplier": number(
                run.get("adaptive_cost_median_multiplier"), 1.0
            ),
            "adaptive_update_fraction": number(
                run.get("adaptive_update_fraction"), 0.10
            ),
            "adaptive_switching_hysteresis": number(
                run.get("adaptive_switching_hysteresis"), 0.10
            ),
            "adaptive_exploration_fraction": number(
                run.get("adaptive_exploration_fraction"), 0.05
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
                row["experiment"],
                row["protocol_label"],
                row["initial_active_fraction"],
                row["cost_median_multiplier"],
                row["adaptive_update_fraction"],
                row["adaptive_switching_hysteresis"],
                row["adaptive_exploration_fraction"],
            )
            for row in runs
            if row["complete"]
        }
    ):
        experiment, protocol, initial, cost, update_fraction, hysteresis, exploration = (
            key
        )
        selected = [
            row
            for row in runs
            if row["complete"]
            and row["experiment"] == experiment
            and row["protocol_label"] == protocol
            and row["initial_active_fraction"] == initial
            and row["cost_median_multiplier"] == cost
            and row["adaptive_update_fraction"] == update_fraction
            and row["adaptive_switching_hysteresis"] == hysteresis
            and row["adaptive_exploration_fraction"] == exploration
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
            "experiment": experiment,
            "protocol_label": protocol,
            "initial_active_fraction": initial,
            "cost_median_multiplier": cost,
            "adaptive_update_fraction": update_fraction,
            "adaptive_switching_hysteresis": hysteresis,
            "adaptive_exploration_fraction": exploration,
        }
        for metric, metric_values in values.items():
            mean, ci, count = mean_ci(metric_values)
            row[metric] = mean
            row[f"{metric}_ci95"] = ci
            row[f"{metric}_n"] = count
        output.append(row)
    return output


def grouped_trajectory(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[
        tuple[str, str, float, float, float, float, float, int], list[float]
    ] = defaultdict(list)
    for row in rows:
        groups[
            (
                str(row["experiment"]),
                str(row["protocol_label"]),
                number(row["initial_active_fraction"]),
                number(row["cost_median_multiplier"]),
                number(row["adaptive_update_fraction"]),
                number(row["adaptive_switching_hysteresis"]),
                number(row["adaptive_exploration_fraction"]),
                int(number(row["epoch"])),
            )
        ].append(number(row["active_stake_share"]))
    output = []
    for (
        experiment,
        protocol,
        initial,
        cost,
        update_fraction,
        hysteresis,
        exploration,
        epoch,
    ), values in sorted(groups.items()):
        mean, ci, count = mean_ci(values)
        output.append(
            {
                "experiment": experiment,
                "protocol_label": protocol,
                "initial_active_fraction": initial,
                "cost_median_multiplier": cost,
                "adaptive_update_fraction": update_fraction,
                "adaptive_switching_hysteresis": hysteresis,
                "adaptive_exploration_fraction": exploration,
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
            row["experiment"],
            row["seed_index"],
            row["initial_active_fraction"],
            row["cost_median_multiplier"],
            row["protocol_label"],
        ): row
        for row in runs
        if row["complete"]
    }
    output = []
    for experiment, seed, initial, cost, protocol in sorted(index):
        if protocol != "topostake":
            continue
        full = index[(experiment, seed, initial, cost, protocol)]
        fee = index.get((experiment, seed, initial, cost, "topostake_eta0"))
        if fee is None:
            continue
        output.append(
            {
                "experiment": experiment,
                "seed_index": seed,
                "seed_value": int(number(full.get("seed_value"))),
                "initial_active_fraction": initial,
                "cost_median_multiplier": cost,
                "adaptive_update_fraction": number(
                    full["adaptive_update_fraction"]
                ),
                "adaptive_switching_hysteresis": number(
                    full["adaptive_switching_hysteresis"]
                ),
                "adaptive_exploration_fraction": number(
                    full["adaptive_exploration_fraction"]
                ),
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
    parser.add_argument(
        "--part-runs",
        type=Path,
        action="append",
        default=[],
        help="Processed *_runs.csv from one independently executed seed tranche.",
    )
    parser.add_argument(
        "--part-trajectory",
        type=Path,
        action="append",
        default=[],
        help="Processed *_trajectory.csv paired with --part-runs.",
    )
    args = parser.parse_args()
    config_path = (ROOT / args.config).resolve()
    spec = load_yaml(config_path)
    acceptance_profile = str(spec.get("acceptance_profile", "full_pilot"))
    expected = expand_runs(spec)
    if args.part_runs or args.part_trajectory:
        runs, trajectories = merge_processed_parts(
            [path.resolve() for path in args.part_runs],
            [path.resolve() for path in args.part_trajectory],
            expected,
        )
    else:
        runs = []
        trajectory = []
        for expected_run in expected:
            run, samples = aggregate_run(expected_run)
            runs.append(run)
            trajectory.extend(samples)
        trajectories = grouped_trajectory(trajectory)
    groups = grouped_rows(runs)
    pairs = paired_rows(runs)
    suite = str(spec.get("suite", config_path.stem))
    prefix = PROCESSED_ROOT / suite
    write_csv(prefix.with_name(prefix.name + "_runs.csv"), runs)
    write_csv(prefix.with_name(prefix.name + "_groups.csv"), groups)
    write_csv(prefix.with_name(prefix.name + "_trajectory.csv"), trajectories)
    write_csv(prefix.with_name(prefix.name + "_paired.csv"), pairs)

    gains_by_condition: dict[tuple[str, float, float], list[float]] = defaultdict(list)
    for row in pairs:
        key = (
            str(row["experiment"]),
            number(row["cost_median_multiplier"]),
            number(row["initial_active_fraction"]),
        )
        gains_by_condition[key].append(number(row["active_stake_gain"]))
    passing_initials_by_cost: dict[float, int] = defaultdict(int)
    for (_experiment, cost, _initial), values in gains_by_condition.items():
        passing_initials_by_cost[cost] += statistics.mean(values) >= 0.10
    passing_cost_regimes = sum(
        passing >= 2 for passing in passing_initials_by_cost.values()
    )
    inclusion_by_condition: dict[
        tuple[str, float, float], list[float]
    ] = defaultdict(list)
    latency_by_condition: dict[tuple[str, float, float], list[float]] = defaultdict(
        list
    )
    for row in pairs:
        key = (
            str(row["experiment"]),
            number(row["cost_median_multiplier"]),
            number(row["initial_active_fraction"]),
        )
        inclusion_by_condition[key].append(number(row["inclusion_rate_gain"]))
        latency_by_condition[key].append(
            number(row["restricted_mean_latency_reduction_s"])
        )
    improving_initials_by_cost: dict[float, int] = defaultdict(int)
    for experiment, cost, initial in latency_by_condition:
        key = (experiment, cost, initial)
        improving_initials_by_cost[cost] += (
            statistics.mean(latency_by_condition[key]) > 0.0
            and statistics.mean(inclusion_by_condition[key]) >= 0.0
        )
    improving_end_to_end_cost_regimes = sum(
        improving >= 2 for improving in improving_initials_by_cost.values()
    )
    complete = [row for row in runs if row["complete"]]
    utility_rows = [
        row
        for row in complete
        if row["protocol_label"] in {"topostake_eta0", "topostake"}
    ]
    initialization_spreads = {}
    for protocol in ("topostake_eta0", "topostake"):
        costs = sorted(
            {
                number(row["cost_median_multiplier"])
                for row in groups
                if row["protocol_label"] == protocol
            }
        )
        for cost in costs:
            values = [
                number(row["steady_active_stake_share"])
                for row in groups
                if row["protocol_label"] == protocol
                and number(row["cost_median_multiplier"]) == cost
            ]
            key = f"{protocol}@{cost:g}"
            initialization_spreads[key] = (
                max(values) - min(values) if values else 1.0
            )
    paired_cost_hashes: dict[tuple[str, int, float, float], set[str]] = defaultdict(
        set
    )
    paired_profile_hashes: dict[
        tuple[str, int, float, float], set[str]
    ] = defaultdict(set)
    for row in complete:
        key = (
            row["experiment"],
            row["seed_index"],
            row["initial_active_fraction"],
            row["cost_median_multiplier"],
        )
        paired_cost_hashes[key].add(str(row["cost_assignment_hash"]))
        paired_profile_hashes[key].add(str(row["initial_profile_hash"]))
    pairing_mismatches = sum(
        len(hashes) != 1 for hashes in paired_cost_hashes.values()
    ) + sum(len(hashes) != 1 for hashes in paired_profile_hashes.values())
    counterfactual_coverage_by_protocol = {}
    unavailable_updates_by_protocol = {}
    for protocol in ("topostake_eta0", "topostake"):
        protocol_rows = [
            row for row in utility_rows if row["protocol_label"] == protocol
        ]
        attempts = sum(
            int(number(row["benefit_update_attempt_count"]))
            for row in protocol_rows
        )
        observed = sum(
            int(number(row["benefit_update_count"])) for row in protocol_rows
        )
        counterfactual_coverage_by_protocol[protocol] = (
            observed / attempts if attempts else 0.0
        )
        unavailable_updates_by_protocol[protocol] = sum(
            int(number(row["benefit_counterfactual_unavailable_count"]))
            for row in protocol_rows
        )
    individual_post_adaptation_drifts = [
        number(row["post_adaptation_active_stake_drift"]) for row in utility_rows
    ]
    maximum_post_adaptation_drift = max(
        individual_post_adaptation_drifts, default=1.0
    )
    p90_post_adaptation_drift = percentile(
        individual_post_adaptation_drifts, 0.90
    )
    maximum_post_adaptation_stddev = max(
        (
            number(row["post_adaptation_active_stake_stddev"])
            for row in utility_rows
        ),
        default=1.0,
    )
    analysis_start_epoch = int(number(spec.get("defaults", {}).get("warmup_epochs")))
    group_post_adaptation_drifts = grouped_post_adaptation_drifts(
        trajectories, analysis_start_epoch
    )
    maximum_group_post_adaptation_drift = max(
        group_post_adaptation_drifts.values(), default=1.0
    )
    stability_pass = (
        maximum_group_post_adaptation_drift
        <= MAX_GROUP_POST_ADAPTATION_DRIFT
        and p90_post_adaptation_drift <= MAX_P90_INDIVIDUAL_DRIFT
    )
    condition_gain_means = {
        f"{experiment}@initial={initial:g}@cost={cost:g}": statistics.mean(values)
        for (experiment, cost, initial), values in sorted(
            gains_by_condition.items()
        )
    }
    condition_gain_intervals = {}
    condition_positive_seed_counts = {}
    for (experiment, cost, initial), values in sorted(gains_by_condition.items()):
        mean, ci, count = mean_ci(values)
        key = f"{experiment}@initial={initial:g}@cost={cost:g}"
        condition_gain_intervals[key] = {
            "mean": mean,
            "ci95": ci,
            "lower": mean - ci,
            "upper": mean + ci,
            "n": count,
        }
        condition_positive_seed_counts[key] = sum(value > 0.0 for value in values)
    condition_latency_intervals = {}
    condition_latency_positive_seed_counts = {}
    condition_inclusion_rate_intervals = {}
    for condition, values in sorted(latency_by_condition.items()):
        experiment, cost, initial = condition
        key = f"{experiment}@initial={initial:g}@cost={cost:g}"
        mean, ci, count = mean_ci(values)
        condition_latency_intervals[key] = {
            "mean": mean,
            "ci95": ci,
            "lower": mean - ci,
            "upper": mean + ci,
            "n": count,
        }
        condition_latency_positive_seed_counts[key] = sum(
            value > 0.0 for value in values
        )
        inclusion_mean, inclusion_ci, inclusion_count = mean_ci(
            inclusion_by_condition[condition]
        )
        condition_inclusion_rate_intervals[key] = {
            "mean": inclusion_mean,
            "ci95": inclusion_ci,
            "lower": inclusion_mean - inclusion_ci,
            "upper": inclusion_mean + inclusion_ci,
            "n": inclusion_count,
        }
    condition_inclusion_direction = {
        f"{experiment}@initial={initial:g}@cost={cost:g}": (
            statistics.mean(
                latency_by_condition[(experiment, cost, initial)]
            )
            > 0.0
            and statistics.mean(
                inclusion_by_condition[(experiment, cost, initial)]
            )
            >= 0.0
        )
        for experiment, cost, initial in sorted(latency_by_condition)
    }
    if acceptance_profile == "stability_probe":
        participation_pass = (
            len(condition_gain_means) == 4
            and all(value > 0.0 for value in condition_gain_means.values())
            and sum(value >= 0.10 for value in condition_gain_means.values()) >= 3
        )
        inclusion_pass = (
            sum(condition_inclusion_direction.values()) >= 3
        )
    elif acceptance_profile == "holdout":
        high_cost_key = "adaptive_holdout@initial=0.5@cost=3"
        lower_cost_keys = (
            "adaptive_holdout@initial=0.5@cost=1",
            "adaptive_holdout@initial=0.5@cost=2",
        )
        participation_pass = (
            high_cost_key in condition_gain_intervals
            and condition_gain_intervals[high_cost_key]["lower"] > 0.0
            and any(
                key in condition_gain_intervals
                and condition_gain_intervals[key]["lower"] > 0.0
                for key in lower_cost_keys
            )
        )
        inclusion_pass = condition_inclusion_direction.get(high_cost_key, False)
    elif acceptance_profile == "sensitivity":
        participation_pass = (
            len(condition_gain_means) == 4
            and all(value > 0.0 for value in condition_gain_means.values())
        )
        inclusion_pass = sum(condition_inclusion_direction.values()) >= 3
    else:
        participation_pass = passing_cost_regimes >= 2
        inclusion_pass = improving_end_to_end_cost_regimes >= 2
    checks = {
        "run_completeness": len(complete) == len(expected),
        "paired_cost_and_initial_strategy": bool(complete)
        and pairing_mismatches == 0,
        "historical_benefit_updates": bool(utility_rows)
        and all(number(row["benefit_update_count"]) > 0 for row in utility_rows),
        "benefit_accounting": sum(
            int(number(row["benefit_accounting_error_count"])) for row in complete
        )
        == 0,
        "counterfactual_coverage": all(
            coverage >= MIN_COUNTERFACTUAL_COVERAGE
            for coverage in counterfactual_coverage_by_protocol.values()
        ),
        "broad_participation_gain": participation_pass,
        "end_to_end_inclusion_direction": inclusion_pass,
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
    if acceptance_profile == "stability_probe":
        checks["post_adaptation_stability"] = stability_pass
    if requires_initialization_robustness(acceptance_profile):
        checks["initialization_robustness"] = all(
            spread <= 0.10 for spread in initialization_spreads.values()
        )
    diagnostics = {
        "expected_runs": len(expected),
        "complete_runs": len(complete),
        "acceptance_profile": acceptance_profile,
        "condition_active_stake_gain_means": condition_gain_means,
        "condition_active_stake_gain_intervals": condition_gain_intervals,
        "condition_positive_seed_counts": condition_positive_seed_counts,
        "condition_latency_reduction_intervals": condition_latency_intervals,
        "condition_latency_positive_seed_counts": (
            condition_latency_positive_seed_counts
        ),
        "condition_inclusion_rate_gain_intervals": (
            condition_inclusion_rate_intervals
        ),
        "condition_inclusion_direction": condition_inclusion_direction,
        "counterfactual_coverage_by_protocol": counterfactual_coverage_by_protocol,
        "counterfactual_unavailable_updates_by_protocol": (
            unavailable_updates_by_protocol
        ),
        "maximum_post_adaptation_active_stake_drift": (
            maximum_post_adaptation_drift
        ),
        "p90_individual_post_adaptation_active_stake_drift": (
            p90_post_adaptation_drift
        ),
        "group_post_adaptation_active_stake_drifts": (
            group_post_adaptation_drifts
        ),
        "maximum_group_post_adaptation_active_stake_drift": (
            maximum_group_post_adaptation_drift
        ),
        "maximum_post_adaptation_active_stake_stddev": (
            maximum_post_adaptation_stddev
        ),
        "exploratory_decisions": sum(
            int(number(row["exploratory_decision_count"]))
            for row in utility_rows
        ),
        "pairing_mismatches": pairing_mismatches,
    }
    if acceptance_profile == "full_pilot":
        diagnostics.update(
            {
                "initial_conditions_with_at_least_10pp_gain_by_cost": dict(
                    sorted(passing_initials_by_cost.items())
                ),
                "cost_regimes_with_broad_participation_gain": (
                    passing_cost_regimes
                ),
                "required_cost_regimes": 2,
                "initial_conditions_with_better_bounded_inclusion_by_cost": dict(
                    sorted(improving_initials_by_cost.items())
                ),
                "cost_regimes_with_better_bounded_inclusion": (
                    improving_end_to_end_cost_regimes
                ),
                "initialization_spreads": initialization_spreads,
            }
        )
    elif acceptance_profile == "sensitivity":
        diagnostics["parameter_variant_spreads"] = initialization_spreads
    acceptance = {
        "suite": suite,
        "pass": all(checks.values()),
        "checks": checks,
        "diagnostics": diagnostics,
    }
    acceptance_path = prefix.with_name(prefix.name + "_acceptance.json")
    acceptance_path.write_text(json.dumps(acceptance, indent=2) + "\n", encoding="utf-8")
    summary_lines = [
        f"# History-only adaptive participation: {acceptance_profile}",
        "",
        "Validators update Active/Lazy strategies from completed-window public reward and forwarding observations. The model uses fixed calibrated costs and no future proposer draws; it is behavioral evidence, not an equilibrium proof.",
        "",
        "| Condition | Protocol | Cost multiplier | Initial active | Post-adaptation active stake | Included within horizon | Restricted mean | Utility-consistent |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in groups:
        summary_lines.append(
            f"| {row['experiment']} | {row['protocol_label']} | "
            f"{number(row['cost_median_multiplier']):g} | "
            f"{number(row['initial_active_fraction']):.0%} | "
            f"{number(row['steady_active_stake_share']):.1%} | "
            f"{number(row['inclusion_within_horizon_rate']):.1%} | "
            f"{number(row['restricted_mean_inclusion_latency_s']):.2f}s | "
            f"{number(row['utility_consistency_share']):.1%} |"
        )
    summary_lines.extend(
        [
            "",
            "| Paired condition | Full-minus-fee active stake | Positive seeds | Restricted-mean reduction | Positive seeds |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for key, interval in condition_gain_intervals.items():
        latency = condition_latency_intervals[key]
        summary_lines.append(
            f"| {key} | {interval['mean']:.1%} "
            f"$\\pm$ {interval['ci95']:.1%} | "
            f"{condition_positive_seed_counts[key]}/{interval['n']} | "
            f"{latency['mean']:.2f}s $\\pm$ {latency['ci95']:.2f}s | "
            f"{condition_latency_positive_seed_counts[key]}/{latency['n']} |"
        )
    summary_lines.extend(
        [
            "",
            "Acceptance: **" + ("PASS" if acceptance["pass"] else "FAIL") + "**",
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
