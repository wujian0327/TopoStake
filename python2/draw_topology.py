import os

import matplotlib.lines as mlines
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np


plt.rcParams.update({
    'font.family': 'DejaVu Sans',
    'font.size': 13,
    'axes.grid': False,
})

# ---------------------------------------------------------------------
# Visual constants
# ---------------------------------------------------------------------
n_high = 4
n_low = 12
n_total = n_high + n_low

color_high = '#203D68'
color_low = '#D8E8FA'
edge_core = '#0B1630'
edge_weak = '#7F7F7F'
edge_incentivized = '#3D8B34'

size_high = 760
size_low = 320


def make_positions(x_shift=0.0, r_outer=1.68):
    """Fixed layout: four validators in the core and twelve relays outside."""
    pos = {
        0: (-0.44 + x_shift, 0.44),
        1: (0.44 + x_shift, 0.44),
        2: (-0.44 + x_shift, -0.44),
        3: (0.44 + x_shift, -0.44),
    }

    # Start at the top and go clockwise to match the reference figure.
    for i in range(n_low):
        angle = np.pi / 2 - 2 * np.pi * i / n_low
        pos[n_high + i] = (
            x_shift + r_outer * np.cos(angle),
            r_outer * np.sin(angle),
        )
    return pos


def core_edges():
    return [(0, 1), (0, 2), (1, 3), (2, 3), (0, 3), (1, 2)]


def draw_nodes(ax, pos):
    nx.draw_networkx_nodes(
        nx.Graph(),
        pos,
        nodelist=range(n_high),
        node_color=color_high,
        node_size=size_high,
        edgecolors=edge_core,
        linewidths=1.25,
        ax=ax,
    )
    nx.draw_networkx_nodes(
        nx.Graph(),
        pos,
        nodelist=range(n_high, n_total),
        node_color=color_low,
        node_size=size_low,
        edgecolors=color_high,
        linewidths=1.1,
        ax=ax,
    )


def format_panel(ax):
    ax.set_xlim(-2.0, 2.0)
    ax.set_ylim(-2.0, 2.0)
    ax.set_aspect('equal')
    ax.axis('off')


def draw_panel_title(ax, title, subtitle):
    ax.text(
        0.5,
        -0.025,
        title,
        transform=ax.transAxes,
        ha='center',
        va='top',
        fontsize=18,
        fontweight='bold',
        color='black',
    )
    ax.text(
        0.5,
        -0.105,
        subtitle,
        transform=ax.transAxes,
        ha='center',
        va='top',
        fontsize=13,
        fontstyle='italic',
        color='#4A4A4A',
    )


def build_lazy_edges():
    # Outer dashed ring plus sparse, local spokes into the core.
    weak_edges = []
    for i in range(n_low):
        weak_edges.append((n_high + i, n_high + (i + 1) % n_low))

    nearest_core_links = {
        4: (0, 1),
        5: (1,),
        6: (1,),
        7: (1, 3),
        8: (3,),
        9: (3,),
        10: (2, 3),
        11: (2,),
        12: (2,),
        13: (0, 2),
        14: (0,),
        15: (0,),
    }
    for low, cores in nearest_core_links.items():
        weak_edges.extend((low, core) for core in cores)
    return weak_edges


def build_incentivized_edges():
    relay_edges = []

    # Keep the outer incentivized relay ring visible.
    for i in range(n_low):
        relay_edges.append((n_high + i, n_high + (i + 1) % n_low))
        relay_edges.append((n_high + i, n_high + (i + 3) % n_low))

    # Rewarded paths from low-stake/object nodes into nearby validators.
    # Apart from the outer ring and every-third relay chords, object nodes
    # do not connect directly to each other.
    for i in range(n_low):
        low = n_high + i
        if i in {10, 11, 0, 1, 2}:
            relay_edges.append((low, 0))
            relay_edges.append((low, 1))
        elif i in {4, 5, 6, 7, 8}:
            relay_edges.append((low, 2))
            relay_edges.append((low, 3))
        elif i in {3}:
            relay_edges.append((low, 1))
            relay_edges.append((low, 3))
        else:
            relay_edges.append((low, 0))
            relay_edges.append((low, 2))

    return list(dict.fromkeys(tuple(sorted(edge)) for edge in relay_edges))


fig, axes = plt.subplots(1, 2, figsize=(8.0, 5.0))
fig.subplots_adjust(left=0.035, right=0.965, top=0.86, bottom=0.19, wspace=0.08)

# ---------------------------------------------------------------------
# Left: Lazy Propagation
# ---------------------------------------------------------------------
ax = axes[0]
pos_left = make_positions()
G_lazy = nx.Graph()
G_lazy.add_nodes_from(range(n_total))

lazy_core_edges = core_edges()
lazy_weak_edges = build_lazy_edges()
G_lazy.add_edges_from(lazy_core_edges + lazy_weak_edges)

nx.draw_networkx_edges(
    G_lazy,
    pos_left,
    edgelist=lazy_weak_edges,
    edge_color=edge_weak,
    style=(0, (4, 3)),
    width=1.05,
    alpha=0.9,
    ax=ax,
)
nx.draw_networkx_edges(
    G_lazy,
    pos_left,
    edgelist=lazy_core_edges,
    edge_color=edge_core,
    width=1.85,
    alpha=1.0,
    ax=ax,
)
draw_nodes(ax, pos_left)
format_panel(ax)
draw_panel_title(ax, 'Lazy Propagation', 'core-dominated topology')

# ---------------------------------------------------------------------
# Right: Incentivized Propagation
# ---------------------------------------------------------------------
ax = axes[1]
pos_right = make_positions()
G_incentivized = nx.Graph()
G_incentivized.add_nodes_from(range(n_total))

incentivized_core_edges = core_edges()
incentivized_relay_edges = build_incentivized_edges()
G_incentivized.add_edges_from(incentivized_core_edges + incentivized_relay_edges)

nx.draw_networkx_edges(
    G_incentivized,
    pos_right,
    edgelist=incentivized_relay_edges,
    edge_color=edge_incentivized,
    width=0.95,
    alpha=0.9,
    ax=ax,
)
nx.draw_networkx_edges(
    G_incentivized,
    pos_right,
    edgelist=incentivized_core_edges,
    edge_color=edge_core,
    width=1.85,
    alpha=1.0,
    ax=ax,
)
draw_nodes(ax, pos_right)
format_panel(ax)
draw_panel_title(ax, 'Incentivized Propagation', 'relay-rewarded topology')

# ---------------------------------------------------------------------
# Central arrow and label
# ---------------------------------------------------------------------
arrow = mpatches.FancyArrowPatch(
    (0.465, 0.535),
    (0.535, 0.535),
    transform=fig.transFigure,
    arrowstyle='simple',
    mutation_scale=38,
    linewidth=0,
    facecolor='black',
    edgecolor='black',
)
fig.add_artist(arrow)
fig.text(
    0.50,
    0.455,
    'TopoStake',
    ha='center',
    va='center',
    fontsize=12,
    fontstyle='italic',
    fontweight='bold',
    color='#111111',
)

# ---------------------------------------------------------------------
# Legend
# ---------------------------------------------------------------------
legend_elements = [
    mlines.Line2D(
        [0],
        [0],
        marker='o',
        color='none',
        markerfacecolor=color_high,
        markeredgecolor=edge_core,
        markeredgewidth=1.1,
        markersize=15,
        label='High-Stake',
    ),
    mlines.Line2D(
        [0],
        [0],
        marker='o',
        color='none',
        markerfacecolor=color_low,
        markeredgecolor=color_high,
        markeredgewidth=1.0,
        markersize=13,
        label='Low-Stake',
    ),
    mlines.Line2D([0], [0], color=edge_core, linewidth=2.4, label='Core Link'),
    mlines.Line2D(
        [0],
        [0],
        color=edge_weak,
        linewidth=1.7,
        linestyle=(0, (4, 3)),
        label='Weak Link',
    ),
    mlines.Line2D(
        [0],
        [0],
        color=edge_incentivized,
        linewidth=2.0,
        label='Incentivized Link',
    ),
]

fig.legend(
    handles=legend_elements,
    loc='upper center',
    ncol=5,
    fontsize=11,
    frameon=True,
    fancybox=True,
    edgecolor='#888888',
    facecolor='white',
    framealpha=1.0,
    borderpad=0.55,
    columnspacing=1.45,
    handlelength=1.65,
    handletextpad=0.45,
    bbox_to_anchor=(0.5, 0.955),
)

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
figures_dir = os.path.join(project_root, 'figures')
os.makedirs(figures_dir, exist_ok=True)

plt.savefig(
    os.path.join(figures_dir, 'topology_comparison.png'),
    dpi=400,
    facecolor='white',
    edgecolor='none',
)
plt.savefig(
    os.path.join(figures_dir, 'topology_comparison.pdf'),
    dpi=400,
    facecolor='white',
    edgecolor='none',
)
print('Done!')
