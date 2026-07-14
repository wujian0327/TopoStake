#!/usr/bin/env python3
"""Validate and summarize the frozen-v1 long-horizon fee/bonus comparison."""

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


PROTOCOLS = ("topostake_eta0", "topostake")
PAIR_METRICS = (
    "throughput_mean",
    "p95_inclusion_latency_s_pooled",
    "inclusion_ratio",
    "credit_eligible_rate",
    "relay_reward_total",
    "proposer_reward_total",
    "relay_reward_per_stake_gini",
    "total_reward_per_stake_gini",
    "relay_reward_degree_spearman",
    "relay_reward_betweenness_spearman",
    "top_degree_quartile_relay_reward_share",
    "forward_attempts_per_included_tx",
    "break_even_relay_cost_per_forward",
    "active_relay_reward_per_stake",
    "lazy_relay_reward_per_stake",
    "active_proposer_reward_per_stake",
    "lazy_proposer_reward_per_stake",
    "active_total_reward_per_stake",
    "lazy_total_reward_per_stake",
    "participation_reward_premium_per_stake",
    "active_forward_attempts_per_stake",
    "lazy_forward_attempts_per_stake",
    "participation_forward_premium_per_stake",
    "participation_break_even_cost_per_forward",
)

# Two-sided 95% Student-t critical values indexed by sample count. The formal
# suite uses 20 seeds; retaining the small-n entries keeps pilot intervals
# honest instead of applying a normal approximation to three observations.
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


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def percentile(values: Iterable[float], quantile: float) -> float:
    ordered = sorted(value for value in values if math.isfinite(value))
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * quantile
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def gini(values: Iterable[float]) -> float:
    ordered = sorted(max(0.0, value) for value in values if math.isfinite(value))
    if not ordered or sum(ordered) <= 0.0:
        return 0.0
    n = len(ordered)
    weighted = sum((index + 1) * value for index, value in enumerate(ordered))
    return 2.0 * weighted / (n * sum(ordered)) - (n + 1.0) / n


def ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: values[index])
    result = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and values[order[end]] == values[order[start]]:
            end += 1
        rank = (start + 1 + end) / 2.0
        for position in range(start, end):
            result[order[position]] = rank
        start = end
    return result


def pearson(xs: list[float], ys: list[float]) -> float:
    if len(xs) < 2 or len(xs) != len(ys):
        return 0.0
    x_mean, y_mean = statistics.mean(xs), statistics.mean(ys)
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    x_norm = math.sqrt(sum((x - x_mean) ** 2 for x in xs))
    y_norm = math.sqrt(sum((y - y_mean) ** 2 for y in ys))
    return numerator / (x_norm * y_norm) if x_norm > 0.0 and y_norm > 0.0 else 0.0


def spearman(xs: list[float], ys: list[float]) -> float:
    return pearson(ranks(xs), ranks(ys))


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


def aggregate_run(run: dict[str, Any]) -> dict[str, Any]:
    output = Path(run["output_dir"])
    status = read_json(output / "runner_status.json")
    summary = read_json(output / "run_summary.json")
    run_config = read_json(output / "run_config.json")
    epochs = read_csv(output / "epoch_metrics.csv")
    nodes = read_csv(output / "node_epoch_metrics.csv")
    samples = read_csv(output / "inclusion_samples.csv")
    warmup = int(run.get("warmup_epochs", 0))
    slots_per_epoch = max(1, int(run.get("slot_per_epoch", 1)))
    warmup_slot = warmup * slots_per_epoch
    usable_epochs = [row for row in epochs if int(number(row.get("epoch"))) >= warmup]
    usable_nodes = [row for row in nodes if int(number(row.get("epoch"))) >= warmup]
    usable_samples = [
        row for row in samples if int(number(row.get("created_slot"), -1.0)) >= warmup_slot
    ]

    node_totals: dict[str, dict[str, Any]] = {}
    for row in usable_nodes:
        validator = row.get("validator_id", "")
        item = node_totals.setdefault(
            validator,
            {
                "profile": row.get("relay_profile", ""),
                "stake": number(row.get("economic_stake")),
                "degree": number(row.get("degree")),
                "betweenness": number(row.get("betweenness")),
                "relay_reward": 0.0,
                "proposer_reward": 0.0,
                "forward_attempts": 0.0,
            },
        )
        item["relay_reward"] += number(row.get("relay_reward"))
        item["proposer_reward"] += number(row.get("proposer_reward"))
        item["forward_attempts"] += number(row.get("relay_forward_attempts"))

    per_stake = []
    total_per_stake = []
    degrees = []
    betweenness = []
    relay_rewards = []
    by_profile: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in node_totals.values():
        stake = max(number(item["stake"]), 1e-15)
        relay_per_stake = number(item["relay_reward"]) / stake
        combined_per_stake = (
            number(item["relay_reward"]) + number(item["proposer_reward"])
        ) / stake
        per_stake.append(relay_per_stake)
        total_per_stake.append(combined_per_stake)
        degrees.append(number(item["degree"]))
        betweenness.append(number(item["betweenness"]))
        relay_rewards.append(number(item["relay_reward"]))
        item["relay_reward_per_stake"] = relay_per_stake
        item["proposer_reward_per_stake"] = number(item["proposer_reward"]) / stake
        item["total_reward_per_stake"] = combined_per_stake
        item["forward_attempts_per_stake"] = number(item["forward_attempts"]) / stake
        by_profile[str(item["profile"])].append(item)

    top_count = max(1, math.ceil(len(node_totals) / 4)) if node_totals else 0
    top_nodes = sorted(node_totals.values(), key=lambda item: number(item["degree"]), reverse=True)[
        :top_count
    ]
    relay_reward_total = sum(relay_rewards)
    proposer_reward_total = sum(number(item["proposer_reward"]) for item in node_totals.values())
    forward_attempts = sum(number(item["forward_attempts"]) for item in node_totals.values())
    generated = sum(number(row.get("generated_tx")) for row in usable_epochs)
    sample_keys = [row.get("tx_hash", "") for row in usable_samples]
    duplicate_samples = len(sample_keys) - len(set(sample_keys))
    eligible_samples = sum(truthy(row.get("evidence_eligible")) for row in usable_samples)

    def profile_mean(profile: str, metric: str) -> float:
        values = [number(item.get(metric)) for item in by_profile.get(profile, [])]
        return statistics.mean(values) if values else 0.0

    profile_comparison_available = bool(by_profile.get("active")) and bool(
        by_profile.get("lazy")
    )
    active_total_reward_per_stake = profile_mean("active", "total_reward_per_stake")
    lazy_total_reward_per_stake = profile_mean("lazy", "total_reward_per_stake")
    active_forward_attempts_per_stake = profile_mean("active", "forward_attempts_per_stake")
    lazy_forward_attempts_per_stake = profile_mean("lazy", "forward_attempts_per_stake")
    participation_reward_premium = (
        active_total_reward_per_stake - lazy_total_reward_per_stake
        if profile_comparison_available
        else 0.0
    )
    participation_forward_premium = (
        active_forward_attempts_per_stake - lazy_forward_attempts_per_stake
        if profile_comparison_available
        else 0.0
    )
    participation_break_even_cost = (
        participation_reward_premium / participation_forward_premium
        if participation_forward_premium > 0.0
        else 0.0
    )

    complete = (
        status.get("status") == "ok"
        and int(number(summary.get("completed_epochs"), -1.0)) >= int(run.get("max_epochs", 0))
        and len(usable_epochs) >= int(run.get("max_epochs", 0)) - warmup
        and bool(node_totals)
    )
    observed_lazy_fraction = (
        len(by_profile.get("lazy", [])) / len(node_totals) if node_totals else 0.0
    )
    profile_assignment = "|".join(
        f"{validator}:{item['profile']}" for validator, item in sorted(node_totals.items())
    )
    return {
        "suite": run.get("suite", ""),
        "protocol_version": run.get("protocol_version", ""),
        "experiment": run.get("experiment", ""),
        "run_id": run.get("run_id", ""),
        "protocol_label": run.get("protocol_label", ""),
        "seed_index": run.get("seed_index", ""),
        "lazy_fraction": number(run.get("lazy_fraction")),
        "observed_lazy_fraction": observed_lazy_fraction,
        "profile_comparison_available": profile_comparison_available,
        "profile_assignment_hash": hashlib.sha256(profile_assignment.encode()).hexdigest(),
        "git_commit_sha": run_config.get("git_commit_sha", "unknown"),
        "status": status.get("status", "missing"),
        "complete": complete,
        "usable_epoch_count": len(usable_epochs),
        "validator_count": len(node_totals),
        "generated_tx": generated,
        "included_tx": len(usable_samples),
        "inclusion_sample_duplicate_count": duplicate_samples,
        "throughput_mean": statistics.mean(
            [number(row.get("throughput")) for row in usable_epochs]
        )
        if usable_epochs
        else 0.0,
        "p95_inclusion_latency_s_pooled": percentile(
            [number(row.get("latency_s")) for row in usable_samples], 0.95
        ),
        "inclusion_ratio": len(usable_samples) / generated if generated > 0.0 else 0.0,
        "credit_eligible_rate": (
            eligible_samples / len(usable_samples) if usable_samples else 0.0
        ),
        "relay_reward_total": relay_reward_total,
        "proposer_reward_total": proposer_reward_total,
        "relay_reward_per_stake_gini": gini(per_stake),
        "total_reward_per_stake_gini": gini(total_per_stake),
        "relay_reward_degree_spearman": spearman(degrees, per_stake),
        "relay_reward_betweenness_spearman": spearman(betweenness, per_stake),
        "top_degree_quartile_relay_reward_share": (
            sum(number(item["relay_reward"]) for item in top_nodes) / relay_reward_total
            if relay_reward_total > 0.0
            else 0.0
        ),
        "relay_forward_attempts": forward_attempts,
        "forward_attempts_per_included_tx": (
            forward_attempts / len(usable_samples) if usable_samples else 0.0
        ),
        "break_even_relay_cost_per_forward": (
            relay_reward_total / forward_attempts if forward_attempts > 0.0 else 0.0
        ),
        "active_relay_reward_per_stake": profile_mean("active", "relay_reward_per_stake"),
        "lazy_relay_reward_per_stake": profile_mean("lazy", "relay_reward_per_stake"),
        "active_proposer_reward_per_stake": profile_mean(
            "active", "proposer_reward_per_stake"
        ),
        "lazy_proposer_reward_per_stake": profile_mean(
            "lazy", "proposer_reward_per_stake"
        ),
        "active_total_reward_per_stake": active_total_reward_per_stake,
        "lazy_total_reward_per_stake": lazy_total_reward_per_stake,
        "participation_reward_premium_per_stake": participation_reward_premium,
        "active_forward_attempts_per_stake": active_forward_attempts_per_stake,
        "lazy_forward_attempts_per_stake": lazy_forward_attempts_per_stake,
        "participation_forward_premium_per_stake": participation_forward_premium,
        "participation_break_even_cost_per_forward": participation_break_even_cost,
        "active_forward_attempts_per_epoch": (
            profile_mean("active", "forward_attempts") / len(usable_epochs)
            if usable_epochs
            else 0.0
        ),
        "lazy_forward_attempts_per_epoch": (
            profile_mean("lazy", "forward_attempts") / len(usable_epochs)
            if usable_epochs
            else 0.0
        ),
        "bound_violation_count": sum(
            1 for row in usable_epochs if truthy(row.get("bound_violation"))
        ),
    }


def paired_rows(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    index = {
        (int(number(row["seed_index"])), number(row["lazy_fraction"]), row["protocol_label"]): row
        for row in runs
        if row["complete"]
    }
    output = []
    for seed, fraction, protocol in sorted(index):
        if protocol != "topostake":
            continue
        full = index[(seed, fraction, "topostake")]
        fee = index.get((seed, fraction, "topostake_eta0"))
        if fee is None:
            continue
        for metric in PAIR_METRICS:
            output.append(
                {
                    "seed_index": seed,
                    "lazy_fraction": fraction,
                    "metric": metric,
                    "full_value": number(full.get(metric)),
                    "fee_only_value": number(fee.get(metric)),
                    "difference": number(full.get(metric)) - number(fee.get(metric)),
                }
            )
    return output


def group_rows(runs: list[dict[str, Any]], pairs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, float, str], list[float]] = defaultdict(list)
    for row in runs:
        if not row["complete"]:
            continue
        for metric in PAIR_METRICS:
            groups[(row["protocol_label"], number(row["lazy_fraction"]), metric)].append(
                number(row.get(metric))
            )
    output = []
    for (protocol, fraction, metric), values in sorted(groups.items()):
        mean, ci, n = mean_ci(values)
        output.append(
            {
                "series": protocol,
                "lazy_fraction": fraction,
                "metric": metric,
                "n": n,
                "mean": mean,
                "ci95": ci,
            }
        )
    pair_groups: dict[tuple[float, str], list[float]] = defaultdict(list)
    for row in pairs:
        pair_groups[(number(row["lazy_fraction"]), row["metric"])].append(number(row["difference"]))
    for (fraction, metric), values in sorted(pair_groups.items()):
        mean, ci, n = mean_ci(values)
        output.append(
            {
                "series": "full-minus-fee-only",
                "lazy_fraction": fraction,
                "metric": metric,
                "n": n,
                "mean": mean,
                "ci95": ci,
            }
        )
    return output


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else ["empty"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--allow-incomplete", action="store_true")
    args = parser.parse_args()
    config_path = (ROOT / args.config).resolve()
    spec = load_yaml(config_path)
    expected = expand_runs(spec)
    runs = [aggregate_run(run) for run in expected]
    pairs = paired_rows(runs)
    groups = group_rows(runs, pairs)
    suite = str(spec.get("suite", config_path.stem))
    prefix = PROCESSED_ROOT / suite
    write_csv(prefix.with_name(prefix.name + "_runs.csv"), runs)
    write_csv(prefix.with_name(prefix.name + "_paired.csv"), pairs)
    write_csv(prefix.with_name(prefix.name + "_groups.csv"), groups)

    complete = [row for row in runs if row["complete"]]
    fractions = sorted({number(run.get("lazy_fraction")) for run in expected})
    expected_pair_count = len(spec.get("seeds", [0])) * len(fractions) * len(PAIR_METRICS)
    profile_mismatches = sum(
        1
        for row in complete
        if abs(number(row["observed_lazy_fraction"]) - number(row["lazy_fraction"]))
        > 1.0 / max(1.0, number(row["validator_count"])) + 1e-12
    )
    assignment_index: dict[tuple[int, float], set[str]] = defaultdict(set)
    for row in complete:
        assignment_index[(int(number(row["seed_index"])), number(row["lazy_fraction"]))].add(
            str(row["profile_assignment_hash"])
        )
    assignment_pair_mismatches = sum(len(hashes) != 1 for hashes in assignment_index.values())
    inclusion_accounting_errors = sum(
        int(number(row["inclusion_sample_duplicate_count"])) > 0
        or number(row["inclusion_ratio"]) > 1.0 + 1e-9
        for row in complete
    )
    non_finite = sum(
        1
        for row in complete
        for metric in PAIR_METRICS
        if not math.isfinite(number(row.get(metric), math.nan))
    )
    profile_coverage_errors = sum(
        1
        for row in complete
        if (number(row["lazy_fraction"]) > 0.0)
        != bool(row["profile_comparison_available"])
    )
    checks = [
        {
            "name": "run-completeness",
            "passed": len(complete) == len(expected),
            "detail": f"complete={len(complete)}/{len(expected)}",
        },
        {
            "name": "paired-completeness",
            "passed": len(pairs) == expected_pair_count,
            "detail": f"metric pairs={len(pairs)}/{expected_pair_count}",
        },
        {
            "name": "relay-profile-assignment",
            "passed": profile_mismatches == 0 and assignment_pair_mismatches == 0,
            "detail": (
                f"fraction mismatches={profile_mismatches}, "
                f"paired assignment mismatches={assignment_pair_mismatches}"
            ),
        },
        {
            "name": "inclusion-accounting",
            "passed": inclusion_accounting_errors == 0,
            "detail": f"accounting errors={inclusion_accounting_errors}",
        },
        {
            "name": "relay-work-observed",
            "passed": bool(complete) and all(number(row["relay_forward_attempts"]) > 0 for row in complete),
            "detail": f"zero-work runs={sum(number(row['relay_forward_attempts']) <= 0 for row in complete)}",
        },
        {
            "name": "participation-profile-coverage",
            "passed": profile_coverage_errors == 0,
            "detail": f"coverage errors={profile_coverage_errors}",
        },
        {
            "name": "finite-metrics",
            "passed": non_finite == 0,
            "detail": f"non-finite values={non_finite}",
        },
        {
            "name": "proposer-envelope",
            "passed": sum(int(number(row["bound_violation_count"])) for row in complete) == 0,
            "detail": f"violating epochs={sum(int(number(row['bound_violation_count'])) for row in complete)}",
        },
    ]
    passed = all(check["passed"] for check in checks)
    acceptance = {
        "suite": suite,
        "protocol_version": spec.get("protocol_version", ""),
        "expected_runs": len(expected),
        "successful_runs": len(complete),
        "passed": passed,
        "checks": checks,
    }
    acceptance_path = prefix.with_name(prefix.name + "_acceptance.json")
    acceptance_path.write_text(json.dumps(acceptance, indent=2) + "\n", encoding="utf-8")
    print(f"{suite}: {'PASS' if passed else 'INCOMPLETE/FAIL'}")
    for check in checks:
        if not check["passed"]:
            print(f"FAILED {check['name']}: {check['detail']}")
    print(f"wrote {acceptance_path.relative_to(ROOT)}")
    return 0 if passed or args.allow_incomplete else 1


if __name__ == "__main__":
    raise SystemExit(main())
