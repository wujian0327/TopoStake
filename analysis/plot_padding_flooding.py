#!/usr/bin/env python3
from collections import defaultdict

from plot_common import FIGURES, PROCESSED, mean_ci, read_csv, to_float, write_line_svg


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
        series = f"D={row.get('topostake_initial_depth', '')}"
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
        total_reward = sum(
            to_float(row.get("relay_reward"), 0.0) + to_float(row.get("proposer_reward"), 0.0)
            for row in group
        )
        adv_reward = sum(
            to_float(row.get("relay_reward"), 0.0) + to_float(row.get("proposer_reward"), 0.0)
            for row in group
            if row.get("adversarial") == "true"
        )
        series = f"D={meta.get('topostake_initial_depth', '')}"
        x = meta.get("padding_identities", "")
        if total_credit > 0:
            padding[(f"credit {series}", x)].append((adv_credit / total_credit) / stake)
        if total_reward > 0:
            padding[(f"reward {series}", x)].append((adv_reward / total_reward) / stake)

    padding_series = defaultdict(list)
    for (series, x), values in padding.items():
        avg, ci, n = mean_ci(values)
        if n:
            padding_series[series].append((float(x), avg, ci))
    write_line_svg(
        FIGURES / "path_padding_ratios.svg",
        "Path-padding coalition ratios",
        "Padding identities",
        "Share / real stake share",
        {key: sorted(value) for key, value in padding_series.items()},
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
    write_line_svg(
        FIGURES / "transaction_flooding_profit.svg",
        "Transaction flooding accounting",
        "Attack transaction multiplier",
        "Amount",
        {key: sorted(value) for key, value in flooding_series.items()},
        include_zero=True,
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
    write_line_svg(
        FIGURES / "transaction_flooding_latency.svg",
        "Transaction flooding latency",
        "Attack transaction multiplier",
        "p95 inclusion latency (s)",
        {key: sorted(value) for key, value in latency_series.items()},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
