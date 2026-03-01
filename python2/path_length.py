import os
from matplotlib import pyplot as plt
import numpy as np
from plot_style import get_project_root, set_plot_style, get_colors_and_styles, format_axes, format_figure
import pandas as pd

project_root = get_project_root()

# 设置统一后的科研风格
set_plot_style('paper')
colors, linestyles, markers = get_colors_and_styles()

# 图 1: Throughput (吞吐量)
fig, ax = plt.subplots(figsize=(10, 8))  # 调整尺寸以适应大字体

# --- 真实实验数据 ---
N = np.array([50, 100, 150, 200, 250, 300])

import pandas as pd

def calculate_path_stats(alg):
    means = []
    stds = []
    for n in N:
        file = os.path.join(project_root, f'result/metrics_{alg}_n_{n}_t_100_ba.csv')
        try:
            if not os.path.exists(file):
                 means.append(np.nan)
                 stds.append(np.nan)
                 continue
            df = pd.read_csv(file)
            if 'avg_path_length' in df.columns:
                valid_data = df[df['avg_path_length'] > 0]
                if not valid_data.empty:
                    means.append(valid_data['avg_path_length'].mean())
                    stds.append(valid_data['avg_path_length'].std())
                else:
                    means.append(np.nan)
                    stds.append(np.nan)
            else:
                means.append(np.nan)
                stds.append(np.nan)
        except Exception:
            means.append(np.nan)
            stds.append(np.nan)
    return np.array(means), np.array(stds)

path_topostake, err_topostake = calculate_path_stats('topostake')
path_pos, err_pos = calculate_path_stats('pos')
path_minotaur, err_minotaur = calculate_path_stats('minotaur')
path_pow, err_pow = calculate_path_stats('pow')

# --- 绘图 ---
fig, ax = plt.subplots(figsize=(10, 8))

# TopoStake
ax.plot(N, path_topostake, 
        marker=markers['topostake'], linestyle=linestyles['topostake'], color=colors['topostake'], 
        label='TopoStake (Ours)')
ax.fill_between(N, path_topostake - err_topostake, path_topostake + err_topostake, 
                color=colors['topostake'], alpha=0.2)

# PoS
ax.plot(N, path_pos, 
        marker=markers['pos'], linestyle=linestyles['pos'], color=colors['pos'], 
        label='PoS')
ax.fill_between(N, path_pos - err_pos, path_pos + err_pos, 
                color=colors['pos'], alpha=0.1)

# Minotaur
ax.plot(N, path_minotaur, 
        marker=markers['minotaur'], linestyle=linestyles['minotaur'], color=colors['minotaur'], 
        label='Minotaur')
# 为了图面整洁，Minotaur 和 PoS 重合度高，可以不画它的误差带，或者画个虚线

# PoW (Baseline Gossip)
ax.plot(N, path_pow, 
        marker=markers['pow'], linestyle=linestyles['pow'], color=colors['pow'], 
        label='PoW')


format_axes(ax, 
            xlabel='Network Size ($N$)', 
            ylabel='Avg. Propagation Hops',)

ax.legend(fontsize=22, loc='upper left', frameon=True, fancybox=False, edgecolor='black', framealpha=0.95)
format_figure(fig)

plt.savefig(os.path.join(project_root, 'figures', 'path_length_n.png'), dpi=300, bbox_inches='tight')
# plt.show()