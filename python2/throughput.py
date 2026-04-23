import os
from matplotlib import pyplot as plt
import numpy as np
from plot_style import get_project_root, set_plot_style, get_colors_and_styles, format_axes, format_figure
import pandas as pd

# 设置统一后的科研风格
set_plot_style('paper')
colors, linestyles, markers = get_colors_and_styles()

# 图 1: Throughput (吞吐量)
fig, (ax1, ax2) = plt.subplots(2, 1, sharex=True, figsize=(10, 8), gridspec_kw={'height_ratios': [2, 1]})
fig.subplots_adjust(hspace=0.1)

N = np.array([50, 100, 150, 200, 250, 300])

project_root = get_project_root()


def calculate_throughput(alg):
    results = []
    for n in N:
        file = os.path.join(project_root, f'result/metrics_{alg}_n_{n}_t_100_ba.csv')
        try:
            if not os.path.exists(file):
                 results.append(np.nan)
                 continue
            df = pd.read_csv(file)
            if 'tx_count' in df.columns and 'timestamp' in df.columns:
                valid_df = df[df['tx_count'] > 0]
                if not valid_df.empty:
                    total_tx = valid_df['tx_count'].sum()
                    total_time = valid_df['timestamp'].max() - df['timestamp'].min()
                    if total_time > 0:
                        results.append(total_tx / total_time)
                    else:
                        results.append(np.nan)
                else:
                    results.append(np.nan)
            else:
                results.append(np.nan)
        except Exception:
            results.append(np.nan)
    return np.array(results)

# 1. 吞吐量数据 (TPS)
# 对应实验结果数据实时计算
tps_topostake = calculate_throughput('topostake')
tps_pos = calculate_throughput('pos')
tps_minotaur = calculate_throughput('minotaur')
tps_pow = calculate_throughput('pow')

for ax in (ax1, ax2):
    ax.plot(N, tps_topostake, 
            marker=markers['topostake'], linestyle=linestyles['topostake'], color=colors['topostake'], 
            label='TopoStake (Ours)')

    ax.plot(N, tps_pos, 
            marker=markers['pos'], linestyle=linestyles['pos'], color=colors['pos'], 
            label='PoS')

    ax.plot(N, tps_minotaur, 
            marker=markers['minotaur'], linestyle=linestyles['minotaur'], color=colors['minotaur'], 
            label='Minotaur')

    ax.plot(N, tps_pow, 
            marker=markers['pow'], linestyle=linestyles['pow'], color=colors['pow'], 
            label='PoW')

# Set specific ylim for each subplot to create a broken axis
ax1.set_ylim(88, 102)
ax2.set_ylim(45, 58)

# Hide spines to create jump
ax1.spines['bottom'].set_visible(False)
ax2.spines['top'].set_visible(False)
ax1.xaxis.tick_top()
ax1.tick_params(labeltop=False)  # keep labels at the bottom ax2 only
ax2.xaxis.tick_bottom()

# Plot the break marks
d = .015
kwargs = dict(marker=[(-1, -d), (1, d)], markersize=15,
              linestyle="none", color='k', mec='k', mew=1.5, clip_on=False)
ax1.plot([0, 1], [0, 0], transform=ax1.transAxes, **kwargs)
ax2.plot([0, 1], [1, 1], transform=ax2.transAxes, **kwargs)

# 使用统一的格式化函数
format_axes(ax1, xlabel='', ylabel='')
format_axes(ax2, xlabel='Network Size ($N$)', ylabel='')

fig.supylabel('Throughput (tx/s)', fontsize=28, x=0.02)

ax1.legend(fontsize=24, loc='best', frameon=True, fancybox=False, edgecolor='black', framealpha=0.95)
format_figure(fig)

plt.savefig(os.path.join(project_root, 'figures', 'throughput_n.png'), dpi=300, bbox_inches='tight')
plt.savefig(os.path.join(project_root, 'figures', 'throughput_n.pdf'), dpi=300, bbox_inches='tight')
# plt.show()