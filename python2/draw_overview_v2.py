import os

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch


navy = '#1B4F72'
blue_mid = '#2874A6'
sky = '#A9CCE3'
green = '#1E8449'
green_lt = '#D5F5E3'
green_deep = '#145A32'
green_deep_lt = '#D4EFDF'
orange = '#C67008'
orange_lt = '#FDEBD0'
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


fig, ax = plt.subplots(1, 1, figsize=(10.2, 7.0))
ax.set_xlim(-0.4, 11.0)
ax.set_ylim(-1.35, 5.0)
ax.set_aspect('equal')
ax.axis('off')

ny = -0.1
nr = 0.42

draw_node(ax, 0.7, ny, nr, sky, blue_mid, '$v_0$')
draw_node(ax, 3.0, ny, nr, sky, blue_mid, '$v_1$')
draw_node(ax, 5.5, ny, nr, sky, blue_mid, '$v_2$')
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
label(ax, 4.08, -0.42, r'$\{v_2 \mid \sigma_1\}$', fs=7.6, color=blue_mid)
label(ax, 8.90, -0.42, r'$\{v_m \mid \sigma_{m-1}\}$', fs=7.6, color=blue_mid)
draw_text_tag(ax, 0.7, 0.72, r'$tx + \emptyset$', 1.05, 0.30, ec=blue_mid)
draw_stacked_tags(ax, 10.1, 0.72, r'$tx + [r_0,\ldots,r_{m-1}]$', 1.58, 0.30, count=3, ec=navy)
draw_stacked_tags(ax, 9.78, 1.78, r'$tx + \{\sigma_{\mathit{agg}} \mid v_0,\ldots,v_{m-1}\}$',
                  1.98, 0.30, count=3, ec=navy)
draw_arrow(ax, 9.95, 0.88, 9.80, 1.60, color=gray_bdr, lw=0.9, ls='--')
label(ax, 10.27, 1.32, 'bls\naggregate', fs=6.6, color=navy, fw='bold', fst='italic')
draw_arrow(ax, 1.25, 0.72, 9.55, 0.72, color=gray_bdr, lw=1.1, ls='--')
draw_arrow(ax, 1.75, 0.05, 1.75, 0.72, color=gray_bdr, lw=0.9, ls='--')
draw_arrow(ax, 4.08, 0.05, 4.08, 0.72, color=gray_bdr, lw=0.9, ls='--')
draw_arrow(ax, 8.90, 0.05, 8.90, 0.72, color=gray_bdr, lw=0.9, ls='--')
label(ax, 1.95, 0.56, 'add', fs=6.6, color=blue_mid, fst='italic')
label(ax, 4.28, 0.56, 'add', fs=6.6, color=blue_mid, fst='italic')
label(ax, 8.70, 0.56, 'add', fs=6.6, color=blue_mid, fst='italic')
label(ax, 2.25, 0.05, 'verify', fs=6.6, color=navy, fw='bold', fst='italic')
label(ax, 4.68, 0.05, 'verify', fs=6.6, color=navy, fw='bold', fst='italic')
label(ax, 7.05, 0.05, 'verify', fs=6.6, color=navy, fw='bold', fst='italic')
label(ax, 9.48, 0.05, 'verify', fs=6.6, color=navy, fw='bold', fst='italic')
label(ax, 5.35, -0.82, '(Step 1)', fs=8.2, color=navy, fw='bold')
label(ax, 5.35, -1.04, 'Verifiable Path Tracing', fs=10.2,
      color=navy, fw='bold', fst='italic')

label(ax, 0.7, -0.72, 'tx originator', fs=8.5, color=blue_mid, fst='italic')
label(ax, 10.1, -0.72, 'block proposer', fs=8.5, color=navy, fst='italic')

# Step 2
label(ax, 7.25, 4.24, '(Step 2)', fs=8.2, color=green, fw='bold')
label(ax, 7.25, 4.02, 'Contribution Quantification', fs=8.8, color=green, fw='bold')
draw_text_tag(ax, 9.55, 3.68, r'Target Depth  $\mathcal{D}_e$', 2.15, 0.28,
              fc=green_lt, ec=green)
draw_text_tag(ax, 9.55, 2.91, r'Atomic Contribution  $\gamma$', 2.15, 0.28,
              fc=green_lt, ec=green)
draw_vertical_tag(ax, 7.85, 2.91, 'Log\nSat', 0.34, 1.32,
                  fc=green_lt, ec=green)
draw_vertical_tag(ax, 7.25, 2.91, 'EMA', 0.34, 1.32,
                  fc=green_lt, ec=green)
draw_arrow(ax, 9.55, 3.50, 9.55, 3.09, color=green, lw=1.0)
draw_arrow(ax, 9.70, 2.22, 9.58, 2.73, color=gray_bdr, lw=0.9, ls='--')
label(ax, 9.20, 2.48, 'position', fs=6.6, color=navy, fw='bold', fst='italic')
label(ax, 9.94, 2.48, 'stake', fs=6.6, color=navy, fw='bold', fst='italic')
draw_arrow(ax, 9.05, 2.91, 8.05, 2.91, color=green, lw=1.0)
draw_arrow(ax, 7.65, 2.91, 7.42, 2.91, color=green, lw=1.0)
draw_box(ax, 6.05, 2.91, 1.15, 1.05, '', fc=white, ec=green, lw=1.2)
label(ax, 6.05, 3.28, 'Contribution', fs=7.5, color=green, fw='bold')
label(ax, 6.05, 3.04, r'$Score(v_1)$', fs=7.1, color=text_dark)
label(ax, 6.05, 2.81, r'$Score(v_2)$', fs=7.1, color=text_dark)
label(ax, 6.05, 2.65, r'$\cdots$', fs=8.0, color=gray_bdr)
label(ax, 6.05, 2.46, r'$Score(v_{m-1})$', fs=7.1, color=text_dark)
draw_arrow(ax, 7.08, 2.91, 6.68, 2.91, color=green, lw=1.0)

# Step 3: Virtual Stake and Leader Election
label(ax, 1.15, 4.02, '(Step 3)', fs=8.2, color=green_deep, fw='bold')
label(ax, 1.15, 3.82, 'Virtual Stake And Election', fs=8.4, color=green_deep, fw='bold')
draw_box(ax, 3.55, 4.30, 1.55, 0.46, 'Economic Stake', fc=green_deep_lt, ec=green_deep, fs=8.1)
draw_box(ax, 3.55, 3.05, 1.80, 0.72, 'Virtual Stake\n$S^{\\mathrm{virt}}$', fc=green_deep_lt, ec=green_deep, fs=8.8, lw=1.6)
draw_box(ax, 1.15, 3.05, 1.70, 0.68, '', fc=white, ec=green_deep, fs=8.8)
label(ax, 1.15, 3.19, 'Leader Election', fs=8.8, color=green_deep, fw='bold')
draw_text_tag(ax, 1.15, 2.87, 'RANDAO', 0.92, 0.22, fc=white, ec=green_deep)

draw_arrow(ax, 3.55, 3.98, 3.55, 3.52, color=green_deep, lw=1.2)
draw_arrow(ax, 5.48, 3.05, 4.62, 3.05, color=green, lw=1.2)
draw_arrow(ax, 2.58, 3.05, 2.00, 3.05, color=green_deep, lw=1.2)

label(ax, 4.10, 3.78, r'$1-\omega$', fs=7.2, color=green_deep)
label(ax, 5.00, 3.28, r'$\omega$', fs=7.2, color=green_deep)

draw_box(ax, 1.15, 1.85, 1.62, 0.62, '', fc=orange_lt, ec=orange, fs=8.2)
label(ax, 1.15, 1.96, 'Proposer Reward', fs=8.2, color=text_dark, fw='bold')
draw_text_tag(ax, 1.15, 1.71, r'$R_{base} + \frac{1}{2}\eta \cdot fee$', 1.34, 0.20, fc=white, ec=orange)

draw_box(ax, 3.55, 1.85, 1.62, 0.62, '', fc=orange_lt, ec=orange, fs=8.1)
label(ax, 3.55, 1.97, 'Redistribution', fs=8.1, color=text_dark, fw='bold')
draw_text_tag(ax, 3.55, 1.69, r'$(1-\frac{1}{2}\eta)\, fee$', 1.12, 0.20, fc=white, ec=orange)
draw_arrow(ax, 1.98, 1.85, 2.74, 1.85, color=orange, lw=1.0)
draw_arrow(ax, 5.68, 2.38, 4.42, 2.22, color=green, lw=1.0, conn='arc3,rad=0.16')
label(ax, 5.65, 1.28, '(Step 4)', fs=8.0, color=orange, fw='bold')
label(ax, 5.65, 1.08, 'Incentive and Reward', fs=8.2, color=orange, fw='bold')

draw_arrow(ax, 1.15, 2.71, 1.15, 2.23, color=green_deep, lw=1.1)
draw_arrow(ax, 3.10, 1.56, 3.00, 0.35, color=orange, lw=0.8, ls='--', conn='arc3,rad=0.18')
draw_arrow(ax, 3.55, 1.56, 5.50, 0.35, color=orange, lw=0.8, ls='--', conn='arc3,rad=-0.12')
draw_arrow(ax, 4.00, 1.56, 7.70, 0.35, color=orange, lw=0.8, ls='--', conn='arc3,rad=-0.20')
label(ax, 2.60, 0.42, 'feedback', fs=6.4, color=orange, fst='italic')
label(ax, 4.98, 0.42, 'feedback', fs=6.4, color=orange, fst='italic')
label(ax, 7.24, 0.42, 'feedback', fs=6.4, color=orange, fst='italic')

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
figures_dir = os.path.join(project_root, 'figures')
os.makedirs(figures_dir, exist_ok=True)

plt.savefig(os.path.join(figures_dir, 'overview.png'), dpi=600,
            bbox_inches='tight', facecolor='white', edgecolor='none')
plt.savefig(os.path.join(figures_dir, 'overview.pdf'),
            bbox_inches='tight', facecolor='white', edgecolor='none')

print("Done!")
