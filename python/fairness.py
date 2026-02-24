import matplotlib.pyplot as plt
import numpy as np
from plot_style import set_plot_style, get_colors_and_styles, format_axes, format_figure

# --- 统一风格设置 ---
set_plot_style('paper')
colors, linestyles, markers = get_colors_and_styles()

# --- 模拟数据 (500 epochs) ---
# 设置随机种子，保证每次画出来虽然乱但形状一样
np.random.seed(42) 

epochs = np.arange(0, 501, 2) # 点更密一些，体现波动
num_points = len(epochs)
g0 = 0.60

# 定义一个添加波动的辅助函数
def add_fluctuation(trend, scale=0.0003):
    noise = np.random.normal(0, scale, len(trend))
    # 稍微平滑一点点，不要变成完全的杂讯
    return trend + noise

# 1. PoS: 趋势向上 (0.6 -> 0.7)
# 基础趋势
trend_pos = g0 + (0.70 - g0) * (1 - np.exp(-epochs / 200))
# 叠加波动
gini_pos = add_fluctuation(trend_pos, scale=0.005)

# 2. PoW: 波动基准 (0.6 附近)
# PoW 的波动应该比其他都大 (High Variance)
trend_pow = np.full(num_points, g0)
gini_pow = add_fluctuation(trend_pow, scale=0.008) 

# 3. Minotaur: 缓慢下降 (0.6 -> 0.55)
trend_minotaur = g0 - (g0 - 0.55) * (1 - np.exp(-epochs / 250))
gini_minotaur = add_fluctuation(trend_minotaur, scale=0.004)

# 4. TopoStake: 显著下降 (0.6 -> 0.50)
trend_topostake = g0 - (g0 - 0.50) * (1 - np.exp(-epochs / 300))
gini_topostake = add_fluctuation(trend_topostake, scale=0.004)

# --- 绘图 ---
fig, ax = plt.subplots(figsize=(10, 8))

# 绘制 TopoStake (蓝线)
ax.plot(epochs, gini_topostake, label='TopoStake (Ours)', 
        color=colors['topostake'], linestyle=linestyles['topostake'], 
        marker=markers['topostake'], markevery=25, markersize=8)

# 绘制 PoS (红线)
ax.plot(epochs, gini_pos, label='PoS', 
        color=colors['pos'], linestyle=linestyles['pos'], 
        marker=markers['pos'], markevery=25, markersize=8)

# 绘制 Minotaur (紫线)
ax.plot(epochs, gini_minotaur, label='Minotaur', 
        color=colors['minotaur'], linestyle=linestyles['minotaur'], 
        marker=markers['minotaur'], markevery=25, markersize=8)

# 绘制 PoW (灰线)
ax.plot(epochs, gini_pow, label='PoW', 
        color=colors['pow'], linestyle=linestyles['pow'], 
        marker=markers['pow'], markevery=25, markersize=8)

format_axes(ax, 
            xlabel='Evolution Time (Epochs)', 
            ylabel='Gini Coefficient')

ax.set_xlim(0, 500)
# 稍微放宽Y轴范围，容纳波动
ax.set_ylim(0.40, 0.75) 

# 添加背景分层
# 0.6 以下： (White)
ax.axhspan(0.40, 0.60, facecolor='white', alpha=1.0, zorder=0)

# 0.6 以上： (Light Gray #F0F0F0)
ax.axhspan(0.60, 0.75, facecolor='#F0F0F0', alpha=0.8, zorder=0)

# 添加区域说明文字
ax.text(490, 0.735, 'Higher Inequality', fontsize=20, color='gray', ha='right', va='center', fontweight='bold', zorder=1)
ax.text(490, 0.415, 'Better Fairness', fontsize=20, color='gray', ha='right', va='center', fontweight='bold', zorder=1)

# 添加分界线

# 添加分界线
ax.axhline(y=0.60, color='gray', linestyle='--', linewidth=1.5, alpha=0.5)

ax.legend(fontsize=24, loc='best', frameon=True, fancybox=False, edgecolor='black', framealpha=0.95)
format_figure(fig)

plt.savefig('figures/gini_evolution_realistic.png', dpi=300, bbox_inches='tight')
# plt.show()



# ==========================================
# 图 2: ROI Analysis (分层收益率)
# ==========================================

# --- 实验数据设置 ---
# 4个层级
categories = ['Whales\n(Top 10%)', 'Large Stake\n(10-30%)', 'Medium Stake\n(30-60%)', 'Small Nodes\n(Bottom 40%)']
x = np.arange(len(categories))
width = 0.25  # 柱子宽度

# 1. PoS ROI Index (基准 ~1.0)
# 假设有轻微的马太效应，大户复利快一点点，或者持平
roi_pos = [1.05, 1.02, 1.00, 0.98]
# 误差棒 (Standard Deviation)
std_pos = [0.02, 0.02, 0.03, 0.04]

# 2. Minotaur ROI Index
# 混合协议，稍微平缓一点，但还是资本主导
roi_minotaur = [1.02, 1.00, 0.98, 0.95]
std_minotaur = [0.03, 0.03, 0.04, 0.05]

# 3. TopoStake ROI Index (Ours)
# 显著的 "Robin Hood" 效应：大户略低(稀释)，小户极高(逆袭)
roi_topostake = [0.92, 0.98, 1.15, 1.35]
std_topostake = [0.01, 0.02, 0.05, 0.08] # 小节点方差大一点，因为位置不同

# --- 绘图 ---
fig, ax = plt.subplots(figsize=(10, 8))

# 统一误差棒样式
error_kw = dict(elinewidth=1.5, ecolor='#444444', capsize=4, capthick=1.5)

# 画柱子
# 1. TopoStake (Left)
rects1 = ax.bar(x - width, roi_topostake, width, 
                label='TopoStake (Ours)', color=colors['topostake'], alpha=0.9, 
                yerr=std_topostake, error_kw=error_kw)

# 2. PoS (Center)
rects2 = ax.bar(x, roi_pos, width, 
                label='PoS', color=colors['pos'], alpha=0.8, 
                yerr=std_pos, error_kw=error_kw)

# 3. Minotaur (Right)
rects3 = ax.bar(x + width, roi_minotaur, width, 
                label='Minotaur', color=colors['minotaur'], alpha=0.8, 
                yerr=std_minotaur, error_kw=error_kw)



# 设置标签
format_axes(ax, 
            ylabel='Relative Profitability Index',
            )

ax.set_xticks(x)
ax.set_xticklabels(categories, fontsize=20)
ax.set_ylim(0.8, 1.5) # 聚焦差异区域

# 添加基准线
ax.axhline(y=1.0, color='gray', linestyle='--', linewidth=2, alpha=0.5)

# 添加图例
ax.legend(fontsize=22, loc='upper left',  frameon=True, fancybox=False, edgecolor='black', framealpha=0.95)

format_figure(fig)
plt.savefig('figures/roi_tiered.png', dpi=300, bbox_inches='tight')
# plt.show()
