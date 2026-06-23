use crate::blockchain::transaction::Transaction;
use crate::wallet::Wallet;
use crate::{tools, wallet};
use blst::min_sig::{PublicKey, Signature};
use dashmap::DashMap;
use hex::{decode, encode};
use lazy_static::lazy_static;
use serde::{Deserialize, Serialize};
use std::collections::HashSet;
use std::fmt;

lazy_static! {
    static ref RECEIPT_COMMITMENT_CACHE: DashMap<String, String> = DashMap::new();
    static ref RECEIPT_CONFLICT_CACHE: DashMap<String, usize> = DashMap::new();
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq)]
pub struct Path {
    pub from: String,
    pub to: String,
    pub prefix: String,
    pub sender_signature: String,
    pub receiver_signature: Option<String>,
}

/// Revised propagation path used while transactions are in flight.
#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct TransactionPaths {
    pub transaction: Transaction,
    pub epoch: u64,
    pub paths: Vec<Path>,
}

/// Revised block-level path record.
///
/// `paths` stores the non-proposer validator sequence. The proposer is obtained
/// from the block header during verification.
#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct AggregatedSignedPaths {
    pub signature: String,
    pub paths: Vec<String>,
}

impl TransactionPaths {
    pub fn new(transaction: Transaction) -> TransactionPaths {
        Self::new_with_epoch(transaction, 0)
    }

    pub fn new_with_epoch(transaction: Transaction, epoch: u64) -> TransactionPaths {
        TransactionPaths {
            transaction,
            epoch,
            paths: Vec::new(),
        }
    }

    pub fn new_with_paths(transaction: Transaction, paths: Vec<Path>) -> TransactionPaths {
        TransactionPaths {
            transaction,
            epoch: 0,
            paths,
        }
    }

    pub fn add_path(&mut self, to: String, wallet: Wallet) {
        let _ = self.append_outgoing_hop(to, wallet);
    }

    pub fn append_outgoing_hop(&mut self, to: String, sender_wallet: Wallet) -> bool {
        if self.has_pending_hop() {
            return false;
        }
        let from = self.current_tail();
        if from != sender_wallet.address {
            return false;
        }
        if self.node_sequence().iter().any(|node| node == &to) {
            return false;
        }
        let prefix = self.chain_value_for_tail();
        let message = edge_statement(&prefix, &from, &to);
        let sender_signature = sender_wallet.sign_by_bls(message);
        self.paths.push(Path {
            from,
            to,
            prefix: encode(prefix),
            sender_signature,
            receiver_signature: None,
        });
        true
    }

    pub fn complete_pending_hop(&mut self, receiver_wallet: Wallet) -> bool {
        let Some(hop) = self.paths.last() else {
            return self.transaction.from == receiver_wallet.address;
        };
        if hop.to != receiver_wallet.address {
            return false;
        }
        if hop.receiver_signature.is_some() {
            return true;
        }
        if !self.verify_pending_sender_signature() {
            return false;
        }

        let prefix = match decode(&hop.prefix) {
            Ok(prefix) => prefix,
            Err(_) => return false,
        };
        let message = edge_statement(&prefix, &hop.from, &hop.to);
        let receipt_key = receipt_cache_key(&self.transaction.hash, self.epoch, &hop.to);
        let receipt_commitment = encode(tools::Hasher::hash(message.clone()));
        if let Some(existing) = RECEIPT_COMMITMENT_CACHE.get(&receipt_key) {
            if existing.value() != &receipt_commitment {
                RECEIPT_CONFLICT_CACHE
                    .entry(receipt_key)
                    .and_modify(|count| *count += 1)
                    .or_insert(1);
                return false;
            }
        } else {
            RECEIPT_COMMITMENT_CACHE.insert(receipt_key, receipt_commitment);
        }

        let receiver_signature = receiver_wallet.sign_by_bls(message);
        if let Some(last) = self.paths.last_mut() {
            last.receiver_signature = Some(receiver_signature);
            true
        } else {
            false
        }
    }

    pub fn append_completed_hop(
        &mut self,
        to: String,
        sender_wallet: Wallet,
        receiver_wallet: Wallet,
    ) -> bool {
        self.append_outgoing_hop(to, sender_wallet) && self.complete_pending_hop(receiver_wallet)
    }

    pub fn verify(&self, current_address: String) -> bool {
        if !self.transaction.clone().verify() {
            return false;
        }
        if self.has_repeated_identities() {
            return false;
        }
        if self.paths.is_empty() {
            return current_address == self.transaction.from;
        }
        if self.current_tail() != current_address {
            return false;
        }
        self.verify_completed_hops()
    }

    pub fn verify_last(&self, current_address: String) -> bool {
        if !self.transaction.clone().verify() {
            return false;
        }
        let Some(hop) = self.paths.last() else {
            return current_address == self.transaction.from;
        };
        if hop.to != current_address {
            return false;
        }
        self.verify_pending_sender_signature()
    }

    pub fn verify_completed_hops(&self) -> bool {
        for (idx, hop) in self.paths.iter().enumerate() {
            if hop.receiver_signature.is_none() {
                return false;
            }
            if !self.verify_hop(idx, true) {
                return false;
            }
        }
        true
    }

    pub fn verify_pending_sender_signature(&self) -> bool {
        let Some(idx) = self.paths.len().checked_sub(1) else {
            return self.transaction.verify();
        };
        self.verify_hop(idx, false)
    }

    fn verify_hop(&self, idx: usize, require_receiver: bool) -> bool {
        let Some(hop) = self.paths.get(idx) else {
            return false;
        };
        let expected_prefix = self.chain_value_for_node_index(idx);
        if encode(&expected_prefix) != hop.prefix {
            return false;
        }
        let nodes = self.node_sequence();
        if nodes.get(idx) != Some(&hop.from) || nodes.get(idx + 1) != Some(&hop.to) {
            return false;
        }
        let message = edge_statement(&expected_prefix, &hop.from, &hop.to);
        let Some(sender_pk) = wallet::get_bls_pub_key(hop.from.clone()) else {
            return false;
        };
        if !Wallet::verify_bls_with_pk(message.clone(), hop.sender_signature.clone(), sender_pk) {
            return false;
        }
        if require_receiver {
            let Some(receiver_signature) = &hop.receiver_signature else {
                return false;
            };
            let Some(receiver_pk) = wallet::get_bls_pub_key(hop.to.clone()) else {
                return false;
            };
            if !Wallet::verify_bls_with_pk(message, receiver_signature.clone(), receiver_pk) {
                return false;
            }
        }
        true
    }

    pub fn to_aggregated_signed_paths(&self) -> AggregatedSignedPaths {
        AggregatedSignedPaths::from_transaction_paths(self.clone())
    }

    pub fn from_json(json: Vec<u8>) -> Result<TransactionPaths, PathError> {
        let transaction_paths: TransactionPaths = serde_json::from_slice(json.as_slice())?;
        Ok(transaction_paths)
    }

    pub fn to_json(&self) -> Vec<u8> {
        serde_json::to_vec(&self).unwrap()
    }

    pub fn to_paths_string(&self) -> String {
        self.node_sequence()
            .iter()
            .map(|x| x[0..5.min(x.len())].to_string())
            .collect::<Vec<String>>()
            .join("->")
    }

    pub fn node_sequence(&self) -> Vec<String> {
        let mut nodes = vec![self.transaction.from.clone()];
        nodes.extend(self.paths.iter().map(|hop| hop.to.clone()));
        nodes
    }

    pub fn has_pending_hop(&self) -> bool {
        self.paths
            .last()
            .map(|hop| hop.receiver_signature.is_none())
            .unwrap_or(false)
    }

    pub fn has_repeated_identities(&self) -> bool {
        let mut seen = HashSet::new();
        self.node_sequence()
            .iter()
            .any(|node| !seen.insert(node.clone()))
    }

    fn current_tail(&self) -> String {
        self.paths
            .last()
            .map(|hop| hop.to.clone())
            .unwrap_or_else(|| self.transaction.from.clone())
    }

    fn chain_value_for_tail(&self) -> Vec<u8> {
        let tail_idx = self.paths.len();
        self.chain_value_for_node_index(tail_idx)
    }

    fn chain_value_for_node_index(&self, node_idx: usize) -> Vec<u8> {
        let nodes = self.node_sequence();
        chain_value_for_nodes(&self.transaction.hash, self.epoch, &nodes, node_idx)
    }
}

pub fn clear_receipt_cache_for_tests() {
    RECEIPT_COMMITMENT_CACHE.clear();
    RECEIPT_CONFLICT_CACHE.clear();
}

pub fn conflicting_receipt_count(tx_hash: &str, epoch: u64, receiver: &str) -> usize {
    RECEIPT_CONFLICT_CACHE
        .get(&receipt_cache_key(tx_hash, epoch, receiver))
        .map(|entry| *entry.value())
        .unwrap_or(0)
}

impl AggregatedSignedPaths {
    pub fn from_transaction_paths(paths: TransactionPaths) -> AggregatedSignedPaths {
        let full_nodes = paths.node_sequence();
        if full_nodes.is_empty() {
            return AggregatedSignedPaths {
                signature: String::new(),
                paths: Vec::new(),
            };
        }

        let non_proposer_nodes = full_nodes[..full_nodes.len().saturating_sub(1)].to_vec();
        if full_nodes.len() == 1 {
            return AggregatedSignedPaths {
                signature: String::new(),
                paths: Vec::new(),
            };
        }
        if !paths.verify_completed_hops() {
            return AggregatedSignedPaths {
                signature: String::new(),
                paths: non_proposer_nodes,
            };
        }

        let mut signatures: Vec<Signature> = Vec::with_capacity(paths.paths.len() * 2);
        for hop in &paths.paths {
            let Ok(sender_sig) = Wallet::bls_signature_from_string(hop.sender_signature.clone())
            else {
                return AggregatedSignedPaths {
                    signature: String::new(),
                    paths: non_proposer_nodes,
                };
            };
            signatures.push(sender_sig);
            let Some(receiver_signature) = &hop.receiver_signature else {
                return AggregatedSignedPaths {
                    signature: String::new(),
                    paths: non_proposer_nodes,
                };
            };
            let Ok(receiver_sig) = Wallet::bls_signature_from_string(receiver_signature.clone())
            else {
                return AggregatedSignedPaths {
                    signature: String::new(),
                    paths: non_proposer_nodes,
                };
            };
            signatures.push(receiver_sig);
        }

        AggregatedSignedPaths {
            signature: Wallet::bls_aggregated_sign(signatures),
            paths: non_proposer_nodes,
        }
    }

    pub fn verify(&self, transaction: Transaction, miner: String) -> bool {
        self.verify_at_epoch(transaction, miner, 0)
    }

    pub fn verify_at_epoch(&self, transaction: Transaction, miner: String, epoch: u64) -> bool {
        if !transaction.verify() {
            return false;
        }
        if transaction.from == miner && self.paths.is_empty() {
            return true;
        }
        if self.paths.is_empty() {
            return false;
        }

        let full_nodes = self.full_path(miner);
        if full_nodes.first() != Some(&transaction.from) {
            return false;
        }
        if has_repeated_nodes(&full_nodes) {
            return false;
        }
        let hop_count = full_nodes.len().saturating_sub(1);
        if hop_count == 0 {
            return transaction.from == full_nodes[0];
        }
        if self.signature.is_empty() {
            return false;
        }

        let mut messages: Vec<Vec<u8>> = Vec::with_capacity(hop_count * 2);
        let mut pks: Vec<PublicKey> = Vec::with_capacity(hop_count * 2);
        for idx in 0..hop_count {
            let prefix = chain_value_for_nodes(&transaction.hash, epoch, &full_nodes, idx);
            let message = edge_statement(&prefix, &full_nodes[idx], &full_nodes[idx + 1]);
            let Some(sender_pk) = wallet::get_bls_pub_key(full_nodes[idx].clone()) else {
                return false;
            };
            let Some(receiver_pk) = wallet::get_bls_pub_key(full_nodes[idx + 1].clone()) else {
                return false;
            };
            messages.push(message.clone());
            pks.push(sender_pk);
            messages.push(message);
            pks.push(receiver_pk);
        }

        Wallet::bls_aggregated_verify(messages, pks, self.signature.clone())
    }

    pub fn full_path(&self, miner: String) -> Vec<String> {
        let mut full_path = self.paths.clone();
        if full_path.last() != Some(&miner) {
            full_path.push(miner);
        }
        full_path
    }

    pub fn has_repeated_identities(&self) -> bool {
        has_repeated_nodes(&self.paths)
    }

    pub fn bytes(&self) -> u64 {
        let path_bytes: u64 = self.paths.iter().map(|n| n.as_bytes().len() as u64).sum();
        path_bytes + self.signature.as_bytes().len() as u64
    }

    pub fn to_json(&self) -> Vec<u8> {
        serde_json::to_vec(&self).unwrap()
    }

    pub fn from_json(json: Vec<u8>) -> AggregatedSignedPaths {
        serde_json::from_slice(json.as_slice()).unwrap()
    }

    pub fn json_bytes(&self) -> u64 {
        self.to_json().len() as u64
    }

    pub fn compress(&self) -> Vec<u8> {
        zstd::stream::encode_all(self.to_json().as_slice(), 22).unwrap()
    }

    pub fn decompress(data: Vec<u8>) -> AggregatedSignedPaths {
        let data = zstd::stream::decode_all(data.as_slice()).unwrap();
        AggregatedSignedPaths::from_json(data)
    }
}

fn chain_value_for_nodes(tx_hash: &str, epoch: u64, nodes: &[String], node_idx: usize) -> Vec<u8> {
    let tx_hash_bytes = decode(tx_hash)
        .unwrap_or_else(|_| tools::Hasher::hash(tx_hash.as_bytes().to_vec()).to_vec());
    if nodes.is_empty() {
        return tools::Hasher::hash(tx_hash_bytes).to_vec();
    }
    let capped_idx = node_idx.min(nodes.len() - 1);
    let mut initial = tx_hash_bytes;
    initial.extend_from_slice(&epoch.to_be_bytes());
    initial.extend_from_slice(&hash_identity(&nodes[0]));
    let mut chain = tools::Hasher::hash(initial).to_vec();
    for node in nodes.iter().take(capped_idx + 1).skip(1) {
        let mut data = chain;
        data.extend_from_slice(&hash_identity(node));
        chain = tools::Hasher::hash(data).to_vec();
    }
    chain
}

fn edge_statement(prefix: &[u8], from: &str, to: &str) -> Vec<u8> {
    let mut message = prefix.to_vec();
    message.extend_from_slice(&hash_identity(from));
    message.extend_from_slice(&hash_identity(to));
    message
}

fn hash_identity(identity: &str) -> Vec<u8> {
    tools::Hasher::hash(identity.as_bytes().to_vec()).to_vec()
}

fn receipt_cache_key(tx_hash: &str, epoch: u64, receiver: &str) -> String {
    format!("{}:{}:{}", tx_hash, epoch, receiver)
}

fn has_repeated_nodes(nodes: &[String]) -> bool {
    let mut seen = HashSet::new();
    nodes.iter().any(|node| !seen.insert(node))
}

#[derive(Debug)]
pub enum PathError {
    JSONError,
}

impl fmt::Display for PathError {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        match *self {
            PathError::JSONError => {
                write!(f, "Invalid Json Error")
            }
        }
    }
}

impl From<serde_json::error::Error> for PathError {
    fn from(_: serde_json::error::Error) -> Self {
        PathError::JSONError
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::wallet;

    fn build_valid_path(
        epoch: u64,
    ) -> (
        Transaction,
        TransactionPaths,
        Wallet,
        Wallet,
        Wallet,
        Wallet,
    ) {
        clear_receipt_cache_for_tests();
        let origin = Wallet::new();
        let relay1 = Wallet::new();
        let relay2 = Wallet::new();
        let miner = Wallet::new();
        let transaction = Transaction::new("123".to_string(), 32, origin.clone());
        let mut transaction_paths = TransactionPaths::new_with_epoch(transaction.clone(), epoch);
        assert!(transaction_paths.append_outgoing_hop(relay1.address.clone(), origin.clone()));
        assert!(transaction_paths.complete_pending_hop(relay1.clone()));
        assert!(transaction_paths.append_outgoing_hop(relay2.address.clone(), relay1.clone()));
        assert!(transaction_paths.complete_pending_hop(relay2.clone()));
        assert!(transaction_paths.append_outgoing_hop(miner.address.clone(), relay2.clone()));
        assert!(transaction_paths.complete_pending_hop(miner.clone()));
        (
            transaction,
            transaction_paths,
            origin,
            relay1,
            relay2,
            miner,
        )
    }

    #[test]
    fn valid_two_sided_path() {
        let (transaction, transaction_paths, _origin, _relay1, _relay2, miner) =
            build_valid_path(7);
        assert!(transaction_paths.verify(miner.address.clone()));
        let aggregated = AggregatedSignedPaths::from_transaction_paths(transaction_paths);
        assert!(aggregated.verify_at_epoch(transaction, miner.address, 7));
    }

    #[test]
    fn missing_receiver_signature_fails() {
        clear_receipt_cache_for_tests();
        let origin = Wallet::new();
        let relay = Wallet::new();
        let transaction = Transaction::new("123".to_string(), 32, origin.clone());
        let mut transaction_paths = TransactionPaths::new_with_epoch(transaction.clone(), 1);
        assert!(transaction_paths.append_outgoing_hop(relay.address.clone(), origin));
        assert!(!transaction_paths.verify(relay.address.clone()));
        let aggregated = AggregatedSignedPaths::from_transaction_paths(transaction_paths);
        assert!(!aggregated.verify_at_epoch(transaction, relay.address, 1));
    }

    #[test]
    fn modified_transaction_fails() {
        let (mut transaction, transaction_paths, _origin, _relay1, _relay2, miner) =
            build_valid_path(1);
        let aggregated = AggregatedSignedPaths::from_transaction_paths(transaction_paths);
        transaction.amount += 1;
        assert!(!aggregated.verify_at_epoch(transaction, miner.address, 1));
    }

    #[test]
    fn modified_epoch_fails() {
        let (transaction, transaction_paths, _origin, _relay1, _relay2, miner) =
            build_valid_path(1);
        let aggregated = AggregatedSignedPaths::from_transaction_paths(transaction_paths);
        assert!(!aggregated.verify_at_epoch(transaction, miner.address, 2));
    }

    #[test]
    fn reordered_node_fails() {
        let (transaction, transaction_paths, _origin, _relay1, _relay2, miner) =
            build_valid_path(1);
        let mut aggregated = AggregatedSignedPaths::from_transaction_paths(transaction_paths);
        aggregated.paths.swap(1, 2);
        assert!(!aggregated.verify_at_epoch(transaction, miner.address, 1));
    }

    #[test]
    fn removed_node_fails() {
        let (transaction, transaction_paths, _origin, _relay1, _relay2, miner) =
            build_valid_path(1);
        let mut aggregated = AggregatedSignedPaths::from_transaction_paths(transaction_paths);
        aggregated.paths.remove(1);
        assert!(!aggregated.verify_at_epoch(transaction, miner.address, 1));
    }

    #[test]
    fn repeated_identity_fails() {
        let (transaction, transaction_paths, _origin, relay1, _relay2, miner) = build_valid_path(1);
        let mut aggregated = AggregatedSignedPaths::from_transaction_paths(transaction_paths);
        aggregated.paths.push(relay1.address);
        assert!(!aggregated.verify_at_epoch(transaction, miner.address, 1));
    }

    #[test]
    fn conflicting_receipts_are_detected() {
        clear_receipt_cache_for_tests();
        let origin = Wallet::new();
        let other_origin = Wallet::new();
        let receiver = Wallet::new();
        let transaction = Transaction::new("123".to_string(), 32, origin.clone());

        let mut first = TransactionPaths::new_with_epoch(transaction.clone(), 9);
        assert!(first.append_outgoing_hop(receiver.address.clone(), origin));
        assert!(first.complete_pending_hop(receiver.clone()));

        let mut second = TransactionPaths::new_with_epoch(transaction.clone(), 9);
        second.transaction.from = other_origin.address.clone();
        assert!(second.append_outgoing_hop(receiver.address.clone(), other_origin));
        assert!(!second.complete_pending_hop(receiver.clone()));
        assert_eq!(
            conflicting_receipt_count(&transaction.hash, 9, &receiver.address),
            1
        );
    }

    #[test]
    fn aggregate_verification_accepts_repeated_messages_with_different_keys() {
        let origin = Wallet::new();
        let relay = Wallet::new();
        let transaction = Transaction::new("123".to_string(), 32, origin.clone());
        let mut transaction_paths = TransactionPaths::new_with_epoch(transaction.clone(), 5);
        assert!(transaction_paths.append_outgoing_hop(relay.address.clone(), origin));
        assert!(transaction_paths.complete_pending_hop(relay.clone()));
        let aggregated = AggregatedSignedPaths::from_transaction_paths(transaction_paths);
        assert!(aggregated.verify_at_epoch(transaction, relay.address, 5));
    }

    #[test]
    fn direct_originator_to_proposer_path() {
        let origin = Wallet::new();
        let miner = Wallet::new();
        let transaction = Transaction::new("123".to_string(), 32, origin.clone());
        let mut transaction_paths = TransactionPaths::new_with_epoch(transaction.clone(), 4);
        assert!(transaction_paths.append_outgoing_hop(miner.address.clone(), origin));
        assert!(transaction_paths.complete_pending_hop(miner.clone()));
        let aggregated = AggregatedSignedPaths::from_transaction_paths(transaction_paths);
        assert_eq!(aggregated.paths, vec![transaction.from.clone()]);
        assert!(aggregated.verify_at_epoch(transaction, miner.address, 4));
    }

    #[test]
    fn proposer_generated_transaction_has_empty_path() {
        let miner = Wallet::new();
        let transaction = Transaction::new("123".to_string(), 32, miner.clone());
        let transaction_paths = TransactionPaths::new_with_epoch(transaction.clone(), 4);
        let aggregated = AggregatedSignedPaths::from_transaction_paths(transaction_paths);
        assert!(aggregated.paths.is_empty());
        assert!(aggregated.signature.is_empty());
        assert!(aggregated.verify_at_epoch(transaction, miner.address, 4));
    }

    #[test]
    fn test_transaction_paths_bls() {
        let wallet = Wallet::new();
        let wallet2 = Wallet::new();
        let wallet3 = Wallet::new();
        let miner = Wallet::new();
        let transaction = Transaction::new("123".to_string(), 32, wallet.clone());
        let mut transaction_paths = TransactionPaths::new(transaction.clone());
        assert!(transaction_paths.append_outgoing_hop(wallet2.address.clone(), wallet.clone()));
        assert!(transaction_paths.complete_pending_hop(wallet2.clone()));
        assert!(transaction_paths.append_outgoing_hop(wallet3.address.clone(), wallet2.clone()));
        assert!(transaction_paths.complete_pending_hop(wallet3.clone()));
        assert!(transaction_paths.append_outgoing_hop(miner.address.clone(), wallet3.clone()));
        assert!(transaction_paths.complete_pending_hop(miner.clone()));
        wallet::insert_bls_pub_key(wallet.address.clone(), wallet.bls_public_key);
        wallet::insert_bls_pub_key(wallet2.address.clone(), wallet2.bls_public_key);
        wallet::insert_bls_pub_key(wallet3.address.clone(), wallet3.bls_public_key);
        wallet::insert_bls_pub_key(miner.address.clone(), miner.bls_public_key);
        assert!(transaction_paths.verify(miner.address.clone()));

        let aggregated_signed_paths =
            AggregatedSignedPaths::from_transaction_paths(transaction_paths);
        assert!(aggregated_signed_paths.verify(transaction.clone(), miner.address.clone()));
        assert_eq!(aggregated_signed_paths.paths.last(), Some(&wallet3.address));
    }
}
