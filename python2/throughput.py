import os
from matplotlib import pyplot as plt
import numpy as np
from plot_style import get_project_root, set_plot_style, get_colors_and_styles, format_axes, format_figure
import pandas as pd

# 设置统一后的科研风格
set_plot_style('paper')
colors, linestyles, markers = get_colors_and_styles()

# 图 1: Throughput (吞吐量)
fig, ax = plt.subplots(figsize=(10, 8))  # 调整尺寸以适应大字体

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
            if 'throughput' in df.columns:
                valid_data = df[df['throughput'] > 0]
                results.append(valid_data['throughput'].mean() if not valid_data.empty else np.nan)
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

# 使用统一的格式化函数
format_axes(ax, 
            xlabel='Network Size ($N$)', 
            ylabel='Throughput (tx/s)', 
           )

ax.set_ylim(40, 110) 
ax.legend(fontsize=24, loc='best', frameon=True, fancybox=False, edgecolor='black', framealpha=0.95)
format_figure(fig)

plt.savefig(os.path.join(project_root, 'figures', 'throughput_n.png'), dpi=300, bbox_inches='tight')
plt.show()