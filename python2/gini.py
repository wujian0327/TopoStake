import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import os
from plot_style import get_project_root, set_plot_style, get_colors_and_styles, format_axes, format_figure

project_root = get_project_root()
# --- 统一风格设置 ---
set_plot_style('paper')
colors, linestyles, markers = get_colors_and_styles()

def get_gini_data(alg):
    if alg == 'topostake_omega_0.5':
        file = os.path.join(project_root, f'result/gini_topostake_n_100_t_100_ba_omega_0.5.csv')
        if not os.path.exists(file):
            file = os.path.join(project_root, f'result/gini_topostake_n_100_t_100_ba_omega_0.5_beta_0.5.csv')
    elif alg == 'topostake_omega_0.8':
        file = os.path.join(project_root, f'result/gini_topostake_n_100_t_100_ba_omega_0.8.csv')
        if not os.path.exists(file):
            file = os.path.join(project_root, f'result/gini_topostake_n_100_t_100_ba_omega_0.8_beta_0.5.csv')
    else:
        file = os.path.join(project_root, f'result/gini_{alg}_n_100_t_100_ba.csv')
    try:
        df = pd.read_csv(file)
        if 'gini_coefficient' in df.columns and 'epoch' in df.columns:
            # Drop NaN values globally
            df = df.dropna(subset=['gini_coefficient', 'epoch'])
            # We assume metrics are collected periodically, group by epoch and take the mean Gini of the epoch
            gini_by_epoch = df.groupby('epoch')['gini_coefficient'].mean()
            return gini_by_epoch.index.to_numpy(), gini_by_epoch.values
    except Exception as e:
         print(f"Error loading data for {alg}: {e}")
         return np.array([]), np.array([])
    return np.array([]), np.array([])

epochs_pos, gini_pos = get_gini_data('pos')
epochs_pow, gini_pow = get_gini_data('pow')
epochs_minotaur, gini_minotaur = get_gini_data('minotaur')
epochs_topostake, gini_topostake = get_gini_data('topostake')
epochs_topostake_omega, gini_topostake_omega = get_gini_data('topostake_omega_0.5')
epochs_topostake_omega_08, gini_topostake_omega_08 = get_gini_data('topostake_omega_0.8')

# To align axes, find overlapping epochs or just plot them against their respective epoch arrays
# --- 绘图 ---
fig, ax = plt.subplots(figsize=(10, 8))

# 绘制 TopoStake (蓝线)
if len(epochs_topostake) > 0:
    ax.plot(epochs_topostake, gini_topostake, label='TopoStake ($\omega=1.0$)', 
            color=colors['topostake'], linestyle=linestyles['topostake'], 
            marker=markers['topostake'], markevery=max(1, len(epochs_topostake)//20), markersize=8)

# 绘制 TopoStake omega=0.8
if len(epochs_topostake_omega_08) > 0:
    ax.plot(epochs_topostake_omega_08, gini_topostake_omega_08, label='TopoStake ($\omega=0.8$)', 
            color=colors['topostake'], linestyle='-.', 
            marker='+', markevery=max(1, len(epochs_topostake_omega_08)//20), markersize=8)

# 绘制 TopoStake omega=0.5 (添加的新线，使用不同的线型或标记)
if len(epochs_topostake_omega) > 0:
    ax.plot(epochs_topostake_omega, gini_topostake_omega, label='TopoStake ($\omega=0.5$)', 
            color=colors['topostake'], linestyle='--', 
            marker='x', markevery=max(1, len(epochs_topostake_omega)//20), markersize=8)



# 绘制 PoS (红线)
if len(epochs_pos) > 0:
    ax.plot(epochs_pos, gini_pos, label='PoS', 
            color=colors['pos'], linestyle=linestyles['pos'], 
            marker=markers['pos'], markevery=max(1, len(epochs_pos)//20), markersize=8)

# 绘制 Minotaur (紫线)
if len(epochs_minotaur) > 0:
    ax.plot(epochs_minotaur, gini_minotaur, label='Minotaur', 
            color=colors['minotaur'], linestyle=linestyles['minotaur'], 
            marker=markers['minotaur'], markevery=max(1, len(epochs_minotaur)//20), markersize=8)

# 绘制 PoW (灰线)
if len(epochs_pow) > 0:
    ax.plot(epochs_pow, gini_pow, label='PoW', 
            color=colors['pow'], linestyle=linestyles['pow'], 
            marker=markers['pow'], markevery=max(1, len(epochs_pow)//20), markersize=8)

format_axes(ax, 
            xlabel='Evolution Time (Epochs)', 
            ylabel='Gini Coefficient')

ax.set_xlim(0, max([len(epochs_pos), len(epochs_pow), len(epochs_minotaur), len(epochs_topostake), len(epochs_topostake_omega), len(epochs_topostake_omega_08), 100]))
# 稍微放宽Y轴范围，容纳波动
ax.set_ylim(0.40, 0.75) 

# 添加背景分层
# 0.6 以下： (White)
# ax.axhspan(0.40, 0.60, facecolor='white', alpha=1.0, zorder=0)

# 0.6 以上： (Light Gray #F0F0F0)
# ax.axhspan(0.60, 0.75, facecolor='#F0F0F0', alpha=0.8, zorder=0)

max_epoch = max([len(epochs_pos), len(epochs_pow), len(epochs_minotaur), len(epochs_topostake), len(epochs_topostake_omega), len(epochs_topostake_omega_08), 100])
# 添加区域说明文字
ax.text(max_epoch * 0.98, 0.65, 'Higher Inequality', fontsize=20, color='gray', ha='right', va='center', fontweight='bold', zorder=1)
ax.text(max_epoch * 0.98, 0.265, 'Better Fairness', fontsize=20, color='gray', ha='right', va='center', fontweight='bold', zorder=1)

ax.set_ylim(0.25, 0.70)

# 添加分界线
ax.axhline(y=0.60, color='gray', linestyle='--', linewidth=1.5, alpha=0.95, zorder=2)

ax.legend(fontsize=20, loc='best', frameon=True, fancybox=False, edgecolor='black', framealpha=0.95)
format_figure(fig)

plt.savefig('figures/gini_evolution_realistic.png', dpi=300, bbox_inches='tight')
plt.savefig('figures/gini_evolution_realistic.pdf', dpi=300, bbox_inches='tight')
# plt.show()