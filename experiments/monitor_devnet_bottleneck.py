#!/usr/bin/env python3
"""Sample Kurtosis devnet resource and chain state during a workload run."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any


CLIENT_SERVICE_RE = re.compile(
    r"^(?:el-\d+-geth-lighthouse|cl-\d+-lighthouse-geth)$"
)


def kurtosis_inspect(enclave: str) -> str:
    env = dict(os.environ)
    env["XDG_DATA_HOME"] = "/tmp/kurtosis-data"
    return subprocess.check_output(
        ["kurtosis", "enclave", "inspect", enclave],
        text=True,
        env=env,
    )


def parse_ports(inspect_text: str) -> dict[str, list[tuple[int, int]]]:
    current = ""
    ports: dict[str, list[tuple[int, int]]] = {"el": [], "cl": []}
    service_re = re.compile(r"^\s*[0-9a-f]{12}\s+(\S+)\s+(.*)$")
    port_re = re.compile(r"([\w-]+):\s+\d+/(?:tcp|udp)\s+->\s+(?:http://)?127\.0\.0\.1:(\d+)")
    for line in inspect_text.splitlines():
        match = service_re.match(line)
        if match:
            current = match.group(1)
            tail = match.group(2)
        elif current:
            tail = line.strip()
        else:
            continue
        port_match = port_re.search(tail)
        if not port_match:
            continue
        port_name, port = port_match.groups()
        el_match = re.match(r"el-(\d+)-geth-lighthouse", current)
        cl_match = re.match(r"cl-(\d+)-lighthouse-geth", current)
        if el_match and port_name == "rpc":
            ports["el"].append((int(el_match.group(1)), int(port)))
        elif cl_match and port_name == "http":
            ports["cl"].append((int(cl_match.group(1)), int(port)))
    ports["el"].sort()
    ports["cl"].sort()
    return ports


def parse_enclave_uuid(inspect_text: str) -> str:
    match = re.search(r"^UUID:\s+([0-9a-f]+)\s*$", inspect_text, re.MULTILINE | re.IGNORECASE)
    return match.group(1).lower() if match else ""


def parse_client_services(inspect_text: str) -> list[str]:
    services = []
    service_re = re.compile(r"^\s*[0-9a-f]{12}\s+(\S+)\s+", re.IGNORECASE)
    for line in inspect_text.splitlines():
        match = service_re.match(line)
        if match and CLIENT_SERVICE_RE.fullmatch(match.group(1)):
            services.append(match.group(1))
    return sorted(set(services))


def client_kind(service_name: str) -> str:
    if service_name.startswith("el-"):
        return "el"
    if service_name.startswith("cl-"):
        return "cl"
    return "unknown"


def service_in_metadata(metadata: Any, service_names: list[str]) -> str | None:
    encoded = json.dumps(metadata, sort_keys=True).lower()
    return next((name for name in service_names if name.lower() in encoded), None)


def metadata_matches_target(metadata: Any, enclave: str, enclave_uuid: str) -> bool:
    encoded = json.dumps(metadata, sort_keys=True).lower()
    identities = [value.lower() for value in (enclave, enclave_uuid) if value]
    return any(identity in encoded for identity in identities)


def discover_client_containers(
    service_names: list[str],
    enclave: str,
    enclave_uuid: str,
) -> dict[str, str]:
    output = subprocess.check_output(
        ["docker", "ps", "--no-trunc", "--format", "{{json .}}"],
        text=True,
    )
    rows = [json.loads(line) for line in output.splitlines() if line.strip()]
    ids = [str(row.get("ID", "")) for row in rows if row.get("ID")]
    inspected_by_id = {}
    if ids:
        inspected = json.loads(
            subprocess.check_output(["docker", "inspect", *ids], text=True)
        )
        inspected_by_id = {
            str(row.get("Id", "")): row for row in inspected if row.get("Id")
        }

    candidates: dict[str, list[tuple[str, dict[str, Any]]]] = {
        service_name: [] for service_name in service_names
    }
    for row in rows:
        container_id = str(row.get("ID", ""))
        inspected = next(
            (
                value
                for key, value in inspected_by_id.items()
                if key.startswith(container_id) or container_id.startswith(key)
            ),
            {},
        )
        metadata = {"docker_ps": row, "docker_inspect": inspected}
        service_name = service_in_metadata(metadata, service_names)
        if container_id and service_name:
            candidates[service_name].append((container_id, metadata))

    containers: dict[str, str] = {}
    errors = []
    for service_name, service_candidates in candidates.items():
        target_candidates = [
            item
            for item in service_candidates
            if metadata_matches_target(item[1], enclave, enclave_uuid)
        ]
        selected = target_candidates or service_candidates
        if len(selected) != 1:
            errors.append(f"{service_name}={len(selected)} candidates")
            continue
        containers[selected[0][0]] = service_name

    if errors:
        raise RuntimeError(
            "failed to map Kurtosis client services to Docker containers: "
            + ",".join(errors)
        )
    return containers


def rpc(port: int, method: str, params: list[Any] | None = None) -> Any:
    import requests

    response = requests.post(
        f"http://127.0.0.1:{port}",
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or []},
        timeout=3,
    )
    response.raise_for_status()
    payload = response.json()
    if "error" in payload:
        raise RuntimeError(payload["error"])
    return payload["result"]


def get_json(url: str) -> dict[str, Any]:
    import requests

    response = requests.get(url, timeout=3)
    response.raise_for_status()
    return response.json()


def docker_stats(containers: dict[str, str]) -> list[dict[str, str]]:
    if not containers:
        return []
    output = subprocess.check_output(
        [
            "docker",
            "stats",
            "--no-stream",
            "--format",
            "{{json .}}",
            *containers,
        ],
        text=True,
    )
    rows = []
    for line in output.splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        observed_id = str(row.get("ID", ""))
        container_id = next(
            (
                candidate
                for candidate in containers
                if candidate.startswith(observed_id) or observed_id.startswith(candidate)
            ),
            "",
        )
        if not container_id:
            continue
        service_name = containers[container_id]
        row["TopoStakeService"] = service_name
        row["TopoStakeKind"] = client_kind(service_name)
        rows.append(row)
    return rows


def sample(
    enclave: str,
    enclave_uuid: str,
    containers: dict[str, str],
    ports: dict[str, list[tuple[int, int]]],
) -> dict[str, Any]:
    now = time.time()
    out: dict[str, Any] = {
        "ts": now,
        "enclave": enclave,
        "enclave_uuid": enclave_uuid,
        "client_containers": containers,
        "docker": docker_stats(containers),
        "el": [],
        "cl": [],
    }
    for index, port in ports["el"]:
        item: dict[str, Any] = {"index": index, "port": port}
        try:
            block = rpc(port, "eth_blockNumber")
            peers = rpc(port, "net_peerCount")
            txpool = rpc(port, "txpool_status")
            item.update(
                {
                    "block": int(block, 16),
                    "peers": int(peers, 16),
                    "pending": int(txpool.get("pending", "0x0"), 16),
                    "queued": int(txpool.get("queued", "0x0"), 16),
                }
            )
        except Exception as exc:
            item["error"] = str(exc)
        out["el"].append(item)
    for index, port in ports["cl"]:
        item = {"index": index, "port": port}
        try:
            head = get_json(f"http://127.0.0.1:{port}/eth/v1/beacon/headers/head")
            finality = get_json(f"http://127.0.0.1:{port}/eth/v1/beacon/states/head/finality_checkpoints")
            item.update(
                {
                    "head_slot": int(head["data"]["header"]["message"]["slot"]),
                    "finalized_epoch": int(finality["data"]["finalized"]["epoch"]),
                }
            )
        except Exception as exc:
            item["error"] = str(exc)
        out["cl"].append(item)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--enclave", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--duration", type=float, default=420.0)
    args = parser.parse_args()

    inspect_text = kurtosis_inspect(args.enclave)
    ports = parse_ports(inspect_text)
    enclave_uuid = parse_enclave_uuid(inspect_text)
    service_names = parse_client_services(inspect_text)
    if not service_names:
        raise RuntimeError("failed to discover EL/CL service names from Kurtosis inspect")
    containers = discover_client_containers(
        service_names,
        args.enclave,
        enclave_uuid,
    )
    print(
        json.dumps(
            {
                "enclave": args.enclave,
                "enclave_uuid": enclave_uuid,
                "client_containers": containers,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + args.duration
    with output.open("w") as handle:
        while time.monotonic() < deadline:
            record = sample(args.enclave, enclave_uuid, containers, ports)
            handle.write(json.dumps(record, sort_keys=True) + "\n")
            handle.flush()
            time.sleep(args.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
