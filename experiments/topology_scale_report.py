#!/usr/bin/env python3
"""Validate and summarize topology/scale organic-capture experiments."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from organic_capture_report import (
    BASELINE,
    PAIR_METRICS,
    STRESS,
    aggregate_run,
    mean_ci,
    number,
    write_csv,
)
from run_experiments import PROCESSED_ROOT, ROOT, expand_runs, load_yaml


BOUND_METRICS = (
    "score_dependent_proposer_weight_bound",
    "theoretical_proposer_weight_bound",
)


def condition_key(row: dict[str, Any]) -> tuple[int, str, int, float, str]:
    return (
        int(number(row.get("node_num"))),
        str(row.get("topology", "")),
        int(number(row.get("seed_index"))),
        number(row.get("adversary_stake_fraction")),
        str(row.get("adversary_placement", "")),
    )


def paired_rows(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    index = {
        (*condition_key(row), str(row.get("attack_mode", ""))): row
        for row in runs
        if row.get("complete")
    }
    output: list[dict[str, Any]] = []
    for node_num, topology, seed, stake, placement in sorted(
        {key[:-1] for key in index}
    ):
        baseline = index.get(
            (node_num, topology, seed, stake, placement, BASELINE)
        )
        stress = index.get((node_num, topology, seed, stake, placement, STRESS))
        if not baseline or not stress:
            continue
        for metric in PAIR_METRICS:
            baseline_value = number(baseline.get(metric))
            stress_value = number(stress.get(metric))
            output.append(
                {
                    "node_num": node_num,
                    "topology": topology,
                    "seed_index": seed,
                    "adversary_stake_fraction": stake,
                    "adversary_placement": placement,
                    "metric": metric,
                    "stress_value": stress_value,
                    "baseline_value": baseline_value,
                    "difference": stress_value - baseline_value,
                }
            )
    return output


def group_rows(
    runs: list[dict[str, Any]], pairs: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    grouped: dict[tuple[int, str, str, str, float, str], list[float]] = defaultdict(
        list
    )
    for row in runs:
        if not row.get("complete"):
            continue
        node_num = int(number(row.get("node_num")))
        topology = str(row.get("topology", ""))
        placement = str(row.get("adversary_placement", ""))
        stake = number(row.get("adversary_stake_fraction"))
        series = f"{row.get('attack_mode', '')}:{placement}"
        for metric in PAIR_METRICS + BOUND_METRICS:
            grouped[(node_num, topology, series, placement, stake, metric)].append(
                number(row.get(metric))
            )
    for row in pairs:
        node_num = int(number(row.get("node_num")))
        topology = str(row.get("topology", ""))
        placement = str(row.get("adversary_placement", ""))
        stake = number(row.get("adversary_stake_fraction"))
        series = f"{STRESS}-minus-{BASELINE}:{placement}"
        grouped[
            (node_num, topology, series, placement, stake, str(row["metric"]))
        ].append(number(row["difference"]))

    output: list[dict[str, Any]] = []
    for (node_num, topology, series, placement, stake, metric), values in sorted(
        grouped.items()
    ):
        mean, ci, count = mean_ci(values)
        output.append(
            {
                "node_num": node_num,
                "topology": topology,
                "series": series,
                "adversary_placement": placement,
                "adversary_stake_fraction": stake,
                "metric": metric,
                "n": count,
                "mean": mean,
                "ci95": ci,
                "ci95_low": mean - ci,
                "ci95_high": mean + ci,
            }
        )
    return output


def percentile(values: list[int], probability: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = max(0, math.ceil(probability * len(ordered)) - 1)
    return ordered[index]


def graph_profile(path: Path, expected_nodes: int) -> dict[str, Any]:
    try:
        raw_edges = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw_edges = []
    edges: set[tuple[str, str]] = set()
    malformed = 0
    for raw in raw_edges:
        if not isinstance(raw, list) or len(raw) != 2:
            malformed += 1
            continue
        source, target = str(raw[0]), str(raw[1])
        if source == target:
            malformed += 1
            continue
        edges.add((source, target) if source < target else (target, source))

    adjacency: dict[str, set[str]] = defaultdict(set)
    for source, target in edges:
        adjacency[source].add(target)
        adjacency[target].add(source)
    observed_nodes = len(adjacency)
    visited: set[str] = set()
    if adjacency:
        queue = deque([next(iter(adjacency))])
        while queue:
            node = queue.popleft()
            if node in visited:
                continue
            visited.add(node)
            queue.extend(adjacency[node] - visited)
    degrees = [len(neighbors) for neighbors in adjacency.values()]
    canonical = json.dumps(sorted(edges), separators=(",", ":"))
    return {
        "graph_path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
        "graph_hash": hashlib.sha256(canonical.encode()).hexdigest(),
        "node_count": expected_nodes,
        "observed_node_count": observed_nodes,
        "edge_count": len(edges),
        "average_degree": 2.0 * len(edges) / expected_nodes if expected_nodes else 0.0,
        "median_degree": percentile(degrees, 0.5),
        "p90_degree": percentile(degrees, 0.9),
        "p95_degree": percentile(degrees, 0.95),
        "max_degree": max(degrees, default=0),
        "fraction_degree_le_16": (
            sum(degree <= 16 for degree in degrees) / expected_nodes
            if expected_nodes
            else 0.0
        ),
        "fraction_degree_lt_50": (
            sum(degree < 50 for degree in degrees) / expected_nodes
            if expected_nodes
            else 0.0
        ),
        "connected": observed_nodes == expected_nodes and len(visited) == expected_nodes,
        "malformed_edges": malformed,
    }


def topology_profiles(expected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    indexed: dict[tuple[int, str, int], list[Path]] = defaultdict(list)
    for run in expected:
        key = (
            int(number(run.get("node_num"))),
            str(run.get("topology", "")),
            int(number(run.get("seed_index"))),
        )
        indexed[key].append(Path(run["output_dir"]) / "graph.json")

    output: list[dict[str, Any]] = []
    for (node_num, topology, seed), paths in sorted(indexed.items()):
        existing = [path for path in paths if path.exists()]
        if not existing:
            profile = graph_profile(paths[0], node_num)
            hashes: set[str] = set()
        else:
            profiles = [graph_profile(path, node_num) for path in existing]
            profile = profiles[0]
            hashes = {item["graph_hash"] for item in profiles}
        profile.update(
            {
                "topology": topology,
                "seed_index": seed,
                "graph_variants": len(hashes),
                "graph_files": len(existing),
                "expected_graph_files": len(paths),
            }
        )
        output.append(profile)
    return output


def summary_markdown(
    suite: str,
    runs: list[dict[str, Any]],
    profiles: list[dict[str, Any]],
    checks: list[dict[str, Any]],
) -> str:
    seed_count = len({int(number(row.get("seed_index"))) for row in runs})
    lines = [
        f"# {suite}",
        "",
        (
            "This pilot validates matrix separation and artifact quality; one seed is not a paper estimate."
            if seed_count == 1
            else f"This paired scale study aggregates {seed_count} independent seeds per condition."
        ),
        "",
        "## Acceptance",
        "",
    ]
    lines.extend(
        f"- {'PASS' if check['passed'] else 'FAIL'}: {check['name']} ({check['detail']})"
        for check in checks
    )
    lines.extend(
        [
            "",
            "## Topology profiles",
            "",
            "| nodes | topology | avg degree | median | p95 | max | <=16 | <50 | connected |",
            "|---:|---|---:|---:|---:|---:|---:|---:|:---:|",
        ]
    )
    for row in profiles:
        lines.append(
            "| {node_count} | {topology} | {average_degree:.2f} | {median_degree} | "
            "{p95_degree} | {max_degree} | {fraction_degree_le_16:.3f} | "
            "{fraction_degree_lt_50:.3f} | {connected} |".format(**row)
        )
    lines.extend(
        [
            "",
            "## Runtime",
            "",
            "| nodes | topology | mode | runs | mean (s) | min--max (s) | complete |",
            "|---:|---|---|---:|---:|---:|:---:|",
        ]
    )
    runtime_groups: dict[tuple[int, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in runs:
        runtime_groups[
            (
                int(number(row.get("node_num"))),
                str(row.get("topology", "")),
                str(row.get("attack_mode", "")),
            )
        ].append(row)
    for (nodes, topology, mode), rows in sorted(runtime_groups.items()):
        durations = [number(row.get("duration_seconds")) for row in rows]
        lines.append(
            "| {nodes} | {topology} | {mode} | {count} | {mean:.3f} | "
            "{minimum:.3f}--{maximum:.3f} | {complete}/{count} |".format(
                nodes=nodes,
                topology=topology,
                mode=mode,
                count=len(rows),
                mean=statistics.mean(durations) if durations else 0.0,
                minimum=min(durations, default=0.0),
                maximum=max(durations, default=0.0),
                complete=sum(bool(row.get("complete")) for row in rows),
            )
        )
    lines.extend(
        [
            "",
            "## Envelope diagnostic",
            "",
            f"- Complete runs: {sum(bool(row.get('complete')) for row in runs)}/{len(runs)}",
            "- Violating epochs: "
            + str(sum(int(number(row.get("bound_violation_count"))) for row in runs)),
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--allow-incomplete", action="store_true")
    args = parser.parse_args()
    config_path = (ROOT / args.config).resolve()
    spec = load_yaml(config_path)
    expected = expand_runs(spec)
    runs = [aggregate_run(run) for run in expected]
    pairs = paired_rows(runs)
    groups = group_rows(runs, pairs)
    profiles = topology_profiles(expected)
    complete = [row for row in runs if row.get("complete")]

    def describe_runs(rows: list[dict[str, Any]], limit: int = 6) -> str:
        labels = [
            "n={node_num},topology={topology},stake={stake:.2f},placement={placement},mode={mode}".format(
                node_num=int(number(row.get("node_num"))),
                topology=str(row.get("topology", "")),
                stake=number(row.get("adversary_stake_fraction")),
                placement=str(row.get("adversary_placement", "")),
                mode=str(row.get("attack_mode", "")),
            )
            for row in rows[:limit]
        ]
        suffix = "" if len(rows) <= limit else f"; ... and {len(rows) - limit} more"
        return "; ".join(labels) + suffix

    zero_organic_runs = [
        row for row in complete if number(row.get("organic_included_tx")) <= 0.0
    ]
    zero_valid_path_runs = [
        row
        for row in complete
        if number(row.get("organic_valid_path_count")) <= 0.0
    ]

    expected_conditions = {condition_key(run) for run in expected}
    assignment_index: dict[tuple[int, str, int, float, str], set[str]] = defaultdict(
        set
    )
    for row in complete:
        assignment_index[condition_key(row)].add(
            str(row.get("adversary_assignment_hash", ""))
        )
    assignment_mismatches = sum(
        len(values) != 1 for values in assignment_index.values()
    )
    accounting_errors = sum(
        number(row.get("adversary_organic_relay_reward"))
        > number(row.get("organic_relay_reward")) + 1e-12
        or number(row.get("adversary_organic_raw_contribution"))
        > number(row.get("organic_raw_contribution")) + 1e-12
        for row in complete
    )
    finite_metrics = PAIR_METRICS + BOUND_METRICS
    non_finite = sum(
        not math.isfinite(number(row.get(metric), math.nan))
        for row in complete
        for metric in finite_metrics
    )
    revisions = {str(row.get("git_commit_sha", "")) for row in complete}
    topology_failures = sum(
        not row["connected"]
        or row["malformed_edges"] != 0
        or (row["graph_files"] > 0 and row["graph_variants"] != 1)
        for row in profiles
    )
    requires_eth_calibration = any(
        row["topology"] == "eth_empirical" and int(row["node_count"]) >= 1000
        for row in profiles
    )
    calibration_failures = sum(
        not 17.5 <= number(row["average_degree"]) <= 18.5
        or number(row["fraction_degree_le_16"]) < 0.5
        or number(row["fraction_degree_lt_50"]) < 0.93
        for row in profiles
        if row["topology"] == "eth_empirical" and int(row["node_count"]) >= 1000
    )
    expected_pairs = len(expected_conditions) * len(PAIR_METRICS)
    violating_epochs = sum(
        int(number(row.get("bound_violation_count"))) for row in complete
    )
    checks = [
        {
            "name": "run-completeness",
            "passed": len(complete) == len(expected),
            "detail": f"complete={len(complete)}/{len(expected)}",
        },
        {
            "name": "paired-completeness",
            "passed": len(pairs) == expected_pairs,
            "detail": f"metric pairs={len(pairs)}/{expected_pairs}",
        },
        {
            "name": "adversary-assignment",
            "passed": assignment_mismatches == 0,
            "detail": f"paired assignment mismatches={assignment_mismatches}",
        },
        {
            "name": "single-revision",
            "passed": len(revisions) == 1 and "" not in revisions,
            "detail": f"revisions={sorted(revisions)}",
        },
        {
            "name": "organic-traffic-observed",
            "passed": bool(complete) and not zero_organic_runs,
            "detail": f"zero-organic runs={len(zero_organic_runs)}"
            + (f"; {describe_runs(zero_organic_runs)}" if zero_organic_runs else ""),
        },
        {
            "name": "valid-organic-paths-observed",
            "passed": bool(complete) and not zero_valid_path_runs,
            "detail": f"zero-valid-path runs={len(zero_valid_path_runs)}"
            + (
                f"; {describe_runs(zero_valid_path_runs)}"
                if zero_valid_path_runs
                else ""
            ),
        },
        {
            "name": "organic-capture-accounting",
            "passed": accounting_errors == 0,
            "detail": f"accounting errors={accounting_errors}",
        },
        {
            "name": "finite-metrics",
            "passed": non_finite == 0,
            "detail": f"non-finite values={non_finite}",
        },
        {
            "name": "topology-artifacts",
            "passed": topology_failures == 0 and bool(profiles),
            "detail": f"invalid/inconsistent profiles={topology_failures}",
        },
        {
            "name": "eth-empirical-calibration",
            "passed": not requires_eth_calibration or calibration_failures == 0,
            "detail": (
                f"calibration failures={calibration_failures}"
                if requires_eth_calibration
                else "not requested by this matrix"
            ),
        },
        {
            "name": "proposer-envelope",
            "passed": violating_epochs == 0,
            "detail": f"violating epochs={violating_epochs}",
        },
    ]
    passed = all(check["passed"] for check in checks)
    suite = str(spec.get("suite", config_path.stem))
    prefix = PROCESSED_ROOT / suite
    write_csv(prefix.with_name(prefix.name + "_runs.csv"), runs)
    write_csv(prefix.with_name(prefix.name + "_paired.csv"), pairs)
    write_csv(prefix.with_name(prefix.name + "_groups.csv"), groups)
    write_csv(prefix.with_name(prefix.name + "_topologies.csv"), profiles)
    acceptance = {
        "suite": suite,
        "protocol_version": spec.get("protocol_version", ""),
        "expected_runs": len(expected),
        "successful_runs": len(complete),
        "passed": passed,
        "checks": checks,
    }
    acceptance_path = prefix.with_name(prefix.name + "_acceptance.json")
    acceptance_path.write_text(
        json.dumps(acceptance, indent=2) + "\n", encoding="utf-8"
    )
    summary_path = prefix.with_name(prefix.name + "_summary.md")
    summary_path.write_text(
        summary_markdown(suite, runs, profiles, checks), encoding="utf-8"
    )
    print(json.dumps(acceptance, indent=2))
    return 0 if passed or args.allow_incomplete else 1


if __name__ == "__main__":
    raise SystemExit(main())
