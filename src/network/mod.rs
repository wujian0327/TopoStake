use crate::blockchain::block::Block;
use crate::blockchain::Blockchain;
use crate::consensus::ConsensusType;
use crate::network::graph::TopologyType;
use crate::network::message::Message;
use crate::network::node::{Neighbor, Node, NodeType};
use crate::network::world_state::WorldState;
use futures::future::join_all;
use log::{debug, info};
use rand::prelude::*;
use rand::thread_rng;
use rand_distr::{Distribution, Poisson};
use std::collections::HashMap;
use std::time::Duration;
use tokio::sync::mpsc::Sender;
use tokio::time;

pub mod graph;
pub mod message;
pub mod node;
pub mod world_state;

pub async fn start_network(
    node_num: u32,
    sybil_node_num: u32,
    fake_node_num: u32,
    unstable_node_num: u32,
    offline_probability: f64,
    trans_num_per_second: u32,
    slot_duration: u64,
    slot_per_epoch: u64,
    pow_difficulty: usize,
    pow_max_threads: usize,
    consensus: ConsensusType,
    topology: TopologyType,
    gini: f64,
    transaction_fee: f64,
    graph_seed: u64,
    base_reward: f64,
    max_tx_per_block: usize,
    wallet_seed: u64,
    max_epochs: u64,
) {
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
        base_reward,
        node_num,
        trans_num_per_second,
        topology.to_string(),
        max_epochs,
    );
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
                node.set_transaction_fee(transaction_fee);
                node.set_hash_power(hash_power);
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
                node.set_transaction_fee(transaction_fee);
                node.set_hash_power(hash_power);
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
                node.set_node_type(NodeType::Unstable);
                node.set_offline_probability(offline_probability);
                node.set_transaction_fee(transaction_fee);
                node.set_hash_power(hash_power);
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

    let mut nodes_address: Vec<String> = node_map.keys().cloned().collect();
    nodes_address.sort();
    info!(
        "Generate {} honest nodes, {} sybil nodes, {} unstable nodes",
        node_num, sybil_node_num, unstable_node_num
    );

    //4. gen the network graph
    let graph = match topology {
        TopologyType::ER => graph::random_er_graph(nodes_address.clone(), 0.1),
        TopologyType::BA => graph::random_ba_graph(nodes_address.clone(), graph_seed),
        TopologyType::WS => graph::random_ws_graph(nodes_address.clone(), 4, 0.1, graph_seed),
    };
    info!("Generate network graph[{}]", topology);
    tokio::time::sleep(Duration::from_secs(3)).await;

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

    // 根据度数设置延迟：度数越小，延迟越大
    for (address, node) in node_map.iter_mut() {
        let degree = *node_degrees.get(address).unwrap_or(&1);
        // 基础延迟 50ms，度数越小，额外延迟越大 (最大额外 150ms)
        let delay = 50 + (150.0 * (1.0 - (degree as f64 / max_degree as f64))) as u64;
        node.set_tx_propagation_delay(delay);
        debug!(
            "Node[{}] degree: {}, delay: {}ms",
            node.index, degree, delay
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
        sender.send(msg).await.unwrap();
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
        Duration::from_secs(1),
        trans_num_per_second,
    );

    let t = tokio::spawn(async move {
        info!(
            "Transaction Generator running, {} tx/s",
            trans_num_per_second
        );
        tg.run().await;
    });
    tasks.push(t);

    let mut printer = Printer::new(nodes_sender.clone(), Duration::from_secs(10));
    let t = tokio::spawn(async move {
        printer.run().await;
    });
    tasks.push(t);

    let _ = join_all(tasks).await;
}

struct TransactionGenerator {
    nodes_sender: HashMap<String, Sender<Message>>,
    nodes_address: Vec<String>,
    time_interval: Duration,
    trans_num_per_interval: u32,
}

impl TransactionGenerator {
    fn new(
        nodes_sender: HashMap<String, Sender<Message>>,
        nodes_address: Vec<String>,
        time_interval: Duration,
        trans_num_per_interval: u32,
    ) -> TransactionGenerator {
        TransactionGenerator {
            nodes_sender,
            nodes_address,
            time_interval,
            trans_num_per_interval,
        }
    }

    async fn run(&mut self) {
        let mut interval = time::interval(self.time_interval);

        loop {
            interval.tick().await;
            // 泊松分布生成器
            let poisson = Poisson::new(self.trans_num_per_interval as f64).unwrap();

            // 获取每秒生成的消息数
            let num_messages: usize = poisson.sample(&mut thread_rng()) as usize;

            for _ in 0..num_messages {
                let node = self.nodes_sender.iter().choose(&mut thread_rng());

                if let Some(node) = node {
                    let to = self
                        .nodes_address
                        .iter()
                        .filter(|x| **x != node.0.clone())
                        .choose(&mut rand::thread_rng())
                        .unwrap();
                    node.1
                        .send(Message::new_generate_transaction_path_msg(to.clone()))
                        .await
                        .unwrap();
                }
            }
            info!(
                "[{}]Transactions generated (λ={})",
                num_messages, self.trans_num_per_interval
            );
        }
    }
}

struct Printer {
    nodes_sender: HashMap<String, Sender<Message>>,
    interval: Duration,
}

impl Printer {
    fn new(nodes_sender: HashMap<String, Sender<Message>>, interval: Duration) -> Printer {
        Printer {
            nodes_sender,
            interval,
        }
    }

    async fn run(&mut self) {
        let mut interval = time::interval(self.interval);
        loop {
            interval.tick().await;

            let node = self.nodes_sender.iter().choose(&mut rand::thread_rng());
            node.unwrap()
                .1
                .send(Message::new_print_blockchain_msg())
                .await
                .unwrap();
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

#[cfg(test)]
mod tests {
    use log::info;
    use rand::prelude::Distribution;
    use rand::thread_rng;
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

        loop {
            // 泊松分布生成器
            let poisson = Poisson::new(poisson_lambda).unwrap();

            // 获取每秒生成的消息数
            let num_messages: usize = poisson.sample(&mut thread_rng()) as usize;

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
        use crate::blockchain::block::Block;
        use crate::blockchain::Blockchain;
        use crate::consensus::ConsensusType;
        use crate::network::graph::TopologyType;
        use tokio::sync::mpsc;

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
        use crate::network::{generate_stake_by_gini, graph, Node, NodeType};
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

        let mut node_map: std::collections::HashMap<String, Node> = (0..total_nodes)
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
                graph::random_er_graph(nodes_address.clone(), 0.2)
            }
            crate::network::graph::TopologyType::BA => {
                graph::random_ba_graph(nodes_address.clone(), graph_seed)
            }
            crate::network::graph::TopologyType::WS => {
                graph::random_ws_graph(nodes_address.clone(), 4, 0.1, graph_seed)
            }
        };

        use petgraph::visit::EdgeRef;
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
