#!/usr/bin/env python3
"""Validate and summarize frozen-v1 organic-traffic path-capture experiments."""

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


BASELINE = "none"
STRESS = "max-score"
PAIR_METRICS = (
    "organic_valid_path_rate",
    "adversary_organic_relay_reward_share",
    "adversary_organic_raw_contribution_share",
    "organic_relay_capture_amplification",
    "organic_contribution_capture_amplification",
    "adversary_score_share",
    "adversary_proposer_weight_share",
    "score_share_lift",
    "proposer_weight_share_lift",
)

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


def mean_ci(values: Iterable[float]) -> tuple[float, float, int]:
    clean = [float(value) for value in values if math.isfinite(float(value))]
    count = len(clean)
    if not clean:
        return 0.0, 0.0, 0
    mean = statistics.mean(clean)
    if count < 2:
        return mean, 0.0, count
    critical = T95.get(count, 1.96)
    return mean, critical * statistics.stdev(clean) / math.sqrt(count), count


def ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator > 0.0 else 0.0


def aggregate_run(run: dict[str, Any]) -> dict[str, Any]:
    output = Path(run["output_dir"])
    status = read_json(output / "runner_status.json")
    summary = read_json(output / "run_summary.json")
    run_config = read_json(output / "run_config.json")
    epochs = read_csv(output / "epoch_metrics.csv")
    nodes = read_csv(output / "node_epoch_metrics.csv")
    warmup = int(run.get("warmup_epochs", 0))
    usable_epochs = [row for row in epochs if int(number(row.get("epoch"))) >= warmup]
    usable_nodes = [row for row in nodes if int(number(row.get("epoch"))) >= warmup]

    organic_included = sum(number(row.get("organic_included_tx")) for row in usable_epochs)
    organic_valid = sum(number(row.get("organic_valid_path_count")) for row in usable_epochs)
    organic_reward = sum(number(row.get("organic_relay_reward")) for row in usable_epochs)
    adversary_organic_reward = sum(
        number(row.get("adversary_organic_relay_reward")) for row in usable_epochs
    )
    organic_contribution = sum(
        number(row.get("organic_raw_contribution")) for row in usable_epochs
    )
    adversary_organic_contribution = sum(
        number(row.get("adversary_organic_raw_contribution")) for row in usable_epochs
    )
    included = sum(number(row.get("included_tx")) for row in usable_epochs)

    def epoch_mean(field: str) -> float:
        values = [number(row.get(field)) for row in usable_epochs]
        return statistics.mean(values) if values else 0.0

    stake_share = epoch_mean("adversary_real_stake_share")
    score_share = epoch_mean("adversary_score_share")
    proposer_share = epoch_mean("adversary_proposer_weight_share")
    organic_reward_share = ratio(adversary_organic_reward, organic_reward)
    organic_contribution_share = ratio(
        adversary_organic_contribution, organic_contribution
    )
    adversarial_ids = sorted(
        {
            row.get("validator_id", "")
            for row in usable_nodes
            if truthy(row.get("adversarial"))
        }
    )
    assignment_hash = hashlib.sha256("|".join(adversarial_ids).encode()).hexdigest()
    complete = (
        status.get("status") == "ok"
        and int(number(summary.get("completed_epochs"), -1.0))
        >= int(run.get("max_epochs", 0))
        and len(usable_epochs) >= int(run.get("max_epochs", 0)) - warmup
        and bool(usable_epochs)
    )

    return {
        "suite": run.get("suite", ""),
        "protocol_version": run.get("protocol_version", ""),
        "experiment": run.get("experiment", ""),
        "run_id": run.get("run_id", ""),
        "node_num": int(number(run.get("node_num"))),
        "topology": str(run.get("topology", "")),
        "seed_index": int(number(run.get("seed_index"))),
        "adversary_stake_fraction": number(run.get("adversary_stake_fraction")),
        "adversary_placement": str(run.get("adversary_placement", "")),
        "attack_mode": str(run.get("attack_mode", "")),
        "adversary_assignment_hash": assignment_hash,
        "git_commit_sha": run_config.get("git_commit_sha", ""),
        "status": status.get("status", "missing"),
        "duration_seconds": number(status.get("duration_seconds")),
        "complete": complete,
        "usable_epoch_count": len(usable_epochs),
        "included_tx": included,
        "organic_included_tx": organic_included,
        "organic_traffic_fraction": ratio(organic_included, included),
        "organic_valid_path_count": organic_valid,
        "organic_valid_path_rate": ratio(organic_valid, organic_included),
        "organic_relay_reward": organic_reward,
        "adversary_organic_relay_reward": adversary_organic_reward,
        "adversary_organic_relay_reward_share": organic_reward_share,
        "organic_raw_contribution": organic_contribution,
        "adversary_organic_raw_contribution": adversary_organic_contribution,
        "adversary_organic_raw_contribution_share": organic_contribution_share,
        "adversary_real_stake_share": stake_share,
        "organic_relay_capture_amplification": ratio(organic_reward_share, stake_share),
        "organic_contribution_capture_amplification": ratio(
            organic_contribution_share, stake_share
        ),
        "adversary_score_share": score_share,
        "adversary_proposer_weight_share": proposer_share,
        "score_share_lift": score_share - stake_share,
        "proposer_weight_share_lift": proposer_share - stake_share,
        "theoretical_proposer_weight_bound": epoch_mean(
            "theoretical_proposer_weight_bound"
        ),
        "score_dependent_proposer_weight_bound": epoch_mean(
            "score_dependent_proposer_weight_bound"
        ),
        "bound_violation_count": sum(
            truthy(row.get("bound_violation")) for row in usable_epochs
        ),
    }


def paired_rows(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    index = {
        (
            int(row["seed_index"]),
            number(row["adversary_stake_fraction"]),
            str(row["adversary_placement"]),
            str(row["attack_mode"]),
        ): row
        for row in runs
        if row["complete"]
    }
    output = []
    conditions = sorted({key[:3] for key in index})
    for seed, stake, placement in conditions:
        baseline = index.get((seed, stake, placement, BASELINE))
        stress = index.get((seed, stake, placement, STRESS))
        if not baseline or not stress:
            continue
        for metric in PAIR_METRICS:
            baseline_value = number(baseline.get(metric))
            stress_value = number(stress.get(metric))
            output.append(
                {
                    "seed_index": seed,
                    "adversary_stake_fraction": stake,
                    "adversary_placement": placement,
                    "metric": metric,
                    "stress_value": stress_value,
                    "baseline_value": baseline_value,
                    "difference": stress_value - baseline_value,
                }
            )
    return output


def group_rows(
    runs: list[dict[str, Any]], pairs: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, float, str], list[float]] = defaultdict(list)
    for row in runs:
        if not row["complete"]:
            continue
        series = f"{row['attack_mode']}:{row['adversary_placement']}"
        for metric in PAIR_METRICS + ("theoretical_proposer_weight_bound",):
            grouped[
                (
                    series,
                    str(row["adversary_placement"]),
                    number(row["adversary_stake_fraction"]),
                    metric,
                )
            ].append(number(row.get(metric)))
    for row in pairs:
        placement = str(row["adversary_placement"])
        grouped[
            (
                f"{STRESS}-minus-{BASELINE}:{placement}",
                placement,
                number(row["adversary_stake_fraction"]),
                str(row["metric"]),
            )
        ].append(number(row["difference"]))

    output = []
    for (series, placement, stake, metric), values in sorted(grouped.items()):
        mean, ci, count = mean_ci(values)
        output.append(
            {
                "series": series,
                "adversary_placement": placement,
                "adversary_stake_fraction": stake,
                "metric": metric,
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
    expected_conditions = {
        (
            int(number(run.get("seed_index"))),
            number(run.get("adversary_stake_fraction")),
            str(run.get("adversary_placement")),
        )
        for run in expected
    }
    assignment_index: dict[tuple[int, float, str], set[str]] = defaultdict(set)
    for row in complete:
        assignment_index[
            (
                int(row["seed_index"]),
                number(row["adversary_stake_fraction"]),
                str(row["adversary_placement"]),
            )
        ].add(str(row["adversary_assignment_hash"]))
    assignment_mismatches = sum(len(values) != 1 for values in assignment_index.values())
    accounting_errors = sum(
        number(row["adversary_organic_relay_reward"])
        > number(row["organic_relay_reward"]) + 1e-12
        or number(row["adversary_organic_raw_contribution"])
        > number(row["organic_raw_contribution"]) + 1e-12
        or not 0.0 <= number(row["adversary_organic_relay_reward_share"]) <= 1.0
        or not 0.0 <= number(row["adversary_organic_raw_contribution_share"]) <= 1.0
        for row in complete
    )
    non_finite = sum(
        not math.isfinite(number(row.get(metric), math.nan))
        for row in complete
        for metric in PAIR_METRICS
    )
    expected_pairs = len(expected_conditions) * len(PAIR_METRICS)
    checks = [
        {
            "name": "run-completeness",
            "passed": len(complete) == len(expected),
            "detail": f"complete={len(complete)}/{len(expected)}",
        },
        {
            "name": "paired-completeness",
            "passed": len(pairs) == expected_pairs,
            "detail": f"metric pairs={len(pairs)}/{expected_pairs}",
        },
        {
            "name": "adversary-assignment",
            "passed": assignment_mismatches == 0,
            "detail": f"paired assignment mismatches={assignment_mismatches}",
        },
        {
            "name": "organic-traffic-observed",
            "passed": bool(complete)
            and all(
                number(row["organic_included_tx"]) > 0.0
                and number(row["organic_valid_path_count"]) > 0.0
                for row in complete
            ),
            "detail": "zero organic/path runs="
            + str(
                sum(
                    number(row["organic_included_tx"]) <= 0.0
                    or number(row["organic_valid_path_count"]) <= 0.0
                    for row in complete
                )
            ),
        },
        {
            "name": "organic-capture-accounting",
            "passed": accounting_errors == 0,
            "detail": f"accounting errors={accounting_errors}",
        },
        {
            "name": "finite-metrics",
            "passed": non_finite == 0,
            "detail": f"non-finite values={non_finite}",
        },
        {
            "name": "proposer-envelope",
            "passed": sum(int(number(row["bound_violation_count"])) for row in complete)
            == 0,
            "detail": "violating epochs="
            + str(sum(int(number(row["bound_violation_count"])) for row in complete)),
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
