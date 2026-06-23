use serde::{Deserialize, Serialize};

/// 每个槽的指标
#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct SlotMetrics {
    pub epoch: u64,
    pub slot: u64,
    pub miner: String,
    pub proposer_stake: f64,
    pub timestamp: u64,
    pub block_hash: String,
    pub tx_count: usize,
    pub throughput: f64, // 吞吐量 (tx/s)
    pub path_stats: PathStats,
    pub stake_concentration: f64, // Herfindahl index
    pub gini_coefficient: f64,    // Gini系数，衡量权益分布不平等程度
    pub consensus_type: String,
    pub consensus_state: String, // e.g., "topostake(D=3)", "pos"
    pub tx_packing_delay_stats: TxPackingDelayStats, // 交易打包延迟统计
    pub block_production_success: usize, // 成功出块数
    pub block_production_failed: usize, // 失败出块数
}

#[derive(Serialize, Deserialize, Debug, Clone, Default)]
pub struct PathStats {
    pub avg_length: f64,
    pub min_length: usize,
    pub max_length: usize,
    pub median_length: usize,
}

#[derive(Serialize, Deserialize, Debug, Clone, Default)]
pub struct TxPackingDelayStats {
    pub avg_delay_s: f64, // 平均打包延迟 (s)
}

#[derive(Serialize, Deserialize, Debug, Clone, Default)]
pub struct EpochMetrics {
    pub epoch: u64,
    pub generated_tx: u64,
    pub included_tx: u64,
    pub throughput: f64,
    pub p50_inclusion_latency_s: f64,
    pub p95_inclusion_latency_s: f64,
    pub p99_inclusion_latency_s: f64,
    pub block_success_ratio: f64,
    pub avg_path_length: f64,
    pub p95_path_length: f64,
    pub valid_path_count: u64,
    pub invalid_path_count: u64,
    pub conflicting_receipt_count: u64,
    pub total_proposer_reward: f64,
    pub total_relay_reward: f64,
    pub burned_relay_fee: f64,
    pub stake_gini: f64,
    pub stake_hhi: f64,
    pub proposer_weight_gini: f64,
    pub proposer_weight_hhi: f64,
    pub adversary_real_stake_share: f64,
    pub adversary_score_share: f64,
    pub adversary_proposer_weight_share: f64,
    pub theoretical_proposer_weight_bound: f64,
    pub observed_adversary_proposer_share: f64,
    pub bound_violation: bool,
}

#[derive(Serialize, Deserialize, Debug, Clone, Default)]
pub struct NodeEpochMetrics {
    pub epoch: u64,
    pub validator_id: String,
    pub adversarial: bool,
    pub economic_stake: f64,
    pub balance: f64,
    pub raw_contribution: f64,
    pub saturated_contribution: f64,
    pub ema_score: f64,
    pub normalized_score: f64,
    pub bonus: f64,
    pub unnormalized_proposer_weight: f64,
    pub normalized_proposer_weight: f64,
    pub proposer_count: u64,
    pub relay_reward: f64,
    pub proposer_reward: f64,
    pub fee_spent: f64,
    pub net_income: f64,
    pub degree: usize,
    pub betweenness: f64,
}

#[derive(Serialize, Deserialize, Debug, Clone, Default)]
pub struct RunSummary {
    pub run_id: String,
    pub completed_epochs: u64,
    pub generated_tx: u64,
    pub included_tx: u64,
    pub block_production_success: usize,
    pub block_production_failed: usize,
    pub adversary_fee_spent: f64,
    pub adversary_reward_income: f64,
    pub adversary_net_income: f64,
}

impl SlotMetrics {
    pub fn to_csv_header() -> String {
        "epoch,slot,miner,proposer_stake,timestamp,block_hash,tx_count,throughput,avg_path_length,\
         min_path_length,max_path_length,median_path_length,stake_concentration,\
         gini_coefficient,consensus_type,consensus_state,avg_tx_delay_s,block_production_success,block_production_failed"
            .to_string()
    }

    pub fn to_csv_row(&self) -> String {
        format!(
            "{},{},{},{:.6},{},{},{},{:.2},{:.2},{},{},{},{:.6},{:.6},{},{},{:.2},{},{}",
            self.epoch,
            self.slot,
            self.miner,
            self.proposer_stake,
            self.timestamp,
            self.block_hash,
            self.tx_count,
            self.throughput,
            self.path_stats.avg_length,
            self.path_stats.min_length,
            self.path_stats.max_length,
            self.path_stats.median_length,
            self.stake_concentration,
            self.gini_coefficient,
            self.consensus_type,
            self.consensus_state,
            self.tx_packing_delay_stats.avg_delay_s,
            self.block_production_success,
            self.block_production_failed,
        )
    }
}

impl EpochMetrics {
    pub fn to_csv_header() -> String {
        "epoch,generated_tx,included_tx,throughput,p50_inclusion_latency_s,p95_inclusion_latency_s,p99_inclusion_latency_s,\
         block_success_ratio,avg_path_length,p95_path_length,valid_path_count,invalid_path_count,conflicting_receipt_count,\
         total_proposer_reward,total_relay_reward,burned_relay_fee,stake_gini,stake_hhi,proposer_weight_gini,proposer_weight_hhi,\
         adversary_real_stake_share,adversary_score_share,adversary_proposer_weight_share,theoretical_proposer_weight_bound,\
         observed_adversary_proposer_share,bound_violation"
            .to_string()
    }

    pub fn to_csv_row(&self) -> String {
        format!(
            "{},{},{},{:.6},{:.6},{:.6},{:.6},{:.6},{:.6},{:.6},{},{},{},{:.6},{:.6},{:.6},{:.6},{:.6},{:.6},{:.6},{:.6},{:.6},{:.6},{:.6},{:.6},{}",
            self.epoch,
            self.generated_tx,
            self.included_tx,
            self.throughput,
            self.p50_inclusion_latency_s,
            self.p95_inclusion_latency_s,
            self.p99_inclusion_latency_s,
            self.block_success_ratio,
            self.avg_path_length,
            self.p95_path_length,
            self.valid_path_count,
            self.invalid_path_count,
            self.conflicting_receipt_count,
            self.total_proposer_reward,
            self.total_relay_reward,
            self.burned_relay_fee,
            self.stake_gini,
            self.stake_hhi,
            self.proposer_weight_gini,
            self.proposer_weight_hhi,
            self.adversary_real_stake_share,
            self.adversary_score_share,
            self.adversary_proposer_weight_share,
            self.theoretical_proposer_weight_bound,
            self.observed_adversary_proposer_share,
            self.bound_violation,
        )
    }
}

impl NodeEpochMetrics {
    pub fn to_csv_header() -> String {
        "epoch,validator_id,adversarial,economic_stake,balance,raw_contribution,saturated_contribution,ema_score,normalized_score,\
         bonus,unnormalized_proposer_weight,normalized_proposer_weight,proposer_count,relay_reward,proposer_reward,fee_spent,\
         net_income,degree,betweenness"
            .to_string()
    }

    pub fn to_csv_row(&self) -> String {
        format!(
            "{},{},{},{:.6},{:.6},{:.6},{:.6},{:.6},{:.6},{:.6},{:.6},{:.6},{},{:.6},{:.6},{:.6},{:.6},{},{}",
            self.epoch,
            self.validator_id,
            self.adversarial,
            self.economic_stake,
            self.balance,
            self.raw_contribution,
            self.saturated_contribution,
            self.ema_score,
            self.normalized_score,
            self.bonus,
            self.unnormalized_proposer_weight,
            self.normalized_proposer_weight,
            self.proposer_count,
            self.relay_reward,
            self.proposer_reward,
            self.fee_spent,
            self.net_income,
            self.degree,
            self.betweenness,
        )
    }
}

/// 计算交易打包平均延迟统计 (以秒为单位)
pub fn calculate_tx_packing_delay(
    transactions_timestamp: Vec<u64>,
    block_timestamp: u64,
) -> TxPackingDelayStats {
    if transactions_timestamp.is_empty() {
        return TxPackingDelayStats { avg_delay_s: 0.0 };
    }

    // 计算平均打包延迟 (秒)
    // 时间戳单位为秒
    let total_delay: f64 = transactions_timestamp
        .iter()
        .map(|tx_time| {
            if block_timestamp >= *tx_time {
                (block_timestamp - tx_time) as f64
            } else {
                0.0
            }
        })
        .sum();

    let avg_delay_s = total_delay / transactions_timestamp.len() as f64;

    TxPackingDelayStats { avg_delay_s }
}

/// 计算Herfindahl index（权益集中度）
pub fn calculate_stake_concentration(stakes: &[f64]) -> f64 {
    if stakes.is_empty() {
        return 0.0;
    }
    let total: f64 = stakes.iter().sum();
    if total <= 0.0 {
        return 0.0;
    }
    let shares: Vec<f64> = stakes.iter().map(|s| s / total).collect();
    shares.iter().map(|s| s * s).sum()
}

pub fn calculate_hhi(values: &[f64]) -> f64 {
    calculate_stake_concentration(values)
}

pub fn percentile_f64(values: &[f64], percentile: f64) -> f64 {
    if values.is_empty() {
        return 0.0;
    }
    let mut sorted = values.to_vec();
    sorted.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    let p = percentile.clamp(0.0, 1.0);
    let idx = ((sorted.len() - 1) as f64 * p).ceil() as usize;
    sorted[idx.min(sorted.len() - 1)]
}

pub fn share_for(
    addresses: &std::collections::HashSet<String>,
    values: &std::collections::HashMap<String, f64>,
) -> f64 {
    let total: f64 = values.values().sum();
    if total <= 0.0 {
        return 0.0;
    }
    addresses
        .iter()
        .map(|address| values.get(address).copied().unwrap_or(0.0))
        .sum::<f64>()
        / total
}

/// 计算路径长度统计
pub fn calculate_path_stats(paths: Vec<Vec<String>>) -> PathStats {
    if paths.is_empty() {
        return PathStats {
            avg_length: 0.0,
            min_length: 0,
            max_length: 0,
            median_length: 0,
        };
    }

    let lengths: Vec<usize> = paths.iter().map(|p| p.len()).collect();
    let min_length = *lengths.iter().min().unwrap_or(&0);
    let max_length = *lengths.iter().max().unwrap_or(&0);
    let avg_length = lengths.iter().sum::<usize>() as f64 / lengths.len() as f64;

    let mut sorted_lengths = lengths.clone();
    sorted_lengths.sort_unstable();
    let median_length = sorted_lengths[sorted_lengths.len() / 2];

    PathStats {
        avg_length,
        min_length,
        max_length,
        median_length,
    }
}
