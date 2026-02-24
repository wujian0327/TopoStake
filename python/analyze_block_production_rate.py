import os
import numpy as np
import matplotlib.pyplot as plt
import matplotlib as mpl

from plot_style import set_plot_style, get_colors_and_styles, format_axes, format_figure, format_axes_background

set_plot_style('paper')

def generate_block_production_data():
    """
    生成模拟的不同掉线概率下各共识算法的出块成功率数据
    掉线概率范围: 0% - 50%（每个节点在每个时刻有X%的概率掉线）
    """
    offline_rates = np.array([0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50])
    
    topostake_success_rates = np.array([1, 142/(1+142), 162/(2+162), 160/(3+160), 156/(6+156),154/(8+154), 150/(10+150), 140/(10+140), 141/(11+141),150/(14+150) , 144/(16+144)]) * 100
    
    pos_success_rates = np.array([1, 155/(2+155),155/(5+155), 156/(10+156), 148/(14+148), 147/(18+147),148/(24+148), 120/(27+128),102/(50+102), 91/(63+91), 70/(85+76)]) * 100
    
    minotaur_success_rates = np.array([1, 140/(2+140), 160/(3+160), 158/(4+158), 154/(7+154), 152/(9+152), 148/(11+148), 138/(11+138), 139/(12+139), 148/(15+148), 142/(17+142)]) * 100
    
    
    
    return offline_rates, topostake_success_rates, pos_success_rates, minotaur_success_rates

def create_block_production_rate_figure():
    """
    绘制不同掉线率下的出块成功率对比图
    """
    # 获取数据
    offline_rates, topostake_rates, pos_rates, minotaur_rates = generate_block_production_data()
    
    # 创建图表
    fig, ax = plt.subplots(figsize=(10, 8))
    colors, linestyles, markers = get_colors_and_styles()
    
    # 绘制三条曲线
    ax.plot(offline_rates, topostake_rates, 
            color=colors['topostake'],  linestyle=linestyles['topostake'], 
            marker=markers['topostake'],  label='topostake', zorder=3)
    
    ax.plot(offline_rates, pos_rates, 
            color=colors['pos'], linestyle=linestyles['pos'], 
            marker=markers['pos'],label='PoS', zorder=3)
    
    ax.plot(offline_rates, minotaur_rates, 
            color=colors['minotaur'], linestyle=linestyles['minotaur'], 
            marker=markers['minotaur'],label='Minotaur', zorder=3)
    # 应用标准格式化
    format_axes(ax, xlabel='Offline Probability(%)', 
                ylabel='Block Production ate(%)', grid=True)
    
    # 设置坐标轴范围
    ax.set_xlim(-2, 52)
    ax.set_ylim(30, 100)
    
    # 设置图例
    ax.legend(fontsize=26, loc='best', frameon=True, fancybox=False, edgecolor='black')
    
    # 应用图形背景格式
    format_figure(fig)
    format_axes_background(ax)
    
    plt.tight_layout()
    project_root = get_project_root()
    output_file = os.path.join(project_root, 'figures', 'block_production_rate.png')
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    plt.savefig(output_file, dpi=300, bbox_inches='tight', facecolor='white')
    print("[1/1] Block production rate figure generated successfully!")
    print(f"      Figure saved as: {output_file}")
    plt.close()

def get_project_root():
    """自动查找项目根目录，通过寻找 Cargo.toml 文件"""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    while current_dir != os.path.dirname(current_dir):
        if os.path.exists(os.path.join(current_dir, 'Cargo.toml')):
            return current_dir
        current_dir = os.path.dirname(current_dir)
    return current_dir

if __name__ == '__main__':
    print("\n========== Block Production Rate Analysis ==========\n")
    create_block_production_rate_figure()
    print("\n====================================================\n")
