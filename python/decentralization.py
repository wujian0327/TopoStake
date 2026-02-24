import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import os

from plot_style import set_plot_style, format_axes, format_figure, format_axes_background

# 设置标准风格（中等字体大小）
set_plot_style('paper')

def calculate_gini(values):
    """计算Gini系数"""
    sorted_values = np.sort(values)
    n = len(sorted_values)
    cumsum = np.cumsum(sorted_values)
    gini = (2 * np.sum(np.arange(1, n + 1) * sorted_values)) / (n * cumsum[-1]) - (n + 1) / n
    return gini

def generate_distribution_with_gini(n_agents=50, target_gini=0.6, seed=42):
    """
    生成具有目标Gini系数的分配
    使用二分查找调整Pareto分布的参数
    """
    np.random.seed(seed)
    
    # 二分查找找到合适的Pareto参数
    low, high = 0.5, 5.0
    pareto_param = None
    
    for _ in range(20):  # 迭代20次找到合适参数
        mid = (low + high) / 2
        values = np.random.pareto(mid, n_agents) + 1
        values = values / np.sum(values)
        gini = calculate_gini(values)
        
        if gini < target_gini:
            high = mid  # Gini太小，需要参数更小（更不均等）
        else:
            low = mid   # Gini太大，需要参数更大（更均等）
        
        pareto_param = mid
    
    # 用最终参数生成分配
    distribution = np.random.pareto(pareto_param, n_agents) + 1
    distribution = distribution / np.sum(distribution)
    return distribution

def simulate_pow_consensus(n_miners=50, n_slots=1000, target_gini=0.6):
    """
    模拟 PoW 共识：基于算力的概率出块
    - 模拟不同矿工拥有不同的算力
    - 算力分配服从目标Gini系数
    """
    # 生成具有目标Gini系数的算力分配
    powers = generate_distribution_with_gini(n_miners, target_gini=target_gini, seed=42)
    
    # 模拟出块
    miners = np.random.choice(range(n_miners), size=n_slots, p=powers)
    return pd.DataFrame({'miner': miners})

def simulate_pos_consensus(n_validators=50, n_slots=1000, target_gini=0.6):
    """
    模拟 PoS 共识：基于权益的概率出块
    - 权益分配服从目标Gini系数
    - 选择概率与权益成正比
    """
    # 生成具有目标Gini系数的权益分配
    stakes = generate_distribution_with_gini(n_validators, target_gini=target_gini, seed=42)
    
    # 模拟出块
    validators = np.random.choice(range(n_validators), size=n_slots, p=stakes)
    return pd.DataFrame({'miner': validators})

def simulate_minotaur_consensus(n_nodes=50, n_slots=1000, target_gini=0.6):
    """
    模拟 Minotaur 共识：混合PoW和PoS
    - 50%权重来自PoW算力分配
    - 50%权重来自PoS权益分配
    - 两者都服从目标Gini系数
    """
    np.random.seed(42)
    # 生成PoW算力分配
    pow_distribution = generate_distribution_with_gini(n_nodes, target_gini=target_gini, seed=42)
    # 生成PoS权益分配
    pos_distribution = generate_distribution_with_gini(n_nodes, target_gini=target_gini, seed=42)
    
    # 混合分配：50% PoW + 50% PoS
    combined_distribution = 0.5 * pow_distribution + 0.5 * pos_distribution
    combined_distribution = combined_distribution / np.sum(combined_distribution)  # 归一化
    
    # 模拟出块
    nodes = np.random.choice(range(n_nodes), size=n_slots, p=combined_distribution)
    return pd.DataFrame({'miner': nodes})

def simulate_topostake_consensus(n_nodes=50, n_slots=1000, n_transactions_per_slot=100):
    """
    模拟 topostake 共识：基于路径贡献的概率出块
    - 模拟交易流生成路径贡献分数
    - 计算虚拟权益并选择出块者
    """
    np.random.seed(42)
    # 生成网络拓扑 (简化：完全图)
    # 初始化贡献分数
    contributions = np.zeros(n_nodes)
    
    # 模拟交易和路径贡献
    for slot in range(n_slots):
        for _ in range(n_transactions_per_slot):
            # 随机选择交易源和目的地
            src = np.random.randint(0, n_nodes)
            dst = np.random.randint(0, n_nodes)
            
            if src == dst:
                continue
            
            # 简化路径模型：路径长度在1-4之间
            # 更长的路径可能涉及更多中间节点，贡献分数分散
            path_length = np.random.randint(1, 5)
            
            # 计算路径上每个节点的贡献 (alpha_k权重)
            # alpha_k = 2(L - k + 1) / (L(L+1))
            for k in range(1, path_length):
                alpha_k = 2.0 * (path_length - k + 1) / (path_length * (path_length + 1))
                node_idx = (src + k) % n_nodes  # 简化：线性路径
                contributions[node_idx] += alpha_k
    
    # 应用 NTD 惩罚和虚拟权益计算
    ntd = 6
    total_contrib = np.sum(contributions)
    if total_contrib > 0:
        c_normalized = contributions / total_contrib
    else:
        c_normalized = np.ones(n_nodes) / n_nodes
    
    # 假设真实权益服从Gini=0.6的分布
    s_real = generate_distribution_with_gini(n_nodes, target_gini=0.6, seed=42)
    
    # 虚拟权益: S_v = omega * C + (1-omega) * S
    omega = 0.8  # topostake配置参数
    s_virtual = omega * c_normalized + (1 - omega) * s_real
    s_virtual = s_virtual / np.sum(s_virtual)  # 归一化
    
    # 模拟出块
    proposers = np.random.choice(range(n_nodes), size=n_slots, p=s_virtual)
    return pd.DataFrame({'miner': proposers})

def get_project_root():
    """自动查找项目根目录，通过寻找 Cargo.toml 文件"""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    while current_dir != os.path.dirname(current_dir):
        if os.path.exists(os.path.join(current_dir, 'Cargo.toml')):
            return current_dir
        current_dir = os.path.dirname(current_dir)
    return current_dir

def read_metrics_csv(consensus_type):
    project_root = get_project_root()
    csv_file = os.path.join(project_root, f'metrics_slots_{consensus_type}.csv')
    if not os.path.exists(csv_file):
        # 如果没有真实文件，使用真实的共识算法模拟数据
        print(f"File {csv_file} not found, using {consensus_type.upper()} algorithm simulation...")
        if consensus_type == 'pow':
            return simulate_pow_consensus(n_miners=50, n_slots=1000)
        elif consensus_type == 'pos':
            return simulate_pos_consensus(n_validators=50, n_slots=1000)
        elif consensus_type == 'topostake':
            return simulate_topostake_consensus(n_nodes=50, n_slots=1000)
        elif consensus_type == 'minotaur':
            return simulate_minotaur_consensus(n_nodes=50, n_slots=1000)
        else:
            return generate_dummy_data(consensus_type)
    return pd.read_csv(csv_file)

def generate_dummy_data(consensus_type):
    # 生成模拟数据以防文件不存在
    n_slots = 1000
    n_nodes = 50
    # PoS: 幂律分布 (Rich get richer)
    if consensus_type == 'pos':
        weights = [1.0 / (i+1)**1.5 for i in range(n_nodes)]
    # topostake: 相对平滑 (Middle class rises)
    elif consensus_type == 'topostake':
        weights = [1.0 / (i+1)**0.8 for i in range(n_nodes)]
    # PoW: 高度中心化 (Mining pools)
    else:
        weights = [1.0 / (i+1)**2.0 for i in range(n_nodes)]
        
    weights = np.array(weights) / sum(weights)
    miners = np.random.choice(range(n_nodes), size=n_slots, p=weights)
    return pd.DataFrame({'miner': miners})

def calculate_lorenz_curve(df):
    # 统计每个矿工的出块数
    miner_counts = df['miner'].value_counts()
    # 补全没出块的节点 (假设总共50个节点)
    all_nodes_count = 50
    current_nodes = len(miner_counts)
    if current_nodes < all_nodes_count:
        zeros = pd.Series([0] * (all_nodes_count - current_nodes))
        miner_counts = pd.concat([miner_counts, zeros])
    
    # 排序
    sorted_counts = np.sort(miner_counts.values)
    
    # 计算累计比例
    cumsum = np.cumsum(sorted_counts)
    lorenz_y = np.insert(cumsum / cumsum[-1], 0, 0)
    lorenz_x = np.linspace(0, 1, len(lorenz_y))
    
    return lorenz_x, lorenz_y

def calculate_nakamoto_coefficient(df, threshold=0.51):
    miner_counts = df['miner'].value_counts(normalize=True)
    sorted_shares = np.sort(miner_counts.values)[::-1] # 降序
    cumsum = np.cumsum(sorted_shares)
    # 找到达到阈值的最小节点数
    nakamoto = np.searchsorted(cumsum, threshold) + 1
    return nakamoto

def plot_lorenz_comparison():
    df_topostake = read_metrics_csv('topostake')
    df_pos = read_metrics_csv('pos')
    df_pow = read_metrics_csv('pow')
    df_minotaur = read_metrics_csv('minotaur')
    
    x_topostake, y_topostake = calculate_lorenz_curve(df_topostake)
    x_pos, y_pos = calculate_lorenz_curve(df_pos)
    x_pow, y_pow = calculate_lorenz_curve(df_pow)
    x_minotaur, y_minotaur = calculate_lorenz_curve(df_minotaur)
    
    fig, ax = plt.subplots(figsize=(10, 8))
    
    # 绘制对角线 (Perfect Equality)
    ax.plot([0, 1], [0, 1], linestyle='--', color='gray', label='Perfect Equality', alpha=0.6)
    
    # 绘制 topostake、PoS、PoW 和 Minotaur
    ax.plot(x_topostake, y_topostake, label='topostake', color='#1f77b4', linewidth=3)
    ax.plot(x_pos, y_pos, label='PoS', color='#2ca02c', linewidth=3)
    ax.plot(x_pow, y_pow, label='PoW', color='#d62728', linewidth=3)
    ax.plot(x_minotaur, y_minotaur, label='Minotaur', color='#9467bd', linewidth=3)
    
    # 应用标准格式化
    format_axes(ax, xlabel='Cumulative Share of Nodes', 
                ylabel='Cumulative Share of Blocks', grid=True)
    
    ax.set_xlim([0, 1])
    ax.set_ylim([0, 1])
    ax.legend(loc='upper left', fontsize=22, frameon=True, fancybox=False, edgecolor='black', framealpha=0.95)
    
    # 应用图形背景格式
    format_figure(fig)
    format_axes_background(ax)

    output_file = os.path.join(get_project_root(), 'figures', 'lorenz_curve.png')
    plt.savefig(output_file, dpi=300, bbox_inches='tight', facecolor='white')
    print(f"Saved {output_file}")
    plt.close()

def plot_nakamoto_bar():
    df_topostake = read_metrics_csv('topostake')
    df_pos = read_metrics_csv('pos')
    df_pow = read_metrics_csv('pow')
    df_minotaur = read_metrics_csv('minotaur')
    
    nk_topostake = calculate_nakamoto_coefficient(df_topostake)
    nk_pos = calculate_nakamoto_coefficient(df_pos)
    nk_pow = calculate_nakamoto_coefficient(df_pow)
    nk_minotaur = calculate_nakamoto_coefficient(df_minotaur)
    
    fig, ax = plt.subplots(figsize=(10, 8))
    
    protocols = ['topostake', 'PoS', 'PoW', 'Minotaur']
    values = [nk_topostake, nk_pos, nk_pow, nk_minotaur]
    colors = ['#1f77b4', '#2ca02c', '#d62728', '#9467bd']
    
    bars = ax.bar(protocols, values, color=colors, alpha=0.8, width=0.6, edgecolor='black', linewidth=1.5)
    
    # 在柱子上标数值
    for bar in bars:
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2., height + 0.5,
                f'{int(height)}',
                ha='center', va='bottom', fontsize=22, fontweight='bold')
    
    # 应用标准格式化
    format_axes(ax, xlabel='Consensus Protocol', 
                ylabel='Min. Nodes to Control 51%', grid=True)
    
    ax.grid(axis='y', linestyle='--', alpha=0.5)
    ax.set_ylim(0, 20)  # 设置y轴最大值为35
    
    # 应用图形背景格式
    format_figure(fig)
    format_axes_background(ax)

    output_file = os.path.join(get_project_root(), 'figures', 'nakamoto_coefficient.png')
    plt.savefig(output_file, dpi=300, bbox_inches='tight', facecolor='white')
    print(f"Saved {output_file}")
    plt.close()

if __name__ == '__main__':
    plot_lorenz_comparison()
    plot_nakamoto_bar()
