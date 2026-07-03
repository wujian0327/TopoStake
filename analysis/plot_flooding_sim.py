#!/usr/bin/env python3
import csv
from pathlib import Path

from plot_path_padding_sim import gamma
from plot_common import FIGURES, PROCESSED


MULTIPLIERS = [0, 0.5, 1, 2, 5]
ADVERSARY_STAKE_SHARE = 0.10
PROPOSER_FEE_RATIO = 0.70
DEPTH = 4
PATH_LENGTH = 3
CONTROLLED_RELAY_POSITIONS = [1]


def coalition_relay_capture() -> float:
    return sum(gamma(DEPTH, position, PATH_LENGTH) for position in CONTROLLED_RELAY_POSITIONS)


def simulation_rows():
    relay_capture = coalition_relay_capture()
    rows = []
    for multiplier in MULTIPLIERS:
        fee_spent = float(multiplier)
        proposer_recovery = fee_spent * PROPOSER_FEE_RATIO * ADVERSARY_STAKE_SHARE
        relay_recovery = fee_spent * (1.0 - PROPOSER_FEE_RATIO) * relay_capture
        recovered = proposer_recovery + relay_recovery
        rows.append(
            {
                "attack_tx_rate_multiplier": multiplier,
                "fee_spent": fee_spent,
                "fee_recovered": recovered,
                "net_income": recovered - fee_spent,
                "relay_capture": relay_capture,
            }
        )
    return rows


def write_csv(rows):
    PROCESSED.mkdir(parents=True, exist_ok=True)
    path = PROCESSED / "transaction_flooding_formula_sim.csv"
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return path


def write_pdf(rows):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    FIGURES.mkdir(parents=True, exist_ok=True)
    path = FIGURES / "transaction_flooding_net_income.pdf"
    fig, ax = plt.subplots(figsize=(4.8, 3.2))
    xs = [row["attack_tx_rate_multiplier"] for row in rows]
    ax.plot(
        xs,
        [row["net_income"] for row in rows],
        marker="o",
        linewidth=1.8,
        label="net income",
    )
    ax.plot(
        xs,
        [-row["fee_spent"] for row in rows],
        marker="s",
        linewidth=1.4,
        linestyle="--",
        label="fee spent",
    )
    ax.plot(
        xs,
        [row["fee_recovered"] for row in rows],
        marker="^",
        linewidth=1.4,
        linestyle=":",
        label="fee recovered",
    )
    ax.axhline(0.0, color="#555555", linewidth=1.0)
    ax.set_xlabel("Attack transaction multiplier", fontsize=15)
    ax.set_ylabel("Normalized income", fontsize=15)
    ax.set_xticks([0, 1, 2, 5])
    ax.tick_params(axis="both", labelsize=13)
    ax.grid(True, alpha=0.25)
    ax.legend(frameon=False, fontsize=12)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def main() -> int:
    rows = simulation_rows()
    csv_path = write_csv(rows)
    pdf_path = write_pdf(rows)
    print(f"Wrote {csv_path}")
    print(f"Wrote {pdf_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
