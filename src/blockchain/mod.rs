pub mod block;
pub mod path;
pub mod transaction;

use crate::blockchain::block::Block;
use log::error;
use serde::{Deserialize, Serialize};
use std::collections::HashSet;
use std::fmt;
use tokio::io::AsyncWriteExt;

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct Blockchain {
    pub blocks: Vec<Block>,
    #[serde(skip)]
    pub transaction_index: HashSet<String>,
    #[serde(skip)]
    pub max_blocks_in_memory: usize,
}

impl Blockchain {
    pub fn new(genesis_block: Block) -> Blockchain {
        let mut set = HashSet::new();
        for x in genesis_block.clone().body.transactions {
            set.insert(x.hash.to_string());
        }
        Blockchain {
            blocks: vec![genesis_block],
            transaction_index: set,
            max_blocks_in_memory: 100, // 默认只在内存中保留最近的100个区块
        }
    }

    pub fn pop_block(&mut self) -> Option<Block> {
        let block = self.blocks.pop()?;
        for tx in &block.body.transactions {
            self.transaction_index.remove(&tx.hash);
        }
        Some(block)
    }

    pub fn get_block(&self, height: u64) -> Option<Block> {
        // 因为我们限制了内存中的区块数量，所以不能直接用 height - 1 作为索引
        // 需要找到对应的区块
        self.blocks
            .iter()
            .find(|b| b.header.index == height)
            .cloned()
    }

    pub fn add_block(&mut self, block: Block) -> Result<(), BlockChainError> {
        if self.get_last_index() + 1 > block.header.index {
            return Err(BlockChainError::IndexTooSmall);
        }
        if !block.verify() {
            return Err(BlockChainError::InvalidBlock);
        }
        if self.get_last_hash() == block.header.hash {
            //重复收到
            return Err(BlockChainError::DuplicateBlocksReceived);
        }
        if self.get_last_hash() != block.header.parent_hash {
            return Err(BlockChainError::ParentHashMismatch);
        }
        if self.get_last_block().header.index + 1 != block.header.index {
            return Err(BlockChainError::IndexMismatch);
        }
        if self.get_last_block().header.epoch > block.header.epoch {
            return Err(BlockChainError::EpochError);
        }
        if self.get_last_block().header.epoch == block.header.epoch
            && self.get_last_block().header.slot > block.header.slot
        {
            return Err(BlockChainError::SlotError);
        }
        //check transaction if exists
        for x in &block.body.transactions {
            if self.exist_transaction(&x.hash) {
                return Err(BlockChainError::TransactionExists);
            }
        }
        for x in &block.body.transactions {
            self.transaction_index.insert(x.hash.clone());
        }
        self.blocks.push(block.clone());

        // 限制内存中的区块数量
        if self.blocks.len() > self.max_blocks_in_memory {
            // 移除最老的区块
            let removed_block = self.blocks.remove(0);
            // 同时从 transaction_index 中移除这些交易的 hash，防止内存泄漏
            for tx in removed_block.body.transactions {
                self.transaction_index.remove(&tx.hash);
            }
        }

        Ok(())
    }

    pub fn exist_transaction(&self, hash: &str) -> bool {
        self.transaction_index.contains(hash)
    }

    pub fn get_last_block(&self) -> Block {
        self.blocks.last().unwrap().clone()
    }

    pub fn get_last_hash(&self) -> String {
        self.blocks.last().unwrap().header.hash.clone()
    }
    pub fn get_last_index(&self) -> u64 {
        self.get_last_block().header.index
    }

    pub fn get_last_epoch_slot(&self) -> (u64, u64) {
        let header = self.get_last_block().header;
        (header.epoch, header.slot)
    }

    pub fn get_last_slot_block(&self) -> Vec<Block> {
        let (epoch, slot) = self.get_last_epoch_slot();
        let mut blocks: Vec<Block> = self
            .blocks
            .iter()
            .rev()
            .take_while(|b| b.header.slot == slot && b.header.epoch == epoch)
            .map(|b| b.clone())
            .collect();
        blocks.reverse();
        blocks
    }

    pub fn get_last_epoch_block(&self) -> Vec<Block> {
        let (epoch, _slot) = self.get_last_epoch_slot();
        let mut blocks: Vec<Block> = self
            .blocks
            .iter()
            .rev()
            .take_while(|b| b.header.epoch == epoch)
            .map(|b| b.clone())
            .collect();
        blocks.reverse();
        blocks
    }

    pub fn simple_print_last_five_block(&self) {
        let last_five = &self.blocks[self.blocks.len().saturating_sub(5)..];
        for x in last_five {
            x.simple_print_no_transaction_detail();
        }
    }

    pub async fn write_to_file_all_json(&self) {
        let path = "blockchain.json";
        let json = serde_json::to_string_pretty(&self.blocks).unwrap();
        match tokio::fs::write(path, json).await {
            Ok(_) => {}
            Err(e) => {
                error!("Error writing blockchain file: {}", e);
            }
        };
    }

    pub async fn write_to_file_last_block_simple(&self) {
        let path = "blockchain.txt";
        if self.get_last_index() == 0 {
            let _ = tokio::fs::remove_file(path).await;
        }
        let mut file = match tokio::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(path)
            .await
        {
            Ok(f) => f,
            Err(e) => {
                error!("Error writing blockchain file: {}", e);
                return;
            }
        };
        let string = self.get_last_block().simple_print_no_transaction_string();
        if let Err(e) = file.write_all(string.as_bytes()).await {
            error!("Error writing blockchain file: {}", e);
        }
    }
}

#[derive(Debug, PartialEq)]
pub enum BlockChainError {
    InvalidBlock,
    ParentHashMismatch,
    IndexMismatch,
    EpochError,
    SlotError,
    DuplicateBlocksReceived,
    TransactionExists,
    IndexTooSmall,
}

impl fmt::Display for BlockChainError {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        match *self {
            BlockChainError::InvalidBlock => {
                write!(f, "Invalid Block Error")
            }
            BlockChainError::ParentHashMismatch => {
                write!(f, "Parent Hash Mismatch Error")
            }
            BlockChainError::IndexMismatch => {
                write!(f, "Parent Index Mismatch Error")
            }
            BlockChainError::EpochError => {
                write!(f, "Epoch Error")
            }
            BlockChainError::SlotError => {
                write!(f, "Slot Error")
            }

            BlockChainError::DuplicateBlocksReceived => {
                write!(f, "Duplicate Block Received")
            }

            BlockChainError::TransactionExists => {
                write!(f, "Transaction exists")
            }
            BlockChainError::IndexTooSmall => {
                write!(f, "Index Too Small Error")
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::blockchain::block::Body;
    use crate::blockchain::path::{AggregatedSignedPaths, TransactionPaths};
    use crate::blockchain::transaction::Transaction;
    use crate::wallet::Wallet;

    #[test]
    fn test_blockchain() {
        let _ = env_logger::builder()
            .filter_level(log::LevelFilter::Info)
            .is_test(true)
            .try_init();

        let mut blockchain = Blockchain::new(Block::gen_genesis_block());
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
            vec![AggregatedSignedPaths::from_transaction_paths(
                transaction_paths,
            )],
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
        blockchain.add_block(block).unwrap();
        blockchain.simple_print_last_five_block();
    }
}
