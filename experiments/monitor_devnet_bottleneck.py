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


def parse_client_service_ids(inspect_text: str) -> dict[str, str]:
    services = {}
    service_re = re.compile(
        r"^\s*([0-9a-f]{12})\s+(\S+)\s+",
        re.IGNORECASE,
    )
    for line in inspect_text.splitlines():
        match = service_re.match(line)
        if match and CLIENT_SERVICE_RE.fullmatch(match.group(2)):
            services[match.group(2)] = match.group(1).lower()
    return dict(sorted(services.items()))


def parse_client_services(inspect_text: str) -> list[str]:
    return list(parse_client_service_ids(inspect_text))


def client_kind(service_name: str) -> str:
    if service_name.startswith("el-"):
        return "el"
    if service_name.startswith("cl-"):
        return "cl"
    return "unknown"


def container_label_values(metadata: dict[str, Any]) -> set[str]:
    labels = metadata.get("Config", {}).get("Labels", {})
    if not isinstance(labels, dict):
        return set()
    return {str(value).strip().lower() for value in labels.values()}


def discover_client_containers(
    service_ids: dict[str, str],
    enclave: str,
    enclave_uuid: str,
) -> dict[str, str]:
    output = subprocess.check_output(
        ["docker", "ps", "--no-trunc", "--format", "{{json .}}"],
        text=True,
    )
    rows = [json.loads(line) for line in output.splitlines() if line.strip()]
    ids = [str(row.get("ID", "")) for row in rows if row.get("ID")]
    inspected = []
    if ids:
        inspected = json.loads(
            subprocess.check_output(["docker", "inspect", *ids], text=True)
        )

    containers: dict[str, str] = {}
    errors = []
    target_values = {
        value.lower() for value in (enclave, enclave_uuid) if value
    }
    for service_name, service_id in service_ids.items():
        id_candidates = []
        name_candidates = []
        for metadata in inspected:
            container_id = str(metadata.get("Id", ""))
            labels = container_label_values(metadata)
            if not container_id:
                continue
            if service_id in labels:
                id_candidates.append(container_id)
            if service_name.lower() in labels and labels.intersection(target_values):
                name_candidates.append(container_id)
        selected = id_candidates or name_candidates
        if len(selected) != 1:
            errors.append(
                f"{service_name}[{service_id}]="
                f"{len(id_candidates)} uuid candidates/"
                f"{len(name_candidates)} name+enclave candidates"
            )
            continue
        containers[selected[0]] = service_name

    if errors:
        label_keys = sorted(
            {
                str(key)
                for metadata in inspected
                for key in (
                    metadata.get("Config", {}).get("Labels", {}) or {}
                )
            }
        )
        raise RuntimeError(
            "failed to map Kurtosis client services to Docker containers: "
            + ",".join(errors)
            + f"; available_label_keys={label_keys}"
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

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("")
    inspect_text = kurtosis_inspect(args.enclave)
    ports = parse_ports(inspect_text)
    enclave_uuid = parse_enclave_uuid(inspect_text)
    service_ids = parse_client_service_ids(inspect_text)
    if not service_ids:
        raise RuntimeError("failed to discover EL/CL service UUIDs from Kurtosis inspect")
    containers = discover_client_containers(
        service_ids,
        args.enclave,
        enclave_uuid,
    )
    print(
        json.dumps(
            {
                "enclave": args.enclave,
                "enclave_uuid": enclave_uuid,
                "client_service_ids": service_ids,
                "client_containers": containers,
            },
            sort_keys=True,
        ),
        flush=True,
    )
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
