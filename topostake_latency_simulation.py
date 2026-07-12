#!/usr/bin/env python3
"""TopoStake proposer-ready latency experiments.

The experiment intentionally isolates one mechanism:

* PoS selects proposers by economic stake.
* TopoStake uses a BA-network relay-centrality proxy as propagation score and
  applies the protocol's capped proposer-weight bonus.
* Network latency is link_delay_ms * hop_count.
* TopoStake additionally pays the measured path-level BLS Sign, Verify, and
  Aggregate construction costs. Aggregate verification is excluded because it
  occurs during block validation.

The main experiment uses event-driven forwarding with active, normal, and lazy
relayers.  It produces p95 proposer-ready latency and within-slot delivery
ratio versus lazy-relayer fraction.  Two ideal-shortest-path sensitivity
sweeps are retained as supplementary results:

1. Validator count: 10, 20, 50, 100, 150, 200, 250, 300 at 50 ms/link.
2. Link delay: 25, 50, 75, 100 ms at 200 validators.
"""

from __future__ import annotations

import argparse
import heapq
import hashlib
import math
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from statistics import NormalDist
from typing import Sequence

import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
import pandas as pd


PROTOCOLS = ("PoS", "TopoStake")
VALIDATOR_COUNTS = (10, 20, 50, 100, 150, 200, 250, 300)
LINK_DELAYS_MS = (25.0, 50.0, 75.0, 100.0)
LAZY_FRACTIONS = (0.0, 0.2, 0.4, 0.6)

BLS_HOPS = np.asarray([1, 2, 4, 8, 16], dtype=float)
BLS_SIGN_MS = np.asarray([0.100, 0.190, 0.385, 0.727, 1.617], dtype=float)
BLS_VERIFY_MS = np.asarray([0.567, 1.076, 2.195, 4.450, 10.287], dtype=float)
BLS_AGGREGATE_MS = np.asarray([1.249, 2.435, 4.820, 9.561, 21.786], dtype=float)


@dataclass(frozen=True)
class Config:
    ba_m: int = 2
    stake_gini: float = 0.0
    eta: float = 0.5
    bonus_cap: float = 1.0
    scale_link_delay_ms: float = 50.0
    delay_sweep_validators: int = 200
    samples_per_seed: int = 20_000
    validators: int = 200
    slots_per_epoch: int = 8
    tx_per_slot: int = 8
    warmup_epochs: int = 20
    measurement_epochs: int = 100
    slot_ms: float = 3_000.0
    edge_delay_low_ms: float = 40.0
    edge_delay_high_ms: float = 60.0
    message_jitter: float = 0.10
    score_beta: float = 0.8
    saturation_k: float = 1.0
    initial_depth: int = 4
    role_placement: str = "random"
    role_profile: str = "fanout"
    initial_stake: float = 1.0
    block_reward: float = 0.5


@dataclass(frozen=True)
class Task:
    validators: int
    seed: int
    config: Config


@dataclass(frozen=True)
class LazyTask:
    lazy_fraction: float
    seed: int
    config: Config


def stable_seed(seed: int, *parts: object) -> int:
    payload = "|".join([str(seed), *map(str, parts)]).encode("utf-8")
    return int.from_bytes(hashlib.blake2b(payload, digest_size=8).digest(), "big")


def gini(values: np.ndarray) -> float:
    values = np.sort(np.asarray(values, dtype=float))
    if values.size == 0 or values.sum() <= 0:
        return 0.0
    n = values.size
    weighted = np.sum(np.arange(1, n + 1) * values)
    return float(2.0 * weighted / (n * values.sum()) - (n + 1.0) / n)


def generate_stakes(n: int, target_gini: float, seed: int) -> np.ndarray:
    """Generate normalized lognormal stake shares with the target population Gini."""
    sigma = math.sqrt(2.0) * NormalDist().inv_cdf((target_gini + 1.0) / 2.0)
    rng = np.random.default_rng(seed)
    stakes = rng.lognormal(mean=0.0, sigma=sigma, size=n)
    return stakes / stakes.sum()


def build_ba_graph(n: int, m: int, seed: int) -> nx.Graph:
    graph = nx.barabasi_albert_graph(n, m, seed=seed)
    if not nx.is_connected(graph):
        raise RuntimeError("BA graph is unexpectedly disconnected")
    return graph


def shortest_path_matrix(graph: nx.Graph) -> np.ndarray:
    n = graph.number_of_nodes()
    distances = np.zeros((n, n), dtype=np.int16)
    for source, lengths in nx.all_pairs_shortest_path_length(graph):
        for target, hops in lengths.items():
            distances[source, target] = hops
    return distances


def relay_score_proxy(graph: nx.Graph) -> np.ndarray:
    """Use normalized relay betweenness as a deterministic propagation-score proxy."""
    centrality = nx.betweenness_centrality(graph, normalized=True, endpoints=False)
    scores = np.asarray([centrality[node] for node in range(graph.number_of_nodes())])
    if scores.sum() <= 0:
        return np.full(graph.number_of_nodes(), 1.0 / graph.number_of_nodes())
    return scores / scores.sum()


def topostake_weights(
    stakes: np.ndarray,
    score_share: np.ndarray,
    eta: float,
    bonus_cap: float,
) -> np.ndarray:
    bonus = np.maximum(score_share / np.maximum(stakes, 1e-15) - 1.0, 0.0)
    bonus = np.minimum(bonus, bonus_cap)
    weights = stakes * (1.0 + eta * bonus)
    return weights / weights.sum()


def sample_weighted(cumulative: np.ndarray, uniforms: np.ndarray) -> np.ndarray:
    return np.searchsorted(cumulative, uniforms, side="right").clip(
        0, cumulative.size - 1
    )


def interpolate_cost(hops: np.ndarray, values: np.ndarray) -> np.ndarray:
    hops = np.asarray(hops, dtype=float)
    result = np.interp(hops, BLS_HOPS, values, left=0.0)
    above = hops > BLS_HOPS[-1]
    if np.any(above):
        slope = (values[-1] - values[-2]) / (BLS_HOPS[-1] - BLS_HOPS[-2])
        result[above] = values[-1] + slope * (hops[above] - BLS_HOPS[-1])
    result[hops <= 0] = 0.0
    return result


def crypto_cost_ms(hops: np.ndarray) -> np.ndarray:
    return (
        interpolate_cost(hops, BLS_SIGN_MS)
        + interpolate_cost(hops, BLS_VERIFY_MS)
        + interpolate_cost(hops, BLS_AGGREGATE_MS)
    )


def assign_roles(
    n: int,
    lazy_fraction: float,
    seed: int,
    *,
    placement: str = "random",
    degrees: np.ndarray | None = None,
) -> np.ndarray:
    """Assign exact lazy counts; every non-lazy node is active."""
    lazy_count = int(round(n * lazy_fraction))
    remaining = n - lazy_count
    active_count = remaining
    normal_count = 0
    roles = np.empty(n, dtype=object)
    if placement == "degree":
        if degrees is None or len(degrees) != n:
            raise ValueError("degree role placement requires one degree per node")
        rng = np.random.default_rng(seed)
        tie_break = rng.random(n)
        order = np.lexsort((tie_break, -np.asarray(degrees, dtype=float)))
        roles[order[:active_count]] = "active"
        roles[order[active_count : active_count + normal_count]] = "normal"
        roles[order[active_count + normal_count :]] = "lazy"
    elif placement == "random":
        roles[:] = (
            ["lazy"] * lazy_count
            + ["active"] * active_count
            + ["normal"] * normal_count
        )
        np.random.default_rng(seed).shuffle(roles)
    else:
        raise ValueError(f"unknown role placement: {placement}")
    return roles


def build_edge_delays(graph: nx.Graph, cfg: Config, seed: int) -> dict[tuple[int, int], float]:
    rng = np.random.default_rng(seed)
    delays: dict[tuple[int, int], float] = {}
    for u, v in sorted(graph.edges()):
        delay = float(rng.uniform(cfg.edge_delay_low_ms, cfg.edge_delay_high_ms))
        delays[(u, v)] = delay
        delays[(v, u)] = delay
    return delays


def select_forward_peers(
    neighbors: Sequence[int], role: str, rng: np.random.Generator
) -> np.ndarray:
    count = len(neighbors)
    if count == 0:
        return np.empty(0, dtype=int)
    if role == "active":
        fanout = count
    elif role == "normal":
        fanout = max(1, math.ceil(0.50 * count))
    else:
        fanout = max(1, math.ceil(0.25 * count))
    if fanout == count:
        return np.asarray(neighbors, dtype=int)
    return rng.choice(np.asarray(neighbors, dtype=int), size=fanout, replace=False)


def propagate_transaction(
    adjacency: Sequence[Sequence[int]],
    roles: np.ndarray,
    edge_delays: dict[tuple[int, int], float],
    origin: int,
    cfg: Config,
    seed: int,
    online: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return earliest network arrival, predecessor, and hop count for one tx."""
    n = len(adjacency)
    arrival = np.full(n, np.inf)
    predecessor = np.full(n, -1, dtype=np.int32)
    hops = np.full(n, -1, dtype=np.int16)
    arrival[origin] = 0.0
    hops[origin] = 0
    queue: list[tuple[float, int]] = [(0.0, origin)]
    rng = np.random.default_rng(seed)

    while queue:
        received_at, node = heapq.heappop(queue)
        if received_at != arrival[node]:
            continue
        incoming = int(predecessor[node])
        eligible_neighbors = (
            adjacency[node]
            if incoming < 0
            else tuple(peer for peer in adjacency[node] if peer != incoming)
        )
        peers = select_forward_peers(eligible_neighbors, str(roles[node]), rng)
        for peer_value in peers:
            peer = int(peer_value)
            if online is not None and not online[peer]:
                continue
            jitter = float(rng.uniform(1.0 - cfg.message_jitter, 1.0 + cfg.message_jitter))
            candidate = received_at + edge_delays[(node, peer)] * jitter
            if candidate < arrival[peer]:
                arrival[peer] = candidate
                predecessor[peer] = node
                hops[peer] = hops[node] + 1
                heapq.heappush(queue, (candidate, peer))
    return arrival, predecessor, hops


def sample_slot_availability(
    roles: np.ndarray, profile: str, seed: int
) -> np.ndarray:
    if profile == "fanout":
        return np.ones(len(roles), dtype=bool)
    if profile != "reliability":
        raise ValueError(f"unknown role profile: {profile}")
    probability = np.where(
        roles == "active",
        1.0,
        np.where(roles == "normal", 0.90, 0.60),
    )
    return np.random.default_rng(seed).random(len(roles)) < probability


def path_to_target(predecessor: np.ndarray, origin: int, target: int) -> list[int]:
    if target == origin:
        return [origin]
    if predecessor[target] < 0:
        return []
    path = [target]
    node = target
    while node != origin:
        node = int(predecessor[node])
        if node < 0:
            return []
        path.append(node)
    path.reverse()
    return path


def add_path_contribution(raw: np.ndarray, path: Sequence[int], target_depth: int) -> None:
    """Apply the paper's bounded path budget and positional relay weights."""
    m = len(path) - 1
    if m <= 1:
        return
    depth = max(1, target_depth)
    lambda_e = (2.0 * depth + 1.0) / (3.0 * depth + 1.0)
    r_e = depth / (2.0 * depth + 1.0)
    budget = min(1.0, depth / m) * lambda_e ** (m - 1)
    denominator = 1.0 - r_e ** (m - 1)
    for position, relay in enumerate(path[1:-1], start=1):
        alpha = (1.0 - r_e) * r_e ** (position - 1) / denominator
        raw[int(relay)] += budget * alpha


def update_target_depth(current: int, path_lengths: Sequence[int]) -> int:
    if not path_lengths:
        return current
    median = int(round(float(np.median(path_lengths))))
    if median > current:
        return current + 1
    if median < current:
        return max(1, current - 1)
    return current


def update_score(
    previous: np.ndarray, raw: np.ndarray, stakes: np.ndarray, cfg: Config
) -> np.ndarray:
    saturated = stakes * np.log1p(raw / np.maximum(cfg.saturation_k * stakes, 1e-15))
    return cfg.score_beta * saturated + (1.0 - cfg.score_beta) * previous


def run_lazy_task(task: LazyTask) -> list[dict[str, float | int | str]]:
    """Run one paired active/normal/lazy experiment seed."""
    cfg = task.config
    n = cfg.validators
    graph = build_ba_graph(n, cfg.ba_m, stable_seed(task.seed, "lazy_graph", n))
    adjacency = [tuple(sorted(graph.neighbors(node))) for node in range(n)]
    initial_shares = generate_stakes(
        n, cfg.stake_gini, stable_seed(task.seed, "lazy_stakes", n)
    )
    initial_balances = initial_shares * (n * cfg.initial_stake)
    balances = {
        protocol: initial_balances.copy()
        for protocol in PROTOCOLS
    }
    roles = assign_roles(
        n,
        task.lazy_fraction,
        stable_seed(task.seed, "roles", task.lazy_fraction),
        placement=cfg.role_placement,
        degrees=np.asarray([graph.degree(node) for node in range(n)]),
    )
    edge_delays = build_edge_delays(
        graph, cfg, stable_seed(task.seed, "edge_delays", n)
    )
    score = np.zeros(n, dtype=float)
    target_depth = cfg.initial_depth
    total_epochs = cfg.warmup_epochs + cfg.measurement_epochs
    measured_latency: dict[str, list[float]] = {protocol: [] for protocol in PROTOCOLS}
    measured_delivery: dict[str, int] = {protocol: 0 for protocol in PROTOCOLS}
    measured_total = 0

    for epoch in range(total_epochs):
        # Economic balances remain absolute.  These normalized snapshots are
        # temporary lottery probabilities (and the paper's \hat{S}_i), not
        # balance updates.
        selection_shares = {
            protocol: balances[protocol] / balances[protocol].sum()
            for protocol in PROTOCOLS
        }
        if score.sum() > 0:
            score_share = score / score.sum()
            topo_weights = topostake_weights(
                selection_shares["TopoStake"], score_share, cfg.eta, cfg.bonus_cap
            )
        else:
            topo_weights = selection_shares["TopoStake"]
        epoch_rng = np.random.default_rng(stable_seed(task.seed, "epoch", task.lazy_fraction, epoch))
        election_uniforms = epoch_rng.random(cfg.slots_per_epoch)
        proposers = {
            "PoS": sample_weighted(
                np.cumsum(selection_shares["PoS"]), election_uniforms
            ),
            "TopoStake": sample_weighted(np.cumsum(topo_weights), election_uniforms),
        }
        raw_contribution = np.zeros(n, dtype=float)
        successful_path_lengths: list[int] = []

        for slot in range(cfg.slots_per_epoch):
            online = sample_slot_availability(
                roles,
                cfg.role_profile,
                stable_seed(task.seed, "availability", task.lazy_fraction, epoch, slot),
            )
            online_nodes = np.flatnonzero(online)
            if online_nodes.size == 0:
                continue
            for tx_index in range(cfg.tx_per_slot):
                origin = int(online_nodes[epoch_rng.integers(0, online_nodes.size)])
                tx_seed = stable_seed(
                    task.seed, "forward", task.lazy_fraction, epoch, slot, tx_index
                )
                arrival, predecessor, hops = propagate_transaction(
                    adjacency, roles, edge_delays, origin, cfg, tx_seed, online
                )
                is_measurement = epoch >= cfg.warmup_epochs
                if is_measurement:
                    measured_total += 1
                for protocol in PROTOCOLS:
                    proposer = int(proposers[protocol][slot])
                    network_latency = float(arrival[proposer])
                    delivered = math.isfinite(network_latency)
                    latency = network_latency
                    if protocol == "TopoStake" and delivered:
                        latency += float(crypto_cost_ms(np.asarray([hops[proposer]]))[0])
                    within_slot = delivered and latency <= cfg.slot_ms
                    if is_measurement:
                        if within_slot:
                            measured_latency[protocol].append(latency)
                        measured_delivery[protocol] += int(within_slot)

                    if protocol == "TopoStake" and within_slot:
                        path = path_to_target(predecessor, origin, proposer)
                        if path:
                            add_path_contribution(raw_contribution, path, target_depth)
                            successful_path_lengths.append(len(path) - 1)

        score = update_score(
            score, raw_contribution, selection_shares["TopoStake"], cfg
        )
        target_depth = update_target_depth(target_depth, successful_path_lengths)
        for protocol in PROTOCOLS:
            np.add.at(balances[protocol], proposers[protocol], cfg.block_reward)

    role_counts = {role: int(np.count_nonzero(roles == role)) for role in ("active", "normal", "lazy")}
    rows: list[dict[str, float | int | str]] = []
    for protocol in PROTOCOLS:
        latencies = np.asarray(measured_latency[protocol], dtype=float)
        rows.append(
            {
                "experiment": "lazy_fraction",
                "lazy_fraction": task.lazy_fraction,
                "protocol": protocol,
                "seed": task.seed,
                "validators": n,
                "active_nodes": role_counts["active"],
                "normal_nodes": role_counts["normal"],
                "lazy_nodes": role_counts["lazy"],
                "transactions": measured_total,
                "delivered_latency_samples": int(latencies.size),
                "p95_latency_ms": float(np.quantile(latencies, 0.95)),
                "delivery_ratio": measured_delivery[protocol] / measured_total,
                "stake_gini_realized": gini(initial_balances),
                "final_stake_gini": gini(balances[protocol]),
                "initial_stake_per_node": cfg.initial_stake,
                "block_reward": cfg.block_reward,
                "final_total_stake": float(balances[protocol].sum()),
                "final_target_depth": target_depth,
            }
        )
    return rows


def summarize_samples(
    *,
    experiment: str,
    x_value: float,
    validators: int,
    link_delay_ms: float,
    protocol: str,
    seed: int,
    hops: np.ndarray,
    latencies_ms: np.ndarray,
    stake_gini_realized: float,
) -> dict[str, float | int | str]:
    return {
        "experiment": experiment,
        "x_value": x_value,
        "validators": validators,
        "link_delay_ms": link_delay_ms,
        "protocol": protocol,
        "seed": seed,
        "samples": int(hops.size),
        "mean_hops": float(hops.mean()),
        "p95_hops": float(np.quantile(hops, 0.95)),
        "mean_latency_ms": float(latencies_ms.mean()),
        "p95_latency_ms": float(np.quantile(latencies_ms, 0.95)),
        "stake_gini_realized": stake_gini_realized,
    }


def run_task(task: Task) -> list[dict[str, float | int | str]]:
    cfg = task.config
    n = task.validators
    graph = build_ba_graph(n, cfg.ba_m, stable_seed(task.seed, "graph", n))
    distances = shortest_path_matrix(graph)
    stakes = generate_stakes(n, cfg.stake_gini, stable_seed(task.seed, "stakes", n))
    score_share = relay_score_proxy(graph)
    topo_weights = topostake_weights(stakes, score_share, cfg.eta, cfg.bonus_cap)

    rng = np.random.default_rng(stable_seed(task.seed, "samples", n))
    origins = rng.integers(0, n, size=cfg.samples_per_seed)
    election_uniforms = rng.random(cfg.samples_per_seed)
    proposers = {
        "PoS": sample_weighted(np.cumsum(stakes), election_uniforms),
        "TopoStake": sample_weighted(np.cumsum(topo_weights), election_uniforms),
    }

    rows: list[dict[str, float | int | str]] = []
    realized_gini = gini(stakes)
    for protocol in PROTOCOLS:
        hops = distances[origins, proposers[protocol]].astype(float)
        crypto = (
            np.zeros_like(hops)
            if protocol == "PoS"
            else crypto_cost_ms(hops)
        )

        scale_latency = cfg.scale_link_delay_ms * hops + crypto
        rows.append(
            summarize_samples(
                experiment="validator_scale",
                x_value=float(n),
                validators=n,
                link_delay_ms=cfg.scale_link_delay_ms,
                protocol=protocol,
                seed=task.seed,
                hops=hops,
                latencies_ms=scale_latency,
                stake_gini_realized=realized_gini,
            )
        )

        if n == cfg.delay_sweep_validators:
            for delay in LINK_DELAYS_MS:
                latency = delay * hops + crypto
                rows.append(
                    summarize_samples(
                        experiment="link_delay",
                        x_value=delay,
                        validators=n,
                        link_delay_ms=delay,
                        protocol=protocol,
                        seed=task.seed,
                        hops=hops,
                        latencies_ms=latency,
                        stake_gini_realized=realized_gini,
                    )
                )
    return rows


def bootstrap_median_ci(
    values: np.ndarray, seed: int, samples: int = 4000
) -> tuple[float, float, float]:
    values = np.asarray(values, dtype=float)
    median = float(np.median(values))
    if values.size == 1:
        return median, median, median
    rng = np.random.default_rng(seed)
    boot = np.median(
        rng.choice(values, size=(samples, values.size), replace=True), axis=1
    )
    low, high = np.quantile(boot, [0.025, 0.975])
    return median, float(low), float(high)


def aggregate_runs(raw: pd.DataFrame) -> pd.DataFrame:
    group_columns = [
        "experiment",
        "x_value",
        "validators",
        "link_delay_ms",
        "protocol",
    ]
    rows: list[dict[str, float | int | str]] = []
    for keys, group in raw.groupby(group_columns, sort=True):
        row: dict[str, float | int | str] = dict(zip(group_columns, keys))
        for metric in ("mean_hops", "p95_hops", "mean_latency_ms", "p95_latency_ms"):
            med, low, high = bootstrap_median_ci(
                group[metric].to_numpy(),
                stable_seed(20260710, *keys, metric),
            )
            row[f"{metric}_median"] = med
            row[f"{metric}_ci_low"] = low
            row[f"{metric}_ci_high"] = high
        rows.append(row)
    return pd.DataFrame(rows)


def aggregate_lazy_runs(raw: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, float | int | str]] = []
    for (lazy_fraction, protocol), group in raw.groupby(
        ["lazy_fraction", "protocol"], sort=True
    ):
        row: dict[str, float | int | str] = {
            "lazy_fraction": lazy_fraction,
            "protocol": protocol,
            "validators": int(group["validators"].iloc[0]),
            "active_nodes": int(group["active_nodes"].iloc[0]),
            "normal_nodes": int(group["normal_nodes"].iloc[0]),
            "lazy_nodes": int(group["lazy_nodes"].iloc[0]),
        }
        for metric in ("p95_latency_ms", "delivery_ratio"):
            median, low, high = bootstrap_median_ci(
                group[metric].to_numpy(),
                stable_seed(20260710, "lazy", lazy_fraction, protocol, metric),
            )
            row[f"{metric}_median"] = median
            row[f"{metric}_ci_low"] = low
            row[f"{metric}_ci_high"] = high
        rows.append(row)
    return pd.DataFrame(rows)


def aggregate_delivery_gain(raw: pd.DataFrame) -> pd.DataFrame:
    pivot = raw.pivot(
        index=["lazy_fraction", "seed"],
        columns="protocol",
        values="delivery_ratio",
    )
    rows = []
    for lazy_fraction, group in pivot.groupby(level="lazy_fraction"):
        gain_pp = 100.0 * (group["TopoStake"] - group["PoS"]).to_numpy()
        median, low, high = bootstrap_median_ci(
            gain_pp,
            stable_seed(20260710, "paired_delivery_gain", lazy_fraction),
        )
        rows.append(
            {
                "lazy_fraction": lazy_fraction,
                "gain_pp_median": median,
                "gain_pp_ci_low": low,
                "gain_pp_ci_high": high,
                "positive_seed_fraction": float((gain_pp > 0).mean()),
            }
        )
    return pd.DataFrame(rows)


def paired_differences(raw: pd.DataFrame) -> pd.DataFrame:
    index = ["experiment", "x_value", "validators", "link_delay_ms", "seed"]
    pivot = raw.pivot(index=index, columns="protocol", values=["mean_hops", "mean_latency_ms"])
    rows = []
    for keys, group in pivot.groupby(level=index[:-1]):
        row = dict(zip(index[:-1], keys))
        for metric in ("mean_hops", "mean_latency_ms"):
            delta = (group[metric]["TopoStake"] - group[metric]["PoS"]).to_numpy()
            med, low, high = bootstrap_median_ci(
                delta, stable_seed(20260710, *keys, metric, "paired")
            )
            row[f"delta_{metric}_median"] = med
            row[f"delta_{metric}_ci_low"] = low
            row[f"delta_{metric}_ci_high"] = high
            row[f"topostake_lower_{metric}_seed_fraction"] = float((delta < 0).mean())
        rows.append(row)
    return pd.DataFrame(rows)


def plot_metric(
    summary: pd.DataFrame,
    *,
    experiment: str,
    metric: str,
    xlabel: str,
    ylabel: str,
    output: Path,
    shaded_ci: bool = True,
) -> None:
    data = summary[summary["experiment"] == experiment]
    styles = {
        "PoS": {"color": "#2ca02c", "marker": "o", "linestyle": "--"},
        "TopoStake": {"color": "#1f77b4", "marker": "^", "linestyle": "-"},
    }
    fig, ax = plt.subplots(figsize=(4.8, 3.2))
    for protocol in PROTOCOLS:
        part = data[data["protocol"] == protocol].sort_values("x_value")
        x = part["x_value"].to_numpy(dtype=float)
        y = part[f"{metric}_median"].to_numpy(dtype=float)
        low = part[f"{metric}_ci_low"].to_numpy(dtype=float)
        high = part[f"{metric}_ci_high"].to_numpy(dtype=float)
        if shaded_ci:
            ax.plot(
                x,
                y,
                linewidth=1.8,
                markersize=6,
                label=protocol,
                **styles[protocol],
            )
            ax.fill_between(
                x,
                low,
                high,
                color=styles[protocol]["color"],
                alpha=0.12,
                linewidth=0,
            )
        else:
            ax.errorbar(
                x,
                y,
                yerr=np.vstack([y - low, high - y]),
                linewidth=1.8,
                markersize=6,
                capsize=2.5,
                label=protocol,
                **styles[protocol],
            )
    ax.set_xlabel(xlabel, fontsize=13)
    ax.set_ylabel(ylabel, fontsize=13)
    ax.tick_params(axis="both", labelsize=11)
    ax.grid(True, alpha=0.25)
    ax.legend(frameon=False, fontsize=11)
    fig.tight_layout()
    fig.savefig(output.with_suffix(".pdf"), bbox_inches="tight")
    fig.savefig(output.with_suffix(".png"), dpi=240, bbox_inches="tight")
    plt.close(fig)


def plot_combined_latency(summary: pd.DataFrame, output: Path) -> None:
    """Create the compact two-panel latency figure used as the main paper plot."""
    styles = {
        "PoS": {"color": "#2ca02c", "marker": "o", "linestyle": "--"},
        "TopoStake": {"color": "#1f77b4", "marker": "^", "linestyle": "-"},
    }
    panels = (
        ("validator_scale", "Number of nodes", "(a) Network scale"),
        ("link_delay", "Link delay (ms)", "(b) Link delay"),
    )
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 2.8))
    handles = []
    labels = []
    for ax, (experiment, xlabel, panel_label) in zip(axes, panels):
        data = summary[summary["experiment"] == experiment]
        for protocol in PROTOCOLS:
            part = data[data["protocol"] == protocol].sort_values("x_value")
            x = part["x_value"].to_numpy(dtype=float)
            y = part["mean_latency_ms_median"].to_numpy(dtype=float)
            low = part["mean_latency_ms_ci_low"].to_numpy(dtype=float)
            high = part["mean_latency_ms_ci_high"].to_numpy(dtype=float)
            (line,) = ax.plot(
                x,
                y,
                linewidth=1.7,
                markersize=5.2,
                label=protocol,
                **styles[protocol],
            )
            ax.fill_between(x, low, high, color=styles[protocol]["color"], alpha=0.12)
            if ax is axes[0]:
                handles.append(line)
                labels.append(protocol)
        ax.set_xlabel(xlabel, fontsize=11)
        ax.tick_params(axis="both", labelsize=9.5)
        ax.grid(True, linewidth=0.5, alpha=0.22)
        ax.text(0.03, 0.95, panel_label, transform=ax.transAxes, ha="left", va="top", fontsize=10)

    axes[0].set_ylabel("Mean latency (ms)", fontsize=11)
    axes[0].set_xticks([10, 50, 100, 150, 200, 250, 300])
    axes[1].set_xticks(list(LINK_DELAYS_MS))
    fig.legend(
        handles,
        labels,
        frameon=False,
        ncol=2,
        loc="upper center",
        bbox_to_anchor=(0.5, 1.02),
        fontsize=10.5,
    )
    fig.subplots_adjust(left=0.10, right=0.99, bottom=0.20, top=0.82, wspace=0.28)
    fig.savefig(output.with_suffix(".pdf"), bbox_inches="tight")
    fig.savefig(output.with_suffix(".png"), dpi=300, bbox_inches="tight")
    plt.close(fig)


def plot_lazy_metric(
    summary: pd.DataFrame,
    *,
    metric: str,
    ylabel: str,
    output: Path,
    percent: bool = False,
) -> None:
    styles = {
        "PoS": {"color": "#2ca02c", "marker": "o", "linestyle": "--"},
        "TopoStake": {"color": "#1f77b4", "marker": "^", "linestyle": "-"},
    }
    fig, ax = plt.subplots(figsize=(4.8, 3.2))
    for protocol in PROTOCOLS:
        part = summary[summary["protocol"] == protocol].sort_values("lazy_fraction")
        x = 100.0 * part["lazy_fraction"].to_numpy(dtype=float)
        scale = 100.0 if percent else 1.0
        y = scale * part[f"{metric}_median"].to_numpy(dtype=float)
        low = scale * part[f"{metric}_ci_low"].to_numpy(dtype=float)
        high = scale * part[f"{metric}_ci_high"].to_numpy(dtype=float)
        ax.plot(x, y, linewidth=1.8, markersize=6, label=protocol, **styles[protocol])
        ax.fill_between(x, low, high, color=styles[protocol]["color"], alpha=0.12, linewidth=0)
    ax.set_xlabel("Lazy relayers (%)", fontsize=13)
    ax.set_ylabel(ylabel, fontsize=13)
    ax.set_xticks([0, 20, 40, 60])
    if percent:
        minimum = float(
            100.0
            * summary[f"{metric}_ci_low"].min()
        )
        lower = max(0.0, 5.0 * math.floor(minimum / 5.0) - 5.0)
        ax.set_ylim(lower, 101.0)
    ax.tick_params(axis="both", labelsize=11)
    ax.grid(True, alpha=0.25)
    ax.legend(frameon=False, fontsize=11)
    fig.tight_layout()
    fig.savefig(output.with_suffix(".pdf"), bbox_inches="tight")
    fig.savefig(output.with_suffix(".png"), dpi=240, bbox_inches="tight")
    plt.close(fig)


def plot_delivery_gain(gain: pd.DataFrame, output: Path) -> None:
    fig, ax = plt.subplots(figsize=(4.8, 3.2))
    gain = gain.sort_values("lazy_fraction")
    x = 100.0 * gain["lazy_fraction"].to_numpy(dtype=float)
    y = gain["gain_pp_median"].to_numpy(dtype=float)
    low = gain["gain_pp_ci_low"].to_numpy(dtype=float)
    high = gain["gain_pp_ci_high"].to_numpy(dtype=float)
    ax.axhline(0.0, color="#555555", linewidth=1.0, linestyle=":")
    ax.plot(x, y, color="#1f77b4", marker="D", linewidth=1.7, markersize=5.0)
    ax.fill_between(x, low, high, color="#1f77b4", alpha=0.14, linewidth=0)
    ax.set_xlabel("Lazy relayers (%)", fontsize=13)
    ax.set_ylabel("TopoStake gain (pp)", fontsize=13)
    ax.set_xticks([0, 20, 40, 60])
    ax.grid(True, alpha=0.25)
    ax.tick_params(axis="both", labelsize=11)
    fig.tight_layout()
    fig.savefig(output.with_suffix(".pdf"), bbox_inches="tight")
    fig.savefig(output.with_suffix(".png"), dpi=300, bbox_inches="tight")
    plt.close(fig)


def write_lazy_tables(
    raw: pd.DataFrame, summary: pd.DataFrame, gain: pd.DataFrame, output_dir: Path
) -> None:
    raw.to_csv(output_dir / "lazy_fraction_raw_runs.csv", index=False)
    summary.to_csv(output_dir / "lazy_fraction_summary.csv", index=False)
    gain.to_csv(output_dir / "delivery_gain_summary.csv", index=False)
    table = pd.DataFrame(
        {
            "Lazy relayers": summary["lazy_fraction"].map(lambda value: f"{100 * value:.0f}%"),
            "Active/Normal/Lazy": summary.apply(
                lambda row: f"{row['active_nodes']}/{row['normal_nodes']}/{row['lazy_nodes']}", axis=1
            ),
            "Protocol": summary["protocol"],
            "p95 delivered latency (ms)": summary["p95_latency_ms_median"].map(lambda value: f"{value:.2f}"),
            "Within-slot delivery": summary["delivery_ratio_median"].map(lambda value: f"{100 * value:.2f}%"),
        }
    )
    table.to_csv(output_dir / "latency_by_lazy_fraction.csv", index=False)
    markdown_table(table, output_dir / "latency_by_lazy_fraction.md")


def markdown_table(frame: pd.DataFrame, path: Path) -> None:
    headers = list(frame.columns)
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in frame.itertuples(index=False, name=None):
        lines.append("| " + " | ".join(map(str, row)) + " |")
    path.write_text("\n".join(lines) + "\n")


def write_tables(summary: pd.DataFrame, paired: pd.DataFrame, output_dir: Path) -> None:
    summary.to_csv(output_dir / "latency_summary.csv", index=False)
    paired.to_csv(output_dir / "paired_differences.csv", index=False)

    for experiment, stem in (
        ("validator_scale", "latency_by_validators"),
        ("link_delay", "latency_by_link_delay"),
    ):
        part = summary[summary["experiment"] == experiment].copy()
        table = pd.DataFrame(
            {
                "x": part["x_value"].map(lambda value: f"{value:g}"),
                "Protocol": part["protocol"],
                "Mean hops": part["mean_hops_median"].map(lambda value: f"{value:.3f}"),
                "Mean latency (ms)": part["mean_latency_ms_median"].map(
                    lambda value: f"{value:.3f}"
                ),
                "p95 latency (ms)": part["p95_latency_ms_median"].map(
                    lambda value: f"{value:.3f}"
                ),
            }
        )
        table.to_csv(output_dir / f"{stem}.csv", index=False)
        markdown_table(table, output_dir / f"{stem}.md")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=20)
    parser.add_argument("--stake-gini", type=float, default=0.0)
    parser.add_argument("--initial-stake", type=float, default=1.0)
    parser.add_argument("--block-reward", type=float, default=0.5)
    parser.add_argument(
        "--role-placement",
        choices=("random", "degree"),
        default="random",
        help="random roles or capacity-correlated roles ordered by BA degree",
    )
    parser.add_argument(
        "--role-profile",
        choices=("fanout", "reliability"),
        default="fanout",
        help="fanout only, or fanout plus 100/90/60%% slot availability",
    )
    parser.add_argument("--samples-per-seed", type=int, default=20_000)
    parser.add_argument("--warmup-epochs", type=int, default=20)
    parser.add_argument("--measurement-epochs", type=int, default=100)
    parser.add_argument(
        "--workers", type=int, default=min(12, max(1, (os.cpu_count() or 2) - 1))
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("results/latency_simple")
    )
    parser.add_argument(
        "--include-supplementary",
        action="store_true",
        help="also rerun the ideal shortest-path node-count and link-delay sweeps",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if (
        args.seeds < 1
        or args.samples_per_seed < 1
        or args.workers < 1
        or args.warmup_epochs < 0
        or args.measurement_epochs < 1
        or not 0.0 <= args.stake_gini < 1.0
        or args.initial_stake <= 0.0
        or args.block_reward < 0.0
    ):
        raise ValueError("invalid non-positive experiment size")
    config = Config(
        stake_gini=args.stake_gini,
        initial_stake=args.initial_stake,
        block_reward=args.block_reward,
        role_placement=args.role_placement,
        role_profile=args.role_profile,
        samples_per_seed=args.samples_per_seed,
        warmup_epochs=args.warmup_epochs,
        measurement_epochs=args.measurement_epochs,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Config: {config}", flush=True)
    lazy_tasks = [
        LazyTask(lazy_fraction=fraction, seed=seed, config=config)
        for fraction in LAZY_FRACTIONS
        for seed in range(args.seeds)
    ]
    print(
        f"Lazy experiment: seeds={args.seeds}; tasks={len(lazy_tasks)}; workers={args.workers}",
        flush=True,
    )
    lazy_rows: list[dict[str, float | int | str]] = []
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(run_lazy_task, task) for task in lazy_tasks]
        for completed, future in enumerate(as_completed(futures), start=1):
            lazy_rows.extend(future.result())
            if completed % 5 == 0 or completed == len(lazy_tasks):
                print(f"Completed lazy task {completed}/{len(lazy_tasks)}", flush=True)
    lazy_raw = pd.DataFrame(lazy_rows).sort_values(
        ["lazy_fraction", "protocol", "seed"]
    )
    lazy_summary = aggregate_lazy_runs(lazy_raw)
    delivery_gain = aggregate_delivery_gain(lazy_raw)
    write_lazy_tables(lazy_raw, lazy_summary, delivery_gain, args.output_dir)
    plot_lazy_metric(
        lazy_summary,
        metric="p95_latency_ms",
        ylabel="p95 delivered latency (ms)",
        output=args.output_dir / "proposer_latency_lazy_fraction",
    )
    plot_lazy_metric(
        lazy_summary,
        metric="delivery_ratio",
        ylabel="Within-slot delivery (%)",
        output=args.output_dir / "proposer_delivery_lazy_fraction",
        percent=True,
    )
    plot_delivery_gain(
        delivery_gain,
        output=args.output_dir / "proposer_delivery_gain_lazy_fraction",
    )

    if args.include_supplementary:
        tasks = [
            Task(validators=n, seed=seed, config=config)
            for n in VALIDATOR_COUNTS
            for seed in range(args.seeds)
        ]
        rows: list[dict[str, float | int | str]] = []
        with ProcessPoolExecutor(max_workers=args.workers) as executor:
            futures = [executor.submit(run_task, task) for task in tasks]
            for completed, future in enumerate(as_completed(futures), start=1):
                rows.extend(future.result())
                if completed % 10 == 0 or completed == len(tasks):
                    print(f"Completed supplementary task {completed}/{len(tasks)}", flush=True)
        raw = pd.DataFrame(rows).sort_values(
            ["experiment", "x_value", "protocol", "seed"]
        )
        raw.to_csv(args.output_dir / "raw_runs.csv", index=False)
        summary = aggregate_runs(raw)
        paired = paired_differences(raw)
        write_tables(summary, paired, args.output_dir)
        plot_metric(
            summary,
            experiment="validator_scale",
            metric="mean_latency_ms",
            xlabel="Number of nodes",
            ylabel="Mean latency (ms)",
            output=args.output_dir / "proposer_latency_validators",
        )
        plot_metric(
            summary,
            experiment="link_delay",
            metric="mean_latency_ms",
            xlabel="One-way link delay (ms)",
            ylabel="Mean latency (ms)",
            output=args.output_dir / "proposer_latency_link_delay",
        )
        plot_metric(
            summary,
            experiment="validator_scale",
            metric="mean_hops",
            xlabel="Number of nodes",
            ylabel="Mean hops",
            output=args.output_dir / "proposer_path_length_validators",
            shaded_ci=False,
        )
        plot_combined_latency(summary, output=args.output_dir / "proposer_latency_sensitivity")
    print(f"Saved results under {args.output_dir}", flush=True)


if __name__ == "__main__":
    main()
