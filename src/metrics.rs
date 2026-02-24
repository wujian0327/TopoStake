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
    pub consensus_state: String, // e.g., "topostake(ntd=3)", "pos"
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
    pub avg_delay_ms: f64, // 平均打包延迟 (ms)
}

impl SlotMetrics {
    pub fn to_csv_header() -> String {
        "epoch,slot,miner,proposer_stake,timestamp,block_hash,tx_count,throughput,avg_path_length,\
         min_path_length,max_path_length,median_path_length,stake_concentration,\
         gini_coefficient,consensus_type,consensus_state,avg_tx_delay_ms,block_production_success,block_production_failed"
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
            self.tx_packing_delay_stats.avg_delay_ms,
            self.block_production_success,
            self.block_production_failed,
        )
    }
}

/// 计算交易打包平均延迟统计 (以毫秒为单位)
pub fn calculate_tx_packing_delay(
    transactions_timestamp: Vec<u64>,
    block_timestamp: u64,
) -> TxPackingDelayStats {
    if transactions_timestamp.is_empty() {
        return TxPackingDelayStats { avg_delay_ms: 0.0 };
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

    let avg_delay_ms = total_delay / transactions_timestamp.len() as f64;

    TxPackingDelayStats { avg_delay_ms }
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

/// 计算Gini系数 (Gini coefficient)
/// 用于衡量财富/权益分布的不平等程度
/// 0 = 完全平等, 1 = 完全不平等
pub fn calculate_gini(values: &[f64]) -> f64 {
    if values.is_empty() {
        return 0.0;
    }

    let n = values.len() as f64;
    let mut sorted_values = values.to_vec();
    sorted_values.sort_by(|a, b| a.partial_cmp(b).unwrap());

    let sum: f64 = sorted_values.iter().sum();
    if sum == 0.0 {
        return 0.0;
    }

    let cumsum: f64 = sorted_values
        .iter()
        .enumerate()
        .map(|(i, &v)| (i as f64 + 1.0) * v)
        .sum();

    let gini = (2.0 * cumsum) / (n * sum) - (n + 1.0) / n;
    gini.max(0.0).min(1.0)
}

/// 根据目标Gini系数生成权益分配
/// 返回长度为node_num的权益数组
///
/// # 参数
/// * `node_num`: 节点数量
/// * `target_gini`: 目标Gini系数（0-1，越接近1越不平等）
/// * `gini_seed`: 随机种子，用于打乱顺序
pub fn generate_stake_by_gini(node_num: u32, target_gini: f64, gini_seed: u64) -> Vec<f64> {
    use rand::rngs::StdRng;
    use rand::{Rng, SeedableRng};

    let n = node_num as usize;
    if n == 0 {
        return vec![];
    }

    // 使用指数分布来近似目标Gini
    // target_gini为0时，所有节点权益相等
    // target_gini接近1时，权益高度集中
    // 公式：stake(i) = exp(-(lambda * i/n))

    let lambda = if target_gini < 0.01 {
        0.0
    } else if target_gini > 0.99 {
        20.0
    } else {
        // 通过二分查找找到合适的lambda
        // 对于n个节点，lambda范围需要更大才能覆盖各种Gini值
        let mut low = 0.0;
        let mut high = 20.0;

        for _ in 0..30 {
            // 增加迭代次数提高精度
            let mid = (low + high) / 2.0;
            let test_stakes: Vec<f64> = (0..n)
                .map(|i| (-(mid * (i as f64 / n as f64))).exp())
                .collect();
            let gini = calculate_gini(&test_stakes);
            if gini < target_gini {
                low = mid;
            } else {
                high = mid;
            }
        }
        (low + high) / 2.0
    };

    let mut stakes: Vec<f64> = (0..n)
        .map(|i| (-(lambda * (i as f64 / n as f64))).exp())
        .collect();

    // 标准化使总权益为node_num（平均每个节点1单位）
    let sum: f64 = stakes.iter().sum();
    let scale_factor = n as f64 / sum;
    stakes.iter_mut().for_each(|s| *s *= scale_factor);

    let mut rng = StdRng::seed_from_u64(gini_seed);

    let sort_keys: Vec<f64> = (0..n).map(|_| rng.gen::<f64>()).collect();

    let mut indexed_stakes: Vec<(usize, f64)> =
        stakes.iter().enumerate().map(|(i, &v)| (i, v)).collect();

    indexed_stakes.sort_by(|a, b| {
        let key_a = sort_keys[a.0] + a.1 * 0.3;
        let key_b = sort_keys[b.0] + b.1 * 0.3;
        key_a
            .partial_cmp(&key_b)
            .unwrap_or(std::cmp::Ordering::Equal)
    });

    stakes = indexed_stakes.into_iter().map(|(_, v)| v).collect();

    stakes
}
