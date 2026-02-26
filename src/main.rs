use clap::Parser;
use log::LevelFilter;
use simplelog::{
    ColorChoice, CombinedLogger, ConfigBuilder, TermLogger, TerminalMode, WriteLogger,
};
use std::fs::File;
use topostake::consensus::ConsensusType;
use topostake::network;
use topostake::network::graph::TopologyType;

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

    /// 最大运行Epoch数 (Max epochs to run)
    /// 当达到此Epoch数时，程序将自动退出
    #[clap(long, default_value = "100")]
    max_epochs: u64,
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    //args
    let args = Args::parse();

    //log setting
    init_logger()?;

    network::start_network(
        args.node_num,
        args.sybil_node_num,
        args.fake_node_num,
        args.unstable_node_num,
        args.offline_probability,
        args.trans_num,
        args.slot_duration,
        args.slot_per_epoch,
        args.pow_difficulty,
        args.pow_max_threads,
        args.consensus,
        args.topology,
        args.gini,
        args.transaction_fee,
        args.graph_seed,
        args.base_reward,
        args.max_tx_per_block,
        args.wallet_seed,
        args.max_epochs,
    )
    .await;
    Ok(())
}

pub fn init_logger() -> Result<(), Box<dyn std::error::Error>> {
    let config = ConfigBuilder::new()
        .set_time_format_str("%Y-%m-%d %H:%M:%S")
        .build();
    CombinedLogger::init(vec![
        TermLogger::new(
            LevelFilter::Info,
            config.clone(),
            TerminalMode::Mixed,
            ColorChoice::Auto,
        ),
        WriteLogger::new(
            LevelFilter::Info,
            config,
            File::create("output.log").unwrap(),
        ),
    ])
    .unwrap();
    Ok(())
}
