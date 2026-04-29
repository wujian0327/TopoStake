import matplotlib.pyplot as plt
import numpy as np
# 假设这是您的 plot_style，为了代码能运行我先注释掉，您运行时保留即可
# from plot_style import set_plot_style, get_colors_and_styles, format_axes, format_figure

# --- 模拟您的风格设置 (您运行时请使用您自己的 import) ---
# set_plot_style('paper')
# colors, linestyles, markers = get_colors_and_styles()
# 为了演示，我手动定义一下颜色，您请用您的字典替换
colors = {'topostake': '#1f77b4', 'pos': '#2ca02c', 'minotaur': '#9467bd', 'pow': '#d62728'}
linestyles = {'topostake': '-', 'pos': '--', 'minotaur': ':', 'pow': '-.'}
markers = {'topostake': 's', 'pos': 'o', 'minotaur': 'd', 'pow': '^'}

# --- 模拟数据 (保持您的逻辑不变) ---
np.random.seed(42) 
epochs = np.arange(0, 501, 2)
num_points = len(epochs)
g0 = 0.60

def add_fluctuation(trend, scale=0.0003):
    noise = np.random.normal(0, scale, len(trend))
    return trend + noise

# 1. PoS (最高)
trend_pos = g0 + (0.70 - g0) * (1 - np.exp(-epochs / 200))
gini_pos = add_fluctuation(trend_pos, scale=0.005)

# 2. PoW
trend_pow = np.full(num_points, g0)
gini_pow = add_fluctuation(trend_pow, scale=0.008) 

# 3. Minotaur
trend_minotaur = g0 - (g0 - 0.55) * (1 - np.exp(-epochs / 250))
gini_minotaur = add_fluctuation(trend_minotaur, scale=0.004)

# 4. TopoStake (最低)
trend_topostake = g0 - (g0 - 0.50) * (1 - np.exp(-epochs / 300))
gini_topostake = add_fluctuation(trend_topostake, scale=0.004)

# --- 绘图 ---
fig, ax = plt.subplots(figsize=(10, 8))

ax.plot(epochs, gini_topostake, label='TopoStake (Ours)', 
        color=colors['topostake'], linestyle=linestyles['topostake'], 
        marker=markers['topostake'], markevery=25, markersize=8)

ax.plot(epochs, gini_pos, label='PoS', 
        color=colors['pos'], linestyle=linestyles['pos'], 
        marker=markers['pos'], markevery=25, markersize=8)

ax.plot(epochs, gini_minotaur, label='Minotaur', 
        color=colors['minotaur'], linestyle=linestyles['minotaur'], 
        marker=markers['minotaur'], markevery=25, markersize=8)

ax.plot(epochs, gini_pow, label='PoW', 
        color=colors['pow'], linestyle=linestyles['pow'], 
        marker=markers['pow'], markevery=25, markersize=8)

# --- 坐标轴设置 ---
ax.set_xlabel('Evolution Time (Epochs)', fontsize=14) # 假设 format_axes 做了这些
ax.set_ylabel('Gini Coefficient', fontsize=14)
ax.set_xlim(0, 550) # 🔥 稍微拉宽X轴，给右边的标注留点位置
ax.set_ylim(0.40, 0.78) # 🔥 稍微拉高Y轴

# ==========================================
# 🔥 核心功能：标注 "最低比最高好 XX%" 🔥
# ==========================================

# 1. 获取最后时刻的数值
y_high = trend_pos[-1]       # PoS 的终值 (约 0.70)
y_low = trend_topostake[-1]  # TopoStake 的终值 (约 0.50)
x_pos = 500                  # 标注的 X 轴位置

# 2. 计算提升百分比
# 公式: (High - Low) / High
improvement = (y_high - y_low) / y_high * 100 

# 3. 绘制双向箭头 (<->)
ax.annotate('', 
            xy=(x_pos, y_low),      # 箭头底部
            xytext=(x_pos, y_high), # 箭头顶部
            arrowprops=dict(arrowstyle='<->', color='black', lw=1.5, shrinkA=0, shrinkB=0))

# 4. 添加文字标注
# 位置放在箭头左侧一点点 (x_pos - 10)
mid_point = (y_high + y_low) / 2
ax.text(x_pos - 15, mid_point, 
        f'{improvement:.1f}% Improvement', # 自动计算，大概是 28.6%
        ha='right', va='center', 
        fontsize=12, fontweight='bold', color='#C00000')

# ==========================================
# 🔥 额外建议：添加 "Lower is Better" 指示 🔥
# ==========================================
ax.annotate('Lower is Better', 
            xy=(50, 0.45),       # 箭头指向 (左下角空旷处)
            xytext=(50, 0.55),   # 文字位置
            arrowprops=dict(facecolor='#C00000', edgecolor='#C00000', shrink=0.05, width=2),
            fontsize=12, fontweight='bold', color='#C00000',
            ha='center')

# Legend
ax.legend(fontsize=14, loc='upper left', frameon=True, fancybox=False, edgecolor='black', framealpha=0.95)

# 保存
plt.tight_layout()
plt.savefig('figures/gini_evolution_annotated.png', dpi=300, bbox_inches='tight')
plt.show()
