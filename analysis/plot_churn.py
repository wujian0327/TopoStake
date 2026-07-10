#!/usr/bin/env python3
from plot_common import FIGURES, PROCESSED, grouped_series, read_csv


def write_line_pdf(path, title, xlabel, ylabel, series, y_min=None, y_max=None):
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
    fig, ax = plt.subplots(figsize=(4.8, 3.2))
    for name, points in sorted(series.items()):
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        yerr = [point[2] for point in points]
        ax.errorbar(xs, ys, yerr=yerr, marker="o", linewidth=1.6, capsize=2.5, label=name)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_xticks(sorted({point[0] for points in series.values() for point in points}))
    if y_min is not None or y_max is not None:
        bottom, top = ax.get_ylim()
        ax.set_ylim(y_min if y_min is not None else bottom, y_max if y_max is not None else top)
    ax.grid(True, alpha=0.25)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def main() -> int:
    rows = read_csv(PROCESSED / "runs.csv")
    churn_throughput = grouped_series(rows, "churn_appendix", "unstable_fraction", "throughput_mean")
    churn_latency = grouped_series(
        rows, "churn_appendix", "unstable_fraction", "p95_inclusion_latency_s_mean"
    )
    churn_success = grouped_series(rows, "churn_appendix", "unstable_fraction", "block_success_ratio_mean")

    for stale in [
        FIGURES / "churn_throughput.svg",
        FIGURES / "churn_latency.svg",
        FIGURES / "churn_success_ratio.svg",
    ]:
        if stale.exists():
            stale.unlink()

    write_line_pdf(
        FIGURES / "churn_throughput.pdf",
        "Throughput under churn",
        "Unstable fraction",
        "Throughput (tx/s)",
        churn_throughput,
    )
    write_line_pdf(
        FIGURES / "churn_latency.pdf",
        "Latency under churn",
        "Unstable fraction",
        "p95 confirmation latency (s)",
        churn_latency,
        y_min=0.0,
    )
    write_line_pdf(
        FIGURES / "churn_success_ratio.pdf",
        "Successful slots under churn",
        "Unstable fraction",
        "Block success ratio",
        churn_success,
        y_min=0.0,
        y_max=1.0,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
