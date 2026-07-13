from __future__ import annotations

import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "experiments"))

from run_frozen_devnet_experiments import (  # noqa: E402
    RunSpec,
    load_config,
    measurement_quality_checks,
    parse_bytes,
    specs_from_config,
    summarize_resources,
)
from monitor_devnet_bottleneck import (  # noqa: E402
    container_label_values,
    discover_client_containers,
    parse_client_service_ids,
    parse_client_services,
)


def args(**overrides: str | None) -> argparse.Namespace:
    values = {
        "variants": None,
        "seeds": None,
        "nodes": None,
        "loads": None,
        "topologies": None,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def spec(variant: str = "topostake") -> RunSpec:
    return RunSpec(
        suite="test",
        variant=variant,
        nodes=4,
        load_tx_per_slot=8,
        topology="ring",
        seed=0,
        validators_per_node=1,
        seconds_per_slot=3,
        slots_per_epoch=8,
        warmup_epochs=1,
        measurement_epochs=1,
        resource_interval=2.0,
        receipt_timeout=60,
        finality_timeout=60,
    )


class FrozenDevnetExperimentTests(unittest.TestCase):
    def test_kurtosis_client_services_are_discovered_from_inspect(self) -> None:
        inspect_text = """
UUID: 72e82fd99b0f
  aaaaaaaaaaaa el-1-geth-lighthouse rpc: 8545/tcp -> 127.0.0.1:12345
  bbbbbbbbbbbb cl-1-lighthouse-geth http: 5052/tcp -> 127.0.0.1:23456
  cccccccccccc prometheus http: 9090/tcp -> 127.0.0.1:34567
"""
        self.assertEqual(
            parse_client_services(inspect_text),
            ["cl-1-lighthouse-geth", "el-1-geth-lighthouse"],
        )
        self.assertEqual(
            parse_client_service_ids(inspect_text),
            {
                "cl-1-lighthouse-geth": "bbbbbbbbbbbb",
                "el-1-geth-lighthouse": "aaaaaaaaaaaa",
            },
        )

    def test_only_exact_docker_label_values_are_used(self) -> None:
        metadata = {
            "Config": {
                "Labels": {
                    "service-id": "aaaaaaaaaaaa",
                    "unrelated-config": "cl-1-lighthouse-geth,cl-2-lighthouse-geth",
                }
            }
        }
        self.assertEqual(
            container_label_values(metadata),
            {
                "aaaaaaaaaaaa",
                "cl-1-lighthouse-geth,cl-2-lighthouse-geth",
            },
        )

    def test_container_discovery_uses_exact_service_uuid_labels(self) -> None:
        docker_ps = "\n".join(
            [
                json.dumps({"ID": "container-el"}),
                json.dumps({"ID": "container-cl"}),
            ]
        )
        docker_inspect = json.dumps(
            [
                {
                    "Id": "container-el",
                    "Config": {
                        "Labels": {
                            "service-id": "aaaaaaaaaaaa",
                            "config": "cl-1-lighthouse-geth,cl-2-lighthouse-geth",
                        }
                    },
                },
                {
                    "Id": "container-cl",
                    "Config": {"Labels": {"service-id": "bbbbbbbbbbbb"}},
                },
            ]
        )
        with patch(
            "monitor_devnet_bottleneck.subprocess.check_output",
            side_effect=[docker_ps, docker_inspect],
        ):
            containers = discover_client_containers(
                {
                    "el-1-geth-lighthouse": "aaaaaaaaaaaa",
                    "cl-1-lighthouse-geth": "bbbbbbbbbbbb",
                },
                "ts-fv1-test",
                "72e82fd99b0f",
            )
        self.assertEqual(
            containers,
            {
                "container-el": "el-1-geth-lighthouse",
                "container-cl": "cl-1-lighthouse-geth",
            },
        )

    def test_pilot_matrix_has_all_five_variants_and_two_loads(self) -> None:
        config = load_config(ROOT / "experiments/configs/frozen_v1_devnet_pilot.yaml")
        specs = specs_from_config(config, args())
        self.assertEqual(len(specs), 10)
        self.assertEqual({item.variant for item in specs}, {
            "baseline", "pathobs", "fee_only", "bonus_only", "topostake"
        })
        self.assertEqual({item.load_tx_per_slot for item in specs}, {8, 32})

    def test_matrix_overrides_are_applied(self) -> None:
        config = load_config(ROOT / "experiments/configs/frozen_v1_devnet_main.yaml")
        specs = specs_from_config(
            config,
            args(variants="baseline,topostake", seeds="9", loads="8"),
        )
        self.assertEqual(len(specs), 2)
        self.assertEqual({item.seed for item in specs}, {9})

    def test_resource_summary_parses_docker_units(self) -> None:
        records = [
            {
                "ts": 1,
                "docker": [
                    {
                        "Name": "el-1-geth-lighthouse--abc",
                        "CPUPerc": "10%",
                        "MemUsage": "1MiB / 2GiB",
                        "NetIO": "1MB / 2MB",
                    },
                    {
                        "Name": "cl-1-lighthouse-geth--abc",
                        "CPUPerc": "20%",
                        "MemUsage": "2MiB / 2GiB",
                        "NetIO": "3MB / 4MB",
                    },
                ],
            },
            {
                "ts": 2,
                "docker": [
                    {
                        "Name": "el-1-geth-lighthouse--abc",
                        "CPUPerc": "12%",
                        "MemUsage": "2MiB / 2GiB",
                        "NetIO": "2MB / 3MB",
                    },
                    {
                        "Name": "cl-1-lighthouse-geth--abc",
                        "CPUPerc": "22%",
                        "MemUsage": "3MiB / 2GiB",
                        "NetIO": "5MB / 7MB",
                    },
                ],
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "resources.jsonl"
            path.write_text("\n".join(json.dumps(record) for record in records))
            summary = summarize_resources(path)
        self.assertEqual(summary["samples"], 2)
        self.assertEqual(summary["cpu_mean_percent"], 32.0)
        self.assertEqual(summary["network_rx_delta_bytes"], 3_000_000.0)
        self.assertEqual(parse_bytes("1.5 GiB"), 1.5 * 1024**3)

    def test_measurement_quality_requires_evidence_timing_off_baseline(self) -> None:
        blocks = {"encoding": "ssz", "count": 2}
        resources = {"samples": 2}
        prometheus = {"evidence_verify_count": 0}
        self.assertTrue(
            measurement_quality_checks(spec("baseline"), blocks, resources, prometheus)[
                "passed"
            ]
        )
        self.assertFalse(
            measurement_quality_checks(spec("topostake"), blocks, resources, prometheus)[
                "passed"
            ]
        )


if __name__ == "__main__":
    unittest.main()
