import json
import os
import networkx as nx
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import colors

import data_process


def get_project_root():
    """
    获取项目根目录（往上查找直到找到 Cargo.toml）
    """
    current_dir = os.path.dirname(os.path.abspath(__file__))
    while current_dir != os.path.dirname(current_dir):  # 不是根目录
        if os.path.exists(os.path.join(current_dir, 'Cargo.toml')):
            return current_dir
        current_dir = os.path.dirname(current_dir)
    return os.path.dirname(os.path.abspath(__file__))  # 备选：返回当前目录


def print_graph(bc: data_process.Blockchain, json_file=None, output_path=None):
    """
    将graph.json文件转换为Matplotlib图表
    """
    
    # 如果未指定路径，则自动查找项目根目录
    if json_file is None:
        project_root = get_project_root()
        json_file = os.path.join(project_root, 'graph.json')
    
    if output_path is None:
        project_root = get_project_root()
        figures_dir = os.path.join(project_root, 'figures')
        os.makedirs(figures_dir, exist_ok=True)
        output_path = os.path.join(figures_dir, 'graph.png')

    with open(json_file, 'r') as file:
        data = json.load(file)
    # [ [   "17",  "9" ],[  "17",  "20" ]]
    G = nx.Graph()
    for edge in data:
        G.add_edge(edge[0], edge[1])
    print("number of nodes:", G.number_of_nodes())

    # 高级布局配置
    pos = nx.spring_layout(
        G,
        k=1,  # 节点间距系数（值越大间距越大）
        iterations=1200,  # 布局迭代次数
        seed=42,  # 随机种子保持可重复性
        # scale=2.0,  # 图像缩放系数
        # threshold=1e-4  # 更严格的收敛阈值
    )

    # 节点出块越多，节点越大
    node_sizes = [1000 * (1 + bc.get_miner_percentage(n) * 30) for n in G.nodes()]

    # 节点网络贡献越多，颜色越鲜艳
    node_colors = [bc.get_node_path_percentage(n) for n in G.nodes()]
    arr = np.array(node_colors)
    node_colors = np.log(arr)

    cmap = plt.cm.viridis  # 使用现代配色方案

    # 边样式配置
    edge_alpha = [0.3 + 0.7 * (np.random.rand()) for _ in G.edges()]  # 随机透明度增加层次感

    # 初始化画布
    plt.figure(figsize=(16, 12), dpi=300)  # 高分辨率大画布
    ax = plt.gca()

    # 绘制边（分批次绘制核心边和普通边）
    nx.draw_networkx_edges(
        G, pos, alpha=0.5, width=0.6, edge_color="#7F7F7F", ax=ax  # 基础透明度
    )

    norm = colors.Normalize(vmin=0.6, vmax=0.3)

    # 绘制节点
    nodes = nx.draw_networkx_nodes(
        G,
        pos,
        node_size=node_sizes,
        node_color=node_colors,
        cmap=cmap,
        edgecolors="#444444",  # 节点边框颜色
        linewidths=0.8,
        alpha=0.95,
    )

    # 标签策略
    # important_nodes = [n for n in G.nodes() if bc.get_node_path_percentage(n) > 0.01]
    # important_nodes = [n for n, d in G.degree() if d > 5]  # 只标记高度数节点
    labels = {n: str(n)[:5] for n in G.nodes()}
    nx.draw_networkx_labels(
        G,
        pos,
        labels=labels,
        font_size=8,
        font_family="sans-serif",
        font_color="#333333",
        alpha=0.9,
    )

    # 添加装饰元素
    cbar = plt.colorbar(nodes, label="Network Contribution Percentage", shrink=0.8)  # 颜色条说明
    # cbar.set_ticks([0, 25, 50, 75, 100])
    cbar.set_ticklabels([f"{bc.get_node_path_percentage(n) * 100:.2f}%" for n in G.nodes()])
    ax.set_title("Validation of Network Contribution Quantification", fontsize=24, pad=20)

    # 优化画布细节
    ax.margins(0.02)
    plt.axis("off")
    plt.tight_layout()

    # 保存输出
    plt.savefig(output_path, bbox_inches="tight", transparent=False)
    plt.close()


if __name__ == '__main__':
    bc = data_process.get_blockchain_from_json()
    # 示例使用
    print_graph(bc)
