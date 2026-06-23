#!/usr/bin/env python3
from plot_common import FIGURES, criterion_estimates, write_line_svg


def main() -> int:
    estimates = criterion_estimates()
    series = {
        "criterion": [(label, value, 0.0) for label, value in sorted(estimates.items())]
    }
    write_line_svg(
        FIGURES / "crypto_overhead.svg",
        "BLS path evidence microbenchmarks",
        "Benchmark",
        "Mean time (ms)",
        series,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
