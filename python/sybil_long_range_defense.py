import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import os

from plot_style import set_plot_style, format_axes, format_figure, format_axes_background

# 设置紧凑风格（小号字体）
set_plot_style('paper')

def compute_position_weight(position, path_length):
    """
    计算位置权重 (参考 src/consensus/topostake.rs)
    alpha_k(L) = 2(L - k + 1) / (L(L + 1))
    注意: position 从 1 开始
    """
    if path_length == 0 or position > path_length or position == 0:
        return 0.0
    return 2.0 * (path_length - position + 1) / (path_length * (path_length + 1))

def simulate_sybil_attack_data(honest_path_len=0):
    """
    模拟女巫攻击（长链攻击）下的收益数据
    """
    # 参数设置
    NTD = 6          # 网络直径阈值 (Network Traversal Diameter)
    HONEST_PATH_LEN = honest_path_len  # 诚实节点的路径长度部分
    
    results = []

    # 模拟攻击者将身份拆分为 N 个 (1 到 15)
    for n_sybil in range(1, 16):
        # 1. 路径长度计算
        total_path_len = HONEST_PATH_LEN + n_sybil
        
        # 2. 计算攻击者获得的原始贡献分数
        sybil_raw_score_sum = 0.0
        for i in range(n_sybil):
            position = HONEST_PATH_LEN + 1 + i
            weight = compute_position_weight(position, total_path_len)
            sybil_raw_score_sum += weight
            
        # 3. 计算 NTD 惩罚因子
        if total_path_len > NTD:
            penalty_factor = (NTD / total_path_len) ** 2
        else:
            penalty_factor = 1.0
            
        # 4. 计算最终收益
        propagation_score = sybil_raw_score_sum * penalty_factor
        
        results.append({
            "sybil_count": n_sybil,
            "path_length": total_path_len,
            "raw_score": sybil_raw_score_sum,
            "penalty_factor": penalty_factor,
            "propagation_score": propagation_score
        })

    return pd.DataFrame(results)

def plot_sybil_long_range_defense():
    df_pure = simulate_sybil_attack_data(honest_path_len=0)
    df_single = simulate_sybil_attack_data(honest_path_len=1)
    df_mixed = simulate_sybil_attack_data(honest_path_len=3)
    
    # 限制横坐标最大为 15
    df_pure = df_pure[df_pure['path_length'] <= 15]
    df_single = df_single[df_single['path_length'] <= 15]
    df_mixed = df_mixed[df_mixed['path_length'] <= 15]

    NTD = 6
    
    # 创建图表
    fig, ax1 = plt.subplots(figsize=(10, 7))

    # 绘制收益曲线 (左轴)
    color_pure = '#1f77b4'
    color_single = '#9467bd' # 紫色
    color_mixed = '#2ca02c'
    
    # 修改 X 轴标签为 Total Path Length
    format_axes(ax1, xlabel='Total Path Length', 
                ylabel='Propagation Score', grid=True)
    
    ax1.tick_params(axis='x')
    
    # Grid styling
    ax1.grid(True, alpha=0.5, linestyle='--', linewidth=0.7, color='gray')
    ax1.set_axisbelow(True)
    
    # 绘制三条线，X轴使用 path_length
    line1, = ax1.plot(df_pure['path_length'], df_pure['propagation_score'], 'o-', color=color_pure,  label='Pure Sybil (Honest=0)')
    line2, = ax1.plot(df_single['path_length'], df_single['propagation_score'], 'D-', color=color_single,  label='Single Honest (Honest=1)')
    line3, = ax1.plot(df_mixed['path_length'], df_mixed['propagation_score'], '^-', color=color_mixed, label='Mixed Sybil (Honest=3)')

    # 标记 NTD 阈值区域 (统一为 NTD=6)
    plt.axvline(x=NTD, color='#d62728', linestyle='--', alpha=0.8, linewidth=2)
    
    # 区域
    ax1.axvspan(NTD, 15, color='#d62728', alpha=0.1)
    
    # 设置X轴范围
    ax1.set_xlim(left=0, right=15)

    # 添加注释
    # Pure Max
    max_pure_idx = df_pure['propagation_score'].idxmax()
    max_pure_x = df_pure.loc[max_pure_idx, 'path_length']
    max_pure_y = df_pure.loc[max_pure_idx, 'propagation_score']
    
    # ax1.annotate(f'Max (Pure)', 
    #              xy=(max_pure_x, max_pure_y), 
    #              xytext=(max_pure_x, max_pure_y + 0.05),
    #              arrowprops=dict(facecolor=color_pure, shrink=0.05),
    #              fontsize=14, fontweight='bold', ha='center', color=color_pure)

    # Single Max
    max_single_idx = df_single['propagation_score'].idxmax()
    max_single_x = df_single.loc[max_single_idx, 'path_length']
    max_single_y = df_single.loc[max_single_idx, 'propagation_score']
    
    # ax1.annotate(f'Max (Single)', 
    #              xy=(max_single_x, max_single_y), 
    #              xytext=(max_single_x, max_single_y + 0.05),
    #              arrowprops=dict(facecolor=color_single, shrink=0.05),
    #              fontsize=14, fontweight='bold', ha='center', color=color_single)

    # Mixed Max
    max_mixed_idx = df_mixed['propagation_score'].idxmax()
    max_mixed_x = df_mixed.loc[max_mixed_idx, 'path_length']
    max_mixed_y = df_mixed.loc[max_mixed_idx, 'propagation_score']
    
    # ax1.annotate(f'Max (Mixed)', 
    #              xy=(max_mixed_x, max_mixed_y), 
    #              xytext=(max_mixed_x, max_mixed_y + 0.05),
    #              arrowprops=dict(facecolor=color_mixed, shrink=0.05),
    #              fontsize=14, fontweight='bold', ha='center', color=color_mixed)

    ax1.annotate(f'NTD Threshold\n(Path>{NTD})', 
                 xy=(NTD, df_pure.loc[df_pure['path_length'] >= NTD, 'propagation_score'].iloc[0]), 
                 xytext=(NTD - 4.5, max_pure_y - 0.15),
                 arrowprops=dict(facecolor='#d62728', shrink=0.05),
                 fontsize=18, color='#d62728', fontweight='bold')

    # 标题
    # plt.title('Sybil Resistance', fontsize=22, fontweight='bold')
    
    # 图例
    lines = [line1, line2, line3]
    labels = [l.get_label() for l in lines]
    ax1.legend(lines, labels, loc='upper right', fontsize=18, frameon=True, fancybox=False, edgecolor='black', framealpha=0.95)

    # 应用图形背景格式
    format_figure(fig)
    format_axes_background(ax1)
    
    # 保存
    output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'figures')
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        
    output_path = os.path.join(output_dir, 'sybil_long_range_defense.png')
    plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='white')
    print(f"Figure saved to: {output_path}")
    plt.close()

if __name__ == "__main__":
    try:
        plot_sybil_long_range_defense()
    except Exception as e:
        import traceback
        traceback.print_exc()
