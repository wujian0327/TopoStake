#!/usr/bin/env python3
from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path

from plot_common import FIGURES, PROCESSED, mean_ci, read_csv, to_float


FIGSIZE = (5.2, 3.5)
PLACEMENT_ORDER = ["random", "high-degree", "high-betweenness"]
COLORS = {
    "random": "#1f77b4",
    "high-degree": "#ff7f0e",
    "high-betweenness": "#2ca02c",
    "bound": "#555555",
}
MARKERS = {"0.25": "o", "0.5": "s"}
LINESTYLES = {"0.25": "-", "0.5": "--"}


def setup_matplotlib():
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        return plt
    except ImportError:
        print("warning: matplotlib is not available; skipped real_stake_bound plots")
        return None


def eta_label(eta_cap: str) -> str:
    return f"eta*cap={float(eta_cap):g}" if eta_cap else "eta*cap=?"


def real_stake_rows() -> list[dict[str, str]]:
    return [
        row
        for row in read_csv(PROCESSED / "runs.csv")
        if row.get("experiment") == "real_stake_bound" and row.get("status") == "ok"
    ]


def ci_field(mean_field: str) -> str:
    return f"{mean_field.removesuffix('_mean')}_ci95"


def grouped_points(
    rows: list[dict[str, str]],
    y_field: str,
    transform=None,
) -> dict[tuple[str, str], list[tuple[float, float, float]]]:
    buckets: dict[tuple[str, str, float], list[tuple[float, float]]] = defaultdict(list)
    yerr_field = ci_field(y_field)
    for row in rows:
        placement = row.get("adversary_placement", "")
        eta_cap = row.get("eta_bonus_product", row.get("eta", ""))
        x = to_float(row.get("adversary_real_stake_share_mean"))
        y = to_float(row.get(y_field))
        yerr = to_float(row.get(yerr_field), 0.0)
        if transform:
            y, yerr = transform(row, y, yerr)
        if not placement or not eta_cap or math.isnan(x) or math.isnan(y):
            continue
        buckets[(placement, eta_cap, x)].append((y, yerr))

    out: dict[tuple[str, str], list[tuple[float, float, float]]] = defaultdict(list)
    for (placement, eta_cap, x), values in buckets.items():
        ys = [value for value, _ in values]
        avg, ci, n = mean_ci(ys)
        if not n:
            continue
        if len(values) == 1:
            ci = values[0][1]
        out[(placement, eta_cap)].append((x, avg, ci))

    for points in out.values():
        points.sort(key=lambda item: item[0])
    return dict(out)


def draw_grouped_lines(
    ax,
    series: dict[tuple[str, str], list[tuple[float, float, float]]],
    include_eta: bool = True,
) -> None:
    for placement in PLACEMENT_ORDER:
        eta_caps = sorted({eta for p, eta in series if p == placement}, key=float)
        for eta_cap in eta_caps:
            points = series.get((placement, eta_cap), [])
            if not points:
                continue
            xs = [point[0] for point in points]
            ys = [point[1] for point in points]
            yerr = [point[2] for point in points]
            label = placement if not include_eta else f"{placement}, {eta_label(eta_cap)}"
            ax.errorbar(
                xs,
                ys,
                yerr=yerr,
                marker=MARKERS.get(eta_cap, "o"),
                linestyle=LINESTYLES.get(eta_cap, "-"),
                linewidth=1.5,
                capsize=2.5,
                color=COLORS.get(placement),
                label=label,
            )


def finish_line_plot(
    ax,
    xlabel: str,
    ylabel: str,
    legend_fontsize: int = 7,
    legend_loc: str = "best",
) -> None:
    ax.set_xlim(left=0)
    ax.set_ylim(bottom=0)
    ax.set_xlabel(xlabel, fontsize=12)
    ax.set_ylabel(ylabel, fontsize=12)
    ax.tick_params(axis="both", labelsize=10)
    ax.grid(True, alpha=0.25)
    ax.legend(frameon=False, fontsize=legend_fontsize, loc=legend_loc)


def save_score_share(rows: list[dict[str, str]]) -> None:
    plt = setup_matplotlib()
    if plt is None:
        return
    eta_caps = sorted({row.get("eta_bonus_product", "") for row in rows}, key=float)
    for eta_cap in eta_caps:
        eta_rows = [row for row in rows if row.get("eta_bonus_product") == eta_cap]
        series = grouped_points(eta_rows, "adversary_score_share_mean")
        fig, ax = plt.subplots(figsize=FIGSIZE)
        draw_grouped_lines(ax, series, include_eta=False)
        finish_line_plot(
            ax,
            "Adversarial real-stake share",
            "Adversarial score share",
            legend_fontsize=13,
        )
        ax.tick_params(axis="both", labelsize=13)
        ax.xaxis.label.set_size(15)
        ax.yaxis.label.set_size(15)
        ax.set_xticks([0.1, 0.2, 0.3])
        suffix = str(eta_cap).replace(".", "p")
        fig.tight_layout()
        fig.savefig(FIGURES / f"real_stake_bound_score_share_eta{suffix}.pdf")
        plt.close(fig)


def save_eta_bound_overlays(rows: list[dict[str, str]]) -> None:
    plt = setup_matplotlib()
    if plt is None:
        return
    eta_caps = sorted({row.get("eta_bonus_product", "") for row in rows}, key=float)
    for eta_cap in eta_caps:
        eta_rows = [row for row in rows if row.get("eta_bonus_product") == eta_cap]
        series = grouped_points(eta_rows, "adversary_proposer_weight_share_mean")
        bound_series = grouped_points(eta_rows, "theoretical_proposer_weight_bound_mean")
        fig, ax = plt.subplots(figsize=FIGSIZE)
        draw_grouped_lines(ax, series, include_eta=False)
        all_bounds = [
            point
            for points in bound_series.values()
            for point in points
        ]
        by_x: dict[float, list[float]] = defaultdict(list)
        for x, y, _ in all_bounds:
            by_x[x].append(y)
        bound_points = sorted((x, sum(values) / len(values)) for x, values in by_x.items())
        if bound_points:
            ax.plot(
                [point[0] for point in bound_points],
                [point[1] for point in bound_points],
                color=COLORS["bound"],
                linestyle="--",
                linewidth=1.5,
                marker="s",
                label="theoretical bound",
            )
        finish_line_plot(
            ax,
            "Adversarial real-stake share",
            "Proposer-weight share",
            legend_fontsize=12,
        )
        ax.tick_params(axis="both", labelsize=13)
        ax.xaxis.label.set_size(15)
        ax.yaxis.label.set_size(15)
        ax.set_xticks([0.1, 0.2, 0.3])
        suffix = str(eta_cap).replace(".", "p")
        fig.tight_layout()
        fig.savefig(FIGURES / f"real_stake_bound_weight_bound_eta{suffix}.pdf")
        plt.close(fig)


def amplification_transform(row: dict[str, str], y: float, yerr: float) -> tuple[float, float]:
    stake = to_float(row.get("adversary_real_stake_share_mean"))
    if math.isnan(stake) or stake <= 0.0:
        return math.nan, 0.0
    return y / stake, yerr / stake if not math.isnan(yerr) else 0.0


def save_amplification_ratio(rows: list[dict[str, str]]) -> None:
    plt = setup_matplotlib()
    if plt is None:
        return
    eta_caps = sorted({row.get("eta_bonus_product", "") for row in rows}, key=float)
    for eta_cap in eta_caps:
        eta_rows = [row for row in rows if row.get("eta_bonus_product") == eta_cap]
        series = grouped_points(
            eta_rows,
            "adversary_proposer_weight_share_mean",
            amplification_transform,
        )
        fig, ax = plt.subplots(figsize=FIGSIZE)
        draw_grouped_lines(ax, series, include_eta=False)
        xmax = max((point[0] for points in series.values() for point in points), default=0.3)
        bound = 1.0 + float(eta_cap)
        ax.hlines(
            bound,
            0.0,
            xmax * 1.03,
            color=COLORS["bound"],
            linestyle="--",
            linewidth=1.2,
            label="theoretical bound",
        )
        finish_line_plot(
            ax,
            "Adversarial real-stake share",
            "Amplification ratio",
            legend_fontsize=12,
            legend_loc="lower left",
        )
        ymax = max(
            [bound]
            + [point[1] for points in series.values() for point in points]
        )
        ax.set_ylim(0, ymax * 1.12)
        ax.set_xticks([0.1, 0.2, 0.3])
        ax.set_yticks([0.0, 0.5, 1.0, bound])
        ax.set_yticklabels(["0", "0.5", "1.0", f"{bound:.2g}"])
        ax.tick_params(axis="both", labelsize=13)
        ax.xaxis.label.set_size(15)
        ax.yaxis.label.set_size(15)
        suffix = str(eta_cap).replace(".", "p")
        fig.tight_layout()
        fig.savefig(FIGURES / f"real_stake_bound_amplification_ratio_eta{suffix}.pdf")
        plt.close(fig)


def remove_stale_outputs() -> None:
    for name in [
        "real_stake_bound.svg",
        "real_stake_bound.pdf",
        "real_stake_bound_weight.pdf",
        "real_stake_bound_eta0p25.pdf",
        "real_stake_bound_eta0p5.pdf",
        "real_stake_bound_score_share.pdf",
        "real_stake_bound_weight_bound.pdf",
        "real_stake_bound_amplification_ratio.pdf",
        "real_stake_bound_observed_bound.pdf",
        "real_stake_bound_violation_rate.pdf",
    ]:
        path = FIGURES / name
        if path.exists():
            path.unlink()


def main() -> int:
    rows = real_stake_rows()
    if not rows:
        print("warning: no real_stake_bound data available")
        return 0

    FIGURES.mkdir(parents=True, exist_ok=True)
    remove_stale_outputs()
    save_score_share(rows)
    save_amplification_ratio(rows)
    save_eta_bound_overlays(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
