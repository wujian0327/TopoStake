#!/usr/bin/env python3
"""Run baseline, path-observation, and TopoStake frozen-v1 devnet smokes."""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from frozen_devnet_acceptance import MODES, artifact_checks, report, static_checks


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = ROOT / "results" / "raw" / "frozen_v1_devnet"
DEFAULT_REPORT = ROOT / "results" / "processed" / "frozen_v1_devnet_smoke.json"
DEFAULT_ARGS_ROOT = ROOT / "results" / "raw" / "frozen_v1_devnet_args"


def command_env() -> dict[str, str]:
    env = dict(os.environ)
    data_home = Path(tempfile.gettempdir()) / "kurtosis-data"
    env.setdefault("XDG_DATA_HOME", str(data_home))
    env.setdefault("NO_PROXY", "127.0.0.1,localhost")
    env.setdefault("no_proxy", "127.0.0.1,localhost")
    return env


def run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    print("$ " + " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=ROOT, env=command_env(), check=check, text=True)


def ensure_registry(nodes: int) -> tuple[Path, Path]:
    public = ROOT / "results" / "processed" / f"frozen_v1_relay_registry_n{nodes}.json"
    private = ROOT / "results" / "raw" / f"frozen_v1_relay_private_n{nodes}.json"
    if public.exists() and private.exists():
        return public, private
    public.parent.mkdir(parents=True, exist_ok=True)
    private.parent.mkdir(parents=True, exist_ok=True)
    run(
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


def generate_args(
    mode: str,
    nodes: int,
    validators_per_node: int,
    public_registry: Path,
    private_registry: Path,
    args_root: Path,
) -> Path:
    args_root.mkdir(parents=True, exist_ok=True)
    output = args_root / f"{mode}.yaml"
    run(
        [
            sys.executable,
            "scripts/topostake_devnet_args.py",
            "--mode",
            mode,
            "--count",
            str(nodes),
            "--validator-count",
            str(validators_per_node),
            "--maxpeers",
            str(max(8, nodes)),
            "--enable-observability",
            "--label",
            f"frozen-v1-smoke-{mode}",
            "--public-registry",
            str(public_registry),
            "--private-registry",
            str(private_registry),
            "--out",
            str(output),
        ]
    )
    return output


def remove_enclave(enclave: str) -> None:
    run(["kurtosis", "enclave", "rm", "-f", enclave], check=False)


def enrich_irrecoverable_costs(summary_path: Path) -> None:
    """Copy the frozen-v1 cost field from live beacon records into artifacts."""
    summary = json.loads(summary_path.read_text())
    records = summary.get("blocks", {}).get("records", [])
    if not records:
        return
    cl_apis = summary.get("endpoints", {}).get("cl_apis", [])
    if not cl_apis:
        raise RuntimeError("devnet summary has evidence records but no CL endpoint")
    cl_api = str(cl_apis[0]).rstrip("/")
    by_slot: dict[int, list[dict]] = {}
    for record in records:
        by_slot.setdefault(int(record["slot"]), []).append(record)

    for slot, slot_records in by_slot.items():
        with urllib.request.urlopen(f"{cl_api}/eth/v2/beacon/blocks/{slot}", timeout=15) as response:
            message = json.loads(response.read())["data"]["message"]
        body = message.get("body", {})
        inline = body.get("topostake_evidence_records") or body.get("topostakeEvidenceRecords") or []
        costs = {
            (str(item.get("tx_hash", "")).lower(), int(item.get("epoch", 0))): int(
                item.get("irrecoverable_cost_wei", 0)
            )
            for item in inline
        }
        for record in slot_records:
            key = (str(record.get("tx_hash", "")).lower(), int(record.get("epoch", 0)))
            if key not in costs:
                raise RuntimeError(f"cannot recover irrecoverable cost for slot={slot}, tx={key[0]}")
            record["irrecoverable_cost_wei"] = costs[key]

    summary["blocks"]["irrecoverable_cost_sum_wei"] = sum(
        int(record["irrecoverable_cost_wei"]) for record in records
    )
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")

    csv_path = summary_path.parent / "block_records.csv"
    if csv_path.exists():
        with csv_path.open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        costs = {
            (str(record["slot"]), str(record["record_index"])): record["irrecoverable_cost_wei"]
            for record in records
        }
        fieldnames = list(rows[0]) if rows else []
        if "irrecoverable_cost_wei" not in fieldnames:
            insert_at = fieldnames.index("priority_fee_wei") + 1 if "priority_fee_wei" in fieldnames else len(fieldnames)
            fieldnames.insert(insert_at, "irrecoverable_cost_wei")
        for row in rows:
            row["irrecoverable_cost_wei"] = costs.get((row.get("slot", ""), row.get("record_index", "")), 0)
        with csv_path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)


def run_mode(args: argparse.Namespace, mode: str, public: Path, private: Path) -> dict:
    enclave = f"ts-frozen-v1-{mode}"
    run_id = mode
    summary_path = args.output_root / run_id / "summary.json"
    if args.skip_existing and summary_path.exists():
        print(f"reuse {summary_path}")
    else:
        args_file = generate_args(
            mode,
            args.nodes,
            args.validators_per_node,
            public,
            private,
            args.args_root,
        )
        remove_enclave(enclave)
        try:
            run(
                [
                    "kurtosis",
                    "run",
                    "--enclave",
                    enclave,
                    str(args.package),
                    "--args-file",
                    str(args_file),
                ]
            )
            run(
                [
                    sys.executable,
                    "experiments/topostake_devnet_runner.py",
                    "run",
                    "--enclave",
                    enclave,
                    "--run-id",
                    run_id,
                    "--output-root",
                    str(args.output_root),
                    "--n",
                    str(args.nodes),
                    "--topology",
                    args.topology,
                    "--seed",
                    str(args.seed),
                    "--tx-count",
                    str(args.tx_count),
                    "--warmup-tx-count",
                    str(args.warmup_tx_count),
                    "--tx-interval-seconds",
                    str(args.tx_interval_seconds),
                    "--origin-mode",
                    "round_robin",
                    "--sender-count",
                    "0",
                    "--send-concurrency",
                    "0",
                    "--receipt-concurrency",
                    "0",
                    "--wait-receipts-after-send",
                    "--warmup-finality-epochs",
                    "3",
                    "--wait-finality",
                    "--wait-finality-epochs",
                    "1",
                    "--finality-timeout-seconds",
                    str(args.finality_timeout_seconds),
                    "--pre-scan-slots",
                    "4",
                ]
            )
            enrich_irrecoverable_costs(summary_path)
        finally:
            if not args.keep_enclaves:
                remove_enclave(enclave)

    if not summary_path.exists():
        raise FileNotFoundError(f"missing devnet artifact {summary_path}")
    summary = json.loads(summary_path.read_text())
    mode_report = report(static_checks() + artifact_checks(summary, mode), mode=mode, artifact=str(summary_path))
    mode_report_path = args.report.parent / f"frozen_v1_devnet_{mode}.json"
    mode_report_path.parent.mkdir(parents=True, exist_ok=True)
    mode_report_path.write_text(json.dumps(mode_report, indent=2, sort_keys=True) + "\n")
    for item in mode_report["checks"]:
        print(f"[{'PASS' if item['passed'] else 'FAIL'}] {mode}/{item['name']}: {item['detail']}")
    return mode_report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--package",
        type=Path,
        default=Path(os.environ.get("TOPOSTAKE_ETHEREUM_PACKAGE", "/tmp/ethereum-package")),
        help="Local ethpandaops/ethereum-package checkout",
    )
    parser.add_argument("--modes", default=",".join(MODES), help="Comma-separated subset of baseline,pathobs,topostake")
    parser.add_argument("--nodes", type=int, default=4)
    parser.add_argument("--validators-per-node", type=int, default=1)
    parser.add_argument("--topology", choices=("linear", "ring", "star", "er", "random_regular", "ba"), default="ring")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--tx-count", type=int, default=32)
    parser.add_argument("--warmup-tx-count", type=int, default=32)
    parser.add_argument("--tx-interval-seconds", type=float, default=0.25)
    parser.add_argument("--finality-timeout-seconds", type=int, default=900)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--args-root", type=Path, default=DEFAULT_ARGS_ROOT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--keep-enclaves", action="store_true")
    args = parser.parse_args()

    modes = [item.strip() for item in args.modes.split(",") if item.strip()]
    unknown = sorted(set(modes) - set(MODES))
    if unknown:
        parser.error(f"unknown modes: {','.join(unknown)}")
    modes_to_run = [
        mode
        for mode in modes
        if not (args.skip_existing and (args.output_root / mode / "summary.json").exists())
    ]
    if modes_to_run and not args.package.exists():
        parser.error(f"ethereum-package not found: {args.package}")

    started = time.time()
    if any(mode != "baseline" for mode in modes_to_run):
        public, private = ensure_registry(args.nodes)
    else:
        public = private = Path("unused-for-baseline-or-existing-artifacts")
    reports = []
    for mode in modes:
        reports.append(run_mode(args, mode, public, private))
    combined = {
        "protocol_version": "frozen-v1",
        "passed": all(item["passed"] for item in reports),
        "duration_seconds": time.time() - started,
        "modes": reports,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(combined, indent=2, sort_keys=True) + "\n")
    print(f"wrote {args.report}")
    return 0 if combined["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
