import sys
import os
# 添加 python 目录到路径以导入 plot_style
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../python')))

import matplotlib.pyplot as plt
import numpy as np
from plot_style import set_plot_style, get_colors_and_styles, format_axes, format_figure

# --- 统一风格设置 ---
set_plot_style('paper')
colors, linestyles, markers = get_colors_and_styles()

# --- 模拟数据 ---
path_lengths = np.arange(1, 51) # 1 到 50 hops

# 常量 (Bytes)
BLOCK_SIZE_BYTES = 500 * 1024 # 500 KB (Reduced from Standard 1MB)
ADDR_SIZE = 20
BLS_SIG = 48

# 1. PoS Total Size (Baseline)
# 恒定为 500 KB
pos_sizes_bytes = np.full(len(path_lengths), BLOCK_SIZE_BYTES)

# 2. TopoStake Total Size (Ours)
# 1MB + Path Overhead
overhead_bytes = (path_lengths * ADDR_SIZE) + BLS_SIG
topo_sizes_bytes = pos_sizes_bytes + overhead_bytes

# 转换为 KB 以方便展示 (1 MB = 1024 KB)
pos_sizes_kb = pos_sizes_bytes / 1024
topo_sizes_kb = topo_sizes_bytes / 1024

# --- 绘图 ---
fig, ax = plt.subplots(figsize=(10, 8))

# TopoStake (Blue Solid) - Slightly above 1024 KB
ax.plot(path_lengths, topo_sizes_kb, 
        label='TopoStake Block (with Path)', color=colors['topostake'], 
        linestyle=linestyles['topostake'], linewidth=3.5, marker=markers['topostake'], markevery=5)

# Standard PoS (Green Dashed) - 1024 KB
ax.plot(path_lengths, pos_sizes_kb, 
        label='Standard Block (500 KB)', color=colors['pos'], 
        linestyle=linestyles['pos'], linewidth=3, marker=markers['pos'], markevery=5)

# 填充区域：展示微小的增量
ax.fill_between(path_lengths, pos_sizes_kb, topo_sizes_kb, color=colors['topostake'], alpha=0.1)

# 关键注释：强调“微乎其微”
# 在 L=50 处标注
val_50 = topo_sizes_kb[-1] # 约 501 KB
val_base = pos_sizes_kb[-1] # 500 KB
diff = val_50 - val_base    # 约 1 KB
ax.annotate(f'Max Overhead at 50 Hops:\nOnly +{diff:.2f} KB (< 0.3%)', 
             xy=(50, val_50), xytext=(20, val_base + 1.2),
             arrowprops=dict(facecolor='black', arrowstyle='->', linewidth=2),
             fontsize=18, bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="black", alpha=0.8))

format_axes(ax, 
            xlabel='Propagation Path Length (Hops)', 
            ylabel='Total Block Size (KB)')

# 设置 Y 轴范围：只看 500 附近
# 这样才能看出两条线的分离
ax.set_ylim(499.5, 502.0) 
ax.set_xlim(1, 50)

ax.legend(fontsize=22, loc='upper left', frameon=True, fancybox=False, edgecolor='black', framealpha=0.95)

format_figure(fig)
plt.savefig('figures/block_size_impact.png', dpi=300, bbox_inches='tight')
# plt.show()
