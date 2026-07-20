use crate::tools;
use crate::tools::get_timestamp;
use crate::wallet::Wallet;
use hex::encode;
use serde::{Deserialize, Serialize};

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct Transaction {
    pub from: String,
    pub to: String,
    pub amount: i64,
    pub fee: f64, // 交易手续费
    /// Protocol-visible cost that is unconditionally irrecoverable by the payer.
    /// This is distinct from `fee`, which is split between proposer and relayers.
    #[serde(default)]
    pub irrecoverable_cost: f64,
    pub hash: String,
    pub signature: String,
    pub timestamp: u64,
    pub data: Vec<u8>,
}

impl Transaction {
    pub fn new(to: String, amount: i64, wallet: Wallet) -> Transaction {
        Self::with_fee(to, amount, 1.0, wallet)
    }

    pub fn with_fee(to: String, amount: i64, fee: f64, wallet: Wallet) -> Transaction {
        Self::with_costs(to, amount, fee, fee, wallet)
    }

    pub fn with_costs(
        to: String,
        amount: i64,
        fee: f64,
        irrecoverable_cost: f64,
        wallet: Wallet,
    ) -> Transaction {
        let from = wallet.address.clone();

        let mut t = Transaction {
            from: from.clone(),
            to: to.clone(),
            amount,
            fee,
            irrecoverable_cost,
            hash: "".to_string(),
            signature: "".to_string(),
            timestamp: get_timestamp(),
            data: Vec::new(),
        };
        let t_json = serde_json::to_string(&t).unwrap();
        let hash = tools::Hasher::hash(t_json.as_bytes().to_vec());
        let signature = wallet.sign(hash.to_vec());
        let hash = encode(hash);
        t.hash = hash;
        t.signature = signature;
        t
    }

    pub fn verify(&self) -> bool {
        let from = self.from.clone();
        let to = self.to.clone();
        let t = Transaction {
            from: from.clone(),
            to: to.clone(),
            amount: self.amount,
            fee: self.fee,
            irrecoverable_cost: self.irrecoverable_cost,
            hash: "".to_string(),
            signature: "".to_string(),
            timestamp: self.timestamp,
            data: Vec::new(),
        };
        let t_json = serde_json::to_string(&t).unwrap();
        let hash = tools::Hasher::hash(t_json.as_bytes().to_vec());
        if self.hash != encode(hash) {
            return false;
        }
        Wallet::verify_by_address(Vec::from(hash), self.signature.clone(), from)
    }

    pub fn bytes(&self) -> u64 {
        let hash = self.hash.as_bytes().len() as u64;
        let from = self.from.as_bytes().len() as u64;
        let to = self.to.as_bytes().len() as u64;
        let signature = self.signature.as_bytes().len() as u64;
        let amount = 8;
        let timestamp = 8;
        let fee = 8;
        let irrecoverable_cost = 8;
        hash + amount
            + fee
            + irrecoverable_cost
            + timestamp
            + from
            + to
            + signature
            + self.data.len() as u64
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use log::info;

    #[test]
    fn test_transaction() {
        let wallet = Wallet::new();
        let transaction = Transaction::new("123".to_string(), 32, wallet);
        info!("{:#?}", transaction);
        assert!(transaction.verify());
    }
}
