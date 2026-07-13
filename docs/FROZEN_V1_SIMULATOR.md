# Frozen-v1 simulator semantics

This document records the Rust simulator semantics that correspond to the
frozen algorithm in the TDSC manuscript. The machine-readable defaults are in
`experiments/configs/protocol_frozen_v1.yaml` and cross-implementation vectors
are in `experiments/golden/frozen_v1_vectors.yaml`.

## Implemented in the first migration stage

- The path target depth `D` is fixed. The previous median-based adaptive
  controller is not part of frozen-v1.
- A transaction carries a distributable `fee` and a distinct
  `irrecoverable_cost`. Long-term contribution uses
  `q(tx) = min(1, irrecoverable_cost / score_cost_reference)`.
- Raw contribution is `q(tx) * gamma`, followed by the stake-scaled logarithmic
  saturation and EMA defined in the paper.
- Score mass is damped by `kappa + sum(active scores)` over the active validator
  set. It is intentionally not normalized to sum to one.
- The proposer bonus is `b_max * x / (zeta + x)`, where
  `x = damped_score / normalized_stake`.
- A produced score root enters a pending queue. It changes proposer weights only
  after `score_activation_delay_epochs`; the current frozen weights are not
  mutated by an unactivated update.
- Metrics expose both the score-dependent proposer bound and the tight
  score-independent envelope.

The simulator has no probabilistic finality gadget. Its activation queue models
the manuscript rule under the explicit assumption that a canonical epoch root
is finalized by the configured activation epoch. Activation stalls and explicit
challenge processing are follow-up state-machine work, not silently simulated
by this first stage.

## Cost convention

`Transaction::with_fee` currently creates an equal-size distributable fee and
irrecoverable cost. The originator therefore pays twice the supplied
`transaction_fee`: one part is split by `theta`, and one part backs score and is
burned. Experiments that need unequal values should construct transactions with
`Transaction::with_costs` after the workload generator receives separate CLI
parameters in the next migration stage.

## Compatibility

The experiment runner maps the legacy key `topostake_initial_depth` to
`topostake_target_depth`, but labels old suites as protocol version `legacy`.
Final paper experiments must use a suite that explicitly declares
`"protocol_version": "frozen-v1"`.

## Verification

Run:

```bash
cargo fmt --check
cargo check
cargo test
python scripts/task.py frozen-smoke
```

The frozen smoke profile is intentionally small and is not paper evidence.

## Formal security evaluation

The security evaluation is separate from the Kurtosis performance matrix. It
uses paired deterministic seeds for path padding, proposer influence, flooding,
score-floor sensitivity, and relay participation. Run the small gate first:

```bash
python scripts/task.py frozen-security-pilot
```

After it passes, launch the 20-seed matrix (1340 resumable runs):

```bash
python scripts/task.py frozen-security-main
```

Use `--dry-run` to print either matrix without executing it. The report checks
the score-dependent and score-independent proposer bounds for every measured
epoch. It reports stochastic outcomes as across-seed means and paired 95%
confidence intervals; finite-slot proposer counts are not treated as a
deterministic safety condition. A partial report can be generated while jobs
are running with:

```bash
python scripts/task.py frozen-security-report \
  --config experiments/configs/frozen_v1_security_main.yaml \
  --allow-incomplete
```

The legacy CSV field `invalid_path_count` means **credit-ineligible path
evidence**, not an invalid transaction or an accepted security violation. In
particular, evidence tagged with an earlier epoch is counted there when its
transaction crosses an epoch boundary. The transaction remains valid, while
the shared eligibility predicate excludes that path from relay reward and
score. The report therefore checks `valid + ineligible == included_tx` and
retains the ineligible count as a descriptive measurement.

The network-level padding sweep is named `path_padding_end_to_end`: it allows
propagation timing and first-path selection to change and is therefore a stress
test, not a direct replay of Theorem 4. `frozen-padding-check` separately holds
the path fixed, replaces one coalition-controlled relay with consecutive
identities, exhaustively enumerates all other coalition relay positions up to
`M_max=16`, and checks that coalition credit never increases:

```bash
python scripts/task.py frozen-padding-check
```

## Frozen-v1 paper figures

After `frozen-security-report` has refreshed the processed run and paired CSVs,
generate all security figures with:

```bash
python scripts/task.py frozen-security-figures
```

The command writes PDF and PNG versions plus
`figures/frozen_v1_security/figure_manifest.json`. The plotting code accepts a
partial matrix while long runs are in progress, but labels figures with fewer
than 20 seeds as preliminary. Re-run the same command after all seeds complete;
no plotting-code or input-path change is required. Relay-participation figures
use focal-relayer metrics, while network-wide lazy-relay latency is reported in
a separate stress figure. End-to-end padding stress is also kept distinct from
the fixed-path non-amplification check.

The score-floor sweep crosses `kappa = {0.1, 1, 10}` with low-to-normal offered
loads. This is intentional: at high score mass, changing `kappa` has little
effect and does not test the startup/idle small-denominator case.

The primary participation experiment uses one deterministic focal relayer.
All other validators remain `normal`, the offered load is below block capacity,
and active/normal/lazy correspond to forwarding probabilities 1.0/0.75/0.25.
All three strategies use the same topology-derived link delay. A separate
`relay_network_stress` experiment retains the all-active versus all-lazy
comparison, but it is interpreted only as network-wide participation collapse,
not as a TopoStake latency improvement. Transaction-level records in
`inclusion_samples.csv` provide pooled latency quantiles and sample coverage;
the report does not use a mean of epoch-level p95 values as its primary latency.
