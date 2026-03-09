use crate::blockchain::block::Block;
use crate::blockchain::Blockchain;
use crate::consensus::{Consensus, Validator, ValidatorError};
use log::{debug, info};
use rand::prelude::StdRng;
use rand::{Rng, SeedableRng};
use std::collections::HashMap;

pub struct TopoStakeConsensus {
    d: usize,
    base_reward: f64,
    score_history: HashMap<String, f64>,
    beta: f64,
    k_sat: f64,
    k_base: f64,
    omega: f64,
}

impl TopoStakeConsensus {
    pub fn new(initial_d: usize, base_reward: f64, omega: f64, beta: f64) -> Self {
        TopoStakeConsensus {
            d: initial_d,
            base_reward,
            score_history: HashMap::new(),
            beta,        // EMA factor: smaller beta = longer memory
            k_sat: 1.0,  // Saturation scale
            k_base: 1.0, // Saturation base
            omega,
        }
    }

    /// Set the consensus weight parameter (omega)
    pub fn set_omega(&mut self, omega: f64) {
        self.omega = omega.max(0.0).min(1.0);
    }

    /// Compute position weights: alpha_k(L) = 2(L - k + 1) / (L(L + 1))
    fn compute_position_weight(position: usize, path_length: usize) -> f64 {
        if path_length == 0 || position > path_length || position == 0 {
            return 0.0;
        }
        2.0 * (path_length - position + 1) as f64 / (path_length * (path_length + 1)) as f64
    }

    fn select_internal(
        &mut self,
        validators: Vec<Validator>,
        combines_seeds: [u8; 32],
        blockchain: Blockchain,
    ) -> Result<Validator, ValidatorError> {
        let last_block = blockchain.get_last_block();
        let paths = last_block.get_all_paths();

        // Step 1: Calculate network contribution (Score(n,t)) with temporal smoothing
        let slot_contribution = self.cal_slot_contribution(&paths, &validators);
        self.update_score_history(&slot_contribution, &validators);

        debug!(
            "Score history: {}",
            serde_json::to_string(&self.score_history)?
        );

        // Step 2: Calculate normalized stake and contribution
        let s_real_map: HashMap<String, f64> = validators
            .iter()
            .map(|x| (x.address.to_string(), x.stake))
            .collect();

        let normalized_stake = self.normalize_map(&s_real_map);
        let normalized_contribution = self.normalize_map(&self.score_history);

        // Step 3: Calculate virtual stake using hybrid formula
        let s_virtual_map =
            self.cal_virtual_stake(&s_real_map, &normalized_stake, &normalized_contribution);

        debug!("Virtual stake: {}", serde_json::to_string(&s_virtual_map)?);

        // Step 4: Select proposer probabilistically using virtual stake
        let validators_with_virtual_stake: Vec<(String, f64)> = validators
            .iter()
            .map(|x| {
                (
                    x.address.clone(),
                    *s_virtual_map.get(&x.address).unwrap_or(&0.0),
                )
            })
            .collect();

        let total_virtual_stake: f64 = validators_with_virtual_stake.iter().map(|(_, vs)| vs).sum();

        let mut rng = StdRng::from_seed(combines_seeds);
        let random_value = if total_virtual_stake < 0.0001 {
            0.0
        } else {
            rng.gen_range(0.0..total_virtual_stake.max(0.0001))
        };

        let mut accumulated_weight = 0.0;
        for (address, virtual_stake) in validators_with_virtual_stake {
            accumulated_weight += virtual_stake;
            if accumulated_weight >= random_value {
                // Find the original validator to return
                if let Some(validator) = validators.iter().find(|v| v.address == address) {
                    info!(
                        "Proposer {} elected with virtual stake {:.6}",
                        validator.address, virtual_stake
                    );
                    return Ok(validator.clone());
                }
            }
        }

        Err(ValidatorError::NOValidatorError)
    }

    /// Normalize a map so all values sum to 1
    fn normalize_map(&self, map: &HashMap<String, f64>) -> HashMap<String, f64> {
        let sum: f64 = map.values().sum();
        if sum == 0.0 {
            return map.clone();
        }
        map.iter().map(|(k, v)| (k.clone(), v / sum)).collect()
    }

    /// Calculate path propagation value: c(p) = 1 if L(p) <= D, else 1/(1 + (L(p) - D))
    fn compute_path_value(&self, path_length: usize) -> f64 {
        if path_length <= self.d {
            1.0
        } else {
            1.0 / (1.0 + (path_length - self.d) as f64)
        }
    }

    /// Calculate raw slot contribution for a node from all paths in this slot
    /// C_slot(n,t) = K_sat * log(1 + sum(r(n,p)) / K_base)
    fn cal_slot_contribution(
        &self,
        paths: &[Vec<String>],
        validators: &[Validator],
    ) -> HashMap<String, f64> {
        let mut raw_scores: HashMap<String, f64> = HashMap::new();

        // Step 1: Calculate atomic scores for all paths
        for path in paths {
            if path.is_empty() {
                continue;
            }

            // Remove miner node (last node in path)
            let path_nodes = &path[..path.len() - 1];
            let path_length = path_nodes.len();

            if path_length == 0 {
                continue;
            }

            // Calculate path value
            let c_p = self.compute_path_value(path_length);

            // Calculate total real stake in this path
            let sum_stake: f64 = path_nodes
                .iter()
                .map(|n| Self::get_real_stake(n, validators))
                .sum();

            if sum_stake == 0.0 {
                continue;
            }

            // Calculate atomic score for each node in this path
            for (position, node) in path_nodes.iter().enumerate() {
                let k_pos = position + 1; // 1-indexed position
                let alpha_k = Self::compute_position_weight(k_pos, path_length);
                let s_r = Self::get_real_stake(node, validators);
                let s_hat = s_r / sum_stake; // Normalized stake in this path

                let atomic_score = c_p * alpha_k * s_hat;
                *raw_scores.entry(node.clone()).or_insert(0.0) += atomic_score;
            }
        }

        // Step 2: Apply logarithmic saturation to prevent spam
        // C_slot(n,t) = K_sat * log(1 + raw_score / K_base)
        let mut slot_contribution: HashMap<String, f64> = HashMap::new();
        for (node, raw_score) in raw_scores {
            let saturated = self.k_sat * (1.0 + raw_score / self.k_base).ln();
            slot_contribution.insert(node, saturated);
        }

        slot_contribution
    }

    /// Update temporal score history using EMA
    /// Score(n,t) = beta * C_slot(n,t) + (1 - beta) * Score(n,t-1)
    fn update_score_history(
        &mut self,
        slot_contribution: &HashMap<String, f64>,
        validators: &[Validator],
    ) {
        for validator in validators {
            let current_slot = slot_contribution.get(&validator.address).unwrap_or(&0.0);
            let previous_score = self.score_history.get(&validator.address).unwrap_or(&0.0);

            let new_score = self.beta * current_slot + (1.0 - self.beta) * previous_score;
            self.score_history
                .insert(validator.address.clone(), new_score);
        }
    }

    /// Get real stake of a node from validator list
    fn get_real_stake(node: &str, validators: &[Validator]) -> f64 {
        validators
            .iter()
            .find(|v| v.address == node)
            .map(|v| v.stake)
            .unwrap_or(0.0)
    }

    /// Calculate virtual stake using hybrid formula:
    /// S_v(n,t) = omega * hat_C(n,t) + (1 - omega) * hat_S_r(n)
    fn cal_virtual_stake(
        &self,
        real_stake_map: &HashMap<String, f64>,
        normalized_stake: &HashMap<String, f64>,
        normalized_contribution: &HashMap<String, f64>,
    ) -> HashMap<String, f64> {
        real_stake_map
            .iter()
            .map(|(node, _real_stake)| {
                let hat_c = normalized_contribution.get(node).unwrap_or(&0.0);
                let hat_s = normalized_stake.get(node).unwrap_or(&0.0);

                // S_v(n,t) = omega * hat_C + (1 - omega) * hat_S_r
                let s_v = self.omega * hat_c + (1.0 - self.omega) * hat_s;
                (node.clone(), s_v)
            })
            .collect()
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
        blockchain: &Blockchain,
    ) -> Result<Validator, ValidatorError> {
        self.select_internal(validators.to_vec(), combines_seed, blockchain.clone())
    }

    fn on_epoch_end(&mut self, blocks: &[Block]) {
        let paths: Vec<Vec<String>> = blocks.iter().flat_map(|b| b.get_all_paths()).collect();
        self.adjust_d(&paths);
        // self.set_omega(self.omega + 0.1);
    }

    fn state_summary(&self) -> String {
        format!(
            "pog(D={}_omega={:.2}_beta={:.2})",
            self.d, self.omega, self.beta
        )
    }

    fn distribute_rewards(
        &self,
        block: &Block,
        validators: &mut [Validator],
        nodes_index: HashMap<String, u32>,
    ) {
        let block_reward = self.base_reward;
        let total_fees: f64 = block.body.transactions.iter().map(|tx| tx.fee).sum();

        let paths: Vec<Vec<String>> = block.get_all_paths();
        if paths.is_empty() {
            info!(
                "POG: No paths in block {}, miner gets all fees {:.6}",
                block.header.index, total_fees
            );
            if let Some(validator) = validators
                .iter_mut()
                .find(|v| v.address == block.header.miner)
            {
                validator.stake += block_reward + total_fees;
                info!(
                    "POG: Miner {} received reward: {:.6}, new stake: {:.6}",
                    validator.address,
                    block_reward + total_fees,
                    validator.stake
                );
            }
            return;
        }

        let avg_path_length = paths
            .iter()
            .map(|p| p.len().saturating_sub(1) as f64)
            .sum::<f64>()
            / paths.len() as f64;

        let penalty_factor = if avg_path_length > self.d as f64 {
            let ratio = self.d as f64 / avg_path_length;
            ratio * ratio
        } else {
            1.0
        };

        debug!(
            "POG: rewards distribution - total_fees={:.6}, avg_path_length={:.2}, penalty_factor={:.6}",
            total_fees, avg_path_length, penalty_factor
        );
        let s_real_map: HashMap<String, f64> = validators
            .iter()
            .map(|v| (v.address.clone(), v.stake))
            .collect();
        let normalized_stake = self.normalize_map(&s_real_map);
        let normalized_contribution = self.normalize_map(&self.score_history);
        let virtual_stake_map =
            self.cal_virtual_stake(&s_real_map, &normalized_stake, &normalized_contribution);

        let miner_share = block_reward + 0.5 * total_fees * penalty_factor;

        if let Some(validator) = validators
            .iter_mut()
            .find(|v| v.address == block.header.miner)
        {
            validator.stake += miner_share;
            let index = nodes_index.get(&validator.address).unwrap_or(&0);
            let virtual_stake = virtual_stake_map.get(&validator.address).unwrap_or(&0.0);
            info!(
                "POG: Miner node[{}]   received reward: {:.6} (virtual_stake: {:.6}), new stake: {:.6}",
                index, miner_share, virtual_stake, validator.stake
            );
        }

        let network_pool = total_fees * (1.0 - 0.5 * penalty_factor);

        for validator in validators.iter_mut() {
            if validator.address == block.header.miner {
                continue;
            }
            let virtual_stake = virtual_stake_map.get(&validator.address).unwrap_or(&0.0);
            let network_reward = network_pool * virtual_stake;
            validator.stake += network_reward;
            if network_reward > 0.0 {
                let index = nodes_index.get(&validator.address).unwrap_or(&0);
                debug!(
                    "POG: Node[{}] received network reward: {:.6} (virtual_stake: {:.6}), new stake: {:.6}",
                    index, network_reward, virtual_stake, validator.stake
                );
            }
        }
    }
}

impl TopoStakeConsensus {
    fn adjust_d(&mut self, paths: &[Vec<String>]) {
        if paths.is_empty() {
            return;
        }
        let p_ave = paths
            .iter()
            .map(|path| path.len().saturating_sub(1))
            .sum::<usize>() as f64
            / paths.len() as f64;
        let target = p_ave.ceil() as usize;
        if self.d > target {
            self.d -= 1;
        } else if self.d < target {
            self.d += 1;
        }
    }
}

#[cfg(test)]
mod tests {
    use crate::blockchain::path::{AggregatedSignedPaths, TransactionPaths};
    use crate::blockchain::transaction::Transaction;
    use crate::consensus::topostake::TopoStakeConsensus;
    use crate::consensus::Validator;
    use crate::wallet::Wallet;
    use log::info;

    #[tokio::test]
    async fn test_contribution_calculation() {
        let _ = env_logger::builder()
            .filter_level(log::LevelFilter::Debug)
            .is_test(true)
            .try_init();

        let wallet = Wallet::new();
        let wallet2 = Wallet::new();
        let wallet3 = Wallet::new();
        let miner = Wallet::new();

        let transaction = Transaction::new("123".to_string(), 32, wallet.clone());
        let mut transaction_paths = TransactionPaths::new(transaction.clone());
        transaction_paths.add_path(wallet2.address.clone(), wallet.clone());
        transaction_paths.add_path(wallet3.address.clone(), wallet2.clone());
        transaction_paths.add_path(miner.address.clone(), wallet3.clone());

        let aggregated_signed_paths =
            AggregatedSignedPaths::from_transaction_paths(transaction_paths);

        let paths = vec![aggregated_signed_paths.paths];

        let v1 = Validator::new(wallet.address, 1.0, 1.0);
        let v2 = Validator::new(wallet2.address, 2.0, 1.0);
        let v3 = Validator::new(wallet3.address, 3.0, 1.0);
        let miner_v = Validator::new(miner.address, 4.0, 1.0);
        let validators = vec![v1, v2, v3, miner_v];

        let mut pog = TopoStakeConsensus::new(3, 1.0, 1.0, 0.5);

        // Test with pure PoS (omega = 0)
        pog.set_omega(0.0);
        let slot_contribution = pog.cal_slot_contribution(&paths, &validators);
        info!("Slot contribution (omega=0): {:#?}", slot_contribution);

        pog.update_score_history(&slot_contribution, &validators);
        info!("Score history: {:#?}", pog.score_history);

        let s_real_map: std::collections::HashMap<String, f64> = validators
            .iter()
            .map(|x| (x.address.to_string(), x.stake))
            .collect();

        let normalized_stake = pog.normalize_map(&s_real_map);
        let normalized_contribution = pog.normalize_map(&pog.score_history);

        let s_v = pog.cal_virtual_stake(&s_real_map, &normalized_stake, &normalized_contribution);
        info!("Virtual stake (omega=0, pure PoS): {:#?}", s_v);

        // Test with hybrid consensus (omega = 0.5)
        pog.set_omega(0.5);
        let s_v_hybrid =
            pog.cal_virtual_stake(&s_real_map, &normalized_stake, &normalized_contribution);
        info!("Virtual stake (omega=0.5, hybrid): {:#?}", s_v_hybrid);

        // Verify that virtual stakes sum to 1
        let sum: f64 = s_v_hybrid.values().sum();
        info!("Sum of virtual stakes: {}", sum);
        assert!((sum - 1.0).abs() < 1e-6, "Virtual stakes should sum to 1");
    }
}
