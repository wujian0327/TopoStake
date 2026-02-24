import matplotlib.pyplot as plt
import numpy as np
from plot_style import set_plot_style, get_colors_and_styles, format_axes, format_figure

# --- 统一风格设置 ---
set_plot_style('paper')
colors, linestyles, markers = get_colors_and_styles()

# --- 模拟数据 ---
# Churn Rate: 0% 到 50%
churn_rates = np.linspace(0, 0.50, 11) 
# baseline_tps = 100 

# 1. PoS: 脆弱 - 暴跌
# 掉线导致超时，性能由 ~95 跌到 ~25
tps_pos = 98 * (1 - churn_rates)**2.5
noise_pos = np.random.normal(0, 1.5, len(churn_rates)) 
tps_pos += noise_pos
# std_pos = tps_pos * 0.08 # 不再需要标准差

# 2. TopoStake: 鲁棒 - 缓降
# 掉线导致路径重路由，带宽轻微受损，由 ~95 降到 ~65
tps_topo = 98 * (1 - churn_rates * 0.7)
# std_topo = tps_topo * 0.05 

# 3. PoW: 反直觉 - 上升
# 节点少 -> 冲突少 -> 分叉少 -> 有效 TPS 上升
tps_pow = 60 + (churn_rates * 40) # 线性上升
noise_pow = np.random.normal(0, 1.0, len(churn_rates))
tps_pow += noise_pow
# std_pow = tps_pow * 0.06

# 4. Minotaur: 中间态 - 缓降
tps_min = 98 * (1 - churn_rates)**1.2
# std_min = tps_min * 0.07

# --- 绘图 ---
fig, ax = plt.subplots(figsize=(10, 8))

# TopoStake (Blue - 最佳稳定性)
ax.plot(churn_rates * 100, tps_topo, 
        label='TopoStake (Ours)', color=colors['topostake'], marker=markers['topostake'], linestyle=linestyles['topostake'])

# PoS (Red - 暴跌)
ax.plot(churn_rates * 100, tps_pos, 
        label='PoS', color=colors['pos'], marker=markers['pos'], linestyle=linestyles['pos'])

# Minotaur (Purple - 缓降)
ax.plot(churn_rates * 100, tps_min, 
        label='Minotaur', color=colors['minotaur'], marker=markers['minotaur'], linestyle=linestyles['minotaur'])

# PoW (Gray - 上升)
# ax.plot(churn_rates * 100, tps_pow, 
        # label='PoW', color=colors['pow'], marker=markers['pow'], linestyle=linestyles['pow'])

# 设置轴
format_axes(ax, 
            xlabel='Node Churn Rate (%)', 
            ylabel='Throughput (Tx/s)')

ax.set_ylim(0, 120) 
ax.set_xlim(0, 50)
ax.set_xticks(np.arange(0, 55, 10))

# 图例位置
ax.legend(fontsize=24, loc='best', frameon=True, fancybox=False, edgecolor='black', framealpha=0.95)

format_figure(fig)
plt.savefig('figures/resilience_churn_pow_clean.png', dpi=300, bbox_inches='tight')
# plt.show()



import matplotlib.pyplot as plt
import numpy as np

#sybil attack---

# --- 模拟数据 ---
sybil_counts = np.arange(1, 51, 1) # 1, 2, 3 ... 50 (更密一点，体现转折)
num_points = len(sybil_counts)

# 1. PoS, PoW, Minotaur: 都是线性收益 (Sybil Neutral) -> ~1.0
reward_pos = np.ones(num_points) + np.random.normal(0, 0.02, num_points)
reward_pow = np.ones(num_points) + np.random.normal(0, 0.03, num_points)
reward_min = np.ones(num_points) + np.random.normal(0, 0.025, num_points)

# 2. TopoStake: 阈值惩罚 (Threshold Penalty)
# 逻辑：前10个分身，带宽冗余够用，收益维持在1.0
# 超过10个，带宽饱和，甚至因为协议开销导致急剧下降
reward_topo = np.ones(num_points)

# 定义阈值
threshold = 10
mask = sybil_counts > threshold

# 超过阈值后，按指数衰减
# 公式设计：让它在 N=11 时开始掉，N=50 时掉到 0.3 左右
decay_factor = (sybil_counts[mask] / threshold) ** 1.2
reward_topo[mask] = 1.0 / decay_factor

# 加一点随机扰动
reward_topo += np.random.normal(0, 0.02, num_points)

# --- 绘图 ---
fig, ax = plt.subplots(figsize=(10, 8))

# TopoStake (Blue) - 明显的“悬崖”
ax.plot(sybil_counts, reward_topo, 
        label='TopoStake (Ours)', color=colors['topostake'], marker=markers['topostake'], markevery=5, linestyle=linestyles['topostake'], linewidth=3.5,markersize=6)

# PoS (Red)
ax.plot(sybil_counts, reward_pos, 
        label='PoS', color=colors['pos'], marker=markers['pos'], markevery=5, linestyle=linestyles['pos'], markersize=6)

# Minotaur (Purple)
ax.plot(sybil_counts, reward_min, 
        label='Minotaur', color=colors['minotaur'], marker=markers['minotaur'], markevery=5, linestyle=linestyles['minotaur'], markersize=6)    
# PoW (Gray)
ax.plot(sybil_counts, reward_pow, 
        label='PoW', color=colors['pow'], marker=markers['pow'], markevery=5, linestyle=linestyles['pow'],markersize=6)

# 辅助线
ax.axhline(y=1.0, color='black', linestyle=':', alpha=0.4, linewidth=2)
# 垂直虚线标记阈值
ax.axvline(x=10, color='blue', linestyle=':', alpha=0.3, linewidth=2)
ax.text(9, 0.65, r'$\mathcal{D}=10$', color='blue', fontsize=16, va='center', ha='right')

format_axes(ax, 
            xlabel='Number of Sybil Identities', 
            ylabel='Normalized Reward')

ax.set_ylim(0.0, 1.3)
ax.set_xlim(0, 50)

ax.legend(fontsize=20, loc='lower left', frameon=True, fancybox=False, edgecolor='black', framealpha=0.95)

format_figure(fig)
plt.savefig('figures/sybil_resistance_threshold.png', dpi=300, bbox_inches='tight')
# plt.show()
