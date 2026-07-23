use crate::blockchain::block::{Block, BlockError, Body};
use crate::blockchain::path::{conflicting_receipt_count, AggregatedSignedPaths, TransactionPaths};
use crate::blockchain::transaction::Transaction;
use crate::blockchain::{BlockChainError, Blockchain};
use crate::consensus::minotaur::MinotaurConsensus;
use crate::consensus::pos::PosConsensus;
use crate::consensus::pow::PowConsensus;
use crate::consensus::topostake::{TopoStakeConfig, TopoStakeConsensus};
use crate::consensus::{Consensus, ConsensusMetricsSnapshot, ConsensusType, RandaoSeed, Validator};
use crate::metrics::{
    self, calculate_hhi, calculate_stake_concentration, EpochMetrics, NodeEpochMetrics, RunSummary,
    SlotMetrics,
};
use crate::network::{calculate_gini, AdaptiveRelayConfig, RelayProfile};
use crate::network::message::Message;
use crate::tools;
use crate::tools::get_timestamp;
use crate::wallet::Wallet;
use log::{debug, error, info, warn};
use rand::rngs::StdRng;
use rand::seq::SliceRandom;
use rand::SeedableRng;
use rand_distr::{Distribution, LogNormal};
use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};
use std::fmt;
use std::io::Write;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
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
    pub account_balances: Arc<RwLock<HashMap<String, f64>>>,
    // sender和receiver要和WorldState解耦，独立返回
    // pub sender: Sender<Message>,
    // pub receiver: Receiver<Message>,
    // pub nodes_balance: HashMap<String, u64>,
    pub nodes_sender: HashMap<String, Sender<Message>>,
    pub node_wallets: HashMap<String, Wallet>,
    pub node_mempools: HashMap<String, Arc<RwLock<HashMap<String, Arc<TransactionPaths>>>>>,
    pub node_relay_profiles: HashMap<String, String>,
    pub node_relay_forward_counters: HashMap<String, Arc<AtomicU64>>,
    adaptive_relay_config: AdaptiveRelayConfig,
    adaptive_relay_costs: HashMap<String, f64>,
    adaptive_benefit_ema: Option<f64>,
    adaptive_observation_window: AdaptiveObservationWindow,
    adaptive_update_round: u64,
    adaptive_failure_seed: u64,
    pub node_availability: HashMap<String, Arc<AtomicBool>>,
    pub blockchain: Arc<RwLock<Blockchain>>,
    pub consensus: Box<dyn Consensus>,
    consensus_name: String,
    metrics_filename: String,
    metrics_slots_file: Option<std::fs::File>,
    epoch_metrics_filename: PathBuf,
    epoch_metrics_file: Option<std::fs::File>,
    node_epoch_metrics_filename: PathBuf,
    node_epoch_metrics_file: Option<std::fs::File>,
    adaptive_relay_metrics_filename: PathBuf,
    adaptive_relay_metrics_file: Option<std::fs::File>,
    inclusion_samples_filename: PathBuf,
    inclusion_samples_file: Option<std::fs::File>,
    generation_samples_filename: PathBuf,
    generation_samples_file: Option<std::fs::File>,
    run_summary_filename: PathBuf,
    proposer_duties_filename: PathBuf,
    proposer_duties_file: Option<std::fs::File>,
    run_id: String,
    slot_duration: Duration,
    real_slot_duration: Duration,
    slot_per_epoch: u64,
    election_seed: u64,
    outage_start_epoch: u64,
    outage_duration_epochs: u64,
    outage_validator_indices: HashSet<u32>,
    outage_validator_addresses: HashSet<String>,
    outage_common_slot_randomness: bool,
    pub logical_slot_counter: Arc<AtomicU64>,
    generated_tx_counter: Arc<AtomicU64>,
    last_generated_tx_counter: u64,
    fee_spent: Arc<std::sync::Mutex<HashMap<String, f64>>>,
    pub nodes_index: HashMap<String, u32>,
    pub adversarial_nodes: HashSet<String>,
    pub focal_relayer_nodes: HashSet<String>,
    pub node_degrees: HashMap<String, usize>,
    pub node_betweenness: HashMap<String, f64>,
    last_relay_forward_attempts: HashMap<String, u64>,
    epoch_proposer_counts: HashMap<String, u64>,
    total_included_tx: u64,
    total_reward_income: HashMap<String, f64>,
    // 出块成功率统计
    pub block_production_success: usize, // 成功出块数
    pub block_production_failed: usize,  // 失败出块数
    last_block_production_success: usize,
    last_block_production_failed: usize,
    pub base_reward: f64, // 所有共识的固定奖励
    reward_reinvestment_rate: f64,
    pub max_epochs: u64,  // 最大运行Epoch数
    max_tx_per_block: usize,
    confirmation_latency_adjustment_s: f64,
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

#[derive(Default)]
struct EpochRewardReport {
    proposer_by_address: HashMap<String, f64>,
    relay_by_address: HashMap<String, f64>,
    total_proposer_reward: f64,
    total_relay_reward: f64,
    burned_relay_fee: f64,
}

#[derive(Default, Debug, Clone)]
struct AdaptiveGroupObservation {
    stake_exposure: f64,
    expected_reward: f64,
    forward_attempts: u64,
}

impl AdaptiveGroupObservation {
    fn expected_reward_per_stake(&self) -> Option<f64> {
        if self.stake_exposure > 0.0 {
            Some(self.expected_reward / self.stake_exposure)
        } else {
            None
        }
    }

    fn forwards_per_stake(&self) -> Option<f64> {
        if self.stake_exposure > 0.0 {
            Some(self.forward_attempts as f64 / self.stake_exposure)
        } else {
            None
        }
    }
}

#[derive(Default, Debug, Clone)]
struct AdaptiveObservationWindow {
    epochs: u64,
    active: AdaptiveGroupObservation,
    lazy: AdaptiveGroupObservation,
}

impl AdaptiveObservationWindow {
    fn observed_benefit_per_forward(&self) -> Option<f64> {
        let reward_premium = self.active.expected_reward_per_stake()?
            - self.lazy.expected_reward_per_stake()?;
        let work_premium =
            self.active.forwards_per_stake()? - self.lazy.forwards_per_stake()?;
        if work_premium > 0.0 && reward_premium.is_finite() {
            Some(reward_premium / work_premium)
        } else {
            None
        }
    }
}

#[derive(Default, Debug, Clone)]
struct OrganicCaptureReport {
    included_tx: u64,
    valid_path_count: u64,
    relay_reward: f64,
    adversary_relay_reward: f64,
    raw_contribution: f64,
    adversary_raw_contribution: f64,
}

impl OrganicCaptureReport {
    fn adversary_relay_reward_share(&self) -> f64 {
        if self.relay_reward > 0.0 {
            self.adversary_relay_reward / self.relay_reward
        } else {
            0.0
        }
    }

    fn adversary_raw_contribution_share(&self) -> f64 {
        if self.raw_contribution > 0.0 {
            self.adversary_raw_contribution / self.raw_contribution
        } else {
            0.0
        }
    }
}

impl EpochRewardReport {
    fn total_by_address(&self) -> HashMap<String, f64> {
        let mut totals = self.proposer_by_address.clone();
        for (address, reward) in &self.relay_by_address {
            *totals.entry(address.clone()).or_insert(0.0) += reward;
        }
        totals
    }
}

fn reinvest_epoch_rewards(
    validators: &[Validator],
    rewards: &EpochRewardReport,
    rate: f64,
) -> Vec<Validator> {
    let rate = if rate.is_finite() {
        rate.clamp(0.0, 1.0)
    } else {
        0.0
    };
    let total_rewards = rewards.total_by_address();
    validators
        .iter()
        .cloned()
        .map(|mut validator| {
            let reward = total_rewards
                .get(&validator.address)
                .copied()
                .unwrap_or(0.0)
                .max(0.0);
            validator.stake += rate * reward;
            validator
        })
        .collect()
}

#[derive(Serialize, Deserialize)]
pub struct LogicalTxMetadata {
    pub created_epoch: u64,
    pub created_slot: u64,
}

pub fn logical_tx_metadata(created_epoch: u64, created_slot: u64) -> Vec<u8> {
    serde_json::to_vec(&LogicalTxMetadata {
        created_epoch,
        created_slot,
    })
    .unwrap_or_default()
}

fn tx_logical_slot(tx: &Transaction, slots_per_epoch: u64) -> Option<u64> {
    let metadata: LogicalTxMetadata = serde_json::from_slice(&tx.data).ok()?;
    Some(metadata.created_epoch * slots_per_epoch + metadata.created_slot)
}

fn logical_time_seconds(epoch: u64, slot: u64, slots_per_epoch: u64, slot_duration: u64) -> u64 {
    (epoch * slots_per_epoch + slot) * slot_duration
}

fn derive_election_seed(election_seed: u64, epoch: u64, slot: u64, block_index: u64) -> [u8; 32] {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(&election_seed.to_le_bytes());
    bytes.extend_from_slice(&epoch.to_le_bytes());
    bytes.extend_from_slice(&slot.to_le_bytes());
    bytes.extend_from_slice(&block_index.to_le_bytes());
    tools::Hasher::hash(bytes)
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
        topostake_config: TopoStakeConfig,
        base_reward: f64,
        reward_reinvestment_rate: f64,
        node_num: u32,
        trans_num: u32,
        topology: String,
        max_epochs: u64,
        max_tx_per_block: usize,
        output_dir: PathBuf,
        run_id: String,
        election_seed: u64,
        real_time: bool,
        time_scale: f64,
        confirmation_latency_adjustment_s: f64,
        generated_tx_counter: Arc<AtomicU64>,
        fee_spent: Arc<std::sync::Mutex<HashMap<String, f64>>>,
    ) -> (Self, Sender<Message>, Receiver<Message>) {
        let (sender, receiver) = tokio::sync::mpsc::channel(4096);
        let nodes_sender: HashMap<String, Sender<Message>> = HashMap::new();
        let slot_duration = Duration::from_secs(slot_duration_secs);
        let real_slot_duration = if real_time {
            slot_duration
        } else {
            Duration::from_secs_f64(slot_duration.as_secs_f64() * time_scale.max(f64::EPSILON))
        };
        let consensus_name = consensus_type.to_string();
        let consensus: Box<dyn Consensus> = match consensus_type {
            ConsensusType::TopoStake => Box::new(
                TopoStakeConsensus::new(base_reward, topostake_config.clone())
                    .expect("invalid TopoStake config"),
            ),
            ConsensusType::POS => Box::new(PosConsensus::new(base_reward)),
            ConsensusType::POW => Box::new(PowConsensus::new(
                pow_difficulty,
                pow_max_threads,
                slot_duration,
                base_reward,
            )),
            ConsensusType::MINOTAUR => {
                Box::new(MinotaurConsensus::new(base_reward, pow_max_threads))
            }
        };
        // Initialize metrics files - delete old file and create new one
        let _ = std::fs::create_dir_all(&output_dir);
        let metrics_filename = match consensus_type {
            ConsensusType::TopoStake => format!(
                "slot_metrics_{}_n_{}_t_{}_{}_D_{}_beta_{}_eta_{}_cap_{}.csv",
                consensus_name,
                node_num,
                trans_num,
                topology,
                topostake_config.target_depth,
                topostake_config.beta,
                topostake_config.eta,
                topostake_config.bonus_cap
            ),
            _ => format!(
                "slot_metrics_{}_n_{}_t_{}_{}.csv",
                consensus_name, node_num, trans_num, topology
            ),
        };
        let metrics_path = output_dir.join(metrics_filename);
        let epoch_metrics_filename = output_dir.join("epoch_metrics.csv");
        let node_epoch_metrics_filename = output_dir.join("node_epoch_metrics.csv");
        let adaptive_relay_metrics_filename = output_dir.join("adaptive_relay_metrics.csv");
        let inclusion_samples_filename = output_dir.join("inclusion_samples.csv");
        let generation_samples_filename = output_dir.join("generation_samples.csv");
        let run_summary_filename = output_dir.join("run_summary.json");
        let proposer_duties_filename = output_dir.join("proposer_duties.csv");
        let _ = std::fs::remove_file(&metrics_path);
        let _ = std::fs::remove_file(&epoch_metrics_filename);
        let _ = std::fs::remove_file(&node_epoch_metrics_filename);
        let _ = std::fs::remove_file(&adaptive_relay_metrics_filename);
        let _ = std::fs::remove_file(&inclusion_samples_filename);
        let _ = std::fs::remove_file(&generation_samples_filename);
        let _ = std::fs::remove_file(&run_summary_filename);
        let _ = std::fs::remove_file(&proposer_duties_filename);
        let metrics_slots_file = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&metrics_path)
            .ok();
        let epoch_metrics_file = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&epoch_metrics_filename)
            .ok();
        let node_epoch_metrics_file = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&node_epoch_metrics_filename)
            .ok();
        let adaptive_relay_metrics_file = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&adaptive_relay_metrics_filename)
            .ok();
        let inclusion_samples_file = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&inclusion_samples_filename)
            .ok();
        let generation_samples_file = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&generation_samples_filename)
            .ok();
        let proposer_duties_file = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&proposer_duties_filename)
            .ok();

        (
            WorldState {
                current_slot: Arc::new(RwLock::new(SlotManager {
                    randao_seeds: vec![],
                    slot_duration,
                    current_epoch: 0,
                    current_slot: 0,
                    next_seed: derive_election_seed(election_seed, 0, 0, 0),
                    start_timestamp: genesis_block.header.timestamp,
                })),
                validators: Arc::new(RwLock::new(vec![])),
                account_balances: Arc::new(RwLock::new(HashMap::new())),
                nodes_sender,
                node_wallets: HashMap::new(),
                node_mempools: HashMap::new(),
                node_relay_profiles: HashMap::new(),
                node_relay_forward_counters: HashMap::new(),
                adaptive_relay_config: AdaptiveRelayConfig::default(),
                adaptive_relay_costs: HashMap::new(),
                adaptive_benefit_ema: None,
                adaptive_observation_window: AdaptiveObservationWindow::default(),
                adaptive_update_round: 0,
                adaptive_failure_seed: 0,
                node_availability: HashMap::new(),
                blockchain: Arc::new(RwLock::new(blockchain)),
                consensus,
                consensus_name,
                metrics_filename: metrics_path.to_string_lossy().to_string(),
                metrics_slots_file,
                epoch_metrics_filename,
                epoch_metrics_file,
                node_epoch_metrics_filename,
                node_epoch_metrics_file,
                adaptive_relay_metrics_filename,
                adaptive_relay_metrics_file,
                inclusion_samples_filename,
                inclusion_samples_file,
                generation_samples_filename,
                generation_samples_file,
                run_summary_filename,
                proposer_duties_filename,
                proposer_duties_file,
                run_id,
                slot_duration,
                real_slot_duration,
                slot_per_epoch,
                election_seed,
                outage_start_epoch: u64::MAX,
                outage_duration_epochs: 0,
                outage_validator_indices: HashSet::new(),
                outage_validator_addresses: HashSet::new(),
                outage_common_slot_randomness: false,
                logical_slot_counter: Arc::new(AtomicU64::new(0)),
                generated_tx_counter,
                last_generated_tx_counter: 0,
                fee_spent,
                nodes_index: HashMap::new(),
                adversarial_nodes: HashSet::new(),
                focal_relayer_nodes: HashSet::new(),
                node_degrees: HashMap::new(),
                node_betweenness: HashMap::new(),
                last_relay_forward_attempts: HashMap::new(),
                epoch_proposer_counts: HashMap::new(),
                total_included_tx: 0,
                total_reward_income: HashMap::new(),
                block_production_success: 0,
                block_production_failed: 0,
                last_block_production_success: 0,
                last_block_production_failed: 0,
                base_reward,
                reward_reinvestment_rate: if reward_reinvestment_rate.is_finite() {
                    reward_reinvestment_rate.clamp(0.0, 1.0)
                } else {
                    0.0
                },
                max_epochs,
                max_tx_per_block,
                confirmation_latency_adjustment_s,
            },
            sender,
            receiver,
        )
    }

    pub fn configure_adaptive_relay(
        &mut self,
        config: AdaptiveRelayConfig,
        failure_seed: u64,
    ) {
        self.adaptive_relay_config = config;
        self.adaptive_failure_seed = failure_seed;
        self.adaptive_relay_costs.clear();
        self.adaptive_benefit_ema = None;
        self.adaptive_observation_window = AdaptiveObservationWindow::default();
        self.adaptive_update_round = 0;
        if !self.adaptive_relay_config.enabled {
            return;
        }

        let median = self.adaptive_relay_config.cost_reference
            * self.adaptive_relay_config.cost_median_multiplier;
        let distribution = LogNormal::new(
            median.ln(),
            self.adaptive_relay_config.cost_log_sigma,
        )
        .expect("validated adaptive relay cost distribution");
        let mut rng = StdRng::seed_from_u64(failure_seed ^ 0x4144_4150_5449_5645);
        let mut addresses: Vec<String> = self.nodes_index.keys().cloned().collect();
        addresses.sort_by(|left, right| {
            self.nodes_index
                .get(left)
                .cmp(&self.nodes_index.get(right))
                .then_with(|| left.cmp(right))
        });
        for address in addresses {
            self.adaptive_relay_costs
                .insert(address, distribution.sample(&mut rng));
        }
        info!(
            "Adaptive relay participation enabled: validators={}, median_cost={:.3e}, log_sigma={:.3}",
            self.adaptive_relay_costs.len(),
            median,
            self.adaptive_relay_config.cost_log_sigma
        );
    }

    /// Configure an evaluation-only sustained outage after node indices and
    /// shared availability flags have been registered by the network builder.
    pub fn configure_scheduled_outage(
        &mut self,
        start_epoch: u64,
        duration_epochs: u64,
        validator_ids: &str,
        common_slot_randomness: bool,
    ) {
        self.outage_start_epoch = start_epoch;
        self.outage_duration_epochs = duration_epochs;
        self.outage_common_slot_randomness = common_slot_randomness;
        self.outage_validator_indices = validator_ids
            .split(',')
            .filter_map(|value| {
                let trimmed = value.trim();
                if trimmed.is_empty() {
                    None
                } else {
                    match trimmed.parse::<u32>() {
                        Ok(index) => Some(index),
                        Err(_) => {
                            warn!("Ignoring invalid outage validator id: {}", trimmed);
                            None
                        }
                    }
                }
            })
            .collect();
        self.outage_validator_addresses = self
            .nodes_index
            .iter()
            .filter_map(|(address, index)| {
                self.outage_validator_indices
                    .contains(index)
                    .then(|| address.clone())
            })
            .collect();
        if !self.outage_validator_indices.is_empty()
            && self.outage_validator_addresses.len() != self.outage_validator_indices.len()
        {
            warn!(
                "Scheduled outage resolved {} of {} validator ids",
                self.outage_validator_addresses.len(),
                self.outage_validator_indices.len()
            );
        }
        info!(
            "Scheduled outage: start_epoch={}, duration_epochs={}, validators={:?}, common_slot_randomness={}",
            self.outage_start_epoch,
            self.outage_duration_epochs,
            self.outage_validator_indices,
            self.outage_common_slot_randomness
        );
    }

    fn scheduled_outage_active(&self, epoch: u64) -> bool {
        if self.outage_validator_addresses.is_empty() || epoch < self.outage_start_epoch {
            return false;
        }
        self.outage_duration_epochs == 0
            || epoch < self.outage_start_epoch.saturating_add(self.outage_duration_epochs)
    }

    fn update_scheduled_availability(&self, epoch: u64) {
        let outage_active = self.scheduled_outage_active(epoch);
        for (address, available) in &self.node_availability {
            let should_be_online =
                !outage_active || !self.outage_validator_addresses.contains(address);
            available.store(should_be_online, Ordering::Relaxed);
        }
    }

    fn write_proposer_duty(
        &mut self,
        slot: &SlotManager,
        proposer: &Validator,
        proposer_weight: f64,
        scheduled_online: bool,
        block_produced: bool,
        failure_reason: &str,
    ) {
        let validator_id = self
            .nodes_index
            .get(&proposer.address)
            .map(|index| index.to_string())
            .unwrap_or_default();
        let outage_active = self.scheduled_outage_active(slot.current_epoch);
        let outage_group = self.outage_validator_addresses.contains(&proposer.address);
        if self.proposer_duties_file.is_none() {
            self.proposer_duties_file = std::fs::OpenOptions::new()
                .create(true)
                .append(true)
                .open(&self.proposer_duties_filename)
                .ok();
        }
        if let Some(file) = self.proposer_duties_file.as_mut() {
            if file.metadata().map(|metadata| metadata.len()).unwrap_or(0) == 0 {
                let _ = writeln!(
                    file,
                    "epoch,slot,validator_id,proposer_address,proposer_stake,proposer_weight,outage_active,outage_group,scheduled_online,block_produced,failure_reason"
                );
            }
            let _ = writeln!(
                file,
                "{},{},{},{},{:.9},{:.9},{},{},{},{},{}",
                slot.current_epoch,
                slot.current_slot,
                validator_id,
                proposer.address,
                proposer.stake,
                proposer_weight,
                outage_active,
                outage_group,
                scheduled_online,
                block_produced,
                failure_reason,
            );
            let _ = file.flush();
        }
    }

    pub async fn next_slot(&mut self) {
        let current_slot = self.current_slot.read().await.clone();
        let block_index = self.blockchain.read().await.get_last_index();
        let validators = self.validators.read().await.clone();

        if current_slot.current_slot >= self.slot_per_epoch - 1 {
            //更新epoch
            self.next_epoch().await;
        } else {
            let next_slot = current_slot.current_slot + 1;
            let seed_block_index = if self.outage_common_slot_randomness {
                0
            } else {
                block_index + 1
            };
            let next_seed = derive_election_seed(
                self.election_seed,
                current_slot.current_epoch,
                next_slot,
                seed_block_index,
            );
            self.current_slot = Arc::new(RwLock::new(SlotManager {
                randao_seeds: vec![],
                slot_duration: self.slot_duration,
                current_epoch: current_slot.current_epoch,
                current_slot: next_slot,
                next_seed,
                start_timestamp: get_timestamp(),
            }));
        }
        self.consensus.next_slot(&validators, block_index);
        self.logical_slot_counter.fetch_add(1, Ordering::Relaxed);
        let current_slot = self.get_current_slot().await;
        self.update_scheduled_availability(current_slot.current_epoch);
        let selection_seed = current_slot.next_seed;
        info!(
            "World State change slot to: epoch[{}] slot[{}] consensus[{}] seed{:?}",
            current_slot.current_epoch,
            current_slot.current_slot,
            self.consensus.state_summary(),
            selection_seed
        );

        let nodes_sender: Vec<Sender<Message>> = self.nodes_sender.values().cloned().collect();

        //通知所有节点更新slot。控制消息必须可靠送达，否则节点的本地
        //epoch/slot 会落后，后续交易的 logical metadata 和 randao 都会被污染。
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
            if let Some(sender) = self.nodes_sender.get(&v.address) {
                if let Err(e) = sender.send(Message::new_send_randao_seed_msg()).await {
                    error!("World State error: send new randao seed msg failed {:?}", e);
                }
            }
        }

        //获得出块节点
        let bc = self.blockchain.read().await.clone();
        let miner_validator = match self
            .consensus
            .select_proposer(&validators, selection_seed, &bc)
        {
            Ok(miner) => miner,
            Err(e) => {
                warn!("World State error: select proposer failed: {}", e);
                return;
            }
        };
        *self
            .epoch_proposer_counts
            .entry(miner_validator.address.clone())
            .or_insert(0) += 1;

        debug!(
            "World State find miner: {}",
            miner_validator.address.clone()
        );
        let scheduled_online = self
            .node_availability
            .get(&miner_validator.address)
            .map(|available| available.load(Ordering::Relaxed))
            .unwrap_or(true);
        let mut produced = false;
        let mut failure_reason = "";
        if !scheduled_online {
            warn!(
                "Scheduled outage: proposer {} missed epoch {} slot {}",
                miner_validator.address, current_slot.current_epoch, current_slot.current_slot
            );
            self.block_production_failed += 1;
            failure_reason = "scheduled_outage";
        } else {
            match self
                .build_canonical_block(
                    &miner_validator,
                    current_slot.current_epoch,
                    current_slot.current_slot,
                )
                .await
            {
                Ok(block) => {
                    if let Err(e) = self.apply_canonical_block(&block).await {
                        error!("World State Add Block Error: {}", e);
                        self.block_production_failed += 1;
                        failure_reason = "apply_failed";
                    } else {
                        produced = true;
                        let block_arc = Arc::new(block);
                        let miner_address = miner_validator.address.clone();
                        for sender in self.nodes_sender.values() {
                            let _ = sender.try_send(Message::new_block_msg(
                                block_arc.clone(),
                                miner_address.clone(),
                            ));
                        }
                    }
                }
                Err(e) => {
                    error!(
                        "World State error: failed to build canonical block for miner {}: {}",
                        miner_validator.address, e
                    );
                    self.block_production_failed += 1;
                    failure_reason = "build_failed";
                }
            }
        }

        let duty_snapshot = self.consensus.metrics_snapshot();
        let proposer_weight = if duty_snapshot.normalized_proposer_weights.is_empty() {
            TopoStakeConsensus::normalized_stake(&validators)
                .get(&miner_validator.address)
                .copied()
                .unwrap_or(0.0)
        } else {
            duty_snapshot
                .normalized_proposer_weights
                .get(&miner_validator.address)
                .copied()
                .unwrap_or(0.0)
        };
        self.write_proposer_duty(
            &current_slot,
            &miner_validator,
            proposer_weight,
            scheduled_online,
            produced,
            failure_reason,
        );
        if produced {
            self.collect_slot_metrics(&miner_validator).await;
        }
    }

    pub async fn next_epoch(&mut self) {
        let current_slot = self.current_slot.read().await.clone();
        let _current_epoch = current_slot.current_epoch;
        let next_epoch = current_slot.current_epoch + 1;
        // Close the asynchronous onset window before exposing an outage epoch.
        // Recovery remains after the old-epoch sample so resumed forwarding is
        // attributed to the new online epoch rather than the final outage one.
        if self.scheduled_outage_active(next_epoch) {
            self.update_scheduled_availability(next_epoch);
        }
        //更新epoch中调用consensus的on_epoch_end
        let blocks = self.blockchain.read().await.get_last_epoch_block();
        let validators = self.validators.read().await.clone();
        self.consensus.on_epoch_end(&blocks, &validators);
        let next_validators = self
            .collect_epoch_metrics(current_slot.current_epoch, &blocks, &validators)
            .await;
        if self.reward_reinvestment_rate > 0.0 {
            *self.validators.write().await = next_validators.clone();
            self.consensus.on_stake_update(&next_validators);
        }
        if !self.scheduled_outage_active(next_epoch) {
            self.update_scheduled_availability(next_epoch);
        }
        let seed_block_index = if self.outage_common_slot_randomness {
            0
        } else {
            self.blockchain.read().await.get_last_index() + 1
        };
        let next_seed = derive_election_seed(
            self.election_seed,
            next_epoch,
            0,
            seed_block_index,
        );
        self.current_slot = Arc::new(RwLock::new(SlotManager {
            randao_seeds: vec![],
            slot_duration: self.slot_duration,
            current_epoch: next_epoch,
            current_slot: 0,
            next_seed,
            start_timestamp: get_timestamp(),
        }));

        // 打印每个 epoch 的节点余额信息
        let effective_validators = if self.reward_reinvestment_rate > 0.0 {
            &next_validators
        } else {
            &validators
        };
        let mut node_stakes: Vec<(u32, f64)> = effective_validators
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

        if current_slot.current_epoch + 1 >= self.max_epochs {
            info!("Reached max epochs ({}), shutting down...", self.max_epochs);
            self.write_run_summary(current_slot.current_epoch + 1).await;
            std::process::exit(0);
        }
    }

    pub async fn get_current_slot(&self) -> SlotManager {
        self.current_slot.read().await.clone()
    }

    async fn build_canonical_block(
        &self,
        miner: &Validator,
        epoch: u64,
        slot: u64,
    ) -> Result<Block, BlockError> {
        let wallet = self
            .node_wallets
            .get(&miner.address)
            .cloned()
            .ok_or(BlockError::InvalidBlock)?;
        let mempool = self
            .node_mempools
            .get(&miner.address)
            .cloned()
            .ok_or(BlockError::InvalidBlock)?;

        let transaction_paths_to_pack = {
            let transaction_paths_cache = mempool.read().await;
            let blockchain = self.blockchain.read().await;
            let mut valid_paths: Vec<Arc<TransactionPaths>> = transaction_paths_cache
                .values()
                .filter(|paths| !blockchain.exist_transaction(&paths.transaction.hash))
                .cloned()
                .collect();

            valid_paths.sort_by(|a, b| {
                b.transaction
                    .fee
                    .partial_cmp(&a.transaction.fee)
                    .unwrap_or(std::cmp::Ordering::Equal)
                    .then_with(|| a.transaction.timestamp.cmp(&b.transaction.timestamp))
            });
            valid_paths.truncate(self.max_tx_per_block);
            valid_paths
        };

        if !transaction_paths_to_pack.is_empty() {
            let mut transaction_paths_cache = mempool.write().await;
            for paths in &transaction_paths_to_pack {
                transaction_paths_cache.remove(&paths.transaction.hash);
            }
        }

        let mut transactions = Vec::with_capacity(transaction_paths_to_pack.len());
        let mut paths = Vec::with_capacity(transaction_paths_to_pack.len());
        for transaction_paths in transaction_paths_to_pack {
            transactions.push(transaction_paths.transaction.clone());
            paths.push(AggregatedSignedPaths::from_transaction_paths(
                transaction_paths.as_ref().clone(),
            ));
        }

        let (last_index, last_hash) = {
            let blockchain = self.blockchain.read().await;
            (blockchain.get_last_index(), blockchain.get_last_hash())
        };
        Block::new(
            last_index + 1,
            epoch,
            slot,
            last_hash,
            Body::new(transactions, paths),
            wallet,
        )
    }

    async fn apply_canonical_block(&mut self, block: &Block) -> Result<(), BlockChainError> {
        {
            self.blockchain.write().await.add_block(block.clone())?;
        }
        self.block_production_success += 1;

        let validators_snapshot = self.validators.read().await.clone();
        let reward_deltas = self.consensus.distribute_rewards(
            block,
            &validators_snapshot,
            self.nodes_index.clone(),
        );

        let balance_updates = {
            let mut balances = self.account_balances.write().await;
            let mut touched = HashSet::new();
            for delta in reward_deltas {
                let address = delta.address;
                *balances.entry(address.clone()).or_insert(0.0) += delta.amount;
                touched.insert(address);
            }
            touched
                .into_iter()
                .filter_map(|address| balances.get(&address).map(|balance| (address, *balance)))
                .collect::<Vec<_>>()
        };

        for (address, balance) in balance_updates {
            if let Some(sender) = self.nodes_sender.get(&address) {
                if let Err(e) = sender
                    .send(Message::new_update_node_balance_msg(balance))
                    .await
                {
                    warn!(
                        "Failed to send UpdateNodeBalance to {}: {}",
                        &address[..8.min(address.len())],
                        e
                    );
                }
            }
        }

        Ok(())
    }

    async fn collect_slot_metrics(&mut self, miner: &Validator) {
        let current_slot = self.current_slot.read().await.clone();
        let validators = self.validators.read().await.clone();
        let blockchain = self.blockchain.read().await.clone();

        // Get last block for stats
        let last_block = blockchain.get_last_block();
        let tx_count = last_block.body.transactions.len();

        let throughput = tx_count as f64 / self.slot_duration.as_secs_f64().max(1.0);

        let paths = last_block.get_all_paths();
        let path_stats = metrics::calculate_path_stats(paths);

        // Calculate stake concentration from stakes
        let stake_values: Vec<f64> = validators.iter().map(|v| v.stake).collect();
        let stake_concentration = calculate_stake_concentration(&stake_values);
        let gini_coefficient = calculate_gini(&stake_values);

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
            timestamp: logical_time_seconds(
                current_slot.current_epoch,
                current_slot.current_slot,
                self.slot_per_epoch,
                self.slot_duration.as_secs(),
            ),
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
                .open(&self.metrics_filename)
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

    async fn collect_epoch_metrics(
        &mut self,
        epoch: u64,
        blocks: &[Block],
        validators: &[Validator],
    ) -> Vec<Validator> {
        let snapshot = self.consensus.metrics_snapshot();
        let generated_total = self.generated_tx_counter.load(Ordering::Relaxed);
        let generated_tx = generated_total.saturating_sub(self.last_generated_tx_counter);
        self.last_generated_tx_counter = generated_total;

        let epoch_blocks: Vec<Block> = blocks
            .iter()
            .filter(|block| block.header.index > 0 && block.header.epoch == epoch)
            .cloned()
            .collect();
        let included_tx: u64 = epoch_blocks
            .iter()
            .map(|block| block.body.transactions.len() as u64)
            .sum();
        self.total_included_tx += included_tx;

        let logical_epoch_secs =
            (self.slot_per_epoch as f64 * self.slot_duration.as_secs_f64()).max(1.0);
        let throughput = included_tx as f64 / logical_epoch_secs;

        let mut latencies = Vec::new();
        let mut path_lengths = Vec::new();
        let mut valid_path_count = 0u64;
        let mut invalid_path_count = 0u64;
        let mut conflict_count = 0u64;
        let mut inclusion_samples = Vec::new();
        for block in &epoch_blocks {
            for (idx, tx) in block.body.transactions.iter().enumerate() {
                let included_slot = block.header.epoch * self.slot_per_epoch + block.header.slot;
                let evidence_eligible = block.verify_path_evidence(idx);
                if let Some(created_slot) = tx_logical_slot(tx, self.slot_per_epoch) {
                    let slots = included_slot.saturating_sub(created_slot);
                    let latency = slots as f64 * self.slot_duration.as_secs_f64()
                        + self.confirmation_latency_adjustment_s;
                    let latency = latency.max(0.0);
                    latencies.push(latency);
                    inclusion_samples.push((
                        block.header.epoch,
                        tx.hash.clone(),
                        created_slot,
                        included_slot,
                        latency,
                        evidence_eligible,
                    ));
                }
                if let Some(path) = block.body.paths.get(idx) {
                    let full_path = path.full_path(block.header.miner.clone());
                    path_lengths.push(full_path.len().saturating_sub(1) as f64);
                    for receiver in &full_path {
                        conflict_count +=
                            conflicting_receipt_count(&tx.hash, path.epoch, receiver) as u64;
                    }
                }
                if evidence_eligible {
                    valid_path_count += 1;
                } else {
                    invalid_path_count += 1;
                }
            }
        }
        self.write_inclusion_samples(&inclusion_samples);

        let reward_report = self.estimate_epoch_rewards(&epoch_blocks, validators, &snapshot);
        let next_validators = reinvest_epoch_rewards(
            validators,
            &reward_report,
            self.reward_reinvestment_rate,
        );
        let organic_capture = self.organic_capture_report(&epoch_blocks, validators, &snapshot);
        for (address, reward) in reward_report.total_by_address() {
            *self.total_reward_income.entry(address).or_insert(0.0) += reward;
        }

        let stake_values: Vec<f64> = validators.iter().map(|v| v.stake).collect();
        let stake_gini = calculate_gini(&stake_values);
        let stake_hhi = calculate_hhi(&stake_values);
        let normalized_stake = TopoStakeConsensus::normalized_stake(validators);
        let proposer_weights = if snapshot.normalized_proposer_weights.is_empty() {
            normalized_stake.clone()
        } else {
            snapshot.normalized_proposer_weights.clone()
        };
        let proposer_weight_values: Vec<f64> = validators
            .iter()
            .map(|v| proposer_weights.get(&v.address).copied().unwrap_or(0.0))
            .collect();
        let proposer_weight_gini = calculate_gini(&proposer_weight_values);
        let proposer_weight_hhi = calculate_hhi(&proposer_weight_values);

        let stake_map: HashMap<String, f64> = validators
            .iter()
            .map(|v| (v.address.clone(), v.stake))
            .collect();
        let adversary_real_stake_share = metrics::share_for(&self.adversarial_nodes, &stake_map);
        let adversary_score_share =
            metrics::share_for(&self.adversarial_nodes, &snapshot.normalized_score);
        let adversary_damped_score_mass: f64 = self
            .adversarial_nodes
            .iter()
            .map(|address| {
                snapshot
                    .normalized_score
                    .get(address)
                    .copied()
                    .unwrap_or(0.0)
            })
            .sum();
        let adversary_proposer_weight_share =
            metrics::share_for(&self.adversarial_nodes, &proposer_weights);
        let eta = snapshot.topostake_eta.unwrap_or(0.0);
        let bonus_cap = snapshot.topostake_bonus_cap.unwrap_or(0.0);
        let zeta = snapshot.topostake_bonus_zeta.unwrap_or(1.0);
        let a = adversary_real_stake_share;
        let coalition_bonus = if a > 0.0 {
            TopoStakeConsensus::propagation_bonus(adversary_damped_score_mass / a, bonus_cap, zeta)
        } else {
            0.0
        };
        let coalition_weight = a * (1.0 + eta * coalition_bonus);
        let score_dependent_proposer_weight_bound = if coalition_weight + 1.0 - a > 0.0 {
            coalition_weight / (coalition_weight + 1.0 - a)
        } else {
            0.0
        };
        let c = eta * bonus_cap;
        let theoretical_proposer_weight_bound = if 1.0 + a * c > 0.0 {
            a * (1.0 + c) / (1.0 + a * c)
        } else {
            0.0
        };
        let proposer_total: u64 = self.epoch_proposer_counts.values().sum();
        let adversary_proposers: u64 = self
            .adversarial_nodes
            .iter()
            .map(|address| {
                self.epoch_proposer_counts
                    .get(address)
                    .copied()
                    .unwrap_or(0)
            })
            .sum();
        let observed_adversary_proposer_share = if proposer_total == 0 {
            0.0
        } else {
            adversary_proposers as f64 / proposer_total as f64
        };
        let epoch_success = self
            .block_production_success
            .saturating_sub(self.last_block_production_success);
        let epoch_failed = self
            .block_production_failed
            .saturating_sub(self.last_block_production_failed);
        let epoch_attempts = epoch_success + epoch_failed;
        let block_success_ratio = if epoch_attempts == 0 {
            0.0
        } else {
            epoch_success as f64 / epoch_attempts as f64
        };

        let epoch_metrics = EpochMetrics {
            epoch,
            generated_tx,
            included_tx,
            throughput,
            p50_inclusion_latency_s: metrics::percentile_f64(&latencies, 0.50),
            p95_inclusion_latency_s: metrics::percentile_f64(&latencies, 0.95),
            p99_inclusion_latency_s: metrics::percentile_f64(&latencies, 0.99),
            block_success_ratio,
            avg_path_length: if path_lengths.is_empty() {
                0.0
            } else {
                path_lengths.iter().sum::<f64>() / path_lengths.len() as f64
            },
            p95_path_length: metrics::percentile_f64(&path_lengths, 0.95),
            valid_path_count,
            invalid_path_count,
            conflicting_receipt_count: conflict_count,
            active_score_epoch: snapshot
                .topostake_active_score_epoch
                .map(|value| value as i64)
                .unwrap_or(-1),
            latest_score_epoch: snapshot
                .topostake_latest_score_epoch
                .map(|value| value as i64)
                .unwrap_or(-1),
            total_proposer_reward: reward_report.total_proposer_reward,
            total_relay_reward: reward_report.total_relay_reward,
            burned_relay_fee: reward_report.burned_relay_fee,
            organic_included_tx: organic_capture.included_tx,
            organic_valid_path_count: organic_capture.valid_path_count,
            organic_relay_reward: organic_capture.relay_reward,
            adversary_organic_relay_reward: organic_capture.adversary_relay_reward,
            adversary_organic_relay_reward_share: organic_capture
                .adversary_relay_reward_share(),
            organic_raw_contribution: organic_capture.raw_contribution,
            adversary_organic_raw_contribution: organic_capture.adversary_raw_contribution,
            adversary_organic_raw_contribution_share: organic_capture
                .adversary_raw_contribution_share(),
            stake_gini,
            stake_hhi,
            proposer_weight_gini,
            proposer_weight_hhi,
            adversary_real_stake_share,
            adversary_score_share,
            adversary_damped_score_mass,
            adversary_proposer_weight_share,
            score_dependent_proposer_weight_bound,
            theoretical_proposer_weight_bound,
            observed_adversary_proposer_share,
            bound_violation: adversary_proposer_weight_share
                > score_dependent_proposer_weight_bound + 1e-9,
        };
        self.write_epoch_metrics(&epoch_metrics);

        let balances = self.account_balances.read().await.clone();
        let fee_spent = self
            .fee_spent
            .lock()
            .map(|ledger| ledger.clone())
            .unwrap_or_default();
        let raw_contribution = self.raw_epoch_contribution(&epoch_blocks, validators, &snapshot);
        let mut epoch_forward_attempts = HashMap::new();
        for validator in validators {
            let cumulative = self
                .node_relay_forward_counters
                .get(&validator.address)
                .map(|counter| counter.load(Ordering::Relaxed))
                .unwrap_or(0);
            let previous = self
                .last_relay_forward_attempts
                .insert(validator.address.clone(), cumulative)
                .unwrap_or(0);
            epoch_forward_attempts.insert(
                validator.address.clone(),
                cumulative.saturating_sub(previous),
            );
        }
        for validator in validators {
            let s_hat = normalized_stake
                .get(&validator.address)
                .copied()
                .unwrap_or(0.0);
            let raw = raw_contribution
                .get(&validator.address)
                .copied()
                .unwrap_or(0.0);
            let saturated = TopoStakeConsensus::saturated_contribution(
                raw,
                s_hat,
                snapshot.topostake_saturation_k.unwrap_or(1.0),
            );
            let proposer_reward = reward_report
                .proposer_by_address
                .get(&validator.address)
                .copied()
                .unwrap_or(0.0);
            let relay_reward = reward_report
                .relay_by_address
                .get(&validator.address)
                .copied()
                .unwrap_or(0.0);
            let fee = fee_spent.get(&validator.address).copied().unwrap_or(0.0);
            let relay_forward_attempts = epoch_forward_attempts
                .get(&validator.address)
                .copied()
                .unwrap_or(0);
            let node_metrics = NodeEpochMetrics {
                epoch,
                validator_id: self
                    .nodes_index
                    .get(&validator.address)
                    .map(|idx| idx.to_string())
                    .unwrap_or_else(|| validator.address.clone()),
                relay_profile: self
                    .node_relay_profiles
                    .get(&validator.address)
                    .cloned()
                    .unwrap_or_else(|| "normal".to_string()),
                focal_relayer: self.focal_relayer_nodes.contains(&validator.address),
                adversarial: self.adversarial_nodes.contains(&validator.address),
                economic_stake: validator.stake,
                balance: balances.get(&validator.address).copied().unwrap_or(0.0),
                raw_contribution: raw,
                saturated_contribution: saturated,
                ema_score: snapshot
                    .score_history
                    .get(&validator.address)
                    .copied()
                    .unwrap_or(0.0),
                normalized_score: snapshot
                    .normalized_score
                    .get(&validator.address)
                    .copied()
                    .unwrap_or(0.0),
                bonus: snapshot
                    .bonuses
                    .get(&validator.address)
                    .copied()
                    .unwrap_or(0.0),
                unnormalized_proposer_weight: snapshot
                    .unnormalized_proposer_weights
                    .get(&validator.address)
                    .copied()
                    .unwrap_or_else(|| {
                        normalized_stake
                            .get(&validator.address)
                            .copied()
                            .unwrap_or(0.0)
                    }),
                normalized_proposer_weight: proposer_weights
                    .get(&validator.address)
                    .copied()
                    .unwrap_or(0.0),
                proposer_count: self
                    .epoch_proposer_counts
                    .get(&validator.address)
                    .copied()
                    .unwrap_or(0),
                relay_reward,
                proposer_reward,
                fee_spent: fee,
                net_income: proposer_reward + relay_reward - fee,
                relay_forward_attempts,
                relay_cost_per_forward: self
                    .adaptive_relay_costs
                    .get(&validator.address)
                    .copied()
                    .unwrap_or(0.0),
                estimated_relay_benefit_per_forward: self
                    .adaptive_benefit_ema
                    .unwrap_or(0.0),
                degree: self
                    .node_degrees
                    .get(&validator.address)
                    .copied()
                    .unwrap_or(0),
                betweenness: self
                    .node_betweenness
                    .get(&validator.address)
                    .copied()
                    .unwrap_or(0.0),
            };
            self.write_node_epoch_metrics(&node_metrics);
        }
        self.update_adaptive_relay_profiles(
            epoch,
            validators,
            &reward_report,
            &proposer_weights,
            &epoch_forward_attempts,
        )
        .await;
        self.epoch_proposer_counts.clear();
        self.last_block_production_success = self.block_production_success;
        self.last_block_production_failed = self.block_production_failed;
        self.write_run_summary(epoch + 1).await;
        next_validators
    }

    async fn update_adaptive_relay_profiles(
        &mut self,
        epoch: u64,
        validators: &[Validator],
        rewards: &EpochRewardReport,
        proposer_weights: &HashMap<String, f64>,
        forward_attempts: &HashMap<String, u64>,
    ) {
        if !self.adaptive_relay_config.enabled {
            return;
        }

        let mut epoch_window = AdaptiveObservationWindow {
            epochs: 1,
            ..AdaptiveObservationWindow::default()
        };
        for validator in validators {
            let profile = self
                .node_relay_profiles
                .get(&validator.address)
                .map(String::as_str)
                .unwrap_or("lazy");
            let group = match profile {
                "active" => &mut epoch_window.active,
                "lazy" => &mut epoch_window.lazy,
                _ => continue,
            };
            let expected_proposer_reward = rewards.total_proposer_reward
                * proposer_weights
                    .get(&validator.address)
                    .copied()
                    .unwrap_or(0.0);
            group.stake_exposure += validator.stake;
            group.expected_reward += rewards
                .relay_by_address
                .get(&validator.address)
                .copied()
                .unwrap_or(0.0)
                + expected_proposer_reward;
            group.forward_attempts += forward_attempts
                .get(&validator.address)
                .copied()
                .unwrap_or(0);
        }
        self.adaptive_observation_window.epochs += 1;
        self.adaptive_observation_window.active.stake_exposure +=
            epoch_window.active.stake_exposure;
        self.adaptive_observation_window.active.expected_reward +=
            epoch_window.active.expected_reward;
        self.adaptive_observation_window.active.forward_attempts +=
            epoch_window.active.forward_attempts;
        self.adaptive_observation_window.lazy.stake_exposure +=
            epoch_window.lazy.stake_exposure;
        self.adaptive_observation_window.lazy.expected_reward +=
            epoch_window.lazy.expected_reward;
        self.adaptive_observation_window.lazy.forward_attempts +=
            epoch_window.lazy.forward_attempts;

        let completed_epochs = epoch + 1;
        let warmup = self.adaptive_relay_config.warmup_epochs;
        let interval = self.adaptive_relay_config.update_interval_epochs;
        let update_due = completed_epochs >= warmup
            && (completed_epochs - warmup) % interval == 0;
        if !update_due {
            let window_epochs = self.adaptive_observation_window.epochs;
            self.write_adaptive_relay_metrics(
                epoch,
                false,
                None,
                0,
                0,
                validators,
                window_epochs,
                None,
            );
            return;
        }

        let window = std::mem::take(&mut self.adaptive_observation_window);
        let observed_benefit = window.observed_benefit_per_forward();
        if let Some(observed) = observed_benefit {
            let alpha = self.adaptive_relay_config.benefit_ema_alpha;
            self.adaptive_benefit_ema = Some(match self.adaptive_benefit_ema {
                Some(previous) => alpha * observed + (1.0 - alpha) * previous,
                None => observed,
            });
        }

        let mut switched_active = 0usize;
        let mut switched_lazy = 0usize;
        if let Some(benefit) = self.adaptive_benefit_ema {
            let mut candidates: Vec<String> = self.adaptive_relay_costs.keys().cloned().collect();
            candidates.sort_by(|left, right| {
                self.nodes_index
                    .get(left)
                    .cmp(&self.nodes_index.get(right))
                    .then_with(|| left.cmp(right))
            });
            let mut rng = StdRng::seed_from_u64(
                self.adaptive_failure_seed
                    ^ 0x5550_4441_5445_5253
                    ^ self.adaptive_update_round,
            );
            candidates.shuffle(&mut rng);
            let update_count = ((candidates.len() as f64
                * self.adaptive_relay_config.update_fraction)
                .round() as usize)
                .max(1)
                .min(candidates.len());
            let hysteresis = self.adaptive_relay_config.switching_hysteresis;
            for address in candidates.into_iter().take(update_count) {
                let cost = self
                    .adaptive_relay_costs
                    .get(&address)
                    .copied()
                    .unwrap_or(f64::INFINITY);
                let active = self
                    .node_relay_profiles
                    .get(&address)
                    .map(|profile| profile == "active")
                    .unwrap_or(false);
                let target = if active {
                    if benefit < cost * (1.0 - hysteresis) {
                        RelayProfile::Lazy
                    } else {
                        RelayProfile::Active
                    }
                } else if benefit > cost * (1.0 + hysteresis) {
                    RelayProfile::Active
                } else {
                    RelayProfile::Lazy
                };
                if active == (target == RelayProfile::Active) {
                    continue;
                }
                if let Some(sender) = self.nodes_sender.get(&address).cloned() {
                    if sender
                        .send(Message::new_update_relay_profile_msg(target))
                        .await
                        .is_ok()
                    {
                        self.node_relay_profiles
                            .insert(address, target.to_string());
                        if target == RelayProfile::Active {
                            switched_active += 1;
                        } else {
                            switched_lazy += 1;
                        }
                    }
                }
            }
            self.adaptive_update_round += 1;
        }
        self.write_adaptive_relay_metrics(
            epoch,
            true,
            observed_benefit,
            switched_active,
            switched_lazy,
            validators,
            window.epochs,
            Some(&window),
        );
    }

    fn adaptive_active_stats(&self, validators: &[Validator]) -> (f64, f64) {
        if validators.is_empty() {
            return (0.0, 0.0);
        }
        let active_count = validators
            .iter()
            .filter(|validator| {
                self.node_relay_profiles
                    .get(&validator.address)
                    .map(|profile| profile == "active")
                    .unwrap_or(false)
            })
            .count();
        let total_stake: f64 = validators.iter().map(|validator| validator.stake).sum();
        let active_stake: f64 = validators
            .iter()
            .filter(|validator| {
                self.node_relay_profiles
                    .get(&validator.address)
                    .map(|profile| profile == "active")
                    .unwrap_or(false)
            })
            .map(|validator| validator.stake)
            .sum();
        (
            active_count as f64 / validators.len() as f64,
            if total_stake > 0.0 {
                active_stake / total_stake
            } else {
                0.0
            },
        )
    }

    fn write_adaptive_relay_metrics(
        &mut self,
        epoch: u64,
        update_applied: bool,
        observed_benefit: Option<f64>,
        switched_active: usize,
        switched_lazy: usize,
        validators: &[Validator],
        window_epochs: u64,
        window: Option<&AdaptiveObservationWindow>,
    ) {
        if self.adaptive_relay_metrics_file.is_none() {
            self.adaptive_relay_metrics_file = std::fs::OpenOptions::new()
                .create(true)
                .append(true)
                .open(&self.adaptive_relay_metrics_filename)
                .ok();
        }
        let (active_fraction, active_stake_share) = self.adaptive_active_stats(validators);
        let mean_cost = if self.adaptive_relay_costs.is_empty() {
            0.0
        } else {
            self.adaptive_relay_costs.values().sum::<f64>()
                / self.adaptive_relay_costs.len() as f64
        };
        let observed = observed_benefit
            .map(|value| format!("{value:.17e}"))
            .unwrap_or_default();
        let smoothed = self
            .adaptive_benefit_ema
            .map(|value| format!("{value:.17e}"))
            .unwrap_or_default();
        let active_reward = window
            .and_then(|value| value.active.expected_reward_per_stake())
            .map(|value| format!("{value:.17e}"))
            .unwrap_or_default();
        let lazy_reward = window
            .and_then(|value| value.lazy.expected_reward_per_stake())
            .map(|value| format!("{value:.17e}"))
            .unwrap_or_default();
        let active_work = window
            .and_then(|value| value.active.forwards_per_stake())
            .map(|value| format!("{value:.17e}"))
            .unwrap_or_default();
        let lazy_work = window
            .and_then(|value| value.lazy.forwards_per_stake())
            .map(|value| format!("{value:.17e}"))
            .unwrap_or_default();
        if let Some(file) = self.adaptive_relay_metrics_file.as_mut() {
            if file.metadata().map(|metadata| metadata.len()).unwrap_or(0) == 0 {
                let _ = writeln!(
                    file,
                    "epoch,window_epochs,update_applied,active_fraction,active_stake_share,observed_benefit_per_forward,smoothed_benefit_per_forward,active_expected_reward_per_stake,lazy_expected_reward_per_stake,active_forward_attempts_per_stake,lazy_forward_attempts_per_stake,switched_to_active,switched_to_lazy,mean_cost_per_forward"
                );
            }
            let _ = writeln!(
                file,
                "{epoch},{window_epochs},{update_applied},{active_fraction:.9},{active_stake_share:.9},{observed},{smoothed},{active_reward},{lazy_reward},{active_work},{lazy_work},{switched_active},{switched_lazy},{mean_cost:.17e}"
            );
            let _ = file.flush();
        }
    }

    fn write_epoch_metrics(&mut self, metrics: &EpochMetrics) {
        if self.epoch_metrics_file.is_none() {
            self.epoch_metrics_file = std::fs::OpenOptions::new()
                .create(true)
                .append(true)
                .open(&self.epoch_metrics_filename)
                .ok();
        }
        if let Some(file) = self.epoch_metrics_file.as_mut() {
            if file.metadata().map(|m| m.len()).unwrap_or(0) == 0 {
                let _ = writeln!(file, "{}", EpochMetrics::to_csv_header());
            }
            let _ = writeln!(file, "{}", metrics.to_csv_row());
            let _ = file.flush();
        }
    }

    fn write_node_epoch_metrics(&mut self, metrics: &NodeEpochMetrics) {
        if self.node_epoch_metrics_file.is_none() {
            self.node_epoch_metrics_file = std::fs::OpenOptions::new()
                .create(true)
                .append(true)
                .open(&self.node_epoch_metrics_filename)
                .ok();
        }
        if let Some(file) = self.node_epoch_metrics_file.as_mut() {
            if file.metadata().map(|m| m.len()).unwrap_or(0) == 0 {
                let _ = writeln!(file, "{}", NodeEpochMetrics::to_csv_header());
            }
            let _ = writeln!(file, "{}", metrics.to_csv_row());
            let _ = file.flush();
        }
    }

    fn write_inclusion_samples(
        &mut self,
        samples: &[(u64, String, u64, u64, f64, bool)],
    ) {
        if samples.is_empty() {
            return;
        }
        if self.inclusion_samples_file.is_none() {
            self.inclusion_samples_file = std::fs::OpenOptions::new()
                .create(true)
                .append(true)
                .open(&self.inclusion_samples_filename)
                .ok();
        }
        if let Some(file) = self.inclusion_samples_file.as_mut() {
            if file.metadata().map(|metadata| metadata.len()).unwrap_or(0) == 0 {
                let _ = writeln!(
                    file,
                    "included_epoch,tx_hash,created_slot,included_slot,latency_s,evidence_eligible"
                );
            }
            for (epoch, tx_hash, created_slot, included_slot, latency, eligible) in samples {
                let _ = writeln!(
                    file,
                    "{},{},{},{},{:.6},{}",
                    epoch, tx_hash, created_slot, included_slot, latency, eligible
                );
            }
            let _ = file.flush();
        }
    }

    fn write_generation_sample(&mut self, tx_hash: &str, epoch: u64, slot: u64) {
        if self.generation_samples_file.is_none() {
            self.generation_samples_file = std::fs::OpenOptions::new()
                .create(true)
                .append(true)
                .open(&self.generation_samples_filename)
                .ok();
        }
        if let Some(file) = self.generation_samples_file.as_mut() {
            if file.metadata().map(|metadata| metadata.len()).unwrap_or(0) == 0 {
                let _ = writeln!(file, "tx_hash,created_epoch,created_slot");
            }
            let _ = writeln!(file, "{tx_hash},{epoch},{slot}");
            let _ = file.flush();
        }
    }

    async fn write_run_summary(&self, completed_epochs: u64) {
        let fee_spent = self
            .fee_spent
            .lock()
            .map(|ledger| ledger.clone())
            .unwrap_or_default();
        let adversary_fee_spent: f64 = self
            .adversarial_nodes
            .iter()
            .map(|address| fee_spent.get(address).copied().unwrap_or(0.0))
            .sum();
        let adversary_reward_income: f64 = self
            .adversarial_nodes
            .iter()
            .map(|address| {
                self.total_reward_income
                    .get(address)
                    .copied()
                    .unwrap_or(0.0)
            })
            .sum();
        let summary = RunSummary {
            run_id: self.run_id.clone(),
            completed_epochs,
            generated_tx: self.generated_tx_counter.load(Ordering::Relaxed),
            included_tx: self.total_included_tx,
            block_production_success: self.block_production_success,
            block_production_failed: self.block_production_failed,
            adversary_fee_spent,
            adversary_reward_income,
            adversary_net_income: adversary_reward_income - adversary_fee_spent,
        };
        if let Ok(json) = serde_json::to_string_pretty(&summary) {
            let _ = tokio::fs::write(&self.run_summary_filename, json).await;
        }
    }

    fn raw_epoch_contribution(
        &self,
        blocks: &[Block],
        validators: &[Validator],
        snapshot: &ConsensusMetricsSnapshot,
    ) -> HashMap<String, f64> {
        let validator_set: HashSet<&str> = validators.iter().map(|v| v.address.as_str()).collect();
        let mut raw = HashMap::new();
        let depth = snapshot.topostake_depth.unwrap_or(1);
        for block in blocks {
            for (idx, tx) in block.body.transactions.iter().enumerate() {
                let Some(path) = block.body.paths.get(idx) else {
                    continue;
                };
                if !block.verify_path_evidence(idx) {
                    continue;
                }
                let full_path = path.full_path(block.header.miner.clone());
                let path_length = full_path.len().saturating_sub(1);
                if path_length < 2 {
                    continue;
                }
                for position in 1..path_length {
                    let relayer = &full_path[position];
                    if validator_set.contains(relayer.as_str()) {
                        let gamma =
                            TopoStakeConsensus::gamma_for_depth(depth, position, path_length);
                        let q = TopoStakeConsensus::transaction_credit_weight(
                            tx.irrecoverable_cost,
                            snapshot.topostake_score_cost_reference.unwrap_or(1.0),
                        );
                        *raw.entry(relayer.clone()).or_insert(0.0) += q * gamma;
                    }
                }
            }
        }
        raw
    }

    fn estimate_epoch_rewards(
        &self,
        blocks: &[Block],
        validators: &[Validator],
        snapshot: &ConsensusMetricsSnapshot,
    ) -> EpochRewardReport {
        let validator_set: HashSet<&str> = validators.iter().map(|v| v.address.as_str()).collect();
        let mut report = EpochRewardReport::default();
        let theta = snapshot.topostake_proposer_fee_ratio.unwrap_or(1.0);
        let depth = snapshot.topostake_depth.unwrap_or(1);
        for block in blocks {
            let total_fee: f64 = block.body.transactions.iter().map(|tx| tx.fee).sum();
            let proposer_reward = if snapshot.topostake_depth.is_some() {
                self.base_reward + theta * total_fee
            } else {
                self.base_reward + total_fee
            };
            *report
                .proposer_by_address
                .entry(block.header.miner.clone())
                .or_insert(0.0) += proposer_reward;
            report.total_proposer_reward += proposer_reward;

            if snapshot.topostake_depth.is_none() {
                continue;
            }
            for (idx, tx) in block.body.transactions.iter().enumerate() {
                let relay_budget = (1.0 - theta) * tx.fee;
                let Some(path) = block.body.paths.get(idx) else {
                    report.burned_relay_fee += relay_budget;
                    continue;
                };
                if !block.verify_path_evidence(idx) {
                    report.burned_relay_fee += relay_budget;
                    continue;
                }
                let full_path = path.full_path(block.header.miner.clone());
                let path_length = full_path.len().saturating_sub(1);
                if path_length < 2 {
                    report.burned_relay_fee += relay_budget;
                    continue;
                }
                let mut paid = 0.0;
                for position in 1..path_length {
                    let relayer = &full_path[position];
                    if !validator_set.contains(relayer.as_str()) {
                        continue;
                    }
                    let amount = relay_budget
                        * TopoStakeConsensus::gamma_for_depth(depth, position, path_length);
                    if amount > 0.0 {
                        paid += amount;
                        *report
                            .relay_by_address
                            .entry(relayer.clone())
                            .or_insert(0.0) += amount;
                    }
                }
                report.total_relay_reward += paid;
                report.burned_relay_fee += (relay_budget - paid).max(0.0);
            }
        }
        report
    }

    /// Measure coalition capture from transactions funded by non-adversarial
    /// originators. This is an evaluation-only decomposition of the existing
    /// reward and score rules; it does not alter path acceptance or consensus.
    fn organic_capture_report(
        &self,
        blocks: &[Block],
        validators: &[Validator],
        snapshot: &ConsensusMetricsSnapshot,
    ) -> OrganicCaptureReport {
        let validator_set: HashSet<&str> = validators.iter().map(|v| v.address.as_str()).collect();
        let theta = snapshot.topostake_proposer_fee_ratio.unwrap_or(1.0);
        let depth = snapshot.topostake_depth.unwrap_or(1);
        let cost_reference = snapshot.topostake_score_cost_reference.unwrap_or(1.0);
        let mut report = OrganicCaptureReport::default();

        if snapshot.topostake_depth.is_none() {
            return report;
        }

        for block in blocks {
            for (idx, tx) in block.body.transactions.iter().enumerate() {
                if self.adversarial_nodes.contains(&tx.from) {
                    continue;
                }
                report.included_tx += 1;
                let Some(path) = block.body.paths.get(idx) else {
                    continue;
                };
                if !block.verify_path_evidence(idx) {
                    continue;
                }
                let full_path = path.full_path(block.header.miner.clone());
                let path_length = full_path.len().saturating_sub(1);
                if path_length < 2 {
                    continue;
                }
                report.valid_path_count += 1;
                let relay_budget = (1.0 - theta) * tx.fee;
                let q = TopoStakeConsensus::transaction_credit_weight(
                    tx.irrecoverable_cost,
                    cost_reference,
                );
                for position in 1..path_length {
                    let relayer = &full_path[position];
                    if !validator_set.contains(relayer.as_str()) {
                        continue;
                    }
                    let gamma =
                        TopoStakeConsensus::gamma_for_depth(depth, position, path_length);
                    let reward = relay_budget * gamma;
                    let contribution = q * gamma;
                    report.relay_reward += reward;
                    report.raw_contribution += contribution;
                    if self.adversarial_nodes.contains(relayer) {
                        report.adversary_relay_reward += reward;
                        report.adversary_raw_contribution += contribution;
                    }
                }
            }
        }
        report
    }

    pub async fn run(self, mut receiver: Receiver<Message>) {
        let node_index = self.nodes_index.clone();
        let consensus_name = self.consensus_name.clone();
        let shared_self = Arc::new(RwLock::new(self));
        let receiver_task = {
            let shared_self = Arc::clone(&shared_self);
            task::spawn(async move {
                while let Some(msg) = receiver.recv().await {
                    match msg {
                        Message::ReceiveRandaoSeed(randao_seed) => {
                            let shared_self = shared_self.write().await;
                            let mut current_slot = shared_self.current_slot.write().await;
                            current_slot.randao_seeds.push(randao_seed.clone());
                        }
                        Message::ReceiveBecomeValidator(validator) => {
                            let shared_self = shared_self.write().await;
                            let mut validators = shared_self.validators.write().await;
                            validators.retain(|v| v.address != validator.address);
                            validators.push(validator.clone());
                            drop(validators);
                            let mut balances = shared_self.account_balances.write().await;
                            balances
                                .entry(validator.address.clone())
                                .or_insert(validator.stake);
                        }
                        Message::UpdateValidatorStake { address, new_stake } => {
                            warn!(
                                "Ignoring immediate stake update for {}; economic stake changes only at epoch boundaries (requested {:.6})",
                                address, new_stake
                            );
                        }
                        Message::UpdateAccountBalance {
                            address,
                            new_balance,
                        } => {
                            let shared_self = shared_self.write().await;
                            let mut balances = shared_self.account_balances.write().await;
                            balances.insert(address, new_balance);
                        }
                        Message::RecordGeneratedTransaction {
                            tx_hash,
                            created_epoch,
                            created_slot,
                        } => {
                            let mut shared_self = shared_self.write().await;
                            shared_self.write_generation_sample(
                                &tx_hash,
                                created_epoch,
                                created_slot,
                            );
                        }
                        Message::SendBlock { block, from: _ } => {
                            {
                                let mut shared_self = shared_self.write().await;
                                let add_block_result = {
                                    shared_self
                                        .blockchain
                                        .write()
                                        .await
                                        .add_block((*block).clone())
                                };

                                if let Err(e) = add_block_result {
                                    match e {
                                        BlockChainError::ParentHashMismatch => {
                                            error!(
                                                "World State: Parent hash mismatch at index {}, there may be a fork",
                                                block.header.index
                                            );
                                            shared_self.block_production_failed += 1;
                                        }
                                        BlockChainError::DuplicateBlocksReceived => {
                                            debug!(
                                                "World State: duplicate block at index {}",
                                                block.header.index
                                            );
                                        }
                                        BlockChainError::IndexTooSmall => {
                                            debug!(
                                                "World State: Received block at index {}, index too small, current index is {}",
                                                block.header.index, shared_self.blockchain.read().await.get_last_index()
                                            );
                                        }
                                        _ => {
                                            error!("World State Add Block Error: {}", e);
                                            shared_self.block_production_failed += 1;
                                        }
                                    }
                                    continue;
                                }

                                // 块添加成功，更新出块成功计数
                                shared_self.block_production_success += 1;

                                // 块添加成功后，结算成熟奖励到账户余额；不修改经济 stake
                                {
                                    let validators_snapshot =
                                        shared_self.validators.read().await.clone();
                                    let reward_deltas = shared_self.consensus.distribute_rewards(
                                        &block,
                                        &validators_snapshot,
                                        node_index.clone(),
                                    );

                                    let balance_updates = {
                                        let mut balances =
                                            shared_self.account_balances.write().await;
                                        let mut touched = HashSet::new();
                                        for delta in reward_deltas {
                                            let address = delta.address;
                                            *balances.entry(address.clone()).or_insert(0.0) +=
                                                delta.amount;
                                            touched.insert(address);
                                        }
                                        touched
                                            .into_iter()
                                            .filter_map(|address| {
                                                balances
                                                    .get(&address)
                                                    .map(|balance| (address, *balance))
                                            })
                                            .collect::<Vec<_>>()
                                    };

                                    let send_updates = balance_updates
                                        .into_iter()
                                        .filter_map(|(address, balance)| {
                                            shared_self
                                                .nodes_sender
                                                .get(&address)
                                                .cloned()
                                                .map(|sender| (address, balance, sender))
                                        })
                                        .collect::<Vec<_>>();

                                    for (address, balance, sender) in send_updates {
                                        let msg = Message::new_update_node_balance_msg(balance);
                                        if let Err(e) = sender.send(msg).await {
                                            warn!(
                                                "Failed to send UpdateNodeBalance to {}: {}",
                                                &address[..8.min(address.len())],
                                                e
                                            );
                                        }
                                    }
                                }
                            }
                            debug!("World State add block successfully");
                        }
                        Message::RequestBlockSync {
                            last_block_index: _,
                            from,
                        } => {
                            let shared_self = shared_self.read().await;
                            let sync_blocks = shared_self.blockchain.read().await.blocks.clone();
                            if let Some(sender) = shared_self.nodes_sender.get(&from) {
                                if let Err(e) =
                                    sender.try_send(Message::new_response_block_sync_msg(
                                        sync_blocks,
                                        "world_state".to_string(),
                                    ))
                                {
                                    warn!(
                                        "World State: failed to send canonical sync to {}: {}",
                                        &from[..8.min(from.len())],
                                        e
                                    );
                                }
                            }
                        }
                        Message::BlockProductionFailed {
                            node_index,
                            slot,
                            reason,
                        } => {
                            // 处理出块失败事件
                            let mut shared_self = shared_self.write().await;
                            shared_self.block_production_failed += 1;
                            debug!(
                                "World State: Block production failed at slot {}: Node[{}] (reason: {})",
                                slot,
                                node_index,
                                reason
                            );
                        }
                        Message::ResponseBlockSync {
                            blocks: sync_blocks,
                            from: _,
                        } => {
                            if sync_blocks.is_empty() {
                                continue;
                            }
                            let shared_self = shared_self.write().await;
                            let mut local_chain = shared_self.blockchain.write().await;

                            let current_index = local_chain.get_last_index();
                            let response_index = sync_blocks.last().unwrap().header.index;
                            let response_start_index = sync_blocks.first().unwrap().header.index;

                            // 同步的数据比我们当前拥有的新很多，且中间有断层
                            if current_index + 1 < response_start_index {
                                warn!(
                                    "World State: received snapshot sync from index {} to {}, gap detected. Replacing local chain",
                                    response_start_index, response_index
                                );

                                local_chain.blocks.clear();
                                local_chain.transaction_index.clear();

                                for sync_block in &sync_blocks {
                                    local_chain.blocks.push(sync_block.clone());
                                    for tx in &sync_block.body.transactions {
                                        local_chain.transaction_index.insert(tx.hash.clone());
                                    }
                                }
                            } else if current_index >= response_index {
                                debug!(
                                    "World State: skipping sync: current_index({}) >= response_index({})",
                                    current_index, response_index
                                );
                            } else {
                                // 寻找分叉点或者追加新块
                                let mut start_idx = 0;
                                let mut found_fork = false;

                                for (i, sync_block) in sync_blocks.iter().enumerate() {
                                    // 根据高度在本地查找是否有相同的块
                                    let local_block_opt = local_chain
                                        .blocks
                                        .iter()
                                        .find(|b| b.header.index == sync_block.header.index);

                                    if let Some(local_block) = local_block_opt {
                                        if local_block.header.hash != sync_block.header.hash {
                                            // 发现分叉
                                            warn!(
                                                "World State: chain diverged at #{}, resolving",
                                                sync_block.header.index
                                            );
                                            start_idx = i;
                                            found_fork = true;

                                            // 删除本地分叉及之后的块，并清理对应交易限制
                                            let local_start = local_chain
                                                .blocks
                                                .first()
                                                .map_or(0, |b| b.header.index);
                                            let truncate_idx =
                                                (sync_block.header.index - local_start) as usize;

                                            // 收集需要删除的交易 hashes
                                            let mut hashes_to_remove = Vec::new();
                                            for b in &local_chain.blocks[truncate_idx..] {
                                                for tx in &b.body.transactions {
                                                    hashes_to_remove.push(tx.hash.clone());
                                                }
                                            }
                                            for hash in hashes_to_remove {
                                                local_chain.transaction_index.remove(&hash);
                                            }

                                            local_chain.blocks.truncate(truncate_idx);
                                            break;
                                        }
                                    } else if sync_block.header.index > local_chain.get_last_index()
                                    {
                                        // 到了需要追加的新块部分
                                        start_idx = i;
                                        found_fork = true;
                                        break;
                                    }
                                }

                                if found_fork {
                                    for sync_idx in start_idx..sync_blocks.len() {
                                        let sync_block = &sync_blocks[sync_idx];
                                        match local_chain.add_block(sync_block.clone()) {
                                            Ok(_) => {
                                                debug!(
                                                    "World State: synced block #{}",
                                                    sync_block.header.index
                                                );
                                            }
                                            Err(e) => {
                                                error!(
                                                    "World State: failed to sync block #{}: {:?}",
                                                    sync_block.header.index, e
                                                );
                                                break;
                                            }
                                        }
                                    }
                                    info!(
                                        "World State: synced chain to index {}",
                                        local_chain.get_last_index()
                                    );
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
                    shared_self.real_slot_duration
                };
                let deadline = Instant::now() + time_interval;
                time::sleep_until(deadline).await;
                debug!("World State time trigger: {}", tools::get_time_string());

                // 对于 PoW 协议，需要等待区块链长度增加后才进入下一个 slot
                if consensus_name == "pow" {
                    let pow_wait_start = Instant::now();
                    let pow_timeout = shared_self.read().await.real_slot_duration.mul_f64(16.0);
                    loop {
                        if last_index == 0 {
                            time::sleep(shared_self.read().await.real_slot_duration).await;
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

    #[test]
    fn adaptive_window_uses_reward_premium_over_extra_work() {
        let window = AdaptiveObservationWindow {
            epochs: 5,
            active: AdaptiveGroupObservation {
                stake_exposure: 10.0,
                expected_reward: 8.0,
                forward_attempts: 50,
            },
            lazy: AdaptiveGroupObservation {
                stake_exposure: 10.0,
                expected_reward: 4.0,
                forward_attempts: 10,
            },
        };
        let benefit = window.observed_benefit_per_forward().unwrap();
        assert!((benefit - 0.1).abs() < 1e-12);
    }

    #[test]
    fn adaptive_window_rejects_missing_counterfactual_group() {
        let window = AdaptiveObservationWindow {
            epochs: 5,
            active: AdaptiveGroupObservation {
                stake_exposure: 10.0,
                expected_reward: 8.0,
                forward_attempts: 50,
            },
            lazy: AdaptiveGroupObservation::default(),
        };
        assert_eq!(window.observed_benefit_per_forward(), None);
    }

    #[test]
    fn reinvestment_applies_proposer_and_relay_rewards_atomically() {
        let validators = vec![
            Validator::new("alice".to_string(), 2.0, 1.0),
            Validator::new("bob".to_string(), 3.0, 1.0),
        ];
        let mut rewards = EpochRewardReport::default();
        rewards
            .proposer_by_address
            .insert("alice".to_string(), 0.4);
        rewards
            .relay_by_address
            .insert("alice".to_string(), 0.2);
        rewards
            .relay_by_address
            .insert("bob".to_string(), 0.6);

        let updated = reinvest_epoch_rewards(&validators, &rewards, 0.5);
        assert!((updated[0].stake - 2.3).abs() < 1e-12);
        assert!((updated[1].stake - 3.3).abs() < 1e-12);
        assert_eq!(validators[0].stake, 2.0);
        assert_eq!(validators[1].stake, 3.0);
    }

    #[test]
    fn zero_reinvestment_preserves_stake_exactly() {
        let validators = vec![Validator::new("alice".to_string(), 2.0, 1.0)];
        let mut rewards = EpochRewardReport::default();
        rewards
            .proposer_by_address
            .insert("alice".to_string(), 99.0);
        assert_eq!(
            reinvest_epoch_rewards(&validators, &rewards, 0.0)[0].stake,
            2.0
        );
    }

    #[test]
    fn organic_capture_excludes_coalition_origins_and_accounts_relayer_credit() {
        let origin = Wallet::new();
        let adversary = Wallet::new();
        let miner = Wallet::new();
        let tx = Transaction::with_costs(
            miner.address.clone(),
            0,
            1.0,
            1.0,
            origin.clone(),
        );
        let mut path = TransactionPaths::new_with_epoch(tx.clone(), 0);
        assert!(path.append_completed_hop(
            adversary.address.clone(),
            origin.clone(),
            adversary.clone(),
        ));
        assert!(path.append_completed_hop(
            miner.address.clone(),
            adversary.clone(),
            miner.clone(),
        ));
        let block = Block::new(
            1,
            0,
            0,
            Block::gen_genesis_block().header.hash,
            Body::new(vec![tx], vec![path.to_aggregated_signed_paths()]),
            miner.clone(),
        )
        .unwrap();
        let config = TopoStakeConfig {
            proposer_fee_ratio: 0.5,
            score_cost_reference: 1.0,
            ..TopoStakeConfig::default()
        };
        let (mut world, _sender, _receiver) = WorldState::new(
            Block::gen_genesis_block(),
            ConsensusType::TopoStake,
            Blockchain::new(Block::gen_genesis_block()),
            1,
            5,
            20,
            8,
            config,
            0.1,
            0.0,
            3,
            1,
            "ba".to_string(),
            1,
            10,
            PathBuf::from("/tmp/topostake-organic-capture-test"),
            "organic-capture-test".to_string(),
            1,
            false,
            0.01,
            0.0,
            Arc::new(AtomicU64::new(0)),
            Arc::new(std::sync::Mutex::new(HashMap::new())),
        );
        world.adversarial_nodes.insert(adversary.address.clone());
        let validators = vec![
            Validator::new(origin.address.clone(), 1.0, 1.0),
            Validator::new(adversary.address.clone(), 1.0, 1.0),
            Validator::new(miner.address.clone(), 1.0, 1.0),
        ];
        let snapshot = world.consensus.metrics_snapshot();
        let report = world.organic_capture_report(&[block.clone()], &validators, &snapshot);
        assert_eq!(report.included_tx, 1);
        assert_eq!(report.valid_path_count, 1);
        assert!(report.relay_reward > 0.0);
        assert_eq!(report.adversary_relay_reward, report.relay_reward);
        assert!(report.raw_contribution > 0.0);
        assert_eq!(
            report.adversary_raw_contribution,
            report.raw_contribution
        );

        world.adversarial_nodes.insert(origin.address);
        let excluded = world.organic_capture_report(&[block], &validators, &snapshot);
        assert_eq!(excluded.included_tx, 0);
        assert_eq!(excluded.relay_reward, 0.0);
    }

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
            TopoStakeConfig::default(),
            0.0, // base_reward
            0.0, // reward_reinvestment_rate
            20,
            10,
            "ba".to_string(),
            500,
            1000,
            PathBuf::from("/tmp/pog-rs-world-test-timer"),
            "test-timer".to_string(),
            1,
            true,
            1.0,
            0.0,
            Arc::new(AtomicU64::new(0)),
            Arc::new(std::sync::Mutex::new(HashMap::new())),
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
            TopoStakeConfig::default(),
            0.0, // base_reward
            0.0, // reward_reinvestment_rate
            20,
            10,
            "ba".to_string(),
            500,
            1000,
            PathBuf::from("/tmp/pog-rs-world-test-seeds"),
            "test-seeds".to_string(),
            1,
            true,
            1.0,
            0.0,
            Arc::new(AtomicU64::new(0)),
            Arc::new(std::sync::Mutex::new(HashMap::new())),
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

        let _handle_world = tokio::spawn(async move {
            world.run(world_receiver).await;
        });
        let _handle0 = tokio::spawn(async move {
            node0.run().await;
        });
        let _handle1 = tokio::spawn(async move {
            node1.run().await;
        });
        //become validator

        let nodes_address = vec![node0_wallet.address.clone(), node1_wallet.address.clone()];
        let mut stake_map: std::collections::HashMap<String, f64> =
            std::collections::HashMap::new();
        for address in nodes_address.iter() {
            stake_map.insert(address.clone(), 1.0);
        }
        // let stake_json = serde_json::to_vec(&stake_map).unwrap_or_default();

        node0_sender
            .send(Message::new_become_validator_msg(stake_map.clone()))
            .await
            .unwrap();
        node1_sender
            .send(Message::new_become_validator_msg(stake_map))
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
                Arc::new(transaction_paths),
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
                Arc::new(transaction_paths),
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
