import networkx as nx
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
import os
import json

from plot_style import set_plot_style, format_axes, format_figure, format_axes_background

# 设置论文风格（大号字体）
set_plot_style('paper')


def generate_or_load_graph(node_num=100, m=2, seed=888, use_file=False):
    """
    尝试加载 graph.json，如果不存在则生成一个图。
    为了使散点图分布更均匀，这里默认生成一个度数分布均匀的随机图，而不是 BA 无标度网络。
    """
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    graph_path = os.path.join(root_dir, 'graph.json')
    
    if use_file and os.path.exists(graph_path):
        print(f"Loading existing graph from {graph_path}...")
        with open(graph_path, 'r') as f:
            edges = json.load(f)
        G = nx.Graph()
        for edge in edges:
            u, v = edge[0], edge[1]
            G.add_edge(u, v)
    else:
        print(f"Generating synthetic graph with uniform degree distribution (n={node_num})...")
        # 尝试生成连通的均匀度分布图
        # 度数范围从 1 到 10 (根据用户请求)
        current_seed = seed
        while True:
            degrees = np.linspace(1, 10, node_num, dtype=int)
            if sum(degrees) % 2 != 0:
                degrees[0] += 1
            
            # configuration_model 生成的是多重图
            G_multi = nx.configuration_model(degrees, seed=current_seed)
            G = nx.Graph(G_multi) # 转换为简单图（去重边）
            G.remove_edges_from(nx.selfloop_edges(G)) # 去自环
            
            if nx.is_connected(G):
                break
            current_seed += 1
            
        # 转换为字符串标签以匹配 Rust 行为
        G = nx.relabel_nodes(G, {i: str(i) for i in G.nodes()})
        
    return G

import random

def simulate_topostake_logic(G, omega=1, rounds=10):
    """
    模拟 topostake 共识逻辑计算出块概率
    通过模拟交易流来计算贡献度
    迭代模式：每一轮的 Miner 选择概率取决于当前的虚拟权益 (Feedback Loop)
    """
    print(f"Simulating transactions ({rounds} rounds/iterations)...")
    
    nodes = list(G.nodes())
    n = len(nodes)
    
    # 初始化贡献度分数 (累计)
    raw_scores = {node: 0.0 for node in nodes}
    
    # 初始 Miner 选择概率 (均匀分布)
    miner_probs = np.array([1.0/n] * n)
    
    # 模拟迭代
    for r in range(rounds):
        # 每一轮，每个节点发送一笔交易
        for src in nodes:
            # 基于当前 miner_probs 选择目标节点
            # np.random.choice 需要 1-D array
            dst = np.random.choice(nodes, p=miner_probs)
            
            # 简单的自环避免
            attempts = 0
            while dst == src and attempts < 10:
                dst = np.random.choice(nodes, p=miner_probs)
                attempts += 1
            
            if dst == src:
                continue
            
            try:
                # 假设交易走最短路径
                path = nx.shortest_path(G, source=src, target=dst)
                
                # topostake 逻辑
                path_nodes = path[:-1]
                path_length = len(path_nodes)
                
                if path_length == 0:
                    continue
                    
                for position, node in enumerate(path_nodes):
                    k = position + 1 
                    alpha_k = 2.0 * (path_length - k + 1) / (path_length * (path_length + 1))
                    s_hat = 1.0 / path_length
                    score = alpha_k * s_hat
                    raw_scores[node] += score
                    
            except nx.NetworkXNoPath:
                continue
        
        # 每一轮结束后，更新 miner_probs (即当前的 s_virtual)
        current_scores = np.array([raw_scores[node] for node in nodes])
        
        # 归一化贡献度
        total_score = np.sum(current_scores)
        if total_score > 0:
            c_norm = current_scores / total_score
        else:
            c_norm = np.array([1.0/n] * n)
            
        # 虚拟权益更新 (假设真实权益平等)
        s_real_norm = np.array([1.0/n] * n)
        s_virtual = omega * c_norm + (1 - omega) * s_real_norm
        
        # 更新概率
        miner_probs = s_virtual / np.sum(s_virtual)

    # 准备结果
    betweenness = nx.betweenness_centrality(G)
    degree = dict(G.degree())
    
    df = pd.DataFrame({
        'node': nodes,
        'betweenness': [betweenness[node] for node in nodes],
        'degree': [degree[node] for node in nodes],
        'raw_score': [raw_scores[node] for node in nodes],
        'prob': miner_probs
    })
    
    return df

def plot_simulation(df, omega):
    fig, ax = plt.subplots(figsize=(10, 7))
    
    # 计算相关系数 (Degree vs Prob)
    corr = df['degree'].corr(df['prob'])
    print(f"Correlation (Degree vs Prob): {corr:.4f}")
    
    # 绘图
    # 使用 degree 作为 x 轴
    sns.regplot(data=df, x='degree', y='prob', ax=ax,
                scatter_kws={'alpha': 0.6, 's': 80, 'marker': 'o'},
                line_kws={'color': 'red', 'label': f'Coefficient={corr:.2f}'},
                color='#2c3e50', x_jitter=0.2) # 添加一点 jitter 防止点重叠
    
    # ax.set_title(f'topostake Topology Bias', fontsize=22, fontweight='bold')
    format_axes(ax, xlabel='Node Degree', ylabel='Block Production Probability', grid=True)
    
    # 添加注释说明
    # ax.text(0.05, 0.95, 
    #         f'Simulation Settings:\n'
    #         f'• Random Transactions (Shortest Path)\n'
    #         f'• Equal Real Stake (Gini=0)\n'
    #         f'• $\omega$ = {omega}',
    #         transform=ax.transAxes,
    #         fontsize=12, verticalalignment='top',
    #         bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))
            
    ax.legend(loc='upper left', fontsize=22, frameon=True, fancybox=False, edgecolor='black', framealpha=0.95)
    ax.grid(True, alpha=0.5, linestyle='--', linewidth=0.7, color='gray')
    ax.set_axisbelow(True)

    # 应用图形背景格式
    format_figure(fig)
    format_axes_background(ax)

    # 保存
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    output_dir = os.path.join(root_dir, 'figures')
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        
    output_path = os.path.join(output_dir, 'topology_bias.png')
    plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='white')
    print(f"Simulation plot saved to: {output_path}")
    plt.close()

if __name__ == "__main__":
    try:
        # 1. 获取图 (use_file=False 强制生成均匀分布的图)
        # 用户请求: 20个节点
        G = generate_or_load_graph(node_num=20, use_file=False)
        
        # 2. 模拟计算 
        # rounds=50: 每个节点发50笔交易，总共约5000笔交易，样本足够大
        omega = 0.8
        df_result = simulate_topostake_logic(G, omega=omega, rounds=50)
        
        # 3. 绘图
        plot_simulation(df_result, omega)
    except Exception as e:
        import traceback
        traceback.print_exc()
