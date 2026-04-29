import os

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch


plt.rcParams.update({
    'font.family': 'STIXGeneral',
    'mathtext.fontset': 'stix',
})

fig, ax = plt.subplots(1, 1, figsize=(10.51, 7.37))
ax.set_xlim(0.0, 9.95)
ax.set_ylim(1.24, 6.95)
ax.axis('off')

navy = '#0F2B63'
green = '#1E5E20'
orange = '#D85D12'
purple = '#3C167A'
gray = '#666666'
gray_fill = '#FAFAFA'
dark = '#1E1E1E'
blue_fill = '#F5F9FF'
orange_fill = '#FFF8EF'
green_fill = '#F6FFF4'
purple_fill = '#F7F0FF'
white = '#FFFFFF'


def rounded_box(x, y, w, h, edge, face=white, lw=1.5, ls='-', radius=0.035,
                zorder=2):
    box = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle=f'round,pad=0.02,rounding_size={radius}',
        facecolor=face,
        edgecolor=edge,
        linewidth=lw,
        linestyle=ls,
        zorder=zorder,
    )
    ax.add_patch(box)
    return box


font_scale = 0.78


def text(x, y, s, size=16, color=dark, weight='normal', style='normal',
         ha='center', va='center', zorder=5):
    ax.text(
        x,
        y,
        s,
        ha=ha,
        va=va,
        fontsize=size * font_scale,
        color=color,
        fontweight=weight,
        fontstyle=style,
        zorder=zorder,
    )


def cell(x, y, w, h, label, edge, face=white, size=15, color=dark, lw=1.35):
    rounded_box(x, y, w, h, edge=edge, face=face, lw=lw, radius=0.035, zorder=3)
    text(x + w / 2, y + h / 2, label, size=size + 2, color=color)


def arrow(start, end, color=dark, lw=1.8, ls='-', ms=17, rad=0.0, zorder=4):
    patch = FancyArrowPatch(
        start,
        end,
        arrowstyle='-|>',
        mutation_scale=ms,
        linewidth=lw,
        linestyle=ls,
        color=color,
        connectionstyle=f'arc3,rad={rad}',
        zorder=zorder,
    )
    ax.add_patch(patch)
    return patch


def open_arrow(start, end, color=dark, lw=1.4, ms=15, zorder=4):
    patch = FancyArrowPatch(
        start,
        end,
        arrowstyle='->',
        mutation_scale=ms,
        linewidth=lw,
        color=color,
        connectionstyle='arc3,rad=0',
        zorder=zorder,
    )
    ax.add_patch(patch)
    return patch


def dashed_arrow(start, end, color=navy, lw=1.4, ms=14, rad=0, zorder=4):
    patch = FancyArrowPatch(
        start,
        end,
        arrowstyle='->',
        mutation_scale=ms,
        linewidth=lw,
        linestyle=(0, (4, 3)),
        color=color,
        connectionstyle=f'arc3,rad={rad}',
        zorder=zorder,
    )
    ax.add_patch(patch)
    return patch


def dashed_line(start, end, color=navy, lw=1.3, zorder=4):
    ax.plot(
        [start[0], end[0]],
        [start[1], end[1]],
        color=color,
        linewidth=lw,
        linestyle=(0, (4, 3)),
        zorder=zorder,
    )


def dashed_curve_arrow(start, head_start, end, color=green, lw=1.7,
                       rad=-0.25, zorder=2):
    curve = FancyArrowPatch(
        start,
        head_start,
        arrowstyle='-',
        linewidth=lw,
        linestyle=(0, (2, 3)),
        color=color,
        connectionstyle=f'arc3,rad={rad}',
        zorder=zorder,
    )
    ax.add_patch(curve)
    head = FancyArrowPatch(
        head_start,
        end,
        arrowstyle='-|>',
        mutation_scale=18,
        linewidth=0,
        facecolor=color,
        edgecolor=color,
        connectionstyle='arc3,rad=0',
        zorder=zorder + 1,
    )
    ax.add_patch(head)
    return curve, head


def dots(x, y, color=dark, size=19):
    text(x, y, r'$\cdots$', size=size, color=color)


cell_w = 0.84
cell_h = 0.55

# Left: Standard PoS block.
rounded_box(0.22, 3.78, 4.0, 3.10, edge=gray, face=gray_fill, lw=1.5,
            ls=(0, (4, 4)), radius=0.10, zorder=1)
text(2.22, 6.55, 'Standard PoS Block', size=18, weight='bold')
text(2.22, 6.24, r'$\mathcal{B}=(\mathcal{H},\mathcal{T})$', size=17)

left_x = 0.86
h_y = 5.42
t_y = 4.58
text(0.48, h_y + cell_h / 2, r'$\mathcal{H}:$', size=18, color=gray)
cell(left_x, h_y, cell_w, cell_h, r'$h_{prev}$', gray, size=15)
cell(left_x + 0.98, h_y, cell_w, cell_h, r'$h_{block}$', gray, size=15)
dots(left_x + 2.05, h_y + cell_h / 2, color=gray)
cell(left_x + 2.33, h_y, cell_w, cell_h, 'proposer', gray, size=13)

text(0.48, t_y + cell_h / 2, r'$\mathcal{T}:$', size=18, color=gray)
cell(left_x, t_y, cell_w, cell_h, r'$tx_0$', gray, size=15)
cell(left_x + 0.98, t_y, cell_w, cell_h, r'$tx_1$', gray, size=15)
dots(left_x + 2.05, t_y + cell_h / 2, color=gray)
cell(left_x + 2.33, t_y, cell_w, cell_h, r'$tx_n$', gray, size=15)
text(2.20, 4.08, 'No propagation metadata', size=15, color=gray,
     style='italic')

# Middle transition.
text(4.54, 5.52, r'$\mathcal{P}$', size=17)
arrow((4.30, 5.34), (4.75, 5.34), color='black', lw=1.45, ms=18)

# Right: TopoStake block.
right_shift = -1.05
rounded_box(5.92 + right_shift, 3.74, 4.36, 3.16, edge=navy, face=white, lw=2.4,
            radius=0.10, zorder=1)
text(
    8.10 + right_shift,
    6.55,
    r'TopoStake Block $\mathcal{B}=(\mathcal{H},\mathcal{T},\mathcal{P})$',
    size=18,
    color=navy,
    weight='bold',
)

right_x = 6.62 + right_shift
right_gap = 0.98
last_x = 9.15 + right_shift
right_row_shift = 0.30
rh_y = h_y + right_row_shift
rt_y = t_y + right_row_shift
p_y = 3.80 + right_row_shift
text(6.24 + right_shift, rh_y + cell_h / 2, r'$\mathcal{H}:$', size=18, color=navy)
cell(right_x, rh_y, cell_w, cell_h, r'$h_{prev}$', navy, blue_fill, size=15)
cell(right_x + right_gap, rh_y, cell_w, cell_h, r'$h_{block}$', navy,
     blue_fill, size=15)
dots(right_x + 2.18, rh_y + cell_h / 2, color=navy)
cell(last_x, rh_y, 0.92, cell_h, 'proposer', navy, blue_fill, size=13)

text(6.24 + right_shift, rt_y + cell_h / 2, r'$\mathcal{T}:$', size=18, color=orange)
cell(right_x, rt_y, cell_w, cell_h, r'$tx_0$', orange, orange_fill,
     size=15)
cell(right_x + right_gap, rt_y, cell_w, cell_h, r'$tx_1$', orange,
     orange_fill, size=15)
dots(right_x + 2.18, rt_y + cell_h / 2, color=orange)
cell(last_x, rt_y, 0.92, cell_h, r'$tx_n$', orange, orange_fill, size=15)

text(6.24 + right_shift, p_y + cell_h / 2, r'$\mathcal{P}:$', size=18, color=green)
cell(right_x, p_y, cell_w, cell_h, r'$p_0$', green, green_fill, size=15)
cell(right_x + right_gap, p_y, cell_w, cell_h, r'$p_1$', green,
     green_fill, size=15)
dots(right_x + 2.18, p_y + cell_h / 2, color=green)
cell(last_x, p_y, 0.92, cell_h, r'$p_n$', green, green_fill, size=15)

for cx in [right_x + cell_w / 2, right_x + right_gap + cell_w / 2,
           last_x + 0.46]:
    ax.plot([cx, cx], [rt_y - 0.05, p_y + cell_h + 0.04],
            color=green, linewidth=1.8, linestyle=(0, (3, 3)), zorder=2)
# text(8.14, 3.55 + right_row_shift, r'$tx_k \leftrightarrow p_k$', size=17,
#      color=green)

# Bottom: path record detail.
bottom_shift = -0.75
bottom_y_shift = 0.25
bottom_x = 1.26 + bottom_shift
bottom_y = 1.03 + bottom_y_shift
bottom_w = 7.85
bottom_h = 1.82
rounded_box(bottom_x, bottom_y, bottom_w, bottom_h, edge=green,
            face=white, lw=2.1, radius=0.08, zorder=1)

dashed_curve_arrow(
    (right_x + 2.18, p_y + cell_h * 0.45-0.2),
    (6.5 + bottom_shift, bottom_y + bottom_h + 0.17),
    (6.4 + bottom_shift, bottom_y + bottom_h + 0.07),
)

text(2.98 + bottom_shift, 2.58 + bottom_y_shift, r'Path record for $tx_k$:', size=22, color=green,
     weight='bold')
text(
    4.3 + bottom_shift,
    2.58 + bottom_y_shift,
    r'$p_k=(\sigma_{agg}^{k},[v_0^k,v_1^k,\ldots,v_{m_k-1}^k])$',
    size=18,
    color=dark,
    ha='left',
)

detail_y = 1.72 + bottom_y_shift
detail_h = 0.56
cell(1.50 + bottom_shift, detail_y, 1.42, detail_h, r'$\sigma_{agg}^{k}$', purple,
     purple_fill, size=18, color=purple, lw=1.55)
text(2.20 + bottom_shift, 1.5 + bottom_y_shift, r'$O(1)$ constant-size', size=18, color=purple,
     style='italic')
text(2.20 + bottom_shift, 1.23 + bottom_y_shift, 'BLS proof', size=18, color=purple, style='italic')

ax.plot([3.26 + bottom_shift, 3.26 + bottom_shift], [1.15 + bottom_y_shift, 2.33 + bottom_y_shift],
        color=gray, linewidth=1.0, zorder=2)

v0_x = 3.58 + bottom_shift
v1_x = 5.02 + bottom_shift
vm_x = 7.55 + bottom_shift
cell(v0_x, detail_y, 0.95, detail_h, r'$v_0^k$', navy, blue_fill,
     size=18, color=navy, lw=1.55)
cell(v1_x, detail_y, 0.95, detail_h, r'$v_1^k$', navy, blue_fill,
     size=18, color=navy, lw=1.55)
dots(6.55 + bottom_shift, detail_y + detail_h / 2, color='black', size=21)
cell(vm_x, detail_y, 1.10, detail_h, r'$v_{m_k-1}^k$', navy, blue_fill,
     size=17, color=navy, lw=1.55)

open_arrow((v0_x + 0.98, detail_y + detail_h / 2),
           (v1_x - 0.05, detail_y + detail_h / 2))
open_arrow((v1_x + 0.98, detail_y + detail_h / 2),
           (6.30 + bottom_shift, detail_y + detail_h / 2))
open_arrow((6.82 + bottom_shift, detail_y + detail_h / 2),
           (vm_x - 0.06, detail_y + detail_h / 2))

br_y = 1.46 + bottom_y_shift
br_left = v0_x - 0.05
br_right = vm_x + 1.15
ax.plot([br_left, br_left, br_right, br_right],
        [br_y + 0.12, br_y, br_y, br_y + 0.12],
        color=navy, linewidth=1.6, zorder=3)
# text((br_left + br_right) / 2, 1.17, r'$O(m_k)$ signer IDs',
#      size=16, color=navy, style='italic')
text((br_left + br_right) / 2, 1.23 + bottom_y_shift, 'signer sequence', size=22,
     color=navy, style='italic')

outside_x = bottom_x + bottom_w + 0.30
rounded_box(outside_x, detail_y, 1.10, detail_h, edge=gray, face=white,
            lw=1.55, ls=(0, (4, 3)), radius=0.035, zorder=3)
text(outside_x + 0.55, detail_y + detail_h / 2, r'$v_{m_k}^k$',
     size=19, color=gray)
text(outside_x + 0.55, detail_y - 0.22, 'omitted', size=15, color=gray,
     style='italic')
dashed_arrow((vm_x + 1.14, detail_y + detail_h / 2),
             (outside_x - 0.06, detail_y + detail_h / 2), color=gray)
proposer_out = (last_x + 1, rh_y + cell_h / 2)
proposer_turn = (outside_x + 0.82, rh_y + cell_h / 2)
dashed_line(proposer_out, proposer_turn, color=gray, lw=1.3)
dashed_arrow(
    proposer_turn,
    (outside_x + 0.83, detail_y + detail_h + 0.02),
    color=gray,
    lw=1.3,
    ms=14,
)
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
figures_dir = os.path.join(project_root, 'figures')
os.makedirs(figures_dir, exist_ok=True)

plt.savefig(
    os.path.join(figures_dir, 'block_structure.png'),
    dpi=600,
    bbox_inches='tight',
    facecolor='white',
    edgecolor='none',
)
plt.savefig(
    os.path.join(figures_dir, 'block_structure.pdf'),
    bbox_inches='tight',
    facecolor='white',
    edgecolor='none',
)
print('Done!')
