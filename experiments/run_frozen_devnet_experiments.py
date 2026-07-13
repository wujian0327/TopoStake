#!/usr/bin/env python3
"""Run resumable frozen-v1 Kurtosis experiment matrices."""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import math
import random
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from frozen_devnet_acceptance import artifact_checks, report, static_checks
from run_frozen_devnet_smoke import (
    collect_build_provenance,
    collect_geth_statuses,
    command_env,
    enrich_irrecoverable_costs,
    ensure_registry,
    remove_enclave,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PACKAGE = Path("/tmp/ethereum-package")
VARIANTS = ("baseline", "pathobs", "fee_only", "bonus_only", "topostake")


@dataclass(frozen=True)
class RunSpec:
    suite: str
    variant: str
    nodes: int
    load_tx_per_slot: int
    topology: str
    seed: int
    validators_per_node: int
    seconds_per_slot: int
    slots_per_epoch: int
    warmup_epochs: int
    measurement_epochs: int
    resource_interval: float
    receipt_timeout: int
    finality_timeout: int

    @property
    def run_id(self) -> str:
        return (
            f"{self.variant}_{self.topology}_n{self.nodes}_"
            f"load{self.load_tx_per_slot}_seed{self.seed}"
        )

    @property
    def enclave(self) -> str:
        return ("ts-fv1-" + self.run_id.replace("_", "-"))[:58]

    @property
    def tx_count(self) -> int:
        return self.load_tx_per_slot * self.slots_per_epoch * self.measurement_epochs

    @property
    def warmup_tx_count(self) -> int:
        return self.load_tx_per_slot * self.slots_per_epoch * self.warmup_epochs

    @property
    def tx_interval_seconds(self) -> float:
        return self.seconds_per_slot / float(self.load_tx_per_slot)


def load_config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def parse_csv_override(raw: str | None, cast: Any) -> list[Any] | None:
    if not raw:
        return None
    return [cast(item.strip()) for item in raw.split(",") if item.strip()]


def specs_from_config(config: dict[str, Any], args: argparse.Namespace) -> list[RunSpec]:
    variants = parse_csv_override(args.variants, str) or list(config["variants"])
    unknown = sorted(set(variants) - set(VARIANTS))
    if unknown:
        raise ValueError(f"unknown variants: {','.join(unknown)}")
    seeds = parse_csv_override(args.seeds, int) or [int(value) for value in config["seeds"]]
    nodes = parse_csv_override(args.nodes, int) or [int(value) for value in config["nodes"]]
    loads = parse_csv_override(args.loads, int) or [int(value) for value in config["loads_tx_per_slot"]]
    topologies = parse_csv_override(args.topologies, str) or list(config["topologies"])
    specs = [
        RunSpec(
            suite=str(config["suite"]),
            variant=variant,
            nodes=node_count,
            load_tx_per_slot=load,
            topology=topology,
            seed=seed,
            validators_per_node=int(config["validators_per_node"]),
            seconds_per_slot=int(config["seconds_per_slot"]),
            slots_per_epoch=int(config["slots_per_epoch"]),
            warmup_epochs=int(config["warmup_epochs"]),
            measurement_epochs=int(config["measurement_epochs"]),
            resource_interval=float(config["resource_sample_interval_seconds"]),
            receipt_timeout=int(config["receipt_timeout_seconds"]),
            finality_timeout=int(config["finality_timeout_seconds"]),
        )
        for variant, node_count, load, topology, seed in itertools.product(
            variants, nodes, loads, topologies, seeds
        )
    ]
    if config.get("randomize_order", True):
        random.Random(int(config.get("order_seed", 0))).shuffle(specs)
    return specs


def run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    print("$ " + " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=ROOT, env=command_env(), check=check, text=True)


def generate_args(spec: RunSpec, public_registry: Path, private_registry: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            sys.executable,
            "scripts/topostake_devnet_args.py",
            "--mode",
            spec.variant,
            "--count",
            str(spec.nodes),
            "--validator-count",
            str(spec.validators_per_node),
            "--maxpeers",
            str(max(8, spec.nodes)),
            "--enable-observability",
            "--label",
            spec.run_id,
            "--public-registry",
            str(public_registry),
            "--private-registry",
            str(private_registry),
            "--out",
            str(output),
        ]
    )


def start_monitor(spec: RunSpec, output: Path) -> tuple[subprocess.Popen[str], Any]:
    log_path = output.with_suffix(".log")
    log_handle = log_path.open("w")
    duration = spec.finality_timeout + (
        spec.warmup_epochs + spec.measurement_epochs + 4
    ) * spec.slots_per_epoch * spec.seconds_per_slot
    process = subprocess.Popen(
        [
            sys.executable,
            "experiments/monitor_devnet_bottleneck.py",
            "--enclave",
            spec.enclave,
            "--output",
            str(output),
            "--interval",
            str(spec.resource_interval),
            "--duration",
            str(duration),
        ],
        cwd=ROOT,
        env=command_env(),
        text=True,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )
    return process, log_handle


def stop_monitor(process: subprocess.Popen[str] | None, log_handle: Any | None) -> None:
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    if log_handle is not None:
        log_handle.close()


def run_workload(spec: RunSpec, output_root: Path) -> None:
    run(
        [
            sys.executable,
            "experiments/topostake_devnet_runner.py",
            "run",
            "--enclave",
            spec.enclave,
            "--run-id",
            spec.run_id,
            "--output-root",
            str(output_root),
            "--n",
            str(spec.nodes),
            "--topology",
            spec.topology,
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
            str(spec.receipt_timeout),
            "--wait-receipts-after-send",
            "--seconds-per-slot",
            str(spec.seconds_per_slot),
            "--warmup-finality-epochs",
            str(spec.warmup_epochs),
            "--wait-finality",
            "--wait-finality-epochs",
            "1",
            "--finality-timeout-seconds",
            str(spec.finality_timeout),
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
    rank = pct / 100.0 * (len(ordered) - 1)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    fraction = rank - low
    return ordered[low] * (1.0 - fraction) + ordered[high] * fraction


def collect_block_sizes(summary: dict[str, Any]) -> dict[str, Any]:
    cl_apis = summary.get("endpoints", {}).get("cl_apis", [])
    blocks = summary.get("blocks", {})
    if not cl_apis or not blocks:
        return {"encoding": "unavailable", "samples": []}
    endpoint = str(cl_apis[0]).rstrip("/")
    samples = []
    encodings = set()
    for slot in range(int(blocks.get("start_slot", 0)), int(blocks.get("end_slot", -1)) + 1):
        request = urllib.request.Request(
            f"{endpoint}/eth/v2/beacon/blocks/{slot}",
            headers={"Accept": "application/octet-stream"},
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                payload = response.read()
                content_type = response.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                continue
            raise
        encoding = "ssz" if "octet-stream" in content_type else "http-response"
        encodings.add(encoding)
        samples.append({"slot": slot, "bytes": len(payload), "encoding": encoding})
    sizes = [float(item["bytes"]) for item in samples]
    return {
        "encoding": encodings.pop() if len(encodings) == 1 else "mixed",
        "samples": samples,
        "count": len(sizes),
        "mean_bytes": sum(sizes) / len(sizes) if sizes else 0.0,
        "p95_bytes": percentile(sizes, 95),
        "max_bytes": max(sizes, default=0.0),
    }


def prometheus_query(endpoint: str, query: str) -> list[dict[str, Any]]:
    url = f"{endpoint.rstrip('/')}/api/v1/query?{urllib.parse.urlencode({'query': query})}"
    with urllib.request.urlopen(url, timeout=15) as response:
        payload = json.loads(response.read())
    return payload.get("data", {}).get("result", [])


def prometheus_sum(endpoint: str, query: str) -> float:
    total = 0.0
    for sample in prometheus_query(endpoint, query):
        try:
            value = float(sample.get("value", [None, 0])[1])
            if math.isfinite(value):
                total += value
        except (TypeError, ValueError):
            pass
    return total


def collect_formal_prometheus(summary: dict[str, Any]) -> dict[str, Any]:
    endpoint = summary.get("endpoints", {}).get("prometheus")
    if not endpoint:
        return {"error": "missing Prometheus endpoint"}
    queries = {
        "evidence_verify_seconds_sum": "topostake_inline_evidence_verify_seconds_sum",
        "evidence_verify_count": "topostake_inline_evidence_verify_seconds_count",
        "evidence_verify_p95_seconds": (
            "histogram_quantile(0.95, sum by (le) "
            "(topostake_inline_evidence_verify_seconds_bucket))"
        ),
        "gossip_block_verify_delay_ms_sum": "sum(topostake_gossip_block_verification_delay_milliseconds)",
    }
    result: dict[str, Any] = {"endpoint": endpoint, "queries": queries}
    for name, query in queries.items():
        try:
            result[name] = prometheus_sum(str(endpoint), query)
        except Exception as exc:
            result[name] = None
            result[f"{name}_error"] = str(exc)
    count = float(result.get("evidence_verify_count") or 0.0)
    total = float(result.get("evidence_verify_seconds_sum") or 0.0)
    result["evidence_verify_mean_seconds"] = total / count if count else 0.0
    return result


def measurement_quality_checks(
    spec: RunSpec,
    block_sizes: dict[str, Any],
    resources: dict[str, Any],
    prometheus: dict[str, Any],
) -> dict[str, Any]:
    checks = [
        {
            "name": "ssz-block-size-samples",
            "passed": block_sizes.get("encoding") == "ssz"
            and int(block_sizes.get("count", 0)) > 0,
            "detail": f"encoding={block_sizes.get('encoding')}, count={block_sizes.get('count', 0)}",
        },
        {
            "name": "resource-samples",
            "passed": int(resources.get("samples", 0)) >= 2,
            "detail": f"samples={resources.get('samples', 0)}, error={resources.get('error')}",
        },
        {
            "name": "prometheus-available",
            "passed": "error" not in prometheus
            and not any(key.endswith("_error") for key in prometheus),
            "detail": str(
                prometheus.get("error")
                or {
                    key: value
                    for key, value in prometheus.items()
                    if key.endswith("_error")
                }
                or "ok"
            ),
        },
    ]
    verify_count = float(prometheus.get("evidence_verify_count") or 0.0)
    if spec.variant == "baseline":
        checks.append(
            {
                "name": "baseline-no-evidence-verification",
                "passed": verify_count == 0.0,
                "detail": f"count={verify_count}",
            }
        )
    else:
        checks.append(
            {
                "name": "evidence-verification-timing",
                "passed": verify_count > 0.0,
                "detail": f"count={verify_count}",
            }
        )
    return {"passed": all(item["passed"] for item in checks), "checks": checks}


BYTE_UNITS = {
    "b": 1.0,
    "kb": 1_000.0,
    "mb": 1_000_000.0,
    "gb": 1_000_000_000.0,
    "kib": 1024.0,
    "mib": 1024.0**2,
    "gib": 1024.0**3,
}


def parse_bytes(raw: str) -> float:
    match = re.match(r"\s*([0-9.]+)\s*([A-Za-z]+)", raw or "")
    if not match:
        return 0.0
    return float(match.group(1)) * BYTE_UNITS.get(match.group(2).lower(), 1.0)


def client_kind(name: str) -> str | None:
    lowered = name.lower()
    if re.search(r"el-\d+-geth", lowered):
        return "el"
    if re.search(r"cl-\d+-lighthouse", lowered):
        return "cl"
    return None


def summarize_resources(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"error": "resource JSONL missing", "samples": 0}
    aggregates = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        row = {
            "ts": float(record.get("ts", 0.0)),
            "cpu_percent": 0.0,
            "memory_bytes": 0.0,
            "network_rx_bytes": 0.0,
            "network_tx_bytes": 0.0,
            "el_cpu_percent": 0.0,
            "cl_cpu_percent": 0.0,
        }
        clients = 0
        for container in record.get("docker", []):
            kind = client_kind(str(container.get("Name", "")))
            if kind is None:
                continue
            clients += 1
            cpu = float(str(container.get("CPUPerc", "0")).strip().rstrip("%") or 0.0)
            memory = parse_bytes(str(container.get("MemUsage", "")).split("/")[0])
            net_parts = str(container.get("NetIO", "")).split("/")
            rx = parse_bytes(net_parts[0]) if net_parts else 0.0
            tx = parse_bytes(net_parts[1]) if len(net_parts) > 1 else 0.0
            row["cpu_percent"] += cpu
            row["memory_bytes"] += memory
            row["network_rx_bytes"] += rx
            row["network_tx_bytes"] += tx
            row[f"{kind}_cpu_percent"] += cpu
        if clients:
            aggregates.append(row)
    cpu = [row["cpu_percent"] for row in aggregates]
    memory = [row["memory_bytes"] for row in aggregates]
    rx = [row["network_rx_bytes"] for row in aggregates]
    tx = [row["network_tx_bytes"] for row in aggregates]
    return {
        "samples": len(aggregates),
        "cpu_mean_percent": sum(cpu) / len(cpu) if cpu else 0.0,
        "cpu_p95_percent": percentile(cpu, 95),
        "memory_max_bytes": max(memory, default=0.0),
        "network_rx_delta_bytes": max(0.0, max(rx, default=0.0) - min(rx, default=0.0)),
        "network_tx_delta_bytes": max(0.0, max(tx, default=0.0) - min(tx, default=0.0)),
        "el_cpu_mean_percent": (
            sum(row["el_cpu_percent"] for row in aggregates) / len(aggregates)
            if aggregates
            else 0.0
        ),
        "cl_cpu_mean_percent": (
            sum(row["cl_cpu_percent"] for row in aggregates) / len(aggregates)
            if aggregates
            else 0.0
        ),
    }


def workload_metrics(summary: dict[str, Any]) -> dict[str, float]:
    workload = summary.get("workload", {})
    txs = workload.get("txs", [])
    delays = [
        float(tx["inclusion_delay_seconds"])
        for tx in txs
        if tx.get("status") == 1 and "inclusion_delay_seconds" in tx
    ]
    return {
        "success_count": float(workload.get("success_count", 0)),
        "success_ratio": float(workload.get("success_count", 0)) / max(1.0, float(len(txs))),
        "inclusion_throughput_tps": float(workload.get("inclusion_throughput_tps", 0.0)),
        "p50_inclusion_delay_seconds": percentile(delays, 50),
        "p95_inclusion_delay_seconds": percentile(delays, 95),
    }


def build_row(spec: RunSpec, run_dir: Path, status: str, error: str = "") -> dict[str, Any]:
    row: dict[str, Any] = {**asdict(spec), "run_id": spec.run_id, "status": status, "error": error}
    summary_path = run_dir / "summary.json"
    if not summary_path.exists():
        return row
    summary = json.loads(summary_path.read_text())
    formal = summary.get("formal_experiment", {})
    row.update(workload_metrics(summary))
    row.update(
        {
            "finalized_epoch_before": summary.get("beacon_before_measurement", {}).get("finalized_epoch", 0),
            "finalized_epoch_after": summary.get("beacon_after", {}).get("finalized_epoch", 0),
            "missed_slots": summary.get("blocks", {}).get("missed_slots", 0),
            "block_records": summary.get("blocks", {}).get("record_count", 0),
            "avg_path_len": summary.get("blocks", {}).get("path_length", {}).get("mean", 0.0),
            "acceptance_passed": formal.get("acceptance", {}).get("passed", False),
            "measurement_quality_passed": formal.get("measurement_quality", {}).get(
                "passed", False
            ),
            "block_ssz_mean_bytes": formal.get("block_sizes", {}).get("mean_bytes", 0.0),
            "block_ssz_p95_bytes": formal.get("block_sizes", {}).get("p95_bytes", 0.0),
            "cpu_mean_percent": formal.get("resources", {}).get("cpu_mean_percent", 0.0),
            "cpu_p95_percent": formal.get("resources", {}).get("cpu_p95_percent", 0.0),
            "memory_max_bytes": formal.get("resources", {}).get("memory_max_bytes", 0.0),
            "network_rx_delta_bytes": formal.get("resources", {}).get("network_rx_delta_bytes", 0.0),
            "network_tx_delta_bytes": formal.get("resources", {}).get("network_tx_delta_bytes", 0.0),
            "evidence_verify_count": formal.get("prometheus", {}).get("evidence_verify_count", 0.0),
            "evidence_verify_mean_seconds": formal.get("prometheus", {}).get(
                "evidence_verify_mean_seconds", 0.0
            ),
            "evidence_verify_p95_seconds": formal.get("prometheus", {}).get(
                "evidence_verify_p95_seconds", 0.0
            ),
            "summary_path": str(summary_path),
        }
    )
    return row


def write_aggregate(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda row: row.get("run_id", "")))


def execute_run(
    spec: RunSpec,
    args: argparse.Namespace,
    provenance: dict[str, Any],
    public_registry: Path,
    private_registry: Path,
) -> tuple[str, str]:
    run_dir = args.output_root / spec.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    status_path = run_dir / "runner_status.json"
    if args.resume and status_path.exists():
        status = json.loads(status_path.read_text())
        if status.get("status") == "ok" and (run_dir / "summary.json").exists():
            existing = json.loads((run_dir / "summary.json").read_text())
            if existing.get("build_provenance") == provenance:
                print(f"skip completed {spec.run_id}")
                return "ok", ""
            print(f"rerun {spec.run_id}: build provenance changed")
    status_path.write_text(
        json.dumps(
            {
                "status": "running",
                "started_at": time.time(),
                "spec": asdict(spec),
                "build_provenance": provenance,
            },
            indent=2,
        )
        + "\n"
    )
    monitor = None
    monitor_log = None
    error = ""
    try:
        args_file = run_dir / "kurtosis_args.yaml"
        generate_args(spec, public_registry, private_registry, args_file)
        remove_enclave(spec.enclave)
        run(
            [
                "kurtosis",
                "run",
                "--enclave",
                spec.enclave,
                str(args.package),
                "--args-file",
                str(args_file),
            ]
        )
        monitor, monitor_log = start_monitor(spec, run_dir / "resources.jsonl")
        run_workload(spec, args.output_root)
        stop_monitor(monitor, monitor_log)
        monitor = monitor_log = None
        summary_path = run_dir / "summary.json"
        if spec.variant != "baseline":
            enrich_irrecoverable_costs(summary_path)
            collect_geth_statuses(summary_path)
        summary = json.loads(summary_path.read_text())
        acceptance = report(
            static_checks() + artifact_checks(summary, spec.variant),
            mode=spec.variant,
            artifact=str(summary_path),
        )
        block_sizes = collect_block_sizes(summary)
        resources = summarize_resources(run_dir / "resources.jsonl")
        prometheus = collect_formal_prometheus(summary)
        measurement_quality = measurement_quality_checks(
            spec, block_sizes, resources, prometheus
        )
        formal = {
            "spec": asdict(spec),
            "build_provenance": provenance,
            "acceptance": acceptance,
            "measurement_quality": measurement_quality,
            "block_sizes": block_sizes,
            "resources": resources,
            "prometheus": prometheus,
        }
        summary["formal_experiment"] = formal
        summary["build_provenance"] = provenance
        summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
        (run_dir / "acceptance.json").write_text(
            json.dumps(acceptance, indent=2, sort_keys=True) + "\n"
        )
        if not acceptance["passed"]:
            raise RuntimeError("frozen-v1 acceptance failed")
        if not measurement_quality["passed"]:
            failed = [
                item["name"]
                for item in measurement_quality["checks"]
                if not item["passed"]
            ]
            raise RuntimeError(f"measurement quality failed: {','.join(failed)}")
        status = "ok"
    except Exception as exc:
        status = "failed"
        error = str(exc)
        print(f"FAILED {spec.run_id}: {error}", flush=True)
    finally:
        stop_monitor(monitor, monitor_log)
        if not args.keep_enclaves:
            remove_enclave(spec.enclave)
        status_path.write_text(
            json.dumps(
                {
                    "status": status,
                    "finished_at": time.time(),
                    "error": error,
                    "spec": asdict(spec),
                    "build_provenance": provenance,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
    return status, error


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--package", type=Path, default=DEFAULT_PACKAGE)
    parser.add_argument("--seeds", help="Comma-separated seed override")
    parser.add_argument("--variants", help="Comma-separated variant override")
    parser.add_argument("--nodes", help="Comma-separated node-count override")
    parser.add_argument("--loads", help="Comma-separated tx/slot override")
    parser.add_argument("--topologies", help="Comma-separated topology override")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--keep-enclaves", action="store_true")
    parser.add_argument("--stop-on-failure", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    config = load_config(args.config)
    if config.get("protocol_version") != "frozen-v1":
        parser.error("config is not frozen-v1")
    specs = specs_from_config(config, args)
    args.output_root = ROOT / "results" / "raw" / str(config["suite"])
    aggregate_path = ROOT / "results" / "processed" / f"{config['suite']}.csv"
    if args.dry_run:
        print(json.dumps([asdict(spec) | {"run_id": spec.run_id} for spec in specs], indent=2))
        print(f"runs={len(specs)}")
        return 0
    if not args.package.exists():
        parser.error(f"ethereum-package not found: {args.package}")

    provenance = collect_build_provenance()
    args.output_root.mkdir(parents=True, exist_ok=True)
    manifest = {
        "config_path": str(args.config),
        "config": config,
        "build_provenance": provenance,
        "created_at": time.time(),
        "runs": [asdict(spec) | {"run_id": spec.run_id, "enclave": spec.enclave} for spec in specs],
    }
    (args.output_root / "experiment_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    registry_by_nodes = {node_count: ensure_registry(node_count) for node_count in {s.nodes for s in specs}}
    rows_by_id: dict[str, dict[str, Any]] = {}
    failures = 0
    for index, spec in enumerate(specs, start=1):
        print(f"[{index}/{len(specs)}] {spec.run_id}", flush=True)
        public, private = registry_by_nodes[spec.nodes]
        status, error = execute_run(spec, args, provenance, public, private)
        rows_by_id[spec.run_id] = build_row(spec, args.output_root / spec.run_id, status, error)
        write_aggregate(aggregate_path, list(rows_by_id.values()))
        if status != "ok":
            failures += 1
            if args.stop_on_failure:
                break
    print(f"wrote {aggregate_path}; failures={failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
