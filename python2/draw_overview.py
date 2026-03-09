import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import numpy as np

fig, ax = plt.subplots(1, 1, figsize=(7.16, 4.2))
ax.set_xlim(-0.5, 10.8)
ax.set_ylim(-2.5, 3.8)
ax.set_aspect('equal')
ax.axis('off')

# ── Color palette ──
navy      = '#1B4F72'
blue_mid  = '#2874A6'
sky       = '#A9CCE3'
green     = '#1E8449'
green_lt  = '#D5F5E3'
orange    = '#C67008'
orange_lt = '#FAD7A0'
blue_bg   = '#EBF5FB'
text_dark = '#1C2833'
white     = '#FFFFFF'
gray_bdr  = '#95A5A6'

def draw_box(ax, x, y, w, h, fc, ec, text, fs=8.5, fw='bold', tc=text_dark, lw=1.5):
    box = FancyBboxPatch((x-w/2, y-h/2), w, h,
                          boxstyle='round,pad=0.15',
                          facecolor=fc, edgecolor=ec, linewidth=lw, zorder=3)
    ax.add_patch(box)
    ax.text(x, y, text, ha='center', va='center', fontsize=fs,
            fontweight=fw, color=tc, fontfamily='serif', zorder=4)

def draw_arrow(ax, x1, y1, x2, y2, color=text_dark, lw=1.4,
               conn='arc3,rad=0', ls='-', zorder=2):
    arr = FancyArrowPatch((x1,y1), (x2,y2), arrowstyle='->', mutation_scale=13,
                           color=color, linewidth=lw, connectionstyle=conn,
                           linestyle=ls, zorder=zorder)
    ax.add_patch(arr)

def draw_node(ax, x, y, r, fc, ec, text, fs=9.5, lw=1.6, double=False):
    if double:
        outer = plt.Circle((x,y), r*1.22, fc=white, ec=ec, lw=lw, zorder=3)
        ax.add_patch(outer)
    c = plt.Circle((x,y), r, fc=fc, ec=ec, lw=lw, zorder=4)
    ax.add_patch(c)
    ax.text(x, y, text, ha='center', va='center', fontsize=fs,
            fontfamily='serif', color=text_dark, fontstyle='italic', zorder=5)

def label(ax, x, y, text, fs=7.5, color=text_dark, fw='normal', fst='normal'):
    ax.text(x, y, text, ha='center', va='center', fontsize=fs,
            color=color, fontweight=fw, fontstyle=fst, fontfamily='serif', zorder=5)

# ====================================================================
# TOP: Steps 2 → 3 → 4
# ====================================================================

# Propagation Scores box
draw_box(ax, 1.5, 1.15, 2.1, 0.78, sky, blue_mid,
         'Propagation\nScores  $\\hat{C}$')

# Economic Stake box
draw_box(ax, 1.5, 2.8, 2.1, 0.78, orange_lt, orange,
         'Economic\nStake  $\\hat{S}_r$')

# (Step 2) label
label(ax, 0.7, 0.0, '(Step 2)', fs=8, color=blue_mid, fw='bold')

# Weight labels
label(ax, 3.55, 0.95, 'Weight $\\omega$', fs=8)
label(ax, 3.55, 3.0, 'Weight $1\\!-\\!\\omega$', fs=8)

# Arrows → Virtual Stake
draw_arrow(ax, 2.6, 1.4, 4.0, 1.85, color=blue_mid, lw=1.5)
draw_arrow(ax, 2.6, 2.55, 4.0, 2.15, color=orange, lw=1.5)

# (Step 3) label
label(ax, 5.2, 2.8, '(Step 3)', fs=8, color=green, fw='bold')

# Virtual Stake box (central emphasis)
draw_box(ax, 5.2, 2.0, 2.3, 0.9, green_lt, green,
         'Virtual Stake\n$S_v$', fs=9.5, lw=2.0)

# Arrow → Leader Election
draw_arrow(ax, 6.4, 2.0, 7.85, 2.0, color=green, lw=1.5)
# label(ax, 7.05, 2.45, 'Probability', fs=8)

# Leader Election & Reward box
draw_box(ax, 9.15, 2.0, 2.3, 0.9, blue_bg, navy,
         'Leader Election\n& Reward', fs=9)

# (Step 4) label
label(ax, 9.15, 2.8, '(Step 4)', fs=8, color=navy, fw='bold')

# ── Dashed feedback arrows ──
# Propagation fee (down-left from Leader Election area to path)
draw_arrow(ax, 7.95, 1.5, 5.5, -0.15, color=green, lw=1.2, ls='--',
           conn='arc3,rad=-0.12')
label(ax, 6.1, 0.55, 'Propagation\nfee', fs=7.5, color=green, fst='italic')

# Block Reward (down from Leader Election to vm)
draw_arrow(ax, 9.8, 1.5, 9.8, -0.15, color=navy, lw=1.2, ls='--')
label(ax, 10.5, 0.65, 'Block\nReward', fs=7.5, color=navy, fst='italic')

# Path Data (up from path to Step 2)
draw_arrow(ax, 1.5, -0.55, 1.5, 0.5, color=blue_mid, lw=1.2, ls='--')
label(ax, 1.9, 0.0, 'Path\nData', fs=7.5, color=blue_mid, fst='italic')

# ====================================================================
# BOTTOM: Validated Propagation Path (Step 1)
# ====================================================================

ny = -0.8   # node y
nr = 0.44   # node radius

# Nodes
draw_node(ax, 0.5,  ny, nr, sky,      blue_mid, '$v_0$')
draw_node(ax, 2.7,  ny, nr, sky,      blue_mid, '$v_1$')
draw_node(ax, 5.2,  ny, nr, green_lt, green,    '$v_i$', double=True)
draw_node(ax, 7.7,  ny, nr, sky,      blue_mid, '$v_{m-1}$', fs=8.5)
draw_node(ax, 9.7,  ny, nr, blue_bg,  navy,     '$v_m$')

# Arrows between nodes
draw_arrow(ax, 0.98, ny, 2.22, ny, lw=1.6)
draw_arrow(ax, 3.18, ny, 4.7,  ny, lw=1.6)
draw_arrow(ax, 6.65, ny, 7.22, ny, lw=1.6)
draw_arrow(ax, 8.18, ny, 9.22, ny, lw=1.6)

# Dots between vi and v_{m-1}
for dx in [5.85, 6.1, 6.35]:
    ax.plot(dx, ny, 'o', color=gray_bdr, markersize=4, zorder=3)

# (Step 1) label
label(ax, 3.95, -0.55, '(Step 1)', fs=8, color=green, fw='bold')

# Path title
label(ax, 5.1, -1.85, 'Validated Propagation Path  $p$', fs=10.5, fw='bold')

import os
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
figures_dir = os.path.join(project_root, 'figures')
os.makedirs(figures_dir, exist_ok=True)

plt.savefig(os.path.join(figures_dir, 'overview.png'), dpi=600, bbox_inches='tight',
            facecolor='white', edgecolor='none')

print("Done!")
