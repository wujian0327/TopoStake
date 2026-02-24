use crate::blockchain::block::Block;
use crate::blockchain::{BlockChainError, Blockchain};
use crate::consensus::minotaur::MinotaurConsensus;
use crate::consensus::topostake::TopoStakeConsensus;
use crate::consensus::pos::PosConsensus;
use crate::consensus::pow::PowConsensus;
use crate::consensus::{Consensus, ConsensusType, RandaoSeed, Validator};
use crate::metrics::{self, calculate_stake_concentration, SlotMetrics};
use crate::network::message::{Message, MessageType};
use crate::tools::get_timestamp;
use crate::{consensus, tools};
use log::{debug, error, info, warn};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fmt;
use std::io::Write;
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::mpsc::{Receiver, Sender};
use tokio::sync::RwLock;
use tokio::time::Instant;
use tokio::{task, time};

/// 全局状态，用于管理时隙、vdf投票，余额等等
/// 也可以用于与所有的节点进行通信
pub struct WorldState {
    pub current_slot: Arc<RwLock<SlotManager>>,
    // pub slots: Vec<SlotManager>,
    pub validators: Arc<RwLock<Vec<Validator>>>,
    // sender和receiver要和WorldState解耦，独立返回
    // pub sender: Sender<Message>,
    // pub receiver: Receiver<Message>,
    // pub nodes_balance: HashMap<String, u64>,
    pub nodes_sender: HashMap<String, Sender<Message>>,
    pub blockchain: Arc<RwLock<Blockchain>>,
    pub consensus: Box<dyn Consensus>,
    consensus_name: String,
    metrics_slots_file: Option<std::fs::File>,
    slot_duration: Duration,
    slot_per_epoch: u64,
    pub nodes_index: HashMap<String, u32>,
    // 出块成功率统计
    pub block_production_success: usize, // 成功出块数
    pub block_production_failed: usize,  // 失败出块数
    pub base_reward: f64,                // 所有共识的固定奖励
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct SlotManager {
    pub randao_seeds: Vec<RandaoSeed>,
    pub slot_duration: Duration,
    pub current_epoch: u64,
    pub current_slot: u64,
    pub next_seed: [u8; 32],
    pub start_timestamp: u64,
}

impl WorldState {
    pub fn new(
        genesis_block: Block,
        consensus_type: ConsensusType,
        blockchain: Blockchain,
        slot_duration_secs: u64,
        slot_per_epoch: u64,
        pow_difficulty: usize,
        pow_max_threads: usize,
        base_reward: f64,
    ) -> (Self, Sender<Message>, Receiver<Message>) {
        let (sender, receiver) = tokio::sync::mpsc::channel(4096);
        let nodes_sender: HashMap<String, Sender<Message>> = HashMap::new();
        let slot_duration = Duration::from_secs(slot_duration_secs);
        let consensus_name = consensus_type.to_string();
        let consensus: Box<dyn Consensus> = match consensus_type {
            ConsensusType::TopoStake => Box::new(TopoStakeConsensus::new(0, base_reward)),
            ConsensusType::POS => Box::new(PosConsensus::new(base_reward)),
            ConsensusType::POW => Box::new(PowConsensus::new(
                pow_difficulty,
                pow_max_threads,
                slot_duration,
                base_reward,
            )),
            ConsensusType::MINOTAUR => Box::new(MinotaurConsensus::new(base_reward)),
        };
        // Initialize metrics files - delete old file and create new one
        let metrics_filename = format!("metrics_slots_{}.csv", consensus_name);
        let _ = std::fs::remove_file(&metrics_filename); // 删除旧文件
        let metrics_slots_file = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&metrics_filename)
            .ok();

        (
            WorldState {
                current_slot: Arc::new(RwLock::new(SlotManager {
                    randao_seeds: vec![],
                    slot_duration,
                    current_epoch: 0,
                    current_slot: 0,
                    next_seed: [0; 32],
                    start_timestamp: genesis_block.header.timestamp,
                })),
                validators: Arc::new(RwLock::new(vec![])),
                nodes_sender,
                blockchain: Arc::new(RwLock::new(blockchain)),
                consensus,
                consensus_name,
                metrics_slots_file,
                slot_duration,
                slot_per_epoch,
                nodes_index: HashMap::new(),
                block_production_success: 0,
                block_production_failed: 0,
                base_reward,
            },
            sender,
            receiver,
        )
    }

    pub async fn next_slot(&mut self) {
        let current_slot = self.current_slot.read().await.clone();
        let block_index = self.blockchain.read().await.get_last_index();
        //计算randao seed
        let validators = self.validators.read().await.clone();
        let next_seed = consensus::combine_seed(validators.clone(), current_slot.randao_seeds);

        if current_slot.current_slot >= self.slot_per_epoch - 1 {
            //更新epoch
            self.next_epoch().await;
        } else {
            self.current_slot = Arc::new(RwLock::new(SlotManager {
                randao_seeds: vec![],
                slot_duration: self.slot_duration,
                current_epoch: current_slot.current_epoch,
                current_slot: current_slot.current_slot + 1,
                next_seed,
                start_timestamp: get_timestamp(),
            }));
        }
        self.consensus.next_slot(&validators, block_index);
        let current_slot = self.get_current_slot().await;
        info!(
            "World State change slot to: epoch[{}] slot[{}] consensus[{}] seed{:?}",
            current_slot.current_epoch,
            current_slot.current_slot,
            self.consensus.state_summary(),
            next_seed
        );

        let nodes_sender: Vec<Sender<Message>> = self.nodes_sender.values().cloned().collect();

        //通知所有节点更新slot
        for sender in nodes_sender {
            if let Err(e) = sender
                .send(Message::new_update_slot_msg(current_slot.clone()))
                .await
            {
                error!("World State error: send update slot msg failed {:?}", e);
            }
        }

        //通知所有的validator可以开始新一轮的发送seed
        for v in validators.clone() {
            if let Err(e) = self.nodes_sender[&v.address]
                .send(Message::new_send_randao_seed_msg())
                .await
            {
                error!("World State error: send new randao seed msg failed {:?}", e);
            }
        }

        //获得出块节点
        let bc = self.blockchain.read().await.clone();
        let miner_validator =
            match self
                .consensus
                .select_proposer(&validators, next_seed.clone(), &bc)
            {
                Ok(miner) => miner,
                Err(e) => {
                    warn!("World State error: select proposer failed: {}", e);
                    return;
                }
            };

        //这里简化成通知miner出块，实际上应该是每个节点自己算
        match self.nodes_sender.get(&miner_validator.address) {
            Some(sender) => {
                debug!(
                    "World State find miner: {}",
                    miner_validator.address.clone()
                );
                sender
                    .send(Message::new_generate_block_msg())
                    .await
                    .unwrap();
            }
            None => {
                error!("World State error: failed to find miner");
            }
        }

        // Collect slot metrics
        self.collect_slot_metrics(&miner_validator).await;
    }

    pub async fn next_epoch(&mut self) {
        let current_slot = self.current_slot.read().await.clone();
        let _current_epoch = current_slot.current_epoch;
        //更新epoch中调用consensus的on_epoch_end
        let blocks = self.blockchain.read().await.get_last_epoch_block();
        self.consensus.on_epoch_end(&blocks);

        let validators = self.validators.read().await.clone();
        let next_seed = consensus::combine_seed(validators.clone(), current_slot.randao_seeds);
        self.current_slot = Arc::new(RwLock::new(SlotManager {
            randao_seeds: vec![],
            slot_duration: self.slot_duration,
            current_epoch: current_slot.current_epoch + 1,
            current_slot: 0,
            next_seed,
            start_timestamp: get_timestamp(),
        }));

        // 打印每个 epoch 的节点余额信息
        let mut node_stakes: Vec<(u32, f64)> = validators
            .iter()
            .filter_map(|validator| {
                self.nodes_index
                    .get(&validator.address)
                    .map(|index| (*index, validator.stake))
            })
            .collect();
        node_stakes.sort_by_key(|k| k.0);
        for (index, stake) in node_stakes {
            info!(
                "Epoch[{}] Node[{}]: stake: {:.6}",
                current_slot.current_epoch, index, stake
            );
        }
    }

    pub async fn get_current_slot(&self) -> SlotManager {
        self.current_slot.read().await.clone()
    }

    async fn collect_slot_metrics(&mut self, miner: &Validator) {
        let current_slot = self.current_slot.read().await.clone();
        let validators = self.validators.read().await.clone();
        let blockchain = self.blockchain.read().await.clone();

        // Get last block for stats
        let last_block = blockchain.get_last_block();
        let tx_count = last_block.body.transactions.len();

        // Calculate throughput (tx/s) - based on time between current and previous block
        let throughput = {
            let blocks = &blockchain.blocks;
            if blocks.len() > 1 {
                let prev_block_timestamp = blocks[blocks.len() - 2].header.timestamp;
                let time_delta = last_block
                    .header
                    .timestamp
                    .saturating_sub(prev_block_timestamp);
                if time_delta > 0 {
                    tx_count as f64 / time_delta as f64
                } else {
                    0.0
                }
            } else {
                0.0
            }
        };

        let paths = last_block.body.paths;
        let paths: Vec<Vec<String>> = paths.iter().map(|p| p.paths.clone()).collect();
        let path_stats = metrics::calculate_path_stats(paths);

        // Calculate stake concentration from stakes
        let stake_values: Vec<f64> = validators.iter().map(|v| v.stake).collect();
        let stake_concentration = calculate_stake_concentration(&stake_values);
        let gini_coefficient = metrics::calculate_gini(&stake_values);

        // Calculate transaction packing delay
        let tx_timestamps: Vec<u64> = last_block
            .body
            .transactions
            .iter()
            .map(|tx| tx.timestamp)
            .collect();
        let tx_packing_delay_stats =
            metrics::calculate_tx_packing_delay(tx_timestamps, last_block.header.timestamp);

        // Get consensus state summary
        let consensus_state = self.consensus.state_summary();

        // Create metrics
        let slot_metrics = SlotMetrics {
            epoch: current_slot.current_epoch,
            slot: current_slot.current_slot,
            miner: miner.address.clone(),
            proposer_stake: miner.stake,
            timestamp: tools::get_timestamp(),
            block_hash: last_block.header.hash.clone(),
            tx_count,
            throughput,
            path_stats: path_stats,
            stake_concentration,
            gini_coefficient,
            consensus_type: self.consensus.name().to_string(),
            consensus_state,
            tx_packing_delay_stats,
            block_production_success: self.block_production_success,
            block_production_failed: self.block_production_failed,
        };

        // Write to CSV
        if self.metrics_slots_file.is_none() {
            if let Ok(file) = std::fs::OpenOptions::new()
                .create(true)
                .append(true)
                .open(format!("metrics_slots_{}.csv", self.consensus_name))
            {
                self.metrics_slots_file = Some(file);
            }
        }

        if let Some(ref mut file) = self.metrics_slots_file {
            // Write header if file is empty
            if file.metadata().map(|m| m.len()).unwrap_or(0) == 0 {
                let _ = writeln!(file, "{}", SlotMetrics::to_csv_header());
            }

            let _ = writeln!(file, "{}", slot_metrics.to_csv_row());
            let _ = file.flush();
        }
    }

    pub async fn run(self, mut receiver: Receiver<Message>) {
        let node_index = self.nodes_index.clone();
        let consensus_name = self.consensus_name.clone();
        let shared_self = Arc::new(RwLock::new(self));
        let receiver_task = {
            let shared_self = Arc::clone(&shared_self);
            task::spawn(async move {
                while let Some(msg) = receiver.recv().await {
                    debug!("World State received msg type: {}", msg.msg_type);
                    match msg.msg_type {
                        MessageType::ReceiveRandaoSeed => {
                            let randao_seed = match RandaoSeed::from_json(msg.data) {
                                Ok(t) => t,
                                Err(e) => {
                                    error!("World State error: {}", e);
                                    continue;
                                }
                            };
                            {
                                let shared_self = shared_self.write().await;
                                let mut current_slot = shared_self.current_slot.write().await;
                                current_slot.randao_seeds.push(randao_seed.clone());
                            }
                        }
                        MessageType::ReceiveBecomeValidator => {
                            let validator = match Validator::from_json(msg.data) {
                                Ok(t) => t,
                                Err(e) => {
                                    error!("World State error: {}", e);
                                    continue;
                                }
                            };
                            {
                                let shared_self = shared_self.write().await;
                                let mut validators = shared_self.validators.write().await;
                                validators.retain(|v| v.address != validator.address);
                                validators.push(validator.clone());
                            }
                        }
                        MessageType::UpdateValidatorStake => {
                            // 解析消息中的 address 和 new_stake
                            if let Ok(json_str) = String::from_utf8(msg.data.clone()) {
                                if let Ok(payload) =
                                    serde_json::from_str::<serde_json::Value>(&json_str)
                                {
                                    if let (Some(address), Some(new_stake)) = (
                                        payload.get("address").and_then(|v| v.as_str()),
                                        payload.get("stake").and_then(|v| v.as_f64()),
                                    ) {
                                        let shared_self = shared_self.write().await;
                                        let mut validators = shared_self.validators.write().await;
                                        // 更新对应 Validator 的 stake
                                        if let Some(validator) =
                                            validators.iter_mut().find(|v| v.address == address)
                                        {
                                            validator.stake = new_stake;
                                        }
                                    }
                                }
                            }
                        }
                        MessageType::SendBlock => {
                            let block = match Block::from_json(msg.data) {
                                Ok(b) => b,
                                Err(e) => {
                                    error!("Error: {}", e);
                                    continue;
                                }
                            };

                            {
                                let mut shared_self = shared_self.write().await;
                                let add_block_result = {
                                    shared_self
                                        .blockchain
                                        .write()
                                        .await
                                        .add_block(block.clone())
                                };

                                if let Err(e) = add_block_result {
                                    match e {
                                        BlockChainError::ParentHashMismatch => {
                                            error!(
                                                "World State: Parent hash mismatch at index {}, there may be a fork",
                                                block.header.index
                                            );
                                            // 出现分叉，显式找到 index==0 的节点请求全链
                                            if let Some((addr, _)) = shared_self
                                                .nodes_index
                                                .iter()
                                                .find(|(_, &idx)| idx == 0)
                                            {
                                                if let Some(sender) =
                                                    shared_self.nodes_sender.get(addr)
                                                {
                                                    warn!(
                                                        "World State: Requesting full blockchain from Node[0] due to fork"
                                                    );
                                                    let _ = sender.try_send(
                                                        Message::new_request_block_sync_msg(
                                                            0,
                                                            "world_state".to_string(),
                                                        ),
                                                    );
                                                }
                                            }
                                        }
                                        BlockChainError::IndexTooSmall => {
                                            warn!(
                                                "World State: Received block at index {}, index too small, current index is {}",
                                                block.header.index, shared_self.blockchain.read().await.get_last_index()
                                            );
                                        }
                                        _ => {
                                            error!("World State Add Block Error: {}", e);
                                        }
                                    }
                                    shared_self.block_production_failed += 1;
                                    continue;
                                }

                                // 块添加成功，更新出块成功计数
                                shared_self.block_production_success += 1;

                                // 块添加成功后，立即分配奖励
                                {
                                    let mut validators = shared_self.validators.write().await;

                                    // 创建一个可变的向量切片来修改
                                    let validators_slice: &mut [Validator] = &mut validators;
                                    shared_self.consensus.distribute_rewards(
                                        &block,
                                        validators_slice,
                                        node_index.clone(),
                                    );

                                    // 在奖励分配后，同步每个获得奖励的节点的 balance
                                    for validator in validators.iter() {
                                        if let Some(sender) =
                                            shared_self.nodes_sender.get(&validator.address)
                                        {
                                            let msg = Message::new_update_node_balance_msg(
                                                validator.stake,
                                            );
                                            if let Err(e) = sender.send(msg).await {
                                                warn!(
                                                    "Failed to send UpdateNodeBalance to {}: {}",
                                                    &validator.address
                                                        [..8.min(validator.address.len())],
                                                    e
                                                );
                                            }
                                        }
                                    }
                                }
                            }
                            debug!("World State add block successfully");
                        }
                        MessageType::BlockProductionFailed => {
                            // 处理出块失败事件
                            if let Ok(json_str) = String::from_utf8(msg.data.clone()) {
                                if let Ok(payload) =
                                    serde_json::from_str::<serde_json::Value>(&json_str)
                                {
                                    if let (Some(node_index), Some(slot), Some(reason)) = (
                                        payload.get("node_index").and_then(|v| v.as_u64()),
                                        payload.get("slot").and_then(|v| v.as_u64()),
                                        payload.get("reason").and_then(|v| v.as_str()),
                                    ) {
                                        let mut shared_self = shared_self.write().await;
                                        shared_self.block_production_failed += 1;
                                        debug!(
                                            "World State: Block production failed at slot {}: Node[{}] (reason: {})",
                                            slot, node_index, reason
                                        );
                                    }
                                }
                            }
                        }
                        MessageType::ResponseBlockSync => {
                            //处理同步逻辑
                            let blocks_json = match String::from_utf8(msg.data) {
                                Ok(s) => s,
                                Err(_e) => {
                                    continue;
                                }
                            };

                            let sync_blocks: Vec<Block> = match serde_json::from_str(&blocks_json) {
                                Ok(blocks) => blocks,
                                Err(_e) => {
                                    continue;
                                }
                            };
                            if sync_blocks.is_empty() {
                                continue;
                            }
                            // 从第一个区块开始对比，找到分叉点后替换本地区块链
                            let shared_self = shared_self.write().await;
                            let mut local_chain = shared_self.blockchain.write().await;

                            let local_len = local_chain.blocks.len();
                            let sync_len = sync_blocks.len();
                            let min_len = local_len.min(sync_len);

                            // 寻找第一个不同的块
                            let mut divergence_idx = None;
                            for i in 0..min_len {
                                if local_chain.blocks[i].header.hash != sync_blocks[i].header.hash {
                                    divergence_idx = Some(i);
                                    break;
                                }
                            }

                            match divergence_idx {
                                Some(idx) => {
                                    // 截断本地链到分叉点，然后用同步链替换后续部分
                                    local_chain.blocks.truncate(idx);
                                    local_chain
                                        .blocks
                                        .extend(sync_blocks[idx..].iter().cloned());
                                    info!(
                                        "World State: chain diverged at #{}, replaced from peer (local_len={} -> sync_len={})",
                                        idx,
                                        local_len,
                                        sync_len
                                    );
                                }
                                None => {
                                    if sync_len > local_len {
                                        // 本地是前缀，直接追加缺失部分
                                        local_chain
                                            .blocks
                                            .extend(sync_blocks[local_len..].iter().cloned());
                                        info!(
                                            "World State: appended {} blocks (local_len={} -> sync_len={})",
                                            sync_len - local_len,
                                            local_len,
                                            sync_len
                                        );
                                    } else if sync_len == local_len {
                                        debug!(
                                            "World State: chains are identical (len={})",
                                            local_len
                                        );
                                    } else {
                                        warn!(
                                            "World State: peer chain shorter (peer_len={} < local_len={}), skip",
                                            sync_len,
                                            local_len
                                        );
                                    }
                                }
                            }
                        }
                        _ => {}
                    }
                }
            })
        };

        let mut last_index = 0;
        let timer_task = task::spawn(async move {
            loop {
                let time_interval = {
                    let shared_self = shared_self.read().await;
                    let current_slot = shared_self.get_current_slot().await;
                    let target_time =
                        current_slot.start_timestamp + current_slot.slot_duration.as_secs();
                    let current_time = get_timestamp();

                    // 如果已经超过目标时间，立即触发下一个 slot
                    if current_time >= target_time {
                        Duration::from_secs(0)
                    } else {
                        Duration::from_secs(target_time - current_time)
                    }
                };
                let deadline = Instant::now() + time_interval;
                time::sleep_until(deadline).await;
                debug!("World State time trigger: {}", tools::get_time_string());

                // 对于 PoW 协议，需要等待区块链长度增加后才进入下一个 slot
                if consensus_name == "pow" {
                    let pow_wait_start = Instant::now();
                    let pow_timeout =
                        Duration::from_secs(shared_self.read().await.slot_duration.as_secs() * 16);
                    loop {
                        if last_index == 0 {
                            time::sleep(Duration::from_secs(
                                shared_self.read().await.slot_per_epoch,
                            ))
                            .await;
                            break;
                        }
                        let current_index = {
                            shared_self
                                .read()
                                .await
                                .blockchain
                                .read()
                                .await
                                .get_last_index()
                        };
                        if current_index > last_index {
                            // 区块链有新块，可以进入下一个 slot
                            break;
                        }

                        // 检查超时
                        if pow_wait_start.elapsed() > pow_timeout {
                            warn!("PoW wait timeout, force entering next slot");
                            break;
                        }

                        // 短暂休眠，避免忙轮询
                        time::sleep(Duration::from_millis(100)).await;
                    }
                }
                last_index = {
                    shared_self
                        .read()
                        .await
                        .blockchain
                        .read()
                        .await
                        .get_last_index()
                };
                {
                    let mut shared_self = shared_self.write().await;
                    shared_self.next_slot().await;
                }
            }
        });

        let _ = tokio::join!(timer_task, receiver_task);
    }
}

impl SlotManager {
    pub fn from_json(json: Vec<u8>) -> Result<SlotManager, WorldStateError> {
        let slot: SlotManager = serde_json::from_slice(json.as_slice())?;
        Ok(slot)
    }

    pub fn to_json(&self) -> Vec<u8> {
        serde_json::to_vec(&self).unwrap()
    }
}

#[derive(Debug)]
pub enum WorldStateError {
    JSONError,
}
impl fmt::Display for WorldStateError {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        match *self {
            WorldStateError::JSONError => {
                write!(f, "Invalid Json Error")
            }
        }
    }
}
impl From<serde_json::error::Error> for WorldStateError {
    fn from(_: serde_json::error::Error) -> Self {
        WorldStateError::JSONError
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::blockchain::block::Block;
    use crate::blockchain::path::TransactionPaths;
    use crate::blockchain::transaction::Transaction;
    use crate::blockchain::Blockchain;
    use crate::network::node::{Neighbor, Node};
    use log::info;

    #[tokio::test]
    async fn timer_trigger() {
        let _ = env_logger::builder()
            .filter_level(log::LevelFilter::Info)
            .is_test(true)
            .try_init();

        let blockchain = Blockchain::new(Block::gen_genesis_block());
        let (world, _world_sender, world_receiver) = WorldState::new(
            blockchain.get_last_block().clone(),
            ConsensusType::POS,
            Blockchain::new(Block::gen_genesis_block()),
            5,
            5,
            20,
            8,
            0.0,
        );
        tokio::spawn(async move {
            world.run(world_receiver).await;
        });
        tokio::time::sleep(Duration::from_secs(11)).await;
    }

    #[tokio::test]
    async fn collect_seeds() {
        let _ = env_logger::builder()
            .filter_level(log::LevelFilter::Info)
            .is_test(true)
            .try_init();

        let blockchain = Blockchain::new(Block::gen_genesis_block());
        let (mut world, world_sender, world_receiver) = WorldState::new(
            blockchain.get_last_block().clone(),
            ConsensusType::POS,
            Blockchain::new(Block::gen_genesis_block()),
            5,
            5,
            20,
            8,
            0.0,
        );

        let validators = world.validators.clone();
        let current_slot = world.current_slot.clone();
        let mut node0 = Node::new(
            0,
            0,
            0,
            blockchain.clone(),
            world_sender.clone(),
            1000,
            ConsensusType::TopoStake,
            0,
        );
        let mut node1 = Node::new(
            1,
            0,
            0,
            blockchain,
            world_sender.clone(),
            1000,
            ConsensusType::TopoStake,
            0,
        );
        let node0_sender = node0.sender.clone();
        let node1_sender = node1.sender.clone();
        let node0_wallet = node0.wallet.clone();
        let node1_wallet = node1.wallet.clone();
        let node0_bc = node0.blockchain.clone();
        let node0_tx_cache = node0.transaction_paths_cache.clone();

        world
            .nodes_sender
            .insert(node0_wallet.address.clone(), node0_sender.clone());
        world
            .nodes_sender
            .insert(node1_wallet.address.clone(), node1_sender.clone());

        node0.neighbors.push(Neighbor::new(
            node1.index,
            node1.wallet.address.clone(),
            node1.sender.clone(),
        ));
        node1.neighbors.push(Neighbor::new(
            node0.index,
            node0.wallet.address.clone(),
            node0.sender.clone(),
        ));

        let handle_world = tokio::spawn(async move {
            world.run(world_receiver).await;
        });
        let handle0 = tokio::spawn(async move {
            node0.run().await;
        });
        let handle1 = tokio::spawn(async move {
            node1.run().await;
        });
        //become validator

        let nodes_address = vec![node0_wallet.address.clone(), node1_wallet.address.clone()];
        let mut stake_map: std::collections::HashMap<String, f64> =
            std::collections::HashMap::new();
        for (i, address) in nodes_address.iter().enumerate() {
            stake_map.insert(address.clone(), 1.0);
        }
        let stake_json = serde_json::to_vec(&stake_map).unwrap_or_default();

        node0_sender
            .send(Message::new_become_validator_msg(stake_json.clone()))
            .await
            .unwrap();
        node1_sender
            .send(Message::new_become_validator_msg(stake_json))
            .await
            .unwrap();
        tokio::time::sleep(Duration::from_secs(1)).await;
        {
            let validators = validators.read().await.clone();
            info!("validators:{:?}", validators);
        }

        //send seed
        node0_sender
            .send(Message::new_send_randao_seed_msg())
            .await
            .unwrap();
        node1_sender
            .send(Message::new_send_randao_seed_msg())
            .await
            .unwrap();
        tokio::time::sleep(Duration::from_secs(1)).await;
        {
            let current_slot = current_slot.read().await.clone();
            info!("current_slot:{:?}", current_slot);
        }

        //node0发送交易
        let transaction = Transaction::new(node1_wallet.address.clone(), 0, node0_wallet.clone());
        let transaction_paths = TransactionPaths::new(transaction);
        node0_sender
            .send(Message::new_transaction_paths_msg(
                transaction_paths,
                "".to_string(),
            ))
            .await
            .unwrap();

        //wait for next slot
        tokio::time::sleep(Duration::from_secs(5)).await;
        {
            node0_bc.read().await.simple_print_last_five_block();
        }
        {
            let txs_cache = node0_tx_cache.read().await;
            info!("txs_cache:{:?}", txs_cache);
        }

        //node1发送交易
        let transaction = Transaction::new(node0_wallet.address, 0, node1_wallet);
        let transaction_paths = TransactionPaths::new(transaction);
        node1_sender
            .send(Message::new_transaction_paths_msg(
                transaction_paths,
                "".to_string(),
            ))
            .await
            .unwrap();

        //wait for next slot
        tokio::time::sleep(Duration::from_secs(5)).await;
        {
            node0_bc.read().await.simple_print_last_five_block();
        }
        {
            let txs_cache = node0_tx_cache.read().await;
            info!("txs_cache:{:?}", txs_cache);
        }
    }

    #[tokio::test]
    async fn test_flat_map() {
        let a = vec![vec![1, 2, 3], vec![4, 5, 6], vec![7, 8, 9]];
        let b = vec![vec![7, 8, 9], vec![10, 11, 12], vec![13, 14, 15]];
        let c = vec![a, b];
        let d: Vec<Vec<i32>> = c.iter().flat_map(|v| v.clone()).collect();
        println!("{:?}", d);
    }
}
