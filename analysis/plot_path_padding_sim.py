#!/usr/bin/env python3
import csv
from pathlib import Path

from plot_common import FIGURES, PROCESSED


DEPTHS = [2, 4, 8]
PADDINGS = [0, 1, 2, 4, 8, 16]
ETA = 0.5
BONUS_CAP = 1.0
BONUS_STRENGTH = 0.4
ADVERSARY_STAKE_SHARE = 0.10


def lambda_for_depth(depth: int) -> float:
    d = float(depth)
    return (2.0 * d + 1.0) / (3.0 * d + 1.0)


def r_for_depth(depth: int) -> float:
    d = float(depth)
    return d / (2.0 * d + 1.0)


def path_budget(depth: int, path_length: int) -> float:
    if path_length < 2:
        return 0.0
    d = float(depth)
    m = float(path_length)
    return min(d, m) / m * lambda_for_depth(depth) ** (path_length - 1)


def alpha(depth: int, position: int, path_length: int) -> float:
    if path_length < 2 or position == 0 or position >= path_length:
        return 0.0
    r = r_for_depth(depth)
    numerator = (1.0 - r) * r ** (position - 1)
    denominator = 1.0 - r ** (path_length - 1)
    return numerator / denominator


def gamma(depth: int, position: int, path_length: int) -> float:
    return path_budget(depth, path_length) * alpha(depth, position, path_length)


def simulation_rows():
    rows = []
    for depth in DEPTHS:
        depth_rows = []
        for padding in PADDINGS:
            controlled_positions = 1 + padding
            path_length = controlled_positions + 2
            adversary_credit = sum(
                gamma(depth, position, path_length)
                for position in range(1, controlled_positions + 1)
            )
            depth_rows.append(
                {
                    "depth": depth,
                    "padding_identities": padding,
                    "path_length": path_length,
                    "adversary_relay_credit": adversary_credit,
                    "path_budget": path_budget(depth, path_length),
                }
            )

        baseline_credit = depth_rows[0]["adversary_relay_credit"]
        for row in depth_rows:
            credit_norm = row["adversary_relay_credit"] / baseline_credit
            score_bonus_norm = credit_norm
            bonus = min(BONUS_STRENGTH * score_bonus_norm, BONUS_CAP)
            row["relay_reward_norm"] = credit_norm
            row["score_bonus_norm"] = score_bonus_norm
            row["proposer_weight_over_stake"] = 1.0 + ETA * bonus
            row["proposal_probability_over_stake"] = row["proposer_weight_over_stake"]
            unnormalized = ADVERSARY_STAKE_SHARE * row["proposer_weight_over_stake"]
            row["proposer_weight_share"] = unnormalized / (
                1.0 - ADVERSARY_STAKE_SHARE + unnormalized
            )

        baseline_excess = depth_rows[0]["proposer_weight_over_stake"] - 1.0
        for row in depth_rows:
            excess = row["proposer_weight_over_stake"] - 1.0
            row["proposer_weight_excess_norm"] = excess / baseline_excess
        rows.extend(depth_rows)
    return rows


def write_csv(rows):
    PROCESSED.mkdir(parents=True, exist_ok=True)
    path = PROCESSED / "path_padding_formula_sim.csv"
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return path


def write_pdfs(rows):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FormatStrFormatter

    FIGURES.mkdir(parents=True, exist_ok=True)
    proposal_path = FIGURES / "path_padding_proposal_probability.pdf"
    reward_path = FIGURES / "path_padding_coalition_relay_reward.pdf"
    for stale in [
        FIGURES / "path_padding_formula_incentive.pdf",
        FIGURES / "path_padding_formula_power.pdf",
        FIGURES / "path_padding_formula_sim.pdf",
        FIGURES / "path_padding_proposal_probability.pdf",
        FIGURES / "path_padding_relay_contribution.pdf",
        FIGURES / "path_padding_coalition_relay_reward.pdf",
    ]:
        if stale.exists():
            stale.unlink()
    xs = [row["padding_identities"] for row in rows]
    xs = sorted(set(xs))

    fig, ax = plt.subplots(figsize=(4.8, 3.2))
    for depth in DEPTHS:
        depth_rows = [row for row in rows if row["depth"] == depth]
        ax.plot(
            xs,
            [row["proposer_weight_share"] for row in depth_rows],
            marker="o",
            linewidth=1.8,
            label=f"D={depth}",
        )
    ax.axhline(
        ADVERSARY_STAKE_SHARE,
        color="#666666",
        linestyle="--",
        linewidth=1.0,
        label="stake share",
    )
    ax.set_xlabel("Padding identities", fontsize=15)
    ax.set_ylabel("Proposer-weight share", fontsize=15)
    ax.yaxis.set_major_formatter(FormatStrFormatter("%.3f"))
    ax.set_xticks(xs)
    ax.tick_params(axis="both", labelsize=13)
    ax.grid(True, alpha=0.25)
    ax.legend(frameon=False, fontsize=12)
    fig.tight_layout()
    fig.savefig(proposal_path)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(4.8, 3.2))
    for depth in DEPTHS:
        depth_rows = [row for row in rows if row["depth"] == depth]
        ax.plot(
            xs,
            [row["adversary_relay_credit"] for row in depth_rows],
            marker="o",
            linewidth=1.8,
            label=f"D={depth}",
        )
    ax.set_xlabel("Padding identities", fontsize=15)
    ax.set_ylabel("Coalition reward share", fontsize=15)
    ax.yaxis.set_major_formatter(FormatStrFormatter("%.2f"))
    ax.set_xticks(xs)
    ax.set_ylim(bottom=0)
    ax.tick_params(axis="both", labelsize=13)
    ax.grid(True, alpha=0.25)
    ax.legend(frameon=False, fontsize=12)
    fig.tight_layout()
    fig.savefig(reward_path)
    plt.close(fig)
    return (proposal_path, reward_path)


def main() -> int:
    rows = simulation_rows()
    csv_path = write_csv(rows)
    pdf_paths = write_pdfs(rows)
    print(f"Wrote {csv_path}")
    for pdf_path in pdf_paths:
        print(f"Wrote {pdf_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
