#!/usr/bin/env python3
import math
import statistics
from collections import defaultdict

from plot_common import FIGURES, PROCESSED, mean_ci, read_csv, to_float, write_line_svg


def gini(values):
    clean = sorted(v for v in values if not math.isnan(v))
    if not clean:
        return math.nan
    total = sum(clean)
    if total <= 0:
        return 0.0
    n = len(clean)
    weighted = sum((idx + 1) * value for idx, value in enumerate(clean))
    return max(0.0, min(1.0, (2 * weighted) / (n * total) - (n + 1) / n))


def corr(xs, ys):
    pairs = [(x, y) for x, y in zip(xs, ys) if not math.isnan(x) and not math.isnan(y)]
    if len(pairs) < 2:
        return math.nan
    x_vals, y_vals = zip(*pairs)
    mx, my = statistics.mean(x_vals), statistics.mean(y_vals)
    num = sum((x - mx) * (y - my) for x, y in pairs)
    den_x = math.sqrt(sum((x - mx) ** 2 for x in x_vals))
    den_y = math.sqrt(sum((y - my) ** 2 for y in y_vals))
    if den_x == 0 or den_y == 0:
        return math.nan
    return num / (den_x * den_y)


def main() -> int:
    node_rows = [
        row
        for row in read_csv(PROCESSED / "node_epoch_metrics_all.csv")
        if row.get("experiment") == "reward_fairness"
    ]
    by_run = defaultdict(list)
    for row in node_rows:
        by_run[row.get("run_id", "")].append(row)

    reward_gini_points = defaultdict(list)
    corr_points = defaultdict(list)
    for run_id, rows in by_run.items():
        if not rows:
            continue
        meta = rows[0]
        rewards_by_validator = defaultdict(float)
        raw_by_validator = defaultdict(float)
        for row in rows:
            validator = row.get("validator_id", "")
            rewards_by_validator[validator] += to_float(row.get("relay_reward"), 0.0) + to_float(
                row.get("proposer_reward"), 0.0
            )
            raw_by_validator[validator] += to_float(row.get("raw_contribution"), 0.0)
        rewards = list(rewards_by_validator.values())
        raws = [raw_by_validator[key] for key in rewards_by_validator]
        reward_gini_points[(meta.get("protocol_label", ""), meta.get("stake_gini", ""))].append(gini(rewards))
        corr_points[(meta.get("protocol_label", ""), meta.get("stake_gini", ""))].append(corr(raws, rewards))

    def collapse(points):
        out = defaultdict(list)
        for (series, x), values in points.items():
            avg, ci, n = mean_ci(values)
            if n:
                out[series].append((float(x), avg, ci))
        return {key: sorted(value) for key, value in out.items()}

    write_line_svg(
        FIGURES / "reward_fairness_reward_gini.svg",
        "Reward concentration",
        "Stake Gini",
        "Reward Gini",
        collapse(reward_gini_points),
    )
    write_line_svg(
        FIGURES / "reward_fairness_contribution_correlation.svg",
        "Contribution/reward correlation",
        "Stake Gini",
        "Correlation",
        collapse(corr_points),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
