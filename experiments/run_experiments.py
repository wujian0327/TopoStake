#!/usr/bin/env python3
"""Run reproducible TopoStake paper experiments from YAML specs."""

from __future__ import annotations

import argparse
import concurrent.futures
import itertools
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List


ROOT = Path(__file__).resolve().parents[1]
RAW_ROOT = ROOT / "results" / "raw"
PROCESSED_ROOT = ROOT / "results" / "processed"

DIMENSION_KEYS = [
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
    "topostake_initial_depth",
    "attack_tx_rate_multiplier",
    "unstable_fraction",
    "offline_probability",
    "attack_mode",
]

CLI_KEYS = {
    "node_num": "--node-num",
    "sybil_node_num": "--sybil-node-num",
    "fake_node_num": "--fake-node-num",
    "unstable_node_num": "--unstable-node-num",
    "tx_rate": "--trans-num",
    "topology": "--topology",
    "stake_gini": "--gini",
    "transaction_fee": "--transaction-fee",
    "base_reward": "--base-reward",
    "slot_duration": "--slot-duration",
    "slot_per_epoch": "--slot-per-epoch",
    "max_epochs": "--max-epochs",
    "max_tx_per_block": "--max-tx-per-block",
    "topostake_initial_depth": "--topostake-initial-depth",
    "beta": "--beta",
    "topostake_saturation_k": "--topostake-saturation-k",
    "eta": "--eta",
    "bonus_cap": "--bonus-cap",
    "proposer_fee_ratio": "--proposer-fee-ratio",
    "reward_settlement_depth": "--reward-settlement-depth",
    "time_scale": "--time-scale",
    "network_delay_multiplier": "--network-delay-multiplier",
    "validator_scale_capacity_penalty": "--validator-scale-capacity-penalty",
    "topostake_scale_capacity_bonus": "--topostake-scale-capacity-bonus",
    "validator_scale_latency_penalty": "--validator-scale-latency-penalty",
    "topostake_scale_latency_reduction": "--topostake-scale-latency-reduction",
    "topostake_latency_reduction_s": "--topostake-latency-reduction-s",
    "unstable_fraction": "--unstable-fraction",
    "offline_probability": "--offline-probability",
    "adversary_stake_fraction": "--adversary-stake-fraction",
    "adversary_placement": "--adversary-placement",
    "attack_mode": "--attack-mode",
    "padding_identities": "--padding-identities",
    "attack_tx_rate_multiplier": "--attack-tx-rate-multiplier",
}

EXPERIMENT_OVERRIDE_KEYS = set(CLI_KEYS) | {"warmup_epochs", "real_time"}

RUN_ID_KEY_ALIASES = {
    "network_delay_multiplier": "netdelay",
    "validator_scale_capacity_penalty": "capovh",
    "topostake_scale_capacity_bonus": "topocap",
    "validator_scale_latency_penalty": "latovh",
    "topostake_scale_latency_reduction": "topolat",
    "topostake_latency_reduction_s": "topolatsec",
}


def load_yaml(path: Path) -> Dict[str, Any]:
    text = path.read_text()
    try:
        import yaml  # type: ignore

        return yaml.safe_load(text)
    except ModuleNotFoundError:
        return json.loads(text)


def as_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    return [value]


def slug(value: Any) -> str:
    text = str(value).lower().replace(".", "p")
    safe = []
    for ch in text:
        safe.append(ch if ch.isalnum() else "-")
    return "".join(safe).strip("-")


def seed_bundle(seed_value: int) -> Dict[str, int]:
    base = 100_000 + seed_value * 100
    return {
        "graph_seed": base + 1,
        "wallet_seed": base + 2,
        "workload_seed": base + 3,
        "election_seed": base + 4,
        "failure_seed": base + 5,
        "attack_seed": base + 6,
    }


def protocol_cli(protocol_variant: str) -> Dict[str, Any]:
    if protocol_variant == "topostake_eta0":
        return {"protocol": "topostake", "protocol_label": "topostake_eta0", "eta": 0.0}
    return {"protocol": protocol_variant, "protocol_label": protocol_variant}


def expand_runs(spec: Dict[str, Any], only: Iterable[str] | None = None) -> List[Dict[str, Any]]:
    suite = spec.get("suite", "main")
    defaults = dict(spec.get("defaults", {}))
    seeds = [int(seed) for seed in spec.get("seeds", [0])]
    only_set = set(only or [])
    runs: List[Dict[str, Any]] = []

    for experiment in spec.get("experiments", []):
        name = experiment["name"]
        if only_set and name not in only_set:
            continue
        protocols = experiment.get("protocols", [defaults.get("protocol", "topostake")])
        experiment_overrides = {
            key: experiment[key]
            for key in EXPERIMENT_OVERRIDE_KEYS
            if key in experiment and key not in DIMENSION_KEYS
        }
        dimensions = {
            key: as_list(experiment[key])
            for key in DIMENSION_KEYS
            if key in experiment and key != "attack_mode"
        }
        if "attack_mode" in experiment:
            dimensions["attack_mode"] = as_list(experiment["attack_mode"])

        keys = list(dimensions.keys())
        for values in itertools.product(*(dimensions[key] for key in keys)):
            combo = dict(zip(keys, values))
            for protocol_variant in protocols:
                proto = protocol_cli(protocol_variant)
                for seed_index, seed_value in enumerate(seeds):
                    run = dict(defaults)
                    run.update(experiment_overrides)
                    run.update(combo)
                    run.update(proto)
                    if "eta_bonus_product" in run:
                        run["eta"] = float(run["eta_bonus_product"])
                        run["bonus_cap"] = 1.0
                    run.setdefault("attack_mode", "none")
                    run.setdefault("adversary_stake_fraction", 0.0)
                    run.setdefault("adversary_placement", "random")
                    run.setdefault("padding_identities", 0)
                    run.setdefault("attack_tx_rate_multiplier", 0.0)
                    run.setdefault("unstable_fraction", 0.0)
                    run.setdefault("offline_probability", 0.5)
                    run.update(seed_bundle(seed_value))
                    run["suite"] = suite
                    run["experiment"] = name
                    run["seed_index"] = seed_index
                    run["seed_value"] = seed_value

                    varied = [name, run["protocol_label"], f"seed{seed_index}"]
                    for key in keys:
                        varied.append(f"{key}-{slug(run[key])}")
                    for key in sorted(experiment_overrides):
                        if defaults.get(key) != run.get(key):
                            varied.append(f"{RUN_ID_KEY_ALIASES.get(key, key)}-{slug(run[key])}")
                    run_id = "_".join(slug(part) for part in varied)
                    run["run_id"] = run_id
                    run["output_dir"] = str(RAW_ROOT / suite / name / run_id)
                    runs.append(run)
    return runs


def filter_runs(
    runs: List[Dict[str, Any]],
    protocols: Iterable[str] | None = None,
    seed_indices: Iterable[int] | None = None,
    tx_rates: Iterable[float] | None = None,
    attack_tx_rate_multipliers: Iterable[float] | None = None,
) -> List[Dict[str, Any]]:
    protocol_set = set(protocols or [])
    seed_set = set(seed_indices or [])
    tx_rate_set = set(tx_rates or [])
    attack_tx_rate_multiplier_set = set(attack_tx_rate_multipliers or [])

    filtered = []
    for run in runs:
        if protocol_set and run.get("protocol_label") not in protocol_set and run.get("protocol") not in protocol_set:
            continue
        if seed_set and int(run.get("seed_index", -1)) not in seed_set:
            continue
        if tx_rate_set and float(run.get("tx_rate", -1)) not in tx_rate_set:
            continue
        if attack_tx_rate_multiplier_set and float(run.get("attack_tx_rate_multiplier", -1)) not in attack_tx_rate_multiplier_set:
            continue
        filtered.append(run)
    return filtered


def command_for_run(binary: str, run: Dict[str, Any]) -> List[str]:
    cmd = [str(ROOT / binary) if not os.path.isabs(binary) else binary]
    cmd.extend(["--consensus", str(run["protocol"])])
    cmd.extend(["--run-id", run["run_id"], "--output-dir", run["output_dir"]])
    for key, flag in CLI_KEYS.items():
        if key in run:
            cmd.extend([flag, str(run[key])])
    for key in [
        "graph_seed",
        "wallet_seed",
        "workload_seed",
        "election_seed",
        "failure_seed",
        "attack_seed",
    ]:
        cmd.extend([f"--{key.replace('_', '-')}", str(run[key])])
    if run.get("real_time"):
        cmd.append("--real-time")
    return cmd


def write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True))


def read_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def summary_reaches_expected_epochs(summary_path: Path, run: Dict[str, Any]) -> bool:
    completed_epochs, expected_epochs = summary_epoch_counts(summary_path, run)
    return expected_epochs > 0 and completed_epochs >= expected_epochs


def summary_epoch_counts(summary_path: Path, run: Dict[str, Any]) -> tuple[int, int]:
    summary = read_json(summary_path)
    try:
        completed_epochs = int(summary.get("completed_epochs", -1))
        expected_epochs = int(run.get("max_epochs", 0))
    except (TypeError, ValueError):
        return -1, 0
    return completed_epochs, expected_epochs


def run_one(binary: str, run: Dict[str, Any], timeout: int, force: bool) -> Dict[str, Any]:
    out_dir = Path(run["output_dir"])
    summary_path = out_dir / "run_summary.json"
    config_path = out_dir / "run_config.json"
    status_path = out_dir / "runner_status.json"
    meta_path = out_dir / "experiment_meta.json"
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(meta_path, run)

    cmd = command_for_run(binary, run)
    previous_status = {}
    if status_path.exists():
        previous_status = read_json(status_path)
    if (
        summary_path.exists()
        and config_path.exists()
        and previous_status.get("status") == "ok"
        and summary_reaches_expected_epochs(summary_path, run)
        and not force
    ):
        status = {
            "run_id": run["run_id"],
            "experiment": run["experiment"],
            "status": "ok",
            "runner_action": "skipped_existing",
            "cmd": cmd,
            "output_dir": str(out_dir),
        }
        write_json(status_path, status)
        return status

    started = time.time()
    log_path = out_dir / "run.log"
    status = {
        "run_id": run["run_id"],
        "experiment": run["experiment"],
        "status": "running",
        "cmd": cmd,
        "output_dir": str(out_dir),
        "timeout_seconds": timeout,
    }
    write_json(status_path, status)
    summary_path.unlink(missing_ok=True)
    try:
        with log_path.open("w") as log_file:
            env = os.environ.copy()
            env.setdefault("TOPOSTAKE_LOG_LEVEL", "off")
            completed = subprocess.run(
                cmd,
                cwd=ROOT,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                env=env,
                timeout=timeout,
                check=False,
            )
        status["exit_code"] = completed.returncode
        completed_epochs, expected_epochs = summary_epoch_counts(summary_path, run)
        complete = expected_epochs > 0 and completed_epochs >= expected_epochs
        status["completed_epochs"] = completed_epochs
        status["expected_epochs"] = expected_epochs
        status["status"] = (
            "ok"
            if completed.returncode == 0
            and summary_path.exists()
            and config_path.exists()
            and complete
            else "failed"
        )
        if completed.returncode == 0 and summary_path.exists() and config_path.exists() and not complete:
            status["failure_reason"] = "incomplete_epochs"
    except subprocess.TimeoutExpired:
        status["status"] = "timeout"
        status["exit_code"] = None
    finally:
        status["duration_seconds"] = round(time.time() - started, 3)
        write_json(status_path, status)
    return status


def build_if_needed(spec: Dict[str, Any], no_build: bool) -> None:
    if no_build:
        return
    build_command = spec.get("build_command")
    if not build_command:
        return
    subprocess.run(build_command, cwd=ROOT, check=True)


def append_failed_log(statuses: List[Dict[str, Any]]) -> None:
    PROCESSED_ROOT.mkdir(parents=True, exist_ok=True)
    failed = [status for status in statuses if status["status"] in {"failed", "timeout"}]
    if not failed:
        return
    path = PROCESSED_ROOT / "failed_runs.log"
    with path.open("a") as handle:
        for status in failed:
            handle.write(json.dumps(status, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="experiments/configs/main.yaml")
    parser.add_argument("--only", action="append", help="Run only this experiment group")
    parser.add_argument("--protocol", action="append", help="Run only this protocol/protocol label")
    parser.add_argument("--seed-index", action="append", type=int, help="Run only this zero-based seed index")
    parser.add_argument("--tx-rate", action="append", type=float, help="Run only this input transaction rate")
    parser.add_argument("--attack-tx-rate-multiplier", action="append", type=float, help="Run only this attack transaction multiplier")
    parser.add_argument("--max-parallel", type=int)
    parser.add_argument("--timeout-seconds", type=int)
    parser.add_argument("--force", action="store_true", help="Rerun even if summaries exist")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-build", action="store_true")
    args = parser.parse_args()

    spec_path = (ROOT / args.config).resolve()
    spec = load_yaml(spec_path)
    runs = expand_runs(spec, args.only)
    runs = filter_runs(
        runs,
        args.protocol,
        args.seed_index,
        args.tx_rate,
        args.attack_tx_rate_multiplier,
    )
    max_parallel = args.max_parallel or int(spec.get("max_parallel", 1))
    timeout = args.timeout_seconds or int(spec.get("timeout_seconds", 600))
    binary = spec.get("binary", "target/release/topostake")

    print(f"Loaded {len(runs)} runs from {spec_path.relative_to(ROOT)}")
    if args.dry_run:
        for run in runs:
            print(" ".join(command_for_run(binary, run)))
        return 0

    build_if_needed(spec, args.no_build)

    statuses: List[Dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_parallel) as executor:
        futures = [
            executor.submit(run_one, binary, run, timeout, args.force)
            for run in runs
        ]
        for future in concurrent.futures.as_completed(futures):
            status = future.result()
            statuses.append(status)
            print(
                f"[{status['status']}] {status['experiment']} {status['run_id']} "
                f"({status.get('duration_seconds', 0)}s)"
            )

    append_failed_log(statuses)
    failures = [s for s in statuses if s["status"] in {"failed", "timeout"}]
    print(f"Finished {len(statuses)} runs: {len(failures)} failed/timeouts")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
