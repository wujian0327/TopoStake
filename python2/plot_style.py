"""
公共的 Matplotlib 样式配置模块

提供标准化的图表样式设置，用于所有分析脚本的一致性呈现。
"""

import os

import matplotlib.pyplot as plt


def set_plot_style(style_name='paper'):
    """
    设置 Matplotlib 的全局样式配置。
    
    参数:
        style_name (str): 样式名称
            - 'paper': 论文风格（字体大：28pt，线宽粗）
            - 'standard': 标准风格（字体中等：10-22pt）
            - 'compact': 紧凑风格（字体小：9-12pt）
    """
    plt.style.use('seaborn-v0_8-whitegrid')
    plt.rcParams['font.sans-serif'] = ['SimHei', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False
    plt.rcParams['figure.dpi'] = 100
    plt.rcParams['savefig.dpi'] = 300
    
    if style_name == 'paper':
        # 论文风格：大号字体和线宽
        plt.rcParams['font.size'] = 28
        plt.rcParams['axes.labelsize'] = 28
        plt.rcParams['axes.titlesize'] = 28
        plt.rcParams['xtick.labelsize'] = 24
        plt.rcParams['ytick.labelsize'] = 24
        plt.rcParams['legend.fontsize'] = 28
        plt.rcParams['lines.linewidth'] = 4.0
        plt.rcParams['lines.markersize'] = 12.0
        plt.rcParams['patch.linewidth'] = 1.2
        
    elif style_name == 'standard':
        # 标准风格：中等字体
        plt.rcParams['font.size'] = 10
        plt.rcParams['axes.labelsize'] = 22
        plt.rcParams['axes.titlesize'] = 22
        plt.rcParams['xtick.labelsize'] = 18
        plt.rcParams['ytick.labelsize'] = 18
        plt.rcParams['legend.fontsize'] = 22
        plt.rcParams['lines.linewidth'] = 2.5
        plt.rcParams['patch.linewidth'] = 1.2
        
    elif style_name == 'compact':
        # 紧凑风格：小号字体
        plt.rcParams['font.size'] = 10
        plt.rcParams['axes.labelsize'] = 11
        plt.rcParams['axes.titlesize'] = 12
        plt.rcParams['xtick.labelsize'] = 9
        plt.rcParams['ytick.labelsize'] = 9
        plt.rcParams['legend.fontsize'] = 10
        plt.rcParams['lines.linewidth'] = 2.0
        plt.rcParams['patch.linewidth'] = 1.2
    
    # 通用网格配置（所有风格都相同）
    plt.rcParams['axes.grid'] = True
    plt.rcParams['grid.alpha'] = 0.4


def get_colors_and_styles():
    """
    返回标准的颜色和线条样式字典，用于一致的图表呈现。
    
    返回:
        tuple: (colors_dict, linestyles_dict, markers_dict)
            - colors_dict: 共识类型到颜色的映射
            - linestyles_dict: 共识类型到线条样式的映射
            - markers_dict: 共识类型到标记符号的映射
    """
    colors = {'topostake': '#1f77b4', 'pos': '#2ca02c', 'pow': '#d62728', 'minotaur': '#9467bd'}
    linestyles = {'topostake': '-', 'pos': '--', 'pow': '-.', 'minotaur': ':'}
    markers = {'topostake': 's', 'pos': 'o', 'pow': '^', 'minotaur': 'D'}
    
    return colors, linestyles, markers


def format_axes(ax, xlabel='', ylabel='', title='', grid=True):
    """
    对坐标轴应用标准格式化。
    
    参数:
        ax: Matplotlib 坐标轴对象
        xlabel (str): X 轴标签
        ylabel (str): Y 轴标签
        title (str): 图表标题
        grid (bool): 是否显示网格
    """
    if xlabel:
        ax.set_xlabel(xlabel, fontweight='bold')
    if ylabel:
        ax.set_ylabel(ylabel, fontweight='bold')
    if title:
        ax.set_title(title, fontsize=22, fontweight='bold')
    
    if grid:
        ax.grid(True, alpha=0.5, linestyle='--', linewidth=0.7, color='gray')
        ax.set_axisbelow(True)
    
    # 强化所有轴边框
    for spine in ax.spines.values():
        spine.set_linewidth(1.5)
        spine.set_color('black')


def format_figure(fig):
    """
    对图形应用标准格式化。
    
    参数:
        fig: Matplotlib 图形对象
    """
    fig.patch.set_facecolor('white')


def format_axes_background(ax):
    """
    设置坐标轴背景为白色。
    
    参数:
        ax: Matplotlib 坐标轴对象
    """
    ax.set_facecolor('white')


def get_project_root():
    """自动查找项目根目录，通过寻找 Cargo.toml 文件"""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    while current_dir != os.path.dirname(current_dir):
        if os.path.exists(os.path.join(current_dir, 'Cargo.toml')):
            return current_dir
        current_dir = os.path.dirname(current_dir)
    return current_dir