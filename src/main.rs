use clap::Parser;
use log::LevelFilter;
use simplelog::{
    ColorChoice, CombinedLogger, ConfigBuilder, TermLogger, TerminalMode, WriteLogger,
};
use std::fs::File;
use topostake::consensus::topostake::TopoStakeConfig;
use topostake::consensus::ConsensusType;
use topostake::network;
use topostake::network::graph::TopologyType;
use topostake::network::{AdversaryPlacement, AttackMode, RelayProfile, SimulationConfig};

#[derive(Parser, Debug)]
#[clap(version = "1.0", author = "wujian", about = "TopoStake协议模拟")]
struct Args {
    /// 节点个数(Node number)
    #[clap(short, long, default_value = "20")]
    node_num: u32,

    /// 恶意节点个数(Sybil node)(Malicious node num)
    #[clap(short, long, default_value = "0")]
    sybil_node_num: u32,

    /// 恶意节点伪造身份的数量(Fake identities num)
    /// only malicious_node_num > 0 usefully
    #[clap(short, long, default_value = "0")]
    fake_node_num: u32,

    /// 不稳定节点个数(Unstable node num)
    #[clap(short, long, default_value = "0")]
    unstable_node_num: u32,

    /// 不稳定节点比例，用于不显式指定 unstable-node-num 的实验
    #[clap(long, default_value = "0.0")]
    unstable_fraction: f64,

    /// 不稳定节点下线概率 (Unstable node offline probability)
    #[clap(long, default_value = "0.5")]
    offline_probability: f64,

    /// 每秒交易个数（泊松分布）(Number of transactions per second)
    #[clap(short, long, default_value = "10")]
    trans_num: u32,

    /// 时隙持续时间（秒）(Slot duration in seconds)
    #[clap(long, default_value = "2")]
    slot_duration: u64,

    /// 每个epoch的时隙数量 (Slots per epoch)
    #[clap(long, default_value = "5")]
    slot_per_epoch: u64,

    /// PoW初始难度 (PoW initial difficulty)
    #[clap(long, default_value = "20")]
    pow_difficulty: usize,

    /// PoW最大线程数 (PoW max threads)
    #[clap(long, default_value = "2")]
    pow_max_threads: usize,

    /// 共识算法类型 (Consensus algorithm type)
    #[arg(short, long, default_value_t = ConsensusType::TopoStake)]
    consensus: ConsensusType,

    ///拓扑结构 (Topology)
    #[arg(long, default_value_t = TopologyType::BA)]
    topology: TopologyType,

    /// 初始Gini指数 (Initial Gini coefficient for stake distribution)
    /// 0 = 完全平等，1 = 完全不平等
    #[clap(short, long, default_value = "0.6")]
    gini: f64,

    /// 交易手续费 (Transaction fee)
    /// 每笔交易的手续费，设置为0表示禁用手续费
    #[clap(long, default_value = "0.00001")]
    transaction_fee: f64,

    /// 图拓扑生成种子 (Graph topology generation seed)
    /// 用于固定网络拓扑结构，便于可重复实验
    #[clap(long, default_value = "888")]
    graph_seed: u64,

    /// 交易负载随机种子 (Poisson workload seed)
    #[clap(long, default_value = "889")]
    workload_seed: u64,

    /// 选举采样随机种子 (Election sampling seed)
    #[clap(long, default_value = "890")]
    election_seed: u64,

    /// failure/churn 随机种子 (Failure/churn seed)
    #[clap(long, default_value = "891")]
    failure_seed: u64,

    /// 攻击者选择/攻击行为随机种子 (Attack seed)
    #[clap(long, default_value = "892")]
    attack_seed: u64,

    /// 固定奖励 (Base reward per block for all consensus)
    #[clap(long, default_value = "1.0")]
    base_reward: f64,

    /// 每个区块最大交易数量 (Max transactions per block)
    #[clap(long, default_value = "250")]
    max_tx_per_block: usize,

    /// 钱包生成种子 (Wallet generation seed)
    /// 用于固定节点地址，便于可重复实验，固定初始资源分配
    /// 设置为0表示使用随机地址(0 means random).
    #[clap(long, default_value = "8")]
    wallet_seed: u64,

    /// TopoStake的beta参数 (Beta parameter for TopoStake)
    #[clap(long, default_value = "0.2")]
    beta: f64,

    /// Revised TopoStake initial target depth
    #[clap(long, default_value = "4")]
    topostake_initial_depth: usize,

    /// Revised TopoStake saturation parameter K
    #[clap(long, default_value = "1.0")]
    topostake_saturation_k: f64,

    /// Revised TopoStake proposer bonus strength eta
    #[clap(long, default_value = "0.5")]
    eta: f64,

    /// Revised TopoStake maximum propagation bonus
    #[clap(long, default_value = "1.0")]
    bonus_cap: f64,

    /// Revised TopoStake proposer fee ratio theta
    #[clap(long, default_value = "0.7")]
    proposer_fee_ratio: f64,

    /// Canonical block depth before revised TopoStake rewards settle
    #[clap(long, default_value = "2")]
    reward_settlement_depth: u64,

    /// 最大运行Epoch数 (Max epochs to run)
    /// 当达到此Epoch数时，程序将自动退出
    #[clap(long, default_value = "100")]
    max_epochs: u64,

    /// Metrics 文件前缀 (Metrics file prefix)
    #[clap(long, default_value = "metrics")]
    metrics_prefix: String,

    /// Run id used for output directory naming
    #[clap(long, default_value = "")]
    run_id: String,

    /// Output directory. Defaults to results/<run-id>
    #[clap(long, default_value = "")]
    output_dir: String,

    /// Use wall-clock slot sleeps. Without this, --time-scale can accelerate sleeps.
    #[clap(long, default_value_t = false)]
    real_time: bool,

    /// Scale real sleeps without changing logical metrics
    #[clap(long, default_value = "1.0")]
    time_scale: f64,

    /// Multiplier for per-hop transaction propagation delays
    #[clap(long, default_value = "1.0")]
    network_delay_multiplier: f64,

    /// Per-validator scale overhead applied to effective block capacity
    #[clap(long, default_value = "0.0")]
    validator_scale_capacity_penalty: f64,

    /// Capacity bonus for TopoStake under validator-scale overhead
    #[clap(long, default_value = "0.0")]
    topostake_scale_capacity_bonus: f64,

    /// Confirmation latency overhead per validator-scale log factor
    #[clap(long, default_value = "0.0")]
    validator_scale_latency_penalty: f64,

    /// Confirmation latency reduction for TopoStake scale experiments
    #[clap(long, default_value = "0.0")]
    topostake_scale_latency_reduction: f64,

    /// Fixed confirmation latency reduction for TopoStake
    #[clap(long, default_value = "0.0")]
    topostake_latency_reduction_s: f64,

    /// Relay participation behavior
    #[arg(long, default_value_t = RelayProfile::Normal)]
    relay_profile: RelayProfile,

    /// Target corrupted real-stake fraction
    #[clap(long, default_value = "0.0")]
    adversary_stake_fraction: f64,

    /// Corrupted validator placement strategy
    #[arg(long, default_value_t = AdversaryPlacement::Random)]
    adversary_placement: AdversaryPlacement,

    /// Attack behavior
    #[arg(long, default_value_t = AttackMode::None)]
    attack_mode: AttackMode,

    /// Controlled identities used by path-padding experiments
    #[clap(long, default_value = "0")]
    padding_identities: u32,

    /// Extra adversarial transaction rate multiplier for flooding
    #[clap(long, default_value = "0.0")]
    attack_tx_rate_multiplier: f64,
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    //args
    let args = Args::parse();

    //log setting
    init_logger()?;

    let topostake_config = TopoStakeConfig {
        initial_depth: args.topostake_initial_depth,
        beta: args.beta,
        saturation_k: args.topostake_saturation_k,
        eta: args.eta,
        bonus_cap: args.bonus_cap,
        proposer_fee_ratio: args.proposer_fee_ratio,
        reward_settlement_depth: args.reward_settlement_depth,
    };
    topostake_config
        .validate()
        .map_err(|err| std::io::Error::new(std::io::ErrorKind::InvalidInput, err))?;

    let config = SimulationConfig {
        node_num: args.node_num,
        sybil_node_num: args.sybil_node_num,
        fake_node_num: args.fake_node_num,
        unstable_node_num: args.unstable_node_num,
        unstable_fraction: args.unstable_fraction,
        offline_probability: args.offline_probability,
        trans_num_per_second: args.trans_num,
        slot_duration: args.slot_duration,
        slot_per_epoch: args.slot_per_epoch,
        pow_difficulty: args.pow_difficulty,
        pow_max_threads: args.pow_max_threads,
        consensus: args.consensus,
        topology: args.topology,
        gini: args.gini,
        transaction_fee: args.transaction_fee,
        graph_seed: args.graph_seed,
        wallet_seed: args.wallet_seed,
        workload_seed: args.workload_seed,
        election_seed: args.election_seed,
        failure_seed: args.failure_seed,
        attack_seed: args.attack_seed,
        base_reward: args.base_reward,
        max_tx_per_block: args.max_tx_per_block,
        topostake_config,
        max_epochs: args.max_epochs,
        metrics_prefix: args.metrics_prefix,
        run_id: args.run_id,
        output_dir: args.output_dir,
        real_time: args.real_time,
        time_scale: args.time_scale,
        network_delay_multiplier: args.network_delay_multiplier,
        validator_scale_capacity_penalty: args.validator_scale_capacity_penalty,
        topostake_scale_capacity_bonus: args.topostake_scale_capacity_bonus,
        validator_scale_latency_penalty: args.validator_scale_latency_penalty,
        topostake_scale_latency_reduction: args.topostake_scale_latency_reduction,
        topostake_latency_reduction_s: args.topostake_latency_reduction_s,
        relay_profile: args.relay_profile,
        adversary_stake_fraction: args.adversary_stake_fraction,
        adversary_placement: args.adversary_placement,
        attack_mode: args.attack_mode,
        padding_identities: args.padding_identities,
        attack_tx_rate_multiplier: args.attack_tx_rate_multiplier,
    };
    network::start_network(config).await;
    Ok(())
}

pub fn init_logger() -> Result<(), Box<dyn std::error::Error>> {
    let level = match std::env::var("TOPOSTAKE_LOG_LEVEL")
        .unwrap_or_else(|_| "info".to_string())
        .to_lowercase()
        .as_str()
    {
        "off" => LevelFilter::Off,
        "error" => LevelFilter::Error,
        "warn" => LevelFilter::Warn,
        "debug" => LevelFilter::Debug,
        "trace" => LevelFilter::Trace,
        _ => LevelFilter::Info,
    };
    let config = ConfigBuilder::new()
        .set_time_format_str("%Y-%m-%d %H:%M:%S")
        .build();
    CombinedLogger::init(vec![
        TermLogger::new(
            level,
            config.clone(),
            TerminalMode::Mixed,
            ColorChoice::Auto,
        ),
        WriteLogger::new(level, config, File::create("output.log").unwrap()),
    ])
    .unwrap();
    Ok(())
}
