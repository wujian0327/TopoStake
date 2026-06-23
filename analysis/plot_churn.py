#!/usr/bin/env python3
from plot_common import FIGURES, PROCESSED, grouped_series, read_csv, write_line_svg


def main() -> int:
    rows = read_csv(PROCESSED / "runs.csv")
    write_line_svg(
        FIGURES / "churn_throughput.svg",
        "Throughput under churn",
        "Unstable fraction",
        "Throughput (tx/s)",
        grouped_series(rows, "churn_appendix", "unstable_fraction", "throughput_mean"),
    )
    write_line_svg(
        FIGURES / "churn_latency.svg",
        "Latency under churn",
        "Unstable fraction",
        "p95 inclusion latency (s)",
        grouped_series(rows, "churn_appendix", "unstable_fraction", "p95_inclusion_latency_s_mean"),
    )
    write_line_svg(
        FIGURES / "churn_success_ratio.svg",
        "Successful slots under churn",
        "Unstable fraction",
        "Block success ratio",
        grouped_series(rows, "churn_appendix", "unstable_fraction", "block_success_ratio_mean"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
