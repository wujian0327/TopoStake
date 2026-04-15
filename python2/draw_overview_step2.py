import os

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch


navy = '#1B4F72'
blue_mid = '#2874A6'
sky = '#A9CCE3'
green = '#1E8449'
green_lt = '#D5F5E3'
text_dark = '#1C2833'
white = '#FFFFFF'
gray_bdr = '#95A5A6'


def draw_arrow(ax, x1, y1, x2, y2, color=text_dark, lw=1.6,
               conn='arc3,rad=0', ls='-', zorder=2):
    arr = FancyArrowPatch((x1, y1), (x2, y2), arrowstyle='->', mutation_scale=14,
                          color=color, linewidth=lw, connectionstyle=conn,
                          linestyle=ls, zorder=zorder)
    ax.add_patch(arr)


def draw_node(ax, x, y, r, fc, ec, text, fs=11, lw=1.8, double=False):
    if double:
        outer = plt.Circle((x, y), r * 1.22, fc=white, ec=ec, lw=lw, zorder=3)
        ax.add_patch(outer)
    c = plt.Circle((x, y), r, fc=fc, ec=ec, lw=lw, zorder=4)
    ax.add_patch(c)
    ax.text(x, y, text, ha='center', va='center', fontsize=fs,
            fontfamily='serif', color=text_dark, fontstyle='italic', zorder=5)


def label(ax, x, y, text, fs=9, color=text_dark, fw='normal', fst='normal'):
    ax.text(x, y, text, ha='center', va='center', fontsize=fs,
            color=color, fontweight=fw, fontstyle=fst, fontfamily='serif', zorder=5)


def draw_route_entry(ax, x, y, w, h, title, body_text,
                     fc=white, ec=blue_mid, tc=text_dark):
    box = FancyBboxPatch((x - w / 2, y - h / 2), w, h,
                         boxstyle='round,pad=0.05',
                         facecolor=fc, edgecolor=ec, linewidth=1.3, zorder=4)
    ax.add_patch(box)
    ax.text(x, y, body_text, ha='center', va='center', fontsize=7.8,
            color=tc, fontfamily='serif', zorder=5)


def draw_payload(ax, x, y, w, h, text, fc=white, ec=blue_mid, tc=text_dark):
    box = FancyBboxPatch((x - w / 2, y - h / 2), w, h,
                         boxstyle='round,pad=0.06',
                         facecolor=fc, edgecolor=ec, linewidth=1.2, zorder=4)
    ax.add_patch(box)
    ax.text(x, y, text, ha='center', va='center', fontsize=7.6,
            color=tc, fontfamily='serif', zorder=5)


def draw_text_tag(ax, x, y, text, w, h, fc=white, ec=blue_mid, tc=text_dark):
    box = FancyBboxPatch((x - w / 2, y - h / 2), w, h,
                         boxstyle='round,pad=0.03',
                         facecolor=fc, edgecolor=ec, linewidth=1.0, zorder=4)
    ax.add_patch(box)
    ax.text(x, y, text, ha='center', va='center', fontsize=8.2,
            color=tc, fontfamily='serif', zorder=5)


def draw_vertical_tag(ax, x, y, text, w, h, fc=white, ec=blue_mid, tc=text_dark):
    box = FancyBboxPatch((x - w / 2, y - h / 2), w, h,
                         boxstyle='round,pad=0.03',
                         facecolor=fc, edgecolor=ec, linewidth=1.0, zorder=4)
    ax.add_patch(box)
    ax.text(x, y, text, ha='center', va='center', fontsize=7.0,
            color=tc, fontfamily='serif', zorder=5)


def draw_stacked_tags(ax, x, y, text, w, h, count=3, dx=-0.10, dy=0.08,
                      fc=white, ec=blue_mid, tc=text_dark):
    # Draw faint backing tags first to suggest multiple verified paths.
    for i in range(count - 1, 0, -1):
        box = FancyBboxPatch((x - w / 2 + dx * i, y - h / 2 + dy * i), w, h,
                             boxstyle='round,pad=0.03',
                             facecolor=fc, edgecolor=ec, linewidth=0.9,
                             alpha=0.45 + 0.12 * (count - i), zorder=3)
        ax.add_patch(box)
    draw_text_tag(ax, x, y, text, w, h, fc=fc, ec=ec, tc=tc)


def draw_box(ax, x, y, w, h, text, fc=white, ec=blue_mid, fs=8.8, lw=1.4):
    box = FancyBboxPatch((x - w / 2, y - h / 2), w, h,
                         boxstyle='round,pad=0.10',
                         facecolor=fc, edgecolor=ec, linewidth=lw, zorder=4)
    ax.add_patch(box)
    ax.text(x, y, text, ha='center', va='center', fontsize=fs,
            color=text_dark, fontweight='bold', fontfamily='serif', zorder=5)


def draw_block(ax, x, y, w, h, title='Block', fc=white, ec=navy):
    box = FancyBboxPatch((x - w / 2, y - h / 2), w, h,
                         boxstyle='round,pad=0.06',
                         facecolor=fc, edgecolor=ec, linewidth=1.2, zorder=4)
    ax.add_patch(box)
    ax.plot([x - w / 2 + 0.08, x + w / 2 - 0.08], [y + 0.10, y + 0.10],
            color=ec, linewidth=0.8, zorder=5)
    ax.plot([x - w / 2 + 0.08, x + w / 2 - 0.08], [y - 0.05, y - 0.05],
            color=ec, linewidth=0.8, zorder=5)
    ax.text(x, y + h / 2 + 0.10, title, ha='center', va='bottom', fontsize=8.0,
            color=ec, fontweight='bold', fontfamily='serif', zorder=5)
    ax.text(x, y - 0.24, r'$P$', ha='center', va='center', fontsize=8.6,
            color=text_dark, fontweight='bold', fontfamily='serif', zorder=5)


def draw_route_stack(ax, x, y, w, h, entries, title='R', fc=white, ec=navy):
    outer = FancyBboxPatch((x - w / 2, y - h / 2), w, h,
                           boxstyle='round,pad=0.05',
                           facecolor=fc, edgecolor=ec, linewidth=1.1, zorder=4)
    ax.add_patch(outer)
    ax.text(x, y + h / 2 + 0.10, title, ha='center', va='bottom', fontsize=8.2,
            color=ec, fontweight='bold', fontfamily='serif', zorder=5)
    slot_h = h / len(entries)
    for i, entry in enumerate(entries):
        cy = y + h / 2 - slot_h * (i + 0.5)
        inner = FancyBboxPatch((x - w / 2 + 0.06, cy - slot_h / 2 + 0.04),
                               w - 0.12, slot_h - 0.08,
                               boxstyle='round,pad=0.02',
                               facecolor=white, edgecolor=gray_bdr,
                               linewidth=0.7, zorder=5)
        ax.add_patch(inner)
        ax.text(x, cy, entry, ha='center', va='center', fontsize=6.8,
                color=text_dark, fontfamily='serif', zorder=6)


fig, ax = plt.subplots(1, 1, figsize=(10.2, 5.2))
ax.set_xlim(-0.4, 11.0)
ax.set_ylim(-1.9, 4.3)
ax.set_aspect('equal')
ax.axis('off')

ny = -0.1
nr = 0.42

draw_node(ax, 0.7, ny, nr, sky, blue_mid, '$v_0$')
draw_node(ax, 3.0, ny, nr, sky, blue_mid, '$v_1$')
draw_node(ax, 5.5, ny, nr, green_lt, green, '$v_i$', double=True)
draw_node(ax, 7.7, ny, nr, sky, blue_mid, '$v_{m-1}$', fs=10)
draw_node(ax, 10.1, ny, nr, '#EBF5FB', navy, '$v_m$')

draw_arrow(ax, 1.16, ny, 2.5, ny)
draw_arrow(ax, 3.46, ny, 5.0, ny)
draw_arrow(ax, 6.94, ny, 7.22, ny)
draw_arrow(ax, 8.18, ny, 9.6, ny)

for dx in [6.1, 6.35, 6.6]:
    ax.plot(dx, ny, 'o', color=gray_bdr, markersize=4.2, zorder=3)

draw_text_tag(ax, 1.75, -0.1, r'$r_0$', 0.46, 0.26)
draw_text_tag(ax, 4.08, -0.1, r'$r_1$', 0.46, 0.26)
draw_text_tag(ax, 8.90, -0.1, r'$r_{m-1}$', 0.66, 0.26)
label(ax, 1.75, -0.42, r'$\{v_1 \mid \sigma_0\}$', fs=7.6, color=blue_mid)
label(ax, 4.08, -0.42, r'$\{v_i \mid \sigma_1\}$', fs=7.6, color=blue_mid)
label(ax, 8.90, -0.42, r'$\{v_m \mid \sigma_{m-1}\}$', fs=7.6, color=blue_mid)
draw_text_tag(ax, 0.7, 0.72, r'$tx + \emptyset$', 1.05, 0.30, ec=blue_mid)
draw_stacked_tags(ax, 10.1, 0.72, r'$tx + [r_0,\ldots,r_{m-1}]$', 1.58, 0.30, count=3, ec=navy)
draw_stacked_tags(ax, 9.78, 1.78, r'$tx + \{\sigma_{\mathit{agg}} \mid v_0,\ldots,v_m\}$',
                  1.98, 0.30, count=3, ec=navy)
draw_arrow(ax, 9.95, 0.88, 9.80, 1.60, color=gray_bdr, lw=0.9, ls='--')
draw_arrow(ax, 1.25, 0.72, 9.55, 0.72, color=gray_bdr, lw=1.1, ls='--')
draw_arrow(ax, 1.75, 0.05, 1.75, 0.72, color=gray_bdr, lw=0.9, ls='--')
draw_arrow(ax, 4.08, 0.05, 4.08, 0.72, color=gray_bdr, lw=0.9, ls='--')
draw_arrow(ax, 8.90, 0.05, 8.90, 0.72, color=gray_bdr, lw=0.9, ls='--')
draw_arrow(ax, 3.0, 0.34, 3.0, 0.72, color=gray_bdr, lw=0.8, ls='--')
draw_arrow(ax, 5.5, 0.34, 5.5, 0.72, color=gray_bdr, lw=0.8, ls='--')
draw_arrow(ax, 7.7, 0.34, 7.7, 0.72, color=gray_bdr, lw=0.8, ls='--')
label(ax, 3.0, 0.86, 'verify', fs=6.6, color=green, fw='bold', fst='italic')
label(ax, 5.5, 0.86, 'verify', fs=6.6, color=green, fw='bold', fst='italic')
label(ax, 7.7, 0.86, 'verify', fs=6.6, color=green, fw='bold', fst='italic')
label(ax, 9.3, 0.44, 'verify', fs=6.6, color=green, fw='bold', fst='italic')
label(ax, 5.35, -1.00, '(Step 1)', fs=8.2, color=green, fw='bold')
label(ax, 5.35, -1.22, 'Chained-signature verifiable path', fs=10.2,
      color=green, fw='bold', fst='italic')

label(ax, 0.7, -0.72, 'tx originator', fs=8.5, color=blue_mid, fst='italic')
label(ax, 10.1, -0.72, 'block proposer', fs=8.5, color=navy, fst='italic')

# Step 2
label(ax, 7.25, 3.92, '(Step 2)', fs=8.2, color=text_dark, fw='bold')
label(ax, 7.25, 3.76, 'Contribution Quantification', fs=8.8, color=text_dark, fw='bold')
draw_text_tag(ax, 9.55, 3.42, r'Target Depth  $\mathcal{D}_e$', 2.15, 0.28,
              fc='#EBF5FB', ec=blue_mid)
draw_text_tag(ax, 9.55, 2.65, r'Atomic Contribution  $\gamma$', 2.15, 0.28,
              fc=green_lt, ec=green)
draw_vertical_tag(ax, 7.85, 2.65, 'Log\nSat', 0.34, 1.32,
                  fc='#FDEBD0', ec='#C67008')
draw_vertical_tag(ax, 7.25, 2.65, 'EMA', 0.34, 1.32,
                  fc='#FDEBD0', ec='#C67008')
draw_arrow(ax, 9.55, 3.24, 9.55, 2.83, color=blue_mid, lw=1.0)
draw_arrow(ax, 9.70, 1.96, 9.58, 2.47, color=gray_bdr, lw=0.9, ls='--')
draw_arrow(ax, 9.05, 2.65, 8.05, 2.65, color='#C67008', lw=1.0)
draw_arrow(ax, 7.65, 2.65, 7.42, 2.65, color='#C67008', lw=1.0)
draw_box(ax, 6.05, 2.65, 1.15, 1.05, '', fc=white, ec=green, lw=1.2)
label(ax, 6.05, 3.02, 'Contribution', fs=7.5, color=green, fw='bold')
label(ax, 6.05, 2.78, r'$Score(v_0)$', fs=7.1, color=text_dark)
label(ax, 6.05, 2.55, r'$Score(v_i)$', fs=7.1, color=text_dark)
label(ax, 6.05, 2.32, r'$Score(v_{m-1})$', fs=7.1, color=text_dark)
draw_arrow(ax, 7.08, 2.65, 6.68, 2.65, color='#C67008', lw=1.0)

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
figures_dir = os.path.join(project_root, 'figures')
os.makedirs(figures_dir, exist_ok=True)

plt.savefig(os.path.join(figures_dir, 'overview_step2.png'), dpi=600,
            bbox_inches='tight', facecolor='white', edgecolor='none')

print("Done!")
