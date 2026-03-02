use crate::blockchain::block::{Block, BlockError, Body};
use crate::blockchain::path::{AggregatedSignedPaths, TransactionPaths};
use crate::blockchain::transaction::Transaction;
use crate::blockchain::{BlockChainError, Blockchain};
use crate::consensus::{ConsensusType, RandaoSeed, Validator};
use crate::network::message::Message;
// use crate::network::world_state::SlotManager;
use crate::wallet::Wallet;
use log::{debug, error, info, warn};
use rand::Rng;
// use serde_json;
use std::collections::HashMap;
use std::fmt::{Display, Formatter};
use std::sync::Arc;
use tokio::sync::mpsc::{Receiver, Sender};
use tokio::sync::RwLock;

///通过Tokio的mpsc通道与其他节点交互
///负责出块、发送交易、发送seed
pub struct Node {
    pub index: u32,
    pub epoch: u64,
    pub slot: u64,
    pub wallet: Wallet,
    pub blockchain: Arc<RwLock<Blockchain>>,
    pub sender: Sender<Message>,
    pub receiver: Receiver<Message>,
    pub neighbors: Vec<Neighbor>,
    pub world_state_sender: Sender<Message>,
    pub transaction_paths_cache: Arc<RwLock<HashMap<String, Arc<TransactionPaths>>>>,
    pub node_type: NodeType,
    pub sybil_nodes: Vec<Node>,
    pub is_online: bool,
    pub offline_until_epoch: Option<u64>,
    pub offline_probability: f64,
    pub sync_in_progress: bool,
    pub transaction_fee: f64,      // 交易手续费
    pub balance: f64,              // 账户余额
    pub max_tx_per_block: usize,   // 每个区块最大交易数量
    pub consensus: ConsensusType,  // 共识算法类型
    pub max_mempool_size: usize,   // 内存池最大容量
    pub hash_power: f64,           // 节点算力
    pub tx_propagation_delay: u64, // 交易传播延迟(ms)
}

#[derive(Clone)]
pub enum NodeType {
    Honest,
    Selfish,
    Sybil,
    Unstable, // 会随机下线的节点
}

impl Display for NodeType {
    fn fmt(&self, f: &mut Formatter<'_>) -> std::fmt::Result {
        match *self {
            NodeType::Honest => write!(f, "Honest"),
            NodeType::Selfish => write!(f, "Selfish"),
            NodeType::Sybil => write!(f, "Sybil"),
            NodeType::Unstable => write!(f, "Unstable"),
        }
    }
}

#[derive(Clone)]
pub struct Neighbor {
    pub index: u32,
    pub address: String,
    pub sender: Sender<Message>,
}

impl Node {
    pub fn new(
        index: u32,
        epoch: u64,
        slot: u64,
        blockchain: Blockchain,
        world_state_sender: Sender<Message>,
        max_tx_per_block: usize,
        consensus: ConsensusType,
        wallet_seed: u64,
    ) -> Self {
        let wallet = if wallet_seed == 0 {
            Wallet::new()
        } else {
            Wallet::new_deterministic(wallet_seed, index)
        };
        let (sender, receiver) = tokio::sync::mpsc::channel(1024 * 16);
        Node {
            index,
            epoch,
            slot,
            wallet,
            blockchain: Arc::new(RwLock::new(blockchain)),
            sender,
            receiver,
            transaction_paths_cache: Arc::new(RwLock::new(HashMap::new())),
            neighbors: Vec::new(),
            world_state_sender,
            node_type: NodeType::Honest,
            sybil_nodes: Vec::new(),
            is_online: true,
            offline_until_epoch: None,
            offline_probability: 0.1,
            sync_in_progress: false,
            transaction_fee: 0.0,
            balance: 0.0,
            max_tx_per_block,
            consensus,
            max_mempool_size: max_tx_per_block,
            hash_power: 1.0,
            tx_propagation_delay: 50, // 默认50ms
        }
    }

    pub fn new_with_wallet(
        index: u32,
        epoch: u64,
        slot: u64,
        blockchain: Blockchain,
        wallet: Wallet,
        world_state_sender: Sender<Message>,
        max_tx_per_block: usize,
        consensus: ConsensusType,
    ) -> Self {
        let (sender, receiver) = tokio::sync::mpsc::channel(8);
        Node {
            index,
            epoch,
            slot,
            wallet,
            blockchain: Arc::new(RwLock::new(blockchain)),
            sender,
            receiver,
            transaction_paths_cache: Arc::new(RwLock::new(HashMap::new())),
            neighbors: Vec::new(),
            world_state_sender,
            node_type: NodeType::Honest,
            sybil_nodes: Vec::new(),
            is_online: true,
            offline_until_epoch: None,
            offline_probability: 0.1,
            sync_in_progress: false,
            transaction_fee: 0.0,
            balance: 0.0,
            max_tx_per_block,
            consensus,
            max_mempool_size: max_tx_per_block,
            hash_power: 1.0,
            tx_propagation_delay: 50, // 默认50ms
        }
    }

    pub fn new_with_sybil_nodes(
        index: u32,
        epoch: u64,
        slot: u64,
        blockchain: Blockchain,
        world_state_sender: Sender<Message>,
        fake_node_num: i32,
        max_tx_per_block: usize,
        consensus: ConsensusType,
        wallet_seed: u64,
    ) -> Self {
        let mut sybil_nodes: Vec<Node> = Vec::new();
        for i in 0..fake_node_num {
            let mut n = Node::new(
                index * 1000 + i as u32,
                epoch,
                slot,
                blockchain.clone(),
                world_state_sender.clone(),
                max_tx_per_block,
                consensus,
                wallet_seed,
            );
            n.set_node_type(NodeType::Sybil);
            sybil_nodes.push(n);
        }
        let wallet = if wallet_seed == 0 {
            Wallet::new()
        } else {
            Wallet::new_deterministic(wallet_seed, index)
        };
        let (sender, receiver) = tokio::sync::mpsc::channel(4096);
        Node {
            index,
            epoch,
            slot,
            wallet,
            blockchain: Arc::new(RwLock::new(blockchain)),
            sender,
            receiver,
            transaction_paths_cache: Arc::new(RwLock::new(HashMap::new())),
            neighbors: Vec::new(),
            world_state_sender,
            node_type: NodeType::Sybil,
            sybil_nodes,
            is_online: true,
            offline_until_epoch: None,
            offline_probability: 0.1,
            sync_in_progress: false,
            transaction_fee: 0.0,
            balance: 0.0,
            max_tx_per_block,
            consensus,
            max_mempool_size: max_tx_per_block,
            hash_power: 1.0,
            tx_propagation_delay: 50, // 默认50ms
        }
    }

    pub fn set_node_type(&mut self, node_type: NodeType) {
        self.node_type = node_type;
    }

    pub fn set_offline_probability(&mut self, probability: f64) {
        self.offline_probability = probability.clamp(0.0, 1.0);
    }

    pub fn set_hash_power(&mut self, hash_power: f64) {
        self.hash_power = hash_power;
    }

    pub fn set_tx_propagation_delay(&mut self, delay: u64) {
        self.tx_propagation_delay = delay;
    }

    pub async fn generate_block(&self, epoch: u64, slot: u64) -> Result<Block, BlockError> {
        let transaction_paths_to_pack = {
            let transaction_paths_cache = self.transaction_paths_cache.read().await;
            let blockchain = self.blockchain.read().await;

            // 1. 过滤掉已经在区块链中的交易
            let mut valid_paths: Vec<&Arc<TransactionPaths>> = transaction_paths_cache
                .values()
                .filter(|x| !blockchain.exist_transaction(&x.transaction.hash))
                .collect();

            // 2. 按手续费从高到低排序，如果手续费相同，则按交易创建时间从早到晚排序
            valid_paths.sort_by(|a, b| {
                b.transaction
                    .fee
                    .partial_cmp(&a.transaction.fee)
                    .unwrap_or(std::cmp::Ordering::Equal)
                    .then_with(|| a.transaction.timestamp.cmp(&b.transaction.timestamp))
            });

            // 3. 截取前 max_tx_per_block 个
            let pack_count = std::cmp::min(valid_paths.len(), self.max_tx_per_block);
            let to_pack: Vec<Arc<TransactionPaths>> = valid_paths[..pack_count]
                .iter()
                .map(|&x| x.clone())
                .collect();

            drop(blockchain);
            drop(transaction_paths_cache);

            // 4. 更新缓存：移除已打包的交易
            if !to_pack.is_empty() {
                let mut cache_write = self.transaction_paths_cache.write().await;
                for tx in &to_pack {
                    cache_write.remove(&tx.transaction.hash);
                }
            }

            to_pack
        };

        let mut transactions: Vec<Transaction> =
            Vec::with_capacity(transaction_paths_to_pack.len());
        let mut paths: Vec<AggregatedSignedPaths> =
            Vec::with_capacity(transaction_paths_to_pack.len());

        for x in transaction_paths_to_pack {
            transactions.push(x.transaction.clone());
            paths.push(x.to_aggregated_signed_paths());
        }

        // 获取需要的信息后再释放读锁
        let blockchain = self.blockchain.read().await;
        let last_index = blockchain.get_last_index();
        let last_hash = blockchain.get_last_hash();
        drop(blockchain);

        let body = Body::new(transactions, paths);
        let new_block = {
            Block::new(
                last_index + 1,
                epoch,
                slot,
                last_hash,
                body,
                self.wallet.clone(),
            )?
        };
        {
            if let Err(e) = self
                .blockchain
                .clone()
                .write()
                .await
                .add_block(new_block.clone())
            {
                error!("Node[{}] error :{}", self.index, e);
                return Err(BlockError::InvalidBlock);
            };
        }

        Ok(new_block)
    }

    pub fn get_address(&self) -> String {
        self.wallet.address.clone()
    }

    pub fn short_address(&self) -> String {
        self.wallet.address.clone()[0..5].to_string()
    }

    pub fn short_address_with_index(&self) -> String {
        self.index.to_string() + "-" + self.short_address().as_str()
    }

    pub fn simple_print(&self) {
        info!(
            "node[{}],node_type[{}],node_address:{}",
            self.index,
            self.node_type,
            self.get_address()
        );
    }

    pub fn set_transaction_fee(&mut self, fee: f64) {
        self.transaction_fee = fee;
    }

    pub fn set_balance(&mut self, balance: f64) {
        self.balance = balance;
    }

    pub fn get_balance(&self) -> f64 {
        self.balance
    }

    /// 尝试扣除余额，如果余额不足则返回 false
    pub fn deduct_balance(&mut self, amount: f64) -> bool {
        if self.balance >= amount {
            self.balance -= amount;
            true
        } else {
            false
        }
    }

    pub async fn run(&mut self) {
        while let Some(msg) = self.receiver.recv().await {
            // 离线逻辑：如果节点离线，跳过大多数消息处理
            // 但 UpdateSlot 消息用于恢复在线逻辑，需要处理
            if !self.is_online && !matches!(msg, Message::UpdateSlot(_)) {
                debug!("Node[{}] is offline, skipping message", self.index);
                match msg {
                    Message::GenerateBlock => {
                        warn!(
                            "Node[{}] missed block generation due to being offline at slot {}",
                            self.index, self.slot
                        );
                        // 报告出块失败事件到 world_state
                        let world_state_sender = self.world_state_sender.clone();
                        let node_index = self.index;
                        let node_slot = self.slot;
                        tokio::spawn(async move {
                            world_state_sender
                                .send(Message::new_block_production_failed_msg(
                                    node_index,
                                    node_slot,
                                    "node_offline".to_string(),
                                ))
                                .await
                                .unwrap();
                        });
                    }
                    _ => {}
                }
                continue;
            }

            match msg {
                Message::SendBlock { block, from } => {
                    debug!(
                        "Node[{}] received msg[SendBlock]: block hash[{}]",
                        self.index, block.header.hash
                    );
                    {
                        //添加到自己的区块链
                        let mut blockchain = self.blockchain.write().await;
                        if let Err(e) = blockchain.add_block((*block).clone()) {
                            match e {
                                BlockChainError::DuplicateBlocksReceived => {
                                    debug!("Node[{}] add block error: {}", self.index, e);
                                }
                                BlockChainError::IndexTooSmall => {
                                    debug!("Node[{}] add block error: {}", self.index, e);
                                }
                                BlockChainError::TransactionExists => {
                                    debug!("Node[{}] add block error: {}", self.index, e);
                                }
                                BlockChainError::ParentHashMismatch => {
                                    warn!("Node[{}] error: {}, trying Block Sync", self.index, e);
                                    // 先释放写锁，再向邻居请求块同步（避免死锁）
                                    let last_block_index = blockchain.get_last_index();
                                    drop(blockchain);

                                    if !self.neighbors.is_empty() {
                                        self.sync_in_progress = true;
                                        for neighbor in &self.neighbors {
                                            let self_address = self.get_address();
                                            let sender = neighbor.sender.clone();
                                            tokio::spawn(async move {
                                                sender
                                                    .send(Message::new_request_block_sync_msg(
                                                        last_block_index,
                                                        self_address,
                                                    ))
                                                    .await
                                                    .unwrap();
                                            });
                                        }
                                    }
                                }
                                _ => {
                                    error!("Node[{}] add block error: {}", self.index, e);
                                }
                            }
                            continue;
                        }
                        debug!("Node[{}] add block successfully", self.index);
                    }
                    {
                        //清除交易缓存
                        let mut transaction_paths_cache =
                            self.transaction_paths_cache.write().await;
                        for t in &block.body.transactions {
                            transaction_paths_cache.remove(&t.hash);
                        }
                    }
                    //广播到其他邻居
                    for neighbor_sender in &self.neighbors {
                        if from == neighbor_sender.address {
                            continue;
                        }
                        let block = block.clone();
                        debug!(
                            "Node[{}] send block to Node[{}]",
                            self.index, neighbor_sender.index
                        );
                        let self_address = self.get_address();
                        let sender = neighbor_sender.sender.clone();
                        tokio::spawn(async move {
                            sender
                                .send(Message::new_block_msg(block, self_address))
                                .await
                                .unwrap();
                        });
                    }
                }
                Message::SendTransactionPaths {
                    transaction_paths,
                    from,
                } => {
                    // if !transaction_paths.verify_last(self.wallet.address.clone()) {
                    //     error!("Node[{}] invalid transaction paths", self.index);
                    //     continue;
                    // }

                    //判断交易是否已经收到了,判断交易的paths是否最短
                    {
                        let transactions_cache = self.transaction_paths_cache.read().await;
                        let tx_hash = &transaction_paths.transaction.hash;

                        if let Some(cached_tx) = transactions_cache.get(tx_hash) {
                            if self.consensus == ConsensusType::TopoStake {
                                // TopoStake: 只有当缓存的路径长度更短或相等时才跳过
                                if cached_tx.paths.len() <= transaction_paths.paths.len() {
                                    continue;
                                }
                            } else {
                                // 其他共识: 只要收到过就跳过
                                continue;
                            }
                        }
                    }

                    {
                        let bc = self.blockchain.read().await;
                        if bc.exist_transaction(&transaction_paths.transaction.hash) {
                            debug!(
                                "Node[{}] received transaction[{}] already in blockchain",
                                self.index, transaction_paths.transaction.hash
                            );
                            continue;
                        }
                    }
                    debug!(
                        "Node[{}] received msg[SendTransactionPaths]: transaction hash[{}],path[{}]",
                        self.short_address_with_index(),
                        transaction_paths.transaction.hash,
                        transaction_paths.to_paths_string(),
                    );
                    //收到交易，存储
                    let mut is_cached = false;
                    {
                        let mut transactions_cache = self.transaction_paths_cache.write().await;
                        let tx_hash = transaction_paths.transaction.hash.clone();

                        // 取消内存池容量限制，确保交易完整传播
                        transactions_cache.insert(tx_hash, transaction_paths.clone());
                        is_cached = true;
                    }

                    if !is_cached {
                        continue;
                    }

                    match self.node_type {
                        NodeType::Selfish => {
                            // drop propagation
                            let mut rng = rand::thread_rng();
                            let random_bool: bool = rng.gen_bool(0.5);
                            if random_bool {
                                continue;
                            }
                        }
                        NodeType::Sybil => {
                            //Sybil,伪造路径,再广播
                            let mut wallet = self.wallet.clone();

                            // Create a modifiable copy
                            let mut fake_paths = (*transaction_paths).clone();

                            self.sybil_nodes.iter().for_each(|s| {
                                fake_paths.add_path(s.get_address(), wallet.clone());
                                wallet = s.wallet.clone();
                            });
                            for neighbor_sender in &self.neighbors {
                                if from == neighbor_sender.address {
                                    continue;
                                }
                                let mut new_trans_paths = fake_paths.clone();
                                new_trans_paths
                                    .add_path(neighbor_sender.address.clone(), wallet.clone());
                                debug!(
                                    "Sybil Node[{}] send transaction[{}] paths[{}] to Node[{}]",
                                    self.short_address_with_index(),
                                    new_trans_paths.transaction.hash,
                                    new_trans_paths.to_paths_string(),
                                    neighbor_sender.short_address_with_index()
                                );
                                let self_address = self.get_address();
                                let sender = neighbor_sender.sender.clone();
                                let delay = self.tx_propagation_delay;
                                tokio::spawn(async move {
                                    if delay > 0 {
                                        tokio::time::sleep(std::time::Duration::from_millis(delay))
                                            .await;
                                    }
                                    sender
                                        .send(Message::new_transaction_paths_msg(
                                            Arc::new(new_trans_paths),
                                            self_address,
                                        ))
                                        .await
                                        .unwrap();
                                });
                            }
                            continue;
                        }
                        _ => {}
                    }

                    //并广播到邻居
                    for neighbor_sender in &self.neighbors {
                        if from == neighbor_sender.address {
                            continue;
                        }
                        let mut new_trans_paths = (*transaction_paths).clone();
                        new_trans_paths
                            .add_path(neighbor_sender.address.clone(), self.wallet.clone());
                        debug!(
                            "Node[{}] send transaction[{}] paths[{}] to Node[{}]",
                            self.short_address_with_index(),
                            new_trans_paths.transaction.hash,
                            new_trans_paths.to_paths_string(),
                            neighbor_sender.short_address_with_index()
                        );
                        let self_address = self.get_address();
                        let sender = neighbor_sender.sender.clone();
                        let delay = self.tx_propagation_delay;
                        tokio::spawn(async move {
                            if delay > 0 {
                                tokio::time::sleep(std::time::Duration::from_millis(delay)).await;
                            }
                            sender
                                .send(Message::new_transaction_paths_msg(
                                    Arc::new(new_trans_paths),
                                    self_address,
                                ))
                                .await
                                .unwrap();
                        });
                    }
                }

                Message::GenerateBlock => {
                    // 同步过程中不能出块
                    if self.sync_in_progress {
                        warn!(
                            "Node[{}] skipping block generation due to sync in progress at slot {}",
                            self.index, self.slot
                        );

                        continue;
                    }

                    let last_block_time = {
                        self.blockchain
                            .read()
                            .await
                            .get_last_block()
                            .header
                            .timestamp
                    };
                    //出块
                    let block = match self.generate_block(self.epoch, self.slot).await {
                        Ok(b) => b,
                        Err(e) => {
                            error!(
                                "Node[{}] generate block failed: {} at slot {}",
                                self.index, e, self.slot
                            );

                            continue;
                        }
                    };
                    info!(
                        "Node[{}] is the miner: block hash[{}]",
                        self.index, block.header.hash
                    );
                    block.simple_print();
                    let during = block.header.timestamp - last_block_time;
                    info!(
                        "Current {:.2}TX/s",
                        block.body.transactions.len() as f64 / during as f64
                    );

                    //广播区块
                    let block_arc = Arc::new(block.clone());
                    for neighbor_sender in &self.neighbors {
                        let block = block_arc.clone();
                        let self_address = self.get_address();
                        let sender = neighbor_sender.sender.clone();
                        tokio::spawn(async move {
                            sender
                                .send(Message::new_block_msg(block, self_address))
                                .await
                                .unwrap();
                        });
                    }
                    //告诉下worldState
                    let world_state_sender = self.world_state_sender.clone();
                    let self_address = self.get_address();
                    let block_to_world = block_arc.clone();
                    tokio::spawn(async move {
                        world_state_sender
                            .send(Message::new_block_msg(block_to_world, self_address))
                            .await
                            .unwrap();
                    });
                }
                Message::GenerateTransactionPaths { to } => {
                    // 检查余额是否充足
                    if !self.deduct_balance(self.transaction_fee) {
                        warn!(
                            "Node[{}] insufficient balance: {} < {}",
                            self.index, self.balance, self.transaction_fee
                        );
                        continue;
                    }

                    // 扣除余额后，同步到 Validator 的 stake
                    self.world_state_sender
                        .send(Message::new_update_validator_stake_msg(
                            self.wallet.address.clone(),
                            self.balance,
                        ))
                        .await
                        .unwrap();

                    let transaction =
                        Transaction::with_fee(to, 0, self.transaction_fee, self.wallet.clone());
                    let mut transaction_paths = TransactionPaths::new(transaction);
                    debug!(
                        "Node[{}] received msg[GenerateTransactionPaths]: transaction hash[{}],path[{}]",
                        self.short_address_with_index(),
                        transaction_paths.transaction.hash,
                        transaction_paths.to_paths_string()
                    );
                    //缓存交易
                    let mut is_cached = false;
                    {
                        let mut transactions_cache = self.transaction_paths_cache.write().await;
                        let tx_hash = transaction_paths.transaction.hash.clone();

                        // 检查内存池是否已满
                        if transactions_cache.len() >= self.max_mempool_size {
                            // 如果内存池满了，且这是一个新交易，则丢弃
                            if !transactions_cache.contains_key(&tx_hash) {
                                debug!(
                                    "Node[{}] mempool full, dropping generated transaction[{}]",
                                    self.index, tx_hash
                                );
                            } else {
                                transactions_cache
                                    .insert(tx_hash, Arc::new(transaction_paths.clone()));
                                is_cached = true;
                            }
                        } else {
                            transactions_cache.insert(tx_hash, Arc::new(transaction_paths.clone()));
                            is_cached = true;
                        }
                    }

                    if !is_cached {
                        continue;
                    }
                    match self.node_type {
                        NodeType::Sybil => {
                            //Sybil,伪造路径,再广播
                            let mut wallet = self.wallet.clone();
                            self.sybil_nodes.iter().for_each(|s| {
                                transaction_paths.add_path(s.get_address(), wallet.clone());
                                wallet = s.wallet.clone();
                            });
                            for neighbor_sender in &self.neighbors {
                                let mut new_trans_paths = transaction_paths.clone();
                                new_trans_paths
                                    .add_path(neighbor_sender.address.clone(), wallet.clone());
                                debug!(
                                    "Sybil Node[{}] send transaction[{}] paths[{}] to Node[{}]",
                                    self.short_address_with_index(),
                                    new_trans_paths.transaction.hash,
                                    new_trans_paths.to_paths_string(),
                                    neighbor_sender.short_address_with_index()
                                );
                                let self_address = self.get_address();
                                let sender = neighbor_sender.sender.clone();
                                let delay = self.tx_propagation_delay;
                                tokio::spawn(async move {
                                    if delay > 0 {
                                        tokio::time::sleep(std::time::Duration::from_millis(delay))
                                            .await;
                                    }
                                    sender
                                        .send(Message::new_transaction_paths_msg(
                                            Arc::new(new_trans_paths),
                                            self_address,
                                        ))
                                        .await
                                        .unwrap();
                                });
                            }
                            continue;
                        }
                        _ => {}
                    }
                    //广播交易
                    for neighbor_sender in &self.neighbors {
                        let mut new_trans_paths = transaction_paths.clone();
                        new_trans_paths
                            .add_path(neighbor_sender.address.clone(), self.wallet.clone());
                        debug!(
                            "Node[{}] send transaction[{}] paths[{}] to Node[{}]",
                            self.short_address_with_index(),
                            new_trans_paths.transaction.hash,
                            new_trans_paths.to_paths_string(),
                            neighbor_sender.short_address_with_index()
                        );
                        let self_address = self.get_address();
                        let sender = neighbor_sender.sender.clone();
                        let delay = self.tx_propagation_delay;
                        tokio::spawn(async move {
                            if delay > 0 {
                                tokio::time::sleep(std::time::Duration::from_millis(delay)).await;
                            }
                            sender
                                .send(Message::new_transaction_paths_msg(
                                    Arc::new(new_trans_paths),
                                    self_address,
                                ))
                                .await
                                .unwrap();
                        });
                    }
                }
                Message::SendRandaoSeed => {
                    let seed = RandaoSeed::generate_seed();
                    let signature = self.wallet.sign(Vec::from(seed));
                    let randao_seed = RandaoSeed {
                        address: self.wallet.address.clone(),
                        seed,
                        signature,
                    };
                    debug!(
                        "Node[{}] received msg[SendRandaoSeed]: seed[{:?}]",
                        self.index, seed
                    );
                    self.world_state_sender
                        .send(Message::new_receive_random_seed_msg(randao_seed))
                        .await
                        .unwrap();
                }
                Message::BecomeValidator(stake_map) => {
                    debug!("Node[{}] received msg[BecomeValidator]", self.index);

                    // 从 stake_map 中获取本节点的 stake，并同步到 balance
                    let my_stake = stake_map
                        .get(&self.wallet.address)
                        .copied()
                        .unwrap_or(self.balance); // 如果没有在 stake_map 中找到，保持当前 balance

                    self.set_balance(my_stake);

                    info!(
                        "Node[{}] with address[{}] becomes validator with stake {} and pow power {}",
                        self.index, self.wallet.address, my_stake, self.hash_power
                    );
                    match self.node_type {
                        NodeType::Honest => {
                            self.world_state_sender
                                .send(Message::new_receive_become_validator_msg(Validator::new(
                                    self.wallet.address.clone(),
                                    my_stake,
                                    self.hash_power,
                                )))
                                .await
                                .unwrap();
                        }
                        NodeType::Selfish => {
                            self.world_state_sender
                                .send(Message::new_receive_become_validator_msg(Validator::new(
                                    self.wallet.address.clone(),
                                    my_stake,
                                    self.hash_power,
                                )))
                                .await
                                .unwrap();
                        }
                        NodeType::Unstable => {
                            self.world_state_sender
                                .send(Message::new_receive_become_validator_msg(Validator::new(
                                    self.wallet.address.clone(),
                                    my_stake,
                                    self.hash_power,
                                )))
                                .await
                                .unwrap();
                        }
                        NodeType::Sybil => {
                            // For malicious nodes with sybil, divide stake among all sybil identities
                            let sybil_num = self.sybil_nodes.len();
                            let stake = my_stake / (sybil_num + 1) as f64;

                            self.world_state_sender
                                .send(Message::new_receive_become_validator_msg(Validator::new(
                                    self.wallet.address.clone(),
                                    stake,
                                    self.hash_power,
                                )))
                                .await
                                .unwrap();
                            for sybil in self.sybil_nodes.iter() {
                                // 处理 sybil
                                self.world_state_sender
                                    .send(Message::new_receive_become_validator_msg(
                                        Validator::new(
                                            sybil.wallet.address.clone(),
                                            stake,
                                            sybil.hash_power,
                                        ),
                                    ))
                                    .await
                                    .unwrap();
                                info!("Node[{}] become validator->fake node", sybil.index);
                            }
                        }
                    }
                }
                Message::UpdateNodeBalance(new_balance) => {
                    // WorldState 通知 Node 更新其 balance（例如获得奖励）
                    self.set_balance(new_balance);
                    debug!("Node[{}] updated balance to {}", self.index, new_balance);
                }
                Message::UpdateSlot(slot) => {
                    debug!("Node[{}] received msg[UpdateSlot]", self.index);

                    let old_epoch = self.epoch;
                    self.slot = slot.current_slot;
                    self.epoch = slot.current_epoch;

                    // 恢复在线时向邻居请求块同步（仅对不稳定节点）
                    if matches!(self.node_type, NodeType::Unstable) {
                        // 检查是否刚从离线恢复
                        if !self.is_online
                            && self.offline_until_epoch.is_some()
                            && self.epoch >= self.offline_until_epoch.unwrap()
                        {
                            // 即将恢复在线，准备同步
                            let last_block_index =
                                { self.blockchain.read().await.blocks.len() as u64 - 1 };

                            // 向所有邻居发送块同步请求，确保至少有一个在线的邻居能响应
                            if !self.neighbors.is_empty() {
                                for neighbor in &self.neighbors {
                                    let self_address = self.get_address();
                                    let sender = neighbor.sender.clone();
                                    let neighbor_address = neighbor.address.clone();
                                    tokio::spawn(async move {
                                        debug!(
                                            "Node[{}] requests block sync from Node[{}], last block index: {}",
                                            self_address, neighbor_address, last_block_index
                                        );
                                        sender
                                            .send(Message::new_request_block_sync_msg(
                                                last_block_index,
                                                self_address,
                                            ))
                                            .await
                                            .unwrap();
                                    });
                                }
                            }

                            self.is_online = true;
                            self.offline_until_epoch = None;
                            warn!(
                                "Node[{}] is back online at epoch {}",
                                self.index, self.epoch
                            );
                        }

                        // 仅在 epoch 变化且节点仍在线时，才考虑随机下线
                        if self.is_online
                            && self.epoch != old_epoch
                            && (self.offline_until_epoch.is_none())
                        {
                            use rand::Rng;
                            let mut rng = rand::thread_rng();
                            // 根据配置的概率下线一个epoch
                            if rng.gen_bool(self.offline_probability) {
                                self.is_online = false;
                                self.offline_until_epoch = Some(self.epoch + 1);
                                warn!(
                                    "Node[{}] goes offline at epoch {} until epoch {}",
                                    self.index,
                                    self.epoch,
                                    self.epoch + 1
                                );
                            }
                        }
                    }
                }
                Message::PrintBlockchain => {
                    debug!("Node[{}] received msg[PrintBlockchain]", self.index);
                    self.blockchain.read().await.write_to_file_all_json().await;
                }
                Message::RequestBlockSync {
                    last_block_index: requested_index,
                    from,
                } => {
                    if self.sync_in_progress {
                        debug!(
                            "Node[{}] is syncing, ignoring new block sync request",
                            self.index
                        );
                        continue;
                    }
                    if from == "world_state" {
                        info!(
                            "Node[{}] received RequestBlockSync from world_state",
                            self.index
                        );
                        let blockchain_read = self.blockchain.read().await;
                        let sync_blocks = blockchain_read.blocks.clone();
                        let self_address = self.get_address();
                        let world_state_sender = self.world_state_sender.clone();
                        tokio::spawn(async move {
                            world_state_sender
                                .send(Message::new_response_block_sync_msg(
                                    sync_blocks,
                                    self_address,
                                ))
                                .await
                                .unwrap();
                        });
                        continue;
                    }

                    let blockchain_read = self.blockchain.read().await;
                    
                    let sync_blocks = if let Some(first_block) = blockchain_read.blocks.first() {
                        let oldest_index = first_block.header.index;
                        if requested_index >= oldest_index {
                            // 请求的区块在内存中
                            let start_index = (requested_index - oldest_index) as usize;
                            if start_index < blockchain_read.blocks.len() {
                                blockchain_read.blocks[start_index..].to_vec()
                            } else {
                                vec![]
                            }
                        } else {
                            // 请求的老区块已经被移除了，返回所有内存中剩下的区块当作快照拉取
                            blockchain_read.blocks.clone()
                        }
                    } else {
                        vec![]
                    };

                    if sync_blocks.is_empty() {
                        continue;
                    }

                    debug!(
                        "Node[{}] processing block sync request: requested_index={}, memory_oldest={}, sending {} blocks to {}",
                        self.index, 
                        requested_index, 
                        blockchain_read.blocks.first().map_or(0, |b| b.header.index), 
                        sync_blocks.len(), 
                        from
                    );

                    if !from.is_empty() {
                        // 找到发送者并发送响应
                        for neighbor in &self.neighbors {
                            if neighbor.address == from {
                                let sync_blocks = sync_blocks.clone();
                                let self_address = self.get_address();
                                let sender = neighbor.sender.clone();
                                tokio::spawn(async move {
                                    sender
                                        .send(Message::new_response_block_sync_msg(
                                            sync_blocks,
                                            self_address,
                                        ))
                                        .await
                                        .unwrap();
                                });
                                break;
                            }
                        }
                    }
                }
                Message::ResponseBlockSync {
                    blocks: sync_blocks,
                    from: _,
                } => {
                    // 处理块同步响应
                    if sync_blocks.is_empty() {
                        error!("Node[{}] received empty block sync response", self.index);
                        continue;
                    }

                    let current_index = { self.blockchain.read().await.get_last_index() };

                    let response_index = sync_blocks.last().unwrap().header.index;
                    let response_start_index = sync_blocks.first().unwrap().header.index;

                    // 验证：当前索引必须小于响应中的最大索引
                    if current_index >= response_index {
                        debug!(
                            "Node[{}] skipping sync: current_index({}) >= response_index({})",
                            self.index, current_index, response_index
                        );
                        continue;
                    }

                    // 按顺序添加块，同时遍历本地区块链和响应块
                    {
                        let mut blockchain = self.blockchain.write().await;

                        // 同步的数据比我们当前拥有的新很多，且中间有断层
                        if current_index + 1 < response_start_index {
                            warn!(
                                "Node[{}] received snapshot sync from index {} to {}, replacing local chain",
                                self.index, response_start_index, response_index
                            );
                            
                            // 清空本地区块链
                            blockchain.blocks.clear();
                            blockchain.transaction_index.clear();
                            
                            // 将收到的这批块作为新的本地链快照
                            for sync_block in &sync_blocks {
                                blockchain.blocks.push(sync_block.clone());
                                for tx in &sync_block.body.transactions {
                                    blockchain.transaction_index.insert(tx.hash.clone());
                                }
                            }
                            
                            // 清理已经被打包的交易的缓存
                            let mut transaction_paths_cache = self.transaction_paths_cache.write().await;
                            for tx_hash in &blockchain.transaction_index {
                                transaction_paths_cache.remove(tx_hash);
                            }
                            
                            self.sync_in_progress = false;
                            info!(
                                "Node[{}] completed snapshot sync: applied {} blocks",
                                self.index, sync_blocks.len()
                            );
                            continue;
                        }

                        // 寻找分叉点或者追加新块
                        let mut start_idx = 0;
                        let mut found_fork = false;
                        
                        for (i, sync_block) in sync_blocks.iter().enumerate() {
                            let local_block_opt = blockchain.blocks.iter().find(|b| b.header.index == sync_block.header.index);
                            
                            if let Some(local_block) = local_block_opt {
                                if local_block.header.hash != sync_block.header.hash {
                                    warn!("Node[{}]: chain diverged at #{}, resolving", self.index, sync_block.header.index);
                                    start_idx = i;
                                    found_fork = true;
                                    
                                    let local_start = blockchain.blocks.first().map_or(0, |b| b.header.index);
                                    let truncate_idx = (sync_block.header.index - local_start) as usize;
                                    
                                    let mut hashes_to_remove = Vec::new();
                                    for b in &blockchain.blocks[truncate_idx..] {
                                        for tx in &b.body.transactions {
                                            hashes_to_remove.push(tx.hash.clone());
                                        }
                                    }
                                    for hash in hashes_to_remove {
                                        blockchain.transaction_index.remove(&hash);
                                    }
                                    
                                    blockchain.blocks.truncate(truncate_idx);
                                    break;
                                }
                            } else if sync_block.header.index > current_index {
                                start_idx = i;
                                found_fork = true;
                                break;
                            }
                        }
                        
                        if found_fork {
                            let mut success = true;
                            for sync_idx in start_idx..sync_blocks.len() {
                                let sync_block = &sync_blocks[sync_idx];
                                match blockchain.add_block(sync_block.clone()) {
                                    Ok(_) => {
                                        debug!("Node[{}] synced block #{}", self.index, sync_block.header.index);
                                        let tx_hashes: Vec<String> = sync_block
                                            .body
                                            .transactions
                                            .iter()
                                            .map(|t| t.hash.clone())
                                            .collect();
                                        let mut transaction_paths_cache =
                                            self.transaction_paths_cache.write().await;
                                        for tx_hash in tx_hashes {
                                            transaction_paths_cache.remove(&tx_hash);
                                        }
                                    },
                                    Err(e) => {
                                        error!("Node[{}] error adding synced block #{}: {:?}", self.index, sync_block.header.index, e);
                                        success = false;
                                        break;
                                    }
                                }
                            }
                            info!(
                                "Node[{}] completed block sync to index {}, success: {}",
                                self.index, blockchain.get_last_index(), success
                            );
                        } else {
                            debug!("Node[{}] sync skipped, no new blocks found or all match", self.index);
                        }
                        self.sync_in_progress = false;
                    }
                }
                _ => {}
            }
        }
    }
}

impl Neighbor {
    pub fn new(index: u32, address: String, sender: Sender<Message>) -> Self {
        Neighbor {
            index,
            address,
            sender,
        }
    }

    pub fn short_address(&self) -> String {
        self.address.clone()[0..5].to_string()
    }

    pub fn short_address_with_index(&self) -> String {
        self.index.to_string() + "-" + self.short_address().as_str()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::blockchain::block::Body;
    use crate::blockchain::path::TransactionPaths;
    use crate::blockchain::transaction::Transaction;
    use crate::wallet::Wallet;
    use std::time::Duration;

    #[tokio::test]
    async fn test_send_block() {
        let _ = env_logger::builder()
            .filter_level(log::LevelFilter::Info)
            .is_test(true)
            .try_init();

        let (world_sender, _) = tokio::sync::mpsc::channel(8);
        let blockchain = Blockchain::new(Block::gen_genesis_block());
        let wallet = Wallet::new();
        let wallet2 = Wallet::new();
        let wallet3 = Wallet::new();
        let miner = Wallet::new();
        let transaction = Transaction::new("123".to_string(), 32, wallet.clone());
        let mut transaction_paths = TransactionPaths::new(transaction.clone());
        transaction_paths.add_path(wallet2.address.clone(), wallet);
        transaction_paths.add_path(wallet3.address.clone(), wallet2);
        transaction_paths.add_path(miner.address.clone(), wallet3);

        let body = Body::new(
            vec![transaction],
            vec![transaction_paths.to_aggregated_signed_paths()],
        );
        let block = Block::new(
            blockchain.get_last_index() + 1,
            0,
            1,
            blockchain.get_last_hash(),
            body,
            miner,
        )
        .unwrap();

        let mut node = Node::new(
            0,
            0,
            0,
            blockchain,
            world_sender,
            1000,
            ConsensusType::TopoStake,
            0,
        );
        let node_sender = node.sender.clone();
        let handle1 = tokio::spawn(async move {
            node.run().await;
        });

        let msg = Message::new_block_msg(Arc::new(block), "".to_string());
        let handle2 = tokio::spawn(async move {
            node_sender.send(msg).await.unwrap();
        });

        tokio::time::sleep(Duration::from_secs(1)).await;

        handle1.abort();
        handle2.abort();
    }

    #[tokio::test]
    async fn test_send_transaction_and_block() {
        let _ = env_logger::builder()
            .filter_level(log::LevelFilter::Info)
            .is_test(true)
            .try_init();

        let (world_sender, _) = tokio::sync::mpsc::channel(8);
        let blockchain = Blockchain::new(Block::gen_genesis_block());
        let wallet0 = Wallet::new();
        let wallet1 = Wallet::new();
        let wallet2 = Wallet::new();
        let wallet3 = Wallet::new();
        let mut node0 = Node::new_with_wallet(
            0,
            0,
            1,
            blockchain.clone(),
            wallet0.clone(),
            world_sender.clone(),
            1000,
            ConsensusType::TopoStake,
        );
        let mut node1 = Node::new_with_wallet(
            1,
            0,
            1,
            blockchain.clone(),
            wallet1.clone(),
            world_sender.clone(),
            1000,
            ConsensusType::TopoStake,
        );
        let mut node2 = Node::new_with_wallet(
            2,
            0,
            1,
            blockchain.clone(),
            wallet2.clone(),
            world_sender.clone(),
            1000,
            ConsensusType::TopoStake,
        );
        let mut node3 = Node::new_with_wallet(
            3,
            0,
            1,
            blockchain.clone(),
            wallet3.clone(),
            world_sender.clone(),
            1000,
            ConsensusType::TopoStake,
        );

        node0.neighbors.push(Neighbor::new(
            node1.index,
            node1.wallet.address.clone(),
            node1.sender.clone(),
        ));
        node1.neighbors.push(Neighbor::new(
            node2.index,
            node2.wallet.address.clone(),
            node2.sender.clone(),
        ));
        node2.neighbors.push(Neighbor::new(
            node3.index,
            node3.wallet.address.clone(),
            node3.sender.clone(),
        ));

        node3.neighbors.push(Neighbor::new(
            node2.index,
            node2.wallet.address.clone(),
            node2.sender.clone(),
        ));

        node2.neighbors.push(Neighbor::new(
            node1.index,
            node1.wallet.address.clone(),
            node1.sender.clone(),
        ));

        node1.neighbors.push(Neighbor::new(
            node0.index,
            node0.wallet.address.clone(),
            node0.sender.clone(),
        ));
        let node0_bc = node0.blockchain.clone();
        let node0_sender = node0.sender.clone();
        let handle0 = tokio::spawn(async move {
            node0.run().await;
        });
        let node1_bc = node1.blockchain.clone();
        let handle1 = tokio::spawn(async move {
            node1.run().await;
        });
        let node2_bc = node2.blockchain.clone();
        let handle2 = tokio::spawn(async move {
            node2.run().await;
        });
        let node3_bc = node3.blockchain.clone();
        let node3_sender = node3.sender.clone();
        let handle3 = tokio::spawn(async move {
            node3.run().await;
        });

        //node0发送交易
        let transaction = Transaction::new(wallet3.address.clone(), 32, wallet0.clone());
        let transaction_paths = TransactionPaths::new(transaction);
        node0_sender
            .send(Message::new_transaction_paths_msg(
                Arc::new(transaction_paths),
                "".to_string(),
            ))
            .await
            .unwrap();

        tokio::time::sleep(Duration::from_secs(1)).await;

        node3_sender
            .send(Message::new_generate_block_msg())
            .await
            .unwrap();
        tokio::time::sleep(Duration::from_secs(1)).await;

        assert_eq!(
            node0_bc.read().await.get_last_hash(),
            node1_bc.read().await.get_last_hash()
        );
        assert_eq!(
            node1_bc.read().await.get_last_hash(),
            node2_bc.read().await.get_last_hash()
        );
        assert_eq!(
            node2_bc.read().await.get_last_hash(),
            node3_bc.read().await.get_last_hash()
        );
        {
            node3_bc.read().await.simple_print_last_five_block();
        }
        handle0.abort();
        handle1.abort();
        handle2.abort();
        handle3.abort();
    }

    #[test]
    fn test_balance_management() {
        let (_tx, _rx) = tokio::sync::mpsc::channel::<Message>(8);
        let (world_tx, _world_rx) = tokio::sync::mpsc::channel::<Message>(8);
        let bc = Blockchain::new(Block::gen_genesis_block());
        let mut node = Node::new(0, 0, 0, bc, world_tx, 1000, ConsensusType::TopoStake, 0);

        assert_eq!(node.get_balance(), 0.0);

        node.set_balance(500.0);
        assert_eq!(node.get_balance(), 500.0);

        assert!(node.deduct_balance(100.0));
        assert_eq!(node.get_balance(), 400.0);

        assert!(node.deduct_balance(400.0));
        assert_eq!(node.get_balance(), 0.0);

        assert!(!node.deduct_balance(0.1));
        assert_eq!(node.get_balance(), 0.0);

        assert!(!node.deduct_balance(10.0));
        assert_eq!(node.get_balance(), 0.0);
    }
}
