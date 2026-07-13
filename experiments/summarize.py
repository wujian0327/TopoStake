#!/usr/bin/env python3
"""Summarize raw experiment outputs into processed CSVs and paper_summary.md."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from run_experiments import RAW_ROOT, ROOT, expand_runs, load_yaml


PROCESSED_ROOT = ROOT / "results" / "processed"

META_FIELDS = [
    "suite",
    "protocol_version",
    "experiment",
    "run_id",
    "protocol_label",
    "protocol",
    "seed_index",
    "seed_value",
    "node_num",
    "sybil_node_num",
    "fake_node_num",
    "unstable_node_num",
    "topology",
    "tx_rate",
    "stake_gini",
    "relay_profile",
    "adversary_stake_fraction",
    "adversary_placement",
    "eta_bonus_product",
    "padding_identities",
    "topostake_target_depth",
    "beta",
    "topostake_saturation_k",
    "topostake_score_cost_reference",
    "topostake_score_floor_kappa",
    "topostake_bonus_zeta",
    "eta",
    "bonus_cap",
    "proposer_fee_ratio",
    "attack_tx_rate_multiplier",
    "unstable_fraction",
    "offline_probability",
    "attack_mode",
    "max_tx_per_block",
    "network_delay_multiplier",
    "validator_scale_capacity_penalty",
    "topostake_scale_capacity_bonus",
    "validator_scale_latency_penalty",
    "topostake_scale_latency_reduction",
    "topostake_latency_reduction_s",
    "warmup_epochs",
    "output_dir",
]

RUN_METRICS = [
    "throughput",
    "p50_inclusion_latency_s",
    "p95_inclusion_latency_s",
    "p99_inclusion_latency_s",
    "block_success_ratio",
    "avg_path_length",
    "p95_path_length",
    "valid_path_count",
    "invalid_path_count",
    "conflicting_receipt_count",
    "active_score_epoch",
    "latest_score_epoch",
    "total_proposer_reward",
    "total_relay_reward",
    "burned_relay_fee",
    "stake_gini",
    "stake_hhi",
    "proposer_weight_gini",
    "proposer_weight_hhi",
    "adversary_real_stake_share",
    "adversary_score_share",
    "adversary_damped_score_mass",
    "adversary_proposer_weight_share",
    "score_dependent_proposer_weight_bound",
    "theoretical_proposer_weight_bound",
    "observed_adversary_proposer_share",
]

SUMMARY_FIELDS = [
    "completed_epochs",
    "generated_tx",
    "included_tx",
    "block_production_success",
    "block_production_failed",
    "adversary_fee_spent",
    "adversary_reward_income",
    "adversary_net_income",
]

GROUP_FIELDS = [
    "suite",
    "protocol_version",
    "experiment",
    "protocol_label",
    "node_num",
    "sybil_node_num",
    "fake_node_num",
    "unstable_node_num",
    "topology",
    "tx_rate",
    "stake_gini",
    "relay_profile",
    "adversary_stake_fraction",
    "adversary_placement",
    "eta_bonus_product",
    "padding_identities",
    "topostake_target_depth",
    "beta",
    "topostake_saturation_k",
    "topostake_score_cost_reference",
    "topostake_score_floor_kappa",
    "topostake_bonus_zeta",
    "eta",
    "bonus_cap",
    "proposer_fee_ratio",
    "attack_tx_rate_multiplier",
    "unstable_fraction",
    "offline_probability",
    "attack_mode",
    "max_tx_per_block",
    "network_delay_multiplier",
    "validator_scale_capacity_penalty",
    "topostake_scale_capacity_bonus",
    "validator_scale_latency_penalty",
    "topostake_scale_latency_reduction",
    "topostake_latency_reduction_s",
]


def read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def read_csv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: List[Dict[str, Any]], fieldnames: Iterable[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def mean(values: List[float]) -> float:
    return statistics.mean(values) if values else 0.0


def ci95(values: List[float]) -> float:
    if len(values) < 2:
        return 0.0
    return 1.96 * statistics.stdev(values) / math.sqrt(len(values))


def discover_meta_files(suites: Iterable[str] | None) -> List[Path]:
    suite_set = set(suites or [])
    metas = []
    for path in RAW_ROOT.glob("**/experiment_meta.json"):
        if suite_set:
            try:
                rel = path.relative_to(RAW_ROOT)
            except ValueError:
                continue
            if rel.parts[0] not in suite_set:
                continue
        metas.append(path)
    return sorted(metas)


def load_config_suites(configs: List[str]) -> List[str]:
    suites = []
    for config in configs:
        spec = load_yaml((ROOT / config).resolve())
        suites.append(spec.get("suite", Path(config).stem))
    return suites


def load_config_meta_files(
    configs: List[str],
    only: Iterable[str] | None = None,
    seed_indices: Iterable[int] | None = None,
    unstable_fractions: Iterable[float] | None = None,
) -> List[Path]:
    seed_set = set(seed_indices or [])
    unstable_fraction_set = set(unstable_fractions or [])
    meta_files = []
    for config in configs:
        spec = load_yaml((ROOT / config).resolve())
        for run in expand_runs(spec, only):
            if seed_set and int(run.get("seed_index", -1)) not in seed_set:
                continue
            if unstable_fraction_set and float(run.get("unstable_fraction", -1)) not in unstable_fraction_set:
                continue
            meta_path = Path(run["output_dir"]) / "experiment_meta.json"
            if meta_path.exists():
                meta_files.append(meta_path)
    return sorted(set(meta_files))


def enrich_rows(rows: List[Dict[str, str]], meta: Dict[str, Any], source: Path) -> List[Dict[str, Any]]:
    enriched = []
    for row in rows:
        out: Dict[str, Any] = {field: meta.get(field, "") for field in META_FIELDS}
        out.update(row)
        out["source_file"] = str(source.relative_to(ROOT))
        enriched.append(out)
    return enriched


def aggregate_run(
    meta: Dict[str, Any],
    summary: Dict[str, Any],
    epoch_rows: List[Dict[str, str]],
    runner_status: Dict[str, Any],
) -> Dict[str, Any]:
    warmup = int(float(meta.get("warmup_epochs", 0) or 0))
    usable = [row for row in epoch_rows if int(float(row.get("epoch", 0) or 0)) >= warmup]
    if not usable:
        usable = epoch_rows
    out: Dict[str, Any] = {field: meta.get(field, "") for field in META_FIELDS}
    status = runner_status.get("status", "missing")
    out["status"] = "ok" if status == "ok" and summary else status
    if status == "ok" and not summary:
        out["status"] = "missing_summary"
    if out["status"] == "ok":
        try:
            completed_epochs = int(summary.get("completed_epochs", -1))
            expected_epochs = int(meta.get("max_epochs", 0))
        except (TypeError, ValueError):
            completed_epochs = -1
            expected_epochs = 0
        if expected_epochs > 0 and completed_epochs < expected_epochs:
            out["status"] = "incomplete_epochs"
    for field in SUMMARY_FIELDS:
        out[field] = summary.get(field, "")
    for metric in RUN_METRICS:
        values = [to_float(row.get(metric)) for row in usable]
        out[f"{metric}_mean"] = mean(values)
        out[f"{metric}_ci95"] = ci95(values)
    out["epoch_metrics_source"] = str(Path(meta["output_dir"]).joinpath("epoch_metrics.csv").relative_to(ROOT))
    out["node_epoch_metrics_source"] = str(Path(meta["output_dir"]).joinpath("node_epoch_metrics.csv").relative_to(ROOT))
    out["run_config_source"] = str(Path(meta["output_dir"]).joinpath("run_config.json").relative_to(ROOT))
    out["run_summary_source"] = str(Path(meta["output_dir"]).joinpath("run_summary.json").relative_to(ROOT))
    out["runner_status_source"] = str(Path(meta["output_dir"]).joinpath("runner_status.json").relative_to(ROOT))
    return out


def aggregate_metrics(run_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[Tuple[Any, ...], List[Dict[str, Any]]] = defaultdict(list)
    for row in run_rows:
        if row.get("status") != "ok":
            continue
        key = tuple(row.get(field, "") for field in GROUP_FIELDS)
        grouped[key].append(row)

    rows = []
    for key, group in sorted(grouped.items(), key=lambda item: tuple(str(part) for part in item[0])):
        base = dict(zip(GROUP_FIELDS, key))
        for metric in [f"{name}_mean" for name in RUN_METRICS] + SUMMARY_FIELDS:
            values = [to_float(row.get(metric), math.nan) for row in group]
            values = [value for value in values if not math.isnan(value)]
            if not values:
                continue
            out = dict(base)
            out.update(
                {
                    "metric": metric,
                    "n": len(values),
                    "mean": mean(values),
                    "ci95": ci95(values),
                }
            )
            rows.append(out)
    return rows


def paper_summary(run_rows: List[Dict[str, Any]], suites: List[str]) -> str:
    lines = [
        "# Paper Experiment Summary",
        "",
        "This file is generated from raw simulator outputs. It reports available runs only and does not infer conclusions when data is missing.",
        "",
        f"Suites: {', '.join(suites) if suites else 'all discovered suites'}",
        "",
    ]
    by_experiment: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in run_rows:
        by_experiment[str(row.get("experiment", ""))].append(row)

    for experiment in sorted(by_experiment):
        rows = by_experiment[experiment]
        ok = [row for row in rows if row.get("status") == "ok"]
        lines.extend([f"## {experiment}", ""])
        lines.append(f"- successful runs: {len(ok)} / {len(rows)}")
        for field in GROUP_FIELDS:
            values = sorted({str(row.get(field, "")) for row in rows if row.get(field, "") != ""})
            if values:
                lines.append(f"- {field}: {', '.join(values)}")
        if ok:
            epoch_sources = sorted({str(row.get("epoch_metrics_source", "")) for row in ok})
            node_sources = sorted({str(row.get("node_epoch_metrics_source", "")) for row in ok})
            lines.append("- source epoch CSV files:")
            lines.extend(f"  - `{source}`" for source in epoch_sources)
            lines.append("- source node CSV files:")
            lines.extend(f"  - `{source}`" for source in node_sources)
        else:
            lines.append("- no successful runs found; no conclusions reported")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", action="append", default=[])
    parser.add_argument("--only", action="append", help="Summarize only this experiment group from the config")
    parser.add_argument("--seed-index", action="append", type=int, help="Summarize only this zero-based seed index")
    parser.add_argument("--unstable-fraction", action="append", type=float, help="Summarize only this unstable node fraction")
    parser.add_argument("--suite", action="append", default=[])
    args = parser.parse_args()

    suites = args.suite or load_config_suites(args.config)
    if args.config:
        meta_files = load_config_meta_files(args.config, args.only, args.seed_index, args.unstable_fraction)
    else:
        meta_files = discover_meta_files(suites if suites else None)
    epoch_all: List[Dict[str, Any]] = []
    node_all: List[Dict[str, Any]] = []
    run_rows: List[Dict[str, Any]] = []

    for meta_path in meta_files:
        meta = read_json(meta_path)
        output_dir = Path(meta["output_dir"])
        summary = read_json(output_dir / "run_summary.json")
        runner_status = read_json(output_dir / "runner_status.json")
        epoch_rows = read_csv(output_dir / "epoch_metrics.csv")
        node_rows = read_csv(output_dir / "node_epoch_metrics.csv")
        epoch_all.extend(enrich_rows(epoch_rows, meta, output_dir / "epoch_metrics.csv"))
        node_all.extend(enrich_rows(node_rows, meta, output_dir / "node_epoch_metrics.csv"))
        run_rows.append(aggregate_run(meta, summary, epoch_rows, runner_status))

    PROCESSED_ROOT.mkdir(parents=True, exist_ok=True)
    run_fields = (
        META_FIELDS
        + ["status"]
        + SUMMARY_FIELDS
        + [f"{metric}_mean" for metric in RUN_METRICS]
        + [f"{metric}_ci95" for metric in RUN_METRICS]
        + [
            "epoch_metrics_source",
            "node_epoch_metrics_source",
            "run_config_source",
            "run_summary_source",
            "runner_status_source",
        ]
    )
    write_csv(PROCESSED_ROOT / "runs.csv", run_rows, run_fields)
    if epoch_all:
        write_csv(PROCESSED_ROOT / "epoch_metrics_all.csv", epoch_all, list(epoch_all[0].keys()))
    else:
        write_csv(PROCESSED_ROOT / "epoch_metrics_all.csv", [], META_FIELDS)
    if node_all:
        write_csv(PROCESSED_ROOT / "node_epoch_metrics_all.csv", node_all, list(node_all[0].keys()))
    else:
        write_csv(PROCESSED_ROOT / "node_epoch_metrics_all.csv", [], META_FIELDS)
    aggregate_rows = aggregate_metrics(run_rows)
    write_csv(PROCESSED_ROOT / "aggregate_metrics.csv", aggregate_rows, GROUP_FIELDS + ["metric", "n", "mean", "ci95"])
    (PROCESSED_ROOT / "paper_summary.md").write_text(paper_summary(run_rows, suites))

    ok = sum(1 for row in run_rows if row.get("status") == "ok")
    print(f"Summarized {len(run_rows)} runs ({ok} successful)")
    print(f"Wrote {PROCESSED_ROOT / 'paper_summary.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
