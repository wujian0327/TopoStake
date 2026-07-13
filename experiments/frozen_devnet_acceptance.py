#!/usr/bin/env python3
"""Validate frozen-v1 configuration and Kurtosis devnet artifacts.

The static checks are dependency-free and validate the shared protocol profile
against the golden vectors. Artifact checks consume the ``summary.json``
written by ``topostake_devnet_runner.py`` and fail closed on missing evidence or
Prometheus data for modes that require them.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATH = ROOT / "experiments" / "configs" / "protocol_frozen_v1.yaml"
GOLDEN_PATH = ROOT / "experiments" / "golden" / "frozen_v1_vectors.yaml"
DEFAULT_REPORT = ROOT / "results" / "processed" / "frozen_v1_devnet_acceptance.json"
MODES = ("baseline", "pathobs", "fee_only", "bonus_only", "topostake")


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def close(actual: float, expected: float, tolerance: float = 1e-12) -> bool:
    return math.isclose(actual, expected, rel_tol=tolerance, abs_tol=tolerance)


def check(name: str, passed: bool, detail: str) -> Check:
    return Check(name=name, passed=bool(passed), detail=detail)


def static_checks() -> list[Check]:
    profile = load_json(PROFILE_PATH)
    golden = load_json(GOLDEN_PATH)
    fixed = profile["devnet_fixed_point"]
    scale = int(fixed["scale"])
    checks = [
        check("protocol-version", profile.get("protocol_version") == "frozen-v1", str(profile.get("protocol_version"))),
        check(
            "activation-delay-consistency",
            int(profile["score_activation_delay_epochs"]) == int(fixed["score_activation_delay_epochs"]),
            f"profile={profile['score_activation_delay_epochs']}, devnet={fixed['score_activation_delay_epochs']}",
        ),
        check(
            "path-cap-consistency",
            int(profile["max_path_hops"]) == int(fixed["max_path_evidence_len"]),
            f"profile={profile['max_path_hops']}, devnet={fixed['max_path_evidence_len']}",
        ),
        check(
            "work-cap-consistency",
            int(profile["evidence_work_limit"]) == int(fixed["evidence_work_limit"]),
            f"profile={profile['evidence_work_limit']}, devnet={fixed['evidence_work_limit']}",
        ),
        check("devnet-seconds-per-slot", int(fixed["seconds_per_slot"]) > 0, str(fixed["seconds_per_slot"])),
        check("devnet-slots-per-epoch", int(fixed["slots_per_epoch"]) > 0, str(fixed["slots_per_epoch"])),
        check(
            "kappa-fixed-point",
            int(fixed["score_floor_kappa_scaled"]) == round(float(profile["score_floor_kappa"]) * scale),
            str(fixed["score_floor_kappa_scaled"]),
        ),
        check(
            "zeta-fixed-point",
            int(fixed["bonus_zeta_scaled"]) == round(float(profile["bonus_zeta"]) * scale),
            str(fixed["bonus_zeta_scaled"]),
        ),
    ]

    depth = float(profile["target_depth"])
    r = depth / (2.0 * depth + 1.0)
    lam = (2.0 * depth + 1.0) / (3.0 * depth + 1.0)
    checks.append(check("padding-safe-identity", close(lam * (1.0 + r), 1.0), f"lambda*(1+r)={lam * (1+r):.16f}"))

    for index, vector in enumerate(golden["credit_weights"]):
        reference = float(vector["reference_cost"])
        actual = 0.0 if reference <= 0 else min(1.0, float(vector["irrecoverable_cost"]) / reference)
        expected = float(vector["expected"])
        checks.append(check(f"credit-weight-{index}", close(actual, expected), f"actual={actual}, expected={expected}"))

    for index, vector in enumerate(golden["bonuses"]):
        x = float(vector["score_to_stake"])
        cap = float(vector["bonus_cap"])
        zeta = float(vector["zeta"])
        actual = 0.0 if zeta + x <= 0 else cap * x / (zeta + x)
        expected = float(vector["expected"])
        checks.append(check(f"concave-bonus-{index}", close(actual, expected), f"actual={actual}, expected={expected}"))

    damped = golden["damped_score"]
    denominator = float(damped["kappa"]) + sum(float(value) for value in damped["scores"])
    actual_damped = [float(value) / denominator for value in damped["scores"]]
    checks.append(
        check(
            "damped-score-vector",
            all(close(actual, float(expected)) for actual, expected in zip(actual_damped, damped["expected"])),
            f"actual={actual_damped}, expected={damped['expected']}",
        )
    )

    proposer = golden["proposer_weight"]
    weights = []
    for stake, damped_score in zip(proposer["stakes"], proposer["damped_scores"]):
        x = float(damped_score) / float(stake)
        bonus = float(proposer["bonus_cap"]) * x / (float(proposer["zeta"]) + x)
        weights.append(float(stake) * (1.0 + float(proposer["eta"]) * bonus))
    normalized = [value / sum(weights) for value in weights]
    checks.extend(
        [
            check(
                "proposer-weight-vector",
                all(close(actual, float(expected)) for actual, expected in zip(weights, proposer["expected_unnormalized"])),
                f"actual={weights}",
            ),
            check(
                "proposer-share-vector",
                all(close(actual, float(expected)) for actual, expected in zip(normalized, proposer["expected_normalized"])),
                f"actual={normalized}",
            ),
        ]
    )
    return checks


def metric_samples(summary: dict[str, Any], name: str) -> tuple[list[dict[str, Any]], str | None]:
    value = summary.get("prometheus", {}).get(name, [])
    if isinstance(value, dict):
        return [], str(value.get("error", "metric query returned an object"))
    if not isinstance(value, list):
        return [], "metric query did not return a list"
    return [item for item in value if isinstance(item, dict)], None


def sample_value(sample: dict[str, Any]) -> float:
    return float(sample.get("value", 0.0))


def metric_sum(summary: dict[str, Any], name: str) -> float:
    samples, _ = metric_samples(summary, name)
    return sum(sample_value(sample) for sample in samples)


def metric_max(summary: dict[str, Any], name: str) -> float:
    samples, _ = metric_samples(summary, name)
    return max((sample_value(sample) for sample in samples), default=0.0)


def frozen_weight_checks(summary: dict[str, Any]) -> list[Check]:
    samples, error = metric_samples(summary, "topostake_proposer_weight_scaled")
    if error:
        return [check("proposer-weight-metric", False, error)]
    within_instance: dict[tuple[str, str, str], set[float]] = {}
    across_instances: dict[tuple[str, str, str], set[float]] = {}
    for sample in samples:
        labels = sample.get("metric", {})
        instance = str(labels.get("instance", ""))
        proposer_epoch = str(labels.get("proposer_epoch", ""))
        validator = str(labels.get("validator_index", ""))
        slot = str(labels.get("slot", ""))
        within_instance.setdefault((instance, proposer_epoch, validator), set()).add(sample_value(sample))
        across_instances.setdefault((proposer_epoch, slot, validator), set()).add(sample_value(sample))
    intra_unstable = {key: values for key, values in within_instance.items() if len(values) > 1}
    cross_unstable = {key: values for key, values in across_instances.items() if len(values) > 1}

    selected, selected_error = metric_samples(summary, "topostake_selected_proposer")
    selected_by_slot: dict[tuple[str, str], set[str]] = {}
    for sample in selected:
        if sample_value(sample) != 1.0:
            continue
        labels = sample.get("metric", {})
        key = (str(labels.get("proposer_epoch", "")), str(labels.get("slot", "")))
        selected_by_slot.setdefault(key, set()).add(str(labels.get("validator_index", "")))
    proposer_divergence = {key: values for key, values in selected_by_slot.items() if len(values) > 1}
    return [
        check("proposer-weight-metric", bool(samples), f"samples={len(samples)}"),
        check(
            "epoch-weight-snapshot-frozen",
            not intra_unstable,
            f"unstable_groups={len(intra_unstable)}, examples={list(intra_unstable.items())[:2]}",
        ),
        check(
            "cross-node-weight-consistency",
            not cross_unstable,
            f"unstable_groups={len(cross_unstable)}, examples={list(cross_unstable.items())[:2]}",
        ),
        check("selected-proposer-metric", selected_error is None and bool(selected), f"samples={len(selected)}, error={selected_error}"),
        check(
            "cross-node-proposer-consistency",
            not proposer_divergence,
            f"divergent_slots={len(proposer_divergence)}, examples={list(proposer_divergence.items())[:2]}",
        ),
    ]


def activation_checks(summary: dict[str, Any], delay: int) -> list[Check]:
    samples, error = metric_samples(summary, "topostake_selection_score_epoch")
    if error:
        return [check("activation-metric", False, error)]
    violations = []
    for sample in samples:
        labels = sample.get("metric", {})
        try:
            proposer_epoch = int(labels["proposer_epoch"])
            score_epoch = int(float(sample["value"]))
        except (KeyError, TypeError, ValueError):
            violations.append(labels)
            continue
        if score_epoch > proposer_epoch - delay:
            violations.append({"proposer_epoch": proposer_epoch, "score_epoch": score_epoch})
    return [
        check("activation-metric", bool(samples), f"samples={len(samples)}"),
        check("activation-delay", not violations, f"violations={violations[:3]}"),
    ]


def artifact_checks(summary: dict[str, Any], mode: str) -> list[Check]:
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}")
    profile = load_json(PROFILE_PATH)
    fixed = profile["devnet_fixed_point"]
    blocks = summary.get("blocks", {})
    records = blocks.get("records", []) if isinstance(blocks, dict) else []
    before = summary.get("beacon_before_measurement", summary.get("beacon_before", {}))
    after = summary.get("beacon_after", summary.get("beacon", {}))
    finalized_before = int(before.get("finalized_epoch", 0))
    finalized_after = int(after.get("finalized_epoch", 0))
    max_path = int(fixed["max_path_evidence_len"])
    work_limit = int(fixed["evidence_work_limit"])
    slots_per_epoch = int(fixed["slots_per_epoch"])
    _, fee_metric_error = metric_samples(summary, "topostake_fee_conservation_violation")

    checks = [
        check("finality-progress", finalized_after > finalized_before, f"before={finalized_before}, after={finalized_after}"),
        check("peer-graph", summary.get("peer_graph", {}).get("matches_target") is True, str(summary.get("peer_graph", {}).get("matches_target"))),
        check("fee-conservation-metric-query", fee_metric_error is None, str(fee_metric_error)),
        check("fee-conservation", metric_sum(summary, "topostake_fee_conservation_violation") == 0.0, str(metric_sum(summary, "topostake_fee_conservation_violation"))),
    ]

    if mode == "baseline":
        checks.extend(
            [
                check("baseline-no-evidence", len(records) == 0, f"records={len(records)}"),
                check("baseline-no-score", metric_max(summary, "topostake_epoch_score_scaled") == 0.0, str(metric_max(summary, "topostake_epoch_score_scaled"))),
            ]
        )
        return checks

    geth_statuses = summary.get("geth_topostake_status", [])
    expected_relay_epoch = int(after.get("head_slot", 0)) // slots_per_epoch
    checks.extend(
        [
            check("geth-status-present", bool(geth_statuses), f"nodes={len(geth_statuses)}"),
            check(
                "geth-dynamic-epoch-enabled",
                bool(geth_statuses) and all(item.get("dynamic_relay_epoch") is True for item in geth_statuses),
                str([item.get("dynamic_relay_epoch") for item in geth_statuses]),
            ),
            check(
                "geth-epoch-timing",
                bool(geth_statuses)
                and all(
                    int(item.get("seconds_per_slot", 0)) == int(fixed["seconds_per_slot"])
                    and int(item.get("slots_per_epoch", 0)) == slots_per_epoch
                    for item in geth_statuses
                ),
                str([(item.get("seconds_per_slot"), item.get("slots_per_epoch")) for item in geth_statuses]),
            ),
            check(
                "geth-relay-epoch-current",
                bool(geth_statuses)
                and all(int(item.get("relay_epoch", -1)) == expected_relay_epoch for item in geth_statuses),
                f"expected={expected_relay_epoch}, observed={[item.get('relay_epoch') for item in geth_statuses]}",
            ),
        ]
    )

    stale = [
        record
        for record in records
        if int(record.get("epoch", -1)) < int(record.get("slot", 0)) // slots_per_epoch
    ]
    future = [
        record
        for record in records
        if int(record.get("epoch", -1)) > int(record.get("slot", 0)) // slots_per_epoch
    ]
    oversized = [record for record in records if int(record.get("path_len", len(record.get("path", [])))) > max_path]
    missing_cost = [record for record in records if "irrecoverable_cost_wei" not in record]
    positive_cost_records = [record for record in records if int(record.get("irrecoverable_cost_wei", 0)) > 0]
    work_by_slot: dict[int, int] = {}
    for record in records:
        slot = int(record.get("slot", 0))
        work_by_slot[slot] = work_by_slot.get(slot, 0) + int(record.get("path_len", len(record.get("path", []))))
    excess_work = {slot: work for slot, work in work_by_slot.items() if work > work_limit}
    checks.extend(
        [
            check("evidence-present", bool(records), f"records={len(records)}"),
            check("evidence-epoch-not-future", not future, f"future={len(future)}"),
            check(
                "stale-evidence-no-credit",
                not stale
                or metric_sum(summary, "topostake_evidence_epoch_invalid_paths") > 0.0,
                (
                    f"stale={len(stale)}, "
                    "invalid_metric="
                    f"{metric_sum(summary, 'topostake_evidence_epoch_invalid_paths')}"
                ),
            ),
            check("path-length-cap", not oversized, f"oversized={len(oversized)}"),
            check("evidence-work-cap", not excess_work, f"excess_slots={excess_work}"),
            check("irrecoverable-cost-carried", not missing_cost, f"missing={len(missing_cost)}"),
            check("irrecoverable-cost-positive", bool(positive_cost_records), f"positive={len(positive_cost_records)}"),
            check("valid-path-metric", metric_sum(summary, "topostake_evidence_epoch_valid_paths") > 0.0, str(metric_sum(summary, "topostake_evidence_epoch_valid_paths"))),
        ]
    )

    if mode == "pathobs":
        return checks

    checks.extend(
        [
            check("score-positive", metric_max(summary, "topostake_epoch_score_scaled") > 0.0, str(metric_max(summary, "topostake_epoch_score_scaled"))),
            check("proposer-score-positive", metric_max(summary, "topostake_proposer_score_scaled") > 0.0, str(metric_max(summary, "topostake_proposer_score_scaled"))),
        ]
    )
    checks.extend(activation_checks(summary, int(fixed["score_activation_delay_epochs"])))
    checks.extend(frozen_weight_checks(summary))

    observed_weight = metric_max(summary, "topostake_proposer_weight_scaled")
    if mode == "fee_only":
        checks.append(
            check(
                "fee-only-disables-proposer-bonus",
                observed_weight <= 32_000_000_000 * int(fixed["scale"]),
                f"observed={observed_weight:.0f}",
            )
        )
    if mode in ("fee_only", "topostake"):
        checks.append(
            check(
                "fee-settlement-positive",
                metric_max(summary, "topostake_fee_settlement_amount_wei") > 0.0,
                str(metric_max(summary, "topostake_fee_settlement_amount_wei")),
            )
        )

    max_weight = 32_000_000_000 * int(fixed["scale"]) * (1.0 + float(profile["eta"]) * float(profile["bonus_cap"]))
    checks.append(check("proposer-weight-cap", observed_weight <= max_weight, f"observed={observed_weight:.0f}, cap={max_weight:.0f}"))
    return checks


def report(checks: Iterable[Check], *, mode: str, artifact: str | None) -> dict[str, Any]:
    items = list(checks)
    return {
        "protocol_version": "frozen-v1",
        "mode": mode,
        "artifact": artifact,
        "passed": all(item.passed for item in items),
        "checks": [asdict(item) for item in items],
    }


def print_report(payload: dict[str, Any]) -> None:
    for item in payload["checks"]:
        mark = "PASS" if item["passed"] else "FAIL"
        print(f"[{mark}] {item['name']}: {item['detail']}")
    print(f"frozen-v1 acceptance: {'PASS' if payload['passed'] else 'FAIL'}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, help="Devnet summary.json to validate")
    parser.add_argument("--mode", choices=MODES, default="topostake")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--no-static", action="store_true", help="Skip shared profile/golden checks")
    args = parser.parse_args()

    checks = [] if args.no_static else static_checks()
    if args.artifact:
        checks.extend(artifact_checks(load_json(args.artifact), args.mode))
    payload = report(checks, mode=args.mode if args.artifact else "static", artifact=str(args.artifact) if args.artifact else None)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print_report(payload)
    print(f"wrote {args.report}")
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
