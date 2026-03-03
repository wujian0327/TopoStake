import os
from matplotlib import pyplot as plt
import numpy as np
from plot_style import get_project_root, set_plot_style, get_colors_and_styles, format_axes, format_figure
import pandas as pd

# 设置统一后的科研风格
set_plot_style('paper')
colors, linestyles, markers = get_colors_and_styles()


project_root = get_project_root()

topologies = ['ba', 'ws', 'er']
display_topologies = ['BA', 'WS', 'ER']

def calculate_throughput(alg):
    results = []
    for topo in topologies:
        file = os.path.join(project_root, f'result/metrics_{alg}_n_100_t_100_{topo}.csv')
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

topo_topostake = calculate_throughput('topostake')
topo_pos = calculate_throughput('pos')
topo_minotaur = calculate_throughput('minotaur')
topo_pow = calculate_throughput('pow')

fig, ax = plt.subplots(figsize=(10, 8))

# 绘制柱状图 (Grouped Bar Chart)
x = np.arange(len(topologies))  # label locations
width = 0.2  # the width of the bars

# Offsets for 4 bars centered around x
rects1 = ax.bar(x - 1.5*width, topo_topostake, width, label='TopoStake (Ours)', 
                color=colors['topostake'], edgecolor='black', hatch=markers['topostake']*2) # hatch optional, using marker symbol as pattern if possible or just standard hatches
# simplify hatch for bars to classic patterns if markers are specific shapes
# Let's just use colors and standard hatches for distinction in bar charts usually

rects2 = ax.bar(x - 0.5*width, topo_pos, width, label='PoS', 
                color=colors['pos'], edgecolor='black', hatch='//')

rects3 = ax.bar(x + 0.5*width, topo_minotaur, width, label='Minotaur', 
                color=colors['minotaur'], edgecolor='black', hatch='\\\\')

rects4 = ax.bar(x + 1.5*width, topo_pow, width, label='PoW', 
                color=colors['pow'], edgecolor='black', hatch='..')


format_axes(ax, 
            xlabel='Network Topology', 
            ylabel='Throughput (tx/s)')

# 设置Y轴范围
ax.set_ylim(0, 145) # slightly higher for bars labels if needed

# 调整X轴标签
ax.set_xticks(x)
ax.set_xticklabels(display_topologies, fontsize=20)

ax.legend(fontsize=20, loc='upper right', frameon=True, fancybox=False, edgecolor='black', framealpha=0.95)
format_figure(fig)

plt.savefig(os.path.join(project_root, 'figures', 'topology.png'), dpi=300, bbox_inches='tight')
# plt.show()