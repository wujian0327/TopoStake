import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
import pandas as pd

from plot_style import (
    format_axes,
    format_figure,
    get_colors_and_styles,
    get_project_root,
    set_plot_style,
)


# =========================================================
# Experiment configuration
# =========================================================

N = 100
EPOCHS = 500
TX_PER_EPOCH = 100
BA_M = 3
TARGET_STAKE_GINI = 0.60

OMEGAS = np.linspace(0.0, 1.0, 11)
SEEDS = [0, 1, 2, 3, 4]

# TopoStake score parameters.  K_BASE follows the paper setup and
# final_score.py; BETA follows the existing beta=0.5 result files.
K_BASE = 0.01
BETA = 0.50
MAX_PATH_LENGTH = 6

# Economic dynamics.  We keep the simulator lightweight, but include the
# wealth-compounding effect that appears in the 500-epoch fairness experiment:
# a block proposer receives a fixed reward, while TopoStake can redistribute
# part of transaction fees to useful relayers according to contribution score.
BLOCK_REWARD = 0.010
BASE_FEE = 1e-5
RELAY_FEE_FRACTION = 0.80

RESULT_DIR = Path(get_project_root()) / "result"
FIG_DIR = Path(get_project_root()) / "figures"
RESULT_DIR.mkdir(parents=True, exist_ok=True)
FIG_DIR.mkdir(parents=True, exist_ok=True)


# =========================================================
# Metrics and helpers
# =========================================================

def gini(values: np.ndarray) -> float:
    values = np.asarray(values, dtype=float)

    if values.size == 0:
        return 0.0
    if np.any(values < 0):
        raise ValueError("Gini input contains negative values.")

    total = values.sum()
    if total <= 0:
        return 0.0

    values = np.sort(values)
    n = values.size
    index = np.arange(1, n + 1)
    return (2.0 * np.sum(index * values) / (n * total)) - (n + 1.0) / n


def fairness_score(values: np.ndarray) -> float:
    return 1.0 - gini(values)


def normalize(values: np.ndarray, fallback: np.ndarray | None = None) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    total = values.sum()
    if total > 0:
        return values / total
    if fallback is not None:
        return normalize(fallback)
    return np.ones_like(values) / len(values)


def generate_stake_with_target_gini(
    rng: np.random.Generator,
    n: int,
    target_gini: float = 0.60,
    max_iter: int = 100,
) -> np.ndarray:
    """Generate normalized stake with Gini close to the paper's 0.6 setup."""
    low, high = 0.01, 5.0
    best_stake = None
    best_gap = float("inf")

    for _ in range(max_iter):
        sigma = (low + high) / 2.0
        stake = rng.lognormal(mean=0.0, sigma=sigma, size=n)
        stake = normalize(stake)

        current_gini = gini(stake)
        gap = abs(current_gini - target_gini)
        if gap < best_gap:
            best_gap = gap
            best_stake = stake

        if gap < 0.005:
            break
        if current_gini < target_gini:
            low = sigma
        else:
            high = sigma

    return best_stake


def update_target_depth(current_d: int, path_lengths: list[int]) -> int:
    avg_len = int(np.ceil(np.mean(path_lengths))) if path_lengths else 0

    if avg_len > current_d:
        return current_d + 1
    if avg_len < current_d:
        return max(0, current_d - 1)
    return current_d


def relay_activity_profile(
    rng: np.random.Generator,
    graph: nx.Graph,
    stake_hat: np.ndarray,
) -> np.ndarray:
    """
    Lightweight behavioral model for propagation effort.

    The paper's fairness argument assumes low-stake validators can compensate
    with useful relay behavior.  We model that by making relay activity only
    weakly tied to topology and partially anti-correlated with stake.
    """
    n = len(stake_hat)
    stake_rank = pd.Series(stake_hat).rank(method="average").to_numpy()
    stake_pct = (stake_rank - 1.0) / max(1, n - 1)

    degree = np.array([graph.degree(i) for i in range(n)], dtype=float)
    degree = degree / (degree.max() + 1e-12)

    low_stake_effort = (1.0 - stake_pct) ** 0.75
    topology_access = 0.75 + 0.25 * degree
    heterogeneity = rng.lognormal(mean=0.0, sigma=0.20, size=n)

    activity = (0.35 + 0.65 * low_stake_effort) * topology_access * heterogeneity
    return normalize(activity)


def sample_propagation_path(
    rng: np.random.Generator,
    shortest_lengths: np.ndarray,
    origin: int,
    proposer: int,
    relay_activity: np.ndarray,
) -> list[int]:
    """
    Generate a verified propagation path abstraction.

    The graph gives the baseline path length, while relay selection is biased by
    active propagation behavior.  This avoids treating static BA betweenness as
    the only source of relay contribution.
    """
    base_length = shortest_lengths[origin, proposer]
    if base_length <= 0:
        base_length = 1

    jitter = int(rng.choice([-1, 0, 1], p=[0.15, 0.70, 0.15]))
    path_length = int(np.clip(base_length + jitter, 1, MAX_PATH_LENGTH))
    relay_count = max(0, path_length - 1)

    if relay_count == 0:
        return [origin, proposer]

    candidates = np.array([v for v in range(len(relay_activity)) if v not in {origin, proposer}])
    probs = relay_activity[candidates]
    probs = normalize(probs)

    relay_count = min(relay_count, len(candidates))
    relayers = rng.choice(candidates, size=relay_count, replace=False, p=probs)
    return [origin, *[int(v) for v in relayers], proposer]


def all_pairs_distance_matrix(graph: nx.Graph, n: int) -> np.ndarray:
    distances = np.ones((n, n), dtype=int)
    np.fill_diagonal(distances, 0)

    for source, lengths in nx.all_pairs_shortest_path_length(graph):
        for target, length in lengths.items():
            distances[source, target] = length

    return distances


# =========================================================
# Paper algorithm
# =========================================================

def atomic_contribution_for_path(path: list[int], target_depth: int) -> dict[int, float]:
    """
    Eq. (atomic score): gamma(v_k,p) = psi(m,D) * lambda^(m-1) * alpha_k.

    path = [origin, relay_1, ..., proposer], so m is the propagation length
    and relayers are path[1:-1].
    """
    m = len(path) - 1
    if target_depth <= 0 or m <= 1:
        return {}

    lambda_e = (2.0 * target_depth + 1.0) / (3.0 * target_depth + 1.0)
    r_e = target_depth / (2.0 * target_depth + 1.0)

    psi = min(1.0, target_depth / m)
    path_budget = psi * (lambda_e ** (m - 1))

    denom = 1.0 - (r_e ** (m - 1))
    contribs = {}
    for k, validator in enumerate(path[1:-1], start=1):
        alpha_k = ((1.0 - r_e) * (r_e ** (k - 1))) / denom
        contribs[validator] = contribs.get(validator, 0.0) + path_budget * alpha_k

    return contribs


def slot_contribution_score(stake_hat: np.ndarray, atomic_scores: np.ndarray) -> np.ndarray:
    """
    Eq. (saturation), using normalized atomic contribution as in final_score.py.
    This keeps K_BASE=0.01 comparable across different TX_PER_EPOCH values.
    """
    atomic_hat = normalize(atomic_scores, fallback=np.zeros_like(atomic_scores))
    return stake_hat * np.log1p(atomic_hat / (K_BASE * stake_hat + 1e-12))


def virtual_stake(stake_hat: np.ndarray, score: np.ndarray, omega: float) -> np.ndarray:
    c_hat = normalize(score, fallback=stake_hat)
    return normalize(omega * c_hat + (1.0 - omega) * stake_hat)


def simulate_run(omega: float, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    graph = nx.barabasi_albert_graph(N, BA_M, seed=seed)
    shortest_lengths = all_pairs_distance_matrix(graph, N)
    nodes = np.arange(N)

    stake_balance = generate_stake_with_target_gini(rng, N, TARGET_STAKE_GINI)
    stake_hat = normalize(stake_balance)
    score = np.zeros(N)
    virt = stake_hat.copy()
    target_depth = 0

    rows = []

    for epoch in range(EPOCHS):
        stake_hat = normalize(stake_balance)
        relay_activity = relay_activity_profile(rng, graph, stake_hat)
        atomic_scores = np.zeros(N)
        path_lengths = []

        proposer = int(rng.choice(nodes, p=virt))
        for _ in range(TX_PER_EPOCH):
            origin = int(rng.choice(nodes[nodes != proposer]))

            path = sample_propagation_path(rng, shortest_lengths, origin, proposer, relay_activity)

            path_lengths.append(len(path) - 1)
            for validator, contribution in atomic_contribution_for_path(path, target_depth).items():
                atomic_scores[validator] += contribution

        c_slot = slot_contribution_score(stake_hat, atomic_scores)
        score = BETA * c_slot + (1.0 - BETA) * score
        virt = virtual_stake(stake_hat, score, omega)

        fee_pool = BASE_FEE * TX_PER_EPOCH
        relay_pool = omega * RELAY_FEE_FRACTION * fee_pool
        proposer_reward = BLOCK_REWARD + fee_pool - relay_pool
        stake_balance[proposer] += proposer_reward

        if relay_pool > 0 and score.sum() > 0:
            stake_balance += relay_pool * normalize(score)

        rows.append({
            "omega": omega,
            "seed": seed,
            "epoch": epoch,
            "target_depth": target_depth,
            "avg_path_length": float(np.mean(path_lengths)) if path_lengths else 0.0,
            "stake_gini": gini(stake_hat),
            "contribution_gini": gini(normalize(score, fallback=stake_hat)),
            "virtual_stake_gini": gini(virt),
            "fairness_score": fairness_score(virt),
            "stake_fairness": fairness_score(stake_hat),
        })

        target_depth = update_target_depth(target_depth, path_lengths)

    return pd.DataFrame(rows)


# =========================================================
# Main experiment
# =========================================================

def main() -> None:
    all_runs = []

    for omega in OMEGAS:
        for seed in SEEDS:
            all_runs.append(simulate_run(float(omega), seed))

    epoch_df = pd.concat(all_runs, ignore_index=True)

    # Steady-state fairness: average over the last 20% of epochs.
    steady_start = int(np.floor(EPOCHS * 0.80))
    steady_df = epoch_df[epoch_df["epoch"] >= steady_start]
    summary_df = (
        steady_df
        .groupby("omega", as_index=False)
        .agg(
            fairness_mean=("fairness_score", "mean"),
            fairness_std=("fairness_score", "std"),
            gini_mean=("virtual_stake_gini", "mean"),
            contribution_gini_mean=("contribution_gini", "mean"),
            target_depth_mean=("target_depth", "mean"),
            avg_path_length_mean=("avg_path_length", "mean"),
        )
    )

    print(summary_df.to_string(index=False, float_format=lambda x: f"{x:.4f}"))

    set_plot_style("paper")
    colors, linestyles, markers = get_colors_and_styles()
    fig, ax = plt.subplots(figsize=(10, 6.8))
    fairness_mean_pct = summary_df["fairness_mean"] * 100.0
    fairness_std_pct = summary_df["fairness_std"] * 100.0

    ax.errorbar(
        summary_df["omega"],
        fairness_mean_pct,
        yerr=fairness_std_pct,
        marker=markers["topostake"],
        linestyle=linestyles["topostake"],
        color=colors["topostake"],
        label="TopoStake",
        capsize=5,
        elinewidth=2.0,
        capthick=2.0,
        markersize=8,
    )

    format_axes(
        ax,
        xlabel=r"Mixing Parameter ($\omega$)",
        ylabel="Fairness Score (%)",
    )
    ax.set_xlim(-0.03, 1.03)
    ax.set_xticks(np.arange(0.0, 1.01, 0.2))
    ax.set_ylim(25, 60)
    ax.set_yticks([30, 40, 50, 60])
    ax.axhline(
        y=40,
        color="gray",
        linestyle="--",
        linewidth=1.5,
        alpha=0.95,
        zorder=2,
    )

    ax.legend(
        fontsize=22,
        loc="lower right",
        frameon=True,
        fancybox=False,
        edgecolor="black",
        framealpha=0.95,
    )
    format_figure(fig)

    png_path = FIG_DIR / "omega_fairness.png"
    pdf_path = FIG_DIR / "omega_fairness.pdf"
    fig.savefig(png_path, dpi=300, bbox_inches="tight")
    fig.savefig(pdf_path, dpi=300, bbox_inches="tight")

    print(f"Saved PNG: {png_path}")
    print(f"Saved PDF: {pdf_path}")


if __name__ == "__main__":
    main()
