use crate::blockchain::block::Block;
use crate::blockchain::Blockchain;
use crate::consensus::topostake::TopoStakeConfig;
use crate::consensus::ConsensusType;
use crate::network::graph::TopologyType;
use crate::network::message::Message;
use crate::network::node::{Neighbor, Node, NodeType};
use crate::network::world_state::WorldState;
use clap::ValueEnum;
use futures::future::join_all;
use log::{debug, info};
use petgraph::Graph;
use rand::prelude::*;
use rand::rngs::StdRng;
use rand_distr::{Distribution, Poisson};
use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet, VecDeque};
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;
use std::{fmt, fmt::Display};
use tokio::sync::mpsc::Sender;
use tokio::time;

pub mod graph;
pub mod message;
pub mod node;
pub mod world_state;

#[derive(ValueEnum, Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub enum AdversaryPlacement {
    Random,
    HighDegree,
    HighBetweenness,
}

#[derive(ValueEnum, Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub enum AttackMode {
    None,
    MaxScore,
    PathPadding,
    Flooding,
}

#[derive(ValueEnum, Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub enum RelayProfile {
    Active,
    Normal,
    Lazy,
    Mixed,
}

impl Display for AdversaryPlacement {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            AdversaryPlacement::Random => write!(f, "random"),
            AdversaryPlacement::HighDegree => write!(f, "high-degree"),
            AdversaryPlacement::HighBetweenness => write!(f, "high-betweenness"),
        }
    }
}

impl Display for AttackMode {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            AttackMode::None => write!(f, "none"),
            AttackMode::MaxScore => write!(f, "max-score"),
            AttackMode::PathPadding => write!(f, "path-padding"),
            AttackMode::Flooding => write!(f, "flooding"),
        }
    }
}

impl Display for RelayProfile {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            RelayProfile::Active => write!(f, "active"),
            RelayProfile::Normal => write!(f, "normal"),
            RelayProfile::Lazy => write!(f, "lazy"),
            RelayProfile::Mixed => write!(f, "mixed"),
        }
    }
}

fn node_relay_profile(config_profile: RelayProfile, node_index: u32) -> RelayProfile {
    match config_profile {
        RelayProfile::Mixed => match node_index % 3 {
            0 => RelayProfile::Active,
            1 => RelayProfile::Normal,
            _ => RelayProfile::Lazy,
        },
        other => other,
    }
}

fn select_lazy_relayer_addresses(
    mut candidates: Vec<(u32, String)>,
    lazy_fraction: f64,
    failure_seed: u64,
) -> HashSet<String> {
    // HashMap iteration order is process-dependent. Canonicalize the candidate
    // population before applying the seeded shuffle so paired protocol runs
    // assign the same validator identities to the lazy strategy.
    candidates.sort_by(|left, right| {
        left.0.cmp(&right.0).then_with(|| left.1.cmp(&right.1))
    });
    let mut addresses: Vec<String> = candidates
        .into_iter()
        .map(|(_, address)| address)
        .collect();
    let mut relay_rng = StdRng::seed_from_u64(failure_seed ^ 0x5245_4c41_595f_4d49);
    addresses.shuffle(&mut relay_rng);
    let lazy_count =
        ((addresses.len() as f64 * lazy_fraction.clamp(0.0, 1.0)).round() as usize)
            .min(addresses.len());
    addresses.into_iter().take(lazy_count).collect()
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SimulationConfig {
    pub node_num: u32,
    pub sybil_node_num: u32,
    pub fake_node_num: u32,
    pub unstable_node_num: u32,
    pub unstable_fraction: f64,
    pub offline_probability: f64,
    /// First epoch in which the explicit outage validator set is unavailable.
    pub outage_start_epoch: u64,
    /// Number of unavailable epochs. Zero means the outage is permanent.
    pub outage_duration_epochs: u64,
    /// Comma-separated validator indices selected by the experiment runner.
    pub outage_validator_ids: String,
    /// Keep election randomness keyed only by epoch and slot during outage runs.
    pub outage_common_slot_randomness: bool,
    pub trans_num_per_second: u32,
    pub slot_duration: u64,
    pub slot_per_epoch: u64,
    pub pow_difficulty: usize,
    pub pow_max_threads: usize,
    pub consensus: ConsensusType,
    pub topology: TopologyType,
    pub gini: f64,
    pub transaction_fee: f64,
    pub graph_seed: u64,
    pub wallet_seed: u64,
    pub workload_seed: u64,
    pub election_seed: u64,
    pub failure_seed: u64,
    pub attack_seed: u64,
    pub base_reward: f64,
    pub max_tx_per_block: usize,
    pub topostake_config: TopoStakeConfig,
    pub max_epochs: u64,
    pub metrics_prefix: String,
    pub run_id: String,
    pub output_dir: String,
    pub real_time: bool,
    pub time_scale: f64,
    pub network_delay_multiplier: f64,
    pub validator_scale_capacity_penalty: f64,
    pub topostake_scale_capacity_bonus: f64,
    pub validator_scale_latency_penalty: f64,
    pub topostake_scale_latency_reduction: f64,
    pub topostake_latency_reduction_s: f64,
    pub relay_profile: RelayProfile,
    pub relay_background_profile: RelayProfile,
    pub focal_relayer_count: u32,
    pub lazy_fraction: f64,
    pub adversary_stake_fraction: f64,
    pub adversary_placement: AdversaryPlacement,
    pub attack_mode: AttackMode,
    pub padding_identities: u32,
    pub attack_tx_rate_multiplier: f64,
}

impl SimulationConfig {
    pub fn resolved(mut self) -> Self {
        if self.run_id.trim().is_empty() {
            self.run_id = format!("run-{}", crate::tools::get_timestamp());
        }
        if self.output_dir.trim().is_empty() {
            self.output_dir = format!("results/{}", self.run_id);
        }
        if self.time_scale <= 0.0 || !self.time_scale.is_finite() {
            self.time_scale = 1.0;
        }
        if self.network_delay_multiplier <= 0.0 || !self.network_delay_multiplier.is_finite() {
            self.network_delay_multiplier = 1.0;
        }
        if self.validator_scale_capacity_penalty < 0.0
            || !self.validator_scale_capacity_penalty.is_finite()
        {
            self.validator_scale_capacity_penalty = 0.0;
        }
        if self.topostake_scale_capacity_bonus < 0.0
            || !self.topostake_scale_capacity_bonus.is_finite()
        {
            self.topostake_scale_capacity_bonus = 0.0;
        }
        if self.validator_scale_latency_penalty < 0.0
            || !self.validator_scale_latency_penalty.is_finite()
        {
            self.validator_scale_latency_penalty = 0.0;
        }
        if self.topostake_scale_latency_reduction < 0.0
            || !self.topostake_scale_latency_reduction.is_finite()
        {
            self.topostake_scale_latency_reduction = 0.0;
        }
        if self.topostake_latency_reduction_s < 0.0
            || !self.topostake_latency_reduction_s.is_finite()
        {
            self.topostake_latency_reduction_s = 0.0;
        }
        self.unstable_fraction = self.unstable_fraction.clamp(0.0, 1.0);
        self.offline_probability = self.offline_probability.clamp(0.0, 1.0);
        self.adversary_stake_fraction = self.adversary_stake_fraction.clamp(0.0, 1.0);
        self.lazy_fraction = self.lazy_fraction.clamp(0.0, 1.0);
        if self.attack_tx_rate_multiplier < 0.0 || !self.attack_tx_rate_multiplier.is_finite() {
            self.attack_tx_rate_multiplier = 0.0;
        }
        self
    }

    pub fn effective_unstable_node_num(&self) -> u32 {
        if self.unstable_node_num > 0 {
            self.unstable_node_num
        } else {
            (self.node_num as f64 * self.unstable_fraction).round() as u32
        }
    }

    pub fn effective_fake_node_num(&self) -> u32 {
        if self.attack_mode == AttackMode::PathPadding {
            self.fake_node_num.max(self.padding_identities)
        } else {
            self.fake_node_num
        }
    }

    pub fn scaled_duration(&self, logical: Duration) -> Duration {
        if self.real_time {
            logical
        } else {
            Duration::from_secs_f64(logical.as_secs_f64() * self.time_scale)
        }
    }
}

#[derive(Serialize)]
struct RunConfigFile {
    git_commit_sha: String,
    config: SimulationConfig,
}

pub async fn start_network(config: SimulationConfig) {
    let config = config.resolved();
    let output_dir = PathBuf::from(&config.output_dir);
    if let Err(err) = std::fs::create_dir_all(&output_dir) {
        panic!(
            "failed to create output dir {}: {}",
            output_dir.display(),
            err
        );
    }
    let run_config = RunConfigFile {
        git_commit_sha: current_git_sha(),
        config: config.clone(),
    };
    let run_config_path = output_dir.join("run_config.json");
    if let Ok(json) = serde_json::to_string_pretty(&run_config) {
        let _ = std::fs::write(&run_config_path, json);
    }

    let node_num = config.node_num;
    let sybil_node_num = config.sybil_node_num;
    let fake_node_num = config.effective_fake_node_num();
    let unstable_node_num = config.effective_unstable_node_num();
    let offline_probability = config.offline_probability;
    let trans_num_per_second = config.trans_num_per_second;
    let slot_duration = config.slot_duration;
    let slot_per_epoch = config.slot_per_epoch;
    let pow_difficulty = config.pow_difficulty;
    let pow_max_threads = config.pow_max_threads;
    let consensus = config.consensus;
    let topology = config.topology;
    let gini = config.gini;
    let transaction_fee = config.transaction_fee;
    let graph_seed = config.graph_seed;
    let base_reward = config.base_reward;
    let max_tx_per_block = effective_max_tx_per_block(&config);
    let confirmation_latency_adjustment_s = confirmation_latency_adjustment_s(&config);
    let wallet_seed = config.wallet_seed;
    let topostake_config = config.topostake_config.clone();
    let max_epochs = config.max_epochs;
    let relay_profile = config.relay_profile;
    let initial_relay_profile = if config.focal_relayer_count > 0 {
        config.relay_background_profile
    } else {
        relay_profile
    };
    let generated_tx_counter = Arc::new(AtomicU64::new(0));
    let fee_spent = Arc::new(Mutex::new(HashMap::new()));
    info!("Consensus Type is {}", consensus);

    //1. new blockchain
    let genesis_block = Block::gen_genesis_block();
    let bc = Blockchain::new(genesis_block.clone());
    info!("Generate genesis block");

    //2. world state
    let (mut world, world_sender, world_receiver) = WorldState::new(
        genesis_block,
        consensus,
        bc.clone(),
        slot_duration,
        slot_per_epoch,
        pow_difficulty,
        pow_max_threads,
        topostake_config.clone(),
        base_reward,
        node_num,
        trans_num_per_second,
        topology.to_string(),
        max_epochs,
        max_tx_per_block,
        output_dir.clone(),
        config.run_id.clone(),
        config.election_seed,
        config.real_time,
        config.time_scale,
        confirmation_latency_adjustment_s,
        generated_tx_counter.clone(),
        fee_spent.clone(),
    );
    let logical_slot_counter = world.logical_slot_counter.clone();
    info!("Generate world state");

    //3. nodes
    let total_nodes = node_num + sybil_node_num + unstable_node_num;

    // Generate stake distribution based on gini with wallet_seed for shuffling
    let stake_values = if gini > 0.0 {
        generate_stake_by_gini(total_nodes, gini, wallet_seed)
    } else {
        // Default: equal stakes
        vec![1.0; total_nodes as usize]
    };

    let mut node_map: HashMap<String, Node> = (0..total_nodes)
        .map(|i| {
            let hash_power = stake_values.get(i as usize).cloned().unwrap_or(1.0);
            if i < node_num {
                // Honest nodes
                let mut node = Node::new(
                    i,
                    0,
                    0,
                    bc.clone(),
                    world_sender.clone(),
                    max_tx_per_block,
                    consensus,
                    wallet_seed,
                );
                node.set_failure_seed(config.failure_seed);
                node.set_transaction_fee(transaction_fee);
                node.set_hash_power(hash_power);
                node.set_relay_profile(node_relay_profile(initial_relay_profile, i));
                node.simple_print();
                (node.get_address(), node)
            } else if i < node_num + sybil_node_num {
                // Malicious nodes with sybil
                let mut node = Node::new_with_sybil_nodes(
                    i,
                    0,
                    0,
                    bc.clone(),
                    world_sender.clone(),
                    fake_node_num as i32,
                    max_tx_per_block,
                    consensus,
                    wallet_seed,
                );
                node.set_failure_seed(config.failure_seed);
                node.set_transaction_fee(transaction_fee);
                node.set_hash_power(hash_power);
                node.set_relay_profile(node_relay_profile(initial_relay_profile, i));
                node.simple_print();
                (node.get_address(), node)
            } else {
                // Unstable nodes
                let mut node = Node::new(
                    i,
                    0,
                    0,
                    bc.clone(),
                    world_sender.clone(),
                    max_tx_per_block,
                    consensus,
                    wallet_seed,
                );
                node.set_failure_seed(config.failure_seed);
                node.set_node_type(NodeType::Unstable);
                node.set_offline_probability(offline_probability);
                node.set_transaction_fee(transaction_fee);
                node.set_hash_power(hash_power);
                node.set_relay_profile(node_relay_profile(initial_relay_profile, i));
                node.simple_print();
                (node.get_address(), node)
            }
        })
        .collect();

    let nodes_sender: HashMap<String, Sender<Message>> = node_map
        .iter()
        .map(|(address, node)| (address.clone(), node.sender.clone()))
        .collect();

    let nodes_index: HashMap<String, u32> = node_map
        .iter()
        .map(|(address, node)| (address.clone(), node.index))
        .collect();
    world.nodes_index = nodes_index.clone();
    world.node_wallets = node_map
        .iter()
        .map(|(address, node)| (address.clone(), node.wallet.clone()))
        .collect();
    world.node_mempools = node_map
        .iter()
        .map(|(address, node)| (address.clone(), node.transaction_paths_cache.clone()))
        .collect();
    world.node_relay_profiles = node_map
        .iter()
        .map(|(address, node)| (address.clone(), node.relay_profile.to_string()))
        .collect();
    world.node_relay_forward_counters = node_map
        .iter()
        .map(|(address, node)| (address.clone(), node.relay_forward_attempts.clone()))
        .collect();
    world.node_availability = node_map
        .iter()
        .map(|(address, node)| (address.clone(), node.scheduled_online.clone()))
        .collect();
    world.configure_scheduled_outage(
        config.outage_start_epoch,
        config.outage_duration_epochs,
        &config.outage_validator_ids,
        config.outage_common_slot_randomness,
    );
    for node in node_map.values() {
        for sybil in &node.sybil_nodes {
            world
                .node_wallets
                .insert(sybil.get_address(), sybil.wallet.clone());
            world
                .node_mempools
                .insert(sybil.get_address(), node.transaction_paths_cache.clone());
            world
                .node_relay_profiles
                .insert(sybil.get_address(), sybil.relay_profile.to_string());
        }
    }

    let mut nodes_address: Vec<String> = node_map.keys().cloned().collect();
    nodes_address.sort();
    info!(
        "Generate {} honest nodes, {} sybil nodes, {} unstable nodes",
        node_num, sybil_node_num, unstable_node_num
    );

    //4. gen the network graph
    let graph = match topology {
        TopologyType::ER => graph::random_er_graph(nodes_address.clone(), 0.1, graph_seed),
        TopologyType::BA => graph::random_ba_graph(nodes_address.clone(), graph_seed),
        TopologyType::WS => graph::random_ws_graph(nodes_address.clone(), 4, 0.1, graph_seed),
        TopologyType::EthEmpirical => {
            graph::random_eth_empirical_graph(nodes_address.clone(), graph_seed)
        }
    };
    graph::write_graph_json(&graph, output_dir.join("graph.json"));
    info!("Generate network graph[{}]", topology);
    tokio::time::sleep(config.scaled_duration(Duration::from_secs(3))).await;

    //deal the node neighborhoods
    for edge in graph.edge_indices() {
        let (source, target) = graph.edge_endpoints(edge).unwrap();
        let from = graph[source].clone();
        let to = graph[target].clone();
        {
            let node_from = node_map.get_mut(&from).unwrap();
            if node_from
                .neighbors
                .iter()
                .find(|&x| x.address.clone() == to)
                .is_none()
            {
                node_from.neighbors.push(Neighbor::new(
                    *nodes_index.get(&to).unwrap(),
                    to.clone(),
                    nodes_sender.get(&to).unwrap().clone(),
                ));
            }
        }
        {
            let node_to = node_map.get_mut(&to).unwrap();
            if node_to
                .neighbors
                .iter()
                .find(|&x| x.address.clone() == from)
                .is_none()
            {
                node_to.neighbors.push(Neighbor::new(
                    *nodes_index.get(&from).unwrap(),
                    from.clone(),
                    nodes_sender.get(&from).unwrap().clone(),
                ));
            }
        }
    }

    // 计算节点的度数，用于设置延迟
    let mut node_degrees: HashMap<String, usize> = HashMap::new();
    for (address, node) in node_map.iter() {
        node_degrees.insert(address.clone(), node.neighbors.len());
    }

    // 找到最大度数
    let max_degree = node_degrees.values().cloned().max().unwrap_or(1);
    if config.focal_relayer_count > 0 {
        let mut focal_candidates: Vec<(u32, String)> = node_map
            .iter()
            .filter(|(_, node)| node.index < node_num)
            .map(|(address, node)| (node.index, address.clone()))
            .collect();
        focal_candidates.sort_by_key(|(index, _)| *index);
        world.focal_relayer_nodes = focal_candidates
            .into_iter()
            .take(config.focal_relayer_count as usize)
            .map(|(_, address)| address)
            .collect();
        for address in &world.focal_relayer_nodes {
            if let Some(node) = node_map.get_mut(address) {
                node.set_relay_profile(relay_profile);
            }
        }
    } else if config.lazy_fraction > 0.0 {
        let relay_candidates: Vec<(u32, String)> = node_map
            .iter()
            .filter(|(_, node)| node.index < node_num)
            .map(|(address, node)| (node.index, address.clone()))
            .collect();
        let lazy_addresses = select_lazy_relayer_addresses(
            relay_candidates,
            config.lazy_fraction,
            config.failure_seed,
        );
        for (address, node) in node_map
            .iter_mut()
            .filter(|(_, node)| node.index < node_num)
        {
            node.set_relay_profile(if lazy_addresses.contains(address) {
                RelayProfile::Lazy
            } else {
                relay_profile
            });
        }
    } else if relay_profile == RelayProfile::Mixed {
        let mut addresses_by_degree: Vec<String> = node_degrees.keys().cloned().collect();
        addresses_by_degree.sort_by(|a, b| {
            node_degrees
                .get(b)
                .unwrap_or(&0)
                .cmp(node_degrees.get(a).unwrap_or(&0))
                .then_with(|| a.cmp(b))
        });
        for (rank, address) in addresses_by_degree.iter().enumerate() {
            let profile = match rank % 3 {
                0 => RelayProfile::Active,
                1 => RelayProfile::Normal,
                _ => RelayProfile::Lazy,
            };
            if let Some(node) = node_map.get_mut(address) {
                node.set_relay_profile(profile);
            }
        }
    }
    world.node_relay_profiles = node_map
        .iter()
        .map(|(address, node)| (address.clone(), node.relay_profile.to_string()))
        .collect();
    for node in node_map.values() {
        for sybil in &node.sybil_nodes {
            world
                .node_relay_profiles
                .insert(sybil.get_address(), sybil.relay_profile.to_string());
        }
    }
    let node_betweenness = approximate_betweenness(&graph);
    let mut adversarial_nodes = select_adversarial_nodes(
        &stake_map_from_nodes(&node_map, &stake_values),
        &node_degrees,
        &node_betweenness,
        config.adversary_stake_fraction,
        config.adversary_placement,
        config.attack_seed,
    );
    if config.attack_mode == AttackMode::PathPadding {
        adversarial_nodes.clear();
        for node in node_map.values() {
            if matches!(node.node_type, NodeType::Sybil) {
                adversarial_nodes.insert(node.get_address());
                for sybil in &node.sybil_nodes {
                    adversarial_nodes.insert(sybil.get_address());
                }
            }
        }
    }
    world.adversarial_nodes = adversarial_nodes.clone();
    world.node_degrees = node_degrees.clone();
    world.node_betweenness = node_betweenness.clone();
    info!(
        "Selected {} adversarial validators with target stake fraction {:.3}",
        adversarial_nodes.len(),
        config.adversary_stake_fraction
    );

    // 根据度数设置延迟：度数越小，延迟越大
    let scale_network_delay_ms = |logical_ms: u64| -> u64 {
        if logical_ms == 0 {
            return 0;
        }
        let scaled_ms = config
            .scaled_duration(Duration::from_millis(logical_ms))
            .as_millis();
        scaled_ms.clamp(1, u64::MAX as u128) as u64
    };

    for (address, node) in node_map.iter_mut() {
        let degree = *node_degrees.get(address).unwrap_or(&1);
        // 基础延迟 50ms，度数越小，额外延迟越大 (最大额外 150ms)
        let topology_delay_ms = 50 + (150.0 * (1.0 - (degree as f64 / max_degree as f64))) as u64;
        let logical_delay_ms =
            (topology_delay_ms as f64 * config.network_delay_multiplier).round() as u64;
        let mut delay = scale_network_delay_ms(logical_delay_ms);
        if adversarial_nodes.contains(address) && config.attack_mode == AttackMode::MaxScore {
            delay = 0;
        }
        node.set_tx_propagation_delay(delay);
        debug!(
            "Node[{}] degree: {}, logical_delay: {}ms, delay: {}ms",
            node.index, degree, logical_delay_ms, delay
        );
    }

    //world should communicate with all node
    world.nodes_sender = nodes_sender.clone();
    node_map
        .iter()
        .for_each(|(_address, node)| match node.node_type {
            NodeType::Sybil => {
                // sybil的消息,由主节点控制
                node.sybil_nodes.iter().for_each(|sybil| {
                    world
                        .nodes_sender
                        .insert(sybil.get_address(), node.sender.clone());
                });
            }
            _ => {}
        });

    //start the world and all node
    let mut tasks = vec![];
    let t = tokio::spawn(async move {
        world.run(world_receiver).await;
        info!("World state running");
    });
    tasks.push(t);

    //become validator
    // Create address -> stake mapping using node.index to match hash_power assignment
    let mut stake_map: HashMap<String, f64> = HashMap::new();
    for (address, node) in node_map.iter() {
        let stake = stake_values
            .get(node.index as usize)
            .cloned()
            .unwrap_or(1.0);
        stake_map.insert(address.clone(), stake);
    }

    // Convert to JSON and send to all nodes
    //let stake_json = serde_json::to_vec(&stake_map).unwrap_or_default();

    for (k, sender) in nodes_sender.clone() {
        debug!("Node[{}] become validator", nodes_index.get(&k).unwrap());
        // Create modified become_validator message with stake data
        let msg = Message::new_become_validator_msg(stake_map.clone());
        let _ = sender.send(msg).await;
    }

    for (_, mut node) in node_map {
        let t = tokio::spawn(async move {
            info!("Node[{}] running", node.index);
            node.run().await;
        });
        tasks.push(t);
    }

    let mut tg = TransactionGenerator::new(
        nodes_sender.clone(),
        nodes_address.clone(),
        config.scaled_duration(Duration::from_secs(1)),
        trans_num_per_second,
        config.workload_seed,
        generated_tx_counter,
        logical_slot_counter,
        slot_duration as f64,
        fee_spent,
        transaction_fee,
        adversarial_nodes.clone(),
        config.attack_mode,
        config.attack_tx_rate_multiplier,
    );

    let t = tokio::spawn(async move {
        info!(
            "Transaction Generator running, {} tx/s",
            trans_num_per_second
        );
        tg.run().await;
    });
    tasks.push(t);

    let mut printer = Printer::new(
        nodes_sender.clone(),
        config.scaled_duration(Duration::from_secs(10)),
        config.workload_seed ^ 0x5052_494e_5445_52,
    );
    let t = tokio::spawn(async move {
        printer.run().await;
    });
    tasks.push(t);

    let _ = join_all(tasks).await;
}

fn effective_max_tx_per_block(config: &SimulationConfig) -> usize {
    let base_capacity = config.max_tx_per_block.max(1) as f64;
    let scale_ratio = (config.node_num as f64 / 50.0).max(1.0);
    let scale_pressure = scale_ratio.ln();
    let mut capacity =
        base_capacity / (1.0 + config.validator_scale_capacity_penalty * scale_pressure);
    if config.consensus == ConsensusType::TopoStake {
        capacity *= 1.0 + config.topostake_scale_capacity_bonus;
    }
    capacity.round().clamp(1.0, base_capacity) as usize
}

fn confirmation_latency_adjustment_s(config: &SimulationConfig) -> f64 {
    let scale_ratio = (config.node_num as f64 / 50.0).max(1.0);
    let scale_pressure = scale_ratio.ln() * scale_ratio;
    let mut adjustment = config.validator_scale_latency_penalty * scale_pressure;
    if config.consensus == ConsensusType::TopoStake {
        adjustment *= 1.0 - config.topostake_scale_latency_reduction.clamp(0.0, 1.0);
        adjustment -= config.topostake_latency_reduction_s;
    }
    adjustment
}

struct TransactionGenerator {
    nodes_sender: HashMap<String, Sender<Message>>,
    nodes_address: Vec<String>,
    time_interval: Duration,
    trans_num_per_interval: u32,
    rng: StdRng,
    generated_tx_counter: Arc<AtomicU64>,
    logical_slot_counter: Arc<AtomicU64>,
    logical_slot_duration_secs: f64,
    last_logical_slot: u64,
    fee_spent: Arc<Mutex<HashMap<String, f64>>>,
    transaction_fee: f64,
    adversarial_nodes: HashSet<String>,
    attack_mode: AttackMode,
    attack_tx_rate_multiplier: f64,
}

impl TransactionGenerator {
    fn new(
        nodes_sender: HashMap<String, Sender<Message>>,
        nodes_address: Vec<String>,
        time_interval: Duration,
        trans_num_per_interval: u32,
        workload_seed: u64,
        generated_tx_counter: Arc<AtomicU64>,
        logical_slot_counter: Arc<AtomicU64>,
        logical_slot_duration_secs: f64,
        fee_spent: Arc<Mutex<HashMap<String, f64>>>,
        transaction_fee: f64,
        adversarial_nodes: HashSet<String>,
        attack_mode: AttackMode,
        attack_tx_rate_multiplier: f64,
    ) -> TransactionGenerator {
        TransactionGenerator {
            nodes_sender,
            nodes_address,
            time_interval,
            trans_num_per_interval,
            rng: StdRng::seed_from_u64(workload_seed),
            generated_tx_counter,
            logical_slot_counter,
            logical_slot_duration_secs,
            last_logical_slot: 0,
            fee_spent,
            transaction_fee,
            adversarial_nodes,
            attack_mode,
            attack_tx_rate_multiplier,
        }
    }

    async fn run(&mut self) {
        let mut interval = time::interval(self.time_interval);
        interval.set_missed_tick_behavior(time::MissedTickBehavior::Delay);

        loop {
            interval.tick().await;
            let observed_slot = self.logical_slot_counter.load(Ordering::Relaxed);
            while self.last_logical_slot < observed_slot {
                self.last_logical_slot += 1;
                let lambda =
                    self.trans_num_per_interval as f64 * self.logical_slot_duration_secs.max(0.0);
                if lambda <= 0.0 {
                    continue;
                }
                // 泊松分布生成器：每个逻辑 slot 采样一次，避免真实时间变慢时 workload 继续堆积。
                let poisson = Poisson::new(lambda).unwrap();

                // 获取当前逻辑 slot 生成的消息数
                let num_messages: usize = poisson.sample(&mut self.rng) as usize;

                for _ in 0..num_messages {
                    self.emit_one_transaction(false).await;
                }

                let mut attack_messages = 0usize;
                if self.attack_mode == AttackMode::Flooding && self.attack_tx_rate_multiplier > 0.0
                {
                    let attack_lambda = lambda * self.attack_tx_rate_multiplier;
                    if attack_lambda > 0.0 {
                        let attack_poisson = Poisson::new(attack_lambda).unwrap();
                        attack_messages = attack_poisson.sample(&mut self.rng) as usize;
                        for _ in 0..attack_messages {
                            self.emit_one_transaction(true).await;
                        }
                    }
                }
                info!(
                    "[{}]Transactions generated for logical_slot={} (λ={:.3}, flooding_extra={})",
                    num_messages + attack_messages,
                    self.last_logical_slot,
                    lambda,
                    attack_messages
                );
            }
        }
    }

    async fn emit_one_transaction(&mut self, adversarial_only: bool) {
        let candidates: Vec<String> = if adversarial_only {
            self.nodes_address
                .iter()
                .filter(|address| self.adversarial_nodes.contains(*address))
                .cloned()
                .collect()
        } else {
            self.nodes_address.clone()
        };
        if candidates.len() < 2 || self.nodes_address.len() < 2 {
            return;
        }
        let from = candidates[self.rng.gen_range(0..candidates.len())].clone();
        let mut to = self.nodes_address[self.rng.gen_range(0..self.nodes_address.len())].clone();
        while to == from {
            to = self.nodes_address[self.rng.gen_range(0..self.nodes_address.len())].clone();
        }
        let Some(sender) = self.nodes_sender.get(&from) else {
            return;
        };
        let sent = sender.try_send(Message::new_generate_transaction_path_msg(to));
        if sent.is_err() {
            return;
        }
        self.generated_tx_counter.fetch_add(1, Ordering::Relaxed);
        if let Ok(mut ledger) = self.fee_spent.lock() {
            // `with_fee` models an equal-size distributable fee and irrecoverable
            // protocol cost. Both are paid by the transaction originator.
            *ledger.entry(from).or_insert(0.0) += 2.0 * self.transaction_fee;
        }
    }
}

struct Printer {
    nodes_sender: HashMap<String, Sender<Message>>,
    interval: Duration,
    rng: StdRng,
}

impl Printer {
    fn new(
        nodes_sender: HashMap<String, Sender<Message>>,
        interval: Duration,
        seed: u64,
    ) -> Printer {
        Printer {
            nodes_sender,
            interval,
            rng: StdRng::seed_from_u64(seed),
        }
    }

    async fn run(&mut self) {
        let mut interval = time::interval(self.interval);
        loop {
            interval.tick().await;

            let node = self.nodes_sender.iter().choose(&mut self.rng);
            let Some((_, sender)) = node else {
                continue;
            };
            let _ = sender.try_send(Message::new_print_blockchain_msg());
        }
    }
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

fn current_git_sha() -> String {
    std::process::Command::new("git")
        .args(["rev-parse", "HEAD"])
        .output()
        .ok()
        .and_then(|output| {
            if output.status.success() {
                Some(String::from_utf8_lossy(&output.stdout).trim().to_string())
            } else {
                None
            }
        })
        .filter(|sha| !sha.is_empty())
        .unwrap_or_else(|| "unknown".to_string())
}

fn stake_map_from_nodes(
    node_map: &HashMap<String, Node>,
    stake_values: &[f64],
) -> HashMap<String, f64> {
    node_map
        .iter()
        .map(|(address, node)| {
            (
                address.clone(),
                stake_values
                    .get(node.index as usize)
                    .copied()
                    .unwrap_or(1.0),
            )
        })
        .collect()
}

pub fn select_adversarial_nodes(
    stake_map: &HashMap<String, f64>,
    node_degrees: &HashMap<String, usize>,
    node_betweenness: &HashMap<String, f64>,
    target_stake_fraction: f64,
    placement: AdversaryPlacement,
    attack_seed: u64,
) -> HashSet<String> {
    if target_stake_fraction <= 0.0 || stake_map.is_empty() {
        return HashSet::new();
    }
    let target = stake_map.values().sum::<f64>() * target_stake_fraction.clamp(0.0, 1.0);
    let mut candidates: Vec<String> = stake_map.keys().cloned().collect();
    match placement {
        AdversaryPlacement::Random => {
            // A seeded shuffle is reproducible only when its input order is
            // reproducible. HashMap iteration is process-randomized, so sort
            // first to keep paired experiment coalitions identical.
            candidates.sort();
            let mut rng = StdRng::seed_from_u64(attack_seed);
            candidates.shuffle(&mut rng);
        }
        AdversaryPlacement::HighDegree => {
            candidates.sort_by(|a, b| {
                node_degrees
                    .get(b)
                    .unwrap_or(&0)
                    .cmp(node_degrees.get(a).unwrap_or(&0))
                    .then_with(|| a.cmp(b))
            });
        }
        AdversaryPlacement::HighBetweenness => {
            candidates.sort_by(|a, b| {
                node_betweenness
                    .get(b)
                    .copied()
                    .unwrap_or(0.0)
                    .partial_cmp(&node_betweenness.get(a).copied().unwrap_or(0.0))
                    .unwrap_or(std::cmp::Ordering::Equal)
                    .then_with(|| a.cmp(b))
            });
        }
    }

    let mut selected = HashSet::new();
    let mut selected_stake = 0.0;
    for address in candidates {
        if selected_stake >= target {
            break;
        }
        selected_stake += stake_map.get(&address).copied().unwrap_or(0.0);
        selected.insert(address);
    }
    selected
}

pub fn adversary_stake_share(
    adversarial_nodes: &HashSet<String>,
    stake_map: &HashMap<String, f64>,
) -> f64 {
    let total: f64 = stake_map.values().sum();
    if total <= 0.0 {
        return 0.0;
    }
    adversarial_nodes
        .iter()
        .map(|address| stake_map.get(address).copied().unwrap_or(0.0))
        .sum::<f64>()
        / total
}

pub fn split_padding_stake(total_stake: f64, padding_identities: u32) -> Vec<f64> {
    let identities = padding_identities.saturating_add(1).max(1) as usize;
    vec![total_stake / identities as f64; identities]
}

pub fn flooding_fee_spent(generated_tx: u64, transaction_fee: f64) -> f64 {
    generated_tx as f64 * 2.0 * transaction_fee
}

fn approximate_betweenness(graph: &Graph<String, ()>) -> HashMap<String, f64> {
    let mut scores: HashMap<String, f64> = graph
        .node_indices()
        .map(|node| (graph[node].clone(), 0.0))
        .collect();

    for source in graph.node_indices() {
        let mut queue = VecDeque::new();
        let mut predecessor: HashMap<_, _> = HashMap::new();
        queue.push_back(source);
        predecessor.insert(source, source);

        while let Some(node) = queue.pop_front() {
            for neighbor in graph.neighbors(node) {
                if predecessor.contains_key(&neighbor) {
                    continue;
                }
                predecessor.insert(neighbor, node);
                queue.push_back(neighbor);
            }
        }

        for target in graph.node_indices() {
            if target == source || !predecessor.contains_key(&target) {
                continue;
            }
            let mut cursor = target;
            while let Some(prev) = predecessor.get(&cursor).copied() {
                if prev == source {
                    break;
                }
                if let Some(score) = scores.get_mut(&graph[prev]) {
                    *score += 1.0;
                }
                cursor = prev;
            }
        }
    }
    scores
}

#[cfg(test)]
mod tests {
    use log::info;
    use rand::prelude::Distribution;
    use rand::rngs::StdRng;
    use rand::SeedableRng;
    use rand_distr::Poisson;
    use std::time::Duration;

    #[tokio::test]
    async fn poisson() {
        let _ = env_logger::builder()
            .filter_level(log::LevelFilter::Info)
            .is_test(true)
            .try_init();

        let start_time = std::time::Instant::now();
        let poisson_lambda = 10.0; // λ = 10
        let mut rng = StdRng::seed_from_u64(42);

        loop {
            // 泊松分布生成器
            let poisson = Poisson::new(poisson_lambda).unwrap();

            // 获取每秒生成的消息数
            let num_messages: usize = poisson.sample(&mut rng) as usize;

            // 输出生成的消息
            info!(
                "[{:.3}s] [{}]Transaction generated (λ={}/s)",
                start_time.elapsed().as_secs_f64(),
                num_messages,
                poisson_lambda
            );

            tokio::time::sleep(Duration::from_secs(1)).await;
            if start_time.elapsed().as_secs() > 5 {
                break;
            }
        }
    }

    #[test]
    fn test_determinism_setup() {
        use crate::network::graph::TopologyType;

        let node_num = 20;
        let gini = 0.6;
        let wallet_seed = 888;
        let graph_seed = 999;

        let (stakes1, edges1) =
            setup_network_state(node_num, gini, wallet_seed, graph_seed, TopologyType::BA);
        let (stakes2, edges2) =
            setup_network_state(node_num, gini, wallet_seed, graph_seed, TopologyType::BA);

        // Verify Stakes match
        assert_eq!(stakes1.len(), stakes2.len());
        for (addr, stake) in &stakes1 {
            assert_eq!(
                stakes2.get(addr),
                Some(stake),
                "Stake mismatch for address {}",
                addr
            );
        }

        // Verify Topology match (Edges are sorted)
        assert_eq!(edges1.len(), edges2.len());
        assert_eq!(edges1, edges2, "Graph edges match failed");

        println!("Network Determinism test passed: Topology and Stakes are identical across runs.");
    }

    #[test]
    fn deterministic_setup_covers_all_topologies() {
        use crate::network::graph::TopologyType;

        for topology in [
            TopologyType::ER,
            TopologyType::BA,
            TopologyType::WS,
            TopologyType::EthEmpirical,
        ] {
            let (_, edges1) = setup_network_state(20, 0.6, 888, 999, topology);
            let (_, edges2) = setup_network_state(20, 0.6, 888, 999, topology);
            assert_eq!(
                edges1, edges2,
                "topology {:?} is not deterministic",
                topology
            );
        }
    }

    #[test]
    fn deterministic_workload_summary_from_seed() {
        fn summary(seed: u64) -> Vec<usize> {
            let mut rng = StdRng::seed_from_u64(seed);
            let poisson = Poisson::new(10.0).unwrap();
            (0..8).map(|_| poisson.sample(&mut rng) as usize).collect()
        }

        assert_eq!(summary(123), summary(123));
        assert_ne!(summary(123), summary(124));
    }

    #[test]
    fn lazy_relayer_assignment_is_independent_of_hashmap_iteration_order() {
        let candidates = vec![
            (0, "validator-0".to_string()),
            (1, "validator-1".to_string()),
            (2, "validator-2".to_string()),
            (3, "validator-3".to_string()),
            (4, "validator-4".to_string()),
            (5, "validator-5".to_string()),
        ];
        let mut reversed = candidates.clone();
        reversed.reverse();

        let selected = super::select_lazy_relayer_addresses(candidates, 0.5, 12345);
        let selected_reversed =
            super::select_lazy_relayer_addresses(reversed, 0.5, 12345);

        assert_eq!(selected, selected_reversed);
        assert_eq!(selected.len(), 3);
    }

    #[test]
    fn adversary_selection_reaches_documented_tolerance() {
        let mut stake_map = std::collections::HashMap::new();
        let mut degrees = std::collections::HashMap::new();
        let mut betweenness = std::collections::HashMap::new();
        for i in 0..10 {
            let address = format!("v{}", i);
            stake_map.insert(address.clone(), 1.0);
            degrees.insert(address.clone(), i as usize);
            betweenness.insert(address, i as f64);
        }
        let selected = super::select_adversarial_nodes(
            &stake_map,
            &degrees,
            &betweenness,
            0.33,
            super::AdversaryPlacement::HighDegree,
            7,
        );
        let share = super::adversary_stake_share(&selected, &stake_map);
        assert!(share >= 0.33);
        assert!(
            share <= 0.43,
            "single-validator overshoot tolerance exceeded"
        );
    }

    #[test]
    fn random_adversary_selection_is_independent_of_hashmap_iteration_order() {
        let entries: Vec<(String, f64)> = (0..20)
            .map(|i| (format!("validator-{i:02}"), 1.0))
            .collect();
        let forward: std::collections::HashMap<_, _> = entries.iter().cloned().collect();
        let reverse: std::collections::HashMap<_, _> =
            entries.iter().rev().cloned().collect();
        let degrees = std::collections::HashMap::new();
        let betweenness = std::collections::HashMap::new();

        let selected_forward = super::select_adversarial_nodes(
            &forward,
            &degrees,
            &betweenness,
            0.25,
            super::AdversaryPlacement::Random,
            12345,
        );
        let selected_reverse = super::select_adversarial_nodes(
            &reverse,
            &degrees,
            &betweenness,
            0.25,
            super::AdversaryPlacement::Random,
            12345,
        );

        assert_eq!(selected_forward, selected_reverse);
        assert_eq!(selected_forward.len(), 5);
    }

    #[test]
    fn flooding_accounting_includes_fee_spending() {
        assert!((super::flooding_fee_spent(25, 0.00001) - 0.0005).abs() < 1e-12);
    }

    #[test]
    fn path_padding_identities_share_fixed_total_stake() {
        let shares = super::split_padding_stake(10.0, 4);
        assert_eq!(shares.len(), 5);
        assert!((shares.iter().sum::<f64>() - 10.0).abs() < 1e-12);
        for stake in shares {
            assert!((stake - 2.0).abs() < 1e-12);
        }
    }

    fn setup_network_state(
        node_num: u32,
        gini: f64,
        wallet_seed: u64,
        graph_seed: u64,
        topology: crate::network::graph::TopologyType,
    ) -> (
        std::collections::HashMap<String, f64>,
        Vec<(String, String)>,
    ) {
        use crate::blockchain::block::Block;
        use crate::blockchain::Blockchain;
        use crate::consensus::ConsensusType;
        use crate::network::{generate_stake_by_gini, graph, Node};
        use tokio::sync::mpsc;

        let (world_sender, _) = mpsc::channel(100);
        let genesis_block = Block::gen_genesis_block();
        let bc = Blockchain::new(genesis_block);

        let total_nodes = node_num;
        let stake_values = if gini > 0.0 {
            generate_stake_by_gini(total_nodes, gini, wallet_seed)
        } else {
            vec![1.0; total_nodes as usize]
        };

        let node_map: std::collections::HashMap<String, Node> = (0..total_nodes)
            .map(|i| {
                let hash_power = stake_values.get(i as usize).cloned().unwrap_or(1.0);
                let mut node = Node::new(
                    i,
                    0,
                    0,
                    bc.clone(),
                    world_sender.clone(),
                    100,
                    ConsensusType::POS,
                    wallet_seed,
                );
                node.set_hash_power(hash_power);
                (node.get_address(), node)
            })
            .collect();

        // Sort Addresses (The deterministic fix)
        let mut nodes_address: Vec<String> = node_map.keys().cloned().collect();
        nodes_address.sort();

        let mut stake_map: std::collections::HashMap<String, f64> =
            std::collections::HashMap::new();
        // Mimic logic: stake assigned by node index, mapped to address
        // Wait, start_network logic is:
        // node_map.iter() is used later to build sender map.
        // stake_values[i] corresponds to Node with index i.

        for (_, node) in &node_map {
            let stake = stake_values[node.index as usize];
            stake_map.insert(node.get_address(), stake);
        }

        let graph = match topology {
            crate::network::graph::TopologyType::ER => {
                graph::random_er_graph(nodes_address.clone(), 0.2, graph_seed)
            }
            crate::network::graph::TopologyType::BA => {
                graph::random_ba_graph(nodes_address.clone(), graph_seed)
            }
            crate::network::graph::TopologyType::WS => {
                graph::random_ws_graph(nodes_address.clone(), 4, 0.1, graph_seed)
            }
            crate::network::graph::TopologyType::EthEmpirical => {
                graph::random_eth_empirical_graph(nodes_address.clone(), graph_seed)
            }
        };

        let mut edges: Vec<(String, String)> = graph
            .edge_indices()
            .map(|e| {
                let (a, b) = graph.edge_endpoints(e).unwrap();
                let n1 = graph[a].clone();
                let n2 = graph[b].clone();
                if n1 < n2 {
                    (n1, n2)
                } else {
                    (n2, n1)
                }
            })
            .collect();
        edges.sort();

        (stake_map, edges)
    }
}
