#!/usr/bin/env python3
from plot_common import FIGURES, PROCESSED, grouped_series, read_csv


def write_line_pdf(path, title, xlabel, ylabel, series, xticks=None):
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
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    if xticks is not None:
        ax.set_xticks(xticks)
    ax.grid(True, alpha=0.25)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def series_xticks(series):
    return sorted({point[0] for points in series.values() for point in points})


def main() -> int:
    rows = read_csv(PROCESSED / "runs.csv")
    performance_load_throughput = grouped_series(rows, "performance_load", "tx_rate", "throughput_mean")
    performance_scale_throughput = grouped_series(rows, "performance_scale", "node_num", "throughput_mean")
    performance_scale_latency = grouped_series(
        rows, "performance_scale", "node_num", "p95_inclusion_latency_s_mean"
    )
    performance_load_latency = grouped_series(
        rows, "performance_load", "tx_rate", "p95_inclusion_latency_s_mean"
    )

    write_line_pdf(
        FIGURES / "performance_load_throughput.pdf",
        "Performance under offered load",
        "Transaction rate",
        "Throughput (tx/s)",
        performance_load_throughput,
        xticks=series_xticks(performance_load_throughput),
    )
    write_line_pdf(
        FIGURES / "performance_load_latency.pdf",
        "Confirmation latency under offered load",
        "Transaction rate",
        "p95 confirmation latency (s)",
        performance_load_latency,
        xticks=series_xticks(performance_load_latency),
    )
    write_line_pdf(
        FIGURES / "performance_scale_throughput.pdf",
        "Performance under network scale",
        "Validators",
        "Throughput (tx/s)",
        performance_scale_throughput,
    )
    write_line_pdf(
        FIGURES / "performance_scale_latency.pdf",
        "Confirmation latency under network scale",
        "Validators",
        "p95 confirmation latency (s)",
        performance_scale_latency,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
