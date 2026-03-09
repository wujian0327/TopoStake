import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import networkx as nx
import numpy as np

np.random.seed(42)

fig, axes = plt.subplots(1, 2, figsize=(10, 4.8))
plt.subplots_adjust(wspace=-0.3, left=0.02, right=0.98, top=0.80, bottom=0.10)

# ── Node setup ──
n_high = 4
n_low  = 12
n_total = n_high + n_low

# Colors
color_high = '#1B4F72'   # dark navy blue
color_low  = '#A9CCE3'   # soft sky blue
edge_active   = '#2C3E50'
edge_weak     = '#B0B0B0'
edge_incentiv = '#1E8449'  # forest green

# Sizes
size_high = 550
size_low  = 200

node_sizes_list = [size_high]*n_high + [size_low]*n_low

# ── Layout ──
def make_positions(r_inner=0.75, r_outer=1.75):
    pos = {}
    # High-stake: inner ring, rotated for visual balance
    for i in range(n_high):
        angle = 2 * np.pi * i / n_high + np.pi/4
        pos[i] = (r_inner * np.cos(angle), r_inner * np.sin(angle))
    # Low-stake: outer ring with slight jitter
    rng = np.random.RandomState(123)
    for i in range(n_low):
        angle = 2 * np.pi * i / n_low + np.pi/6
        jx = rng.uniform(-0.12, 0.12)
        jy = rng.uniform(-0.12, 0.12)
        pos[n_high + i] = (r_outer * np.cos(angle) + jx,
                           r_outer * np.sin(angle) + jy)
    return pos

pos = make_positions()

# ====================================================================
# LEFT PANEL: Lazy Propagation
# ====================================================================
ax = axes[0]
ax.text(0, -2.8, 'Lazy Propagation', fontsize=18, fontweight='bold', ha='center', va='top')

G_lazy = nx.DiGraph()
G_lazy.add_nodes_from(range(n_total))

# High-stake clique (dense, solid)
edges_strong = []
for i in range(n_high):
    for j in range(n_high):
        if i != j:
            edges_strong.append((i, j))

# Sparse peripheral links (weak, dashed)
edges_weak = []
# Each low-stake connects to just 1 high-stake
for i in range(n_low):
    edges_weak.append((n_high + i, i % n_high))

# Very few peer-to-peer among low-stake
edges_weak += [(n_high+0, n_high+1), (n_high+4, n_high+5),
               (n_high+8, n_high+9), (n_high+6, n_high+7)]

G_lazy.add_edges_from(edges_strong + edges_weak)

# Draw weak edges first (behind)
nx.draw_networkx_edges(G_lazy, pos, edgelist=edges_weak,
                       style=(0, (4, 3)), edge_color=edge_weak,
                       arrows=True, arrowsize=7, width=0.8,
                       connectionstyle='arc3,rad=0.05',
                       alpha=0.55, ax=ax, node_size=node_sizes_list,
                       min_source_margin=8, min_target_margin=8)

# Draw strong edges
nx.draw_networkx_edges(G_lazy, pos, edgelist=edges_strong,
                       style='solid', edge_color=edge_active,
                       arrows=True, arrowsize=9, width=1.3,
                       connectionstyle='arc3,rad=0.1',
                       alpha=0.75, ax=ax, node_size=node_sizes_list,
                       min_source_margin=10, min_target_margin=10)

# Draw nodes
nx.draw_networkx_nodes(G_lazy, pos, nodelist=range(n_high),
                       node_color=color_high, node_size=size_high,
                       edgecolors='#0D2F4F', linewidths=1.5, ax=ax)
nx.draw_networkx_nodes(G_lazy, pos, nodelist=range(n_high, n_total),
                       node_color=color_low, node_size=size_low,
                       edgecolors='#5D6D7E', linewidths=0.8, ax=ax)

ax.set_xlim(-2.6, 2.6)
ax.set_ylim(-2.6, 2.6)
ax.set_aspect('equal')
ax.axis('off')

# ====================================================================
# RIGHT PANEL: Incentivized Propagation
# ====================================================================
ax = axes[1]
ax.text(0, -2.8, 'Incentivized Propagation', fontsize=18, fontweight='bold', ha='center', va='top')

G_inc = nx.DiGraph()
G_inc.add_nodes_from(range(n_total))

# Core links (high-stake still connected)
edges_core = []
for i in range(n_high):
    for j in range(n_high):
        if i != j:
            edges_core.append((i, j))

# Rich relay links (green, incentivized)
edges_relay = []
for i in range(n_low):
    # Each low-stake connects to 2 high-stake nodes
    t1 = i % n_high
    t2 = (i + 1) % n_high
    edges_relay.append((n_high + i, t1))
    edges_relay.append((t2, n_high + i))

    # Each low-stake connects to 2-3 neighboring low-stake
    for offset in [1, 3]:
        nb = n_high + (i + offset) % n_low
        edges_relay.append((n_high + i, nb))

# Cross-links for mesh-like appearance
extras = [(n_high+0, n_high+6), (n_high+2, n_high+8),
          (n_high+4, n_high+10), (n_high+5, n_high+11),
          (n_high+1, n_high+9), (n_high+7, n_high+3),
          (n_high+9, n_high+2), (n_high+11, n_high+5)]
edges_relay += extras

# High-stake outward to some low-stake
for i in range(n_high):
    for offset in [2, 5, 8]:
        target = n_high + (offset + i * 3) % n_low
        edges_relay.append((i, target))

G_inc.add_edges_from(edges_core + edges_relay)

# Draw incentivized relay edges
nx.draw_networkx_edges(G_inc, pos, edgelist=edges_relay,
                       style='solid', edge_color=edge_incentiv,
                       arrows=True, arrowsize=6, width=0.8,
                       connectionstyle='arc3,rad=0.06',
                       alpha=0.35, ax=ax, node_size=node_sizes_list,
                       min_source_margin=8, min_target_margin=8)

# Draw core edges
nx.draw_networkx_edges(G_inc, pos, edgelist=edges_core,
                       style='solid', edge_color=edge_active,
                       arrows=True, arrowsize=9, width=1.3,
                       connectionstyle='arc3,rad=0.1',
                       alpha=0.75, ax=ax, node_size=node_sizes_list,
                       min_source_margin=10, min_target_margin=10)

# Draw nodes
nx.draw_networkx_nodes(G_inc, pos, nodelist=range(n_high),
                       node_color=color_high, node_size=size_high,
                       edgecolors='#0D2F4F', linewidths=1.5, ax=ax)
nx.draw_networkx_nodes(G_inc, pos, nodelist=range(n_high, n_total),
                       node_color=color_low, node_size=size_low,
                       edgecolors='#5D6D7E', linewidths=0.8, ax=ax)

ax.set_xlim(-2.6, 2.6)
ax.set_ylim(-2.6, 2.6)
ax.set_aspect('equal')
ax.axis('off')

# ====================================================================
# Central arrow
# ====================================================================
fig.text(0.50, 0.51, '⟹', fontsize=32, ha='center', va='center',
         fontweight='bold', color='#2C3E50')
fig.text(0.50, 0.43, 'TopoStake', fontsize=12, ha='center', va='center',
         fontstyle='italic', color='#2C3E50', fontweight='bold')

# ====================================================================
# Legend
# ====================================================================
legend_elements = [
    mpatches.Patch(facecolor=color_high, edgecolor='#0D2F4F',
                   linewidth=1.0, label='High-Stake'),
    mpatches.Patch(facecolor=color_low, edgecolor='#5D6D7E',
                   linewidth=0.8, label='Low-Stake'),
    plt.Line2D([0], [0], color=edge_active, linewidth=1.4,
               linestyle='-', label='Core Link'),
    plt.Line2D([0], [0], color=edge_weak, linewidth=1.0,
               linestyle='--', label='Weak Link'),
    plt.Line2D([0], [0], color=edge_incentiv, linewidth=1.3,
               linestyle='-', label='Incentivized Link'),
]

fig.legend(handles=legend_elements, loc='upper center', ncol=3,
           fontsize=12, frameon=True, fancybox=False,
           edgecolor='#CCCCCC', borderpad=0.5,
           columnspacing=2.0, handlelength=1.6,
           bbox_to_anchor=(0.5, 0.90))

import os
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
figures_dir = os.path.join(project_root, 'figures')
os.makedirs(figures_dir, exist_ok=True)

plt.savefig(os.path.join(figures_dir, 'topology_comparison.png'), dpi=400, bbox_inches='tight',
            facecolor='white', edgecolor='none')
# plt.savefig(os.path.join(figures_dir, 'topology_comparison.pdf'), dpi=400, bbox_inches='tight',
            # facecolor='white', edgecolor='none')
print("Done!")
