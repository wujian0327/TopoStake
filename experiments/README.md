# Experiment Pipeline

The pipeline is driven by YAML experiment specifications in `experiments/configs/`.
The checked-in specs are JSON-compatible YAML so the scripts work with only the
Python standard library; if PyYAML is installed, normal YAML is also accepted.

## Commands

```bash
python scripts/task.py experiments-smoke
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

## Reproducibility

Each run gets its own directory under `results/raw/<suite>/<experiment>/<run-id>/`
with:

- `experiment_meta.json`
- `runner_status.json`
- `run.log`
- simulator `run_config.json`
- simulator `run_summary.json`
- simulator CSV outputs

The runner supports resume by skipping runs that already contain both
`run_config.json` and `run_summary.json`. Use `--force` to rerun them.

## Processed Outputs

`experiments/summarize.py` writes:

- `results/processed/runs.csv`
- `results/processed/epoch_metrics_all.csv`
- `results/processed/node_epoch_metrics_all.csv`
- `results/processed/aggregate_metrics.csv`
- `results/processed/paper_summary.md`

The summary file reports available data and source CSVs only; it does not invent
conclusions when runs are missing.
