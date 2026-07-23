#!/usr/bin/env python3
"""Calibrate and solve a reduced-form endogenous relay-participation model."""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import statistics
from collections import defaultdict
from pathlib import Path
from statistics import NormalDist
from typing import Any, Iterable, Sequence

from run_experiments import PROCESSED_ROOT, ROOT, load_yaml, write_json


ARM_COLUMNS = {"fee_only": "fee_only_value", "full": "full_value"}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else []
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def percentile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return math.nan
    if len(ordered) == 1:
        return ordered[0]
    position = probability * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def geometric_mean(values: Iterable[float]) -> float:
    materialized = list(values)
    if not materialized or any(value <= 0.0 for value in materialized):
        raise ValueError("geometric mean requires positive values")
    return math.exp(statistics.fmean(math.log(value) for value in materialized))


def logarithmic_grid(minimum: float, maximum: float, count: int) -> list[float]:
    if minimum <= 0.0 or maximum <= minimum or count < 2:
        raise ValueError("invalid logarithmic-grid bounds")
    start = math.log(minimum)
    step = (math.log(maximum) - start) / (count - 1)
    return [math.exp(start + index * step) for index in range(count)]


def prepare_index(
    rows: list[dict[str, str]],
) -> tuple[dict[tuple[int, float, str], dict[str, str]], list[int], int]:
    index: dict[tuple[int, float, str], dict[str, str]] = {}
    duplicates = 0
    seeds = set()
    for row in rows:
        seed = int(row["seed_index"])
        fraction = float(row["lazy_fraction"])
        metric = row["metric"]
        key = (seed, fraction, metric)
        if key in index:
            duplicates += 1
        index[key] = row
        seeds.add(seed)
    return index, sorted(seeds), duplicates


def metric_values(
    index: dict[tuple[int, float, str], dict[str, str]],
    seeds: Sequence[int],
    fraction: float,
    metric: str,
    arm: str,
) -> list[float]:
    column = ARM_COLUMNS[arm]
    return [float(index[(seed, fraction, metric)][column]) for seed in seeds]


def benefit_curve(
    index: dict[tuple[int, float, str], dict[str, str]],
    seeds: Sequence[int],
    fractions: Sequence[float],
    reward_metric: str,
    work_metric: str,
    arm: str,
) -> list[float]:
    curve = []
    for fraction in fractions:
        rewards = metric_values(index, seeds, fraction, reward_metric, arm)
        work = metric_values(index, seeds, fraction, work_metric, arm)
        denominator = sum(work)
        if denominator <= 0.0:
            raise ValueError(
                f"non-positive forwarding-work denominator for {arm}, q={fraction}"
            )
        curve.append(sum(rewards) / denominator)
    return curve


def pooled_latency_curve(
    index: dict[tuple[int, float, str], dict[str, str]],
    seeds: Sequence[int],
    fractions: Sequence[float],
    latency_metric: str,
) -> list[float]:
    curve = []
    for fraction in fractions:
        values = []
        for arm in ARM_COLUMNS:
            values.extend(
                metric_values(index, seeds, fraction, latency_metric, arm)
            )
        curve.append(statistics.fmean(values))
    return curve


def interpolate_curve(
    x: float, xs: Sequence[float], ys: Sequence[float], mode: str
) -> float:
    if len(xs) != len(ys) or len(xs) < 2:
        raise ValueError("curve interpolation requires matching points")
    if mode not in {"linear", "clamp"}:
        raise ValueError(f"unknown interpolation mode: {mode}")
    if x <= xs[0]:
        if mode == "clamp":
            return ys[0]
        value = ys[0] + (x - xs[0]) * (ys[1] - ys[0]) / (xs[1] - xs[0])
        return max(0.0, value)
    if x >= xs[-1]:
        if mode == "clamp":
            return ys[-1]
        value = ys[-1] + (x - xs[-1]) * (ys[-1] - ys[-2]) / (
            xs[-1] - xs[-2]
        )
        return max(0.0, value)
    for index in range(len(xs) - 1):
        if xs[index] <= x <= xs[index + 1]:
            return ys[index] + (x - xs[index]) * (
                ys[index + 1] - ys[index]
            ) / (xs[index + 1] - xs[index])
    raise AssertionError("interpolation interval not found")


def lognormal_cdf(value: float, median: float, log_sigma: float) -> float:
    if value <= 0.0:
        return 0.0
    if median <= 0.0 or log_sigma <= 0.0:
        raise ValueError("lognormal parameters must be positive")
    return NormalDist().cdf((math.log(value) - math.log(median)) / log_sigma)


def response_probability(
    active_fraction: float,
    fractions: Sequence[float],
    curve: Sequence[float],
    cost_median: float,
    log_sigma: float,
    interpolation_mode: str,
) -> float:
    lazy_fraction = 1.0 - active_fraction
    benefit = interpolate_curve(
        lazy_fraction, fractions, curve, interpolation_mode
    )
    return lognormal_cdf(benefit, cost_median, log_sigma)


def solve_fixed_point(
    fractions: Sequence[float],
    curve: Sequence[float],
    cost_median: float,
    log_sigma: float,
    interpolation_mode: str,
) -> float:
    def residual(active_fraction: float) -> float:
        return response_probability(
            active_fraction,
            fractions,
            curve,
            cost_median,
            log_sigma,
            interpolation_mode,
        ) - active_fraction

    low, high = 0.0, 1.0
    if residual(low) <= 0.0:
        return low
    if residual(high) >= 0.0:
        return high
    for _ in range(100):
        middle = (low + high) / 2.0
        if residual(middle) > 0.0:
            low = middle
        else:
            high = middle
    return (low + high) / 2.0


def iterate_response(
    initial_active_fraction: float,
    fractions: Sequence[float],
    curve: Sequence[float],
    cost_median: float,
    log_sigma: float,
    interpolation_mode: str,
    update_rate: float,
    max_steps: int,
    tolerance: float,
) -> tuple[float, int, bool]:
    active = initial_active_fraction
    for step in range(1, max_steps + 1):
        target = response_probability(
            active,
            fractions,
            curve,
            cost_median,
            log_sigma,
            interpolation_mode,
        )
        updated = (1.0 - update_rate) * active + update_rate * target
        if abs(updated - active) <= tolerance:
            return updated, step, True
        active = updated
    return active, max_steps, False


def supported_latency(
    active_fraction: float,
    fractions: Sequence[float],
    latency_curve: Sequence[float],
) -> float | None:
    lazy_fraction = 1.0 - active_fraction
    if lazy_fraction < fractions[0] or lazy_fraction > fractions[-1]:
        return None
    return interpolate_curve(lazy_fraction, fractions, latency_curve, "linear")


def confidence(values: Sequence[float]) -> tuple[float, float, float]:
    return (
        statistics.fmean(values),
        percentile(values, 0.025),
        percentile(values, 0.975),
    )


def markdown_summary(
    profile: dict[str, Any],
    benefit_rows: list[dict[str, Any]],
    regime_rows: list[dict[str, Any]],
    sensitivity_rows: list[dict[str, Any]],
    acceptance: dict[str, Any],
) -> str:
    lines = [
        "# Endogenous relay-participation mean-field pilot",
        "",
        "This reduced-form pilot asks whether the measured expected reward advantage can support a materially higher endogenous active fraction under heterogeneous relay costs. It is a calibrated behavioral sensitivity analysis, not an equilibrium proof.",
        "",
        "## Input audit",
        "",
        f"- Paired seeds: {profile['seed_count']}",
        f"- Input rows: {profile['row_count']} ({profile['duplicate_keys']} duplicate keys)",
        f"- Lazy-fraction support: {', '.join(f'{value:.0%}' for value in profile['lazy_fractions'])}",
        "- Benefit is the ratio of summed expected active-minus-lazy reward per stake to summed extra forwarding work per stake; per-seed ratios are not averaged.",
        "",
        "## Empirical break-even benefit",
        "",
        "| Lazy fraction | Fee-only | Full TopoStake | Full / fee-only |",
        "|---:|---:|---:|---:|",
    ]
    for row in benefit_rows:
        lines.append(
            f"| {row['lazy_fraction']:.0%} | {row['fee_only_benefit']:.3e} | "
            f"{row['full_benefit']:.3e} | {row['benefit_ratio']:.2f}x |"
        )
    lines.extend(
        [
            "",
            "## Pre-specified calibration cost regimes",
            "",
            "The cost median is expressed relative to the geometric mean of the fee-only break-even curve. The primary cost heterogeneity is lognormal with log-sigma 0.75. These regimes are transparent calibration assumptions, not measurements of validator operating costs.",
            "",
            "| Regime | Median multiplier | Fee-only active | Full active | Gain | 95% bootstrap CI | Projected p95 latency |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in regime_rows:
        latency = (
            f"{row['fee_only_latency_s']:.2f}s -> {row['full_latency_s']:.2f}s"
            if row["latency_supported"]
            else "outside measured q support"
        )
        lines.append(
            f"| {row['regime']} | {row['cost_multiplier']:.2f}x | "
            f"{row['fee_only_active_fraction']:.1%} | {row['full_active_fraction']:.1%} | "
            f"{row['participation_gain']:.1%} | "
            f"[{row['gain_ci_low']:.1%}, {row['gain_ci_high']:.1%}] | {latency} |"
        )
    min_gain = min(row["participation_gain"] for row in sensitivity_rows)
    max_gain = max(row["participation_gain"] for row in sensitivity_rows)
    lines.extend(
        [
            "",
            "## Sensitivity and decision",
            "",
            f"Across the pre-specified cost regimes, log-sigma values, and linear/clamped endpoint treatments, the Full-minus-fee active-fraction gain ranges from {min_gain:.1%} to {max_gain:.1%}.",
            f"Initialization sensitivity is evaluated with damped responses from 25%, 50%, and 75% initial participation; the maximum terminal spread is {acceptance['diagnostics']['maximum_initialization_spread']:.3%}.",
            "",
            "Rust-prototype go/no-go result: **"
            + ("GO" if acceptance["pass"] else "NO-GO")
            + "**",
            "",
        ]
    )
    for name, passed in acceptance["checks"].items():
        lines.append(f"- {name}: {'pass' if passed else 'FAIL'}")
    lines.extend(
        [
            "",
            "The latency values are projections through the existing exogenous participation--latency curve and are reported only when both fixed points remain inside its measured 25%--75% lazy-fraction support. They are not new end-to-end causal observations.",
            "With positive relay cost and no relay-derived benefit, the corresponding PoS reduced-form baseline selects the lazy strategy for the entire population; this is a modeling baseline, not an observation of real PoS validator behavior.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        default="experiments/configs/frozen_v1_endogenous_participation_pilot.yaml",
    )
    parser.add_argument("--paired", type=Path)
    args = parser.parse_args()

    config_path = (ROOT / args.config).resolve()
    spec = load_yaml(config_path)
    paired_path = args.paired or (ROOT / spec["input_paired_csv"])
    paired_path = paired_path.resolve()
    rows = read_csv(paired_path)
    index, seeds, duplicate_keys = prepare_index(rows)
    fractions = list(map(float, spec["lazy_fractions"]))
    metrics = spec["metrics"]
    required_metrics = [
        metrics["expected_reward_premium"],
        metrics["forwarding_work_premium"],
        metrics["latency"],
    ]
    missing = [
        (seed, fraction, metric)
        for seed in seeds
        for fraction in fractions
        for metric in required_metrics
        if (seed, fraction, metric) not in index
    ]
    if missing:
        raise ValueError(f"missing {len(missing)} required paired metric rows")

    curves = {
        arm: benefit_curve(
            index,
            seeds,
            fractions,
            metrics["expected_reward_premium"],
            metrics["forwarding_work_premium"],
            arm,
        )
        for arm in ARM_COLUMNS
    }
    latency_curve = pooled_latency_curve(
        index, seeds, fractions, metrics["latency"]
    )
    fee_reference = geometric_mean(curves["fee_only"])
    cost = spec["cost_model"]
    multipliers = logarithmic_grid(
        float(cost["sweep_min_multiplier"]),
        float(cost["sweep_max_multiplier"]),
        int(cost["sweep_points"]),
    )
    regime_multipliers = {
        str(name): float(value) for name, value in cost["regime_multipliers"].items()
    }
    for multiplier in regime_multipliers.values():
        if not any(math.isclose(multiplier, value) for value in multipliers):
            multipliers.append(multiplier)
    multipliers = sorted(set(multipliers))
    primary_sigma = float(cost["primary_log_sigma"])
    sigmas = sorted(set(map(float, cost["log_sigma_sensitivity"])))
    curve_modes = [str(spec["curve_model"]["primary"])] + list(
        map(str, spec["curve_model"].get("sensitivity", []))
    )
    curve_modes = list(dict.fromkeys(curve_modes))

    point_rows = []
    point_index: dict[tuple[str, float, float], dict[str, Any]] = {}
    dynamics = spec["dynamics"]
    for mode in curve_modes:
        for sigma in sigmas:
            for multiplier in multipliers:
                median = fee_reference * multiplier
                arm_values = {
                    arm: solve_fixed_point(
                        fractions, curve, median, sigma, mode
                    )
                    for arm, curve in curves.items()
                }
                initial_terminals: dict[str, list[float]] = defaultdict(list)
                all_converged = True
                max_steps = 0
                for arm, curve in curves.items():
                    for initial in map(
                        float, dynamics["initial_active_fractions"]
                    ):
                        terminal, steps, converged = iterate_response(
                            initial,
                            fractions,
                            curve,
                            median,
                            sigma,
                            mode,
                            float(dynamics["update_rate"]),
                            int(dynamics["max_steps"]),
                            float(dynamics["tolerance"]),
                        )
                        initial_terminals[arm].append(terminal)
                        all_converged = all_converged and converged
                        max_steps = max(max_steps, steps)
                fee_latency = supported_latency(
                    arm_values["fee_only"], fractions, latency_curve
                )
                full_latency = supported_latency(
                    arm_values["full"], fractions, latency_curve
                )
                row = {
                    "interpolation_mode": mode,
                    "log_sigma": sigma,
                    "cost_multiplier": multiplier,
                    "cost_median": median,
                    "fee_only_active_fraction": arm_values["fee_only"],
                    "full_active_fraction": arm_values["full"],
                    "participation_gain": arm_values["full"]
                    - arm_values["fee_only"],
                    "fee_only_lazy_fraction": 1.0 - arm_values["fee_only"],
                    "full_lazy_fraction": 1.0 - arm_values["full"],
                    "latency_supported": fee_latency is not None
                    and full_latency is not None,
                    "fee_only_latency_s": fee_latency if fee_latency is not None else "",
                    "full_latency_s": full_latency if full_latency is not None else "",
                    "projected_latency_reduction_s": (
                        fee_latency - full_latency
                        if fee_latency is not None and full_latency is not None
                        else ""
                    ),
                    "fee_only_initialization_spread": max(
                        initial_terminals["fee_only"]
                    )
                    - min(initial_terminals["fee_only"]),
                    "full_initialization_spread": max(initial_terminals["full"])
                    - min(initial_terminals["full"]),
                    "dynamics_converged": all_converged,
                    "maximum_convergence_steps": max_steps,
                }
                point_rows.append(row)
                point_index[(mode, sigma, multiplier)] = row

    primary_mode = str(spec["curve_model"]["primary"])
    bootstrap = spec["bootstrap"]
    rng = random.Random(int(bootstrap["seed"]))
    bootstrap_samples = int(bootstrap["samples"])
    bootstrap_values: dict[tuple[float, str], list[float]] = defaultdict(list)
    bootstrap_gain: dict[float, list[float]] = defaultdict(list)
    bootstrap_benefits: dict[tuple[float, str], list[float]] = defaultdict(list)
    for _ in range(bootstrap_samples):
        sampled = [rng.choice(seeds) for _seed in seeds]
        sampled_curves = {
            arm: benefit_curve(
                index,
                sampled,
                fractions,
                metrics["expected_reward_premium"],
                metrics["forwarding_work_premium"],
                arm,
            )
            for arm in ARM_COLUMNS
        }
        for fraction, fee_value, full_value in zip(
            fractions, sampled_curves["fee_only"], sampled_curves["full"]
        ):
            bootstrap_benefits[(fraction, "fee_only")].append(fee_value)
            bootstrap_benefits[(fraction, "full")].append(full_value)
        for multiplier in multipliers:
            median = fee_reference * multiplier
            arm_values = {
                arm: solve_fixed_point(
                    fractions,
                    curve,
                    median,
                    primary_sigma,
                    primary_mode,
                )
                for arm, curve in sampled_curves.items()
            }
            for arm, value in arm_values.items():
                bootstrap_values[(multiplier, arm)].append(value)
            bootstrap_gain[multiplier].append(
                arm_values["full"] - arm_values["fee_only"]
            )

    sweep_rows = []
    for multiplier in multipliers:
        point = point_index[(primary_mode, primary_sigma, multiplier)]
        fee_mean, fee_low, fee_high = confidence(
            bootstrap_values[(multiplier, "fee_only")]
        )
        full_mean, full_low, full_high = confidence(
            bootstrap_values[(multiplier, "full")]
        )
        gain_mean, gain_low, gain_high = confidence(bootstrap_gain[multiplier])
        sweep_rows.append(
            {
                "cost_multiplier": multiplier,
                "cost_median": fee_reference * multiplier,
                "fee_only_active_fraction": point["fee_only_active_fraction"],
                "fee_only_bootstrap_mean": fee_mean,
                "fee_only_ci_low": fee_low,
                "fee_only_ci_high": fee_high,
                "full_active_fraction": point["full_active_fraction"],
                "full_bootstrap_mean": full_mean,
                "full_ci_low": full_low,
                "full_ci_high": full_high,
                "participation_gain": point["participation_gain"],
                "gain_bootstrap_mean": gain_mean,
                "gain_ci_low": gain_low,
                "gain_ci_high": gain_high,
            }
        )

    benefit_rows = []
    for fraction, fee_value, full_value, latency in zip(
        fractions, curves["fee_only"], curves["full"], latency_curve
    ):
        fee_mean, fee_low, fee_high = confidence(
            bootstrap_benefits[(fraction, "fee_only")]
        )
        full_mean, full_low, full_high = confidence(
            bootstrap_benefits[(fraction, "full")]
        )
        benefit_rows.append(
            {
                "lazy_fraction": fraction,
                "fee_only_benefit": fee_value,
                "fee_only_bootstrap_mean": fee_mean,
                "fee_only_ci_low": fee_low,
                "fee_only_ci_high": fee_high,
                "full_benefit": full_value,
                "full_bootstrap_mean": full_mean,
                "full_ci_low": full_low,
                "full_ci_high": full_high,
                "benefit_ratio": full_value / fee_value,
                "pooled_p95_latency_s": latency,
            }
        )

    regime_rows = []
    for regime, multiplier in regime_multipliers.items():
        point = point_index[(primary_mode, primary_sigma, multiplier)]
        _gain_mean, gain_low, gain_high = confidence(bootstrap_gain[multiplier])
        regime_rows.append(
            {
                "regime": regime,
                **point,
                "gain_ci_low": gain_low,
                "gain_ci_high": gain_high,
            }
        )

    sensitivity_rows = [
        row
        for row in point_rows
        if any(
            math.isclose(float(row["cost_multiplier"]), multiplier)
            for multiplier in regime_multipliers.values()
        )
    ]
    go_no_go = spec["go_no_go"]
    minimum_gain = float(go_no_go["minimum_participation_gain"])
    passing_regimes = sum(
        row["participation_gain"] >= minimum_gain and row["gain_ci_low"] > 0.0
        for row in regime_rows
    )
    maximum_initialization_spread = max(
        max(
            float(row["fee_only_initialization_spread"]),
            float(row["full_initialization_spread"]),
        )
        for row in sensitivity_rows
    )
    checks = {
        "minimum_seed_count": len(seeds)
        >= int(go_no_go["minimum_seed_count"]),
        "unique_input_grain": duplicate_keys == 0,
        "complete_metric_coverage": not missing,
        "positive_aggregate_benefits": all(
            value > 0.0 for curve in curves.values() for value in curve
        ),
        "full_benefit_exceeds_fee_only": all(
            full > fee
            for fee, full in zip(curves["fee_only"], curves["full"])
        ),
        "broad_cost_regime_gain": passing_regimes
        >= int(go_no_go["minimum_passing_cost_regimes"]),
        "initialization_robustness": maximum_initialization_spread
        <= float(go_no_go["maximum_initialization_spread"]),
        "dynamics_converged": all(bool(row["dynamics_converged"]) for row in sensitivity_rows),
    }
    acceptance = {
        "suite": spec["suite"],
        "pass": all(checks.values()),
        "checks": checks,
        "diagnostics": {
            "input_paired_csv": str(paired_path),
            "seed_count": len(seeds),
            "fee_only_cost_reference": fee_reference,
            "passing_cost_regimes": passing_regimes,
            "required_passing_cost_regimes": int(
                go_no_go["minimum_passing_cost_regimes"]
            ),
            "minimum_participation_gain": minimum_gain,
            "maximum_initialization_spread": maximum_initialization_spread,
            "bootstrap_samples": bootstrap_samples,
        },
    }
    profile = {
        "row_count": len(rows),
        "duplicate_keys": duplicate_keys,
        "seed_count": len(seeds),
        "lazy_fractions": fractions,
    }
    output = PROCESSED_ROOT / str(spec["suite"])
    write_csv(output / "benefit_curves.csv", benefit_rows)
    write_csv(output / "fixed_point_sweep.csv", sweep_rows)
    write_csv(output / "cost_regime_summary.csv", regime_rows)
    write_csv(output / "sensitivity.csv", sensitivity_rows)
    write_json(output / "acceptance.json", acceptance)
    (output / "summary.md").write_text(
        markdown_summary(
            profile, benefit_rows, regime_rows, sensitivity_rows, acceptance
        ),
        encoding="utf-8",
    )
    print(json.dumps(acceptance, indent=2))
    print(f"wrote {output.relative_to(ROOT)}")
    return 0 if acceptance["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
