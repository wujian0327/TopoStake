#!/usr/bin/env python3
"""Audit and summarize the paired long-term reward-reinvestment experiment."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from run_experiments import PROCESSED_ROOT, RAW_ROOT, ROOT, load_yaml, read_json


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
PROTOCOLS = ("pos", "topostake_eta0", "topostake")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def gini(values: Iterable[float]) -> float:
    ordered = sorted(max(0.0, float(value)) for value in values)
    if not ordered:
        return 0.0
    total = sum(ordered)
    if total <= 0.0:
        return 0.0
    count = len(ordered)
    weighted = sum((index + 1) * value for index, value in enumerate(ordered))
    return (2.0 * weighted) / (count * total) - (count + 1.0) / count


def mean_ci(values: Iterable[float]) -> tuple[float, float, int]:
    materialized = list(values)
    if not materialized:
        return math.nan, math.nan, 0
    if len(materialized) == 1:
        return materialized[0], 0.0, 1
    count = len(materialized)
    ci = T95.get(count, 1.96) * statistics.stdev(materialized) / math.sqrt(count)
    return statistics.fmean(materialized), ci, count


def stake_gini_trajectory(
    node_rows: Iterable[dict[str, str]], reinvestment_rate: float
) -> tuple[list[dict[str, float]], float]:
    by_epoch: dict[int, list[dict[str, str]]] = defaultdict(list)
    for row in node_rows:
        by_epoch[int(row["epoch"])].append(row)
    if not by_epoch:
        return [], math.inf

    points: list[dict[str, float]] = []
    continuity_error = 0.0
    previous_post: dict[str, float] | None = None
    for epoch in sorted(by_epoch):
        rows = by_epoch[epoch]
        pre = {row["validator_id"]: float(row["economic_stake"]) for row in rows}
        if previous_post is not None:
            shared = set(pre) & set(previous_post)
            continuity_error = max(
                continuity_error,
                max((abs(pre[key] - previous_post[key]) for key in shared), default=0.0),
            )
        if not points:
            points.append({"epoch": 0, "stake_gini": gini(pre.values())})
        post = {
            row["validator_id"]: float(row["economic_stake"])
            + reinvestment_rate
            * (float(row["proposer_reward"]) + float(row["relay_reward"]))
            for row in rows
        }
        points.append({"epoch": epoch + 1, "stake_gini": gini(post.values())})
        previous_post = post
    return points, continuity_error


def summarize_run(run_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    meta = read_json(run_dir / "experiment_meta.json")
    summary = read_json(run_dir / "run_summary.json")
    rate = float(meta["reward_reinvestment_rate"])
    trajectory, continuity_error = stake_gini_trajectory(
        read_csv(run_dir / "node_epoch_metrics.csv"), rate
    )
    completed = int(summary.get("completed_epochs", -1)) >= int(meta["max_epochs"])
    common = {
        "run_id": meta["run_id"],
        "protocol_label": meta["protocol_label"],
        "seed_index": int(meta["seed_index"]),
        "seed_value": int(meta["seed_value"]),
        "reward_reinvestment_rate": rate,
    }
    rows = [{**common, **point} for point in trajectory]
    audit = {
        **common,
        "completed": completed,
        "expected_points": int(meta["max_epochs"]) + 1,
        "observed_points": len(trajectory),
        "continuity_error": continuity_error,
        "initial_gini": trajectory[0]["stake_gini"] if trajectory else math.nan,
        "final_gini": trajectory[-1]["stake_gini"] if trajectory else math.nan,
    }
    return rows, audit


def grouped_rows(runs: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, int], list[float]] = defaultdict(list)
    for row in runs:
        grouped[(str(row["protocol_label"]), int(row["epoch"]))].append(
            float(row["stake_gini"])
        )
    output = []
    for (protocol, epoch), values in sorted(grouped.items()):
        mean, ci, count = mean_ci(values)
        output.append(
            {
                "protocol_label": protocol,
                "epoch": epoch,
                "n": count,
                "mean": mean,
                "ci95": ci,
                "ci95_low": mean - ci,
                "ci95_high": mean + ci,
            }
        )
    return output


def endpoint_pairs(runs: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    by_seed: dict[int, dict[str, dict[str, Any]]] = defaultdict(dict)
    max_epoch: dict[tuple[int, str], int] = {}
    for row in runs:
        seed = int(row["seed_index"])
        protocol = str(row["protocol_label"])
        key = (seed, protocol)
        epoch = int(row["epoch"])
        if epoch >= max_epoch.get(key, -1):
            max_epoch[key] = epoch
            by_seed[seed][protocol] = row
    pairs = []
    for seed, variants in sorted(by_seed.items()):
        if not all(protocol in variants for protocol in PROTOCOLS):
            continue
        pos = float(variants["pos"]["stake_gini"])
        fee = float(variants["topostake_eta0"]["stake_gini"])
        full = float(variants["topostake"]["stake_gini"])
        pairs.append(
            {
                "seed_index": seed,
                "epoch": int(variants["topostake"]["epoch"]),
                "pos_gini": pos,
                "fee_only_gini": fee,
                "full_gini": full,
                "fee_only_minus_pos": fee - pos,
                "full_minus_pos": full - pos,
                "full_minus_fee_only": full - fee,
            }
        )
    return pairs


def endpoint_group_rows(pairs: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    materialized = list(pairs)
    rows = []
    for metric in (
        "pos_gini",
        "fee_only_gini",
        "full_gini",
        "fee_only_minus_pos",
        "full_minus_pos",
        "full_minus_fee_only",
    ):
        mean, ci, count = mean_ci(float(row[metric]) for row in materialized)
        rows.append(
            {
                "metric": metric,
                "n": count,
                "mean": mean,
                "ci95": ci,
                "ci95_low": mean - ci,
                "ci95_high": mean + ci,
            }
        )
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else []
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        default="experiments/configs/frozen_v1_reinvestment_gini_main.yaml",
    )
    parser.add_argument("--allow-incomplete", action="store_true")
    args = parser.parse_args()

    spec = load_yaml((ROOT / args.config).resolve())
    run_root = RAW_ROOT / str(spec["suite"]) / "reinvestment_gini"
    all_rows: list[dict[str, Any]] = []
    audits: list[dict[str, Any]] = []
    for meta_path in sorted(run_root.glob("*/experiment_meta.json")):
        rows, audit = summarize_run(meta_path.parent)
        all_rows.extend(rows)
        audits.append(audit)

    expected_runs = len(spec.get("seeds", [])) * len(PROTOCOLS)
    pairs = endpoint_pairs(all_rows)
    complete = (
        len(audits) == expected_runs
        and len(pairs) == len(spec.get("seeds", []))
        and all(audit["completed"] for audit in audits)
        and all(audit["observed_points"] == audit["expected_points"] for audit in audits)
        and all(audit["continuity_error"] <= 2e-6 for audit in audits)
    )
    if not complete and not args.allow_incomplete:
        raise SystemExit(
            f"incomplete reinvestment matrix: observed {len(audits)}/{expected_runs} runs"
        )

    output = PROCESSED_ROOT / str(spec["suite"])
    write_csv(output / "reinvestment_gini_runs.csv", all_rows)
    write_csv(output / "reinvestment_gini_groups.csv", grouped_rows(all_rows))
    write_csv(output / "reinvestment_gini_endpoints.csv", pairs)
    write_csv(
        output / "reinvestment_gini_endpoint_groups.csv", endpoint_group_rows(pairs)
    )
    write_csv(output / "reinvestment_gini_audit.csv", audits)
    (output / "reinvestment_gini_acceptance.json").write_text(
        json.dumps(
            {
                "complete": complete,
                "expected_runs": expected_runs,
                "observed_runs": len(audits),
                "protocols": list(PROTOCOLS),
                "reward_reinvestment_rate": spec["defaults"]["reward_reinvestment_rate"],
                "max_epochs": spec["defaults"]["max_epochs"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    print(f"wrote reinvestment report to {output.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
