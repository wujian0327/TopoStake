# TopoStake Rust Simulator

## How to Run

### Install Rust

Windows:

https://www.rust-lang.org/tools/install

Linux/macOS:

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
```


### Run a Simulation

Use release mode for normal experiments:

```bash
cargo run --release -- -n 100 -t 10 -c pos
```

TopoStake example:

```bash
cargo run --release -- -n 100 -t 100 -c topostake -g 0.6 --base-reward 1.0 --slot-duration 2 --transaction-fee 0.00001 --max-tx-per-block 250 --run-id seed0
```

PoW example:

```bash
cargo run --release -- -n 100 -t 10 -c pow --pow-difficulty 20 --pow-max-threads 2
```

Minotaur example:

```bash
cargo run --release -- -n 100 -t 10 -c minotaur
```

## Common Options

- `-n, --node-num`: number of nodes, default `20`
- `-t, --trans-num`: transactions per second, default `10`
- `-c, --consensus`: consensus algorithm, one of `pos`, `topostake`, `pow`, `minotaur`
- `--topology`: network topology, one of `er`, `ba`, `ws`, default `ba`
- `-g, --gini`: initial Gini coefficient, default `0.6`
- `--slot-duration`: slot duration in seconds, default `2`
- `--slot-per-epoch`: number of slots per epoch, default `5`
- `--max-epochs`: maximum number of epochs to run, default `100`
- `--metrics-prefix`: retained for compatibility in `run_config.json`; file locations are controlled by `--output-dir`
- `--run-id`: stable run identifier, default `run-<timestamp>`
- `--output-dir`: output directory, default `results/<run-id>`
- `--graph-seed`, `--wallet-seed`, `--workload-seed`, `--election-seed`, `--failure-seed`, `--attack-seed`: independent seeds for topology, addresses/stake shuffle, Poisson workload, proposer sampling, churn, and attacks
- `--time-scale`: scales real sleeps without changing logical metrics, default `1.0`
- `--real-time`: use wall-clock slot sleeps instead of accelerated scaled sleeps
- `--unstable-fraction`, `--offline-probability`: unstable-node experiment controls
- `--adversary-stake-fraction`: target corrupted real-stake share
- `--adversary-placement`: `random`, `high-degree`, or `high-betweenness`
- `--attack-mode`: `none`, `max-score`, `path-padding`, or `flooding`
- `--padding-identities`: controlled identities for path-padding experiments
- `--attack-tx-rate-multiplier`: extra adversarial transaction rate for flooding

## Output Files

Each run writes `output.log` in the project root and a reproducibility bundle to `<output-dir>`:

- `run_config.json`: full resolved `SimulationConfig` plus git commit SHA
- `graph.json`: generated network topology
- `slot_metrics_*.csv`: optional slot-level metrics
- `epoch_metrics.csv`: epoch-level logical-time/security metrics
- `node_epoch_metrics.csv`: per-validator stake, score, reward, fee, and topology metrics
- `run_summary.json`: final generated/included transaction counts, block success/failure counts, and adversary net income

`epoch_metrics.csv` includes generated/included transactions, logical throughput, p50/p95/p99 inclusion latency, block success ratio, path length and validity counts, conflicting receipt count, proposer/relay/burned rewards, stake and proposer-weight Gini/HHI, adversary stake/score/weight shares, theoretical proposer-weight bound, observed adversary proposer share, and a bound-violation flag.

`node_epoch_metrics.csv` includes validator id, adversarial flag, economic stake, balance, raw/saturated contribution, EMA and normalized score, bonus, proposer weights, proposer count, relay/proposer reward, fee spent, net income, degree, and betweenness.

## Paper Experiment Pipeline

The reproducible paper pipeline lives under `experiments/` and `analysis/`.

Use the cross-platform Python runner on Windows, Linux, or macOS:

- `python scripts/task.py test`: formatting, check, and unit tests
- `python scripts/task.py bench`: quick BLS path benchmark
- `python scripts/task.py experiments-smoke`: reduced end-to-end pipeline
- `python scripts/task.py experiments-main`: full paper experiment matrix
- `python scripts/task.py figures`: regenerate SVG figures from processed/raw outputs

The Makefile provides the same targets for environments that already have
`make` installed.

Raw outputs are written under `results/raw/<suite>/`, processed tables under
`results/processed/`, and figures under `figures/`.
