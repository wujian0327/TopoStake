# Experiment Pipeline

The pipeline is driven by YAML experiment specifications in `experiments/configs/`.
The checked-in specs are JSON-compatible YAML so the scripts work with only the
Python standard library; if PyYAML is installed, normal YAML is also accepted.

## Commands

```bash
python scripts/task.py experiments-smoke
python scripts/task.py frozen-smoke
python scripts/task.py frozen-eth-empirical-dry-run --dry-run
python scripts/task.py frozen-topology-scale-pilot --dry-run
python scripts/task.py frozen-topology-scale-timing-probe --dry-run
python scripts/task.py frozen-padding-check
python scripts/task.py frozen-evidence-bench
python scripts/task.py frozen-security-pilot
python scripts/task.py frozen-security-main --dry-run
python scripts/task.py frozen-security-figures
python scripts/task.py frozen-sustained-outage-main --dry-run
python scripts/task.py frozen-sustained-outage-figures
python scripts/task.py frozen-devnet-check
python scripts/task.py frozen-devnet-figures
python scripts/task.py frozen-devnet-pilot --dry-run
python scripts/task.py tdsc-fast
python scripts/task.py experiments-main
python scripts/task.py figures
python scripts/task.py paper-figures
```

The Python task runner is the recommended cross-platform entry point,
especially on Windows where `make` is usually not installed. The Makefile keeps
equivalent shortcuts for environments that already have `make`.
`paper-figures` only redraws figures from existing raw/processed data; it does
not rerun any experiment.

`frozen-evidence-bench` measures path construction, individual BLS
verification, aggregation, cold aggregate verification, and encoded evidence
size for 1/2/4/8/16 hops. It also checks malformed-signature rejection and the
consensus-defined maximum-path/work-limit boundary. Run it on an otherwise idle
machine in release mode; the task writes raw samples, a summary CSV, an
acceptance JSON, separate `_a`/`_b` PDF/PNG figures, and a generated LaTeX table.

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

`frozen_v1_security_pilot.yaml` is a 38-run correctness and reporting gate.
`frozen_v1_security_main.yaml` is the formal 20-seed Rust-simulator matrix. It
contains 1340 resumable runs covering end-to-end path-padding stress, the two
proposer-influence bounds, flooding economics, low-load score-floor
sensitivity, focal-relayer participation, and a separate network-wide relay
stress test. In the focal experiment, all non-focal validators keep the normal
strategy and the same deterministic validator changes only its forwarding
probability; relay strategy never changes the topology-derived link delay.
A separate deterministic fixed-path
check exhaustively validates padding non-amplification against the Rust reward
formulas. The security report writes run-level, grouped, paired-CI, and
acceptance artifacts under `results/processed/`. Run the pilot before the main
matrix; use `--dry-run` to inspect exact commands.

`frozen_v1_eth_empirical_dry_run.yaml` is a single-run resource probe for the
1,000-validator Rust simulator. Its `eth_empirical` topology is a connected,
preferential-attachment graph calibrated to an average degree of approximately
18 and a heavy-tailed degree profile. It represents public Ethereum crawl
statistics rather than a recovered mainnet adjacency snapshot. The profile is
deliberately short (six epochs), uses one seed and `max_parallel=1`, and is not
a paper result. It writes only to
`results/raw/frozen_v1_eth_empirical_dry_run/` and does not replace the generic
processed experiment tables. On a 32-core server, run it with a bounded Tokio
worker pool and retain the host resource report separately:

```bash
/usr/bin/time -v -o eth_empirical_dry_run_time.txt \
  env TOKIO_WORKER_THREADS=32 \
  python scripts/task.py frozen-eth-empirical-dry-run
```

`frozen_v1_topology_scale_pilot.yaml` is the 32-run, one-seed quality gate for
the RQ3 topology/scale extension. It crosses 100/1,000 validators, BA and
`eth_empirical` graphs, 10/30% coalition stake, random/high-degree placement,
and normal/favorable-path conditions. It runs serially and reports each
node-count/topology cell separately. The report rejects incomplete or
unpaired runs, assignment drift, mixed revisions, malformed or disconnected
graphs, an out-of-profile 1,000-node empirical graph, accounting errors, and
any proposer-envelope violation. It also writes inspectable topology profiles
and a Markdown summary under `results/processed/`.
The checked-in profile uses `time_scale=0.5`; a four-run timing probe showed
that the earlier 0.02 acceleration starved 1,000-node path processing and
produced zero valid relay paths, while 0.5 restored valid paths for both BA
and `eth_empirical` graphs.

```bash
env TOKIO_WORKER_THREADS=32 \
  python scripts/task.py frozen-topology-scale-pilot
```

If all 1,000-node pilot runs complete but contain no valid organic relay path,
run the four-condition timing probe before repeating the matrix. It preserves
the logical workload but raises `time_scale` from 0.02 to 0.5 so Tokio has
enough wall-clock time to process forwarding, two-sided signatures, and path
aggregation before each proposal:

```bash
env TOKIO_WORKER_THREADS=32 \
  python scripts/task.py frozen-topology-scale-timing-probe
```

Every simulator run also writes `inclusion_samples.csv`. The security report
defines its post-warmup cohort by transaction creation slot, then uses the
included members of that cohort for pooled p50/p95/p99 latency and inclusion
ratio. This prevents transactions created during warmup but included afterward
from inflating the numerator. The report rejects duplicate cohort samples and
an inclusion ratio above one. It also reads the recorded revision from each
referenced `run_config.json` and rejects a matrix that mixes Git revisions. The
older `p95_inclusion_latency_s_mean` field is retained for compatibility but is
only the mean of per-epoch p95 values and is not the paper latency statistic.

`frozen_v1_devnet_pilot.yaml` and `frozen_v1_devnet_main.yaml` drive the formal
Kurtosis evaluation. They compare five variants with the same frozen profile:

- `baseline`: unmodified PoS path with no TopoStake evidence;
- `pathobs`: evidence and score observability with no fee or proposer bonus;
- `fee_only`: evidence, scoring, and relay-fee settlement with `eta=0`;
- `bonus_only`: evidence, scoring, and proposer bonus without fee settlement;
- `topostake`: the complete mechanism.

Run the 10-run pilot before starting the 75-run main matrix:

```bash
python scripts/task.py frozen-devnet-pilot \
  --package /home/wujian/ethereum-package \
  --resume --stop-on-failure

python scripts/task.py frozen-devnet-main \
  --package /home/wujian/ethereum-package \
  --resume
```

The pilot uses one seed, four nodes, a ring, and two offered loads. The main
matrix uses five seeds, eight nodes, a BA topology, and 8/32/64 transactions per
slot. Use `--seeds`, `--variants`, `--nodes`, `--loads`, or `--topologies` for a
comma-separated subset. `--dry-run` prints the exact matrix without launching
Kurtosis.

Each formal run must pass both the frozen-v1 protocol checks and a measurement
quality gate for SSZ block bytes, resource samples, Prometheus availability,
and inline-evidence verification timing. Per-run artifacts live under
`results/raw/<suite>/<run-id>/`; the suite manifest is
`experiment_manifest.json`, and the flat analysis table is written to
`results/processed/<suite>.csv`. Failed runs retain their artifacts and can be
repeated with `--resume` after the underlying issue is fixed.
The aggregate table includes `block_ssz_count` and `resource_samples` so every
block-size and resource result retains its measurement denominator.

After the main matrix completes, `frozen-devnet-figures` validates every row
and writes paired, seed-level 95% Student-t comparisons against baseline. Each
metric is exported as a separate PDF/PNG under
`figures/frozen_v1_devnet/`; the task also writes an inspectable figure-data
CSV, a compact LaTeX table, and a manifest. Before plotting, the task
reprocesses each run's `resources.jsonl`: it pairs Geth and Lighthouse by node
index, computes CPU, peak memory, and network traffic per node, and then uses
the run-level mean across nodes. Confidence intervals remain paired by seed;
the eight colocated nodes are not treated as independent repetitions.

The sustained-outage suite pairs Full TopoStake with the `eta=0` baseline
using the same seed-specific validator assignment. It evaluates random outage
groups at 10%, 20%, and 30% target stake on a 100-node BA network with Gini 0.1
and 64 transactions per slot. All conditions remain strictly below the
one-third finality threshold. The report audits
outage enforcement, silent relays, paired assignments, the `eta=0` stake
baseline, and proposer-weight-envelope compliance. The figure task writes
three independent, standard-aspect-ratio panels under
`figures/frozen_v1_sustained_outage/`: proposer share, missed slots, and the
post-outage proposer-share adaptation trace. The adaptation trace uses a
five-epoch trailing mean computed within each seed before its cross-seed 95%
interval. The missed-slot panel shows both absolute mechanisms and annotates
Full TopoStake's paired change from fee-only.
The report additionally derives the expected missed-slot rate from the
outage group's frozen proposer-weight share. This expectation removes finite
slot-lottery noise; the realized missed-slot rate remains the primary observed
outcome. Node-metric weights are aligned to their actual effective epoch, and
the relay-silence audit reports the asynchronous onset drain separately and
requires zero forwarding in every subsequent sustained-outage epoch.
The pilot uses five seeds; the main matrix uses twenty. Both use a 30-epoch
warm-up and a 100-epoch outage while retaining the frozen `eta=0.5` protocol
envelope.

## Frozen-v1 Devnet Acceptance

Run the dependency-free profile and golden-vector checks with:

```bash
python scripts/task.py frozen-devnet-check
```

After building the `topostake/geth:dev` and `topostake/lighthouse:dev` images,
run the sequential baseline, path-observation, and TopoStake Kurtosis smokes:

```bash
python scripts/task.py frozen-devnet-smoke --package /path/to/ethereum-package
```

On Windows, pass the native checkout path to `--package`. The runner generates
relay registries and Kurtosis args, runs a small ring workload in each mode,
waits for finality, validates each `summary.json`, and removes each enclave
unless `--keep-enclaves` is set. Use `--skip-existing` to validate already
collected artifacts without restarting Kurtosis.

Acceptance reports are written to
`results/processed/frozen_v1_devnet_*.json`; raw mode artifacts live under
`results/raw/frozen_v1_devnet/`.
Use the exact local client build and packaging commands documented in
`docs/FROZEN_V1_DEVNET.md`; Lighthouse must include the `spec-minimal` feature.

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
