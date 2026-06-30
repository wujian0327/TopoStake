## 7. 可以让 Codex 修改代码的提示词

下面这些提示词可以直接给 Codex。建议先做第 1、2、4、5 条，不要一开始让 Codex 大改核心协议。

### Prompt 1：新增一套快速投稿实验配置

```text
You are working on the revision-v2 branch of the TopoStake Rust simulator.

Add a new experiment configuration file:
experiments/configs/tdsc_fast.yaml

Goal: produce a compact but publication-ready evaluation matrix for the TopoStake paper.

Requirements:
1. Keep the existing main.yaml unchanged.
2. Use deterministic seeds [0, 1, 2].
3. Use a default node count of 100, BA topology, tx_rate 100, stake_gini 0.6, initial_depth 4, beta 0.2, eta 0.5, bonus_cap 1.0, proposer_fee_ratio 0.7.
4. Reduce runtime compared with main.yaml: use fewer epochs, a warmup period, and smaller scale sweeps where necessary.
5. Include the following experiments:
   - performance_load: protocols [pos, topostake], tx_rate [25, 50, 100, 150, 200].
   - performance_scale: protocols [pos, topostake], node_num [50, 100, 200].
   - real_stake_bound: protocol topostake, adversary_fraction [0.05, 0.10, 0.20, 0.30], adversary_placement [random, high-degree, high-betweenness], eta_bonus_product [0.25, 0.5].
   - path_padding: protocol topostake, padding_identities [0, 1, 2, 4, 8, 16], initial_depth [2, 4, 8].
   - transaction_flooding: protocol topostake, flooding_multiplier [0, 0.5, 1, 2, 5].
   - reward_fairness: protocols [pos, topostake_eta0, topostake], stake_gini [0.2, 0.6, 0.8].
   - churn_appendix: protocols [pos, topostake], unstable_fraction [0, 0.1, 0.3, 0.5].
6. Add a short README section explaining that tdsc_fast.yaml is intended for paper figures and main.yaml is intended for extended experiments.
7. Ensure scripts/task.py can run this config via:
   python scripts/task.py tdsc-fast
8. The runner should skip completed runs, continue after failed runs, and record failures in a machine-readable summary.
```

------

### Prompt 2：补 high-betweenness adversary placement

```text
The README exposes adversary placement options including high-betweenness, but the paper experiment config currently only uses random and high-degree.

Please implement or verify support for adversary_placement=high-betweenness.

Requirements:
1. Compute betweenness centrality from the generated network graph.
2. Select adversarial validators in descending betweenness order until the requested adversary real-stake fraction is reached or exceeded.
3. Keep random and high-degree behavior unchanged.
4. Export the selected adversarial node IDs and their total real stake share to run_config.json and epoch_metrics.csv.
5. Add unit tests or a small integration test verifying that high-betweenness placement selects nodes with higher average betweenness than random placement on the same graph and seed.
6. Add high-betweenness to tdsc_fast.yaml under the real_stake_bound experiment.
```

------

### Prompt 3：补图级 topology metrics

```text
Add graph-level topology metrics for the TopoStake evaluation.

Metrics to compute:
1. number of nodes
2. number of edges
3. average degree
4. degree Gini
5. average shortest path length on the largest connected component
6. effective diameter or p90 shortest-path distance
7. largest connected component ratio
8. average clustering coefficient
9. betweenness Gini
10. maximum betweenness

Requirements:
1. Export these metrics to graph_metrics.csv for every run.
2. If the graph is static, compute them once per run.
3. If the simulator supports peer adaptation over epochs, also export per-epoch graph metrics.
4. Add analysis/plot_topology_metrics.py to generate:
   - average shortest path by topology
   - effective diameter by topology
   - degree Gini and betweenness Gini by topology
5. Ensure the script works even if some metrics are missing by printing clear warnings instead of crashing.
```

------

### Prompt 4：把 BLS benchmark 结果输出成论文表格

```text
Improve the BLS benchmark pipeline for the TopoStake paper.

Current code has Criterion benchmarks for sender signing, receiver signing, aggregation, and aggregate verification. Please add a script that extracts the benchmark estimates and writes:

results/processed/bls_bench.csv

Columns:
- operation
- path_length
- mean_ns
- median_ns if available
- stddev_ns or ci_low_ns/ci_high_ns if available
- samples
- benchmark_profile

Operations:
- sender_sign
- receiver_sign
- aggregate
- aggregate_verify

Path lengths:
1, 2, 4, 8, 16

Also generate:
1. results/processed/bls_bench_table.tex
2. figures/crypto_overhead.pdf

The LaTeX table should be compact and suitable for an IEEE two-column paper.
Do not change the cryptographic implementation.
```

------

### Prompt 5：补 reward-rule ablation

```text
Add reward-rule ablation support to TopoStake.

Add a CLI/config option:
--reward-rule {log_stake, linear, sqrt, hard_cap}

Default must remain log_stake.

Definitions:
1. log_stake: existing TopoStake rule
   C_i = s_i * ln(1 + A_i / (K s_i))
2. linear:
   C_i = A_i
3. sqrt:
   C_i = sqrt(A_i)
4. hard_cap:
   C_i = min(A_i, cap_value * s_i)

Requirements:
1. Preserve all existing behavior when reward_rule is not specified.
2. Export reward_rule to run_config.json and epoch_metrics.csv.
3. Add an experiment reward_ablation to tdsc_fast.yaml:
   reward_rule [linear, sqrt, hard_cap, log_stake]
   adversary_fraction [0.1, 0.2]
   adversary_placement [random, high-degree]
4. Add plots comparing:
   - adversary proposer weight share
   - reward Gini
   - score Gini
   - bound violation rate
5. Add tests verifying that log_stake matches the existing implementation.
```

------

### Prompt 6：让运行更快、更适合论文复现

```text
Improve experiment runtime and reproducibility.

Requirements:
1. Add environment variable TOPOSTAKE_MAX_PARALLEL. If set, use it as the maximum number of parallel runs. If unset, default to min(available_cpu_count / 2, 4).
2. Add resume support: if a run directory already contains complete epoch_metrics.csv and run_summary.json, skip it unless --force is passed.
3. Add --only EXPERIMENT_NAME and --dry-run to scripts/task.py.
4. Write a manifest file results/processed/manifest.json containing:
   - git commit hash
   - config file
   - command line
   - start/end time
   - number of completed runs
   - number of failed runs
   - failed run IDs
5. Summarization must not silently ignore missing experiments. It should report missing runs in paper_summary.md.
6. Add a small CI/sanity profile that runs one seed, 30 nodes, and 2 short experiments in under a few minutes.
```

------

