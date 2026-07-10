建议 Codex 分四个阶段做，不要一次要求它重写整个仓库。

## Prompt 1：实现 revised protocol core

```text
Repository: wujian0327/TopoStake
Base branch: main

Create a new branch named revision-v2.

The current code implements the old Virtual Stake protocol. Replace the default TopoStake implementation with the revised real-stake-bounded protocol described below.

Before editing, inspect:
- src/consensus/topostake.rs
- src/consensus/mod.rs
- src/network/world_state.rs
- src/network/node.rs
- src/blockchain/path.rs
- src/blockchain/block.rs
- src/wallet/mod.rs
- src/main.rs

First create docs/REVISION_V2_PLAN.md containing:
1. current/new behavior mapping;
2. data-model changes;
3. epoch state-transition order;
4. migration risks;
5. planned tests.

Then implement the following.

A. Separate economic stake from spendable balance

The current code treats transaction balance and validator stake as the same value. Refactor this.

- Validator economic stake is fixed during an epoch.
- Transaction fees are deducted from account balance, not from economic stake.
- Relay and proposer rewards increase balance or pending rewards.
- Economic-stake changes, if enabled, may only be applied at epoch boundaries.
- Default experiments must keep the economic-stake snapshot fixed unless an explicit auto_compound option is enabled.
- Finality voting weight is always the normalized economic-stake snapshot.

B. Implement epoch-level revised TopoStake

Add a TopoStakeConfig with:
- initial_depth
- beta
- saturation_k
- eta
- bonus_cap
- proposer_fee_ratio
- reward_settlement_depth

Validate:
- initial_depth >= 1
- 0 < beta <= 1
- saturation_k > 0
- 0 <= proposer_fee_ratio < 1
- eta >= 0
- bonus_cap >= 0
- eta * bonus_cap <= 0.5

The revised protocol uses the following formulas.

For path length m >= 2:

lambda = (2D + 1) / (3D + 1)
r = D / (2D + 1)
B(m) = min(1, D/m) * lambda^(m-1)
alpha(k,m) = (1-r) * r^(k-1) / (1-r^(m-1))
gamma(k,p) = B(m) * alpha(k,m)

Only intermediate relayers receive gamma.

At the end of epoch e:

A_i(e) = sum of gamma for eligible finalized paths containing validator i

C_i(e) =
S_hat_i(e) * ln(1 + A_i(e) / (K * S_hat_i(e)))

Score_i(e) =
beta * C_i(e) + (1-beta) * Score_i(e-1)

Normalize Score_i(e) to C_hat_i(e).

Epoch e-1 propagation affects epoch e proposer selection:

bonus_i(e) =
min(bonus_cap, max(C_hat_i(e-1) / S_hat_i(e) - 1, 0))

W_i(e) =
S_hat_i(e) * (1 + eta * bonus_i(e))

Normalize W_i(e) for proposer election.

Do not update scores inside select_proposer().
The proposer weights must be frozen for the full epoch.

C. Implement path-level rewards

For transaction fee f and proposer ratio theta:

proposer receives theta * f plus the base reward.

Intermediate relay i receives:

(1-theta) * f * gamma(i,p)

The sum of relay rewards must not exceed (1-theta)*f.
Burn the undistributed relay budget.
Do not distribute relay fees according to global score or proposer weight.

Rewards should be placed in a pending settlement queue and applied after reward_settlement_depth canonical blocks. This is only a simulator finality abstraction; do not claim it simulates BFT voting.

D. Commit path metadata in the block

The current block header commits only to transaction hashes.

Add either:
- a path_root, or
- a combined body_root over transaction hashes and serialized path records.

Changing any path record after block construction must invalidate the body commitment.

Split block checks into:
- base block/transaction validity;
- path-evidence validity.

Invalid or missing path evidence gives zero reward and zero score, but does not invalidate an otherwise valid base transaction or halt the base PoS chain.

E. Tests

Add unit/property tests for:
- path budget sums to B(m) and B(m) <= 1;
- B(m) decreases with m;
- lambda * (1+r) == 1 within tolerance;
- epoch e score does not affect epoch e proposer election;
- W_i <= (1 + eta*bonus_cap) * S_hat_i;
- coalition proposer-weight bound;
- fee-budget balance;
- balance changes do not alter the current epoch stake snapshot;

Run:
cargo fmt --check
cargo check
cargo test

Do not fabricate experiment results.
At the end, summarize changed files, unresolved assumptions, and commands run.
```

---

## Prompt 2：实现双向路径证明

```text
Continue on branch revision-v2.

Implement the revised two-sided, prefix-bound path evidence.

The current src/blockchain/path.rs signs only H(tx) || H(next). Replace it with the revised TopoStake path representation.

Protocol requirements:

For transaction tx in epoch e and path v0,...,vm:

c0 = H(H(tx) || e || H(v0))
ci = H(c_{i-1} || H(vi)) for i > 0

For edge (vi, v{i+1}):

Mi = ci || H(vi) || H(v{i+1})

The sender vi signs Mi.
The receiver v{i+1} also signs Mi.

A valid hop requires both signatures.

Implementation guidance:
- An edge-centric in-memory representation is acceptable if it is simpler.
- A pending outgoing hop may initially have only the sender signature.
- The receiver verifies the prefix and sender signature, adds its receiver signature, and may append a new outgoing hop.
- A finalized block path must contain only completed hops.
- The block-level record should store one aggregate signature plus the non-proposer validator sequence.
- The proposer identity comes from the block header.
- Reject repeated validator identities.
- Bind every proof to the epoch to prevent cross-epoch replay.
- Maintain a receipt-commitment cache keyed by (transaction_hash, epoch).
- A validator may forward to multiple peers, but it may create at most one reward-eligible receiving proof for the same transaction and epoch.
- Multiple outgoing sender proofs are allowed.
- Two conflicting receiving proofs must be detectable as public equivocation evidence.

BLS requirements:
- Aggregate all sender and receiver signatures.
- An m-hop path has 2m signer-message pairs.
- Add proof-of-possession verification when registering BLS relay keys, or clearly isolate a trusted registry abstraction if the blst API makes a full PoP implementation impractical.
- Do not silently accept unregistered keys.

Block behavior:
- A proposer may select at most one eligible path per transaction.
- Honest selection may prefer the shortest locally available eligible path with deterministic tie-breaking.
- Do not claim or implement a global fastest-path oracle.
- Fully colluding paths may still be syntactically valid; the scoring budget limits their effect.

Add tests for:
- valid two-sided path;
- missing receiver signature;
- modified transaction;
- modified epoch;
- reordered node;
- removed node;
- repeated identity;
- conflicting receipts;
- aggregate verification with repeated messages and different public keys;
- direct originator-to-proposer path;
- proposer-generated transaction.

Add Criterion benchmarks in benches/bls_path.rs for:
- sender sign;
- receiver sign;
- aggregation;
- aggregate verification;
- path lengths 1, 2, 4, 8, and 16.

Update Cargo.toml as needed.

Run cargo fmt, cargo check, cargo test, and the benchmark in quick mode.
Document the path format in docs/PATH_EVIDENCE.md.
```

---

## Prompt 3：增加攻击模型、指标和可重复性

```text
Continue on branch revision-v2.

Upgrade the simulator so that the revised paper experiments are reproducible and expose the security-relevant metrics.

A. Reproducibility

Introduce a SimulationConfig rather than continuing to expand long positional function argument lists.

Add independent CLI seeds:
- graph_seed
- wallet_seed
- workload_seed
- election_seed
- failure_seed
- attack_seed

Remove thread_rng() from experiment-critical paths.
Use seeded StdRng instances.

The ER, BA, and WS topology generators must all use graph_seed.
The Poisson transaction workload must use workload_seed.
Failure/churn decisions must use failure_seed.
Election sampling must use election_seed.

Add --run-id and write the full resolved configuration and git commit SHA to every output directory.

B. Logical-time metrics

Do not compute throughput from wall-clock timestamps or Tokio scheduler timing.

Use logical simulation time based on slot duration and event timestamps.
Add an optional --time-scale parameter that scales real sleeps without changing logical metrics.

Keep real-time mode available, but use accelerated logical-time mode for paper experiments.

C. Metrics

Write:
- run_config.json
- epoch_metrics.csv
- node_epoch_metrics.csv
- run_summary.json
- optional slot_metrics.csv

epoch_metrics.csv should include:
- epoch
- generated_tx
- included_tx
- throughput
- p50/p95/p99 inclusion latency
- block success ratio
- average/p95 path length
- valid and invalid path counts
- conflicting receipt count
- total proposer reward
- total relay reward
- burned relay fee
- stake Gini and HHI
- proposer-weight Gini and HHI
- adversary real-stake share
- adversary score share
- adversary proposer-weight share
- theoretical proposer-weight bound
- observed adversary proposer share
- bound violation flag

node_epoch_metrics.csv should include:
- validator id
- adversarial flag
- economic stake
- balance
- raw contribution
- saturated contribution
- EMA score
- normalized score
- bonus
- unnormalized and normalized proposer weight
- proposer count
- relay reward
- proposer reward
- fee spent
- net income
- degree and optional betweenness

D. Attack selection and behavior

Add:
--adversary-stake-fraction
--adversary-placement random|high-degree|high-betweenness
--attack-mode none|max-score|path-padding|flooding
--padding-identities
--attack-tx-rate-multiplier

Select corrupted validators after topology construction.
For high-degree placement, sort by degree and select validators until the target real-stake fraction is reached.
For high-betweenness placement, calculate betweenness centrally during setup.

max-score attackers relay aggressively and use low forwarding delay but do not forge honest signatures.

path-padding attackers replace one controlled relay position with consecutive controlled identities that share a fixed total stake.

flooding attackers generate additional self-funded transactions.
Track their fee spending, returned proposer/relay fees, and net profit.

Preserve the existing unstable-node mode and expose unstable fraction and offline probability cleanly.

E. Tests

Add deterministic tests proving:
- the same configuration and seeds generate the same graph, workload summary, and proposer-weight sequence;
- adversary real-stake selection is within a documented tolerance;
- no revised TopoStake epoch violates the theoretical proposer-weight bound;
- transaction flooding accounting includes fee spending;
- path-padding identities have fixed total economic stake.

Run formatting, checks, and tests.
Update README.md with all new CLI options and output schemas.
```

---

## Prompt 4：自动运行实验和画图

```text
Continue on branch revision-v2.

Create a reproducible paper-experiment pipeline. Do not hard-code measured values in plotting scripts.

Directory structure:

experiments/
  configs/
  run_experiments.py
  summarize.py
  README.md

analysis/
  plot_performance.py
  plot_crypto_overhead.py
  plot_fairness.py
  plot_weight_bound.py
  plot_padding_flooding.py
  plot_churn.py

results/
  raw/
  processed/

figures/

Use YAML experiment specifications and subprocess execution.
Support:
- multiple seeds;
- resume after interruption;
- bounded parallelism;
- per-run timeout;
- failed-run log;
- automatic collection of run_config.json and run_summary.json.

Use five paired seeds for all protocol comparisons.
Compute mean and 95% confidence intervals.
Never use broken axes.
Do not set a narrow y-range solely to magnify differences.
Every figure must be generated only from raw CSV/JSON outputs.

Implement these experiment groups.

1. performance_load
- protocols: pos, topostake
- N = 100
- topology = ba
- tx_rate = [25, 50, 100, 150, 200]

2. performance_scale
- protocols: pos, topostake
- N = [50, 100, 200, 300]
- topology = ba
- tx_rate = 100

3. topology_robustness
- protocols: pos, topostake
- topology = [ba, er, ws]
- N = 100
- tx_rate = 100

4. reward_fairness
- protocols: pos, topostake with eta=0, full topostake
- stake_gini = [0.2, 0.6, 0.8]
- independent relay profiles: active, normal, lazy
- report contribution/reward correlation, low-stake active-relayer income uplift, reward Gini, and proposer uplift

5. real_stake_bound
- protocols: topostake
- adversary_stake_fraction = [0.05, 0.10, 0.20, 0.30]
- adversary_placement = [random, high-degree]
- revised settings eta*bonus_cap = [0.25, 0.5]
- plot adversary proposer-weight share against the theoretical bound

6. path_padding
- padding identities = [0, 1, 2, 4, 8, 16]
- D = [2, 4, 8]
- report coalition credit ratio, reward ratio, score ratio, and proposer-weight ratio

7. transaction_flooding
- attack tx multiplier = [0, 0.5, 1, 2, 5]
- adversary stake = 0.10
- report fee spent, fee recovered, net profit, score, proposer weight, and normal-user p95 latency

8. churn_appendix
- unstable fraction = [0, 0.1, 0.3, 0.5]
- offline probability = 0.5
- report throughput, p95 latency, propagation coverage, and successful-slot ratio

Default revised TopoStake parameters:
- initial D = 4
- beta = 0.2
- K = 1.0
- theta = 0.7
- eta = 0.5
- bonus cap = 1.0
- eta * bonus cap = 0.5
- 20 slots per epoch
- 80 epochs
- ignore the first 10 epochs as warm-up
- max transactions per block = 250

Add Makefile targets:
- make test
- make bench
- make experiments-smoke
- make experiments-main
- make figures

experiments-smoke must finish quickly and validate the complete pipeline with reduced sizes.

Add a manuscript-ready summary file:
results/processed/paper_summary.md

It should list each experiment, exact parameters, number of successful runs, and the source CSV files. It must not invent conclusions when results are missing.

Run the smoke pipeline and fix all failures.
```

---

## 最后建议

先让 Codex完成 Prompt 1，并检查：

- balance 与 stake 是否真正分离；
- score 是否只在 epoch 边界更新；
- proposer weight 是否冻结一整个 epoch；
- reward 是否按 (\gamma)；
- path metadata 是否进入 block commitment。

这五项没稳定之前，不要开始批量实验。否则生成的数据仍然属于旧协议，后面论文和代码会再次对不上。
