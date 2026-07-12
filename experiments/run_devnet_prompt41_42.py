#!/usr/bin/env python3
"""Run Prompt 41/42 devnet suites and write a compact metrics table."""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = Path("/tmp/ethereum-package")
OUTPUT_ROOT = ROOT / "results" / "raw" / "devnet_prompt41_42"
PROCESSED = ROOT / "results" / "processed" / "devnet_prompt41_42_summary.csv"
ARGS_DIR = ROOT / "results" / "raw" / "devnet_args"
SECONDS_PER_SLOT = 3
SLOTS_PER_EPOCH = 8
MODES = ("baseline", "pathobs", "topostake")
MODE_LABELS = {
    "baseline": "PoS-Beacon",
    "pathobs": "PoS+PathObs",
    "topostake": "TopoStake",
}

MEASUREMENT_EPOCHS_BY_PROMPT = {
    "prompt41": 5,
    "prompt42": 5,
    "prompt43": 5,
    "prompt44": 5,
}

WARMUP_EPOCHS_BY_PROMPT = {
    "prompt41": {
        "baseline": 3,
        "pathobs": 3,
        "topostake": 5,
    },
    "prompt42": {
        "baseline": 3,
        "pathobs": 3,
        "topostake": 3,
    },
}


@dataclass(frozen=True)
class RunSpec:
    prompt: str
    figure: str
    mode: str
    topology: str
    nodes: int
    offered_tx_per_slot: int
    suite_order: int
    degree: float = 2.0
    ba_m: int = 2
    seed: int = 0
    offered_tps: int | None = None

    @property
    def run_id(self) -> str:
        load_label = (
            f"tps{self.offered_tps}"
            if self.offered_tps is not None
            else f"txslot{self.offered_tx_per_slot}"
        )
        return (
            f"{self.prompt}_{self.figure}_{self.mode}_"
            f"{self.topology}_n{self.nodes}_{load_label}_seed{self.seed}"
        )

    @property
    def enclave(self) -> str:
        safe = self.run_id.replace("_", "-")
        return f"ts-{safe}"[:58]

    @property
    def tx_count(self) -> int:
        epochs = MEASUREMENT_EPOCHS_BY_PROMPT.get(self.prompt, 1)
        return self.offered_tx_per_slot * SLOTS_PER_EPOCH * epochs

    @property
    def warmup_tx_count(self) -> int:
        epochs = self.warmup_epochs
        return self.offered_tx_per_slot * SLOTS_PER_EPOCH * epochs

    @property
    def warmup_epochs(self) -> int:
        prompt_value = WARMUP_EPOCHS_BY_PROMPT.get(self.prompt, 5)
        if isinstance(prompt_value, dict):
            return int(prompt_value.get(self.mode, 5))
        return int(prompt_value)

    @property
    def tx_interval_seconds(self) -> float:
        return SECONDS_PER_SLOT / float(self.offered_tx_per_slot)

    @property
    def offered_tps_value(self) -> float:
        if self.offered_tps is not None:
            return float(self.offered_tps)
        return float(self.offered_tx_per_slot) / float(SECONDS_PER_SLOT)

    @property
    def measurement_window_seconds(self) -> int:
        epochs = MEASUREMENT_EPOCHS_BY_PROMPT.get(self.prompt, 1)
        return SECONDS_PER_SLOT * SLOTS_PER_EPOCH * epochs


def command_env() -> dict[str, str]:
    env = dict(os.environ)
    env["XDG_DATA_HOME"] = "/tmp/kurtosis-data"
    env["NO_PROXY"] = "127.0.0.1,localhost"
    env["no_proxy"] = "127.0.0.1,localhost"
    return env


def log(message: str) -> None:
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}", flush=True)


def run_cmd(cmd: list[str], *, cwd: Path = ROOT, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess[str]:
    log("$ " + " ".join(cmd))
    return subprocess.run(
        cmd,
        cwd=cwd,
        env=command_env(),
        check=check,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
    )


def specs_for_prompt41() -> list[RunSpec]:
    specs: list[RunSpec] = []
    order = 0
    for topology in ("linear", "er", "ba"):
        for mode in MODES:
            specs.append(
                RunSpec(
                    prompt="prompt41",
                    figure="topology",
                    mode=mode,
                    topology=topology,
                    nodes=10,
                    offered_tx_per_slot=32,
                    suite_order=order,
                )
            )
            order += 1
    return specs


def specs_for_prompt42() -> list[RunSpec]:
    specs: list[RunSpec] = []
    order = 1000
    for load in (32, 64, 128, 160):
        for mode in ("baseline", "topostake"):
            specs.append(
                RunSpec(
                    prompt="prompt42",
                    figure="load",
                    mode=mode,
                    topology="ba",
                    nodes=8,
                    offered_tx_per_slot=load,
                    suite_order=order,
                )
            )
            order += 1
    for nodes in (6, 9, 12, 16):
        for mode in ("pathobs", "topostake"):
            specs.append(
                RunSpec(
                    prompt="prompt42",
                    figure="nodes",
                    mode=mode,
                    topology="ba",
                    nodes=nodes,
                    offered_tx_per_slot=32,
                    suite_order=order,
                )
            )
            order += 1
    return specs


def specs_for_prompt43() -> list[RunSpec]:
    specs: list[RunSpec] = []
    order = 2000
    for topology in ("er", "ba"):
        for mode in ("pathobs", "topostake"):
            specs.append(
                RunSpec(
                    prompt="prompt43",
                    figure="path_length_16node",
                    mode=mode,
                    topology=topology,
                    nodes=16,
                    offered_tx_per_slot=32,
                    suite_order=order,
                )
            )
            order += 1
    return specs


def specs_for_prompt44() -> list[RunSpec]:
    specs: list[RunSpec] = []
    order = 3000
    for topology in ("linear", "er", "ba"):
        for mode in MODES:
            specs.append(
                RunSpec(
                    prompt="prompt44",
                    figure="topology_16node",
                    mode=mode,
                    topology=topology,
                    nodes=16,
                    offered_tx_per_slot=32,
                    suite_order=order,
                )
            )
            order += 1
    return specs


def selected_specs(suite: str) -> list[RunSpec]:
    if suite == "prompt41":
        return specs_for_prompt41()
    if suite == "prompt42":
        return specs_for_prompt42()
    if suite == "prompt43":
        return specs_for_prompt43()
    if suite == "prompt44":
        return specs_for_prompt44()
    return specs_for_prompt41() + specs_for_prompt42() + specs_for_prompt43() + specs_for_prompt44()


def registry_paths(nodes: int) -> tuple[Path, Path]:
    return (
        ROOT / "results" / "processed" / f"topostake_relay_key_registry_{nodes}.json",
        ROOT / "results" / "raw" / f"topostake_relay_keys_private_{nodes}.json",
    )


def ensure_registry(nodes: int) -> tuple[Path, Path]:
    public, private = registry_paths(nodes)
    if public.exists() and private.exists():
        return public, private
    log(f"generate TopoStake relay registry for {nodes} nodes")
    run_cmd(
        [
            "cargo",
            "run",
            "--bin",
            "topostake_relay_registry",
            "--",
            "--count",
            str(nodes),
            "--public-out",
            str(public),
            "--private-out",
            str(private),
        ]
    )
    return public, private


def args_file_for(spec: RunSpec) -> Path:
    return ARGS_DIR / f"{spec.run_id}.yaml"


def ensure_args_file(spec: RunSpec) -> Path:
    out = args_file_for(spec)
    public, private = ensure_registry(spec.nodes)
    maxpeers = max(8, spec.nodes)
    cmd = [
        sys.executable,
        "scripts/topostake_devnet_args.py",
        "--mode",
        spec.mode,
        "--count",
        str(spec.nodes),
        "--validator-count",
        "1",
        "--maxpeers",
        str(maxpeers),
        "--label",
        spec.run_id,
        "--public-registry",
        str(public),
        "--private-registry",
        str(private),
        "--out",
        str(out),
    ]
    if os.environ.get("TOPOSTAKE_DISABLE_FEE_SETTLEMENT") == "1":
        cmd.append("--disable-fee-settlement")
    run_cmd(cmd)
    return out


def remove_enclave(enclave: str) -> None:
    run_cmd(["kurtosis", "enclave", "rm", "-f", enclave], check=False)


def start_devnet(spec: RunSpec) -> None:
    if not PACKAGE.exists():
        raise FileNotFoundError(f"missing local Kurtosis package: {PACKAGE}")
    args_file = ensure_args_file(spec)
    remove_enclave(spec.enclave)
    run_cmd(["kurtosis", "run", "--enclave", spec.enclave, str(PACKAGE), "--args-file", str(args_file)])


def run_workload(spec: RunSpec) -> None:
    receipt_timeout = 1200 if spec.offered_tx_per_slot <= 180 else 1800
    finality_timeout = 1200 if spec.offered_tx_per_slot <= 180 else 1800
    run_cmd(
        [
            sys.executable,
            "experiments/topostake_devnet_runner.py",
            "run",
            "--enclave",
            spec.enclave,
            "--run-id",
            spec.run_id,
            "--output-root",
            str(OUTPUT_ROOT),
            "--n",
            str(spec.nodes),
            "--topology",
            spec.topology,
            "--degree",
            str(spec.degree),
            "--ba-m",
            str(spec.ba_m),
            "--seed",
            str(spec.seed),
            "--tx-count",
            str(spec.tx_count),
            "--warmup-tx-count",
            str(spec.warmup_tx_count),
            "--tx-interval-seconds",
            f"{spec.tx_interval_seconds:.12f}",
            "--origin-mode",
            "round_robin",
            "--sender-count",
            "0",
            "--send-concurrency",
            "0",
            "--receipt-concurrency",
            "0",
            "--receipt-timeout",
            str(receipt_timeout),
            "--wait-receipts-after-send",
            "--seconds-per-slot",
            str(SECONDS_PER_SLOT),
            "--warmup-finality-epochs",
            str(spec.warmup_epochs),
            "--wait-finality",
            "--wait-finality-epochs",
            "1",
            "--finality-timeout-seconds",
            str(finality_timeout),
            "--pre-scan-slots",
            "4",
        ]
    )


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (pct / 100.0) * (len(ordered) - 1)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    frac = rank - low
    return ordered[low] * (1.0 - frac) + ordered[high] * frac


def prometheus_sum(prometheus: Any, metric: str) -> float:
    values = prometheus.get(metric)
    if not isinstance(values, list):
        return 0.0
    total = 0.0
    for item in values:
        try:
            total += float(item.get("value", 0))
        except (TypeError, ValueError):
            pass
    return total


def normalize_tx_hash(value: Any) -> str | None:
    if not value:
        return None
    text = str(value).lower()
    if text.startswith("0x"):
        text = text[2:]
    return text


def summarize(spec: RunSpec, status: str = "ok", error: str = "") -> dict[str, Any]:
    summary_path = OUTPUT_ROOT / spec.run_id / "summary.json"
    row: dict[str, Any] = {
        "prompt": spec.prompt,
        "figure": spec.figure,
        "mode": spec.mode,
        "mode_label": MODE_LABELS[spec.mode],
        "topology": spec.topology,
        "nodes": spec.nodes,
        "offered_tps": spec.offered_tps_value,
        "offered_tx_per_slot": spec.offered_tx_per_slot,
        "tx_count": spec.tx_count,
        "warmup_tx_count": spec.warmup_tx_count,
        "seed": spec.seed,
        "run_id": spec.run_id,
        "status": status,
        "error": error,
        "suite_order": spec.suite_order,
    }
    if not summary_path.exists():
        return row

    result = json.loads(summary_path.read_text())
    workload = result.get("workload", {})
    blocks = result.get("blocks", {})
    txs = workload.get("txs", [])
    measurement_hashes = {
        normalized
        for tx in txs
        if (normalized := normalize_tx_hash(tx.get("tx_hash")))
    }
    records = [
        record
        for record in blocks.get("records", [])
        if normalize_tx_hash(record.get("tx_hash")) in measurement_hashes
    ]
    path_lens = [float(record.get("path_len", 0)) for record in records]
    fee_records = [record for record in records if int(record.get("priority_fee_wei", 0)) > 0]
    delays = [
        float(tx.get("inclusion_delay_seconds", 0.0))
        for tx in txs
        if tx.get("status") == 1 and "inclusion_delay_seconds" in tx
    ]
    success_count = int(workload.get("success_count", 0))
    inclusion_tps = float(workload.get("inclusion_throughput_tps", 0.0))
    achieved_tx_per_slot = inclusion_tps * SECONDS_PER_SLOT
    achieved_ratio = achieved_tx_per_slot / float(spec.offered_tx_per_slot)
    measurement_window_seconds = spec.measurement_window_seconds
    window_start_unix = float(workload.get("first_send_unix", 0.0))
    window_end_unix = window_start_unix + float(measurement_window_seconds)
    window_included_count = sum(
        1
        for tx in txs
        if tx.get("status") == 1
        and float(tx.get("included_block_timestamp", 0.0) or 0.0) <= window_end_unix
    )
    window_achieved_tps = window_included_count / float(measurement_window_seconds)
    peer_graph = result.get("peer_graph", {})
    after = result.get("beacon_after", {})
    before_measurement = result.get("beacon_before_measurement", {})
    prom = result.get("prometheus", {})
    propagation = result.get("propagation", {})
    propagation_delay = propagation.get("delay_millis", {})
    row.update(
        {
            "status": status,
            "tx_success": success_count,
            "tx_success_ratio": success_count / float(spec.tx_count),
            "included_ratio": success_count / float(spec.tx_count),
            "window_included_count": window_included_count,
            "window_included_ratio": window_included_count / float(spec.tx_count),
            "measurement_window_seconds": measurement_window_seconds,
            "window_achieved_tps": window_achieved_tps,
            "window_achieved_ratio": window_achieved_tps / spec.offered_tps_value,
            "actual_send_tps": float(workload.get("actual_send_tps", 0.0)),
            "origin_mode": workload.get("origin_mode", ""),
            "origin_node_count": int(workload.get("origin_node_count", 0)),
            "origin_count_min": int(workload.get("origin_count_min", 0)),
            "origin_count_max": int(workload.get("origin_count_max", 0)),
            "origin_counts_json": json.dumps(workload.get("origin_counts", {}), sort_keys=True),
            "inclusion_tps": inclusion_tps,
            "achieved_tx_per_slot": achieved_tx_per_slot,
            "achieved_ratio": achieved_ratio,
            "p50_inclusion_delay_seconds": percentile(delays, 50),
            "p95_inclusion_delay_seconds": percentile(delays, 95),
            "propagation_records": int(propagation.get("record_count", 0)),
            "propagation_missing": int(propagation.get("missing_count", 0)),
            "p50_propagation_delay_millis": float(propagation_delay.get("p50", 0.0)),
            "p95_propagation_delay_millis": float(propagation_delay.get("p95", 0.0)),
            "avg_path_len": (sum(path_lens) / len(path_lens)) if path_lens else 0.0,
            "path_records": len(records),
            "fee_records": len(fee_records),
            "priority_fee_sum_wei": sum(int(record.get("priority_fee_wei", 0)) for record in records),
            "raw_block_records": int(blocks.get("record_count", 0)),
            "raw_nonzero_fee_records": int(blocks.get("nonzero_fee_records", 0)),
            "matches_target": peer_graph.get("matches_target"),
            "missed_slots": int(blocks.get("missed_slots", 0)),
            "head_slot": int(after.get("head_slot", 0)),
            "measurement_start_head_slot": int(before_measurement.get("head_slot", 0)),
            "finalized_epoch": int(after.get("finalized_epoch", 0)),
            "fee_conservation_violation_sum": prometheus_sum(prom, "topostake_fee_conservation_violation"),
            "summary_path": str(summary_path),
        }
    )
    return row


def write_rows(rows: list[dict[str, Any]]) -> None:
    PROCESSED.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "prompt",
        "figure",
        "mode",
        "mode_label",
        "topology",
        "nodes",
        "offered_tps",
        "offered_tx_per_slot",
        "tx_count",
        "warmup_tx_count",
        "seed",
        "run_id",
        "status",
        "error",
        "suite_order",
        "tx_success",
        "tx_success_ratio",
        "included_ratio",
        "window_included_count",
        "window_included_ratio",
        "measurement_window_seconds",
        "window_achieved_tps",
        "window_achieved_ratio",
        "actual_send_tps",
        "origin_mode",
        "origin_node_count",
        "origin_count_min",
        "origin_count_max",
        "origin_counts_json",
        "inclusion_tps",
        "achieved_tx_per_slot",
        "achieved_ratio",
        "p50_inclusion_delay_seconds",
        "p95_inclusion_delay_seconds",
        "propagation_records",
        "propagation_missing",
        "p50_propagation_delay_millis",
        "p95_propagation_delay_millis",
        "avg_path_len",
        "path_records",
        "fee_records",
        "priority_fee_sum_wei",
        "raw_block_records",
        "raw_nonzero_fee_records",
        "matches_target",
        "missed_slots",
        "head_slot",
        "measurement_start_head_slot",
        "finalized_epoch",
        "fee_conservation_violation_sum",
        "summary_path",
    ]
    with PROCESSED.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in sorted(rows, key=lambda item: int(item.get("suite_order", 0))):
            writer.writerow(row)
    log(f"wrote {PROCESSED}")


def load_existing_rows() -> list[dict[str, Any]]:
    if not PROCESSED.exists():
        return []
    with PROCESSED.open() as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=["prompt41", "prompt42", "prompt43", "prompt44", "all"], default="all")
    parser.add_argument("--topologies", help="Comma-separated topology filter, e.g. er,ba")
    parser.add_argument("--modes", help="Comma-separated mode filter, e.g. pathobs,topostake")
    parser.add_argument("--loads", help="Comma-separated offered tx/slot filter, e.g. 192,224")
    parser.add_argument("--tps", help="Comma-separated offered TPS values; internally converted to tx/slot")
    parser.add_argument("--nodes", help="Comma-separated node-count filter, e.g. 16")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--stop-on-failure", action="store_true")
    args = parser.parse_args()

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    ARGS_DIR.mkdir(parents=True, exist_ok=True)
    rows_by_run = {row["run_id"]: row for row in load_existing_rows() if row.get("run_id")}
    requested_loads = [int(item.strip()) for item in args.loads.split(",") if item.strip()] if args.loads else []
    requested_tps = [int(item.strip()) for item in args.tps.split(",") if item.strip()] if args.tps else []
    if args.suite == "prompt42" and requested_tps:
        specs = []
        order = 5000
        for tps in requested_tps:
            tx_per_slot = tps * SECONDS_PER_SLOT
            for mode in ("baseline", "topostake"):
                specs.append(
                    RunSpec(
                        prompt="prompt42",
                        figure="load_tps",
                        mode=mode,
                        topology="ba",
                        nodes=8,
                        offered_tx_per_slot=tx_per_slot,
                        offered_tps=tps,
                        suite_order=order,
                    )
                )
                order += 1
    elif args.suite == "prompt42" and requested_loads:
        specs = []
        order = 4000
        for load in requested_loads:
            for mode in ("baseline", "topostake"):
                specs.append(
                    RunSpec(
                        prompt="prompt42",
                        figure="load",
                        mode=mode,
                        topology="ba",
                        nodes=8,
                        offered_tx_per_slot=load,
                        suite_order=order,
                    )
                )
                order += 1
    else:
        specs = selected_specs(args.suite)
    if args.topologies:
        allowed = {item.strip() for item in args.topologies.split(",") if item.strip()}
        specs = [spec for spec in specs if spec.topology in allowed]
    if args.modes:
        allowed = {item.strip() for item in args.modes.split(",") if item.strip()}
        specs = [spec for spec in specs if spec.mode in allowed]
    if args.nodes:
        allowed_nodes = {int(item.strip()) for item in args.nodes.split(",") if item.strip()}
        specs = [spec for spec in specs if spec.nodes in allowed_nodes]
    if requested_loads:
        allowed_loads = set(requested_loads)
        specs = [spec for spec in specs if spec.offered_tx_per_slot in allowed_loads]
    total = len(specs)
    log(f"selected {total} runs for {args.suite}")

    for index, spec in enumerate(specs, start=1):
        summary_path = OUTPUT_ROOT / spec.run_id / "summary.json"
        if args.skip_existing and summary_path.exists():
            log(f"[{index}/{total}] skip existing {spec.run_id}")
            rows_by_run[spec.run_id] = summarize(spec)
            write_rows(list(rows_by_run.values()))
            continue

        log(
            f"[{index}/{total}] start {spec.run_id}: "
            f"{MODE_LABELS[spec.mode]}, {spec.topology}, n={spec.nodes}, "
            f"{spec.offered_tx_per_slot} tx/slot"
        )
        try:
            start_devnet(spec)
            run_workload(spec)
            rows_by_run[spec.run_id] = summarize(spec)
            row = rows_by_run[spec.run_id]
            log(
                f"[{index}/{total}] done {spec.run_id}: "
                f"{row.get('tx_success', 0)}/{spec.tx_count}, "
                f"included={float(row.get('included_ratio', 0.0)):.3f}, "
                f"achieved={float(row.get('achieved_ratio', 0.0)):.3f}, "
                f"p95={float(row.get('p95_inclusion_delay_seconds', 0.0)):.2f}s, "
                f"path={float(row.get('avg_path_len', 0.0)):.2f}"
            )
        except Exception as exc:
            log(f"[{index}/{total}] FAILED {spec.run_id}: {exc}")
            rows_by_run[spec.run_id] = summarize(spec, status="failed", error=str(exc))
            if args.stop_on_failure:
                raise
        finally:
            write_rows(list(rows_by_run.values()))
            remove_enclave(spec.enclave)

    write_rows(list(rows_by_run.values()))


if __name__ == "__main__":
    main()
