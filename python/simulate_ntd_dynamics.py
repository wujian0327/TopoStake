import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator
import os

from plot_style import set_plot_style, format_axes, format_figure, format_axes_background

set_plot_style('paper')

def simulate_ntd_dynamics():
    epochs = 100
    attack_start = 20
    attack_end = 50
    
    # 真实网络参数
    true_diameter = 6
    honest_mean = 6 # 修改为 6，使 NTD 收敛值与真实直径重合，便于观察
    honest_std = 1.5
    
    # 攻击参数
    attack_len_min = 15
    attack_len_max = 20
    attack_ratio = 0.1 # 10% 的交易是攻击交易
    
    # 初始 NTD
    ntd_naive = 0.0
    
    history = []
    
    for epoch in range(epochs):
        # 1. 生成本轮交易路径数据
        n_tx = 1000
        
        # 诚实交易
        honest_count = n_tx
        if attack_start <= epoch <= attack_end:
            honest_count = int(n_tx * (1 - attack_ratio))
            attack_count = n_tx - honest_count
        else:
            attack_count = 0
            
        # 生成诚实路径长度 (截断正态分布)
        honest_paths = np.random.normal(honest_mean, honest_std, honest_count)
        honest_paths = np.clip(honest_paths, 1, true_diameter + 2) # 允许少量波动超过直径
        
        paths = list(honest_paths)
        
        # 生成攻击路径
        if attack_count > 0:
            attack_paths = np.random.uniform(attack_len_min, attack_len_max, attack_count)
            paths.extend(attack_paths)
            
        paths = np.array(paths)
        
        # 2. 计算本轮的目标 NTD
        # 策略 A: Naive (复刻 Rust 代码: 基于平均值)
        # Rust: p_ave = sum(len-1) / count; target = ceil(p_ave)
        # 注意: 这里的 paths 已经是 hop 数了 (len-1)
        target_naive = np.ceil(np.mean(paths))
        
        # 3. 更新 NTD (步进式 +1/-1)
        if ntd_naive < target_naive:
            ntd_naive += 1.0
        elif ntd_naive > target_naive:
            ntd_naive -= 1.0
            
        
        history.append({
            'epoch': epoch,
            'ntd_naive': ntd_naive,
            'true_diameter': true_diameter,
            'honest_avg': np.mean(honest_paths),
            'all_paths_avg': np.mean(paths), # 添加这一行
            'attack_active': 1 if attack_count > 0 else 0,
            'max_observed': np.max(paths)
        })
        
    df = pd.DataFrame(history)
    return df

def plot_ntd_dynamics(df):
    fig, ax = plt.subplots(figsize=(10, 7))
    
    # 1. 绘制背景区域 (攻击区间)
    attack_indices = df[df['attack_active'] == 1].index
    if len(attack_indices) > 0:
        ax.axvspan(attack_indices[0], attack_indices[-1], color='#d62728', alpha=0.1, label='Long-Range Attack Phase')
        
    # 2. 绘制基准线 (Ground Truth)
    ax.plot(df['epoch'], df['honest_avg'], color='gray', linestyle='--',  label='Avg Honest Path Length', alpha=0.8)
    
    # 3. 绘制 Naive NTD
    ax.plot(df['epoch'], df['ntd_naive'], color='#ff7f0e', linestyle='-', label='Dynamic NTD')
    
    # 4. 绘制攻击信号 (散点示意)
    attack_phase = df[df['attack_active'] == 1]
    if not attack_phase.empty:
        sample_indices = np.random.choice(attack_phase.index, 50)
        x_scatter = sample_indices
        y_scatter = np.random.uniform(15, 20, 50)
        ax.scatter(x_scatter, y_scatter, color='#d62728', alpha=0.3, s=30, marker='x', label='Attack Paths (15-20 hops)')

    # 应用标准格式化
    format_axes(ax, xlabel='Epoch', ylabel='NTD', grid=True)
    
    # 强制纵坐标为整数
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    
    ax.legend(loc='upper right', fontsize=16, frameon=True, fancybox=False, edgecolor='black', framealpha=0.95)
    
    # 应用图形背景格式
    format_figure(fig)
    format_axes_background(ax)
    
    # 保存
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    output_dir = os.path.join(root_dir, 'figures')
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    output_path = os.path.join(output_dir, 'ntd_dynamics_simulation.png')
    plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='white')
    print(f"Plot saved to: {output_path}")
    plt.close()

if __name__ == "__main__":
    df = simulate_ntd_dynamics()
    plot_ntd_dynamics(df)
