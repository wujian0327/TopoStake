use crate::blockchain::block::Block;
use crate::blockchain::Blockchain;
use crate::network::node::Node;
use crate::tools;
use crate::wallet::Wallet;
use clap::ValueEnum;
use log::error;
use rand::rngs::OsRng;
use rand::RngCore;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fmt;
use std::fmt::{Display, Formatter};

pub mod minotaur;
pub mod pos;
pub mod pow;
pub mod topostake;

#[derive(ValueEnum, Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum ConsensusType {
    POS,
    #[value(name = "topostake")]
    TopoStake,
    POW,
    MINOTAUR,
}

impl Display for ConsensusType {
    fn fmt(&self, f: &mut Formatter) -> fmt::Result {
        match *self {
            ConsensusType::POS => {
                write!(f, "pos")
            }
            ConsensusType::TopoStake => {
                write!(f, "topostake")
            }
            ConsensusType::POW => {
                write!(f, "pow")
            }
            ConsensusType::MINOTAUR => {
                write!(f, "minotaur")
            }
        }
    }
}

pub trait Consensus: Send + Sync {
    fn name(&self) -> &'static str;
    fn select_proposer(
        &mut self,
        validators: &[Validator],
        combines_seed: [u8; 32],
        blockchain: &Blockchain,
    ) -> Result<Validator, ValidatorError>;
    fn on_epoch_end(&mut self, blocks: &[Block], validators: &[Validator]);
    /// Refresh any epoch-frozen proposer state after an atomic stake transition.
    /// Consensus implementations that read the live validator slice need no work.
    fn on_stake_update(&mut self, _validators: &[Validator]) {}
    fn apply_block_feedback(&mut self, _block: &Block) {}
    fn state_summary(&self) -> String {
        String::new()
    }

    fn metrics_snapshot(&self) -> ConsensusMetricsSnapshot {
        ConsensusMetricsSnapshot::default()
    }

    /// 分配区块奖励到账户余额
    ///
    /// # 参数
    /// * `block` - 单个区块
    /// * `validators` - 所有验证者快照，经济 stake 不应在这里被修改
    ///
    /// # 说明
    /// - 默认实现不做任何操作，具体共识算法可覆盖此方法
    /// - 奖励以 balance delta 返回，由 WorldState 结算到账户余额
    fn distribute_rewards(
        &mut self,
        _block: &Block,
        _validators: &[Validator],
        _nodes_index: HashMap<String, u32>,
    ) -> Vec<BalanceDelta> {
        Vec::new()
    }

    fn next_slot(&mut self, _validators: &[Validator], _block_index: u64) {}
}

#[derive(Serialize, Deserialize, Debug, Clone, Default)]
pub struct ConsensusMetricsSnapshot {
    pub topostake_depth: Option<usize>,
    pub topostake_beta: Option<f64>,
    pub topostake_eta: Option<f64>,
    pub topostake_bonus_cap: Option<f64>,
    pub topostake_saturation_k: Option<f64>,
    pub topostake_proposer_fee_ratio: Option<f64>,
    pub topostake_score_floor_kappa: Option<f64>,
    pub topostake_bonus_zeta: Option<f64>,
    pub topostake_score_cost_reference: Option<f64>,
    pub topostake_active_score_epoch: Option<u64>,
    pub topostake_latest_score_epoch: Option<u64>,
    pub score_history: HashMap<String, f64>,
    pub latest_score_history: HashMap<String, f64>,
    pub normalized_score: HashMap<String, f64>,
    pub bonuses: HashMap<String, f64>,
    pub unnormalized_proposer_weights: HashMap<String, f64>,
    pub normalized_proposer_weights: HashMap<String, f64>,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq)]
pub struct BalanceDelta {
    pub address: String,
    pub amount: f64,
}

impl BalanceDelta {
    pub fn new(address: String, amount: f64) -> Self {
        BalanceDelta { address, amount }
    }
}

pub fn combine_seed(validators: Vec<Validator>, vdf_seeds: Vec<RandaoSeed>) -> [u8; 32] {
    let mut result = [0u8; 32];
    for v in vdf_seeds.clone() {
        if !validators
            .iter()
            .any(|validator| validator.address.eq(&v.address))
        {
            error!("Randao combine seed warning: this seed is not from validators");
            continue;
        }
        let valid = Wallet::verify_by_address(Vec::from(v.seed), v.signature, v.address);
        if valid {
            for i in 0..32 {
                result[i] ^= v.seed[i];
            }
        } else {
            error!("Randao combine seed warning: invalid seed");
        }
    }
    tools::Hasher::hash(Vec::from(result))
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct Validator {
    pub address: String,
    pub stake: f64,
    pub hash_power: f64,
}

impl Validator {
    pub fn new(address: String, stake: f64, hash_power: f64) -> Self {
        Validator {
            address,
            stake,
            hash_power,
        }
    }

    pub fn from_node(node: Node, stake: f64) -> Self {
        Validator::new(node.wallet.address.clone(), stake, node.hash_power)
    }

    pub fn from_json(json: Vec<u8>) -> Result<Validator, ValidatorError> {
        let randao_seed: Validator = serde_json::from_slice(json.as_slice())?;
        Ok(randao_seed)
    }

    pub fn to_json(&self) -> Vec<u8> {
        serde_json::to_vec(&self).unwrap()
    }
}

#[derive(Debug, PartialEq, Eq)]
pub enum ValidatorError {
    JSONError,
    NOValidatorError,
    NoWinner,
}
impl fmt::Display for ValidatorError {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        match *self {
            ValidatorError::JSONError => {
                write!(f, "Invalid Json Error")
            }

            ValidatorError::NOValidatorError => {
                write!(f, "NoValidatorError")
            }

            ValidatorError::NoWinner => {
                write!(f, "NoWinner")
            }
        }
    }
}
impl From<serde_json::error::Error> for ValidatorError {
    fn from(_: serde_json::error::Error) -> Self {
        ValidatorError::JSONError
    }
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct RandaoSeed {
    pub address: String,
    pub seed: [u8; 32],
    pub signature: String,
}

impl RandaoSeed {
    pub fn new(wallet: Wallet) -> Self {
        let seed = RandaoSeed::generate_seed();
        let signature = wallet.sign(Vec::from(seed));
        RandaoSeed {
            address: wallet.address,
            seed,
            signature,
        }
    }

    pub fn generate_seed() -> [u8; 32] {
        let mut rng = OsRng;
        let mut seed = [0u8; 32];
        rng.fill_bytes(&mut seed);
        seed
    }

    pub fn from_json(json: Vec<u8>) -> Result<RandaoSeed, ValidatorError> {
        let randao_seed: RandaoSeed = serde_json::from_slice(json.as_slice())?;
        Ok(randao_seed)
    }

    pub fn to_json(&self) -> Vec<u8> {
        serde_json::to_vec(&self).unwrap()
    }
}
