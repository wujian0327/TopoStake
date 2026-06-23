# Paper Experiment Summary

This file is generated from raw simulator outputs. It reports available runs only and does not infer conclusions when data is missing.

Suites: quick_main

## churn_appendix

- successful runs: 2 / 2
- suite: quick_main
- experiment: churn_appendix
- protocol_label: topostake
- node_num: 100
- sybil_node_num: 0
- fake_node_num: 0
- unstable_node_num: 0
- topology: ba
- tx_rate: 25
- stake_gini: 0.6
- adversary_stake_fraction: 0.0
- adversary_placement: random
- padding_identities: 0
- topostake_initial_depth: 4
- attack_tx_rate_multiplier: 0.0
- unstable_fraction: 0, 0.3
- offline_probability: 0.5
- attack_mode: none
- source epoch CSV files:
  - `results/raw/quick_main/churn_appendix/churn-appendix_topostake_seed0_unstable-fraction-0_offline-probability-0p5/epoch_metrics.csv`
  - `results/raw/quick_main/churn_appendix/churn-appendix_topostake_seed0_unstable-fraction-0p3_offline-probability-0p5/epoch_metrics.csv`
- source node CSV files:
  - `results/raw/quick_main/churn_appendix/churn-appendix_topostake_seed0_unstable-fraction-0_offline-probability-0p5/node_epoch_metrics.csv`
  - `results/raw/quick_main/churn_appendix/churn-appendix_topostake_seed0_unstable-fraction-0p3_offline-probability-0p5/node_epoch_metrics.csv`

## path_padding

- successful runs: 2 / 2
- suite: quick_main
- experiment: path_padding
- protocol_label: topostake
- node_num: 100
- sybil_node_num: 1
- fake_node_num: 0
- unstable_node_num: 0
- topology: ba
- tx_rate: 25
- stake_gini: 0.6
- adversary_stake_fraction: 0.1
- adversary_placement: random
- padding_identities: 0, 2
- topostake_initial_depth: 4
- attack_tx_rate_multiplier: 0.0
- unstable_fraction: 0.0
- offline_probability: 0.5
- attack_mode: path-padding
- source epoch CSV files:
  - `results/raw/quick_main/path_padding/path-padding_topostake_seed0_sybil-node-num-1_adversary-stake-fraction-0p1_padding-identities-0_topostake-initial-depth-4_attack-mode-path-padding/epoch_metrics.csv`
  - `results/raw/quick_main/path_padding/path-padding_topostake_seed0_sybil-node-num-1_adversary-stake-fraction-0p1_padding-identities-2_topostake-initial-depth-4_attack-mode-path-padding/epoch_metrics.csv`
- source node CSV files:
  - `results/raw/quick_main/path_padding/path-padding_topostake_seed0_sybil-node-num-1_adversary-stake-fraction-0p1_padding-identities-0_topostake-initial-depth-4_attack-mode-path-padding/node_epoch_metrics.csv`
  - `results/raw/quick_main/path_padding/path-padding_topostake_seed0_sybil-node-num-1_adversary-stake-fraction-0p1_padding-identities-2_topostake-initial-depth-4_attack-mode-path-padding/node_epoch_metrics.csv`

## performance_load

- successful runs: 2 / 2
- suite: quick_main
- experiment: performance_load
- protocol_label: pos, topostake
- node_num: 100
- sybil_node_num: 0
- fake_node_num: 0
- unstable_node_num: 0
- topology: ba
- tx_rate: 25
- stake_gini: 0.6
- adversary_stake_fraction: 0.0
- adversary_placement: random
- padding_identities: 0
- topostake_initial_depth: 4
- attack_tx_rate_multiplier: 0.0
- unstable_fraction: 0.0
- offline_probability: 0.5
- attack_mode: none
- source epoch CSV files:
  - `results/raw/quick_main/performance_load/performance-load_pos_seed0_node-num-100_topology-ba_tx-rate-25/epoch_metrics.csv`
  - `results/raw/quick_main/performance_load/performance-load_topostake_seed0_node-num-100_topology-ba_tx-rate-25/epoch_metrics.csv`
- source node CSV files:
  - `results/raw/quick_main/performance_load/performance-load_pos_seed0_node-num-100_topology-ba_tx-rate-25/node_epoch_metrics.csv`
  - `results/raw/quick_main/performance_load/performance-load_topostake_seed0_node-num-100_topology-ba_tx-rate-25/node_epoch_metrics.csv`

## performance_scale

- successful runs: 2 / 2
- suite: quick_main
- experiment: performance_scale
- protocol_label: pos, topostake
- node_num: 100
- sybil_node_num: 0
- fake_node_num: 0
- unstable_node_num: 0
- topology: ba
- tx_rate: 25
- stake_gini: 0.6
- adversary_stake_fraction: 0.0
- adversary_placement: random
- padding_identities: 0
- topostake_initial_depth: 4
- attack_tx_rate_multiplier: 0.0
- unstable_fraction: 0.0
- offline_probability: 0.5
- attack_mode: none
- source epoch CSV files:
  - `results/raw/quick_main/performance_scale/performance-scale_pos_seed0_node-num-100_topology-ba_tx-rate-25/epoch_metrics.csv`
  - `results/raw/quick_main/performance_scale/performance-scale_topostake_seed0_node-num-100_topology-ba_tx-rate-25/epoch_metrics.csv`
- source node CSV files:
  - `results/raw/quick_main/performance_scale/performance-scale_pos_seed0_node-num-100_topology-ba_tx-rate-25/node_epoch_metrics.csv`
  - `results/raw/quick_main/performance_scale/performance-scale_topostake_seed0_node-num-100_topology-ba_tx-rate-25/node_epoch_metrics.csv`

## real_stake_bound

- successful runs: 1 / 1
- suite: quick_main
- experiment: real_stake_bound
- protocol_label: topostake
- node_num: 100
- sybil_node_num: 0
- fake_node_num: 0
- unstable_node_num: 0
- topology: ba
- tx_rate: 25
- stake_gini: 0.6
- adversary_stake_fraction: 0.1
- adversary_placement: random
- eta_bonus_product: 0.5
- padding_identities: 0
- topostake_initial_depth: 4
- attack_tx_rate_multiplier: 0.0
- unstable_fraction: 0.0
- offline_probability: 0.5
- attack_mode: none
- source epoch CSV files:
  - `results/raw/quick_main/real_stake_bound/real-stake-bound_topostake_seed0_adversary-stake-fraction-0p1_adversary-placement-random_eta-bonus-product-0p5/epoch_metrics.csv`
- source node CSV files:
  - `results/raw/quick_main/real_stake_bound/real-stake-bound_topostake_seed0_adversary-stake-fraction-0p1_adversary-placement-random_eta-bonus-product-0p5/node_epoch_metrics.csv`

## reward_fairness

- successful runs: 3 / 3
- suite: quick_main
- experiment: reward_fairness
- protocol_label: pos, topostake, topostake_eta0
- node_num: 100
- sybil_node_num: 0
- fake_node_num: 0
- unstable_node_num: 0
- topology: ba
- tx_rate: 25
- stake_gini: 0.6
- relay_profile: normal
- adversary_stake_fraction: 0.0
- adversary_placement: random
- padding_identities: 0
- topostake_initial_depth: 4
- attack_tx_rate_multiplier: 0.0
- unstable_fraction: 0.0
- offline_probability: 0.5
- attack_mode: none
- source epoch CSV files:
  - `results/raw/quick_main/reward_fairness/reward-fairness_pos_seed0_stake-gini-0p6_relay-profile-normal/epoch_metrics.csv`
  - `results/raw/quick_main/reward_fairness/reward-fairness_topostake-eta0_seed0_stake-gini-0p6_relay-profile-normal/epoch_metrics.csv`
  - `results/raw/quick_main/reward_fairness/reward-fairness_topostake_seed0_stake-gini-0p6_relay-profile-normal/epoch_metrics.csv`
- source node CSV files:
  - `results/raw/quick_main/reward_fairness/reward-fairness_pos_seed0_stake-gini-0p6_relay-profile-normal/node_epoch_metrics.csv`
  - `results/raw/quick_main/reward_fairness/reward-fairness_topostake-eta0_seed0_stake-gini-0p6_relay-profile-normal/node_epoch_metrics.csv`
  - `results/raw/quick_main/reward_fairness/reward-fairness_topostake_seed0_stake-gini-0p6_relay-profile-normal/node_epoch_metrics.csv`

## topology_robustness

- successful runs: 2 / 2
- suite: quick_main
- experiment: topology_robustness
- protocol_label: pos, topostake
- node_num: 100
- sybil_node_num: 0
- fake_node_num: 0
- unstable_node_num: 0
- topology: ba
- tx_rate: 25
- stake_gini: 0.6
- adversary_stake_fraction: 0.0
- adversary_placement: random
- padding_identities: 0
- topostake_initial_depth: 4
- attack_tx_rate_multiplier: 0.0
- unstable_fraction: 0.0
- offline_probability: 0.5
- attack_mode: none
- source epoch CSV files:
  - `results/raw/quick_main/topology_robustness/topology-robustness_pos_seed0_node-num-100_topology-ba_tx-rate-25/epoch_metrics.csv`
  - `results/raw/quick_main/topology_robustness/topology-robustness_topostake_seed0_node-num-100_topology-ba_tx-rate-25/epoch_metrics.csv`
- source node CSV files:
  - `results/raw/quick_main/topology_robustness/topology-robustness_pos_seed0_node-num-100_topology-ba_tx-rate-25/node_epoch_metrics.csv`
  - `results/raw/quick_main/topology_robustness/topology-robustness_topostake_seed0_node-num-100_topology-ba_tx-rate-25/node_epoch_metrics.csv`

## transaction_flooding

- successful runs: 2 / 2
- suite: quick_main
- experiment: transaction_flooding
- protocol_label: topostake
- node_num: 100
- sybil_node_num: 0
- fake_node_num: 0
- unstable_node_num: 0
- topology: ba
- tx_rate: 25
- stake_gini: 0.6
- adversary_stake_fraction: 0.1
- adversary_placement: random
- padding_identities: 0
- topostake_initial_depth: 4
- attack_tx_rate_multiplier: 0, 1
- unstable_fraction: 0.0
- offline_probability: 0.5
- attack_mode: flooding
- source epoch CSV files:
  - `results/raw/quick_main/transaction_flooding/transaction-flooding_topostake_seed0_adversary-stake-fraction-0p1_attack-tx-rate-multiplier-0_attack-mode-flooding/epoch_metrics.csv`
  - `results/raw/quick_main/transaction_flooding/transaction-flooding_topostake_seed0_adversary-stake-fraction-0p1_attack-tx-rate-multiplier-1_attack-mode-flooding/epoch_metrics.csv`
- source node CSV files:
  - `results/raw/quick_main/transaction_flooding/transaction-flooding_topostake_seed0_adversary-stake-fraction-0p1_attack-tx-rate-multiplier-0_attack-mode-flooding/node_epoch_metrics.csv`
  - `results/raw/quick_main/transaction_flooding/transaction-flooding_topostake_seed0_adversary-stake-fraction-0p1_attack-tx-rate-multiplier-1_attack-mode-flooding/node_epoch_metrics.csv`
