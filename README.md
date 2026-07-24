# TopoStake

TopoStake is a research artifact for studying propagation incentives whose
effect on Proof-of-Stake proposer selection remains bounded by real economic
stake. The repository contains:

- a Rust event-driven simulator and the frozen-v1 protocol implementation;
- reproducible experiment matrices, acceptance checks, reports, and plotting
  scripts;
- modified Geth and Lighthouse clients for the real-client Ethereum devnet;
- Kurtosis-based devnet runners and resource/evidence measurement tooling.

The paper experiments use the frozen-v1 configurations under
`experiments/configs/`. Each run records its resolved configuration, independent
random seeds, and Git revision.

## Reproducing the Experiments

### 1. Environment

Clone the experiment branch and enter the repository:

```bash
git clone -b codex/frozen-v1-security-eval \
  https://github.com/wujian0327/TopoStake.git
cd TopoStake
```

The simulator requires a stable Rust toolchain and Python 3.10 or newer. The
report and figure scripts use Matplotlib, NumPy, PyYAML, Requests, and Web3.py.

```bash
rustup update stable
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install matplotlib numpy pyyaml requests web3
cargo build --release
```

Run the repository checks before starting an experiment:

```bash
python scripts/task.py test
python scripts/task.py frozen-smoke
```

All commands below run from the repository root. Add `--dry-run` to a formal
matrix command to inspect its exact runs without launching them. Existing
complete simulator runs are reused unless `--force` is supplied.

### 2. Simulator Security Experiments

Run the smaller pilot first, followed by the formal 20-seed matrix:

```bash
python scripts/task.py frozen-security-pilot
python scripts/task.py frozen-security-main --dry-run
python scripts/task.py frozen-security-main
python scripts/task.py frozen-security-figures
```

The security workflow covers path padding, proposer-influence bounds, flooding
economics, score-floor sensitivity, and relay-participation stress. It also
runs the exhaustive fixed-path padding check. The two standalone security
microbenchmarks can be reproduced with:

```bash
python scripts/task.py frozen-padding-check
python scripts/task.py frozen-evidence-bench
```

### 3. Long-Horizon Fee and Proposer-Bonus Experiment

```bash
python scripts/task.py frozen-fee-bonus-pilot
python scripts/task.py frozen-fee-bonus-main --dry-run
python scripts/task.py frozen-fee-bonus-main
```

To regenerate the main figures without rerunning the matrix:

```bash
python scripts/task.py frozen-fee-bonus-report \
  --config experiments/configs/frozen_v1_fee_bonus_main.yaml
python scripts/task.py frozen-fee-bonus-figures \
  --config experiments/configs/frozen_v1_fee_bonus_main.yaml
```

The report recomputes both identity-weighted and stake-weighted realized
reward premiums from the existing per-validator metrics.  It also converts
the frozen proposer weights into an expected reward-per-stake premium.  These
steps only reprocess existing raw outputs; they do not rerun the simulator.

The reduced-form endogenous-participation pilot consumes the paired RQ2 CSV;
it does not rerun Rust:

```bash
python scripts/task.py frozen-endogenous-participation-pilot
```

It reconstructs fee-only and Full expected break-even benefit curves, solves
the heterogeneous-cost mean-field fixed point, bootstraps paired seeds, and
checks cost, interpolation, and initialization sensitivity. Its `GO` result
only decides whether a dynamic Rust-agent experiment is worth implementing;
it is not an equilibrium or real-validator participation claim.

The history-only Rust adaptive-agent pilot then tests the endogenous chain
inside the event-driven simulator:

```bash
python scripts/task.py frozen-adaptive-participation-pilot
```

Each validator receives a paired, fixed heterogeneous relay cost. Every five
completed epochs, a seeded subset may switch between Lazy (`p=0.25`) and
Active (`p=1`) using an EMA of the preceding windows' public active-minus-lazy
expected reward per extra forward; 5% of reconsidering validators instead
try the opposite strategy to preserve observable counterfactuals. The
decision never reads future proposer draws. The second-stage pilot sweeps
`1x`, `2x`, and `3x` cost-median regimes
over 100 epochs, comparing PoS, fee-only, and Full TopoStake from 25%, 50%,
and 75% initial active fractions. Generated transactions are tracked as a
fixed-follow-up cohort, so unfinished transactions affect both the inclusion
rate and restricted mean time to inclusion. Missing Active/Lazy
counterfactuals are reported as unavailable rather than accounting errors,
and acceptance checks coverage separately for fee-only and Full TopoStake.
Post-adaptation stability uses first-half versus second-half mean drift rather
than a tail maximum. The report writes three independent figure files.

After pilot development, run the frozen holdout and the separate behavioral
parameter sensitivity check:

```bash
python scripts/task.py frozen-adaptive-participation-main --dry-run
python scripts/task.py frozen-adaptive-participation-main
python scripts/task.py frozen-adaptive-participation-sensitivity --dry-run
python scripts/task.py frozen-adaptive-participation-sensitivity
```

The holdout uses 20 paired seeds disjoint from the pilot seeds, fixes the
initial active-stake share at 50%, and compares Fee-only with Full TopoStake
at `1x`, `2x`, and `3x` median relay cost. A single `2x` PoS condition provides
the no-incentive reference without redundantly repeating it across cost
labels. The frozen acceptance rule requires a positive paired 95% confidence
lower bound at `3x` and at least one lower-cost regime; it evaluates
finite-horizon response rather than equilibrium convergence. The sensitivity
suite uses separate seeds and changes one behavioral parameter at a time.

Before a full rerun, the 24-run stability probe tests the representative and
previously least stable conditions with slower updates, stronger smoothing,
and a 300-epoch horizon whose post-adaptation analysis begins at epoch 200:

```bash
python scripts/task.py frozen-adaptive-participation-stability-probe
```

Its gate uses seed-averaged condition drift and the 90th percentile of
per-run drift; the single worst run remains diagnostic.

### 4. Organic-Traffic Capture Experiment

```bash
python scripts/task.py frozen-organic-capture-pilot
python scripts/task.py frozen-organic-capture-main --dry-run
python scripts/task.py frozen-organic-capture-main
```

To regenerate the main report and figures:

```bash
python scripts/task.py frozen-organic-capture-report \
  --config experiments/configs/frozen_v1_organic_capture_main.yaml
python scripts/task.py frozen-organic-capture-figures \
  --config experiments/configs/frozen_v1_organic_capture_main.yaml
```

### 5. Long-Term Reward Reinvestment

The RQ3 upper-bound compounding stress test keeps the organic-capture network
parameters, reinvests 100% of proposer and relay rewards, and compares paired
PoS, fee-only, and full TopoStake trajectories:

```bash
python scripts/task.py frozen-reinvestment-gini-pilot
python scripts/task.py frozen-reinvestment-gini-main --dry-run
python scripts/task.py frozen-reinvestment-gini-main
```

To regenerate its report and three-line stake-Gini figure without rerunning:

```bash
python scripts/task.py frozen-reinvestment-gini-report
python scripts/task.py frozen-reinvestment-gini-figures
```

### 6. Sustained-Outage Experiment

```bash
python scripts/task.py frozen-sustained-outage-pilot
python scripts/task.py frozen-sustained-outage-eta-pilot --dry-run
python scripts/task.py frozen-sustained-outage-eta-pilot
python scripts/task.py frozen-sustained-outage-main --dry-run
python scripts/task.py frozen-sustained-outage-main
```

The main report and the three independent outage figures can be regenerated
from existing results with:

```bash
python scripts/task.py frozen-sustained-outage-report
python scripts/task.py frozen-sustained-outage-figures
```

The main RQ5 matrix compares fee-only, the conservative full setting
`eta=0.5`, and the largest admissible setting `eta=1` at 10%, 20%, and 30%
outage stake. Existing fee-only and `eta=0.5` runs are reused, so extending a
completed main suite materializes only the 60 new `eta=1` runs. The adaptation
panel uses the representative 20% outage target, while the steady-weight and
missed-slot panels retain all three targets.

The optional eta pilot holds the outage target at 20% stake and compares
`eta={0,0.25,0.5,0.75,1}` over five paired seeds. It writes a separate
expected-versus-realized missed-slot reduction figure without replacing the
main RQ5 artifacts.

### 7. Real-Client Ethereum Devnet

The devnet additionally requires Docker, the Kurtosis CLI, and a local checkout
of `ethereum-package`. Build the modified clients and package their images:

```bash
cd ethereum-topostake/go-ethereum-topostake
make geth
cd ../..
GETH_BINARY="$PWD/ethereum-topostake/go-ethereum-topostake/build/bin/geth" \
  ./scripts/geth_image.sh package-local

cd ethereum-topostake/lighthouse
cargo build --release -p lighthouse --features spec-minimal
cd ../..
LIGHTHOUSE_BINARY="$PWD/ethereum-topostake/lighthouse/target/release/lighthouse" \
  ./scripts/lighthouse_image.sh package-local
```

Validate the frozen profile, inspect the matrices, and then run the pilot and
formal devnet experiments:

```bash
python scripts/task.py frozen-devnet-check
python scripts/task.py frozen-devnet-pilot \
  --package /path/to/ethereum-package --dry-run
python scripts/task.py frozen-devnet-pilot \
  --package /path/to/ethereum-package --resume --stop-on-failure
python scripts/task.py frozen-devnet-main \
  --package /path/to/ethereum-package --dry-run
python scripts/task.py frozen-devnet-main \
  --package /path/to/ethereum-package --resume
python scripts/task.py frozen-devnet-figures
```

The formal matrix compares unmodified PoS, path observation, fee-only,
bonus-only, and full TopoStake. Detailed client-build, evidence, activation,
and acceptance semantics are documented in `docs/FROZEN_V1_DEVNET.md`.

### 7. Outputs and Replotting

Simulator and devnet artifacts follow the same layout:

- `results/raw/<suite>/`: per-run configurations, logs, metrics, and summaries;
- `results/processed/`: grouped tables, paired comparisons, quality gates, and
  report summaries;
- `figures/`: generated PDF and PNG paper figures.

Report and figure tasks do not rerun completed simulations. Use the
suite-specific commands above when regenerating figures; `paper-figures` only
replots the generic and sustained-outage panels whose required processed data
are already present.

For long simulator matrices on a multicore server, the Tokio worker pool can
be bounded explicitly, for example:

```bash
env TOKIO_WORKER_THREADS=32 \
  python scripts/task.py frozen-security-main
```
