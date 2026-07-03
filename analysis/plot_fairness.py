#!/usr/bin/env python3
import argparse
import math
import statistics
from collections import defaultdict

from plot_common import FIGURES, PROCESSED, mean_ci, read_csv, to_float


REWARD_FAIRNESS_SEED_INDEX = "0"
PROTOCOL_LABELS = {
    "pos": "PoS",
    "topostake_eta0": r"TopoStake-$\eta0$",
    "topostake": "TopoStake",
}


def write_line_pdf(path, title, xlabel, ylabel, series, show_errorbars=True, zero_line=False):
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print(f"warning: matplotlib is not available; skipped {path}")
        return

    series = {name: points for name, points in series.items() if points}
    if not series:
        if path.exists():
            path.unlink()
        print(f"warning: no data available; skipped {path}")
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(4.8, 3.2))
    for name, points in sorted(series.items()):
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        yerr = [point[2] for point in points]
        if show_errorbars:
            ax.errorbar(xs, ys, yerr=yerr, marker="o", linewidth=1.6, capsize=2.5, label=name)
        else:
            ax.plot(xs, ys, marker="o", linewidth=1.6, label=name)
    if zero_line:
        ax.axhline(0.0, color="#666666", linewidth=1.0, linestyle="--", alpha=0.8)
    ax.set_xlabel(xlabel, fontsize=15)
    ax.set_ylabel(ylabel, fontsize=15)
    ax.set_xticks(sorted({point[0] for points in series.values() for point in points}))
    ax.tick_params(axis="both", labelsize=13)
    ax.grid(True, alpha=0.25)
    ax.legend(frameon=False, fontsize=12)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


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


def hhi(values):
    clean = [v for v in values if not math.isnan(v)]
    total = sum(clean)
    if total <= 0:
        return 0.0
    return sum((value / total) ** 2 for value in clean)


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


def expected_rewards_for_run(rows):
    by_epoch = defaultdict(list)
    for row in rows:
        by_epoch[row.get("epoch", "")].append(row)

    rewards_by_validator = defaultdict(float)
    for epoch_rows in by_epoch.values():
        total_proposer_reward = sum(to_float(row.get("proposer_reward"), 0.0) for row in epoch_rows)
        total_stake = sum(to_float(row.get("economic_stake"), 0.0) for row in epoch_rows)
        protocol_label = epoch_rows[0].get("protocol_label", "")

        for row in epoch_rows:
            validator = row.get("validator_id", "")
            relay_reward = to_float(row.get("relay_reward"), 0.0)
            if protocol_label == "pos" or protocol_label == "topostake_eta0":
                stake = to_float(row.get("economic_stake"), 0.0)
                proposer_share = stake / total_stake if total_stake > 0 else 0.0
            else:
                proposer_share = to_float(row.get("normalized_proposer_weight"), 0.0)
            rewards_by_validator[validator] += proposer_share * total_proposer_reward + relay_reward

    return list(rewards_by_validator.values())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed-index", default=REWARD_FAIRNESS_SEED_INDEX)
    parser.add_argument("--suffix", default="")
    parser.add_argument(
        "--only",
        choices=["all", "reward-gini", "expected-gini", "gini-reduction", "reward-hhi"],
        default="all",
    )
    args = parser.parse_args()
    suffix = f"_{args.suffix}" if args.suffix else ""

    node_rows = [
        row
        for row in read_csv(PROCESSED / "node_epoch_metrics_all.csv")
        if row.get("experiment") == "reward_fairness"
        and row.get("seed_index", "") == str(args.seed_index)
    ]
    by_run = defaultdict(list)
    for row in node_rows:
        by_run[row.get("run_id", "")].append(row)

    reward_gini_points = defaultdict(list)
    reward_hhi_points = defaultdict(list)
    expected_reward_gini_points = defaultdict(list)
    for run_id, rows in by_run.items():
        if not rows:
            continue
        meta = rows[0]
        rewards_by_validator = defaultdict(float)
        for row in rows:
            validator = row.get("validator_id", "")
            rewards_by_validator[validator] += to_float(row.get("relay_reward"), 0.0) + to_float(
                row.get("proposer_reward"), 0.0
            )
        rewards = list(rewards_by_validator.values())
        protocol_label = PROTOCOL_LABELS.get(meta.get("protocol_label", ""), meta.get("protocol_label", ""))
        reward_gini_points[(protocol_label, meta.get("stake_gini", ""))].append(gini(rewards))
        reward_hhi_points[(protocol_label, meta.get("stake_gini", ""))].append(hhi(rewards))
        expected_reward_gini_points[(protocol_label, meta.get("stake_gini", ""))].append(
            gini(expected_rewards_for_run(rows))
        )

    def collapse(points):
        out = defaultdict(list)
        for (series, x), values in points.items():
            avg, ci, n = mean_ci(values)
            if n:
                out[series].append((float(x), avg, ci))
        return {key: sorted(value) for key, value in out.items()}

    def reduction_vs_pos(collapsed):
        baseline = {x: y for x, y, _ in collapsed.get("PoS", collapsed.get("pos", []))}
        out = defaultdict(list)
        for series, points in collapsed.items():
            if series in {"pos", "PoS"}:
                continue
            for x, y, _ in points:
                if x in baseline:
                    out[series].append((x, baseline[x] - y, 0.0))
        return {key: sorted(value) for key, value in out.items()}

    if not suffix:
        for stale in [
            FIGURES / "reward_fairness_reward_gini.svg",
            FIGURES / "reward_fairness_reward_hhi.svg",
            FIGURES / "reward_fairness_contribution_correlation.svg",
            FIGURES / "reward_fairness_contribution_correlation.pdf",
        ]:
            if stale.exists():
                stale.unlink()

    if args.only in {"all", "reward-gini"}:
        write_line_pdf(
            FIGURES / f"reward_fairness_reward_gini{suffix}.pdf",
            "Reward concentration",
            "Stake Gini",
            "Reward Gini",
            collapse(reward_gini_points),
            show_errorbars=False,
        )
    if args.only in {"all", "expected-gini"}:
        write_line_pdf(
            FIGURES / f"reward_fairness_expected_reward_gini{suffix}.pdf",
            "Expected reward concentration",
            "Stake Gini",
            "Expected reward Gini",
            collapse(expected_reward_gini_points),
            show_errorbars=False,
        )
    if args.only in {"all", "gini-reduction"}:
        write_line_pdf(
            FIGURES / f"reward_fairness_expected_reward_gini_reduction{suffix}.pdf",
            "Expected reward concentration",
            "Stake Gini",
            "Gini reduction vs PoS",
            reduction_vs_pos(collapse(expected_reward_gini_points)),
            show_errorbars=False,
            zero_line=True,
        )
    if args.only in {"all", "reward-hhi"}:
        write_line_pdf(
            FIGURES / f"reward_fairness_reward_hhi{suffix}.pdf",
            "Reward concentration",
            "Stake Gini",
            "Reward HHI",
            collapse(reward_hhi_points),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
