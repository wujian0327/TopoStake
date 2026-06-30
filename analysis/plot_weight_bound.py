#!/usr/bin/env python3
from collections import defaultdict

from plot_common import FIGURES, PROCESSED, mean_ci, read_csv, to_float


def write_line_pdf(path, title, xlabel, ylabel, series):
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print(f"warning: matplotlib is not available; skipped {path}")
        return

    series = {name: points for name, points in series.items() if points}
    if not series:
        if path.exists():
            path.unlink()
        print(f"warning: no data available; skipped {path}")
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(5.2, 3.5))
    for name, points in sorted(series.items()):
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        yerr = [point[2] for point in points]
        linestyle = "--" if name == "bound" else "-"
        marker = "s" if name == "bound" else "o"
        ax.errorbar(xs, ys, yerr=yerr, marker=marker, linestyle=linestyle, linewidth=1.5, capsize=2.5, label=name)
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_xticks(sorted({point[0] for points in series.values() for point in points}))
    ax.grid(True, alpha=0.25)
    ax.legend(frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def main() -> int:
    rows = [
        row
        for row in read_csv(PROCESSED / "runs.csv")
        if row.get("experiment") == "real_stake_bound" and row.get("status") == "ok"
    ]
    buckets = defaultdict(list)
    for row in rows:
        x = row.get("adversary_stake_fraction", "")
        eta_cap = row.get("eta_bonus_product", row.get("eta", ""))
        placement = row.get("adversary_placement", "")
        buckets[(eta_cap, f"observed {placement}", x)].append(
            to_float(row.get("adversary_proposer_weight_share_mean"))
        )
        buckets[(eta_cap, "bound", x)].append(
            to_float(row.get("theoretical_proposer_weight_bound_mean"))
        )

    series_by_eta = defaultdict(lambda: defaultdict(list))
    for (eta_cap, name, x), values in buckets.items():
        avg, ci, n = mean_ci(values)
        if n:
            series_by_eta[eta_cap][name].append((float(x), avg, ci))

    for stale in [FIGURES / "real_stake_bound.svg", FIGURES / "real_stake_bound.pdf"]:
        if stale.exists():
            stale.unlink()

    for eta_cap, series in sorted(series_by_eta.items(), key=lambda item: float(item[0])):
        suffix = str(eta_cap).replace(".", "p")
        write_line_pdf(
            FIGURES / f"real_stake_bound_eta{suffix}.pdf",
            f"Adversary proposer-weight bound (eta*cap={eta_cap})",
            "Adversary real-stake share",
            "Proposer-weight share",
            {key: sorted(value) for key, value in series.items()},
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
