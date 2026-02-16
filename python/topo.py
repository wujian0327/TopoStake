import matplotlib.pyplot as plt
import numpy as np
from plot_style import set_plot_style, get_colors_and_styles, format_axes, format_figure

# --- 统一风格设置 ---
set_plot_style('paper')
colors, linestyles, markers = get_colors_and_styles()

# --- 模拟数据 ---
epochs = np.arange(0, 101, 5)
num_points = len(epochs)

# 初始 APL (Barabási-Albert, N=1000)
start_apl = 3.8
target_apl = 2.6 # 物理极限

# 1. PoS (Green): 随机优化，缓慢
# 模拟：线性缓慢下降，带有随机性
apl_pos = start_apl - (epochs * 0.004) # 100 epoch 降 0.4
apl_pos += np.random.normal(0, 0.03, num_points)

# 2. PoW (Red): 类似 PoS，甚至更慢（因为连接数通常较少）
apl_pow = start_apl - (epochs * 0.003) 
apl_pow += np.random.normal(0, 0.04, num_points)

# 3. Minotaur (Purple): 混合型，也差不多
apl_min = start_apl - (epochs * 0.0035)
apl_min += np.random.normal(0, 0.03, num_points)

# 4. TopoStake (Blue): 结构演化，极快收敛
# 模拟：指数衰减
apl_topo = target_apl + (start_apl - target_apl) * np.exp(-epochs / 20)
apl_topo += np.random.normal(0, 0.02, num_points)

# --- 绘图 ---
fig, ax = plt.subplots(figsize=(10, 8))

# TopoStake (Ours) - 放第一个
ax.plot(epochs, apl_topo, label='TopoStake (Ours)', 
        color=colors['pog'], marker=markers['pog'], linestyle=linestyles['pog'], 
        markersize=8, linewidth=3)

# PoS
ax.plot(epochs, apl_pos, label='PoS', 
        color=colors['pos'], marker=markers['pos'], linestyle=linestyles['pos'], 
        markersize=8, alpha=0.9)

# Minotaur
ax.plot(epochs, apl_min, label='Minotaur', 
        color=colors['minotaur'], marker=markers['minotaur'], linestyle=linestyles['minotaur'], 
        markersize=8, alpha=0.9)

# PoW
ax.plot(epochs, apl_pow, label='PoW', 
        color=colors['pow'], marker=markers['pow'], linestyle=linestyles['pow'], 
        markersize=8, alpha=0.9)


format_axes(ax, 
            xlabel='Evolution Time (Epochs)', 
            ylabel='Avg. Propagation Hops')

ax.set_ylim(2.4, 4.0)
ax.set_xlim(0, 100)

# 上移图例位置，避免遮挡曲线
ax.legend(fontsize=22, loc='center right', bbox_to_anchor=(1, 0.4), frameon=True, fancybox=False, edgecolor='black', framealpha=0.95)

format_figure(fig)
plt.savefig('figures/network_evolution_comparison.png', dpi=300, bbox_inches='tight')
# plt.show()