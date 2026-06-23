#!/usr/bin/env python3
from collections import defaultdict

from plot_common import FIGURES, PROCESSED, mean_ci, read_csv, to_float, write_line_svg


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
        buckets[(f"observed {placement} eta*cap={eta_cap}", x)].append(
            to_float(row.get("adversary_proposer_weight_share_mean"))
        )
        buckets[(f"bound eta*cap={eta_cap}", x)].append(
            to_float(row.get("theoretical_proposer_weight_bound_mean"))
        )

    series = defaultdict(list)
    for (name, x), values in buckets.items():
        avg, ci, n = mean_ci(values)
        if n:
            series[name].append((float(x), avg, ci))
    write_line_svg(
        FIGURES / "real_stake_bound.svg",
        "Adversary proposer-weight bound",
        "Adversary real-stake share",
        "Proposer-weight share",
        {key: sorted(value) for key, value in series.items()},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
