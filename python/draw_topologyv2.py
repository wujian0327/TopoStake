import os

import matplotlib.lines as mlines
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
from matplotlib.image import imread
from matplotlib.image import BboxImage
from matplotlib.legend_handler import HandlerBase
from matplotlib.offsetbox import AnnotationBbox, OffsetImage
from matplotlib.transforms import Bbox, TransformedBbox
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

icon_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'icon')
icon_images = {
    'relay_reward': imread(os.path.join(icon_dir, 'gold.png')),
    'contribution_score': imread(os.path.join(icon_dir, 'fs.png')),
    'virtual_stake': imread(os.path.join(icon_dir, 'tp.png')),
}


class RelayRewardHandle:
    pass


class ContributionScoreHandle:
    pass


class VirtualStakeHandle:
    pass


def make_legend_image_artist(image, xdescent, ydescent, width, height, trans,
                             scale=1.45):
    icon_size = height * scale
    x0 = xdescent + (width - icon_size) / 2
    y0 = ydescent + (height - icon_size) / 2
    bbox = TransformedBbox(Bbox.from_bounds(x0, y0, icon_size, icon_size), trans)
    artist = BboxImage(bbox, interpolation='hanning')
    artist.set_data(image)
    return artist


def add_center_icon_row(fig, y=0.455, icon_size=0.043):
    """Add contribution branching to virtual stake and relay reward."""
    icon_positions = {
        'contribution_score': (0.450, y),
        'virtual_stake': (0.545, y + 0.025),
        'relay_reward': (0.545, y - 0.025),
    }

    arrows = [
        ((0.475, y + 0.004), (0.518, y + 0.023)),
        ((0.475, y - 0.004), (0.518, y - 0.023)),
    ]
    for start, end in arrows:
        arrow = mpatches.FancyArrowPatch(
            start,
            end,
            transform=fig.transFigure,
            arrowstyle='->',
            mutation_scale=12,
            linewidth=1.8,
            color='#111111',
            zorder=3,
        )
        fig.add_artist(arrow)

    for key, (x, icon_y) in icon_positions.items():
        icon_ax = fig.add_axes([
            x - icon_size / 2,
            icon_y - icon_size / 2,
            icon_size,
            icon_size,
        ])
        icon_ax.imshow(icon_images[key])
        icon_ax.axis('off')

    fig.text(
        0.498,
        y - 0.045,
        'contribution',
        ha='center',
        va='center',
        fontsize=7.5,
        color='#4A4A4A',
    )
    fig.text(
        0.498,
        y - 0.070,
        'stake + reward',
        ha='center',
        va='center',
        fontsize=7.5,
        color='#4A4A4A',
    )


class HandlerRelayReward(HandlerBase):
    def create_artists(self, legend, orig_handle, xdescent, ydescent, width, height,
                       fontsize, trans):
        return [make_legend_image_artist(
            icon_images['relay_reward'],
            xdescent,
            ydescent,
            width,
            height,
            trans,
            scale=1.85,
        )]


class HandlerContributionScore(HandlerBase):
    def create_artists(self, legend, orig_handle, xdescent, ydescent, width, height,
                       fontsize, trans):
        return [make_legend_image_artist(
            icon_images['contribution_score'],
            xdescent,
            ydescent,
            width,
            height,
            trans,
            scale=1.75,
        )]


class HandlerVirtualStake(HandlerBase):
    def create_artists(self, legend, orig_handle, xdescent, ydescent, width, height,
                       fontsize, trans):
        return [make_legend_image_artist(
            icon_images['virtual_stake'],
            xdescent,
            ydescent,
            width,
            height,
            trans,
            scale=1.85,
        )]


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


def draw_reward_stake_icons(ax, zoom=0.055):
    icon_groups = {
        5: {
            'reward': (0.55, 1.81),
            'plus': (0.75, 1.81),
            'stake': (0.95, 1.81),
        },
        9: {
            'reward': (1.08, -1.62),
            'plus': (1.28, -1.62),
            'stake': (1.48, -1.62),
        },
        13: {
            'reward': (-2.06, 0.36),
            'plus': (-1.86, 0.36),
            'stake': (-1.66, 0.36),
        },
    }

    for group in icon_groups.values():
        for key, image_key in [
            ('reward', 'relay_reward'),
            ('stake', 'virtual_stake'),
        ]:
            image = OffsetImage(icon_images[image_key], zoom=zoom)
            artist = AnnotationBbox(
                image,
                group[key],
                frameon=False,
                box_alignment=(0.5, 0.5),
                zorder=7,
            )
            ax.add_artist(artist)
        ax.text(
            *group['plus'],
            '+',
            ha='center',
            va='center',
            fontsize=8.5,
            fontweight='bold',
            color='#111111',
            zorder=8,
        )


def draw_contribution_icons(ax, zoom=0.052):
    contribution_icon_positions = [
        (-0.22, 1.18),
        (-1.20, -0.35),
        (0.26, -1.18),
    ]

    for xy in contribution_icon_positions:
        image = OffsetImage(icon_images['contribution_score'], zoom=zoom)
        artist = AnnotationBbox(
            image,
            xy,
            frameon=False,
            box_alignment=(0.5, 0.5),
            zorder=7,
        )
        ax.add_artist(artist)


def format_panel(ax):
    ax.set_xlim(-2.15, 2.15)
    ax.set_ylim(-2.15, 2.15)
    ax.set_aspect('equal')
    ax.axis('off')


def draw_summary_card(fig, x, y, width, height, title, bullets,
                      title_color, bullet_color, facecolor, edgecolor,
                      bullet_indent=0.075, text_indent=0.105):
    card = mpatches.FancyBboxPatch(
        (x, y),
        width,
        height,
        boxstyle='round,pad=0.006,rounding_size=0.008',
        transform=fig.transFigure,
        facecolor=facecolor,
        edgecolor=edgecolor,
        linewidth=0.85,
        alpha=0.98,
        zorder=2,
    )
    fig.add_artist(card)

    center_x = x + width / 2
    fig.text(
        center_x,
        y + height * 0.80,
        title,
        ha='center',
        va='center',
        fontsize=13.0,
        fontweight='bold',
        color=title_color,
        zorder=3,
    )

    bullet_x = x + width * bullet_indent
    text_x = x + width * text_indent
    first_y = y + height * 0.515
    line_gap = height * 0.210
    for idx, bullet in enumerate(bullets):
        item_y = first_y - idx * line_gap
        dot = mlines.Line2D(
            [bullet_x],
            [item_y],
            marker='o',
            markersize=3.8,
            linestyle='none',
            transform=fig.transFigure,
            markerfacecolor=bullet_color,
            markeredgecolor=bullet_color,
            markeredgewidth=0,
            zorder=3,
        )
        fig.add_artist(dot)
        fig.text(
            text_x,
            item_y,
            bullet,
            ha='left',
            va='center',
            fontsize=9.85,
            fontweight='normal',
            color='#222222',
            zorder=3,
        )


def build_lazy_edges():
    # Outer dashed ring plus sparse, local spokes into the core.
    weak_edges = []
    for i in range(n_low):
        if i not in {1, 3, 4, 7, 9, 10}:
            weak_edges.append((n_high + i, n_high + (i + 1) % n_low))

    nearest_core_links = {
        4: (0,),
        6: (1,),
        8: (3,),
        10: (3,),
        12: (2,),
        14: (0,),
    }
    for low, cores in nearest_core_links.items():
        weak_edges.extend((low, core) for core in cores)
    return weak_edges


def normalize_edges(edges):
    return [tuple(sorted(edge)) for edge in edges]


active_relay_nodes = [5, 9, 13]
active_extra_edges = normalize_edges([
    (5, 4),
    (5, 6),
    (5, 7),
    (5, 0),
    (5, 1),
    (5, 15),
    (9, 8),
    (9, 10),
    (9, 11),
    (9, 3),
    (9, 2),
    (9, 7),
    (13, 12),
    (13, 14),
    (13, 15),
    (13, 2),
    (13, 0),
    (13, 11),
])


fig, axes = plt.subplots(1, 2, figsize=(8.0, 5.0))
fig.subplots_adjust(left=0.035, right=0.965, top=0.86, bottom=0.245, wspace=0.08)

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

# ---------------------------------------------------------------------
# Right: Incentivized Propagation
# ---------------------------------------------------------------------
ax = axes[1]
pos_right = make_positions()
G_incentivized = nx.Graph()
G_incentivized.add_nodes_from(range(n_total))

incentivized_core_edges = core_edges()
incentivized_relay_edges = build_lazy_edges()
normalized_relay_edges = normalize_edges(incentivized_relay_edges)
active_edge_set = {
    edge
    for edge in normalized_relay_edges
    if edge[0] in active_relay_nodes or edge[1] in active_relay_nodes
}
active_edge_set.update(active_extra_edges)
active_relay_edges = sorted(active_edge_set)
inactive_relay_edges = [
    edge for edge in normalized_relay_edges
    if edge not in active_edge_set
]
G_incentivized.add_edges_from(
    incentivized_core_edges + inactive_relay_edges + active_relay_edges
)

nx.draw_networkx_edges(
    G_incentivized,
    pos_right,
    edgelist=inactive_relay_edges,
    edge_color=edge_weak,
    style=(0, (4, 3)),
    width=1.05,
    alpha=0.9,
    ax=ax,
)
nx.draw_networkx_edges(
    G_incentivized,
    pos_right,
    edgelist=active_relay_edges,
    edge_color=edge_incentivized,
    style='solid',
    width=1.25,
    alpha=0.95,
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
nx.draw_networkx_nodes(
    G_incentivized,
    pos_right,
    nodelist=active_relay_nodes,
    node_color='#DFF2D7',
    node_size=size_low,
    edgecolors=edge_incentivized,
    linewidths=1.25,
    ax=ax,
)
draw_reward_stake_icons(ax)
draw_contribution_icons(ax)
format_panel(ax)

draw_summary_card(
    fig,
    0.085,
    0.095,
    0.35,
    0.160,
    'Lazy Propagation',
    [
        'Free-rider equilibrium',
        'Topology rigidity & centralization',
    ],
    title_color='#9B2F26',
    bullet_color='#9B2F26',
    facecolor='#FFF8F7',
    edgecolor='#E7C9C6',
)
draw_summary_card(
    fig,
    0.565,
    0.095,
    0.385,
    0.160,
    'Incentivized Propagation',
    [
        'Reward active relays',
        'Better connected & more robust',
        'Less core domination & fairer participation',
    ],
    title_color='#3D7A35',
    bullet_color='#3D7A35',
    facecolor='#F8FCF4',
    edgecolor='#CFE2C7',
    bullet_indent=0.032,
    text_indent=0.062,
)

# ---------------------------------------------------------------------
# Central arrow and label
# ---------------------------------------------------------------------
arrow = mpatches.FancyArrowPatch(
    (0.455, 0.535),
    (0.545, 0.535),
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
# add_center_icon_row(fig)

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
        markersize=12,
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
        markersize=12,
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
    mlines.Line2D(
        [0],
        [0],
        marker='o',
        color='none',
        markerfacecolor='#DFF2D7',
        markeredgecolor=edge_incentivized,
        markeredgewidth=1.0,
        markersize=13,
        label='Active Relay',
    ),
    RelayRewardHandle(),
    ContributionScoreHandle(),
    VirtualStakeHandle(),
]
legend_labels = [
    'High-Stake',
    'Low-Stake',
    'Core Link',
    'Weak Link',
    'Incentivized Link',
    'Active Relay',
    'Relay Reward',
    'Contribution Score',
    'Virtual Stake',
]

fig.legend(
    handles=legend_elements,
    labels=legend_labels,
    loc='upper center',
    ncol=5,
    fontsize=9.5,
    frameon=True,
    fancybox=True,
    edgecolor='#888888',
    facecolor='white',
    framealpha=1.0,
    borderpad=0.55,
    columnspacing=1.35,
    handlelength=1.8,
    handletextpad=0.55,
    bbox_to_anchor=(0.5, 0.965),
    handler_map={
        RelayRewardHandle: HandlerRelayReward(),
        ContributionScoreHandle: HandlerContributionScore(),
        VirtualStakeHandle: HandlerVirtualStake(),
    },
)

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
figures_dir = os.path.join(project_root, 'figures')
os.makedirs(figures_dir, exist_ok=True)

plt.savefig(
    os.path.join(figures_dir, 'topology_comparison.png'),
    dpi=400,
    facecolor='white',
    edgecolor='none',
    bbox_inches='tight',
    pad_inches=0.1,
)
plt.savefig(
    os.path.join(figures_dir, 'topology_comparison.pdf'),
    dpi=400,
    facecolor='white',
    edgecolor='none',
    bbox_inches='tight',
    pad_inches=0.1,
)
print('Done!')
