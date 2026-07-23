# Experiment Layout

The root [`README.md`](../README.md) is the canonical reproduction guide. This
directory contains the experiment specifications and the Python runners that
support the current frozen-v1 evaluation.

## Current suites

- `frozen_v1_security_{pilot,main}.yaml`: security envelope, path manipulation,
  flooding, and relay-participation stress.
- `frozen_v1_fee_bonus_{pilot,main}.yaml`: long-horizon fee and proposer-bonus
  ablation.
- `frozen_v1_endogenous_participation_pilot.yaml`: reduced-form, paired-seed
  mean-field participation and heterogeneous-cost sensitivity calibrated from
  the RQ2 output; this suite does not rerun the Rust simulator.
- `frozen_v1_adaptive_participation_pilot.yaml`: Rust adaptive-agent pilot in
  which validators update Active/Lazy relay strategies from completed-window
  reward and forwarding observations without future proposer information;
  the second-stage configuration sweeps `1x`, `2x`, and `3x` cost regimes over
  100 epochs, uses 5% seeded exploration to preserve counterfactual coverage,
  and evaluates fixed-follow-up transaction cohorts.
- `frozen_v1_adaptive_participation_stability_probe.yaml`: 24-run targeted
  probe with a 200-epoch horizon, slower strategy updates, and representative
  plus prior boundary conditions.
- `frozen_v1_organic_capture_{pilot,main}.yaml`: organic-traffic capture under
  favorable placement.
- `frozen_v1_reinvestment_gini_{pilot,main}.yaml`: paired long-term stake-Gini
  trajectories under a full-reinvestment upper-bound stress test.
- `frozen_v1_sustained_outage_{pilot,main}.yaml`: random sustained outages and
  proposer-side adaptation; the main suite compares `eta={0,0.5,1}` at 10%,
  20%, and 30% outage stake.
- `frozen_v1_sustained_outage_eta_pilot.yaml`: five-seed, 20%-stake outage
  sweep over `eta={0,0.25,0.5,0.75,1}`.
- `frozen_v1_devnet_{pilot,main}.yaml`: paired real-client Ethereum devnet
  feasibility and overhead.
- `frozen_v1_topology_scale_timing_probe.yaml`: six-run BA scalability probe
  at 100, 500, and 1,000 validators under organic and max-score conditions.
- `frozen_v1_topology_scale_main.yaml`: 20-seed RQ3 scale-robustness matrix at
  100, 500, and 1,000 validators.

The shared protocol parameters are defined in
`configs/protocol_frozen_v1.yaml`. `frozen_v1_smoke.yaml` is the fast simulator
correctness check. The `eth_empirical` and topology-scale profiles are retained
as optional scalability diagnostics; they are not part of the paper's five
main experiment groups.

## Entry points

Run experiments through `scripts/task.py` from the repository root. The usual
pattern is:

```bash
python scripts/task.py frozen-smoke
python scripts/task.py frozen-topology-scale-timing-probe --dry-run
python scripts/task.py frozen-topology-scale-timing-probe
python scripts/task.py frozen-topology-scale-main --dry-run
python scripts/task.py frozen-topology-scale-main
python scripts/task.py <suite>-pilot
python scripts/task.py <suite>-main --dry-run
python scripts/task.py <suite>-main
python scripts/task.py <suite>-figures
```

Use the exact suite commands and devnet prerequisites listed in the root
README. Lower-level modules in this directory implement matrix execution,
acceptance checks, aggregation, and report generation; they are not separate
experiment definitions.

## Outputs

- `results/raw/<suite>/`: per-run logs, resolved configurations, and metrics.
- `results/processed/`: acceptance JSON, grouped and paired tables, summaries,
  and figure inputs.
- `figures/`: generated PDF and PNG figures.

Formal matrices are resumable. Use `--force` only when intentionally replacing
completed simulator runs, and `--resume` for interrupted devnet matrices.
