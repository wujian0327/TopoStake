import matplotlib.pyplot as plt
import numpy as np
from plot_style import set_plot_style, get_colors_and_styles, format_axes, format_figure

# --- 统一风格设置 ---
set_plot_style('paper')
colors, linestyles, markers = get_colors_and_styles()

import os
import pandas as pd
from plot_style import get_project_root
project_root = get_project_root()

def get_unstable_throughput(alg):
    u_values = [0, 10, 20, 30,40, 50]
    results = []
    for u in u_values:
        n = 100 - u
        if u == 0:
            file = os.path.join(project_root, f'result/metrics_{alg}_n_100_t_100_ba.csv')
        else:
            file = os.path.join(project_root, f'result/unstable{u}_{alg}_n_{n}_t_100_ba.csv')
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
    return np.array(u_values), np.array(results)

u_vals, tps_topo = get_unstable_throughput('topostake')
_, tps_pos = get_unstable_throughput('pos')
_, tps_min = get_unstable_throughput('minotaur')
# _, tps_pow = get_unstable_throughput('pow')

# --- 绘图 ---
fig, ax = plt.subplots(figsize=(10, 8))

ax.plot(u_vals, tps_topo, 
        label='TopoStake (Ours)', color=colors['topostake'], marker=markers['topostake'], linestyle=linestyles['topostake'])

ax.plot(u_vals, tps_pos, 
        label='PoS', color=colors['pos'], marker=markers['pos'], linestyle=linestyles['pos'])

ax.plot(u_vals, tps_min, 
        label='Minotaur', color=colors['minotaur'], marker=markers['minotaur'], linestyle=linestyles['minotaur'])


# 设置轴
format_axes(ax, 
            xlabel='Unstable Node Rate (%)', 
            ylabel='Throughput (Tx/s)')

ax.set_ylim(40, 110) 
ax.set_xlim(0, 51)
ax.set_xticks(np.arange(0, 55, 10))

# 图例位置
ax.legend(fontsize=24, loc='lower left', frameon=True, fancybox=False, edgecolor='black', framealpha=0.95)

format_figure(fig)
plt.savefig(os.path.join(project_root, 'figures', 'unstable.png'), dpi=300, bbox_inches='tight')
# plt.show()