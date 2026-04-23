import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import numpy as np

fig, ax = plt.subplots(1, 1, figsize=(7.16, 3.6))
ax.set_xlim(-0.3, 11.2)
ax.set_ylim(-2.0, 5.0)
ax.set_aspect('equal')
ax.axis('off')

# ── Colors ──
navy      = '#1B4F72'
blue_mid  = '#2874A6'
sky_lt    = '#D6EAF8'
green     = '#1E8449'
green_lt  = '#D5F5E3'
green_bg  = '#F0FFF0'
orange    = '#C67008'
orange_lt = '#FAD7A0'
purple    = '#6C3483'
purple_lt = '#E8DAEF'
blue_bg   = '#EBF5FB'
text_dark = '#1C2833'
gray      = '#7F8C8D'
gray_lt   = '#E5E7E9'
white     = '#FFFFFF'

def cell(ax, x, y, w, h, fc, ec, text, fs=7, lw=1.0, tc=text_dark):
    box = FancyBboxPatch((x, y), w, h, boxstyle='round,pad=0.06',
                          facecolor=fc, edgecolor=ec, linewidth=lw, zorder=3)
    ax.add_patch(box)
    ax.text(x+w/2, y+h/2, text, ha='center', va='center', fontsize=fs,
            color=tc, fontfamily='serif', zorder=4)

def lab(ax, x, y, text, fs=8, tc=text_dark, fw='normal', fst='normal', ha='center'):
    ax.text(x, y, text, ha=ha, va='center', fontsize=fs,
            fontweight=fw, color=tc, fontfamily='serif', fontstyle=fst, zorder=5)

def arrow(ax, x1, y1, x2, y2, color=text_dark, lw=1.2, ls='-', conn='arc3,rad=0'):
    a = FancyArrowPatch((x1,y1), (x2,y2), arrowstyle='->', mutation_scale=10,
                         color=color, linewidth=lw, linestyle=ls,
                         connectionstyle=conn, zorder=2)
    ax.add_patch(a)

ch = 0.55   # cell height
gap = 0.08

# ====================================================================
# LEFT SIDE: Standard PoS Block
# ====================================================================
# Outer frame
left_frame = FancyBboxPatch((0.0, 1.0), 4.6, 3.8,
                             boxstyle='round,pad=0.12', facecolor=gray_lt,
                             edgecolor=gray, linewidth=1.3, zorder=0,
                             linestyle='--')
ax.add_patch(left_frame)

lab(ax, 2.3, 4.55, 'Standard PoS Block', fs=9, tc=gray, fw='bold')

# H row
r1y = 3.5
cw_l = 1.05
lx = 0.05
cx_l = 0.65

lab(ax, lx + 0.25, r1y + ch/2, '$\\mathcal{H}$:', fs=8, tc=gray)
cell(ax, cx_l,             r1y, cw_l, ch, white, gray, '$h_{prev}$',  fs=6.5, lw=0.8, tc=gray)
cell(ax, cx_l+cw_l+gap,   r1y, cw_l, ch, white, gray, '$h_{block}$', fs=6.5, lw=0.8, tc=gray)
lab(ax, cx_l+2*(cw_l+gap)+0.25, r1y+ch/2, '...', fs=7, tc=gray)
cell(ax, cx_l+2*(cw_l+gap)+0.5, r1y, cw_l, ch, white, gray, 'proposer', fs=6, lw=0.8, tc=gray)

# T row
r2y = 2.55
lab(ax, lx + 0.25, r2y + ch/2, '$\\mathcal{T}$:', fs=8, tc=gray)
cell(ax, cx_l,           r2y, cw_l, ch, white, gray, '$tx_0$', fs=6.5, lw=0.8, tc=gray)
cell(ax, cx_l+cw_l+gap,  r2y, cw_l, ch, white, gray, '$tx_1$', fs=6.5, lw=0.8, tc=gray)
lab(ax, cx_l+2*(cw_l+gap)+0.25, r2y+ch/2, '...', fs=7, tc=gray)
cell(ax, cx_l+2*(cw_l+gap)+0.5, r2y, cw_l, ch, white, gray, '$tx_n$', fs=6.5, lw=0.8, tc=gray)

# "No propagation data" note
lab(ax, 2.3, 1.6, 'No propagation\nmetadata', fs=7.5, tc=gray, fst='italic')

# ====================================================================
# CENTER: Arrow showing evolution
# ====================================================================
arrow(ax, 4.85, 3.0, 5.55, 3.0, color=green, lw=1.8)
# lab(ax, 5.2, 3.5, 'TopoStake', fs=8, tc=green, fw='bold', fst='italic')

# ====================================================================
# RIGHT SIDE: TopoStake Block
# ====================================================================
# Outer frame
right_frame = FancyBboxPatch((5.7, 1.0), 5.0, 3.8,
                              boxstyle='round,pad=0.12', facecolor=white,
                              edgecolor=navy, linewidth=1.8, zorder=0)
ax.add_patch(right_frame)

lab(ax, 8.2, 4.55, 'TopoStake Block  $\\mathcal{B}$', fs=9, tc=navy, fw='bold')

# H row
cx_r = 6.55
cw_r = 1.08

lab(ax, 6.05, r1y + ch/2, '$\\mathcal{H}$:', fs=8, tc=navy)
cell(ax, cx_r,             r1y, cw_r, ch, sky_lt, blue_mid, '$h_{prev}$',  fs=6.5)
cell(ax, cx_r+cw_r+gap,   r1y, cw_r, ch, sky_lt, blue_mid, '$h_{block}$', fs=6.5)
lab(ax, cx_r+2*(cw_r+gap)+0.25, r1y+ch/2, '...', fs=7, tc=gray)
cell(ax, cx_r+2*(cw_r+gap)+0.5, r1y, cw_r, ch, sky_lt, blue_mid, 'proposer', fs=6)

# T row
lab(ax, 6.05, r2y + ch/2, '$\\mathcal{T}$:', fs=8, tc=orange)
cell(ax, cx_r,           r2y, cw_r, ch, orange_lt, orange, '$tx_0$', fs=6.5)
cell(ax, cx_r+cw_r+gap,  r2y, cw_r, ch, orange_lt, orange, '$tx_1$', fs=6.5)
lab(ax, cx_r+2*(cw_r+gap)+0.25, r2y+ch/2, '...', fs=7, tc=gray)
cell(ax, cx_r+2*(cw_r+gap)+0.5, r2y, cw_r, ch, orange_lt, orange, '$tx_n$', fs=6.5)

# P row (NEW - emphasized)
r3y = 1.6

# Highlight background for P row
p_bg = FancyBboxPatch((5.85, r3y - 0.12), 4.7, ch + 0.24,
                       boxstyle='round,pad=0.08', facecolor=green_bg,
                       edgecolor=green, linewidth=1.0, zorder=1,
                       linestyle='-', alpha=0.5)
ax.add_patch(p_bg)

lab(ax, 6.05, r3y + ch/2, '$\\mathcal{P}$:', fs=8, tc=green, fw='bold')
cell(ax, cx_r,           r3y, cw_r, ch, green_lt, green, '$p_0$', fs=6.5, lw=1.2)
cell(ax, cx_r+cw_r+gap,  r3y, cw_r, ch, green_lt, green, '$p_1$', fs=6.5, lw=1.2)
lab(ax, cx_r+2*(cw_r+gap)+0.25, r3y+ch/2, '...', fs=7, tc=gray)
cell(ax, cx_r+2*(cw_r+gap)+0.5, r3y, cw_r, ch, green_lt, green, '$p_n$', fs=6.5, lw=1.2)

# "NEW" badge removed

# Correspondence arrows (tx_k ↔ p_k)
for i in range(3):
    if i < 2:
        cx = cx_r + i*(cw_r+gap) + cw_r/2
    else:
        cx = cx_r + 2*(cw_r+gap) + 0.5 + cw_r/2
    ax.annotate('', xy=(cx, r3y + ch + 0.02), xytext=(cx, r2y - 0.02),
                arrowprops=dict(arrowstyle='-', color=gray, lw=0.6,
                               linestyle='dotted'))

# Small "1:1" label between T and P
# lab(ax, 10.95, (r2y + r3y + ch) / 2 + 0.05, '1:1', fs=5.5, tc=gray, fst='italic')

# ====================================================================
# BOTTOM: Zoom-in on path structure
# ====================================================================

# Zoom arrow from p_0
zoom_start_x = cx_r + cw_r/2
zoom_start_y = r3y - 0.12

arrow(ax, zoom_start_x, zoom_start_y, 2.5, 0.3,
      color=green, lw=1.0, ls='--', conn='arc3,rad=0.25')

# Path detail container
det_y = -1.1
det_h = 0.75
det_cw = 1.35
det_gap = 0.07

# Zoom label
lab(ax, 1.0, 0.15, 'Path Record of $p_k$:', fs=7.5, tc=green, fw='bold', ha='left')

# Detail outer frame
det_frame = FancyBboxPatch((0.8, det_y - 0.12), 9.05, det_h + 0.24,
                            boxstyle='round,pad=0.1', facecolor=green_bg,
                            edgecolor=green, linewidth=1.3, zorder=1)
ax.add_patch(det_frame)

# Cells inside
det_x = 1.1
det_items = [
    ('$\\sigma_{agg}^k$',  purple_lt, purple,  '\nBLS Aggregate\nSignature'),
    ('$v_0$',              sky_lt,    blue_mid, None),
    ('$v_1$',              sky_lt,    blue_mid, None),
    (None,                 None,      None,     None),  # dots
    ('$v_{m-1}$',          sky_lt,    blue_mid, None),
]

v0_x = det_x + 1 * (det_cw + det_gap)
v1_x = det_x + 2 * (det_cw + det_gap) + 0.6
vm1_x = det_x + 7.1
dots_x = (v1_x + vm1_x) / 2

det_positions = [
    det_x,
    v0_x,
    v1_x,
    dots_x,
    vm1_x,
]

positions = []
for i, (txt, fc, ec, annot) in enumerate(det_items):
    x = det_positions[i]
    if fc is None:
        lab(ax, x + det_cw/2, det_y + det_h/2, '...', fs=9, tc=gray)
    else:
        cell(ax, x, det_y, det_cw, det_h, fc, ec, txt, fs=7.5, lw=1.2)
        if annot:
            lab(ax, x + det_cw/2, det_y - 0.40, annot, fs=7.5, tc=ec, fst='italic')
    positions.append(x)

# Small arrows between relay nodes (v0 → v1 → ... → v_{m-1})
arrow(ax, positions[1] + det_cw + 0.01, det_y + det_h/2,
      positions[2] + 0.01, det_y + det_h/2, color=gray, lw=0.8)
arrow(ax, positions[2] + det_cw + 0.01, det_y + det_h/2,
      positions[3] + det_cw/2 - 0.18, det_y + det_h/2, color=gray, lw=0.8)
arrow(ax, positions[3] + det_cw/2 + 0.16, det_y + det_h/2,
      positions[4] + 0.01, det_y + det_h/2, color=gray, lw=0.8)

# Brace under relay nodes
brace_y = det_y - 0.4
bx_left = positions[1] + det_cw/2
bx_right = positions[4] + det_cw/2
ax.plot([bx_left, bx_right], [brace_y, brace_y], color=green, lw=0.8)
ax.plot([bx_left, bx_left], [brace_y, brace_y+0.08], color=green, lw=0.8)
ax.plot([bx_right, bx_right], [brace_y, brace_y+0.08], color=green, lw=0.8)
bx_mid = (bx_left + bx_right) / 2
ax.plot([bx_mid, bx_mid], [brace_y, brace_y-0.08], color=green, lw=0.8)

lab(ax, bx_mid, brace_y - 0.3, 'Signing-node Sequence', fs=8, tc=text_dark, fst='italic')

# Separator line between σ and signing-node sequence
sep_x = positions[0] + det_cw + det_gap/2
ax.plot([sep_x, sep_x], [det_y + 0.05, det_y + det_h - 0.05],
        color=gray, lw=0.6, linestyle=':')

import os
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
figures_dir = os.path.join(project_root, 'figures')
os.makedirs(figures_dir, exist_ok=True)

plt.savefig(os.path.join(figures_dir, 'block_structure.png'), dpi=600, bbox_inches='tight',
            facecolor='white', edgecolor='none')
plt.savefig(os.path.join(figures_dir, 'block_structure.pdf'), bbox_inches='tight',
            facecolor='white', edgecolor='none')
print("Done!")
