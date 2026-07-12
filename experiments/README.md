# Experiment Pipeline

The pipeline is driven by YAML experiment specifications in `experiments/configs/`.
The checked-in specs are JSON-compatible YAML so the scripts work with only the
Python standard library; if PyYAML is installed, normal YAML is also accepted.

## Commands

```bash
python scripts/task.py experiments-smoke
python scripts/task.py frozen-smoke
python scripts/task.py tdsc-fast
python scripts/task.py experiments-main
python scripts/task.py figures
```

The Python task runner is the recommended cross-platform entry point,
especially on Windows where `make` is usually not installed. The Makefile keeps
equivalent shortcuts for environments that already have `make`.

To run the lower-level scripts directly:

```bash
python experiments/run_experiments.py --config experiments/configs/smoke.yaml
python experiments/summarize.py --config experiments/configs/smoke.yaml
python analysis/plot_performance.py
```

## Experiment Profiles

`experiments/configs/frozen_v1_smoke.yaml` is the first migration smoke test for
the frozen TDSC formulas. It is a correctness check, not a paper experiment.
Its protocol defaults come from `experiments/configs/protocol_frozen_v1.yaml`.

`experiments/configs/tdsc_fast.yaml` is the compact paper-figure profile. It uses deterministic seeds `[0, 1, 2]`, a shorter epoch horizon with warmup, and reduced sweeps for the TDSC submission figures.

`experiments/configs/main.yaml` is the extended experiment profile. Keep it for broader validation runs and appendix-scale sweeps; use `tdsc_fast.yaml` when regenerating the core paper figures quickly.

## Reproducibility

Each run gets its own directory under `results/raw/<suite>/<experiment>/<run-id>/`
with:

- `experiment_meta.json`
- `runner_status.json`
- `run.log`
- simulator `run_config.json`
- simulator `run_summary.json`
- simulator CSV outputs

The runner supports resume by skipping runs that already contain complete
`run_config.json`, `run_summary.json`, and an `ok` runner status. Use `--force`
to rerun them. Failed and timed-out runs keep their per-run `runner_status.json`;
failures are also appended as JSON lines to `results/processed/failed_runs.log`.

## Processed Outputs

`experiments/summarize.py` writes:

- `results/processed/runs.csv`
- `results/processed/epoch_metrics_all.csv`
- `results/processed/node_epoch_metrics_all.csv`
- `results/processed/aggregate_metrics.csv`
- `results/processed/paper_summary.md`

The summary file reports available data and source CSVs only; it does not invent
conclusions when runs are missing.
