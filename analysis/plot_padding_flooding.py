#!/usr/bin/env python3
from collections import defaultdict

from plot_common import FIGURES, PROCESSED, mean_ci, read_csv, to_float


def write_line_pdf(
    path,
    title,
    xlabel,
    ylabel,
    series,
    include_zero=True,
    y_min=None,
    label_fontsize=10,
    tick_fontsize=10,
    legend_fontsize=10,
    y_decimal_places=None,
    xticks=None,
):
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
        ax.errorbar(xs, ys, yerr=yerr, marker="o", linewidth=1.5, capsize=2.5, label=name)
    ax.set_xlabel(xlabel, fontsize=label_fontsize)
    ax.set_ylabel(ylabel, fontsize=label_fontsize)
    ax.tick_params(axis="both", labelsize=tick_fontsize)
    if y_decimal_places is not None:
        from matplotlib.ticker import FormatStrFormatter

        ax.yaxis.set_major_formatter(FormatStrFormatter(f"%.{y_decimal_places}f"))
    ax.set_xticks(xticks or sorted({point[0] for points in series.values() for point in points}))
    if include_zero:
        bottom, top = ax.get_ylim()
        ax.set_ylim(min(0.0, bottom), top)
    if y_min is not None:
        bottom, top = ax.get_ylim()
        ax.set_ylim(y_min, max(top, y_min + 1e-9))
    ax.grid(True, alpha=0.25)
    ax.legend(frameon=False, fontsize=legend_fontsize)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def main() -> int:
    rows = read_csv(PROCESSED / "runs.csv")
    node_rows = read_csv(PROCESSED / "node_epoch_metrics_all.csv")

    padding = defaultdict(list)
    for row in rows:
        if row.get("experiment") != "path_padding" or row.get("status") != "ok":
            continue
        stake = to_float(row.get("adversary_real_stake_share_mean"), 0.0)
        if stake <= 0:
            continue
        series = f"D={row.get('topostake_target_depth', row.get('topostake_initial_depth', ''))}"
        x = row.get("padding_identities", "")
        padding[(f"weight {series}", x)].append(
            to_float(row.get("adversary_proposer_weight_share_mean"), 0.0) / stake
        )
        padding[(f"score {series}", x)].append(
            to_float(row.get("adversary_score_share_mean"), 0.0) / stake
        )

    by_run = defaultdict(list)
    for row in node_rows:
        if row.get("experiment") == "path_padding":
            by_run[row.get("run_id", "")].append(row)
    run_meta = {row.get("run_id", ""): row for row in rows}
    for run_id, group in by_run.items():
        meta = run_meta.get(run_id)
        if not meta:
            continue
        stake = to_float(meta.get("adversary_real_stake_share_mean"), 0.0)
        if stake <= 0:
            continue
        total_credit = sum(to_float(row.get("raw_contribution"), 0.0) for row in group)
        adv_credit = sum(
            to_float(row.get("raw_contribution"), 0.0)
            for row in group
            if row.get("adversarial") == "true"
        )
        total_reward = sum(to_float(row.get("relay_reward"), 0.0) for row in group)
        adv_reward = sum(
            to_float(row.get("relay_reward"), 0.0)
            for row in group
            if row.get("adversarial") == "true"
        )
        series = f"D={meta.get('topostake_target_depth', meta.get('topostake_initial_depth', ''))}"
        x = meta.get("padding_identities", "")
        if total_credit > 0:
            padding[(f"credit {series}", x)].append((adv_credit / total_credit) / stake)
        if total_reward > 0:
            padding[(f"relay reward {series}", x)].append((adv_reward / total_reward) / stake)

    padding_series = defaultdict(list)
    for (series, x), values in padding.items():
        avg, ci, n = mean_ci(values)
        if n:
            padding_series[series].append((float(x), avg, ci))
    for stale in [
        FIGURES / "path_padding_ratios.svg",
        FIGURES / "transaction_flooding_profit.svg",
        FIGURES / "transaction_flooding_latency.svg",
        FIGURES / "path_padding_ratios.pdf",
        FIGURES / "transaction_flooding_weight.pdf",
    ]:
        if stale.exists():
            stale.unlink()

    weight_score_series = {
        key: sorted(value)
        for key, value in padding_series.items()
        if key.startswith("weight ") or key.startswith("score ")
    }
    reward_credit_series = {
        key: sorted(value)
        for key, value in padding_series.items()
        if key.startswith("relay reward ") or key.startswith("credit ")
    }
    write_line_pdf(
        FIGURES / "path_padding_weight_score.pdf",
        "Path-padding adversary weight and score",
        "Padding identities",
        "Share / real stake share",
        weight_score_series,
    )
    write_line_pdf(
        FIGURES / "path_padding_reward_credit.pdf",
        "Path-padding adversary relay reward and credit",
        "Padding identities",
        "Share / real stake share",
        reward_credit_series,
    )
    flooding = defaultdict(list)
    for row in rows:
        if row.get("experiment") != "transaction_flooding" or row.get("status") != "ok":
            continue
        flooding[("net profit", row.get("attack_tx_rate_multiplier", ""))].append(
            to_float(row.get("adversary_net_income"), 0.0)
        )
        flooding[("fee spent", row.get("attack_tx_rate_multiplier", ""))].append(
            to_float(row.get("adversary_fee_spent"), 0.0)
        )
        flooding[("fee recovered", row.get("attack_tx_rate_multiplier", ""))].append(
            to_float(row.get("adversary_reward_income"), 0.0)
        )

    flooding_series = defaultdict(list)
    for (series, x), values in flooding.items():
        avg, ci, n = mean_ci(values)
        if n:
            flooding_series[series].append((float(x), avg, ci))
    write_line_pdf(
        FIGURES / "transaction_flooding_profit.pdf",
        "Transaction flooding accounting",
        "Attack transaction multiplier",
        "Amount",
        {key: sorted(value) for key, value in flooding_series.items()},
        include_zero=True,
    )
    weight = defaultdict(list)
    for row in rows:
        if row.get("experiment") != "transaction_flooding" or row.get("status") != "ok":
            continue
        x = row.get("attack_tx_rate_multiplier", "")
        weight[("proposer-weight share", x)].append(
            to_float(row.get("adversary_proposer_weight_share_mean"), 0.0)
        )
        weight[("theoretical bound", x)].append(
            to_float(row.get("theoretical_proposer_weight_bound_mean"), 0.0)
        )
        weight[("real stake share", x)].append(
            to_float(row.get("adversary_real_stake_share_mean"), 0.0)
        )

    weight_series = defaultdict(list)
    for (series, x), values in weight.items():
        avg, ci, n = mean_ci(values)
        if n:
            weight_series[series].append((float(x), avg, ci))
    write_line_pdf(
        FIGURES / "transaction_flooding_proposer_weight.pdf",
        "Transaction flooding proposer weight",
        "Attack transaction multiplier",
        "Proposer-weight share",
        {key: sorted(value) for key, value in weight_series.items()},
        include_zero=True,
        y_min=0.0,
        label_fontsize=15,
        tick_fontsize=13,
        legend_fontsize=11,
        y_decimal_places=2,
        xticks=[0, 1, 2, 5],
    )

    latency = defaultdict(list)
    for row in rows:
        if row.get("experiment") != "transaction_flooding" or row.get("status") != "ok":
            continue
        latency[("p95 latency", row.get("attack_tx_rate_multiplier", ""))].append(
            to_float(row.get("p95_inclusion_latency_s_mean"), 0.0)
        )
    latency_series = defaultdict(list)
    for (series, x), values in latency.items():
        avg, ci, n = mean_ci(values)
        if n:
            latency_series[series].append((float(x), avg, ci))
    write_line_pdf(
        FIGURES / "transaction_flooding_latency.pdf",
        "Transaction flooding latency",
        "Attack transaction multiplier",
        "p95 confirmation latency (s)",
        {key: sorted(value) for key, value in latency_series.items()},
        include_zero=True,
        y_min=0.0,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
