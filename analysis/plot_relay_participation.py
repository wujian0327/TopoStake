#!/usr/bin/env python3
import argparse
import math
import statistics
from collections import defaultdict

from plot_common import FIGURES, PROCESSED, read_csv, to_float


PROFILE_ORDER = ["active", "normal", "lazy"]
PROFILE_COLORS = {
    "active": "#2ca02c",
    "normal": "#1f77b4",
    "lazy": "#d62728",
}
SCORE_BOXPLOT_UPPER_QUANTILE = 0.95
RELAY_SEED_BY_GINI = {
    0.2: 0,
    0.4: 0,
    0.6: 0,
    0.8: 1,
}
RELAY_INCOME_SEED_BY_GINI = {
    0.2: 0,
    0.4: 0,
    0.6: 0,
    0.8: 0,
}


def mean_ci(values):
    clean = [value for value in values if not math.isnan(value)]
    if not clean:
        return math.nan, 0.0
    if len(clean) == 1:
        return clean[0], 0.0
    return statistics.mean(clean), 1.96 * statistics.stdev(clean) / math.sqrt(len(clean))


def trim_upper_quantile(values, quantile):
    clean = sorted(value for value in values if not math.isnan(value))
    if not clean:
        return []
    cutoff_index = max(0, min(len(clean) - 1, math.ceil(len(clean) * quantile) - 1))
    cutoff = clean[cutoff_index]
    return [value for value in clean if value <= cutoff]


def selected_relay_seed(row):
    gini = round(to_float(row.get("stake_gini"), math.nan), 1)
    seed_index = int(to_float(row.get("seed_index"), -1))
    return RELAY_SEED_BY_GINI.get(gini, 0) == seed_index


def selected_relay_income_seed(row):
    gini = round(to_float(row.get("stake_gini"), math.nan), 1)
    seed_index = int(to_float(row.get("seed_index"), -1))
    return RELAY_INCOME_SEED_BY_GINI.get(gini, 0) == seed_index


def selected_seed_index(seed_index):
    def selector(row):
        return int(to_float(row.get("seed_index"), -1)) == seed_index

    return selector


def warmup_filtered_node_rows(seed_selector=selected_relay_seed):
    rows = []
    for row in read_csv(PROCESSED / "node_epoch_metrics_all.csv"):
        if row.get("experiment") != "relay_participation":
            continue
        if not seed_selector(row):
            continue
        warmup = int(to_float(row.get("warmup_epochs"), 0.0))
        epoch = int(to_float(row.get("epoch"), 0.0))
        if epoch >= warmup:
            rows.append(row)
    return rows


def write_profile_line_pdf(path, title, ylabel, metric, profiles, seed_selector=selected_relay_seed):
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print(f"warning: matplotlib is not available; skipped {path}")
        return

    rows = [
        row
        for row in warmup_filtered_node_rows(seed_selector)
        if row.get("protocol_label") == "topostake" and row.get("relay_profile") in PROFILE_ORDER
    ]
    by_run = defaultdict(list)
    for row in rows:
        by_run[row.get("run_id", "")].append(row)

    buckets = defaultdict(list)
    for run_rows in by_run.values():
        if not run_rows:
            continue
        gini = to_float(run_rows[0].get("stake_gini"))
        totals = defaultdict(float)
        counts = defaultdict(int)
        total_reward = 0.0
        for row in run_rows:
            reward = to_float(row.get(metric), 0.0)
            profile = row.get("relay_profile", "")
            totals[profile] += reward
            counts[profile] += 1
            total_reward += reward
        if total_reward <= 0:
            continue
        average_reward = total_reward / len(run_rows)
        for profile in profiles:
            if counts[profile] > 0 and average_reward > 0:
                buckets[(profile, gini)].append((totals[profile] / counts[profile]) / average_reward)

    series = defaultdict(list)
    for (profile, gini), values in buckets.items():
        avg, ci = mean_ci(values)
        if not math.isnan(avg):
            series[profile].append((gini, avg, ci))
    for points in series.values():
        points.sort(key=lambda item: item[0])

    if not series:
        if path.exists():
            path.unlink()
        print(f"warning: no data available; skipped {path}")
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(4.8, 3.2))
    for profile in profiles:
        points = series.get(profile, [])
        if not points:
            continue
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        yerr = [point[2] for point in points]
        ax.errorbar(
            xs,
            ys,
            yerr=yerr,
            marker="o",
            linewidth=1.6,
            capsize=2.5,
            label=profile,
            color=PROFILE_COLORS.get(profile),
        )
    ax.set_xlabel("Stake Gini", fontsize=15)
    ax.set_ylabel(ylabel, fontsize=15)
    ax.set_xticks(sorted({point[0] for points in series.values() for point in points}))
    ax.yaxis.set_major_formatter(plt.FormatStrFormatter("%.2f"))
    ax.tick_params(axis="both", labelsize=13)
    ax.grid(True, alpha=0.25)
    ax.legend(frameon=False, fontsize=12)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def write_score_distribution_pdf(path, seed_selector=selected_relay_seed):
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Patch
    except ImportError:
        print(f"warning: matplotlib is not available; skipped {path}")
        return

    rows = [
        row
        for row in warmup_filtered_node_rows(seed_selector)
        if row.get("protocol_label") == "topostake" and row.get("relay_profile") in PROFILE_ORDER
    ]
    ginis = sorted({to_float(row.get("stake_gini")) for row in rows})
    data = []
    positions = []
    colors = []
    labels = []
    width = 0.22
    for group_idx, gini in enumerate(ginis):
        center = group_idx + 1
        for profile_idx, profile in enumerate(PROFILE_ORDER):
            values = [
                to_float(row.get("raw_contribution"), math.nan)
                for row in rows
                if to_float(row.get("stake_gini")) == gini and row.get("relay_profile") == profile
            ]
            values = trim_upper_quantile(values, SCORE_BOXPLOT_UPPER_QUANTILE)
            if not values:
                continue
            data.append(values)
            positions.append(center + (profile_idx - 1) * width)
            colors.append(PROFILE_COLORS[profile])
            labels.append(profile)

    if not data:
        if path.exists():
            path.unlink()
        print(f"warning: no data available; skipped {path}")
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(4.8, 3.2))
    box = ax.boxplot(data, positions=positions, widths=0.16, patch_artist=True, showfliers=False)
    for patch, color in zip(box["boxes"], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.55)
    ax.set_xlabel("Stake Gini", fontsize=15)
    ax.set_ylabel("Raw contribution", fontsize=15)
    ax.set_xticks(range(1, len(ginis) + 1))
    ax.set_xticklabels([f"{gini:g}" for gini in ginis])
    ax.tick_params(axis="both", labelsize=13)
    ax.grid(True, axis="y", alpha=0.25)
    bottom, top = ax.get_ylim()
    ax.set_ylim(bottom, top + (top - bottom) * 0.08)
    handles = [Patch(facecolor=PROFILE_COLORS[p], alpha=0.55, label=p) for p in PROFILE_ORDER]
    ax.legend(
        handles=handles,
        frameon=False,
        fontsize=12,
        loc="upper left",
        ncol=3,
        handlelength=1.2,
        columnspacing=1.0,
    )
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def write_weight_gini_pdf(path, seed_selector=selected_relay_seed):
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print(f"warning: matplotlib is not available; skipped {path}")
        return

    rows = [
        row
        for row in read_csv(PROCESSED / "runs.csv")
        if row.get("experiment") == "relay_participation" and row.get("status") == "ok"
        and seed_selector(row)
    ]
    labels = {
        "topostake_eta0": "eta=0",
        "topostake": "capped bonus",
    }
    series = defaultdict(list)
    for row in rows:
        label = labels.get(row.get("protocol_label", ""))
        if not label:
            continue
        series[label].append(
            (
                to_float(row.get("stake_gini")),
                to_float(row.get("proposer_weight_gini_mean"), math.nan),
                to_float(row.get("proposer_weight_gini_ci95"), 0.0),
            )
        )
    for points in series.values():
        points.sort(key=lambda item: item[0])

    if not series:
        if path.exists():
            path.unlink()
        print(f"warning: no data available; skipped {path}")
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(4.8, 3.2))
    for label, points in sorted(series.items()):
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        yerr = [point[2] for point in points]
        ax.errorbar(xs, ys, yerr=yerr, marker="o", linewidth=1.6, capsize=2.5, label=label)
    ax.set_xlabel("Stake Gini", fontsize=15)
    ax.set_ylabel("Proposer-weight Gini", fontsize=15)
    ax.set_xticks(sorted({point[0] for points in series.values() for point in points}))
    ax.tick_params(axis="both", labelsize=13)
    ax.grid(True, alpha=0.25)
    ax.legend(frameon=False, fontsize=12)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def write_weight_uplift_pdf(path, seed_selector=selected_relay_income_seed):
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print(f"warning: matplotlib is not available; skipped {path}")
        return

    rows = [
        row
        for row in warmup_filtered_node_rows(seed_selector)
        if row.get("protocol_label") == "topostake" and row.get("relay_profile") in PROFILE_ORDER
    ]
    by_run = defaultdict(list)
    for row in rows:
        by_run[row.get("run_id", "")].append(row)

    buckets = defaultdict(list)
    for run_rows in by_run.values():
        if not run_rows:
            continue
        gini = to_float(run_rows[0].get("stake_gini"))
        total_stake = sum(to_float(row.get("economic_stake"), 0.0) for row in run_rows)
        total_weight = sum(to_float(row.get("normalized_proposer_weight"), 0.0) for row in run_rows)
        if total_stake <= 0 or total_weight <= 0:
            continue
        for profile in PROFILE_ORDER:
            profile_rows = [row for row in run_rows if row.get("relay_profile") == profile]
            if not profile_rows:
                continue
            stake_share = sum(to_float(row.get("economic_stake"), 0.0) for row in profile_rows) / total_stake
            weight_share = (
                sum(to_float(row.get("normalized_proposer_weight"), 0.0) for row in profile_rows)
                / total_weight
            )
            if stake_share > 0:
                buckets[(profile, gini)].append(weight_share / stake_share)

    series = defaultdict(list)
    for (profile, gini), values in buckets.items():
        avg, ci = mean_ci(values)
        if not math.isnan(avg):
            series[profile].append((gini, avg, ci))
    for points in series.values():
        points.sort(key=lambda item: item[0])

    if not series:
        if path.exists():
            path.unlink()
        print(f"warning: no data available; skipped {path}")
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(4.8, 3.2))
    for profile in PROFILE_ORDER:
        points = series.get(profile, [])
        if not points:
            continue
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        yerr = [point[2] for point in points]
        ax.errorbar(
            xs,
            ys,
            yerr=yerr,
            marker="o",
            linewidth=1.6,
            capsize=2.5,
            label=profile,
            color=PROFILE_COLORS.get(profile),
        )
    ax.axhline(1.0, color="#444444", linestyle="--", linewidth=1.0, label="stake parity")
    ax.set_xlabel("Stake Gini", fontsize=15)
    ax.set_ylabel("Weight uplift", fontsize=15)
    ax.set_xticks(sorted({point[0] for points in series.values() for point in points}))
    ax.yaxis.set_major_formatter(plt.FormatStrFormatter("%.2f"))
    ax.tick_params(axis="both", labelsize=13)
    ax.grid(True, alpha=0.25)
    ax.legend(frameon=False, fontsize=11, ncol=2)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def write_weight_shift_pdf(path, seed_selector=selected_relay_income_seed):
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print(f"warning: matplotlib is not available; skipped {path}")
        return

    rows = [
        row
        for row in warmup_filtered_node_rows(seed_selector)
        if row.get("protocol_label") in {"topostake_eta0", "topostake"}
        and row.get("relay_profile") in PROFILE_ORDER
    ]
    by_run = defaultdict(list)
    for row in rows:
        by_run[row.get("run_id", "")].append(row)

    share_by_protocol = {}
    for run_rows in by_run.values():
        if not run_rows:
            continue
        protocol = run_rows[0].get("protocol_label", "")
        gini = to_float(run_rows[0].get("stake_gini"))
        total_weight = sum(to_float(row.get("normalized_proposer_weight"), 0.0) for row in run_rows)
        if total_weight <= 0:
            continue
        profile_shares = {}
        for profile in PROFILE_ORDER:
            profile_weight = sum(
                to_float(row.get("normalized_proposer_weight"), 0.0)
                for row in run_rows
                if row.get("relay_profile") == profile
            )
            profile_shares[profile] = profile_weight / total_weight
        share_by_protocol[(protocol, gini)] = profile_shares

    series = defaultdict(list)
    ginis = sorted({gini for protocol, gini in share_by_protocol if protocol == "topostake"})
    for gini in ginis:
        eta0 = share_by_protocol.get(("topostake_eta0", gini))
        capped = share_by_protocol.get(("topostake", gini))
        if not eta0 or not capped:
            continue
        for profile in PROFILE_ORDER:
            shift_pp = 100.0 * (capped[profile] - eta0[profile])
            series[profile].append((gini, shift_pp))

    if not series:
        if path.exists():
            path.unlink()
        print(f"warning: no data available; skipped {path}")
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(4.8, 3.2))
    for profile in PROFILE_ORDER:
        points = series.get(profile, [])
        if not points:
            continue
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        ax.plot(
            xs,
            ys,
            marker="o",
            linewidth=1.6,
            label=profile,
            color=PROFILE_COLORS.get(profile),
        )
    ax.axhline(0.0, color="#444444", linestyle="--", linewidth=1.0)
    ax.set_xlabel("Stake Gini", fontsize=15)
    ax.set_ylabel("Weight shift (pp)", fontsize=15)
    ax.set_xticks(sorted({point[0] for points in series.values() for point in points}))
    ax.yaxis.set_major_formatter(plt.FormatStrFormatter("%.1f"))
    ax.tick_params(axis="both", labelsize=13)
    ax.grid(True, alpha=0.25)
    ax.legend(frameon=False, fontsize=12)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--only",
        choices=["all", "income", "score", "weight"],
        default="all",
        help="Regenerate only the selected relay-participation figure group.",
    )
    args = parser.parse_args()

    for stale in [
        FIGURES / "relay_participation_income.svg",
        FIGURES / "relay_participation_score.svg",
        FIGURES / "relay_participation_weight_gini.svg",
        FIGURES / "relay_participation_income_seed1.svg",
        FIGURES / "relay_participation_score_seed1.svg",
        FIGURES / "relay_participation_weight_gini_seed1.svg",
        FIGURES / "relay_participation_weight_uplift.svg",
        FIGURES / "relay_participation_weight_uplift_seed1.svg",
        FIGURES / "relay_participation_weight_shift.svg",
        FIGURES / "relay_participation_weight_shift_seed1.svg",
    ]:
        if stale.exists():
            stale.unlink()

    seed1 = selected_seed_index(1)
    if args.only in {"all", "income"}:
        write_profile_line_pdf(
            FIGURES / "relay_participation_income.pdf",
            "Relay income by participation",
            "Relative relay income",
            "relay_reward",
            PROFILE_ORDER,
            selected_relay_income_seed,
        )
        write_profile_line_pdf(
            FIGURES / "relay_participation_income_seed1.pdf",
            "Relay income by participation",
            "Relative relay income",
            "relay_reward",
            PROFILE_ORDER,
            seed1,
        )
    if args.only in {"all", "score"}:
        write_score_distribution_pdf(FIGURES / "relay_participation_score.pdf")
        write_score_distribution_pdf(FIGURES / "relay_participation_score_seed1.pdf", seed1)
    if args.only in {"all", "weight"}:
        write_weight_gini_pdf(FIGURES / "relay_participation_weight_gini.pdf")
        write_weight_gini_pdf(FIGURES / "relay_participation_weight_gini_seed1.pdf", seed1)
        write_weight_uplift_pdf(FIGURES / "relay_participation_weight_uplift.pdf")
        write_weight_uplift_pdf(FIGURES / "relay_participation_weight_uplift_seed1.pdf", seed1)
        write_weight_shift_pdf(FIGURES / "relay_participation_weight_shift.pdf")
        write_weight_shift_pdf(FIGURES / "relay_participation_weight_shift_seed1.pdf", seed1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
