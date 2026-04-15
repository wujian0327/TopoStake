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


fig, ax = plt.subplots(1, 1, figsize=(10.2, 3.8))
ax.set_xlim(-0.4, 11.0)
ax.set_ylim(-1.9, 2.4)
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
draw_text_tag(ax, 10.1, 0.72, r'$tx + R$', 0.82, 0.30, ec=navy)
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
label(ax, 9.3, 0.86, 'verify', fs=6.6, color=green, fw='bold', fst='italic')
label(ax, 5.35, -1.18, 'Chained-signature verifiable path', fs=10.2,
      color=green, fw='bold', fst='italic')

label(ax, 0.7, -0.72, 'tx originator', fs=8.5, color=blue_mid, fst='italic')
label(ax, 10.1, -0.72, 'block proposer', fs=8.5, color=navy, fst='italic')

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
figures_dir = os.path.join(project_root, 'figures')
os.makedirs(figures_dir, exist_ok=True)

plt.savefig(os.path.join(figures_dir, 'overview_step1.png'), dpi=600,
            bbox_inches='tight', facecolor='white', edgecolor='none')

print("Done!")
