use crate::blockchain::block::Block;
use crate::blockchain::Blockchain;
use crate::consensus::{Consensus, Validator, ValidatorError};
use log::{debug, info, warn};
use rand::prelude::StdRng;
use rand::{Rng, RngCore, SeedableRng};
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread::{self, JoinHandle};
use std::time::Duration;

/// PoW块数据结构：存储节点在某个index的PoW计算结果
#[derive(Debug, Clone)]
pub struct PowBlock {
    pub address: String,
    pub hash_count: u64,
    pub index: u64,
    pub nonce: u64,
    pub max_difficulty: u64,
}

/// Minotaur共识：Multi-Resource Blockchain Consensus
/// 结合了PoW算力证明和PoS权益证明的混合共识机制
/// 核心原则：所有计算都是有效的，直接累积计算工作量，不需要满足难度目标
/// 每个slot中，节点进行PoW运算并存储计算结果到pow_blocks中
#[derive(Debug)]
pub struct MinotaurConsensus {
    pow_blocks: HashMap<u64, Vec<PowBlock>>,
    base_reward: f64,
    pow_weight: f64,
    block_index: u64,
    max_threads: usize,
    /// 后台计算任务：存储线程句柄和结果存储位置
    background_task: Arc<Mutex<Option<(u64, JoinHandle<Vec<PowBlock>>, Arc<AtomicBool>)>>>,
}

impl MinotaurConsensus {
    /// 创建新的Minotaur共识实例
    pub fn new(base_reward: f64, max_threads: usize) -> Self {
        MinotaurConsensus {
            pow_blocks: HashMap::new(),
            base_reward,
            pow_weight: 0.5, // 默认50%权重
            block_index: 0,
            max_threads,
            background_task: Arc::new(Mutex::new(None)),
        }
    }

    /// 执行PoW计算：计算指定次数的哈希
    #[allow(dead_code)]
    fn perform_pow_computation(&self, address: &str, slot: u64, max_attempts: u64) -> u64 {
        let mut hash_count = 0u64;
        for nonce in 0..max_attempts {
            hash_count += 1;
            let mut hasher = Sha256::new();
            hasher.update(address.as_bytes());
            hasher.update(slot.to_le_bytes());
            hasher.update(nonce.to_le_bytes());
            let _hash = hasher.finalize();
        }
        hash_count
    }

    /// 计算哈希的难度（leading zeros 的数量）
    fn calculate_difficulty(hash: &[u8]) -> u64 {
        let mut difficulty = 0u64;
        for byte in hash {
            if *byte == 0 {
                difficulty += 8;
            } else {
                difficulty += byte.leading_zeros() as u64;
                break;
            }
        }
        difficulty
    }

    /// 添加PoW块
    pub fn add_pow_block(&mut self, block: PowBlock) {
        self.pow_blocks
            .entry(block.index)
            .or_insert_with(Vec::new)
            .push(block);
    }

    /// 获取指定index的PoW块列表
    pub fn get_pow_blocks(&self, index: u64) -> Vec<PowBlock> {
        self.pow_blocks.get(&index).cloned().unwrap_or_default()
    }
}

impl Consensus for MinotaurConsensus {
    fn name(&self) -> &'static str {
        "Minotaur"
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
        // 实现混合选择逻辑（PoW + PoS）
        // 查询 最新的pow块
        if self.block_index == 0 {
            warn!("Block index is 0, no pow blocks available");
            return Ok(validators[0].clone());
        }
        let pow_blocks = self.get_pow_blocks(self.block_index - 1);
        if pow_blocks.is_empty() {
            warn!("No PoW blocks available for index {}", self.block_index - 1);
        }
        // 计算每个验证者的pow得分
        let mut pow_scores: HashMap<String, f64> = HashMap::new();
        for block in pow_blocks {
            //score 是2的指数形式
            let score = 2f64.powf(block.max_difficulty as f64);
            *pow_scores.entry(block.address.clone()).or_insert(0.0) += score;
        }
        debug!("PoW Scores: {:?}", pow_scores);
        // 计算pow的每个节点的百分比
        let total_pow_score: f64 = pow_scores.values().sum();
        let mut pow_ratio_scores: HashMap<String, f64> = HashMap::new();
        for validator in validators {
            let pow_score = pow_scores.get(&validator.address).cloned().unwrap_or(0.0);
            let pow_ratio = if total_pow_score > 0.0 {
                pow_score / total_pow_score
            } else {
                0.0
            };
            pow_ratio_scores.insert(validator.address.clone(), pow_ratio);
        }
        debug!("PoW Ratio Scores: {:?}", pow_ratio_scores);
        // 计算pos的权重
        let total_stake: f64 = validators.iter().map(|v| v.stake).sum();
        let mut pos_ratio_scores: HashMap<String, f64> = HashMap::new();
        for validator in validators {
            let pos_ratio = if total_stake > 0.0 {
                validator.stake / total_stake
            } else {
                0.0
            };
            pos_ratio_scores.insert(validator.address.clone(), pos_ratio);
        }
        debug!("PoS Ratio Scores: {:?}", pos_ratio_scores);
        // 根据pow_weight 计算综合得分
        let mut combined_scores: HashMap<String, f64> = HashMap::new();
        for validator in validators {
            let pow_ratio = pow_ratio_scores
                .get(&validator.address)
                .cloned()
                .unwrap_or(0.0);
            let pos_ratio = pos_ratio_scores
                .get(&validator.address)
                .cloned()
                .unwrap_or(0.0);
            let combined_score = self.pow_weight * pow_ratio + (1.0 - self.pow_weight) * pos_ratio;
            combined_scores.insert(validator.address.clone(), combined_score);
        }
        debug!("Combined Scores: {:?}", combined_scores);
        // 将combined_scores 视作vitual_stake,算出出块者
        let mut rng = StdRng::from_seed(combines_seed);
        let total_combined_score: f64 = combined_scores.values().sum();
        let mut pick = rng.gen_range(0.0..total_combined_score);
        for validator in validators {
            let score = combined_scores
                .get(&validator.address)
                .cloned()
                .unwrap_or(0.0);
            let pow_score = pow_ratio_scores
                .get(&validator.address)
                .cloned()
                .unwrap_or(0.0);
            let pos_score = pos_ratio_scores
                .get(&validator.address)
                .cloned()
                .unwrap_or(0.0);
            if pick < score {
                info!(
                    "Minotaur Selected proposer: {} with virtual stake {:.6},pow_score {:.6},pos_score {:.6}",
                    validator.address, score, pow_score, pos_score
                );
                return Ok(validator.clone());
            }
            pick -= score;
        }

        // 临时返回第一个验证者
        warn!("Fallback: selecting first validator as proposer");
        Ok(validators[0].clone())
    }

    fn on_epoch_end(&mut self, _blocks: &[Block]) {}

    fn state_summary(&self) -> String {
        format!("minotaur(pow_w:{:.2})", self.pow_weight)
    }

    fn distribute_rewards(
        &self,
        block: &Block,
        validators: &mut [Validator],
        _nodes_index: HashMap<String, u32>,
    ) {
        // Minotaur: 基础奖励 + 交易费用
        if let Some(validator) = validators
            .iter_mut()
            .find(|v| v.address == block.header.miner)
        {
            let base_reward = self.base_reward;
            let tx_fees: f64 = block.body.transactions.iter().map(|tx| tx.fee).sum();
            let total_reward = base_reward + tx_fees;
            validator.stake += total_reward;
            info!(
                "Minotaur: Miner {} received reward: base={:.6} + fees={:.6} = {:.6}, new stake: {:.6}",
                validator.address, base_reward, tx_fees, total_reward, validator.stake
            );
        }
    }

    fn next_slot(&mut self, validators: &[Validator], block_index: u64) {
        // Minotaur在这里处理pow_blocks的slot更新逻辑
        // 在slot开始的时候，保存上一个pow_blocks的数据
        // 然后开始新的pow运算
        // 保存此轮计算的结果

        // 第一步：收集上一个后台任务的计算结果
        let collected_blocks = {
            let mut task_guard = self.background_task.lock().unwrap();
            let mut blocks = Vec::new();
            if let Some((_, handle, stop_flag)) = task_guard.take() {
                // 发送停止信号给上一个后台任务
                stop_flag.store(true, Ordering::Relaxed);

                // 等待上一个后台任务完成并收集结果
                match handle.join() {
                    Ok(pow_blocks) => {
                        blocks = pow_blocks;
                        debug!(
                            "Collected PoW results from background task: {} blocks",
                            blocks.len()
                        );
                        // 打印一下每个块的信息
                        for block in &blocks {
                            debug!(
                                "  PowBlock: address={}, index={}, hash_count={}, max_difficulty={}",
                                block.address, block.index, block.hash_count, block.max_difficulty
                            );
                        }
                    }
                    Err(_) => {
                        debug!("Failed to join background task");
                    }
                }
            }
            blocks
        }; // 释放锁

        // 现在将收集到的块添加到 pow_blocks
        for block in collected_blocks {
            self.add_pow_block(block);
        }

        self.block_index = block_index;
        debug!("Transitioning to next block index: {}", self.block_index);

        let max_threads_limit = self.max_threads;
        // 第二步：启动新的后台计算任务
        let validators_clone: Vec<Validator> = validators.to_vec();
        let stop_signal = Arc::new(AtomicBool::new(false));
        let stop_signal_clone = Arc::clone(&stop_signal);

        let handle = thread::spawn(move || {
            let pow_blocks = Arc::new(Mutex::new(HashMap::new()));
            let mut handles = vec![];

            let num_threads = std::cmp::min(validators_clone.len(), max_threads_limit);
            if num_threads > 0 {
                let thread_step = (validators_clone.len() + num_threads - 1) / num_threads;

                for chunk in validators_clone.chunks(thread_step) {
                    let chunk_validators = chunk.to_vec();
                    let pow_blocks_clone = Arc::clone(&pow_blocks);
                    let stop_signal_inner = Arc::clone(&stop_signal_clone);
                    let index = block_index;

                    let handle = thread::spawn(move || {
                        let base_sleep_micros = 5_000_u64; // 基础休眠时间（微秒）
                        let base_batch_size = 5_000_f64; // 基础批次计算量

                        // 状态维护
                        struct ValidatorState {
                            address: String,
                            hash_power: f64,
                            nonce: u64,
                            best_pow_block: Option<PowBlock>,
                        }

                        let mut states: Vec<ValidatorState> = chunk_validators
                            .into_iter()
                            .map(|v| ValidatorState {
                                address: v.address,
                                hash_power: v.hash_power,
                                nonce: 0,
                                best_pow_block: None,
                            })
                            .collect();

                        loop {
                            if stop_signal_inner.load(Ordering::Relaxed) {
                                break;
                            }

                            for state in states.iter_mut() {
                                if stop_signal_inner.load(Ordering::Relaxed) {
                                    break;
                                }

                                // 算力越高，此次循环计算的哈希次数越多，模拟哈希速率差异
                                let target_hashes =
                                    (base_batch_size * state.hash_power).max(1.0) as u64;

                                for _ in 0..target_hashes {
                                    let mut hasher = Sha256::new();
                                    hasher.update(state.address.as_bytes());
                                    hasher.update(index.to_le_bytes());
                                    hasher.update(state.nonce.to_le_bytes());
                                    let hash = hasher.finalize();

                                    let difficulty = Self::calculate_difficulty(&hash.to_vec());

                                    if state.best_pow_block.is_none()
                                        || difficulty
                                            > state.best_pow_block.as_ref().unwrap().max_difficulty
                                    {
                                        let mut rng = StdRng::from_seed([index as u8; 32]);
                                        let pow_nonce = rng.next_u64();

                                        state.best_pow_block = Some(PowBlock {
                                            address: state.address.clone(),
                                            hash_count: state.nonce + 1,
                                            index,
                                            nonce: pow_nonce,
                                            max_difficulty: difficulty,
                                        });
                                    }
                                    state.nonce += 1;
                                }
                            }

                            if base_sleep_micros > 0 && !stop_signal_inner.load(Ordering::Relaxed) {
                                thread::sleep(Duration::from_micros(base_sleep_micros));
                            }
                        }

                        // 将最佳结果存储到共享的HashMap中
                        let mut blocks = pow_blocks_clone.lock().unwrap();
                        let entry = blocks.entry(index).or_insert_with(Vec::new);
                        for state in states {
                            if let Some(pow_block) = state.best_pow_block {
                                debug!(
                                    "PoW computation finished for index {}: address={}, total attempts={}, max_difficulty={}",
                                    index, pow_block.address, state.nonce, pow_block.max_difficulty
                                );
                                entry.push(pow_block);
                            }
                        }
                    });

                    handles.push(handle);
                }
            }

            // 等待所有计算线程完成
            for handle in handles {
                handle.join().expect("Worker thread panicked");
            }

            // 收集所有结果
            let results = pow_blocks.lock().unwrap();
            let mut all_blocks = Vec::new();
            for (_, blocks) in results.iter() {
                all_blocks.extend(blocks.clone());
            }

            info!(
                "Background PoW computation completed for block index: {} blocks produced",
                all_blocks.len()
            );
            all_blocks
        });

        // 保存后台任务信息
        let mut task_guard = self.background_task.lock().unwrap();
        *task_guard = Some((block_index, handle, stop_signal));

        info!(
            "Started background PoW computation for block index {}: {} validators",
            block_index,
            validators.len()
        );
    }
}

#[cfg(test)]
mod tests {}
