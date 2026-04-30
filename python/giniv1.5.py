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


# --- 读取数据 ---
epochs_topostake, gini_topostake = get_gini_data('topostake')  # omega = 1.0
epochs_pos, gini_pos = get_gini_data('pos')
epochs_pow, gini_pow = get_gini_data('pow')
epochs_minotaur, gini_minotaur = get_gini_data('minotaur')

# --- 使用原始 Gini 系数 ---
gini_topostake = np.asarray(gini_topostake)
gini_pos = np.asarray(gini_pos)
gini_pow = np.asarray(gini_pow)
gini_minotaur = np.asarray(gini_minotaur)

# --- 绘图 ---
fig, ax = plt.subplots(figsize=(10, 6.8))

if len(epochs_topostake) > 0:
    ax.plot(
        epochs_topostake,
        gini_topostake,
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
        gini_pos,
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
        gini_minotaur,
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
        gini_pow,
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
    ylabel='Gini Coefficient'
)

all_epochs = [
    epochs_topostake,
    epochs_pos,
    epochs_pow,
    epochs_minotaur
]
max_epoch = max([e.max() if len(e) > 0 else 0 for e in all_epochs] + [100])
ax.text(max_epoch * 0.98, 0.42, 'Better Fairness', fontsize=20, color='gray', ha='right', va='center', fontweight='bold', zorder=1)
ax.set_xlim(0, 500)

ax.set_ylim(0.4,0.7)
ax.set_yticks(np.arange(0.4, 0.71, 0.1))

# 参考线：Gini = 0.60
ax.axhline(
    y=0.60,
    color='gray',
    linestyle='--',
    linewidth=1.5,
    alpha=0.95,
    zorder=2
)



ax.legend(
    fontsize=20,
    loc=(0.7,0.55),
    frameon=True,
    fancybox=False,
    edgecolor='black',
    framealpha=0.95
)

format_figure(fig)

plt.savefig(
    os.path.join(project_root, 'figures', 'gini.png'),
    dpi=300,
    bbox_inches='tight'
)
plt.savefig(
    os.path.join(project_root, 'figures', 'gini.pdf'),
    dpi=300,
    bbox_inches='tight'
)

# plt.show()