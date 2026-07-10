#!/usr/bin/env python3
import csv
import math
import re
from collections import defaultdict
from pathlib import Path

from plot_common import PROCESSED, ROOT, to_float


RAW_ROOT = ROOT / "results" / "raw" / "tdsc_seed_scan" / "stake_seed_scan"
OUT = PROCESSED / "stake_seed_scan_topology.csv"
RUN_RE = re.compile(r"seed(?P<seed>\d+)_stake-gini-(?P<gini>\d+p\d+)")


def corr(xs, ys):
    pairs = [(x, y) for x, y in zip(xs, ys) if math.isfinite(x) and math.isfinite(y)]
    if len(pairs) < 2:
        return math.nan
    mx = sum(x for x, _ in pairs) / len(pairs)
    my = sum(y for _, y in pairs) / len(pairs)
    num = sum((x - mx) * (y - my) for x, y in pairs)
    den_x = math.sqrt(sum((x - mx) ** 2 for x, _ in pairs))
    den_y = math.sqrt(sum((y - my) ** 2 for _, y in pairs))
    return num / (den_x * den_y) if den_x and den_y else math.nan


def percentile(values, q):
    if not values:
        return math.nan
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    low = math.floor(pos)
    high = math.ceil(pos)
    if low == high:
        return ordered[low]
    return ordered[low] * (high - pos) + ordered[high] * (pos - low)


def scan_run(path):
    rows = []
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("epoch") == "0":
                rows.append(row)
    if not rows:
        return None

    stakes = [to_float(row.get("economic_stake"), 0.0) for row in rows]
    degrees = [to_float(row.get("degree"), 0.0) for row in rows]
    betweenness = [to_float(row.get("betweenness"), 0.0) for row in rows]
    total_stake = sum(stakes)
    if total_stake <= 0:
        return None

    degree_p25 = percentile(degrees, 0.25)
    degree_p50 = percentile(degrees, 0.50)
    betweenness_p25 = percentile(betweenness, 0.25)
    edge_by_degree = [i for i, value in enumerate(degrees) if value <= degree_p25]
    edge_by_betweenness = [i for i, value in enumerate(betweenness) if value <= betweenness_p25]
    leaves = [i for i, value in enumerate(degrees) if value <= 1.0]
    low_degree_half = [i for i, value in enumerate(degrees) if value <= degree_p50]
    top_stake_count = max(1, math.ceil(len(stakes) * 0.10))
    top_stake = set(sorted(range(len(stakes)), key=lambda i: stakes[i], reverse=True)[:top_stake_count])

    def stake_share(indices):
        return sum(stakes[i] for i in indices) / total_stake if indices else 0.0

    def top_stake_count_in(indices):
        index_set = set(indices)
        return sum(1 for i in top_stake if i in index_set)

    meta = rows[0]
    run_id = path.parent.name
    match = RUN_RE.search(run_id)
    return {
        "run_id": run_id,
        "seed_index": meta.get("seed_index", "") or (match.group("seed") if match else ""),
        "seed_value": meta.get("seed_value", ""),
        "stake_gini": meta.get("stake_gini", "") or (match.group("gini").replace("p", ".") if match else ""),
        "stake_degree_corr": corr(stakes, degrees),
        "stake_betweenness_corr": corr(stakes, betweenness),
        "edge_degree_stake_share": stake_share(edge_by_degree),
        "edge_betweenness_stake_share": stake_share(edge_by_betweenness),
        "leaf_stake_share": stake_share(leaves),
        "low_degree_half_stake_share": stake_share(low_degree_half),
        "top10_stake_nodes_in_edge_degree": top_stake_count_in(edge_by_degree),
        "top10_stake_nodes_in_edge_betweenness": top_stake_count_in(edge_by_betweenness),
    }


def main():
    records = []
    for path in sorted(RAW_ROOT.glob("*/node_epoch_metrics.csv")):
        record = scan_run(path)
        if record:
            records.append(record)
    if not records:
        print(f"no scan data found under {RAW_ROOT}")
        return 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    fields = list(records[0].keys())
    with OUT.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)

    records.sort(
        key=lambda row: (
            float(row["edge_degree_stake_share"]),
            float(row["edge_betweenness_stake_share"]),
        ),
        reverse=True,
    )
    print(f"wrote {OUT}")
    print("top seeds by bottom-degree-quartile stake share:")
    for row in records[:8]:
        print(
            "gini={stake_gini} seed={seed_index} "
            "edge_degree_share={edge_degree_stake_share:.3f} "
            "edge_betweenness_share={edge_betweenness_stake_share:.3f} "
            "stake_degree_corr={stake_degree_corr:.3f} "
            "top10_in_edge={top10_stake_nodes_in_edge_degree}".format(
                stake_gini=row["stake_gini"],
                seed_index=row["seed_index"],
                edge_degree_stake_share=float(row["edge_degree_stake_share"]),
                edge_betweenness_stake_share=float(row["edge_betweenness_stake_share"]),
                stake_degree_corr=float(row["stake_degree_corr"]),
                top10_stake_nodes_in_edge_degree=row["top10_stake_nodes_in_edge_degree"],
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
