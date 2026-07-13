#!/usr/bin/env python3
"""Validate and summarize frozen-v1 simulator security experiments.

The deterministic protocol envelope is checked per epoch. Stochastic outcomes
are summarized over seeds and, where a natural reference exists, as paired
differences with 95% confidence intervals.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from run_experiments import DIMENSION_KEYS, PROCESSED_ROOT, ROOT, expand_runs, load_yaml


BOUND_TOLERANCE = 2e-6  # CSV values are emitted with six decimal places.
FIXED_PADDING_REPORT = (
    PROCESSED_ROOT / "frozen_v1_padding_fixed_path_acceptance.json"
)
REFERENCE_FIELDS = {
    "path_padding_end_to_end": ("padding_identities", 0),
    "flooding_cost_to_influence": ("attack_tx_rate_multiplier", 0),
    "relay_participation": ("relay_profile", "lazy"),
    "relay_network_stress": ("relay_profile", "lazy"),
    "score_floor_sensitivity": ("topostake_score_floor_kappa", 1.0),
}
PAIR_METRICS = [
    "adversary_raw_contribution_total",
    "adversary_relay_reward_total",
    "adversary_damped_score_mass_mean",
    "adversary_proposer_weight_share_mean",
    "adversary_fee_spent",
    "adversary_reward_income",
    "adversary_net_income",
    "adversary_credit_share",
    "adversary_relay_reward_share",
    "credit_ineligible_path_rate",
    "relay_reward_per_stake",
    "focal_raw_contribution_total",
    "focal_relay_reward_total",
    "focal_relay_reward_per_stake",
    "focal_bonus_mean",
    "focal_proposer_weight_mean",
    "p50_inclusion_latency_s_pooled",
    "p95_inclusion_latency_s_pooled",
    "p99_inclusion_latency_s_pooled",
    "inclusion_ratio",
]
RUN_METRICS = [
    "throughput",
    "p95_inclusion_latency_s",
    "block_success_ratio",
    "adversary_real_stake_share",
    "adversary_score_share",
    "adversary_damped_score_mass",
    "adversary_proposer_weight_share",
    "score_dependent_proposer_weight_bound",
    "theoretical_proposer_weight_bound",
    "observed_adversary_proposer_share",
]
IDENTITY_FIELDS = ["suite", "protocol_version", "experiment", "protocol_label", "protocol"]
SCENARIO_FIELDS = IDENTITY_FIELDS + DIMENSION_KEYS


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


def to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def is_true(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def mean_ci95(values: Iterable[float]) -> tuple[float, float, int]:
    clean = [value for value in values if math.isfinite(value)]
    if not clean:
        return math.nan, 0.0, 0
    if len(clean) == 1:
        return clean[0], 0.0, 1
    return (
        statistics.mean(clean),
        1.96 * statistics.stdev(clean) / math.sqrt(len(clean)),
        len(clean),
    )


def percentile(values: Iterable[float], quantile: float) -> float:
    ordered = sorted(value for value in values if math.isfinite(value))
    if not ordered:
        return math.nan
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def usable_rows(rows: list[dict[str, str]], warmup: int) -> list[dict[str, str]]:
    usable = [row for row in rows if int(to_float(row.get("epoch"))) >= warmup]
    return usable or rows


def aggregate_run(run: dict[str, Any]) -> dict[str, Any]:
    output_dir = Path(run["output_dir"])
    status = read_json(output_dir / "runner_status.json")
    summary = read_json(output_dir / "run_summary.json")
    epochs = read_csv(output_dir / "epoch_metrics.csv")
    nodes = read_csv(output_dir / "node_epoch_metrics.csv")
    inclusion_samples = read_csv(output_dir / "inclusion_samples.csv")
    warmup = int(run.get("warmup_epochs", 0))
    epochs = usable_rows(epochs, warmup)
    nodes = usable_rows(nodes, warmup)
    inclusion_samples = [
        row
        for row in inclusion_samples
        if int(to_float(row.get("included_epoch"))) >= warmup
    ]

    out = {field: run.get(field, "") for field in SCENARIO_FIELDS}
    out.update(
        {
            "run_id": run["run_id"],
            "seed_index": run["seed_index"],
            "seed_value": run["seed_value"],
            "output_dir": run["output_dir"],
            "status": status.get("status", "missing"),
            "completed_epochs": summary.get("completed_epochs", 0),
            "expected_epochs": run.get("max_epochs", 0),
            "adversary_fee_spent": summary.get("adversary_fee_spent", 0.0),
            "adversary_reward_income": summary.get("adversary_reward_income", 0.0),
            "adversary_net_income": summary.get("adversary_net_income", 0.0),
            "usable_epoch_count": len(epochs),
            "usable_node_rows": len(nodes),
        }
    )
    complete = (
        out["status"] == "ok"
        and int(to_float(out["completed_epochs"], -1)) >= int(to_float(out["expected_epochs"]))
        and bool(epochs)
        and bool(nodes)
    )
    out["complete"] = complete

    for metric in RUN_METRICS:
        values = [to_float(row.get(metric), math.nan) for row in epochs]
        out[f"{metric}_mean"] = mean_ci95(values)[0]

    score_excess = [
        to_float(row.get("adversary_proposer_weight_share"))
        - to_float(row.get("score_dependent_proposer_weight_bound"))
        for row in epochs
    ]
    cap_excess = [
        to_float(row.get("adversary_proposer_weight_share"))
        - to_float(row.get("theoretical_proposer_weight_bound"))
        for row in epochs
    ]
    bound_order_excess = [
        to_float(row.get("score_dependent_proposer_weight_bound"))
        - to_float(row.get("theoretical_proposer_weight_bound"))
        for row in epochs
    ]
    out["bound_violation_count"] = sum(is_true(row.get("bound_violation")) for row in epochs)
    out["max_score_bound_excess"] = max(score_excess, default=0.0)
    out["max_cap_bound_excess"] = max(cap_excess, default=0.0)
    out["max_bound_order_excess"] = max(bound_order_excess, default=0.0)
    out["eligible_path_count"] = sum(
        int(to_float(row.get("valid_path_count"))) for row in epochs
    )
    out["credit_ineligible_path_count"] = sum(
        int(to_float(row.get("invalid_path_count"))) for row in epochs
    )
    out["included_tx_total"] = sum(
        int(to_float(row.get("included_tx"))) for row in epochs
    )
    out["generated_tx_total"] = sum(
        int(to_float(row.get("generated_tx"))) for row in epochs
    )
    out["inclusion_ratio"] = (
        out["included_tx_total"] / out["generated_tx_total"]
        if out["generated_tx_total"] > 0
        else 0.0
    )
    latency_samples = [
        to_float(row.get("latency_s"), math.nan) for row in inclusion_samples
    ]
    out["inclusion_latency_sample_count"] = sum(
        math.isfinite(value) for value in latency_samples
    )
    out["inclusion_latency_sample_coverage"] = (
        out["inclusion_latency_sample_count"] / out["included_tx_total"]
        if out["included_tx_total"] > 0
        else 0.0
    )
    out["p50_inclusion_latency_s_pooled"] = percentile(latency_samples, 0.50)
    out["p95_inclusion_latency_s_pooled"] = percentile(latency_samples, 0.95)
    out["p99_inclusion_latency_s_pooled"] = percentile(latency_samples, 0.99)
    out["credit_ineligible_path_rate"] = (
        out["credit_ineligible_path_count"] / out["included_tx_total"]
        if out["included_tx_total"] > 0
        else 0.0
    )
    out["evidence_accounting_mismatch"] = sum(
        abs(
            int(to_float(row.get("valid_path_count")))
            + int(to_float(row.get("invalid_path_count")))
            - int(to_float(row.get("included_tx")))
        )
        for row in epochs
    )

    adversarial = [row for row in nodes if is_true(row.get("adversarial"))]
    out["adversary_raw_contribution_total"] = sum(
        to_float(row.get("raw_contribution")) for row in adversarial
    )
    out["adversary_relay_reward_total"] = sum(
        to_float(row.get("relay_reward")) for row in adversarial
    )
    out["raw_contribution_total"] = sum(to_float(row.get("raw_contribution")) for row in nodes)
    relay_reward = sum(to_float(row.get("relay_reward")) for row in nodes)
    out["adversary_credit_share"] = (
        out["adversary_raw_contribution_total"] / out["raw_contribution_total"]
        if out["raw_contribution_total"] > 0
        else 0.0
    )
    out["adversary_relay_reward_share"] = (
        out["adversary_relay_reward_total"] / relay_reward if relay_reward > 0 else 0.0
    )
    stake_exposure = sum(to_float(row.get("economic_stake")) for row in nodes)
    out["relay_reward_per_stake"] = relay_reward / stake_exposure if stake_exposure > 0 else 0.0
    focal = [row for row in nodes if is_true(row.get("focal_relayer"))]
    background = [row for row in nodes if not is_true(row.get("focal_relayer"))]
    out["focal_node_rows"] = len(focal)
    out["focal_profile_mismatch_count"] = sum(
        str(row.get("relay_profile")) != str(run.get("relay_profile")) for row in focal
    )
    out["background_profile_mismatch_count"] = (
        sum(
            str(row.get("relay_profile")) != str(run.get("relay_background_profile"))
            for row in background
        )
        if int(to_float(run.get("focal_relayer_count"))) > 0
        else 0
    )
    out["focal_raw_contribution_total"] = sum(
        to_float(row.get("raw_contribution")) for row in focal
    )
    out["focal_relay_reward_total"] = sum(
        to_float(row.get("relay_reward")) for row in focal
    )
    focal_stake_exposure = sum(to_float(row.get("economic_stake")) for row in focal)
    out["focal_relay_reward_per_stake"] = (
        out["focal_relay_reward_total"] / focal_stake_exposure
        if focal_stake_exposure > 0
        else 0.0
    )
    out["focal_bonus_mean"] = mean_ci95(
        to_float(row.get("bonus"), math.nan) for row in focal
    )[0]
    out["focal_proposer_weight_mean"] = mean_ci95(
        to_float(row.get("normalized_proposer_weight"), math.nan) for row in focal
    )[0]
    out["finite_metrics"] = all(
        math.isfinite(to_float(out.get(field), math.nan))
        for field in [
            "max_score_bound_excess",
            "max_cap_bound_excess",
            "max_bound_order_excess",
            "adversary_raw_contribution_total",
            "adversary_relay_reward_total",
            "adversary_credit_share",
            "adversary_relay_reward_share",
            "credit_ineligible_path_rate",
            "relay_reward_per_stake",
            "inclusion_ratio",
            "p95_inclusion_latency_s_pooled",
        ]
    )
    return out


def scenario_key(row: dict[str, Any], excluded: str | None = None) -> tuple[Any, ...]:
    fields = [field for field in SCENARIO_FIELDS if field != excluded]
    return tuple(str(row.get(field, "")) for field in fields)


def group_runs(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    fields = SCENARIO_FIELDS
    for row in rows:
        if row["complete"]:
            groups[tuple(str(row.get(field, "")) for field in fields)].append(row)
    result: list[dict[str, Any]] = []
    numeric = PAIR_METRICS + [
        "max_score_bound_excess",
        "max_cap_bound_excess",
        "max_bound_order_excess",
        "credit_ineligible_path_count",
        "credit_ineligible_path_rate",
        "evidence_accounting_mismatch",
    ]
    for key, group in sorted(groups.items()):
        base = dict(zip(fields, key))
        for metric in numeric:
            avg, ci, n = mean_ci95(to_float(row.get(metric), math.nan) for row in group)
            result.append({**base, "metric": metric, "n": n, "mean": avg, "ci95": ci})
    return result


def paired_differences(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    complete = [row for row in rows if row["complete"]]
    result: list[dict[str, Any]] = []
    for experiment, (field, reference_value) in REFERENCE_FIELDS.items():
        selected = [row for row in complete if row.get("experiment") == experiment]
        references = {
            (scenario_key(row, field), int(row["seed_value"])): row
            for row in selected
            if str(row.get(field)) == str(reference_value)
        }
        buckets: dict[tuple[tuple[Any, ...], str, str], list[float]] = defaultdict(list)
        for row in selected:
            if str(row.get(field)) == str(reference_value):
                continue
            reference = references.get((scenario_key(row, field), int(row["seed_value"])))
            if not reference:
                continue
            for metric in PAIR_METRICS:
                diff = to_float(row.get(metric), math.nan) - to_float(reference.get(metric), math.nan)
                if math.isfinite(diff):
                    buckets[(scenario_key(row), str(row.get(field)), metric)].append(diff)
        for (key, scenario_value, metric), values in sorted(buckets.items()):
            avg, ci, n = mean_ci95(values)
            base = dict(zip(SCENARIO_FIELDS, key))
            result.append(
                {
                    **base,
                    "reference_field": field,
                    "reference_value": reference_value,
                    "scenario_value": scenario_value,
                    "metric": metric,
                    "n_pairs": n,
                    "mean_difference": avg,
                    "ci95": ci,
                    "ci95_low": avg - ci,
                    "ci95_high": avg + ci,
                }
            )
    return result


def check(name: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "detail": detail}


def fixed_padding_check(path: Path = FIXED_PADDING_REPORT) -> dict[str, Any]:
    report = read_json(path)
    return check(
        "fixed-path-padding-non-amplification",
        bool(report.get("passed")) and int(report.get("violations", -1)) == 0,
        "cases={}, coalition assignments={}, maximum ratio={}".format(
            report.get("cases", 0),
            report.get("coalition_assignments", 0),
            report.get("maximum_ratio", "missing"),
        ),
    )


def validation(rows: list[dict[str, Any]], expected_seeds: int) -> list[dict[str, Any]]:
    complete = [row for row in rows if row["complete"]]
    scenario_counts: dict[tuple[Any, ...], int] = defaultdict(int)
    for row in complete:
        scenario_counts[scenario_key(row)] += 1
    min_coverage = min(scenario_counts.values(), default=0)
    max_score_excess = max((to_float(row["max_score_bound_excess"]) for row in complete), default=0.0)
    max_cap_excess = max((to_float(row["max_cap_bound_excess"]) for row in complete), default=0.0)
    max_order_excess = max(
        (to_float(row["max_bound_order_excess"]) for row in complete), default=0.0
    )
    return [
        check("run-completeness", len(complete) == len(rows), f"complete={len(complete)}/{len(rows)}"),
        check(
            "seed-coverage",
            bool(scenario_counts) and min_coverage >= expected_seeds,
            f"minimum successful seeds per scenario={min_coverage}, expected={expected_seeds}",
        ),
        check(
            "score-dependent-proposer-bound",
            all(row["bound_violation_count"] == 0 for row in complete)
            and max_score_excess <= BOUND_TOLERANCE,
            f"maximum excess={max_score_excess:.3g}",
        ),
        check(
            "score-independent-proposer-cap",
            max_cap_excess <= BOUND_TOLERANCE and max_order_excess <= BOUND_TOLERANCE,
            f"weight excess={max_cap_excess:.3g}, score-bound excess over cap={max_order_excess:.3g}",
        ),
        check(
            "evidence-eligibility-accounting",
            all(row["evidence_accounting_mismatch"] == 0 for row in complete),
            "credit-ineligible={} ({:.2%}), accounting mismatches={}".format(
                sum(int(row["credit_ineligible_path_count"]) for row in complete),
                (
                    sum(int(row["credit_ineligible_path_count"]) for row in complete)
                    / sum(int(row["included_tx_total"]) for row in complete)
                    if sum(int(row["included_tx_total"]) for row in complete) > 0
                    else 0.0
                ),
                sum(int(row["evidence_accounting_mismatch"]) for row in complete),
            ),
        ),
        check(
            "transaction-latency-sample-coverage",
            all(
                to_float(row.get("inclusion_latency_sample_coverage")) >= 1.0 - 1e-9
                for row in complete
            ),
            "minimum sample coverage={:.2%}".format(
                min(
                    (
                        to_float(row.get("inclusion_latency_sample_coverage"))
                        for row in complete
                    ),
                    default=0.0,
                )
            ),
        ),
        check(
            "focal-relayer-isolation",
            all(
                int(row.get("focal_node_rows", 0))
                == int(to_float(row.get("focal_relayer_count")))
                * int(row.get("usable_epoch_count", 0))
                and int(row.get("focal_profile_mismatch_count", 0)) == 0
                and int(row.get("background_profile_mismatch_count", 0)) == 0
                for row in complete
                if row.get("experiment") == "relay_participation"
            ),
            "profile or focal-row mismatches={}".format(
                sum(
                    int(row.get("focal_profile_mismatch_count", 0))
                    + int(row.get("background_profile_mismatch_count", 0))
                    for row in complete
                    if row.get("experiment") == "relay_participation"
                )
            ),
        ),
        check(
            "finite-security-metrics",
            all(row["finite_metrics"] for row in complete),
            f"non-finite runs={sum(not row['finite_metrics'] for row in complete)}",
        ),
    ]


def markdown_report(
    suite: str,
    rows: list[dict[str, Any]],
    groups: list[dict[str, Any]],
    pairs: list[dict[str, Any]],
    checks: list[dict[str, Any]],
) -> str:
    lines = [
        f"# {suite} security report",
        "",
        f"Successful runs: {sum(row['complete'] for row in rows)} / {len(rows)}.",
        "Deterministic bounds are checked per epoch; stochastic effects are reported across paired seeds.",
        "",
        "## Acceptance",
        "",
    ]
    for item in checks:
        lines.append(f"- {'PASS' if item['passed'] else 'FAIL'} — {item['name']}: {item['detail']}")
    lines.extend(
        [
            "",
            "## Artifacts",
            "",
            f"- run-level records: `{suite}_runs.csv`",
            f"- scenario summaries: `{suite}_groups.csv` ({len(groups)} metric rows)",
            f"- paired differences: `{suite}_paired.csv` ({len(pairs)} comparisons)",
            "- fixed-path padding cases: `frozen_v1_padding_fixed_path.csv`",
            "",
            "A paired confidence interval is descriptive evidence, not a replacement for the deterministic protocol bound.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument(
        "--allow-incomplete",
        action="store_true",
        help="Write a partial report and do not fail solely because runs or seeds are missing.",
    )
    args = parser.parse_args()

    spec = load_yaml((ROOT / args.config).resolve())
    if spec.get("protocol_version") != "frozen-v1":
        parser.error("security report requires a frozen-v1 experiment config")
    runs = expand_runs(spec)
    rows = [aggregate_run(run) for run in runs]
    groups = group_runs(rows)
    pairs = paired_differences(rows)
    checks = validation(rows, len(spec.get("seeds", [0])))
    checks.append(fixed_padding_check())
    suite = str(spec["suite"])
    prefix = PROCESSED_ROOT / suite

    run_fields = list(rows[0].keys()) if rows else SCENARIO_FIELDS
    write_csv(prefix.with_name(prefix.name + "_runs.csv"), rows, run_fields)
    group_fields = SCENARIO_FIELDS + ["metric", "n", "mean", "ci95"]
    write_csv(prefix.with_name(prefix.name + "_groups.csv"), groups, group_fields)
    paired_fields = SCENARIO_FIELDS + [
        "reference_field",
        "reference_value",
        "scenario_value",
        "metric",
        "n_pairs",
        "mean_difference",
        "ci95",
        "ci95_low",
        "ci95_high",
    ]
    write_csv(prefix.with_name(prefix.name + "_paired.csv"), pairs, paired_fields)
    payload = {
        "suite": suite,
        "protocol_version": "frozen-v1",
        "expected_runs": len(rows),
        "successful_runs": sum(row["complete"] for row in rows),
        "passed": all(item["passed"] for item in checks),
        "checks": checks,
    }
    acceptance_path = prefix.with_name(prefix.name + "_acceptance.json")
    acceptance_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    report_path = prefix.with_name(prefix.name + "_report.md")
    report_path.write_text(markdown_report(suite, rows, groups, pairs, checks))

    print(f"frozen-v1 simulator security: {'PASS' if payload['passed'] else 'INCOMPLETE/FAIL'}")
    print(f"wrote {acceptance_path.relative_to(ROOT)}")
    if payload["passed"]:
        return 0
    if args.allow_incomplete:
        safety_checks = checks[2:]
        return 0 if all(item["passed"] for item in safety_checks) else 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
