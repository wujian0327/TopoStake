#!/usr/bin/env python3
from plot_common import FIGURES, PROCESSED, grouped_series, read_csv, write_line_svg


def main() -> int:
    rows = read_csv(PROCESSED / "runs.csv")
    write_line_svg(
        FIGURES / "performance_load_throughput.svg",
        "Performance under offered load",
        "Transaction rate",
        "Throughput (tx/s)",
        grouped_series(rows, "performance_load", "tx_rate", "throughput_mean"),
    )
    write_line_svg(
        FIGURES / "performance_scale_throughput.svg",
        "Performance under network scale",
        "Validators",
        "Throughput (tx/s)",
        grouped_series(rows, "performance_scale", "node_num", "throughput_mean"),
    )
    write_line_svg(
        FIGURES / "topology_robustness_throughput.svg",
        "Topology robustness",
        "Topology",
        "Throughput (tx/s)",
        grouped_series(rows, "topology_robustness", "topology", "throughput_mean"),
    )
    write_line_svg(
        FIGURES / "performance_load_latency.svg",
        "Inclusion latency under offered load",
        "Transaction rate",
        "p95 inclusion latency (s)",
        grouped_series(rows, "performance_load", "tx_rate", "p95_inclusion_latency_s_mean"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
