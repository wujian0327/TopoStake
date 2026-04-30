import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Circle
import numpy as np

fig, ax = plt.subplots(1, 1, figsize=(3.5, 4.0))  # IEEE single-column
ax.set_xlim(-1.8, 5.8)
ax.set_ylim(-4.2, 3.0)
ax.set_aspect('equal')
ax.axis('off')

# ── Colors ──
navy      = '#1B4F72'
blue_mid  = '#2874A6'
sky       = '#A9CCE3'
sky_lt    = '#D6EAF8'
green     = '#1E8449'
green_lt  = '#D5F5E3'
green_bg  = '#F0FFF0'
orange    = '#C67008'
orange_lt = '#FAD7A0'
red_soft  = '#C0392B'
red_lt    = '#F5B7B1'
text_dark = '#1C2833'
gray      = '#95A5A6'
gray_lt   = '#D5D8DC'
white     = '#FFFFFF'

def draw_node(ax, x, y, r, fc, ec, text, fs=11, lw=1.8, tc=text_dark):
    c = plt.Circle((x, y), r, facecolor=fc, edgecolor=ec,
                   linewidth=lw, zorder=4)
    ax.add_patch(c)
    ax.text(x, y, text, ha='center', va='center', fontsize=fs,
            fontfamily='serif', color=tc, fontstyle='italic',
            fontweight='bold', zorder=5)

def draw_arrow(ax, x1, y1, x2, y2, color=text_dark, lw=1.5,
               ls='-', conn='arc3,rad=0', zorder=3, alpha=1.0):
    a = FancyArrowPatch((x1,y1), (x2,y2), arrowstyle='->', mutation_scale=14,
                         color=color, linewidth=lw, linestyle=ls,
                         connectionstyle=conn, zorder=zorder, alpha=alpha)
    ax.add_patch(a)

def lab(ax, x, y, text, fs=7, tc=text_dark, fw='normal', fst='normal',
        ha='center', va='center', rotation=0, bbox=None):
    ax.text(x, y, text, ha=ha, va=va, fontsize=fs, fontweight=fw,
            color=tc, fontfamily='serif', fontstyle=fst, rotation=rotation,
            zorder=6, bbox=bbox)

# ── Node positions ──
nr = 0.42  # node radius

# v0 - Tx Initiator (bottom-left)
v0 = (-1.0, -1.0)
# v1 - bottom-center
v1 = (1.8, -2.0)
# v2 - top-left
v2 = (0.8, 2.0)
# v3 - top-right
v3 = (3.5, 2.0)
# v4 - Proposer (right)
v4 = (4.5, -1.0)

# ====================================================================
# STEP 1: Draw discarded paths first (behind everything)
# ====================================================================

# v0 → v2 → v3: route [r0, r2] arrives at v3 (accepted - first arrival)
# But v2 → v1: Tx[r0, r2] discarded at v1 (v1 already has shorter)
# v3 → v4: Tx[r0, r2, r3] discarded (longer path)

# Discarded: v2 → v1 (Tx[r0, r2] - discarded because equal length, later arrival)
draw_arrow(ax, v2[0]-0.15, v2[1]-nr-0.05, v1[0]-0.25, v1[1]+nr+0.05,
           color=red_soft, lw=1.0, ls=(0,(4,3)), conn='arc3,rad=0.2',
           zorder=2, alpha=0.5)
lab(ax, 1.45, 0.0, '$Tx[r_0, r_2]$\n(Discarded)', fs=5.5, tc=red_soft, fst='italic')

# Discarded: v1 → v3 (Tx[r0, r1] - discarded because v3 already has it)
draw_arrow(ax, v1[0]+0.1, v1[1]+nr+0.05, v3[0]-0.2, v3[1]-nr-0.05,
           color=red_soft, lw=1.0, ls=(0,(4,3)), conn='arc3,rad=-0.15',
           zorder=2, alpha=0.5)
lab(ax, 3.1, 0.35, '$Tx[r_0, r_1]$\n(Discarded)', fs=5.5, tc=red_soft, fst='italic')

# Discarded: v3 → v4 (Tx[r0, r2, r3] - longer path, discarded)
draw_arrow(ax, v3[0]+0.2, v3[1]-nr-0.05, v4[0]+0.1, v4[1]+nr+0.05,
           color=red_soft, lw=1.0, ls=(0,(4,3)), conn='arc3,rad=-0.2',
           zorder=2, alpha=0.5)
lab(ax, 5.15, 0.85, '$Tx[r_0,r_2,r_3]$\n(Discarded)', fs=5.5, tc=red_soft, fst='italic')

# ====================================================================
# STEP 2: Draw accepted paths (solid, prominent)
# ====================================================================

# v0 → v2: Tx[r0] (accepted)
draw_arrow(ax, v0[0]+0.15, v0[1]+nr+0.05, v2[0]-0.25, v2[1]-nr-0.05,
           color=green, lw=1.8, conn='arc3,rad=0.05')
lab(ax, -0.55, 0.85, '$Tx[r_0]$', fs=7, tc=green, fw='bold')

# v0 → v1: Tx[r0] (accepted)
draw_arrow(ax, v0[0]+nr+0.05, v0[1]-0.15, v1[0]-nr-0.05, v1[1]+0.1,
           color=green, lw=1.8, conn='arc3,rad=0.05')
lab(ax, 0.65, -1.35, '$Tx[r_0]$', fs=7, tc=green, fw='bold')

# v2 → v3: Tx[r0, r2] (accepted - first to reach v3)
draw_arrow(ax, v2[0]+nr+0.05, v2[1]+0.05, v3[0]-nr-0.05, v3[1]+0.05,
           color=green, lw=1.8)
lab(ax, 2.15, 2.55, '$Tx[r_0, r_2]$', fs=7, tc=green, fw='bold')

# v1 → v4: Tx[r0, r1] (accepted - SHORTEST path to proposer)
draw_arrow(ax, v1[0]+nr+0.05, v1[1]-0.05, v4[0]-nr-0.05, v4[1]-0.15,
           color=green, lw=2.2)
lab(ax, 3.15, -1.05, '$Tx[r_0, r_1]$', fs=7.5, tc=green, fw='bold')

# ====================================================================
# STEP 3: Draw nodes (on top of arrows)
# ====================================================================

draw_node(ax, *v0, nr, sky_lt, blue_mid, '$v_0$')
draw_node(ax, *v1, nr, sky_lt, blue_mid, '$v_1$')
draw_node(ax, *v2, nr, sky_lt, blue_mid, '$v_2$')
draw_node(ax, *v3, nr, sky_lt, blue_mid, '$v_3$')
draw_node(ax, *v4, nr, green_lt, green, '$v_4$', lw=2.2)  # Proposer emphasized

# ====================================================================
# STEP 4: Role labels
# ====================================================================

lab(ax, v0[0], v0[1]-nr-0.4, 'Tx Initiator', fs=7, tc=blue_mid, fw='bold')

lab(ax, v4[0], v4[1]+nr-1, 'Proposer', fs=7, tc=green, fw='bold')

# ====================================================================
# STEP 5: Block result box (bottom-right)
# ====================================================================

bx, by, bw, bh = 2.2, -3.6, 3.3, 0.7

# Arrow from proposer down to block
draw_arrow(ax, v4[0], v4[1]-nr-0.45, v4[0]-0.8, by+bh+0.05,
           color=navy, lw=1.2, ls='--', conn='arc3,rad=-0.15')

box = FancyBboxPatch((bx, by), bw, bh, boxstyle='round,pad=0.1',
                      facecolor=green_bg, edgecolor=navy,
                      linewidth=1.3, zorder=3)
ax.add_patch(box)

lab(ax, bx+0.15, by+bh-0.15, 'Block', fs=6.5, tc=navy, fw='bold', ha='left')
lab(ax, bx+bw/2, by+0.2,
    '$\\{Tx,\\, \\sigma_{agg},\\, [v_0, v_1, v_4]\\}$',
    fs=7.5, tc=text_dark)

# ====================================================================
# STEP 6: Legend
# ====================================================================

# legend_elements = [
#     plt.Line2D([0], [0], color=green, linewidth=2.0, linestyle='-',
#                label='Accepted relay'),
#     plt.Line2D([0], [0], color=navy, linewidth=2.2, linestyle='-',
#                label='Selected shortest path'),
#     plt.Line2D([0], [0], color=red_soft, linewidth=1.2, linestyle='--',
#                alpha=0.6, label='Discarded (longer/duplicate)'),
# ]

# fig.legend(handles=legend_elements, loc='lower center', ncol=3,
#            fontsize=6.5, frameon=True, fancybox=False,
#            edgecolor='#CCCCCC', borderpad=0.4,
#            columnspacing=0.8, handlelength=1.8,
#            prop={'family': 'serif'}, bbox_to_anchor=(0.5, -0.01))

import os
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
figures_dir = os.path.join(project_root, 'figures')
os.makedirs(figures_dir, exist_ok=True)

plt.savefig(os.path.join(figures_dir, 'path_optimization.png'), dpi=600, bbox_inches='tight',
            facecolor='white', edgecolor='none')

print("Done!")
