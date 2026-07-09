#!/usr/bin/env python3
"""Run reproducible TopoStake topology workloads against a Kurtosis devnet."""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import subprocess
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

import requests
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = ROOT / "results" / "raw" / "devnet_topology"
DEFAULT_PRIVATE_KEY = "0xbcdf20249abf0ed6d944c0288fad489e33f66b3960d9e6229c1cd214ed3bbe31"
DEFAULT_RECIPIENT = "0xE25583099BA105D9ec0A67f5Ae86D90e50036425"
DEFAULT_PREFUNDED_PRIVATE_KEYS = [
    "0xbcdf20249abf0ed6d944c0288fad489e33f66b3960d9e6229c1cd214ed3bbe31",
    "0x39725efee3fb28614de3bacaffe4cc4bd8c436257e2c8bb887c4b5c4be45e76d",
    "0x53321db7c1e331d93a11a41d16f004d7ff63972ec8ec7c25db329728ceeb1710",
    "0xab63b23eb7941c1251757e24b3d2350d2bc05c3c388d06f8fe6feafefb1e8c70",
    "0x5d2344259f42259f82d2c140aa66102ba89b57b4883ee441a8b312622bd42491",
    "0x27515f805127bebad2fb9b183508bdacb8c763da16f54e0678b16e8f28ef3fff",
    "0x7ff1a4c1d57e5e784d327c4c7651e952350bc271f156afb3d00d20f5ef924856",
    "0x3a91003acaf4c21b3953d94fa4a6db694fa69e5242b2e37be05dd82761058899",
    "0xbb1d0f125b4fb2bb173c318cdead45468474ca71474e2247776b2b4c0fa2d3f5",
    "0x850643a0224065ecce3882673c21f56bcf6eef86274cc21cadff15930b59fc8c",
    "0x94eb3102993b41ec55c241060f47daa0f6372e2e3ad7e91612ae36c364042e44",
    "0xdaf15504c22a352648a71ef2926334fe040ac1d5005019e09f6c979808024dc7",
    "0xeaba42282ad33c8ef2524f07277c03a776d98ae19f581990ce75becb7cfa1c23",
    "0x3fd98b5187bf6526734efaa644ffbb4e3670d66f5d0268ce0323ec09124bff61",
    "0x5288e2f440c7f0cb61a9be8afdeb4295f786383f96f5e35eb0c94ef103996b64",
    "0xf296c7802555da2a5a662be70e078cbd38b44f96f8615ae529da41122ce8db05",
]
TOPOSTAKE_METRICS = [
    "topostake_evidence_paths_total",
    "topostake_evidence_sources_total",
    "topostake_evidence_epoch_valid_paths",
    "topostake_evidence_epoch_invalid_paths",
    "topostake_evidence_epoch_duplicate_receivers",
    "topostake_evidence_epoch_scored_validators",
    "topostake_epoch_raw_contribution_scaled",
    "topostake_epoch_saturated_contribution_scaled",
    "topostake_epoch_score_scaled",
    "topostake_epoch_score_share_scaled",
    "topostake_selection_score_epoch",
    "topostake_proposer_score_scaled",
    "topostake_proposer_weight_scaled",
    "topostake_selected_proposer",
    "topostake_fee_settlement_records_total",
    "topostake_fee_settlement_amount_wei",
    "topostake_fee_validator_amount_wei",
    "topostake_fee_burned_amount_wei",
    "topostake_fee_conservation_violation",
]


Edge = Tuple[int, int]


@dataclass
class Endpoints:
    el_rpcs: List[str]
    cl_apis: List[str]
    prometheus: str | None


def rpc(url: str, method: str, params: Sequence[Any] | None = None) -> Any:
    response = requests.post(
        url,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": list(params or [])},
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()
    if "error" in payload:
        raise RuntimeError(f"{method} failed on {url}: {payload['error']}")
    return payload["result"]


def get_json(url: str) -> Dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
    assert last_error is not None
    raise last_error


def normalize_edges(edges: Iterable[Edge]) -> List[Edge]:
    normalized = {(min(a, b), max(a, b)) for a, b in edges if a != b}
    return sorted(normalized)


def generate_topology(n: int, kind: str, seed: int, degree: float, ba_m: int) -> List[Edge]:
    if n < 1:
        raise ValueError("n must be >= 1")
    rng = random.Random(seed)
    if kind == "linear":
        return [(i, i + 1) for i in range(n - 1)]
    if kind == "ring":
        return normalize_edges([(i, (i + 1) % n) for i in range(n)])
    if kind == "star":
        return [(0, i) for i in range(1, n)]
    if kind == "er":
        p = max(0.0, min(1.0, degree / max(1, n - 1)))
        edges = [(i, j) for i in range(n) for j in range(i + 1, n) if rng.random() < p]
        return ensure_connected(n, edges, rng)
    if kind == "random_regular":
        return random_degree_limited(n, max(1, round(degree)), rng)
    if kind == "ba":
        return barabasi_albert(n, max(1, ba_m), rng)
    raise ValueError(f"unknown topology kind: {kind}")


def ensure_connected(n: int, edges: Iterable[Edge], rng: random.Random) -> List[Edge]:
    edge_set = set(normalize_edges(edges))
    if n <= 1:
        return []
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for a, b in edge_set:
        union(a, b)
    components: Dict[int, List[int]] = defaultdict(list)
    for node in range(n):
        components[find(node)].append(node)
    groups = list(components.values())
    while len(groups) > 1:
        left = groups.pop()
        right = groups[-1]
        a = rng.choice(left)
        b = rng.choice(right)
        edge_set.add((min(a, b), max(a, b)))
        right.extend(left)
    return sorted(edge_set)


def random_degree_limited(n: int, degree: int, rng: random.Random) -> List[Edge]:
    edges = set((i, i + 1) for i in range(n - 1))
    degree = min(degree, max(1, n - 1))
    attempts = 0
    while attempts < n * n * 10:
        attempts += 1
        degrees = Counter()
        for a, b in edges:
            degrees[a] += 1
            degrees[b] += 1
        candidates = [node for node in range(n) if degrees[node] < degree]
        if len(candidates) < 2:
            break
        a, b = rng.sample(candidates, 2)
        edge = (min(a, b), max(a, b))
        if edge not in edges:
            edges.add(edge)
    return sorted(edges)


def barabasi_albert(n: int, m: int, rng: random.Random) -> List[Edge]:
    if n <= 1:
        return []
    m = min(m, n - 1)
    edges = set()
    degrees = [0 for _ in range(n)]
    edges.add((0, 1))
    degrees[0] += 1
    degrees[1] += 1
    for node in range(2, n):
        targets = set()
        while len(targets) < min(m, node):
            population = list(range(node))
            weights = [degrees[i] + 1 for i in population]
            targets.add(rng.choices(population, weights=weights, k=1)[0])
        for target in targets:
            edge = (min(node, target), max(node, target))
            edges.add(edge)
            degrees[node] += 1
            degrees[target] += 1
    return sorted(edges)


def parse_csv_urls(raw: str | None) -> List[str]:
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def discover_from_kurtosis(enclave: str) -> Endpoints:
    env = dict(os.environ)
    env["XDG_DATA_HOME"] = "/tmp/kurtosis-data"
    result = subprocess.run(
        ["kurtosis", "enclave", "inspect", enclave],
        check=True,
        text=True,
        capture_output=True,
        env=env,
    )
    return parse_kurtosis_inspect(result.stdout)


def parse_kurtosis_inspect(text: str) -> Endpoints:
    service_re = re.compile(r"^[0-9a-f]{12}\s+(\S+)\s+(.*)$")
    current = ""
    ports: Dict[str, Dict[str, str]] = defaultdict(dict)
    for line in text.splitlines():
        match = service_re.match(line)
        if match:
            current = match.group(1)
            tail = match.group(2)
        elif current:
            tail = line.strip()
        else:
            continue
        if not tail:
            continue
        port_match = re.search(r"([\w-]+):\s+\d+/(?:tcp|udp)\s+->\s+(?:http://)?127\.0\.0\.1:(\d+)", tail)
        if port_match:
            name, port = port_match.groups()
            ports[current][name] = f"http://127.0.0.1:{port}"
    el = [ports[name]["rpc"] for name in sorted(ports) if name.startswith("el-") and "rpc" in ports[name]]
    cl = [ports[name]["http"] for name in sorted(ports) if name.startswith("cl-") and "http" in ports[name]]
    prometheus = ports.get("prometheus", {}).get("http")
    if not el or not cl:
        raise RuntimeError("failed to discover EL/CL endpoints from kurtosis inspect output")
    return Endpoints(el, cl, prometheus)


def resolve_endpoints(args: argparse.Namespace) -> Endpoints:
    if args.enclave:
        discovered = discover_from_kurtosis(args.enclave)
    else:
        discovered = Endpoints([], [], None)
    el = parse_csv_urls(args.el_rpcs) or discovered.el_rpcs
    cl = parse_csv_urls(args.cl_apis) or discovered.cl_apis
    prometheus = args.prometheus or discovered.prometheus
    if not el:
        raise RuntimeError("no EL RPC endpoints supplied")
    if not cl:
        raise RuntimeError("no CL API endpoints supplied")
    return Endpoints(el, cl, prometheus)


def node_id_from_enode(enode: str) -> str:
    return enode.split("://", 1)[1].split("@", 1)[0]


def apply_topology(el_rpcs: List[str], edges: List[Edge], prune: bool) -> Dict[str, Any]:
    node_infos = [rpc(url, "admin_nodeInfo") for url in el_rpcs]
    enodes = [info["enode"] for info in node_infos]
    node_ids = [info["id"] for info in node_infos]
    target_neighbors = {i: set() for i in range(len(el_rpcs))}
    for a, b in edges:
        target_neighbors[a].add(b)
        target_neighbors[b].add(a)

    target_edges = normalize_edges(edges)
    if prune:
        for _ in range(8):
            remove_extra_peers(el_rpcs, enodes, node_ids, target_neighbors)
            for a, b in target_edges:
                rpc(el_rpcs[a], "admin_addPeer", [enodes[b]])
                rpc(el_rpcs[b], "admin_addPeer", [enodes[a]])
            time.sleep(2)
            graph = inspect_peer_graph(el_rpcs, enodes, target_edges, node_ids=node_ids)
            if graph["matches_target"]:
                return graph
        return graph

    for a, b in target_edges:
        rpc(el_rpcs[a], "admin_addPeer", [enodes[b]])
        rpc(el_rpcs[b], "admin_addPeer", [enodes[a]])

    time.sleep(2)
    return inspect_peer_graph(el_rpcs, enodes, target_edges, node_ids=node_ids)


def remove_extra_peers(
    el_rpcs: List[str],
    enodes: List[str],
    node_ids: List[str],
    target_neighbors: Dict[int, set[int]],
) -> None:
    index_by_id = {node_id: index for index, node_id in enumerate(node_ids)}
    for index, url in enumerate(el_rpcs):
        for peer in rpc(url, "admin_peers"):
            peer_index = index_by_id.get(peer.get("id", ""))
            if peer_index is None or peer_index not in target_neighbors[index]:
                peer_enode = peer.get("enode")
                if peer_enode:
                    rpc(url, "admin_removePeer", [peer_enode])
                if peer_index is not None:
                    rpc(el_rpcs[peer_index], "admin_removePeer", [enodes[index]])


def inspect_peer_graph(
    el_rpcs: List[str],
    enodes: List[str] | None = None,
    target_edges: List[Edge] | None = None,
    node_ids: List[str] | None = None,
) -> Dict[str, Any]:
    if enodes is None or node_ids is None:
        node_infos = [rpc(url, "admin_nodeInfo") for url in el_rpcs]
        enodes = [info["enode"] for info in node_infos]
        node_ids = [info["id"] for info in node_infos]
    index_by_id = {node_id: index for index, node_id in enumerate(node_ids)}
    observed = set()
    peer_counts = []
    peers_by_node = {}
    for index, url in enumerate(el_rpcs):
        peers = rpc(url, "admin_peers")
        peer_counts.append(len(peers))
        mapped = []
        for peer in peers:
            peer_index = index_by_id.get(peer.get("id", ""))
            if peer_index is not None:
                mapped.append(peer_index)
                observed.add((min(index, peer_index), max(index, peer_index)))
        peers_by_node[str(index)] = sorted(set(mapped))
    target = normalize_edges(target_edges or [])
    return {
        "peer_counts": peer_counts,
        "target_edges": target,
        "observed_edges": sorted(observed),
        "matches_target": sorted(observed) == target if target else None,
        "peers_by_node": peers_by_node,
        "enodes": enodes,
    }


def beacon_head(cl_api: str) -> Dict[str, int]:
    head = get_json(f"{cl_api}/eth/v1/beacon/headers/head")["data"]["header"]["message"]
    finality = get_json(f"{cl_api}/eth/v1/beacon/states/head/finality_checkpoints")["data"]
    return {
        "head_slot": int(head["slot"]),
        "finalized_epoch": int(finality["finalized"]["epoch"]),
        "justified_epoch": int(finality["current_justified"]["epoch"]),
    }


def beacon_genesis(cl_api: str) -> Dict[str, int]:
    data = get_json(f"{cl_api}/eth/v1/beacon/genesis")["data"]
    return {
        "genesis_time": int(data["genesis_time"]),
    }


def selected_private_keys(args: argparse.Namespace) -> List[str]:
    if args.sender_count < 1:
        raise ValueError("--sender-count must be resolved to at least one sender before workload starts")
    if args.private_keys:
        private_keys = [part.strip() for part in args.private_keys.split(",") if part.strip()]
    elif args.sender_count == 1 and args.private_key != DEFAULT_PRIVATE_KEY:
        private_keys = [args.private_key]
    else:
        private_keys = DEFAULT_PREFUNDED_PRIVATE_KEYS[: args.sender_count]
    if not private_keys:
        raise ValueError("at least one sender private key is required")
    if len(private_keys) < args.sender_count:
        raise ValueError(f"requested {args.sender_count} senders but only {len(private_keys)} private keys are available")
    return private_keys[: args.sender_count]


def run_workload(
    args: argparse.Namespace,
    endpoints: Endpoints,
    *,
    phase: str = "measurement",
    tx_count: int | None = None,
) -> Dict[str, Any]:
    from eth_account import Account

    private_keys = selected_private_keys(args)
    accounts = [Account.from_key(private_key) for private_key in private_keys]
    tx_count = args.tx_count if tx_count is None else tx_count
    txs: List[Dict[str, Any]] = []
    genesis = beacon_genesis(endpoints.cl_apis[0])
    genesis_time = genesis["genesis_time"]
    seconds_per_slot = args.seconds_per_slot
    nonce_w3 = Web3(Web3.HTTPProvider(endpoints.el_rpcs[0], request_kwargs={"timeout": 10}))
    nonce_w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    nonces = [nonce_w3.eth.get_transaction_count(account.address, "pending") for account in accounts]
    chain_id = nonce_w3.eth.chain_id
    first_schedule_monotonic = time.monotonic()
    last_receipt_monotonic = None
    send_workers = max(1, args.send_concurrency or len(endpoints.el_rpcs))
    receipt_workers = max(1, args.receipt_concurrency or len(endpoints.el_rpcs))

    def send_one(tx_record: Dict[str, Any]) -> Dict[str, Any]:
        account = accounts[tx_record["sender_index"]]
        origin = tx_record["origin"]
        w3 = Web3(Web3.HTTPProvider(endpoints.el_rpcs[origin], request_kwargs={"timeout": 10}))
        w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        tx = {
            "chainId": chain_id,
            "from": account.address,
            "to": Web3.to_checksum_address(args.recipient),
            "value": args.value_wei,
            "gas": 21000,
            "nonce": tx_record["nonce"],
            "maxFeePerGas": Web3.to_wei(args.max_fee_gwei, "gwei"),
            "maxPriorityFeePerGas": Web3.to_wei(args.priority_fee_gwei, "gwei"),
        }
        signed = account.sign_transaction(tx)
        raw_tx = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction")
        send_monotonic = time.monotonic()
        send_unix = time.time()
        tx_hash = send_raw_transaction_with_retry(w3, raw_tx, timeout_seconds=args.receipt_timeout).hex()
        tx_record.update(
            {
                "sender": account.address,
                "tx_hash": tx_hash,
                "send_unix": send_unix,
                "send_monotonic": send_monotonic,
                "send_slot_estimate": slot_for_timestamp(send_unix, genesis_time, seconds_per_slot),
            }
        )
        return tx_record

    futures = []
    with ThreadPoolExecutor(max_workers=send_workers) as executor:
        for index in range(tx_count):
            sender_index = index % len(accounts)
            origin = choose_origin(index, len(endpoints.el_rpcs), args.origin_mode, args.seed)
            tx_record = {
                "index": index,
                "phase": phase,
                "origin": origin,
                "sender_index": sender_index,
                "nonce": nonces[sender_index],
            }
            nonces[sender_index] += 1
            txs.append(tx_record)
            target_monotonic = first_schedule_monotonic + index * args.tx_interval_seconds
            sleep_seconds = target_monotonic - time.monotonic()
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)
            futures.append(executor.submit(send_one, tx_record))
        for future in as_completed(futures):
            future.result()

    txs.sort(key=lambda tx: tx["index"])
    first_send_monotonic = min((tx["send_monotonic"] for tx in txs if "send_monotonic" in tx), default=None)
    first_send_unix = min((tx["send_unix"] for tx in txs if "send_unix" in tx), default=None)
    last_send_monotonic = max((tx["send_monotonic"] for tx in txs if "send_monotonic" in tx), default=None)
    last_send_unix = max((tx["send_unix"] for tx in txs if "send_unix" in tx), default=None)

    def wait_receipt(tx_record: Dict[str, Any]) -> Dict[str, Any]:
        w3 = Web3(Web3.HTTPProvider(endpoints.el_rpcs[tx_record["origin"]], request_kwargs={"timeout": 10}))
        w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        receipt = wait_for_transaction_receipt_with_retry(w3, tx_record["tx_hash"], args.receipt_timeout)
        receipt_monotonic = time.monotonic()
        tx_record.update(receipt_fields(w3, receipt, tx_record, receipt_monotonic, genesis_time, seconds_per_slot))
        return tx_record

    if args.wait_receipts_after_send:
        with ThreadPoolExecutor(max_workers=receipt_workers) as executor:
            receipt_futures = [executor.submit(wait_receipt, tx_record) for tx_record in txs]
            for future in as_completed(receipt_futures):
                receipt_record = future.result()
                receipt_monotonic = receipt_record.get("receipt_monotonic")
                if receipt_monotonic is not None:
                    last_receipt_monotonic = max(last_receipt_monotonic or receipt_monotonic, receipt_monotonic)
    else:
        for tx_record in txs:
            receipt_record = wait_receipt(tx_record)
            receipt_monotonic = receipt_record.get("receipt_monotonic")
            if receipt_monotonic is not None:
                last_receipt_monotonic = max(last_receipt_monotonic or receipt_monotonic, receipt_monotonic)
    receipt_latencies = [
        tx["observed_receipt_latency_seconds"]
        for tx in txs
        if tx.get("status") == 1 and "observed_receipt_latency_seconds" in tx
    ]
    inclusion_delay_slots = [
        tx["inclusion_delay_slots"]
        for tx in txs
        if tx.get("status") == 1 and "inclusion_delay_slots" in tx
    ]
    inclusion_delay_seconds = [
        tx["inclusion_delay_seconds"]
        for tx in txs
        if tx.get("status") == 1 and "inclusion_delay_seconds" in tx
    ]
    receipt_elapsed = (
        last_receipt_monotonic - first_send_monotonic
        if first_send_monotonic is not None and last_receipt_monotonic is not None
        else 0.0
    )
    latest_inclusion_timestamp = max(
        (tx["included_block_timestamp"] for tx in txs if tx.get("status") == 1 and "included_block_timestamp" in tx),
        default=None,
    )
    inclusion_elapsed = (
        latest_inclusion_timestamp - first_send_unix
        if first_send_unix is not None and latest_inclusion_timestamp is not None
        else 0.0
    )
    send_elapsed = (
        last_send_monotonic - first_send_monotonic
        if first_send_monotonic is not None and last_send_monotonic is not None
        else 0.0
    )
    success_count = sum(1 for tx in txs if tx.get("status") == 1)
    origin_counts = {str(index): 0 for index in range(len(endpoints.el_rpcs))}
    success_origin_counts = {str(index): 0 for index in range(len(endpoints.el_rpcs))}
    for tx in txs:
        origin_key = str(tx["origin"])
        origin_counts[origin_key] = origin_counts.get(origin_key, 0) + 1
        if tx.get("status") == 1:
            success_origin_counts[origin_key] = success_origin_counts.get(origin_key, 0) + 1
    origin_values = list(origin_counts.values())
    return {
        "sender": accounts[0].address,
        "senders": [account.address for account in accounts],
        "sender_count": len(accounts),
        "origin_mode": args.origin_mode,
        "origin_node_count": len(endpoints.el_rpcs),
        "origin_counts": origin_counts,
        "success_origin_counts": success_origin_counts,
        "origin_count_min": min(origin_values) if origin_values else 0,
        "origin_count_max": max(origin_values) if origin_values else 0,
        "chain_id": chain_id,
        "genesis_time": genesis_time,
        "seconds_per_slot": seconds_per_slot,
        "phase": phase,
        "tx_count": tx_count,
        "success_count": success_count,
        "send_interval_seconds": args.tx_interval_seconds,
        "send_concurrency": send_workers,
        "receipt_concurrency": receipt_workers,
        "send_elapsed_seconds": send_elapsed,
        "actual_send_tps": (tx_count / send_elapsed) if send_elapsed > 0 else 0.0,
        "first_send_unix": first_send_unix or 0.0,
        "last_send_unix": last_send_unix or 0.0,
        "wait_receipts_after_send": args.wait_receipts_after_send,
        "receipt_elapsed_seconds": receipt_elapsed,
        "observed_receipt_throughput_tps": (success_count / receipt_elapsed) if receipt_elapsed > 0 else 0.0,
        "observed_receipt_latency_seconds": latency_summary(receipt_latencies),
        "inclusion_elapsed_seconds": inclusion_elapsed,
        "inclusion_throughput_tps": (success_count / inclusion_elapsed) if inclusion_elapsed > 0 else 0.0,
        "inclusion_delay_slots": latency_summary(inclusion_delay_slots),
        "inclusion_delay_seconds": latency_summary(inclusion_delay_seconds),
        "txs": txs,
    }


def wait_for_transaction_receipt_with_retry(w3: Web3, tx_hash: str, timeout_seconds: int) -> Any:
    deadline = time.monotonic() + timeout_seconds
    delay = 0.5
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            return w3.eth.wait_for_transaction_receipt(tx_hash, timeout=min(10, timeout_seconds))
        except Exception as exc:
            last_error = exc
            time.sleep(delay)
            delay = min(delay * 1.5, 5.0)
    raise TimeoutError(f"receipt not available for {tx_hash} after {timeout_seconds}s") from last_error


def get_block_with_retry(w3: Web3, block_number: int, timeout_seconds: int = 120) -> Any:
    deadline = time.monotonic() + timeout_seconds
    delay = 0.5
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            return w3.eth.get_block(block_number)
        except Exception as exc:
            last_error = exc
            time.sleep(delay)
            delay = min(delay * 1.5, 5.0)
    raise TimeoutError(f"block {block_number} not available after {timeout_seconds}s") from last_error


def send_raw_transaction_with_retry(w3: Web3, raw_tx: bytes, timeout_seconds: int) -> bytes:
    deadline = time.monotonic() + min(timeout_seconds, 60)
    delay = 0.25
    expected_hash = Web3.keccak(raw_tx)
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            return w3.eth.send_raw_transaction(raw_tx)
        except Exception as exc:
            message = str(exc).lower()
            if "already known" in message or "nonce too low" in message:
                return expected_hash
            last_error = exc
            time.sleep(delay)
            delay = min(delay * 1.5, 3.0)
    raise TimeoutError(f"raw transaction send failed after retries: {expected_hash.hex()}") from last_error


def receipt_fields(
    w3: Web3,
    receipt: Any,
    tx_record: Dict[str, Any],
    receipt_monotonic: float,
    genesis_time: int,
    seconds_per_slot: int,
) -> Dict[str, Any]:
    block = get_block_with_retry(w3, int(receipt.blockNumber))
    block_timestamp = int(block.timestamp)
    included_slot = slot_for_timestamp(block_timestamp, genesis_time, seconds_per_slot)
    send_slot = tx_record["send_slot_estimate"]
    inclusion_delay_seconds = max(0.0, block_timestamp - float(tx_record["send_unix"]))
    return {
        "status": int(receipt.status),
        "block_number": int(receipt.blockNumber),
        "included_block_timestamp": block_timestamp,
        "included_slot": included_slot,
        "inclusion_delay_slots": max(0, included_slot - send_slot),
        "inclusion_delay_seconds": inclusion_delay_seconds,
        "gas_used": int(receipt.gasUsed),
        "receipt_unix": time.time(),
        "receipt_monotonic": receipt_monotonic,
        "observed_receipt_latency_seconds": receipt_monotonic - tx_record["send_monotonic"],
    }


def slot_for_timestamp(timestamp: float, genesis_time: int, seconds_per_slot: int) -> int:
    return max(0, int((timestamp - genesis_time) // seconds_per_slot))


def latency_summary(values: List[float]) -> Dict[str, float]:
    if not values:
        return {"count": 0, "min": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0, "mean": 0.0}
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "min": ordered[0],
        "p50": percentile(ordered, 50),
        "p95": percentile(ordered, 95),
        "max": ordered[-1],
        "mean": sum(ordered) / len(ordered),
    }


def percentile(ordered_values: List[float], pct: float) -> float:
    if not ordered_values:
        return 0.0
    if len(ordered_values) == 1:
        return ordered_values[0]
    rank = (pct / 100.0) * (len(ordered_values) - 1)
    low = int(rank)
    high = min(low + 1, len(ordered_values) - 1)
    fraction = rank - low
    return ordered_values[low] * (1.0 - fraction) + ordered_values[high] * fraction


def path_length_summary(records: List[Dict[str, Any]]) -> Dict[str, float]:
    summary = latency_summary([float(record["path_len"]) for record in records])
    summary["avg_path_len"] = summary["mean"]
    summary["avg_hops"] = max(0.0, summary["mean"] - 1.0) if summary["count"] else 0.0
    return summary


def choose_origin(index: int, n: int, mode: str, seed: int) -> int:
    if mode == "single":
        return 0
    if mode == "round_robin":
        return index % n
    rng = random.Random(seed + index)
    return rng.randrange(n)


def collect_blocks(cl_api: str, start_slot: int, end_slot: int) -> Dict[str, Any]:
    records = []
    missed_slots = []
    for slot in range(start_slot, end_slot + 1):
        response = requests.get(f"{cl_api}/eth/v2/beacon/blocks/{slot}", timeout=10)
        if response.status_code == 404:
            missed_slots.append(slot)
            continue
        response.raise_for_status()
        message = response.json()["data"]["message"]
        body = message.get("body", {})
        inline_records = body.get("topostake_evidence_records") or body.get("topostakeEvidenceRecords") or []
        for record_index, record in enumerate(inline_records):
            path = [int(v) for v in record.get("relay_path", [])]
            records.append(
                {
                    "slot": int(message["slot"]),
                    "proposer_index": int(message["proposer_index"]),
                    "record_index": record_index,
                    "tx_hash": record.get("tx_hash"),
                    "epoch": int(record.get("epoch", 0)),
                    "priority_fee_wei": int(record.get("priority_fee_wei", 0)),
                    "path": path,
                    "path_len": len(path),
                    "aggregate_signature_len": len(record.get("aggregate_signature", [])),
                }
            )
    path_histogram = Counter(str(record["path_len"]) for record in records)
    relay_counts = Counter()
    for record in records:
        for relay in record["path"][1:-1]:
            relay_counts[str(relay)] += 1
    return {
        "start_slot": start_slot,
        "end_slot": end_slot,
        "missed_slots": len(missed_slots),
        "missed_slot_list": missed_slots,
        "record_count": len(records),
        "nonzero_fee_records": sum(1 for record in records if record["priority_fee_wei"] > 0),
        "priority_fee_sum_wei": sum(record["priority_fee_wei"] for record in records),
        "path_length_histogram": dict(sorted(path_histogram.items())),
        "path_length": path_length_summary(records),
        "relay_counts": dict(sorted(relay_counts.items(), key=lambda item: int(item[0]))),
        "records": records,
    }


def collect_prometheus(prometheus: str | None) -> Dict[str, Any]:
    if not prometheus:
        return {}
    out = {}
    for metric in TOPOSTAKE_METRICS:
        try:
            response = requests.get(
                f"{prometheus}/api/v1/query",
                params={"query": metric},
                timeout=10,
            )
            response.raise_for_status()
            result = response.json()["data"]["result"]
            out[metric] = [
                {"metric": item.get("metric", {}), "value": item.get("value", [None, None])[1]}
                for item in result
            ]
        except Exception as exc:  # best-effort collection
            out[metric] = {"error": str(exc)}
    return out


def write_records_csv(path: Path, records: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "slot",
        "proposer_index",
        "record_index",
        "tx_hash",
        "epoch",
        "priority_fee_wei",
        "path_len",
        "path",
        "aggregate_signature_len",
    ]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            row = dict(record)
            row["path"] = "-".join(str(v) for v in record["path"])
            writer.writerow(row)


def save_result(output_dir: Path, result: Dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    block_records = result.get("blocks", {}).get("records", [])
    if block_records:
        write_records_csv(output_dir / "block_records.csv", block_records)


def wait_for_finality(cl_api: str, start_finalized_epoch: int, min_advance: int, timeout_seconds: int) -> Dict[str, int]:
    deadline = time.time() + timeout_seconds
    target = start_finalized_epoch + min_advance
    latest = beacon_head(cl_api)
    while time.time() < deadline:
        latest = beacon_head(cl_api)
        if latest["finalized_epoch"] >= target:
            return latest
        time.sleep(6)
    return latest


def command_run(args: argparse.Namespace) -> Dict[str, Any]:
    endpoints = resolve_endpoints(args)
    if args.n is None:
        args.n = len(endpoints.el_rpcs)
    edges = generate_topology(args.n, args.topology, args.seed, args.degree, args.ba_m)
    if args.n > len(endpoints.el_rpcs):
        raise RuntimeError(f"topology requires {args.n} EL nodes, only {len(endpoints.el_rpcs)} endpoints supplied")

    endpoints.el_rpcs = endpoints.el_rpcs[: args.n]
    endpoints.cl_apis = endpoints.cl_apis[: args.n]
    if args.sender_count == 0:
        args.sender_count = args.n
    if args.send_concurrency == 0:
        args.send_concurrency = args.n
    if args.receipt_concurrency == 0:
        args.receipt_concurrency = args.n
    before = beacon_head(endpoints.cl_apis[0])
    if args.skip_apply_topology:
        node_infos = [rpc(url, "admin_nodeInfo") for url in endpoints.el_rpcs]
        peer_graph = inspect_peer_graph(
            endpoints.el_rpcs,
            [info["enode"] for info in node_infos],
            normalize_edges(edges),
            node_ids=[info["id"] for info in node_infos],
        )
    else:
        peer_graph = apply_topology(endpoints.el_rpcs, edges, prune=args.prune_peers)
    warmup = None
    if args.warmup_tx_count > 0:
        warmup = run_workload(args, endpoints, phase="warmup", tx_count=args.warmup_tx_count)
        if args.warmup_finality_epochs > 0:
            wait_for_finality(
                endpoints.cl_apis[0],
                before["finalized_epoch"],
                args.warmup_finality_epochs,
                args.finality_timeout_seconds,
            )
    measurement_before = beacon_head(endpoints.cl_apis[0])
    workload = run_workload(args, endpoints, phase="measurement")
    if args.wait_finality:
        after_finality = wait_for_finality(
            endpoints.cl_apis[0],
            measurement_before["finalized_epoch"],
            args.wait_finality_epochs,
            args.finality_timeout_seconds,
        )
    else:
        after_finality = beacon_head(endpoints.cl_apis[0])
    after = beacon_head(endpoints.cl_apis[0])
    blocks = collect_blocks(
        endpoints.cl_apis[0],
        max(0, measurement_before["head_slot"] - args.pre_scan_slots),
        after["head_slot"],
    )
    result = {
        "run_id": args.run_id,
        "enclave": args.enclave,
        "topology": {
            "kind": args.topology,
            "n": args.n,
            "seed": args.seed,
            "degree": args.degree,
            "ba_m": args.ba_m,
            "edges": edges,
        },
        "endpoints": {
            "el_rpcs": endpoints.el_rpcs,
            "cl_apis": endpoints.cl_apis,
            "prometheus": endpoints.prometheus,
        },
        "beacon_before": before,
        "beacon_before_measurement": measurement_before,
        "beacon_after_finality_wait": after_finality,
        "beacon_after": after,
        "peer_graph": peer_graph,
        "warmup": warmup,
        "workload": workload,
        "blocks": blocks,
        "prometheus": collect_prometheus(endpoints.prometheus),
    }
    save_result(args.output_root / args.run_id, result)
    return result


def command_topology(args: argparse.Namespace) -> Dict[str, Any]:
    edges = generate_topology(args.n, args.topology, args.seed, args.degree, args.ba_m)
    result = {"topology": args.topology, "n": args.n, "seed": args.seed, "degree": args.degree, "ba_m": args.ba_m, "edges": edges}
    print(json.dumps(result, indent=2, sort_keys=True))
    return result


def command_apply(args: argparse.Namespace) -> Dict[str, Any]:
    endpoints = resolve_endpoints(args)
    n = args.n or len(endpoints.el_rpcs)
    edges = generate_topology(n, args.topology, args.seed, args.degree, args.ba_m)
    result = apply_topology(endpoints.el_rpcs[:n], edges, prune=args.prune_peers)
    print(json.dumps(result, indent=2, sort_keys=True))
    return result


def command_collect(args: argparse.Namespace) -> Dict[str, Any]:
    endpoints = resolve_endpoints(args)
    head = beacon_head(endpoints.cl_apis[0])
    start_slot = args.start_slot if args.start_slot is not None else max(0, head["head_slot"] - args.slots_back)
    blocks = collect_blocks(endpoints.cl_apis[0], start_slot, head["head_slot"])
    result = {"beacon": head, "blocks": blocks, "prometheus": collect_prometheus(endpoints.prometheus)}
    save_result(args.output_root / args.run_id, result)
    print(json.dumps({k: v for k, v in result.items() if k != "prometheus"}, indent=2, sort_keys=True))
    return result


def add_common_endpoint_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--enclave", help="Kurtosis enclave name to inspect for ports")
    parser.add_argument("--el-rpcs", help="Comma-separated EL RPC URLs")
    parser.add_argument("--cl-apis", help="Comma-separated CL Beacon API URLs")
    parser.add_argument("--prometheus", help="Prometheus URL")


def add_topology_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--n", type=int, default=None, help="Number of EL nodes")
    parser.add_argument("--topology", choices=["linear", "ring", "star", "er", "random_regular", "ba"], default="linear")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--degree", type=float, default=2.0)
    parser.add_argument("--ba-m", type=int, default=1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    topology = sub.add_parser("topology", help="Generate a deterministic topology edge list")
    add_topology_args(topology)
    topology.set_defaults(func=command_topology)

    apply = sub.add_parser("apply", help="Apply a topology to a running devnet")
    add_common_endpoint_args(apply)
    add_topology_args(apply)
    apply.add_argument("--prune-peers", action="store_true", default=True)
    apply.set_defaults(func=command_apply)

    collect = sub.add_parser("collect", help="Collect block-inline path records and TopoStake metrics")
    add_common_endpoint_args(collect)
    collect.add_argument("--slots-back", type=int, default=128)
    collect.add_argument("--start-slot", type=int)
    collect.add_argument("--run-id", default="manual-collect")
    collect.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    collect.set_defaults(func=command_collect)

    run = sub.add_parser("run", help="Apply topology, send workload, wait, and collect evidence")
    add_common_endpoint_args(run)
    add_topology_args(run)
    run.add_argument("--run-id", default="manual-run")
    run.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    run.add_argument("--prune-peers", action="store_true", default=True)
    run.add_argument("--skip-apply-topology", action="store_true")
    run.add_argument("--tx-count", type=int, default=16)
    run.add_argument("--tx-interval-seconds", type=float, default=3.0)
    run.add_argument("--origin-mode", choices=["single", "round_robin", "random"], default="round_robin")
    run.add_argument("--private-key", default=DEFAULT_PRIVATE_KEY)
    run.add_argument("--private-keys", help="Comma-separated sender private keys; overrides --private-key/--sender-count defaults")
    run.add_argument("--sender-count", type=int, default=0, help="Number of funded sender accounts; 0 means one sender per EL node")
    run.add_argument("--send-concurrency", type=int, default=0, help="Concurrent transaction senders; 0 means one worker per EL node")
    run.add_argument("--receipt-concurrency", type=int, default=0, help="Concurrent receipt waiters; 0 means one worker per EL node")
    run.add_argument("--recipient", default=DEFAULT_RECIPIENT)
    run.add_argument("--value-wei", type=int, default=1)
    run.add_argument("--priority-fee-gwei", type=float, default=2.0)
    run.add_argument("--max-fee-gwei", type=float, default=50.0)
    run.add_argument("--receipt-timeout", type=int, default=90)
    run.add_argument("--wait-receipts-after-send", action="store_true")
    run.add_argument("--seconds-per-slot", type=int, default=3)
    run.add_argument("--warmup-tx-count", type=int, default=0)
    run.add_argument("--warmup-finality-epochs", type=int, default=0)
    run.add_argument("--wait-finality", action="store_true")
    run.add_argument("--wait-finality-epochs", type=int, default=2)
    run.add_argument("--finality-timeout-seconds", type=int, default=240)
    run.add_argument("--pre-scan-slots", type=int, default=4)
    run.set_defaults(func=command_run)

    args = parser.parse_args()
    result = args.func(args)
    if args.command == "run":
        compact = {
            "run_id": result["run_id"],
            "peer_counts": result["peer_graph"]["peer_counts"],
            "matches_target": result["peer_graph"]["matches_target"],
            "tx_success": result["workload"]["success_count"],
            "sender_count": result["workload"]["sender_count"],
            "origin_mode": result["workload"]["origin_mode"],
            "origin_counts": result["workload"]["origin_counts"],
            "actual_send_tps": result["workload"]["actual_send_tps"],
            "observed_receipt_throughput_tps": result["workload"]["observed_receipt_throughput_tps"],
            "observed_receipt_latency_seconds": result["workload"]["observed_receipt_latency_seconds"],
            "inclusion_throughput_tps": result["workload"]["inclusion_throughput_tps"],
            "inclusion_delay_slots": result["workload"]["inclusion_delay_slots"],
            "inclusion_delay_seconds": result["workload"]["inclusion_delay_seconds"],
            "record_count": result["blocks"]["record_count"],
            "path_length_histogram": result["blocks"]["path_length_histogram"],
            "avg_path_len": result["blocks"]["path_length"]["avg_path_len"],
            "avg_hops": result["blocks"]["path_length"]["avg_hops"],
            "priority_fee_sum_wei": result["blocks"]["priority_fee_sum_wei"],
            "finalized_epoch": result["beacon_after"]["finalized_epoch"],
            "output": str(args.output_root / args.run_id),
        }
        print(json.dumps(compact, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
