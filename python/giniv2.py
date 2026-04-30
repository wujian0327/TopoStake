import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import os
from plot_style import (
    get_project_root,
    set_plot_style,
    get_colors_and_styles,
    format_axes,
    format_figure
)

project_root = get_project_root()

# --- 统一风格设置 ---
set_plot_style('paper')
colors, linestyles, markers = get_colors_and_styles()


def get_gini_data(alg):
    if alg == 'topostake':
        file = os.path.join(project_root, 'result/gini_topostake_n_100_t_100_ba.csv')
        if not os.path.exists(file):
            file = os.path.join(project_root, 'result/gini_topostake_n_100_t_100_ba.csv')
    else:
        file = os.path.join(project_root, f'result/gini_{alg}_n_100_t_100_ba.csv')

    try:
        df = pd.read_csv(file)
        if 'gini_coefficient' in df.columns and 'epoch' in df.columns:
            df = df.dropna(subset=['gini_coefficient', 'epoch'])
            gini_by_epoch = df.groupby('epoch')['gini_coefficient'].mean()
            return gini_by_epoch.index.to_numpy(), gini_by_epoch.values
    except Exception as e:
        print(f"Error loading data for {alg}: {e}")
        return np.array([]), np.array([])

    return np.array([]), np.array([])


def gini_to_fairness(gini_values):
    """
    Convert Gini coefficient to Fairness Score.
    Higher values indicate better fairness.
    """
    return (1.0 - np.array(gini_values)) * 100.0


# --- 读取数据 ---
epochs_topostake, gini_topostake = get_gini_data('topostake')  # omega = 1.0
epochs_pos, gini_pos = get_gini_data('pos')
epochs_pow, gini_pow = get_gini_data('pow')
epochs_minotaur, gini_minotaur = get_gini_data('minotaur')

# --- 转换为 Fairness Score ---
fair_topostake = gini_to_fairness(gini_topostake)
fair_pos = gini_to_fairness(gini_pos)
fair_pow = gini_to_fairness(gini_pow)
fair_minotaur = gini_to_fairness(gini_minotaur)

# --- 绘图 ---
fig, ax = plt.subplots(figsize=(10, 6.8))

if len(epochs_topostake) > 0:
    ax.plot(
        epochs_topostake,
        fair_topostake,
        label='TopoStake',
        color=colors['topostake'],
        linestyle=linestyles['topostake'],
        marker=markers['topostake'],
        markevery=max(1, len(epochs_topostake) // 20),
        markersize=8
    )

if len(epochs_pos) > 0:
    ax.plot(
        epochs_pos,
        fair_pos,
        label='PoS',
        color=colors['pos'],
        linestyle=linestyles['pos'],
        marker=markers['pos'],
        markevery=max(1, len(epochs_pos) // 20),
        markersize=8
    )

if len(epochs_minotaur) > 0:
    ax.plot(
        epochs_minotaur,
        fair_minotaur,
        label='Minotaur',
        color=colors['minotaur'],
        linestyle=linestyles['minotaur'],
        marker=markers['minotaur'],
        markevery=max(1, len(epochs_minotaur) // 20),
        markersize=8
    )

if len(epochs_pow) > 0:
    ax.plot(
        epochs_pow,
        fair_pow,
        label='PoW',
        color=colors['pow'],
        linestyle=linestyles['pow'],
        marker=markers['pow'],
        markevery=max(1, len(epochs_pow) // 20),
        markersize=8
    )


# --- 坐标轴设置 ---
format_axes(
    ax,
    xlabel='Evolution Time (Epochs)',
    ylabel='Fairness Score (%)'
)

all_epochs = [
    epochs_topostake,
    epochs_pos,
    epochs_pow,
    epochs_minotaur
]
max_epoch = max([e.max() if len(e) > 0 else 0 for e in all_epochs] + [100])

ax.set_xlim(0, 500)

ax.set_ylim(15, 60)

# 原来的 Gini=0.60 分界线，对应 Fairness=40%
ax.axhline(
    y=40,
    color='gray',
    linestyle='--',
    linewidth=1.5,
    alpha=0.95,
    zorder=2
)



ax.legend(
    fontsize=20,
    loc='best',
    frameon=True,
    fancybox=False,
    edgecolor='black',
    framealpha=0.95
)

format_figure(fig)

plt.savefig(
    os.path.join(project_root, 'figures', 'fairness.png'),
    dpi=300,
    bbox_inches='tight'
)
plt.savefig(
    os.path.join(project_root, 'figures', 'fairness.pdf'),
    dpi=300,
    bbox_inches='tight'
)

# plt.show()