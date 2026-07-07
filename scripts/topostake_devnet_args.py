#!/usr/bin/env python3
"""Generate Kurtosis ethereum-package args for TopoStake devnet experiments."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PUBLIC_REGISTRY = ROOT / "results" / "processed" / "topostake_relay_key_registry.json"
DEFAULT_PRIVATE_REGISTRY = ROOT / "results" / "raw" / "topostake_relay_keys_private.json"


def compact_json(value: Dict[str, Any]) -> str:
    return json.dumps(value, separators=(",", ":"))


def q(value: str) -> str:
    return "'" + value + "'"


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text())


def el_rpc_registry(count: int) -> Dict[str, Any]:
    return {
        "endpoints": [
            {
                "cl_service_name": f"cl-{index + 1}-lighthouse-geth",
                "el_rpc_url": f"http://el-{index + 1}-geth-lighthouse:8545",
            }
            for index in range(count)
        ]
    }


def write_args(args: argparse.Namespace) -> None:
    lines: List[str] = []
    lines.extend(
        [
            "participants:",
            "  - el_type: geth",
            "    el_image: topostake/geth:dev",
            "    el_extra_params:",
            (
                '      - "--http.api=admin,debug,eth,net,web3,txpool,topostake"'
                if args.mode == "topostake"
                else '      - "--http.api=admin,debug,eth,net,web3,txpool"'
            ),
            '      - "--nodiscover"',
            f'      - "--maxpeers={args.maxpeers}"',
            '      - "--bootnodes="',
        ]
    )

    if args.mode == "topostake":
        private_registry = load_json(args.private_registry)
        public_registry = load_json(args.public_registry)
        lines.extend(
            [
                "    el_extra_env_vars:",
                f'      TOPOSTAKE_CHAIN_ID: "{args.chain_id}"',
                '      TOPOSTAKE_RELAY_EPOCH: "0"',
                '      TOPOSTAKE_FEE_ESCROW: "1"',
                f"      TOPOSTAKE_RELAY_PRIVATE_REGISTRY_JSON: {q(compact_json(private_registry))}",
            ]
        )
    lines.extend(
        [
            "    cl_type: lighthouse",
            "    cl_image: topostake/lighthouse:dev",
        ]
    )
    if args.mode == "topostake":
        public_registry = load_json(args.public_registry)
        rpc_registry = el_rpc_registry(args.count)
        lines.extend(
            [
                "    cl_extra_env_vars:",
                f"      TOPOSTAKE_RELAY_PUBLIC_REGISTRY_JSON: {q(compact_json(public_registry))}",
                f"      TOPOSTAKE_EL_RPC_REGISTRY_JSON: {q(compact_json(rpc_registry))}",
                '      TOPOSTAKE_TX_EVIDENCE_GRAFFITI_COMMITMENT: "1"',
                '      TOPOSTAKE_FORK_EPOCH: "0"',
                f'      TOPOSTAKE_ETA_SCALED: "{args.eta_scaled}"',
                '      TOPOSTAKE_EVIDENCE_FINALITY_DEPTH: "1"',
            ]
        )
    lines.extend(
        [
            f"    count: {args.count}",
            f"    validator_count: {args.validator_count}",
            "    prometheus_config:",
            "      scrape_interval: 15s",
            "      labels:",
            f"        experiment: {args.label}",
            "",
            "network_params:",
            "  network: kurtosis",
            f'  network_id: "{args.chain_id}"',
            "  seconds_per_slot: 3",
            "  slot_duration_ms: 3000",
            "  genesis_delay: 20",
            "  genesis_gaslimit: 60000000",
            f"  num_validator_keys_per_node: {args.validator_count}",
            "  validator_balance: 32",
            "  fulu_fork_epoch: 18446744073709551615",
            "  preset: minimal",
        ]
    )
    if args.mode == "topostake":
        lines.extend(
            [
                "",
                "ethereum_genesis_generator_params:",
                "  extra_env:",
                "    TOPOSTAKE_CONFIG_YAML: |",
                "      TOPOSTAKE_CONFIG:",
                '        TOPOSTAKE_FORK_EPOCH: "0"',
                f'        ETA_SCALED: "{args.eta_scaled}"',
                '        BONUS_CAP_SCALED: "1000000000"',
                '        EVIDENCE_FINALITY_DEPTH: "1"',
                '        MAX_PATH_EVIDENCE_LEN: "32"',
                '        MAX_PATHS_PER_BLOCK: "1024"',
            ]
        )
    lines.extend(
        [
            "",
            "additional_services:",
            "  - prometheus",
            "  - grafana",
            "",
            "prometheus_params:",
            '  storage_tsdb_retention_time: "1d"',
            '  storage_tsdb_retention_size: "512MB"',
            "",
            "ethereum_metrics_exporter_enabled: true",
            "global_log_level: info",
            "",
        ]
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines))
    print(f"wrote {args.out}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["baseline", "topostake"], required=True)
    parser.add_argument("--count", type=int, default=8)
    parser.add_argument("--validator-count", type=int, default=16)
    parser.add_argument("--chain-id", type=int, default=7_032_030)
    parser.add_argument("--maxpeers", type=int, default=8)
    parser.add_argument("--eta-scaled", type=int, default=1_000_000_000)
    parser.add_argument("--label", default="topostake-devnet-8node-overhead")
    parser.add_argument("--public-registry", type=Path, default=DEFAULT_PUBLIC_REGISTRY)
    parser.add_argument("--private-registry", type=Path, default=DEFAULT_PRIVATE_REGISTRY)
    parser.add_argument("--out", type=Path, required=True)
    write_args(parser.parse_args())


if __name__ == "__main__":
    main()
