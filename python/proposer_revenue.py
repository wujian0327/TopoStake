import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import os

from plot_style import set_plot_style, format_axes, format_figure, format_axes_background

# 设置论文风格（大号字体）
set_plot_style('paper')

def compute_penalty_factor(avg_path_length, d=10):
    """
    计算惩罚因子 P(B) (对应 src/consensus/topostake.rs 中的 distribute_rewards)
    P(B) = (d / L_avg)^2 if L_avg > d
    P(B) = 1.0 otherwise
    """
    if avg_path_length <= d:
        return 1.0
    else:
        return (d / avg_path_length) ** 2

def simulate_proposer_revenue():
    d = 6
    max_length = 30
    lengths = np.arange(1, max_length + 1)
    
    # 经济参数
    block_reward = 1.0  # 固定区块奖励
    base_fee_per_tx = 0.0005 # 单笔交易手续费 (增大以展示视觉效果)
    
    # 修改：使用交易个数定义容量
    block_tx_count = 2000 # 区块容量 (标准交易个数)
    # 意味着如果所有交易长度都为 d，则刚好能打包 block_tx_count 个交易
    block_capacity_hops = block_tx_count * d
    
    results = []
    
    for l in lengths:
        # 1. 计算区块内交易数量
        # 路径越长，交易越大，能打包的数量越少
        num_tx = block_tx_count
        
        # 2. 计算总手续费 (Total Fees)
        total_fees = num_tx * base_fee_per_tx
        
        # 3. 计算惩罚因子 P(B)
        penalty = compute_penalty_factor(l, d)
        
        # 4. 计算矿工收益 (Miner Share)
        # Miner Reward = Block Reward + 0.5 * Total Fees * Penalty
        miner_fee_income = 0.5 * total_fees * penalty
        miner_total_revenue = block_reward + miner_fee_income
        
        # 5. 计算网络池收益 (Network Pool)
        # Network Pool = Total Fees * (1 - 0.5 * Penalty)
        # 注意：如果 Penalty 很小，网络池分到的就多，但这部分不归矿工
        network_pool = total_fees * (1.0 - 0.5 * penalty)
        
        results.append({
            'Length': l,
            'Tx_Count': num_tx,
            'Total_Fees': total_fees,
            'Penalty_Factor': penalty,
            'Miner_Fee_Income': miner_fee_income,
            'Miner_Total_Revenue': miner_total_revenue,
            'Network_Pool': network_pool
        })
        
    return pd.DataFrame(results)

def plot_proposer_revenue():
    df = simulate_proposer_revenue()
    d = 6
    
    fig, ax = plt.subplots(figsize=(10, 7))
    
    # 颜色定义
    color_miner_base = '#ff7f0e'   # 橙色 (矿工基础奖励)
    color_miner_fee = '#d62728'    # 红色 (矿工手续费)
    color_pool = '#1f77b4'         # 蓝色 (网络池/其他节点)
    
    # 准备堆叠数据
    # 1. 矿工基础奖励 (Block Reward)
    miner_base = df['Miner_Total_Revenue'] - df['Miner_Fee_Income']
    # 2. 矿工手续费 (Miner Fee Income)
    miner_fee = df['Miner_Fee_Income']
    # 3. 网络池 (Network Pool)
    network_pool = df['Network_Pool']
    
    # 绘制堆叠图
    ax.stackplot(df['Length'], 
                 miner_base, 
                 miner_fee, 
                 network_pool,
                 labels=['Miner: Base Reward', 'Miner: Fee Share', 'Network Rewards'],
                 colors=[color_miner_base, color_miner_fee, color_pool],
                 alpha=0.85)

    # 添加边界线以增强视觉区分
    # 累积高度
    y1 = miner_base
    y2 = miner_base + miner_fee
    y3 = miner_base + miner_fee + network_pool
    
    # 绘制层级分隔线
    ax.plot(df['Length'], y1, color='black', linewidth=0.5, alpha=0.3)
    ax.plot(df['Length'], y2, color='black', linewidth=0.5, alpha=0.3)
    # 绘制总轮廓线
    # ax.plot(df['Length'], y3, color='black', linewidth=1.5)
    
    # 装饰
    format_axes(ax, xlabel='Average Block Transaction Path Length', 
                ylabel='Revenue Distribution', grid=True)
    
    ax.tick_params(axis='both')
    
    # 应用图形背景格式
    format_figure(fig)
    format_axes_background(ax)

    # d 线
    ax.axvline(x=d, color='black', linestyle='--', linewidth=2, alpha=0.5)
    
    # 标注 d 区域
    # 动态计算文本位置
    y_max = (miner_base + miner_fee + network_pool).max()
    ax.text(d + 0.5, y_max * 0.8, f'd Threshold\n(Path>{d})', 
             fontsize=16, color='black', fontweight='bold')

    # 图例
    ax.legend(fontsize=22, loc='upper right', frameon=True, fancybox=False, edgecolor='black', framealpha=0.95)
    
    ax.grid(True, alpha=0.4, linestyle='--', linewidth=0.7, color='gray')
    
    # 保存
    output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'figures')
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        
    output_path = os.path.join(output_dir, 'proposer_revenue.png')
    plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='white')
    print(f"Figure saved to: {output_path}")
    plt.close()

if __name__ == "__main__":
    try:
        plot_proposer_revenue()
    except Exception as e:
        import traceback
        traceback.print_exc()

