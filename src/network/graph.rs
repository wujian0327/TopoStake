use clap::ValueEnum;
use petgraph::graph::NodeIndex;
use petgraph::prelude::EdgeRef;
use petgraph::Graph;
use rand::Rng;
use rand::SeedableRng;
use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};
use std::fmt;
use std::fmt::{Display, Formatter};
use std::fs::File;

#[derive(ValueEnum, Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub enum TopologyType {
    ER,
    BA,
    WS,
    #[value(name = "eth_empirical", alias = "eth-empirical")]
    EthEmpirical,
}

impl Display for TopologyType {
    fn fmt(&self, f: &mut Formatter) -> fmt::Result {
        match *self {
            TopologyType::ER => {
                write!(f, "er")
            }
            TopologyType::BA => {
                write!(f, "ba")
            }
            TopologyType::WS => {
                write!(f, "ws")
            }
            TopologyType::EthEmpirical => {
                write!(f, "eth_empirical")
            }
        }
    }
}

//Barabási–Albert 模型，用于生成无标度网络
struct BANetwork {
    adjacency: HashMap<usize, HashSet<usize>>, // 邻接表：节点 -> 连接的节点
    degrees: Vec<usize>,                       // 节点度数列表（索引为节点ID）
    total_edges: usize,                        // 总边数的两倍（无向图）
    rng: rand::rngs::StdRng,                   // 随机数生成器（带种子）
}

impl BANetwork {
    fn new(m0: usize, rng: rand::rngs::StdRng) -> Self {
        let mut adjacency = HashMap::new();
        let mut degrees = vec![0; m0];

        // 初始化为全连通
        for i in 0..m0 {
            let mut neighbors = HashSet::new();
            for j in 0..m0 {
                if i != j {
                    neighbors.insert(j);
                }
            }
            adjacency.insert(i, neighbors);
            degrees[i] = m0 - 1; // 初始每个节点度数 = m0-1
        }

        BANetwork {
            adjacency,
            degrees,
            total_edges: m0 * (m0 - 1), // 总边数（无向图每条边算两次）
            rng,
        }
    }

    // 选择要连接的节点（返回选中的节点ID）
    fn choose_node(&mut self) -> usize {
        use rand::Rng;
        let mut sum = 0;
        let target = self.rng.gen_range(0..self.total_edges);

        // 遍历所有节点，通过度数累计概率
        for (node, &degree) in self.degrees.iter().enumerate() {
            sum += degree;
            if sum > target {
                return node;
            }
        }
        panic!("Selection failed"); // 理论上不应触发
    }

    fn add_node(&mut self, m: usize) {
        let new_node = self.degrees.len();
        let mut set: HashSet<usize> = HashSet::new();

        // 选择 m 个不同的节点进行连接
        // 需要确保不会选择相同的节点，且不会选择自己
        while set.len() < m && set.len() < self.degrees.len() {
            let target = self.choose_node();
            // 避免自连接（虽然在 BA 模型中不应该发生）
            if target != new_node {
                set.insert(target);
            }
        }

        // 更新现有节点的邻接表和度数
        for target in set.iter() {
            self.adjacency.get_mut(target).unwrap().insert(new_node);
            self.degrees[*target] += 1;
            self.total_edges += 2; // 无向图，双向各加1
        }

        // 添加新节点
        self.adjacency.insert(new_node, set.clone());
        self.degrees.push(set.len()); // 新节点的度数 = 实际连接数
    }

    fn generate_ba_network(n_nodes: usize, m0: usize, m: usize, seed: u64) -> BANetwork {
        assert!(m <= m0, "m must be ≤ m0");
        use rand::SeedableRng;
        let rng = rand::rngs::StdRng::seed_from_u64(seed);
        let mut network = BANetwork::new(m0, rng);

        for _ in m0..n_nodes {
            network.add_node(m);
        }
        network
    }
}

//Erdős–Rényi(ER)拓扑
pub fn random_er_graph(
    nodes_address: Vec<String>,
    probability: f64,
    seed: u64,
) -> Graph<String, ()> {
    let mut graph = Graph::<String, ()>::new();
    let mut rng = rand::rngs::StdRng::seed_from_u64(seed);

    let nodes: Vec<NodeIndex> = nodes_address
        .iter()
        .map(|i| graph.add_node(i.clone()))
        .collect();

    // 以 p 的概率生成边
    for i in 0..nodes.len() {
        for j in (i + 1)..nodes.len() {
            if rng.gen::<f64>() < probability {
                graph.add_edge(nodes[i], nodes[j], ());
            }
        }
    }

    print_graph(&graph.clone());
    graph
}

pub fn random_ba_graph(nodes_address: Vec<String>, seed: u64) -> Graph<String, ()> {
    let node_number = nodes_address.len();
    let ba_network = BANetwork::generate_ba_network(node_number, 3, 2, seed);
    let adj = ba_network.adjacency;

    let mut graph = Graph::<String, ()>::new();
    let mut node_map = HashMap::new();
    for (x, _) in adj.clone() {
        let node = graph.add_node(nodes_address[x].clone());
        node_map.insert(nodes_address[x].clone(), node);
    }
    for (x, edge) in adj {
        let from = node_map.get(&nodes_address[x].clone()).unwrap();
        for y in edge {
            let to = node_map.get(&nodes_address[y].clone()).unwrap();
            graph.add_edge(*from, *to, ());
        }
    }

    print_graph(&graph.clone());
    graph
}

/// Generate a connected, Ethereum-measurement-calibrated synthetic topology.
///
/// Public Ethereum topology measurements do not provide a reusable mainnet
/// adjacency snapshot. They do, however, consistently describe a sparse,
/// heavy-tailed peer graph. We therefore use preferential attachment with nine
/// links per arriving node. At 1,000 nodes this yields an average degree of
/// approximately 18, while retaining the observed pattern in which most nodes
/// have modest degree and a small minority form high-degree hubs.
///
/// This is an empirical *profile*, not a reconstruction of a specific crawl.
pub fn random_eth_empirical_graph(nodes_address: Vec<String>, seed: u64) -> Graph<String, ()> {
    const LINKS_PER_NEW_NODE: usize = 9;
    const INITIAL_CLIQUE_SIZE: usize = LINKS_PER_NEW_NODE + 1;

    let node_number = nodes_address.len();
    let initial_clique = node_number.min(INITIAL_CLIQUE_SIZE);
    let links_per_new_node = LINKS_PER_NEW_NODE.min(initial_clique.saturating_sub(1));

    let mut graph = Graph::<String, ()>::new();
    let node_indices: Vec<NodeIndex> = nodes_address
        .iter()
        .map(|address| graph.add_node(address.clone()))
        .collect();

    if node_number < 2 {
        print_graph(&graph);
        return graph;
    }

    let network = BANetwork::generate_ba_network(
        node_number,
        initial_clique,
        links_per_new_node,
        seed,
    );
    let mut edges = Vec::new();
    for (source, neighbors) in network.adjacency {
        for target in neighbors {
            if source < target {
                edges.push((source, target));
            }
        }
    }
    edges.sort_unstable();
    for (source, target) in edges {
        graph.add_edge(node_indices[source], node_indices[target], ());
    }

    print_graph(&graph);
    graph
}

// Watts-Strogatz (WS) 小世界网络模型
pub fn random_ws_graph(
    nodes_address: Vec<String>,
    k: usize,
    p: f64,
    seed: u64,
) -> Graph<String, ()> {
    let n = nodes_address.len();
    assert!(k < n, "k must be less than n");
    assert!(k % 2 == 0, "k must be even");

    use rand::SeedableRng;
    let mut rng = rand::rngs::StdRng::seed_from_u64(seed);
    let mut graph = Graph::<String, ()>::new();
    let mut node_indices = Vec::with_capacity(n);

    // 添加所有节点
    for addr in &nodes_address {
        node_indices.push(graph.add_node(addr.clone()));
    }

    // 记录已存在的边，避免重复添加
    let mut edges = HashSet::new();

    // 1. 构建规则环形格子：每个节点与相邻的 k 个节点相连 (左右各 k/2 个)
    let half_k = k / 2;
    for i in 0..n {
        for j in 1..=half_k {
            let target = (i + j) % n;
            // 确保 i < target 以避免无向图重复记录
            let (u, v) = if i < target { (i, target) } else { (target, i) };
            edges.insert((u, v));
        }
    }

    // 2. 随机重连边
    let mut final_edges = HashSet::new();
    let mut ordered_edges: Vec<(usize, usize)> = edges.iter().copied().collect();
    ordered_edges.sort_unstable();
    for &(u, v) in &ordered_edges {
        if rng.gen::<f64>() < p {
            // 以概率 p 重连这条边
            let mut new_v = rng.gen_range(0..n);
            // 避免自环和重复边
            while new_v == u
                || edges.contains(&(std::cmp::min(u, new_v), std::cmp::max(u, new_v)))
                || final_edges.contains(&(std::cmp::min(u, new_v), std::cmp::max(u, new_v)))
            {
                new_v = rng.gen_range(0..n);
            }
            final_edges.insert((std::cmp::min(u, new_v), std::cmp::max(u, new_v)));
        } else {
            // 保持原边
            final_edges.insert((u, v));
        }
    }

    // 将最终的边添加到图中
    let mut ordered_final_edges: Vec<(usize, usize)> = final_edges.into_iter().collect();
    ordered_final_edges.sort_unstable();
    for (u, v) in ordered_final_edges {
        graph.add_edge(node_indices[u], node_indices[v], ());
    }

    print_graph(&graph.clone());
    graph
}

pub fn print_graph(graph: &Graph<String, ()>) {
    let vec = graph_edges(graph);
    let path = "graph.json";
    let mut file = File::create(path).unwrap();
    serde_json::to_writer_pretty(&mut file, &vec).unwrap();
}

pub fn write_graph_json(graph: &Graph<String, ()>, path: impl AsRef<std::path::Path>) {
    let vec = graph_edges(graph);
    let mut file = File::create(path).unwrap();
    serde_json::to_writer_pretty(&mut file, &vec).unwrap();
}

pub fn graph_edges(graph: &Graph<String, ()>) -> Vec<(String, String)> {
    let mut vec: Vec<(String, String)> = vec![];
    for edge_ref in graph.edge_references() {
        let src = edge_ref.source();
        let dst = edge_ref.target();
        let from = graph.node_weight(src).unwrap().to_string();
        let to = graph.node_weight(dst).unwrap().to_string();
        if vec.iter().find(|&x| x.0 == to && x.1 == from).is_some() {
            continue;
        }
        vec.push((from, to));
    }
    vec.sort();
    vec
}

#[cfg(test)]
mod tests {
    use crate::network::graph::{
        graph_edges, print_graph, random_eth_empirical_graph, BANetwork, TopologyType,
    };
    use clap::ValueEnum;
    use log::info;
    use petgraph::dot::{Config, Dot};
    use petgraph::graph::NodeIndex;

    use petgraph::prelude::EdgeRef;
    use petgraph::Graph;
    use rand::Rng;
    use rand::SeedableRng;
    use std::collections::HashMap;

    #[test]
    fn eth_empirical_cli_name_is_stable() {
        assert_eq!(
            TopologyType::from_str("eth_empirical", false),
            Ok(TopologyType::EthEmpirical)
        );
        assert_eq!(
            TopologyType::from_str("eth-empirical", false),
            Ok(TopologyType::EthEmpirical)
        );
        assert_eq!(TopologyType::EthEmpirical.to_string(), "eth_empirical");
    }

    #[test]
    fn eth_empirical_profile_is_deterministic_connected_and_calibrated() {
        let node_count = 1_000;
        let addresses: Vec<String> = (0..node_count)
            .map(|index| format!("validator-{index}"))
            .collect();
        let graph = random_eth_empirical_graph(addresses.clone(), 42);
        let repeated = random_eth_empirical_graph(addresses, 42);

        assert_eq!(graph_edges(&graph), graph_edges(&repeated));
        assert_eq!(graph.node_count(), node_count);

        let mut degrees = vec![0usize; node_count];
        for edge in graph.edge_references() {
            degrees[edge.source().index()] += 1;
            degrees[edge.target().index()] += 1;
        }
        let average_degree = degrees.iter().sum::<usize>() as f64 / node_count as f64;
        let modest_degree_fraction =
            degrees.iter().filter(|&&degree| degree <= 16).count() as f64 / node_count as f64;
        let below_fifty_fraction =
            degrees.iter().filter(|&&degree| degree < 50).count() as f64 / node_count as f64;

        assert!((17.5..=18.5).contains(&average_degree));
        assert!(modest_degree_fraction >= 0.5);
        assert!(below_fifty_fraction >= 0.93);

        assert_eq!(petgraph::algo::connected_components(&graph), 1);
    }

    #[test]
    fn ba_network() {
        let ba_network = BANetwork::generate_ba_network(100, 3, 2, 42);
        let adj = ba_network.adjacency;

        let mut graph = Graph::<String, ()>::new();
        let mut node_map = HashMap::new();
        for (x, _) in adj.clone() {
            let node = graph.add_node(x.to_string());
            node_map.insert(x, node);
        }
        for (x, edge) in adj {
            let from = node_map.get(&x).unwrap();
            for y in edge {
                let to = node_map.get(&y).unwrap();
                graph.add_edge(from.clone(), to.clone(), ());
            }
        }
        print_graph(&graph);
    }

    #[test]
    fn ba_network_test() {
        let num = 1000;
        let ba_network = BANetwork::generate_ba_network(num, 3, 2, 42);
        let adj = ba_network.adjacency;

        for (x, y) in adj.clone() {
            if y.contains(&x) {
                panic!("Wrong");
            }
        }

        if adj.len() != num {
            panic!("Wrong");
        }

        let mut graph = Graph::<String, ()>::new();
        let mut node_map = HashMap::new();
        for (x, _) in adj.clone() {
            let node = graph.add_node(x.to_string());
            node_map.insert(x, node);
        }
        for (x, edge) in adj {
            let from = node_map.get(&x).unwrap();
            for y in edge {
                let to = node_map.get(&y).unwrap();
                graph.add_edge(from.clone(), to.clone(), ());
            }
        }

        let mut vec: Vec<(String, String)> = vec![];
        for edge_ref in graph.edge_references() {
            let src = edge_ref.source();
            let dst = edge_ref.target();
            let from = graph.node_weight(src).unwrap().to_string();
            let to = graph.node_weight(dst).unwrap().to_string();
            if vec.iter().find(|&x| x.0 == to && x.1 == from).is_some() {
                continue;
            }
            vec.push((from, to));
        }

        for x in vec {
            if x.0 == x.1 {
                panic!("Wrong");
            }
        }
    }

    #[test]
    fn graph() {
        let _ = env_logger::builder()
            .filter_level(log::LevelFilter::Info)
            .is_test(true)
            .try_init();

        let mut graph = Graph::<&str, &str>::new();

        let a = graph.add_node("A");
        let b = graph.add_node("B");
        let c = graph.add_node("C");

        graph.add_edge(a, b, "edge_1");
        graph.add_edge(b, c, "edge_2");

        // 打印图的 DOT 表示
        info!("{:?}", Dot::with_config(&graph, &[Config::EdgeNoLabel]));
    }

    #[test]
    fn random_graph() {
        let mut graph = Graph::<String, ()>::new();
        let mut rng = rand::rngs::StdRng::seed_from_u64(7);

        // 随机生成 5 个节点
        let nodes: Vec<NodeIndex> = (0..10)
            .map(|i| graph.add_node(format!("node{}", i)))
            .collect();

        // 以 30% 的概率生成边
        let probability = 0.3;
        for i in 0..nodes.len() {
            for j in (i + 1)..nodes.len() {
                // 只检查一半的组合，避免重复添加边
                if rng.gen::<f64>() < probability {
                    // 生成 [0.0, 1.0) 范围的随机浮点数
                    graph.add_edge(nodes[i], nodes[j], ());
                }
            }
        }

        // 打印图的 DOT 表示
        info!("{:?}", Dot::with_config(&graph, &[Config::EdgeNoLabel]));

        // 打印图的节点和边
        for node in graph.node_indices() {
            info!("Node: {:?}", graph[node]);
        }

        for edge in graph.edge_indices() {
            let (source, target) = graph.edge_endpoints(edge).unwrap();
            info!("Edge: {} -> {}", graph[source], graph[target]);
        }
    }
}
