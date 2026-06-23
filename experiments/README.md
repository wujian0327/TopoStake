# Experiment Pipeline

The pipeline is driven by YAML experiment specifications in `experiments/configs/`.
The checked-in specs are JSON-compatible YAML so the scripts work with only the
Python standard library; if PyYAML is installed, normal YAML is also accepted.

## Commands

```bash
python3 experiments/run_experiments.py --config experiments/configs/smoke.yaml
python3 experiments/summarize.py --config experiments/configs/smoke.yaml
python3 analysis/plot_performance.py
```

`make experiments-smoke` runs the complete reduced pipeline. `make
experiments-main` expands the full paper matrix with five paired seeds.

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
