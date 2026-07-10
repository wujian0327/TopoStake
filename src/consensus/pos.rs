use std::collections::HashMap;

use crate::blockchain::block::Block;
use crate::blockchain::Blockchain;
use crate::consensus::{BalanceDelta, Consensus, Validator, ValidatorError};
use rand::prelude::StdRng;
use rand::{Rng, SeedableRng};

pub struct PosConsensus {
    base_reward: f64,
}

impl PosConsensus {
    pub fn new(base_reward: f64) -> Self {
        PosConsensus { base_reward }
    }

    fn select(
        validators: Vec<Validator>,
        combines_seeds: [u8; 32],
        _blockchain: Blockchain,
    ) -> Result<Validator, ValidatorError> {
        if validators.is_empty() {
            return Err(ValidatorError::NOValidatorError);
        }
        let total_stake: f64 = validators.iter().map(|v| v.stake).sum();
        let mut rng = StdRng::from_seed(combines_seeds);
        let random_value = rng.gen_range(0.0..total_stake);
        let mut accumulated_weight = 0f64;
        for validator in validators.clone() {
            accumulated_weight += validator.stake;
            if accumulated_weight > random_value {
                return Ok(validator);
            }
        }
        Err(ValidatorError::NOValidatorError)
    }
}

impl Consensus for PosConsensus {
    fn name(&self) -> &'static str {
        "POS"
    }

    fn select_proposer(
        &mut self,
        validators: &[Validator],
        combines_seed: [u8; 32],
        blockchain: &Blockchain,
    ) -> Result<Validator, ValidatorError> {
        Self::select(validators.to_vec(), combines_seed, blockchain.clone())
    }

    fn on_epoch_end(&mut self, _blocks: &[Block], _validators: &[Validator]) {}

    fn state_summary(&self) -> String {
        "pos".to_string()
    }

    fn distribute_rewards(
        &mut self,
        block: &Block,
        validators: &[Validator],
        _nodes_index: HashMap<String, u32>,
    ) -> Vec<BalanceDelta> {
        // PoS: 固定奖励 + 交易费用
        if let Some(validator) = validators.iter().find(|v| v.address == block.header.miner) {
            let base_reward = self.base_reward;
            let tx_fees: f64 = block.body.transactions.iter().map(|tx| tx.fee).sum();
            let total_reward = base_reward + tx_fees;
            log::info!(
                "PoS: Miner {} received balance reward: base={:.6} + fees={:.6} = {:.6}",
                validator.address,
                base_reward,
                tx_fees,
                total_reward
            );
            return vec![BalanceDelta::new(validator.address.clone(), total_reward)];
        }
        Vec::new()
    }
}
