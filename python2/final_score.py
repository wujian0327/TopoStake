import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import networkx as nx
from matplotlib.patches import Rectangle
from plot_style import set_plot_style, format_axes, format_figure, get_project_root

# =========================================================
# Unified plotting style (consistent with other figures)
# =========================================================
set_plot_style('paper')

np.random.seed(42)

# =========================================================
# Parameters
# =========================================================
N = 100
NUM_TX = 8000
BA_M = 3
TARGET_STAKE_GINI = 0.6
D = 4
REGION_X = 40
REGION_Y = 60
REGION2_X = 60
REGION2_Y = 40
REGION3_X_MIN = 40
REGION3_X_MAX = 60
REGION3_Y_MIN = 40
REGION3_Y_MAX = 60

# TopoStake score parameters
K_SAT = 1.0
K_BASE = 0.01

# visualization parameters
GRID_BINS_X = 6
GRID_BINS_Y = 6
MAX_POINTS_PER_CELL = 2

SAVE_DIR = os.path.join(get_project_root(), "figures")
os.makedirs(SAVE_DIR, exist_ok=True)

# =========================================================
# Utility functions
# =========================================================
def gini(x):
    x = np.asarray(x, dtype=float)
    x = x[x >= 0]
    if len(x) == 0 or np.sum(x) == 0:
        return 0.0
    x = np.sort(x)
    n = len(x)
    return (2 * np.sum(np.arange(1, n + 1) * x) / (n * np.sum(x))) - (n + 1) / n


def generate_stake_with_target_gini(n, target_gini=0.6, max_iter=100):
    """
    Generate a normalized stake distribution with Gini close to target_gini.
    """
    low, high = 0.01, 5.0
    best_stake = None

    for _ in range(max_iter):
        sigma = (low + high) / 2.0
        stake = np.random.lognormal(mean=0.0, sigma=sigma, size=n)
        stake = stake / stake.sum()

        current_gini = gini(stake)
        best_stake = stake

        if abs(current_gini - target_gini) < 0.005:
            break

        if current_gini < target_gini:
            low = sigma
        else:
            high = sigma

    return best_stake


def atomic_contribution_for_path(path, D):
    """
    path = [origin, relay_1, relay_2, ..., proposer]
    """
    m = len(path) - 1
    if m <= 1:
        return {}

    lambda_e = (2 * D + 1) / (3 * D + 1)
    r_e = D / (2 * D + 1)

    psi = min(1.0, D / m)
    path_budget = psi * (lambda_e ** (m - 1))

    contribs = {}
    for k, v in enumerate(path[1:-1], start=1):
        alpha_k = ((1 - r_e) * (r_e ** (k - 1))) / (1 - r_e ** (m - 1))
        contribs[v] = path_budget * alpha_k

    return contribs


def percentile_rank(x, method="average"):
    x = np.asarray(x, dtype=float)
    ranks = pd.Series(x).rank(method=method).to_numpy()
    if len(x) <= 1:
        return np.zeros_like(x)
    return (ranks - 1) / (len(x) - 1) * 100.0


def compute_final_score(stake_hat, atomic_scores, k_sat=1.0, k_base=0.01):
    """
    Paper-style final score:
      C(v) = K_sat * S_hat(v) * log(1 + A(v)/(K_base * S_hat(v)))
    where A(v) is normalized atomic score.
    """
    stake_hat = np.asarray(stake_hat, dtype=float)
    atomic_scores = np.asarray(atomic_scores, dtype=float)

    A_norm = atomic_scores / (atomic_scores.sum() + 1e-12)
    final_scores = k_sat * stake_hat * np.log1p(A_norm / (k_base * stake_hat + 1e-12))
    return final_scores


def balanced_visual_sample(x, y, label, bins_x=6, bins_y=6, max_per_cell=3, random_state=42):
    """
    Visualization-only balanced sampling.
    No jitter here, to preserve consistency with the boundary.
    """
    rng = np.random.default_rng(random_state)

    x = np.asarray(x)
    y = np.asarray(y)
    label = np.asarray(label)

    x_edges = np.linspace(0, 100, bins_x + 1)
    y_edges = np.linspace(0, 100, bins_y + 1)

    keep_idx = []

    for i in range(bins_x):
        for j in range(bins_y):
            mask = (
                (x >= x_edges[i]) & (x < x_edges[i + 1]) &
                (y >= y_edges[j]) & (y < y_edges[j + 1])
            )

            idx = np.where(mask)[0]
            if len(idx) == 0:
                continue

            idx_low = idx[label[idx] == 0]
            idx_high = idx[label[idx] == 1]

            selected = []
            half_quota = max_per_cell // 2

            if len(idx_low) > 0:
                k_low = min(len(idx_low), half_quota if len(idx_high) > 0 else max_per_cell)
                selected.extend(rng.choice(idx_low, size=k_low, replace=False).tolist())

            if len(idx_high) > 0:
                remain = max_per_cell - len(selected)
                k_high = min(len(idx_high), remain)
                selected.extend(rng.choice(idx_high, size=k_high, replace=False).tolist())

            remain = max_per_cell - len(selected)
            if remain > 0:
                pool = np.setdiff1d(idx, np.array(selected, dtype=int), assume_unique=False)
                if len(pool) > 0:
                    k_fill = min(len(pool), remain)
                    selected.extend(rng.choice(pool, size=k_fill, replace=False).tolist())

            keep_idx.extend(selected)

    keep_idx = np.array(sorted(set(keep_idx)))
    return keep_idx


def value_to_percentile(sorted_arr, v):
    """
    Convert a raw value to empirical percentile in [0, 100].
    Linear-interpolated empirical CDF for smoother boundaries.

    Compared with a stepwise CDF, this keeps monotonicity while avoiding
    obvious staircase artifacts on the plotted boundary curve.
    """
    sorted_arr = np.asarray(sorted_arr)
    n = len(sorted_arr)
    if n == 0:
        return 0.0

    if v <= sorted_arr[0]:
        return 0.0
    if v >= sorted_arr[-1]:
        return 100.0

    # Percentile coordinates for each ordered sample.
    p = np.linspace(0.0, 100.0, n)
    return float(np.interp(v, sorted_arr, p))


# =========================================================
# Step 1. Simulate topology and scores
# =========================================================
G = nx.barabasi_albert_graph(N, BA_M, seed=42)

stake_hat = generate_stake_with_target_gini(N, TARGET_STAKE_GINI)
atomic_scores = np.zeros(N)
nodes = np.arange(N)

for _ in range(NUM_TX):
    origin, proposer = np.random.choice(nodes, size=2, replace=False)

    try:
        path = nx.shortest_path(G, source=origin, target=proposer)
    except nx.NetworkXNoPath:
        continue

    contribs = atomic_contribution_for_path(path, D)
    for v, c in contribs.items():
        atomic_scores[v] += c

final_scores = compute_final_score(
    stake_hat,
    atomic_scores,
    k_sat=K_SAT,
    k_base=K_BASE
)

# =========================================================
# Step 2. Percentiles and labels
# =========================================================
stake_pct_raw = percentile_rank(stake_hat, method="average")
atomic_pct_raw = percentile_rank(atomic_scores, method="average")
final_pct_raw = percentile_rank(final_scores, method="average")

label_raw = (final_pct_raw >= 50).astype(int)

# =========================================================
# Step 3. Exact 50th-percentile boundary from the formula
# =========================================================
# We use the median of the final score as the threshold.
c50 = np.median(final_scores)

stake_sorted = np.sort(stake_hat)
atomic_sorted = np.sort(atomic_scores)
A_total = atomic_scores.sum() + 1e-12

x_boundary = np.linspace(0, 100, 300)
y_boundary = []

for xp in x_boundary:
    # Convert stake percentile -> raw stake value
    s = np.percentile(stake_hat, xp)

    # Solve exact threshold from:
    # c50 = K_SAT * s * log(1 + A_norm / (K_BASE * s))
    # => A_norm = K_BASE * s * (exp(c50 / (K_SAT * s)) - 1)
    A_norm_th = K_BASE * s * np.expm1(c50 / (K_SAT * s + 1e-12))
    A_raw_th = A_norm_th * A_total

    # Convert raw atomic threshold back to atomic percentile
    yp = value_to_percentile(atomic_sorted, A_raw_th)
    y_boundary.append(yp)

y_boundary = np.array(y_boundary)
y_boundary = np.clip(y_boundary, 0, 100)

# =========================================================
# Step 4. Visualization-only balanced sampling
# =========================================================
# No jitter: avoid visual contradiction with the boundary.
keep_idx = balanced_visual_sample(
    stake_pct_raw,
    atomic_pct_raw,
    label_raw,
    bins_x=GRID_BINS_X,
    bins_y=GRID_BINS_Y,
    max_per_cell=MAX_POINTS_PER_CELL,
    random_state=42
)

stake_show = stake_pct_raw[keep_idx]
atomic_show = atomic_pct_raw[keep_idx]
label_show = label_raw[keep_idx]

low_mask = (label_show == 0)
high_mask = (label_show == 1)

# =========================================================
# Step 5. Plot
# =========================================================
fig, ax = plt.subplots(figsize=(10, 6.8))

# Two visual regions:
# Region 1: upper-left  (x <= 40, y >= 60)
# Region 2: lower-right (x >= 60, y <= 40)
# Region 3: center block (40 <= x <= 60, 40 <= y <= 60)

# Highlight Final Score >= 50% area (above boundary)
ax.fill_between(
    x_boundary,
    y_boundary,
    100,
    color="#b7d7f0",
    alpha=0.26,
    zorder=0,
)

# Region split reference lines
ax.axhline(REGION_Y, xmin=0.0, xmax=REGION_X / 100.0, color="#d62728", linestyle="-", linewidth=2.0, alpha=0.95, zorder=1)
ax.axvline(REGION_X, ymin=REGION_Y / 100.0, ymax=1.0, color="#d62728", linestyle="-", linewidth=2.0, alpha=0.95, zorder=1)
ax.axhline(REGION2_Y, xmin=REGION2_X / 100.0, xmax=1.0, color="#1f77b4", linestyle="-", linewidth=2.0, alpha=0.95, zorder=1)
ax.axvline(REGION2_X, ymin=0.0, ymax=REGION2_Y / 100.0, color="#1f77b4", linestyle="-", linewidth=2.0, alpha=0.95, zorder=1)

# Region 3 border (center block)
ax.add_patch(
    Rectangle(
        (REGION3_X_MIN, REGION3_Y_MIN),
        REGION3_X_MAX - REGION3_X_MIN,
        REGION3_Y_MAX - REGION3_Y_MIN,
        fill=False,
        edgecolor="#2ca02c",
        linestyle="-",
        linewidth=2.0,
        alpha=0.95,
        zorder=1,
    )
)

# Region labels
ax.text(2, 62, "Active Validators", fontsize=20, fontweight="bold", alpha=0.8)
ax.text(61, 3, "Rich Validators", fontsize=20, fontweight="bold", alpha=0.8)
ax.annotate(
    "Balance Validators",
    xy=(50, 50),
    xytext=(18, 18),
    fontsize=20,
    fontweight="bold",
    alpha=0.85,
    arrowprops=dict(arrowstyle="->", lw=2.2, color="black")
)

# Scatter points
ax.scatter(
    stake_show[low_mask],
    atomic_show[low_mask],
    s=60,
    marker='o',
    alpha=0.45,
    label='Final Score < 50th pct.',
    clip_on=True
)

ax.scatter(
    stake_show[high_mask],
    atomic_show[high_mask],
    s=72,
    marker='D',
    alpha=0.55,
    label='Final Score ≥ 50th pct.',
    clip_on=True
)

# Exact formula-derived boundary
ax.plot(
    x_boundary,
    y_boundary,
    color="#4b006e",
    linestyle="--",
    linewidth=2.3,
    label='50th-percentile boundary'
)

format_axes(ax, xlabel='Stake Percentile (%)', ylabel='Atomic Score Percentile (%)')
ax.set_xlim(0, 100)
ax.set_ylim(0, 100)
ax.set_xticks(np.arange(0, 101, 20))
ax.set_yticks(np.arange(0, 101, 20))

ax.legend(
    loc='upper right',
    fontsize=22,
    frameon=True,
    fancybox=False,
    edgecolor='black',
    framealpha=0.95
)

format_figure(fig)
fig.subplots_adjust(left=0.12, right=0.97, bottom=0.13, top=0.96)

# =========================================================
# Step 6. Save
# =========================================================
png_path = os.path.join(SAVE_DIR, "final_score.png")
pdf_path = os.path.join(SAVE_DIR, "final_score.pdf")

plt.savefig(png_path, dpi=300)
plt.savefig(pdf_path, dpi=300)

# plt.show()

print(f"Stake Gini: {gini(stake_hat):.3f}")
print(f"Total validators: {N}")
print(f"Scatter points shown: {len(keep_idx)}")
print(f"Saved PNG: {png_path}")
print(f"Saved PDF: {pdf_path}")