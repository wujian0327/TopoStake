import sys
import os
import matplotlib.pyplot as plt
import numpy as np
from plot_style import get_project_root, set_plot_style, get_colors_and_styles, format_axes, format_figure

project_root = get_project_root()
# --- 统一风格设置 ---
set_plot_style('paper')
colors, linestyles, markers = get_colors_and_styles()

# --- 数据计算 ---
tx_counts = np.arange(0, 301) # 0 到 300 个交易

# 常量 (Bytes)
HEADER_SIZE = 100
TX_SIZE = 200
ADDR_SIZE = 20
BLS_SIG = 48
PATH_LENGTH = 4

# 1. PoS Total Size (Baseline)
# Block Header + (Tx Size * Tx Count)
pos_sizes_bytes = HEADER_SIZE + (TX_SIZE * tx_counts)

# 2. TopoStake Total Size (Ours)
# PoS Size + ((Path Length * Addr Size + BLS Sig) * Tx Count)
per_tx_overhead = (PATH_LENGTH * ADDR_SIZE) + BLS_SIG
topo_sizes_bytes = pos_sizes_bytes + (per_tx_overhead * tx_counts)

# 转换为 KB 以方便展示
pos_sizes_kb = pos_sizes_bytes / 1024
topo_sizes_kb = topo_sizes_bytes / 1024

# --- 绘图 ---
fig, ax = plt.subplots(figsize=(10, 8))

# TopoStake (Blue Solid)
ax.plot(tx_counts, topo_sizes_kb, 
        label='TopoStake Block (with Paths)', color=colors['topostake'], 
        linestyle=linestyles['topostake'], linewidth=3.5, marker=markers['topostake'], markevery=50)

# Standard PoS (Green Dashed)
ax.plot(tx_counts, pos_sizes_kb, 
        label='Standard PoS Block', color=colors['pos'], 
        linestyle=linestyles['pos'], linewidth=3, marker=markers['pos'], markevery=50)

# 填充区域：展示增量
ax.fill_between(tx_counts, pos_sizes_kb, topo_sizes_kb, color=colors['topostake'], alpha=0.1)

# 关键注释：强调“微乎其微”
val_500_topo = topo_sizes_kb[-1] 
val_500_pos = pos_sizes_kb[-1] 
diff = val_500_topo - val_500_pos
percentage = (diff / val_500_pos) * 100
# ax.annotate(f'Overhead at 500 Txs:\n+{diff:.2f} KB (+{percentage:.1f}%)', 
#              xy=(500, val_500_topo), xytext=(200, val_500_topo * 0.9),
#              arrowprops=dict(facecolor='black', arrowstyle='->', linewidth=2),
#              fontsize=18, bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="black", alpha=0.8))

format_axes(ax, 
            xlabel='Number of Transactions per Block', 
            ylabel='Total Block Size (KB)')

ax.set_ylim(0, val_500_topo * 1.1) 
ax.set_xlim(0, 310)

ax.legend(fontsize=22, loc='upper left', frameon=True, fancybox=False, edgecolor='black', framealpha=0.95)

format_figure(fig)
plt.savefig(os.path.join(project_root, 'figures', 'block_size_impact.png'), dpi=300, bbox_inches='tight')

# plt.show()
