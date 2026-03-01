import os
from matplotlib import pyplot as plt
import numpy as np
from plot_style import get_project_root, set_plot_style, get_colors_and_styles, format_axes, format_figure
import pandas as pd

# 设置统一后的科研风格
set_plot_style('paper')
colors, linestyles, markers = get_colors_and_styles()


project_root = get_project_root()
input_rate = np.array([50, 100, 150, 200, 250, 300])

def calculate_throughput(alg):
    results = []
    for t in input_rate:
        file = os.path.join(project_root, f'result/metrics_{alg}_n_100_t_{t}_ba.csv')
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

confirmed_topostake = calculate_throughput('topostake')
confirmed_pos = calculate_throughput('pos')
confirmed_minotaur = calculate_throughput('minotaur')
confirmed_pow = calculate_throughput('pow')


fig, ax = plt.subplots(figsize=(10, 8))

ax.plot(input_rate, confirmed_topostake, 
        marker=markers['topostake'], linestyle=linestyles['topostake'], color=colors['topostake'], 
        label='TopoStake (Ours)')

ax.plot(input_rate, confirmed_pos, 
        marker=markers['pos'], linestyle=linestyles['pos'], color=colors['pos'], 
        label='PoS')

ax.plot(input_rate, confirmed_minotaur, 
        marker=markers['minotaur'], linestyle=linestyles['minotaur'], color=colors['minotaur'], 
        label='Minotaur')

ax.plot(input_rate, confirmed_pow, 
        marker=markers['pow'], linestyle=linestyles['pow'], color=colors['pow'], 
        label='PoW')

format_axes(ax, 
            xlabel='Input Transaction Rate (tx/s)', 
            ylabel='Confirmed Throughput (tx/s)')

ax.set_ylim(0, 200)
ax.legend(fontsize=22, loc='upper left', frameon=True, fancybox=False, edgecolor='black', framealpha=0.95)
format_figure(fig)

plt.savefig(os.path.join(project_root, 'figures', 'confirmed_throughput_vs_input.png'), dpi=300, bbox_inches='tight')
# plt.show()