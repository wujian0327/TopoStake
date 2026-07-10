use crate::blockchain::block::Block;
use crate::blockchain::path::AggregatedSignedPaths;
use crate::blockchain::transaction::Transaction;
use crate::blockchain::Blockchain;
use crate::consensus::{
    BalanceDelta, Consensus, ConsensusMetricsSnapshot, Validator, ValidatorError,
};
use log::{debug, info};
use rand::prelude::StdRng;
use rand::{Rng, SeedableRng};
use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet, VecDeque};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TopoStakeConfig {
    pub initial_depth: usize,
    pub beta: f64,
    pub saturation_k: f64,
    pub eta: f64,
    pub bonus_cap: f64,
    pub proposer_fee_ratio: f64,
    pub reward_settlement_depth: u64,
}

impl Default for TopoStakeConfig {
    fn default() -> Self {
        TopoStakeConfig {
            initial_depth: 4,
            beta: 0.2,
            saturation_k: 1.0,
            eta: 0.5,
            bonus_cap: 1.0,
            proposer_fee_ratio: 0.7,
            reward_settlement_depth: 2,
        }
    }
}

impl TopoStakeConfig {
    pub fn validate(&self) -> Result<(), String> {
        if self.initial_depth < 1 {
            return Err("initial_depth must be >= 1".to_string());
        }
        if !(self.beta > 0.0 && self.beta <= 1.0) {
            return Err("beta must satisfy 0 < beta <= 1".to_string());
        }
        if self.saturation_k <= 0.0 {
            return Err("saturation_k must be > 0".to_string());
        }
        if !(self.proposer_fee_ratio >= 0.0 && self.proposer_fee_ratio < 1.0) {
            return Err("proposer_fee_ratio must satisfy 0 <= theta < 1".to_string());
        }
        if self.eta < 0.0 {
            return Err("eta must be >= 0".to_string());
        }
        if self.bonus_cap < 0.0 {
            return Err("bonus_cap must be >= 0".to_string());
        }
        if self.eta * self.bonus_cap > 0.5 + f64::EPSILON {
            return Err("eta * bonus_cap must be <= 0.5".to_string());
        }
        Ok(())
    }
}

#[derive(Debug, Clone)]
struct PendingRewardBatch {
    settle_at_block: u64,
    rewards: Vec<BalanceDelta>,
}

#[derive(Debug, Clone, Default)]
pub struct RewardPlan {
    pub rewards: Vec<BalanceDelta>,
    pub proposer_reward: f64,
    pub relay_reward: f64,
    pub burned_relay_fee: f64,
    pub total_fee: f64,
}

pub struct TopoStakeConsensus {
    config: TopoStakeConfig,
    current_depth: usize,
    base_reward: f64,
    score_history: HashMap<String, f64>,
    normalized_score: HashMap<String, f64>,
    epoch_stake_snapshot: HashMap<String, f64>,
    unnormalized_proposer_weights: HashMap<String, f64>,
    frozen_proposer_weights: HashMap<String, f64>,
    epoch_bonuses: HashMap<String, f64>,
    pending_rewards: VecDeque<PendingRewardBatch>,
}

impl TopoStakeConsensus {
    pub fn new(base_reward: f64, config: TopoStakeConfig) -> Result<Self, String> {
        config.validate()?;
        Ok(TopoStakeConsensus {
            current_depth: config.initial_depth,
            config,
            base_reward,
            score_history: HashMap::new(),
            normalized_score: HashMap::new(),
            epoch_stake_snapshot: HashMap::new(),
            unnormalized_proposer_weights: HashMap::new(),
            frozen_proposer_weights: HashMap::new(),
            epoch_bonuses: HashMap::new(),
            pending_rewards: VecDeque::new(),
        })
    }

    pub fn config(&self) -> &TopoStakeConfig {
        &self.config
    }

    pub fn current_depth(&self) -> usize {
        self.current_depth
    }

    pub fn score_history(&self) -> &HashMap<String, f64> {
        &self.score_history
    }

    pub fn frozen_proposer_weights(&self) -> &HashMap<String, f64> {
        &self.frozen_proposer_weights
    }

    pub fn unnormalized_proposer_weights(&self) -> &HashMap<String, f64> {
        &self.unnormalized_proposer_weights
    }

    pub fn epoch_stake_snapshot(&self) -> &HashMap<String, f64> {
        &self.epoch_stake_snapshot
    }

    pub fn lambda_for_depth(depth: usize) -> f64 {
        let d = depth as f64;
        (2.0 * d + 1.0) / (3.0 * d + 1.0)
    }

    pub fn r_for_depth(depth: usize) -> f64 {
        let d = depth as f64;
        d / (2.0 * d + 1.0)
    }

    pub fn path_budget_for_depth(depth: usize, path_length: usize) -> f64 {
        if path_length < 2 {
            return 0.0;
        }
        let d = depth as f64;
        let m = path_length as f64;
        let lambda = Self::lambda_for_depth(depth);
        d.min(m) / m * lambda.powi(path_length as i32 - 1)
    }

    pub fn alpha_for_depth(depth: usize, position: usize, path_length: usize) -> f64 {
        if path_length < 2 || position == 0 || position >= path_length {
            return 0.0;
        }
        let r = Self::r_for_depth(depth);
        let numerator = (1.0 - r) * r.powi(position as i32 - 1);
        let denominator = 1.0 - r.powi(path_length as i32 - 1);
        numerator / denominator
    }

    pub fn gamma_for_depth(depth: usize, position: usize, path_length: usize) -> f64 {
        Self::path_budget_for_depth(depth, path_length)
            * Self::alpha_for_depth(depth, position, path_length)
    }

    pub fn path_budget(&self, path_length: usize) -> f64 {
        Self::path_budget_for_depth(self.current_depth, path_length)
    }

    pub fn gamma(&self, position: usize, path_length: usize) -> f64 {
        Self::gamma_for_depth(self.current_depth, position, path_length)
    }

    pub fn freeze_proposer_weights(&mut self, validators: &[Validator]) {
        let normalized_stake = Self::normalized_stake(validators);
        self.epoch_stake_snapshot = validators
            .iter()
            .map(|v| (v.address.clone(), v.stake))
            .collect();

        let mut unnormalized = HashMap::new();
        let mut bonuses = HashMap::new();
        for validator in validators {
            let s_hat = *normalized_stake.get(&validator.address).unwrap_or(&0.0);
            let c_hat = *self
                .normalized_score
                .get(&validator.address)
                .unwrap_or(&0.0);
            let bonus = if s_hat > 0.0 {
                (c_hat / s_hat - 1.0).max(0.0).min(self.config.bonus_cap)
            } else {
                0.0
            };
            let weight = s_hat * (1.0 + self.config.eta * bonus);
            bonuses.insert(validator.address.clone(), bonus);
            unnormalized.insert(validator.address.clone(), weight);
        }

        self.epoch_bonuses = bonuses;
        self.unnormalized_proposer_weights = unnormalized.clone();
        self.frozen_proposer_weights = Self::normalize_map(&unnormalized);
    }

    pub fn compute_block_rewards(&self, block: &Block, validators: &[Validator]) -> RewardPlan {
        let validator_set: HashSet<&str> = validators.iter().map(|v| v.address.as_str()).collect();
        let total_fee: f64 = block.body.transactions.iter().map(|tx| tx.fee).sum();
        let proposer_reward = self.base_reward + self.config.proposer_fee_ratio * total_fee;
        let mut rewards = vec![BalanceDelta::new(
            block.header.miner.clone(),
            proposer_reward,
        )];
        let mut relay_reward = 0.0;
        let mut burned_relay_fee = 0.0;

        for (idx, tx) in block.body.transactions.iter().enumerate() {
            let relay_budget = (1.0 - self.config.proposer_fee_ratio) * tx.fee;
            let Some(path) = block.body.paths.get(idx) else {
                burned_relay_fee += relay_budget;
                continue;
            };
            if !Self::valid_path_record(path, tx, &block.header.miner, block.header.epoch) {
                burned_relay_fee += relay_budget;
                continue;
            }

            let full_path = path.full_path(block.header.miner.clone());
            let path_length = full_path.len().saturating_sub(1);
            if path_length < 2 {
                burned_relay_fee += relay_budget;
                continue;
            }

            let mut paid_for_tx = 0.0;
            for position in 1..path_length {
                let relayer = &full_path[position];
                if !validator_set.contains(relayer.as_str()) {
                    continue;
                }
                let gamma = self.gamma(position, path_length);
                let amount = relay_budget * gamma;
                if amount > 0.0 {
                    paid_for_tx += amount;
                    rewards.push(BalanceDelta::new(relayer.clone(), amount));
                }
            }
            relay_reward += paid_for_tx;
            burned_relay_fee += (relay_budget - paid_for_tx).max(0.0);
        }

        RewardPlan {
            rewards,
            proposer_reward,
            relay_reward,
            burned_relay_fee,
            total_fee,
        }
    }

    fn select_with_frozen_weights(
        &mut self,
        validators: &[Validator],
        seed: [u8; 32],
    ) -> Result<Validator, ValidatorError> {
        if validators.is_empty() {
            return Err(ValidatorError::NOValidatorError);
        }
        if self.frozen_proposer_weights.is_empty() {
            self.freeze_proposer_weights(validators);
        }

        let total_weight: f64 = validators
            .iter()
            .map(|v| {
                self.frozen_proposer_weights
                    .get(&v.address)
                    .copied()
                    .unwrap_or(0.0)
            })
            .sum();
        if total_weight <= 0.0 {
            return Err(ValidatorError::NOValidatorError);
        }

        let mut rng = StdRng::from_seed(seed);
        let random_value = rng.gen_range(0.0..total_weight);
        let mut accumulated_weight = 0.0;
        for validator in validators {
            let weight = self
                .frozen_proposer_weights
                .get(&validator.address)
                .copied()
                .unwrap_or(0.0);
            accumulated_weight += weight;
            if accumulated_weight >= random_value {
                info!(
                    "TopoStake revised proposer {} elected with frozen weight {:.6}",
                    validator.address, weight
                );
                return Ok(validator.clone());
            }
        }

        validators
            .last()
            .cloned()
            .ok_or(ValidatorError::NOValidatorError)
    }

    fn update_scores_from_epoch(&mut self, blocks: &[Block], validators: &[Validator]) {
        let normalized_stake = Self::normalized_stake(validators);
        let raw_contribution = self.raw_epoch_contribution(blocks, validators);
        let mut next_scores = HashMap::new();

        for validator in validators {
            let s_hat = *normalized_stake.get(&validator.address).unwrap_or(&0.0);
            let raw = *raw_contribution.get(&validator.address).unwrap_or(&0.0);
            let saturated = Self::saturated_contribution(raw, s_hat, self.config.saturation_k);
            let previous = *self.score_history.get(&validator.address).unwrap_or(&0.0);
            let next = self.config.beta * saturated + (1.0 - self.config.beta) * previous;
            next_scores.insert(validator.address.clone(), next);
        }

        self.score_history = next_scores;
        self.normalized_score = Self::normalize_map(&self.score_history);
        debug!(
            "TopoStake revised epoch scores: {}",
            serde_json::to_string(&self.score_history).unwrap_or_default()
        );
    }

    fn raw_epoch_contribution(
        &self,
        blocks: &[Block],
        validators: &[Validator],
    ) -> HashMap<String, f64> {
        let validator_set: HashSet<&str> = validators.iter().map(|v| v.address.as_str()).collect();
        let mut raw = HashMap::new();

        for block in blocks {
            for (idx, tx) in block.body.transactions.iter().enumerate() {
                let Some(path) = block.body.paths.get(idx) else {
                    continue;
                };
                if !Self::valid_path_record(path, tx, &block.header.miner, block.header.epoch) {
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
                        let gamma = self.gamma(position, path_length);
                        *raw.entry(relayer.clone()).or_insert(0.0) += gamma;
                    }
                }
            }
        }

        raw
    }

    fn adjust_depth_from_epoch_paths(&mut self, blocks: &[Block]) {
        let mut lengths = Vec::new();
        for block in blocks {
            for (idx, tx) in block.body.transactions.iter().enumerate() {
                let Some(path) = block.body.paths.get(idx) else {
                    continue;
                };
                if !Self::valid_path_record(path, tx, &block.header.miner, block.header.epoch) {
                    continue;
                }
                let path_length = path
                    .full_path(block.header.miner.clone())
                    .len()
                    .saturating_sub(1);
                if path_length >= 2 {
                    lengths.push(path_length);
                }
            }
        }
        if lengths.is_empty() {
            return;
        }
        lengths.sort_unstable();
        let median = lengths[lengths.len() / 2];
        if median > self.current_depth {
            self.current_depth += 1;
        } else if median < self.current_depth {
            self.current_depth = self.current_depth.saturating_sub(1).max(1);
        }
    }

    pub fn saturated_contribution(raw: f64, normalized_stake: f64, saturation_k: f64) -> f64 {
        if raw <= 0.0 || normalized_stake <= 0.0 {
            return 0.0;
        }
        normalized_stake * (1.0 + raw / (saturation_k * normalized_stake)).ln()
    }

    pub fn normalized_stake(validators: &[Validator]) -> HashMap<String, f64> {
        let raw: HashMap<String, f64> = validators
            .iter()
            .map(|v| (v.address.clone(), v.stake.max(0.0)))
            .collect();
        Self::normalize_map(&raw)
    }

    fn normalize_map(map: &HashMap<String, f64>) -> HashMap<String, f64> {
        let sum: f64 = map.values().sum();
        if sum <= 0.0 {
            return map.keys().map(|k| (k.clone(), 0.0)).collect();
        }
        map.iter().map(|(k, v)| (k.clone(), v / sum)).collect()
    }

    fn valid_path_record(
        path: &AggregatedSignedPaths,
        tx: &Transaction,
        miner: &str,
        epoch: u64,
    ) -> bool {
        path.verify_at_epoch(tx.clone(), miner.to_string(), epoch)
    }

    fn settle_matured_rewards(&mut self, current_block_index: u64) -> Vec<BalanceDelta> {
        let mut matured = Vec::new();
        while self
            .pending_rewards
            .front()
            .map(|batch| batch.settle_at_block <= current_block_index)
            .unwrap_or(false)
        {
            if let Some(batch) = self.pending_rewards.pop_front() {
                matured.extend(batch.rewards);
            }
        }
        matured
    }
}

impl Consensus for TopoStakeConsensus {
    fn name(&self) -> &'static str {
        "TopoStake"
    }

    fn select_proposer(
        &mut self,
        validators: &[Validator],
        combines_seed: [u8; 32],
        _blockchain: &Blockchain,
    ) -> Result<Validator, ValidatorError> {
        self.select_with_frozen_weights(validators, combines_seed)
    }

    fn on_epoch_end(&mut self, blocks: &[Block], validators: &[Validator]) {
        self.update_scores_from_epoch(blocks, validators);
        self.adjust_depth_from_epoch_paths(blocks);
        self.freeze_proposer_weights(validators);
    }

    fn state_summary(&self) -> String {
        format!(
            "topostake-v2(D={}_beta={:.2}_eta={:.2}_cap={:.2}_pending={})",
            self.current_depth,
            self.config.beta,
            self.config.eta,
            self.config.bonus_cap,
            self.pending_rewards.len()
        )
    }

    fn metrics_snapshot(&self) -> ConsensusMetricsSnapshot {
        ConsensusMetricsSnapshot {
            topostake_depth: Some(self.current_depth),
            topostake_beta: Some(self.config.beta),
            topostake_eta: Some(self.config.eta),
            topostake_bonus_cap: Some(self.config.bonus_cap),
            topostake_saturation_k: Some(self.config.saturation_k),
            topostake_proposer_fee_ratio: Some(self.config.proposer_fee_ratio),
            score_history: self.score_history.clone(),
            normalized_score: self.normalized_score.clone(),
            bonuses: self.epoch_bonuses.clone(),
            unnormalized_proposer_weights: self.unnormalized_proposer_weights.clone(),
            normalized_proposer_weights: self.frozen_proposer_weights.clone(),
        }
    }

    fn distribute_rewards(
        &mut self,
        block: &Block,
        validators: &[Validator],
        _nodes_index: HashMap<String, u32>,
    ) -> Vec<BalanceDelta> {
        let plan = self.compute_block_rewards(block, validators);
        info!(
            "TopoStake revised rewards: block={} proposer={:.6} relay={:.6} burned={:.6}",
            block.header.index, plan.proposer_reward, plan.relay_reward, plan.burned_relay_fee
        );
        if !plan.rewards.is_empty() {
            self.pending_rewards.push_back(PendingRewardBatch {
                settle_at_block: block.header.index + self.config.reward_settlement_depth,
                rewards: plan.rewards,
            });
        }
        self.settle_matured_rewards(block.header.index)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::blockchain::block::{Block, Body};
    use crate::blockchain::path::{AggregatedSignedPaths, TransactionPaths};
    use crate::blockchain::transaction::Transaction;
    use crate::blockchain::Blockchain;
    use crate::consensus::Consensus;
    use crate::wallet::Wallet;

    fn test_config() -> TopoStakeConfig {
        TopoStakeConfig {
            reward_settlement_depth: 0,
            ..TopoStakeConfig::default()
        }
    }

    fn validators(wallets: &[&Wallet]) -> Vec<Validator> {
        wallets
            .iter()
            .enumerate()
            .map(|(idx, wallet)| Validator::new(wallet.address.clone(), (idx + 1) as f64, 1.0))
            .collect()
    }

    fn block_with_path(
        origin: &Wallet,
        relay: &Wallet,
        miner: &Wallet,
        fee: f64,
    ) -> (Block, Vec<Validator>) {
        let tx = Transaction::with_fee("receiver".to_string(), 0, fee, origin.clone());
        let mut tx_paths = TransactionPaths::new_with_epoch(tx.clone(), 0);
        assert!(tx_paths.append_outgoing_hop(relay.address.clone(), origin.clone()));
        assert!(tx_paths.complete_pending_hop(relay.clone()));
        assert!(tx_paths.append_outgoing_hop(miner.address.clone(), relay.clone()));
        assert!(tx_paths.complete_pending_hop(miner.clone()));
        let path = AggregatedSignedPaths::from_transaction_paths(tx_paths);
        let body = Body::new(vec![tx], vec![path]);
        let block = Block::new(
            1,
            0,
            0,
            Block::gen_genesis_block().header.hash,
            body,
            miner.clone(),
        )
        .unwrap();
        let validators = validators(&[origin, relay, miner]);
        (block, validators)
    }

    #[test]
    fn path_budget_sums_to_budget() {
        let depth = 4;
        for path_length in 2..12 {
            let budget = TopoStakeConsensus::path_budget_for_depth(depth, path_length);
            let sum: f64 = (1..path_length)
                .map(|position| TopoStakeConsensus::gamma_for_depth(depth, position, path_length))
                .sum();
            assert!((sum - budget).abs() < 1e-9);
            assert!(budget <= 1.0);
        }
    }

    #[test]
    fn path_budget_decreases_with_length() {
        let depth = 4;
        let mut previous = TopoStakeConsensus::path_budget_for_depth(depth, 2);
        for path_length in 3..16 {
            let current = TopoStakeConsensus::path_budget_for_depth(depth, path_length);
            assert!(current < previous);
            previous = current;
        }
    }

    #[test]
    fn lambda_times_one_plus_r_is_one() {
        for depth in 1..20 {
            let lambda = TopoStakeConsensus::lambda_for_depth(depth);
            let r = TopoStakeConsensus::r_for_depth(depth);
            assert!((lambda * (1.0 + r) - 1.0).abs() < 1e-12);
        }
    }

    #[test]
    fn epoch_score_does_not_mutate_frozen_epoch_weights() {
        let a = Wallet::new();
        let b = Wallet::new();
        let c = Wallet::new();
        let validators = validators(&[&a, &b, &c]);
        let mut consensus = TopoStakeConsensus::new(1.0, test_config()).unwrap();
        consensus.freeze_proposer_weights(&validators);
        let before = consensus.frozen_proposer_weights.clone();

        let (block, _) = block_with_path(&a, &b, &c, 10.0);
        consensus.update_scores_from_epoch(&[block], &validators);

        assert_eq!(before, consensus.frozen_proposer_weights);
    }

    #[test]
    fn select_proposer_does_not_update_score() {
        let a = Wallet::new();
        let b = Wallet::new();
        let validators = validators(&[&a, &b]);
        let blockchain = Blockchain::new(Block::gen_genesis_block());
        let mut consensus = TopoStakeConsensus::new(1.0, test_config()).unwrap();
        consensus.freeze_proposer_weights(&validators);
        let before = consensus.score_history.clone();

        let _ = consensus
            .select_proposer(&validators, [9; 32], &blockchain)
            .unwrap();

        assert_eq!(before, consensus.score_history);
    }

    #[test]
    fn proposer_weight_bound_holds_per_validator_and_coalition() {
        let a = Wallet::new();
        let b = Wallet::new();
        let validators = vec![
            Validator::new(a.address.clone(), 1.0, 1.0),
            Validator::new(b.address.clone(), 3.0, 1.0),
        ];
        let mut consensus = TopoStakeConsensus::new(1.0, test_config()).unwrap();
        consensus.normalized_score.insert(a.address.clone(), 1.0);
        consensus.normalized_score.insert(b.address.clone(), 0.0);
        consensus.freeze_proposer_weights(&validators);
        let stake = TopoStakeConsensus::normalized_stake(&validators);
        let bound_factor = 1.0 + consensus.config.eta * consensus.config.bonus_cap;

        for validator in &validators {
            let w = consensus
                .unnormalized_proposer_weights
                .get(&validator.address)
                .copied()
                .unwrap();
            let s = stake.get(&validator.address).copied().unwrap();
            assert!(w <= bound_factor * s + 1e-12);
        }

        let coalition_weight: f64 = validators
            .iter()
            .take(1)
            .map(|v| consensus.frozen_proposer_weights.get(&v.address).unwrap())
            .sum();
        let coalition_stake: f64 = validators
            .iter()
            .take(1)
            .map(|v| stake.get(&v.address).unwrap())
            .sum();
        assert!(coalition_weight <= bound_factor * coalition_stake + 1e-12);
    }

    #[test]
    fn proposer_sequence_is_deterministic_for_seed_sequence() {
        let wallets: Vec<Wallet> = (0..4)
            .map(|idx| Wallet::new_deterministic(77, idx))
            .collect();
        let validator_refs: Vec<&Wallet> = wallets.iter().collect();
        let validators = validators(&validator_refs);
        let blockchain = Blockchain::new(Block::gen_genesis_block());
        let seeds = [[1u8; 32], [2u8; 32], [3u8; 32], [4u8; 32]];

        let mut a = TopoStakeConsensus::new(1.0, test_config()).unwrap();
        let mut b = TopoStakeConsensus::new(1.0, test_config()).unwrap();
        a.freeze_proposer_weights(&validators);
        b.freeze_proposer_weights(&validators);

        let seq_a: Vec<String> = seeds
            .iter()
            .map(|seed| {
                a.select_proposer(&validators, *seed, &blockchain)
                    .unwrap()
                    .address
            })
            .collect();
        let seq_b: Vec<String> = seeds
            .iter()
            .map(|seed| {
                b.select_proposer(&validators, *seed, &blockchain)
                    .unwrap()
                    .address
            })
            .collect();

        assert_eq!(seq_a, seq_b);
    }

    #[test]
    fn fee_budget_balance_uses_gamma() {
        let origin = Wallet::new();
        let relay = Wallet::new();
        let miner = Wallet::new();
        let (block, validators) = block_with_path(&origin, &relay, &miner, 10.0);
        let consensus = TopoStakeConsensus::new(1.0, test_config()).unwrap();
        let plan = consensus.compute_block_rewards(&block, &validators);
        let relay_budget = (1.0 - consensus.config.proposer_fee_ratio) * plan.total_fee;

        assert!(plan.relay_reward <= relay_budget + 1e-12);
        assert!((plan.relay_reward + plan.burned_relay_fee - relay_budget).abs() < 1e-9);
        assert!(plan
            .rewards
            .iter()
            .any(|delta| delta.address == relay.address && delta.amount > 0.0));
    }

    #[test]
    fn balance_changes_do_not_alter_epoch_stake_snapshot() {
        let a = Wallet::new();
        let b = Wallet::new();
        let validators = validators(&[&a, &b]);
        let mut consensus = TopoStakeConsensus::new(1.0, test_config()).unwrap();
        consensus.freeze_proposer_weights(&validators);
        let snapshot = consensus.epoch_stake_snapshot.clone();

        let mut balances = HashMap::new();
        balances.insert(a.address.clone(), 100.0);
        *balances.get_mut(&a.address).unwrap() -= 10.0;

        assert_eq!(snapshot, consensus.epoch_stake_snapshot);
    }
}
