import os
import matplotlib.pyplot as plt

from matplotlib.patches import (
    Circle,
    FancyBboxPatch,
    FancyArrowPatch,
    Rectangle,
)


# ============================================================
# Output
# ============================================================

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT_DIR, "figures")
OUT_PDF = os.path.join(OUT_DIR, "overview.pdf")
OUT_PNG = os.path.join(OUT_DIR, "overview.png")

os.makedirs(OUT_DIR, exist_ok=True)


# ============================================================
# Global style
# ============================================================

plt.rcParams["font.family"] = "STIXGeneral"
plt.rcParams["mathtext.fontset"] = "stix"

# Colors
BLUE = "#174F94"
BLUE_DARK = "#0B376D"
BLUE_LIGHT = "#F4FAFF"
BLUE_NODE = "#DDEEFF"

GREEN = "#2F6B3F"
GREEN_DARK = "#1F5B33"
GREEN_LIGHT = "#F3FFF4"
GREEN_BOX = "#EAF7EC"

TEAL = "#1D6F68"
TEAL_DARK = "#0F514D"
TEAL_LIGHT = "#F1FFFC"
TEAL_BOX = "#E6F7F4"

ORANGE = "#C96A12"
ORANGE_DARK = "#A64F00"
ORANGE_LIGHT = "#FFF7EE"

GRAY = "#6F7F8A"
GRAY_LIGHT = "#F7F7F7"
GRAY_EDGE = "#9AA7B3"

BLACK = "#1E2A36"


# ============================================================
# Helper functions
# ============================================================

def rounded_box(
    ax,
    x,
    y,
    w,
    h,
    text="",
    fc="white",
    ec="black",
    lw=1.2,
    radius=0.06,
    fontsize=11,
    color=BLACK,
    weight="normal",
    style="normal",
    ha="center",
    va="center",
    zorder=5,
    pad=0.03,
    linespacing=1.15,
    linestyle="solid",
):
    """Draw rounded rectangle with centered text."""
    box = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle=f"round,pad={pad},rounding_size={radius}",
        facecolor=fc,
        edgecolor=ec,
        lw=lw,
        linestyle=linestyle,
        zorder=zorder,
    )
    ax.add_patch(box)

    if text:
        ax.text(
            x + w / 2,
            y + h / 2,
            text,
            ha=ha,
            va=va,
            fontsize=fontsize,
            color=color,
            fontweight=weight,
            fontstyle=style,
            linespacing=linespacing,
            zorder=zorder + 1,
        )

    return box


def draw_arrow(
    ax,
    p1,
    p2,
    color=BLACK,
    lw=1.6,
    dashed=False,
    rad=0.0,
    mutation=14,
    zorder=20,
    alpha=1.0,
    arrowstyle="-|>",
):
    """Draw arrow between two points."""
    linestyle = (0, (4, 3)) if dashed else "solid"

    arrow = FancyArrowPatch(
        p1,
        p2,
        arrowstyle=arrowstyle,
        mutation_scale=mutation,
        linewidth=lw,
        color=color,
        linestyle=linestyle,
        connectionstyle=f"arc3,rad={rad}",
        zorder=zorder,
        alpha=alpha,
    )
    ax.add_patch(arrow)
    return arrow


def draw_panel(ax, x, y, w, h, edge, fill, step, title, title_color):
    """Draw a top-level step panel."""
    rounded_box(
        ax,
        x,
        y,
        w,
        h,
        fc=fill,
        ec=edge,
        lw=1.4,
        radius=0.12,
        zorder=1,
    )

    ax.text(
        x + w / 2,
        y + h - 0.38,
        step,
        ha="center",
        va="center",
        fontsize=17,
        fontweight="bold",
        color=title_color,
        zorder=10,
    )

    ax.text(
        x + w / 2,
        y + h - 0.72,
        title,
        ha="center",
        va="center",
        fontsize=13.9,
        fontweight="bold",
        color=title_color,
        zorder=10,
    )


def draw_small_network_icon(ax, cx, cy, s=1.0):
    """Small path-tracing network icon in Step 1."""
    pts = {
        "a": (cx - 0.95 * s, cy + 0.18 * s),
        "b": (cx - 0.05 * s, cy + 0.78 * s),
        "c": (cx + 0.72 * s, cy + 0.42 * s),
        "d": (cx - 0.28 * s, cy - 0.12 * s),
        "e": (cx + 0.48 * s, cy - 0.08 * s),
        "f": (cx - 0.92 * s, cy - 0.55 * s),
        "g": (cx + 1.05 * s, cy - 0.50 * s),
        "h": (cx - 0.22 * s, cy - 0.90 * s),
    }

    dashed_edges = [
        ("a", "b"),
        ("b", "c"),
        ("b", "d"),
        ("a", "f"),
        ("f", "d"),
        ("d", "h"),
        ("c", "e"),
        ("e", "g"),
    ]

    solid_edges = [
        ("a", "d"),
        ("d", "e"),
    ]

    for u, v in dashed_edges:
        x1, y1 = pts[u]
        x2, y2 = pts[v]
        ax.plot(
            [x1, x2],
            [y1, y2],
            color="#7AA0D6",
            lw=1.0,
            linestyle=(0, (4, 3)),
            zorder=5,
        )

    for u, v in solid_edges:
        x1, y1 = pts[u]
        x2, y2 = pts[v]
        ax.plot(
            [x1, x2],
            [y1, y2],
            color=BLUE,
            lw=1.3,
            zorder=6,
        )

    for x, y in pts.values():
        ax.add_patch(
            Circle(
                (x, y),
                0.12 * s,
                facecolor="white",
                edgecolor=BLUE,
                lw=1.2,
                zorder=8,
            )
        )


def draw_divider(ax, x1, x2, y, color):
    ax.plot(
        [x1, x2],
        [y, y],
        color=color,
        lw=1.0,
        alpha=0.85,
        zorder=8,
    )


# ============================================================
# Step 1
# ============================================================

def draw_step1(ax, x, y, w, h):
    draw_panel(
        ax,
        x,
        y,
        w,
        h,
        edge=BLUE,
        fill=BLUE_LIGHT,
        step="Step 1",
        title="Verifiable Path Tracing",
        title_color=BLUE_DARK,
    )

    draw_small_network_icon(ax, x + w / 2, y + 2.12, s=0.75)

    draw_divider(ax, x + 0.40, x + w - 0.40, y + 1.22, BLUE)

    ax.text(
        x + 1.48,
        y + 0.63,
        "Trace the transaction\npropagation and collect\nsignatures.",
        ha="center",
        va="center",
        fontsize=11.6,
        color=BLACK,
        linespacing=1.25,
        zorder=10,
    )


# ============================================================
# Step 2
# ============================================================

def draw_step2(ax, x, y, w, h):
    draw_panel(
        ax,
        x,
        y,
        w,
        h,
        edge=GREEN,
        fill=GREEN_LIGHT,
        step="Step 2",
        title="Contribution Quantification",
        title_color=GREEN_DARK,
    )

    box_y = y + 2.05
    box_h = 0.70

    b1 = (x + 0.12, box_y, 0.72, box_h)
    b2 = (x + 1.17, box_y, 0.74, box_h)
    b3 = (x + 2.24, box_y, 0.66, box_h)
    b4 = (x + 3.23, box_y, 0.52, box_h)
    b5 = (x + 4.08, box_y, 0.92, box_h)

    rounded_box(
        ax, *b1,
        text="Verified\npath $p$",
        fc=GREEN_BOX,
        ec=GREEN,
        fontsize=10.0,
        color=BLACK,
    )
    rounded_box(
        ax, *b2,
        text="Atomic\nscore\n$\\gamma(v,p)$",
        fc=GREEN_BOX,
        ec=GREEN,
        fontsize=9.8,
        color=BLACK,
    )
    rounded_box(
        ax, *b3,
        text="LogSat",
        fc=GREEN_BOX,
        ec=GREEN,
        fontsize=10.3,
        color=BLACK,
    )
    rounded_box(
        ax, *b4,
        text="EMA",
        fc=GREEN_BOX,
        ec=GREEN,
        fontsize=10.3,
        color=BLACK,
    )
    rounded_box(
        ax, *b5,
        text="Contribution\nScore\n$Score(v,t)$",
        fc=GREEN_BOX,
        ec=GREEN,
        fontsize=9.5,
        color=BLACK,
    )

    # Pipeline arrows
    step_arrow = dict(color=GREEN, mutation=11, lw=1.25, arrowstyle="->")
    draw_arrow(ax, (b1[0] + b1[2] + 0.02, box_y + box_h / 2), (b2[0] - 0.02, box_y + box_h / 2), **step_arrow)
    draw_arrow(ax, (b2[0] + b2[2] + 0.02, box_y + box_h / 2), (b3[0] - 0.02, box_y + box_h / 2), **step_arrow)
    draw_arrow(ax, (b3[0] + b3[2] + 0.02, box_y + box_h / 2), (b4[0] - 0.02, box_y + box_h / 2), **step_arrow)
    draw_arrow(ax, (b4[0] + b4[2] + 0.02, box_y + box_h / 2), (b5[0] - 0.02, box_y + box_h / 2), **step_arrow)

    # Inputs to atomic score
    iy = y + 1.15
    input_boxes = [
        (x + 0.50, iy, 0.78, 0.48, "position", b2[0] + b2[2] * 0.18),
        (x + 1.49, iy, 0.82, 0.48, "path\nlength", b2[0] + b2[2] * 0.50),
        (x + 2.52, iy, 0.92, 0.48, "target\ndepth $D_e$", b2[0] + b2[2] * 0.82),
    ]

    for bx, by, bw, bh, txt, target_x in input_boxes:
        rounded_box(
            ax,
            bx,
            by,
            bw,
            bh,
            text=txt,
            fc=GREEN_BOX,
            ec=GREEN,
            fontsize=10.2,
            color=BLACK,
            style="italic",
        )
        draw_arrow(
            ax,
            (bx + bw / 2, by + bh + 0.03),
            (target_x, box_y),
            color=GREEN,
            lw=1.2,
            dashed=True,
            mutation=10,
            zorder=15,
            arrowstyle="->",
        )

    draw_divider(ax, x + 0.35, x + w - 0.35, y + 0.88, GREEN)

    ax.text(
        x + 2.55,
        y + 0.45,
        "Quantify each relay's contribution using path\nfeatures and smoothing.",
        ha="center",
        va="center",
        fontsize=12.3,
        color=BLACK,
        linespacing=1.2,
        zorder=10,
    )


# ============================================================
# Step 3
# ============================================================

def draw_step3(ax, x, y, w, h):
    draw_panel(
        ax,
        x,
        y,
        w,
        h,
        edge=TEAL,
        fill=TEAL_LIGHT,
        step="Step 3",
        title="Virtual Stake & Election",
        title_color=TEAL_DARK,
    )

    top_y = y + 2.52

    rounded_box(
        ax,
        x + 0.24,
        top_y,
        1.18,
        0.64,
        text="Economic\nStake\n$S(v,t)$",
        fc=TEAL_BOX,
        ec=TEAL,
        fontsize=10.6,
        color=BLACK,
    )

    rounded_box(
        ax,
        x + 2.02,
        top_y,
        1.34,
        0.64,
        text="Contribution\nScore\n$Score(v,t)$",
        fc=TEAL_BOX,
        ec=TEAL,
        fontsize=10.3,
        color=BLACK,
    )

    vs_x = x + 0.88
    vs_y = y + 1.52
    vs_w = 1.86
    vs_h = 0.62

    rounded_box(
        ax,
        vs_x,
        vs_y,
        vs_w,
        vs_h,
        text="Virtual Stake\n$S^{virt}(v,t+1)$",
        fc=TEAL_BOX,
        ec=TEAL,
        fontsize=11.4,
        color=BLACK,
    )

    # Merge arrows
    draw_arrow(
        ax,
        (x + 0.87, top_y),
        (vs_x + vs_w * 0.35, vs_y + vs_h),
        color=TEAL,
        lw=1.3,
        mutation=12,
        arrowstyle="->",
    )
    draw_arrow(
        ax,
        (x + 2.72, top_y),
        (vs_x + vs_w * 0.65, vs_y + vs_h),
        color=TEAL,
        lw=1.3,
        mutation=12,
        arrowstyle="->",
    )

    # Timing callout
    rounded_box(
        ax,
        x + 2.98,
        y + 1.53,
        0.58,
        0.60,
        text="applied\nat slot\n$t+1$",
        fc="#FFFFFF",
        ec=TEAL,
        lw=1.0,
        radius=0.05,
        fontsize=8.5,
        color=TEAL_DARK,
        zorder=12,
        linestyle=(0, (3, 2)),
    )

    # Election boxes
    le_x = x + 0.88
    le_y = y + 0.795
    le_w = 1.86
    le_h = 0.46

    rounded_box(
        ax,
        le_x,
        le_y,
        le_w,
        le_h,
        text="Leader election\n(RANDAO)",
        fc=TEAL_BOX,
        ec=TEAL,
        fontsize=10.6,
        color=BLACK,
    )

    ps_x = x + 0.88
    ps_y = y + 0.18
    ps_w = 1.86
    ps_h = 0.35

    rounded_box(
        ax,
        ps_x,
        ps_y,
        ps_w,
        ps_h,
        text="Proposer selected",
        fc=TEAL_BOX,
        ec=TEAL,
        fontsize=10.4,
        color=BLACK,
    )

    draw_arrow(
        ax,
        (vs_x + vs_w / 2, vs_y),
        (le_x + le_w / 2, le_y + le_h),
        color=TEAL,
        lw=1.3,
        mutation=12,
        arrowstyle="->",
    )
    draw_arrow(
        ax,
        (le_x + le_w / 2, le_y),
        (ps_x + ps_w / 2, ps_y + ps_h),
        color=TEAL,
        lw=1.3,
        mutation=12,
        arrowstyle="->",
    )


# ============================================================
# Step 4
# ============================================================

def draw_step4(ax, x, y, w, h):
    draw_panel(
        ax,
        x,
        y,
        w,
        h,
        edge=ORANGE,
        fill=ORANGE_LIGHT,
        step="Step 4",
        title="Incentive and Reward",
        title_color=ORANGE_DARK,
    )

    fee_x = x + 0.36
    fee_y = y + 2.52
    fee_w = w - 0.72
    fee_h = 0.62

    rounded_box(
        ax,
        fee_x,
        fee_y,
        fee_w,
        fee_h,
        text="Transaction fees",
        fc="#FFFDF9",
        ec=ORANGE,
        fontsize=10.9,
        color=BLACK,
    )

    ax.text(
        x + w / 2,
        y + 2.1,
        "fee split",
        ha="center",
        va="center",
        fontsize=10.0,
        color=ORANGE_DARK,
        zorder=12,
    )

    prop_x = x + 0.10
    prop_y = y + 1.02
    prop_w = 1.30
    prop_h = 0.92

    rel_x = x + 1.60
    rel_y = y + 1.02
    rel_w = 1.30
    rel_h = 0.92

    rounded_box(
        ax,
        prop_x,
        prop_y,
        prop_w,
        prop_h,
        text="Proposer\nreward\n$base + \\frac{1}{2}\\eta \cdot fee$",
        fc="#FFFDF9",
        ec=ORANGE,
        fontsize=10,
        color=ORANGE_DARK,
    )

    rounded_box(
        ax,
        rel_x,
        rel_y,
        rel_w,
        rel_h,
        text="Relay\nredistribution\nby score\n$(1-\\frac{1}{2}\\eta)\\, \cdot fee$",
        fc="#FFFDF9",
        ec=ORANGE,
        fontsize=9.3,
        color=ORANGE_DARK,
    )

    relayer_x = x + 1.60
    relayer_y = y + 0.25
    relayer_w = 1.30
    relayer_h = 0.44

    rounded_box(
        ax,
        relayer_x,
        relayer_y,
        relayer_w,
        relayer_h,
        text="Relayers on the\nverified path",
        fc="#FFFDF9",
        ec=ORANGE,
        fontsize=9.3,
        color=BLACK,
        style="italic",
    )

    # Split arrows
    draw_arrow(
        ax,
        (x + w / 2, fee_y),
        (prop_x + prop_w / 2, prop_y + prop_h),
        color=ORANGE,
        lw=1.2,
        mutation=11,
        arrowstyle="->",
    )
    draw_arrow(
        ax,
        (x + w / 2, fee_y),
        (rel_x + rel_w / 2, rel_y + rel_h),
        color=ORANGE,
        lw=1.2,
        mutation=11,
        arrowstyle="->",
    )

    # Relay redistribution to path relayers
    draw_arrow(
        ax,
        (rel_x + rel_w / 2, rel_y),
        (relayer_x + relayer_w / 2, relayer_y + relayer_h),
        color=ORANGE,
        lw=1.2,
        dashed=True,
        mutation=10,
        arrowstyle="->",
    )


# ============================================================
# Bottom transaction propagation example
# ============================================================

def draw_route_box(ax, x, y, text):
    rounded_box(
        ax,
        x,
        y,
        0.62,
        0.36,
        text=text,
        fc="white",
        ec=BLUE,
        lw=1.1,
        radius=0.035,
        fontsize=11.8,
        color=BLACK,
        zorder=15,
    )


def draw_path_node(ax, x, y, label, sublabel=None, proposer=False):
    r = 0.38 if not proposer else 0.36
    fc = BLUE_NODE if not proposer else "white"
    ec = BLUE if not proposer else BLUE_DARK
    lw = 1.8 if not proposer else 2.0

    ax.add_patch(
        Circle(
            (x, y),
            r,
            facecolor=fc,
            edgecolor=ec,
            lw=lw,
            zorder=20,
        )
    )

    ax.text(
        x,
        y,
        label,
        ha="center",
        va="center",
        fontsize=18.0,
        color=BLACK,
        zorder=21,
    )

    if sublabel:
        sub_y = y - 0.62 if proposer else y - 0.56
        sub_fs = 10.4 if proposer else 11.2
        ax.text(
            x,
            sub_y,
            sublabel,
            ha="center",
            va="center",
            fontsize=sub_fs,
            color=BLUE_DARK,
            fontstyle="italic",
            zorder=21,
        )


def draw_transaction_example(ax, x, y, w, h):
    # Outer panel
    rounded_box(
        ax,
        x,
        y,
        w,
        h,
        fc=BLUE_LIGHT,
        ec=BLUE,
        lw=1.4,
        radius=0.12,
        zorder=1,
    )

    # Title band
    rounded_box(
        ax,
        x + 0.18,
        y + h - 0.39,
        3.95,
        0.28,
        text="Transaction Propagation Example",
        fc=BLUE,
        ec=BLUE,
        lw=1.0,
        radius=0.05,
        fontsize=12.0,
        color="white",
        weight="bold",
        zorder=10,
    )

    ax.text(
        x + 4.32,
        y + h - 0.25,
        "(aligned with Step 1)",
        ha="left",
        va="center",
        fontsize=12.0,
        color=BLUE_DARK,
        fontstyle="italic",
        zorder=10,
    )

    # Path nodes
    node_y = y + 1.34
    xs = [x + 0.80, x + 3.05, x + 5.00, x + 7.35]
    labels = [r"$v_0$", r"$v_1$", r"$v_2$", r"$v_m$"]
    sublabels = ["tx originator", None, None, "block proposer"]

    draw_path_node(ax, xs[0], node_y, labels[0], sublabels[0])
    draw_path_node(ax, xs[1], node_y, labels[1], sublabels[1])
    draw_path_node(ax, xs[2], node_y, labels[2], sublabels[2])
    draw_path_node(ax, xs[3], node_y, labels[3], sublabels[3], proposer=True)

    # Arrows between nodes
    arrow_y = node_y

    draw_arrow(
        ax,
        (xs[0] + 0.42, arrow_y),
        (xs[1] - 0.42, arrow_y),
        color=BLACK,
        lw=1.6,
        mutation=15,
        arrowstyle="->",
    )
    ax.text(
        (xs[0] + xs[1]) / 2,
        arrow_y + 0.28,
        "verify +\nappend",
        ha="center",
        va="center",
        fontsize=11.2,
        color=BLUE_DARK,
        fontstyle="italic",
        zorder=20,
    )

    draw_arrow(
        ax,
        (xs[1] + 0.42, arrow_y),
        (xs[2] - 0.42, arrow_y),
        color=BLACK,
        lw=1.6,
        mutation=15,
        arrowstyle="->",
    )
    ax.text(
        (xs[1] + xs[2]) / 2,
        arrow_y + 0.28,
        "verify +\nappend",
        ha="center",
        va="center",
        fontsize=11.2,
        color=BLUE_DARK,
        fontstyle="italic",
        zorder=20,
    )

    # Omitted relays: solid segment, ellipsis, then final arrow.
    ell_x0 = x + 6.02
    ax.plot(
        [xs[2] + 0.42, ell_x0 - 0.36],
        [arrow_y, arrow_y],
        color=BLACK,
        lw=1.6,
        zorder=18,
    )
    for i in range(3):
        ax.add_patch(
            Circle(
                (ell_x0 + i * 0.20, arrow_y),
                0.055,
                facecolor=GRAY,
                edgecolor="none",
                zorder=20,
            )
        )

    draw_arrow(
        ax,
        (ell_x0 + 0.62, arrow_y),
        (xs[3] - 0.43, arrow_y),
        color=BLACK,
        lw=1.6,
        mutation=15,
        arrowstyle="->",
    )

    # Route boxes
    route_y = y + 0.58
    draw_route_box(ax, (xs[0] + xs[1]) / 2 - 0.28, route_y, r"$r_0$")
    draw_route_box(ax, (xs[1] + xs[2]) / 2 - 0.28, route_y, r"$r_1$")
    draw_route_box(ax, ell_x0 - 0.12, route_y, r"$r_{m-1}$")

    # Dashed vertical connectors
    connector_positions = [
        ((xs[0] + xs[1]) / 2, route_y + 0.34),
        ((xs[1] + xs[2]) / 2, route_y + 0.34),
        (ell_x0 + 0.16, route_y + 0.34),
    ]

    for cx, cy in connector_positions:
        ax.plot(
            [cx, cx],
            [cy, node_y - 0.12],
            color=BLACK,
            lw=1.0,
            linestyle=(0, (3, 2)),
            alpha=0.75,
            zorder=14,
        )

    # Separator before proof compression
    sep_x = x + 8.15
    ax.plot(
        [sep_x, sep_x],
        [y + 0.24, y + h - 0.18],
        color=GRAY_EDGE,
        lw=1.0,
        linestyle=(0, (3, 3)),
        alpha=0.8,
        zorder=10,
    )

    # Proof compression box
    pc_x = x + 8.45
    pc_y = y + 0.22
    pc_w = 2.55
    pc_h = h - 0.42

    rounded_box(
        ax,
        pc_x,
        pc_y,
        pc_w,
        pc_h,
        fc=GRAY_LIGHT,
        ec=GRAY_EDGE,
        lw=1.0,
        radius=0.07,
        zorder=5,
    )

    ax.text(
        pc_x + pc_w / 2,
        pc_y + pc_h - 0.28,
        "Proof Compression",
        ha="center",
        va="center",
        fontsize=12.6,
        color=BLACK,
        fontweight="bold",
        zorder=15,
    )

    rounded_box(
        ax,
        pc_x + 0.20,
        pc_y + 1.20,
        pc_w - 0.40,
        0.58,
        text="Route record\n$[r_0,\\ldots,r_{m-1}]$",
        fc="white",
        ec=BLUE,
        lw=1.0,
        radius=0.05,
        fontsize=10.5,
        color=BLACK,
        zorder=12,
    )

    draw_arrow(
        ax,
        (pc_x + pc_w / 2, pc_y + 1.18),
        (pc_x + pc_w / 2, pc_y + 0.88),
        color=BLACK,
        lw=1.2,
        zorder=14,
    )

    rounded_box(
        ax,
        pc_x + 0.20,
        pc_y + 0.12,
        pc_w - 0.40,
        0.78,
        text="BLS aggregate proof\n$\\sigma_{agg}$ + signer sequence\n$[v_0,\\ldots,v_{m-1}]$",
        fc="white",
        ec=BLUE,
        lw=1.0,
        radius=0.05,
        fontsize=9.5,
        color=BLACK,
        zorder=12,
    )


# ============================================================
# Feedback loop
# ============================================================

def draw_feedback_loop(ax):
    """
    Draw large dashed reward feedback loop from Step 4 to transaction path.
    """

    # Polyline style feedback path
    xs = [15.50, 15.50, 2.15, 2.15]
    ys = [4.70, 0.63, 0.63, 1.18]

    ax.plot(
        xs[:3],
        ys[:3],
        color=ORANGE_DARK,
        lw=1.3,
        linestyle=(0, (4, 3)),
        zorder=2,
    )

    ax.plot(
        [2.15, 2.15],
        [0.63, 1.12],
        color=ORANGE_DARK,
        lw=1.3,
        linestyle=(0, (4, 3)),
        zorder=2,
    )
    draw_arrow(
        ax,
        (2.15, 1.12),
        (2.15, 1.25),
        color=ORANGE_DARK,
        lw=1.3,
        mutation=13,
        zorder=3,
        arrowstyle="->",
    )

    ax.text(
        7.80,
        0.82,
        "feedback to future relay behavior",
        ha="center",
        va="center",
        fontsize=14.8,
        color=ORANGE_DARK,
        fontstyle="italic",
        zorder=5,
    )


# ============================================================
# Main drawing
# ============================================================

def draw_overview():
    fig, ax = plt.subplots(figsize=(11.37334, 6.40))

    ax.set_xlim(0, 16.5)
    ax.set_ylim(0.3, 9.0)
    ax.set_aspect("equal")
    ax.axis("off")

    # Top panels
    step_y = 4.45
    step_h = 4.15

    s1 = (0.40, step_y, 3.00, step_h)
    s2 = (3.75, step_y, 5.10, step_h)
    s3 = (9.25, step_y, 3.65, step_h)
    s4 = (13.25, step_y, 3.00, step_h)

    draw_step1(ax, *s1)
    draw_step2(ax, *s2)
    draw_step3(ax, *s3)
    draw_step4(ax, *s4)

    # Main pipeline arrows between top panels
    pipeline_y = step_y + step_h / 2
    draw_arrow(
        ax,
        (s1[0] + s1[2], pipeline_y),
        (s2[0], pipeline_y),
        color=BLUE_DARK,
        lw=1.8,
        mutation=18,
    )

    draw_arrow(
        ax,
        (s2[0] + s2[2], pipeline_y),
        (s3[0], pipeline_y),
        color=BLUE_DARK,
        lw=1.8,
        mutation=18,
    )

    draw_arrow(
        ax,
        (s3[0] + s3[2], pipeline_y),
        (s4[0], pipeline_y),
        color=BLUE_DARK,
        lw=1.8,
        mutation=18,
    )

    # Bottom propagation example
    bottom = (0.40, 1.25, 11.20, 2.75)
    draw_transaction_example(ax, *bottom)

    # Link Step 1 to bottom example
    link_x = s1[0] + s1[2] / 2
    draw_arrow(
        ax,
        (link_x, bottom[1] + bottom[3] + 0.01),
        (link_x, step_y - 0.01),
        color=GRAY_EDGE,
        lw=1.0,
        dashed=True,
        mutation=11,
        zorder=3,
        arrowstyle="->",
    )

    # Feedback loop
    draw_feedback_loop(ax)

    # Optional small label, useful when exported standalone.
    # 如果 LaTeX 里已有 caption，一般不需要图内 caption。
    # ax.text(
    #     8.25,
    #     -0.10,
    #     "Figure 2: Closed-loop workflow of TopoStake.",
    #     ha="center",
    #     va="top",
    #     fontsize=12,
    #     fontweight="bold",
    # )

    plt.tight_layout(pad=0.2)

    fig.savefig(OUT_PDF, bbox_inches="tight", pad_inches=0.005, facecolor="white")
    fig.savefig(OUT_PNG, dpi=150, bbox_inches="tight", pad_inches=0.005, facecolor="white")

    return fig, ax


if __name__ == "__main__":
    fig, ax = draw_overview()
    # plt.show()
