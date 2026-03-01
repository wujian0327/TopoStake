import os
from matplotlib import pyplot as plt
import numpy as np
from plot_style import get_project_root, set_plot_style, get_colors_and_styles, format_axes, format_figure
import pandas as pd

set_plot_style('paper')
colors, linestyles, markers = get_colors_and_styles()

project_root = get_project_root()

def get_latency_data(alg):
    delays = []
    import glob
    for file in glob.glob(os.path.join(project_root, f'result/metrics_{alg}_n_100_t_100_ba.csv')):
        try:
            df = pd.read_csv(file)
            if 'avg_tx_delay_s' in df.columns:
                valid = df[df['avg_tx_delay_s'] > 0]['avg_tx_delay_s']
                if not valid.empty:
                    delays.extend(valid.tolist())
        except Exception:
            pass
    
    if len(delays) == 0:
        return np.array([0])
        
    delays = np.array(delays)
    threshold = np.percentile(delays, 85)
    filtered_delays = delays[delays <= threshold]
    
    return filtered_delays

data_topostake = get_latency_data('topostake')
data_pos = get_latency_data('pos')
data_minotaur = get_latency_data('minotaur')
data_pow = get_latency_data('pow')

data = [data_topostake, data_pos, data_minotaur, data_pow]
labels = ['TopoStake\n(Ours)', 'PoS', 'Minotaur', 'PoW']
plot_colors = [colors['topostake'], colors['pos'], colors['minotaur'], colors['pow']]

# --- 2. 绘制箱线图 ---
fig, ax = plt.subplots(figsize=(10, 8))

bplot = ax.boxplot(data, patch_artist=True, tick_labels=labels, 
                   notch=False, vert=True, showfliers=False, widths=0.6,
                   flierprops=dict(marker='o', markerfacecolor='gray', markersize=8, linestyle='none', alpha=0.6),
                   medianprops=dict(color='black', linewidth=2.5),
                   boxprops=dict(linewidth=2),
                   whiskerprops=dict(linewidth=2),
                   capprops=dict(linewidth=2))

# --- 3. 美化 ---
for patch, color in zip(bplot['boxes'], plot_colors):
    patch.set_facecolor(color)
    patch.set_alpha(0.7)

# --- 4. 坐标轴设置 (线性) ---
format_axes(ax, 
            ylabel='Transaction Latency (s)')

# 将坐标轴改为对数轴以适应差异过大的情况
ax.set_yscale('log')

# 自定义由于对数轴导致的难看的科学计数法，将其转换为容易理解的数字 1, 10, 100 等
from matplotlib.ticker import FuncFormatter
ax.yaxis.set_major_formatter(FuncFormatter(lambda y, _: '{:g}'.format(y)))

format_figure(fig)

plt.savefig(os.path.join(project_root, 'figures', 'latency_n.png'), dpi=300, bbox_inches='tight')
# plt.show()
