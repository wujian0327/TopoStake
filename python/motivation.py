import os
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
import random

def draw_motivation_figure():
    # 设置随机种子以保证每次画出的图是一样的（为了布局稳定）
    random.seed(888)
    np.random.seed(888)

    # --- 1. 定义节点和位置 ---
    # 3个大节点 (Whales)，12个小节点 (Shrimps)
    whales = [0, 1, 2]
    shrimps = list(range(3, 15))
    all_nodes = whales + shrimps

    # 节点大小 (大节点显著大)
    node_sizes = [2000 if n in whales else 400 for n in all_nodes]
    
    # 节点颜色 (大节点深色，小节点浅色)
    node_colors = ['#1f77b4' if n in whales else '#aec7e8' for n in all_nodes]

    # --- 布局算法 ---
    # 手动微调位置：Whales在中心，Shrimps在周围一圈
    pos = {}
    # 中心三角形
    pos[0] = np.array([0.0, 0.2])
    pos[1] = np.array([-0.15, -0.1])
    pos[2] = np.array([0.15, -0.1])
    
    # 外围圆形
    radius = 0.5
    angle_step = 2 * np.pi / len(shrimps)
    for i, node in enumerate(shrimps):
        angle = i * angle_step
        pos[node] = np.array([radius * np.cos(angle), radius * np.sin(angle)])

    # --- 创建画布 ---
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    
    # ==========================================
    # 左图: Traditional PoS (Rational Inertia)
    # ==========================================
    ax1 = axes[0]
    G1 = nx.Graph()
    G1.add_nodes_from(all_nodes)
    
    # 连边逻辑：
    # 1. Whales 之间紧密连接 (Strong Clique)
    whale_edges = [(0, 1), (1, 2), (2, 0)]
    G1.add_edges_from(whale_edges)
    
    # 2. Whales 到 Shrimps：稀疏且微弱 (Lazy Propagation)
    # 只连一部分，且用虚线表示
    # lazy_edges = []
    # for w in whales:
    #     # 每个Whale只随机连5个Shrimp，表示不想多传
    #     targets = random.sample(shrimps, 5)
    #     for t in targets:
    #         lazy_edges.append((w, t))
    lazy_edges = []
    for s in shrimps:
        targets = random.sample(whales, 1)
        for t in targets:
            lazy_edges.append((t, s))
    # 相邻的shrimps，有30%的概率互连，表示偶尔传播
    for i in range(len(shrimps)):
        j = (i+1) % len(shrimps)
        if random.random() < 0.5:
            lazy_edges.append((shrimps[i], shrimps[j]))
    G1.add_edges_from(lazy_edges)

    # 绘图 - 节点
    nx.draw_networkx_nodes(G1, pos, ax=ax1, node_size=node_sizes, node_color=node_colors, edgecolors='black')
    
    # 绘图 - 连边 (Whale之间：实线)
    nx.draw_networkx_edges(G1, pos, ax=ax1, edgelist=whale_edges, width=3.0, edge_color='#555555')
    
    # 绘图 - 连边 (Lazy：虚线，红色，表示阻塞或惰性)
    nx.draw_networkx_edges(G1, pos, ax=ax1, edgelist=lazy_edges, width=1.5, edge_color='#d62728', style='dashed', alpha=0.6)

    # 标注文字
    ax1.set_title("(a) Traditional PoS: Lazy Propagation", fontsize=16, y=-0.01)
    # ax1.text(0, 0, "Rich Clique", fontsize=10, ha='center', va='center', color='white', fontweight='bold')
    # ax1.text(0, 0.6, "Lazy Propagation", fontsize=12, ha='center', color='#d62728', fontweight='bold')
    
    # 去除坐标轴
    ax1.axis('off')
    ax1.set_xlim(-0.7, 0.7)
    ax1.set_ylim(-0.7, 0.7)


    # ==========================================
    # 右图: Proof-of-Graph (Incentivized)
    # ==========================================
    # 右边的节点大小，中间的Whales更小一些，边上的Shrimps更大一些
    node_sizes = [1000 if n in whales else 600 for n in all_nodes]

    ax2 = axes[1]
    G2 = nx.Graph()
    G2.add_nodes_from(all_nodes)
    
    # 连边逻辑：全连接，活跃
    active_edges = []
    # Whales 之间
    active_edges.extend(whale_edges)
    # Whales 到 Shrimps (全连)
    for w in whales:
        # 找最近的几个连
        for s in shrimps:
            dist = np.linalg.norm(pos[w] - pos[s])
            if dist < 0.6: # 距离阈值
                active_edges.append((w, s))
    
    # Shrimps 之间 (互相传播)
    for i in range(len(shrimps)):
        s1 = shrimps[i]
        s2 = shrimps[(i+1) % len(shrimps)] # 连成环
        active_edges.append((s1, s2))

    G2.add_edges_from(active_edges)

    # 绘图 - 节点
    nx.draw_networkx_nodes(G2, pos, ax=ax2, node_size=node_sizes, node_color=node_colors, edgecolors='black')
    
    # 绘图 - 连边 (绿色，实线，箭头感)
    nx.draw_networkx_edges(G2, pos, ax=ax2, edgelist=active_edges, width=2.0, edge_color='#2ca02c', alpha=0.8)

    # 添加“$”符号表示激励
    for (u, v) in active_edges:
        # 只在部分边上加符号，避免太乱
        if random.random() > 0.6: 
            mid_point = (pos[u] + pos[v]) / 2
            ax2.text(mid_point[0], mid_point[1], "$", fontsize=16, color='green', fontweight='bold', ha='center', va='center')

    # 标注文字
    ax2.set_title("(b) PoG: Incentivized Propagation", fontsize=16, y=-0.01)
    ax2.text(0, 0, "Active Core", fontsize=10, ha='center', va='center', color='white', fontweight='bold')
    # ax2.text(0, 0.6, "Optimized Topology\n(Reward Driven)", fontsize=12, ha='center', color='#2ca02c', fontweight='bold')

    # 去除坐标轴
    ax2.axis('off')
    ax2.set_xlim(-0.7, 0.7)
    ax2.set_ylim(-0.7, 0.7)

    plt.tight_layout()
    # 保存图片
    # 两个图能更近一些
    plt.subplots_adjust(wspace=0.1)

    output_file = os.path.join(get_project_root(), 'figures', 'pog_motivation.png')
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    plt.show()

def get_project_root():
    """自动查找项目根目录，通过寻找 Cargo.toml 文件"""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    while current_dir != os.path.dirname(current_dir):
        if os.path.exists(os.path.join(current_dir, 'Cargo.toml')):
            return current_dir
        current_dir = os.path.dirname(current_dir)
    return current_dir

if __name__ == "__main__":
    draw_motivation_figure()