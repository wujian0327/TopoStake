use crate::blockchain::block::Block;
use crate::blockchain::Blockchain;
use crate::consensus::{Consensus, Validator, ValidatorError};
use log::{info, warn};
use rand::Rng;
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;

/// Proof-of-Work 共识
/// 基于计算难度的共识机制，proposer 需要完成特定的计算工作来赢得出块权
#[derive(Debug, Clone)]
pub struct PowConsensus {
    /// 当前难度目标（leading zeros 的数量）
    difficulty: usize,
    /// 当前 epoch 的块数（用于判断是否需要调整难度）
    blocks_in_epoch: usize,
    max_threads: usize,
    slot_duration: Duration,
    base_reward: f64,
}

impl PowConsensus {
    /// 创建新的 PoW 共识实例
    pub fn new(
        initial_difficulty: usize,
        max_threads: usize,
        slot_duration: Duration,
        base_reward: f64,
    ) -> Self {
        PowConsensus {
            difficulty: initial_difficulty,
            blocks_in_epoch: 0,
            max_threads,
            slot_duration,
            base_reward,
        }
    }

    /// 验证工作量证明
    /// 检查 hash 是否满足难度要求（leading zeros）
    fn verify_pow(hash: &[u8], difficulty: usize) -> bool {
        // 检查前 difficulty 位是否为 0
        for i in 0..difficulty {
            let byte_index = i / 8;
            let bit_index = 7 - (i % 8);

            if byte_index >= hash.len() {
                return false;
            }

            let bit = (hash[byte_index] >> bit_index) & 1;
            if bit != 0 {
                return false;
            }
        }
        true
    }

    /// 计算所需的工作量（Hashes attempted）
    /// 难度为 d 时，平均需要 2^d 次哈希尝试
    fn compute_work_amount(difficulty: usize) -> f64 {
        2_f64.powi(difficulty as i32)
    }

    /// 进行 PoW 计算，返回满足难度要求的 nonce 和对应的 hash
    #[allow(dead_code)]
    fn mine_pow(data: &[u8], difficulty: usize, max_attempts: u64) -> Option<(u64, Vec<u8>)> {
        for nonce in 0..max_attempts {
            let mut hasher = Sha256::new();
            hasher.update(data);
            hasher.update(nonce.to_le_bytes());
            let hash = hasher.finalize();
            let hash_bytes = hash.to_vec();

            if Self::verify_pow(&hash_bytes, difficulty) {
                return Some((nonce, hash_bytes));
            }
        }
        None
    }

    /// 动态调整难度（每个 epoch 调整一次）
    /// 基于 epoch 内的块生成时间
    fn adjust_difficulty(&mut self, blocks: &[Block]) {
        if blocks.is_empty() {
            return;
        }

        // 计算整个 epoch 的平均块时间
        let first_time = blocks.first().unwrap().header.timestamp;
        let last_time = blocks.last().unwrap().header.timestamp;
        let time_diff = if last_time > first_time {
            last_time - first_time
        } else {
            1
        };

        let avg_block_time = time_diff / (blocks.len() as u64);
        let target_block_time = self.slot_duration.as_secs();

        // 根据实际块时间调整难度
        if avg_block_time > target_block_time {
            // 块生成太慢，降低难度
            self.difficulty = self.difficulty.saturating_sub(1);
            info!(
                "PoW: Difficulty decreased to {} (avg block time: {}s)",
                self.difficulty, avg_block_time
            );
        } else {
            // 块生成太快，增加难度
            self.difficulty = self.difficulty.saturating_add(1);
            info!(
                "PoW: Difficulty increased to {} (avg block time: {}s)",
                self.difficulty, avg_block_time
            );
        }

        self.blocks_in_epoch = 0;
    }
}

impl Consensus for PowConsensus {
    fn name(&self) -> &'static str {
        "pow"
    }

    fn select_proposer(
        &mut self,
        validators: &[Validator],
        combines_seed: [u8; 32],
        _blockchain: &Blockchain,
    ) -> Result<Validator, ValidatorError> {
        if validators.is_empty() {
            return Err(ValidatorError::NOValidatorError);
        }

        // 如果只有一个验证者，直接返回
        if validators.len() == 1 {
            return Ok(validators[0].clone());
        }

        // 多线程 PoW 竞争：所有验证者并行计算，第一个找到结果的胜利
        let winner = Arc::new(Mutex::new(None::<Validator>));
        let should_stop = Arc::new(std::sync::atomic::AtomicBool::new(false));
        let mut handles = vec![];

        let start_time = std::time::Instant::now();
        let slot_duration = self.slot_duration;

        // 限制最大线程数
        let num_threads = std::cmp::min(validators.len(), self.max_threads);
        let thread_step = if num_threads > 0 {
            (validators.len() + num_threads - 1) / num_threads // 向上取整
        } else {
            1
        };

        for chunk in validators.chunks(thread_step) {
            let chunk_validators = chunk.to_vec();
            let winner_clone = Arc::clone(&winner);
            let should_stop_clone = Arc::clone(&should_stop);
            let difficulty = self.difficulty;
            let seed = combines_seed;

            let handle = thread::spawn(move || {
                // 恢复为固定的最大尝试次数，不再通过次数限制算力
                let max_attempts = 100_000_000u64;

                let base_sleep_micros = 5_000_u64; // 5ms
                let base_batch_size = 5_000_f64;

                // 维护每个验证者的状态
                struct ValidatorState {
                    validator: Validator,
                    nonce: u64,
                    mining_data: Vec<u8>,
                }

                let mut states: Vec<ValidatorState> = chunk_validators
                    .into_iter()
                    .map(|v| {
                        let mut mining_data = Vec::new();
                        mining_data.extend_from_slice(&seed);
                        mining_data.extend_from_slice(v.address.as_bytes());
                        ValidatorState {
                            validator: v,
                            nonce: 0,
                            mining_data,
                        }
                    })
                    .collect();

                let mut any_running = true;
                while any_running {
                    any_running = false;

                    if should_stop_clone.load(std::sync::atomic::Ordering::Relaxed) {
                        return;
                    }

                    for state in states.iter_mut() {
                        if should_stop_clone.load(std::sync::atomic::Ordering::Relaxed) {
                            return;
                        }

                        if state.nonce >= max_attempts {
                            continue;
                        }
                        any_running = true;

                        let target_hashes =
                            (base_batch_size * state.validator.hash_power).max(1.0) as u64;

                        for _ in 0..target_hashes {
                            if state.nonce >= max_attempts {
                                break;
                            }

                            let mut hasher = Sha256::new();
                            hasher.update(&state.mining_data);
                            hasher.update(state.nonce.to_le_bytes());
                            let hash = hasher.finalize();
                            let hash_bytes = hash.to_vec();

                            if Self::verify_pow(&hash_bytes, difficulty) {
                                if let Ok(mut winner_guard) = winner_clone.try_lock() {
                                    if winner_guard.is_none() {
                                        *winner_guard = Some(state.validator.clone());
                                        info!(
                                            "PoW: Validator {} won with nonce {}, pow power {:.2}",
                                            state.validator.address,
                                            state.nonce,
                                            state.validator.hash_power
                                        );
                                        should_stop_clone
                                            .store(true, std::sync::atomic::Ordering::Relaxed);
                                    }
                                }
                                return;
                            }
                            state.nonce += 1;
                        }
                    }

                    if base_sleep_micros > 0
                        && !should_stop_clone.load(std::sync::atomic::Ordering::Relaxed)
                    {
                        thread::sleep(Duration::from_micros(base_sleep_micros));
                    }
                }
            });

            handles.push(handle);
        }

        // 等待线程完成或超时
        let timeout_instant = start_time + slot_duration * 10;
        loop {
            let now = std::time::Instant::now();

            // 检查是否有获胜者（使用 try_lock 避免主线程被阻塞）
            if let Ok(guard) = winner.try_lock() {
                if guard.is_some() {
                    break;
                }
            }

            // 检查是否超时
            if now >= timeout_instant {
                warn!(
                    "PoW: Timeout waiting for threads after {:.2}s (slot_duration: {}s)",
                    now.duration_since(start_time).as_secs_f64(),
                    slot_duration.as_secs()
                );
                should_stop.store(true, std::sync::atomic::Ordering::Relaxed);
                break;
            }

            // 短暂休眠，避免忙轮询
            thread::sleep(Duration::from_millis(1));
        }

        // 等待所有线程完成（设置了 should_stop 后应该很快就结束）
        for handle in handles {
            let _ = handle.join();
        }

        // 获取获胜者或使用 fallback
        let winner_result = {
            if let Ok(winner_guard) = winner.try_lock() {
                winner_guard.clone()
            } else {
                None
            }
        };

        match winner_result {
            Some(validator) => {
                info!("PoW proposer selected: {}", validator.address);
                Ok(validator)
            }
            None => {
                // 如果在规定时间内没有找到获胜者，随机选择一个验证者并降低难度
                let mut rng = rand::thread_rng();
                let index = rng.gen_range(0..validators.len());
                self.difficulty = self.difficulty.saturating_sub(1);
                warn!(
                    "PoW: No winner found within slot time, randomly selecting validator: {}, difficulty reduced to {}",
                    validators[index].address, self.difficulty
                );
                Ok(validators[index].clone())
            }
        }
    }

    fn on_epoch_end(&mut self, blocks: &[Block]) {
        // 在 epoch 结束时调整难度
        self.adjust_difficulty(blocks);
    }

    fn state_summary(&self) -> String {
        format!(
            "pow(difficulty={}_work_amount={:.0})",
            self.difficulty,
            Self::compute_work_amount(self.difficulty)
        )
    }

    fn distribute_rewards(
        &self,
        block: &Block,
        validators: &mut [Validator],
        _nodes_index: HashMap<String, u32>,
    ) {
        // PoW: 固定奖励 + 交易费用
        if let Some(validator) = validators
            .iter_mut()
            .find(|v| v.address == block.header.miner)
        {
            let base_reward = self.base_reward;
            let tx_fees: f64 = block.body.transactions.iter().map(|tx| tx.fee).sum();
            let total_reward = base_reward + tx_fees;
            validator.stake += total_reward;
            info!(
                "PoW: Miner {} received reward: base={:.6} + fees={:.6} = {:.6}, new stake: {:.6}",
                validator.address, base_reward, tx_fees, total_reward, validator.stake
            );
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_pow_verification() {
        // 创建测试 hash：0x00 0x00 0xFF 0xFF
        let hash = vec![0x00u8, 0x00, 0xFF, 0xFF];

        // 16 位前导零应该通过
        assert!(PowConsensus::verify_pow(&hash, 16));

        // 17 位前导零应该失败
        assert!(!PowConsensus::verify_pow(&hash, 17));

        // 0 位应该总是通过
        assert!(PowConsensus::verify_pow(&hash, 0));
    }

    #[test]
    fn test_work_amount() {
        let work_1 = PowConsensus::compute_work_amount(1);
        let work_10 = PowConsensus::compute_work_amount(10);

        // 难度增加 9，工作量应该增加 2^9
        assert!(work_10 >= work_1 * 512.0);
    }

    #[test]
    fn test_mine_pow() {
        let data = b"test data for PoW mining";
        let result = PowConsensus::mine_pow(data, 2, 100_000);
        assert!(result.is_some());

        let (_nonce, hash) = result.unwrap();
        // 验证找到的 nonce 确实满足难度要求
        assert!(PowConsensus::verify_pow(&hash, 2));
    }
}
