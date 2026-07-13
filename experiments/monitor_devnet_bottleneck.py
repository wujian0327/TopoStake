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

import requests


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
    service_re = re.compile(r"^[0-9a-f]{12}\s+(\S+)\s+(.*)$")
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


def rpc(port: int, method: str, params: list[Any] | None = None) -> Any:
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
    response = requests.get(url, timeout=3)
    response.raise_for_status()
    return response.json()


def docker_stats(enclave_uuid: str) -> list[dict[str, str]]:
    output = subprocess.check_output(
        ["docker", "stats", "--no-stream", "--format", "{{json .}}"],
        text=True,
    )
    rows = []
    for line in output.splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        identity = f"{row.get('Name', '')} {row.get('ID', '')}".lower()
        if not enclave_uuid or enclave_uuid in identity:
            rows.append(row)
    return rows


def sample(
    enclave: str,
    enclave_uuid: str,
    ports: dict[str, list[tuple[int, int]]],
) -> dict[str, Any]:
    now = time.time()
    out: dict[str, Any] = {
        "ts": now,
        "enclave": enclave,
        "enclave_uuid": enclave_uuid,
        "docker": docker_stats(enclave_uuid),
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
    if not enclave_uuid:
        raise RuntimeError("failed to identify enclave UUID for Docker resource isolation")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + args.duration
    with output.open("w") as handle:
        while time.monotonic() < deadline:
            record = sample(args.enclave, enclave_uuid, ports)
            handle.write(json.dumps(record, sort_keys=True) + "\n")
            handle.flush()
            time.sleep(args.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
