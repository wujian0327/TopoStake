use crate::tools::Hasher;
use blst::min_sig::{AggregateSignature, SecretKey as BlsSecretKey};
use blst::min_sig::{PublicKey as BlsPublicKey, Signature};
use blst::BLST_ERROR;
use dashmap::DashMap;
use hex::{decode, encode, FromHexError};
use lazy_static::lazy_static;
use log::info;
use secp256k1::ecdsa::{RecoverableSignature, RecoveryId};
use secp256k1::{Message, PublicKey, Secp256k1, SecretKey};
use std::fmt;
use std::num::ParseIntError;
use std::str::FromStr;

// Trusted BLS relay-key registry abstraction.
//
// A production deployment should register relay keys with proof-of-possession.
// The simulator derives BLS keys from local wallets and inserts them into this
// trusted registry at wallet creation time. Path verification never accepts an
// unregistered key; missing registry entries make the proof invalid.
lazy_static! {
    static ref BLS_PUB_KEY_MAP: DashMap<String, BlsPublicKey> = DashMap::new();
}

pub fn get_bls_pub_key(address: String) -> Option<BlsPublicKey> {
    BLS_PUB_KEY_MAP.get(&address).map(|entry| *entry.value())
}

pub fn register_trusted_bls_pub_key(address: String, public_key: BlsPublicKey) {
    BLS_PUB_KEY_MAP.insert(address, public_key);
}

pub fn insert_bls_pub_key(address: String, public_key: BlsPublicKey) {
    register_trusted_bls_pub_key(address, public_key);
}

#[derive(Debug, Clone)]
pub struct Wallet {
    pub secret_key: SecretKey,
    pub public_key: PublicKey,
    // blsKey用于对网络贡献度和pos投票进行签名
    pub bls_private_key: BlsSecretKey,
    pub bls_public_key: BlsPublicKey,
    pub address: String,
}

impl Default for Wallet {
    fn default() -> Self {
        Self::new()
    }
}

impl Wallet {
    pub fn new() -> Wallet {
        let secp = Secp256k1::new();

        let (secret_key, public_key) = secp.generate_keypair(&mut rand::thread_rng());
        let address = Wallet::public_key_to_address(public_key);
        let bls_private_key =
            BlsSecretKey::key_gen(secret_key.secret_bytes().as_slice(), &[]).unwrap();
        let bls_public_key = bls_private_key.sk_to_pk();
        register_trusted_bls_pub_key(address.clone(), bls_public_key);
        Wallet {
            secret_key,
            public_key,
            bls_private_key,
            bls_public_key,
            address,
        }
    }

    pub fn new_deterministic(seed: u64, index: u32) -> Wallet {
        let mut combined = seed.to_be_bytes().to_vec();
        combined.extend_from_slice(&index.to_be_bytes());
        let hash = Hasher::hash(combined);

        let secret_key = SecretKey::from_slice(&hash).expect("32 bytes");
        let secp = Secp256k1::new();
        let public_key = secret_key.public_key(&secp);
        let address = Wallet::public_key_to_address(public_key);

        let bls_private_key =
            BlsSecretKey::key_gen(secret_key.secret_bytes().as_slice(), &[]).unwrap();
        let bls_public_key = bls_private_key.sk_to_pk();
        register_trusted_bls_pub_key(address.clone(), bls_public_key);
        Wallet {
            secret_key,
            public_key,
            bls_private_key,
            bls_public_key,
            address,
        }
    }

    #[allow(dead_code)]
    fn from_secret_key_string(mut secret_key: String) -> Result<Wallet, WalletError> {
        if secret_key.len() == 66 {
            secret_key = secret_key[2..].to_string();
        }
        if secret_key.len() != 64 {
            return Err(WalletError::InvalidPrivateKeyString);
        }
        let secret_key = match SecretKey::from_str(secret_key.as_str()) {
            Ok(sk) => sk,
            Err(_e) => {
                return Err(WalletError::InvalidPrivateKeyString);
            }
        };
        let secp = Secp256k1::new();
        let public_key = secret_key.public_key(&secp);
        let address = Wallet::public_key_to_address(public_key);

        let bls_private_key =
            BlsSecretKey::key_gen(secret_key.secret_bytes().as_slice(), &[]).unwrap();
        let bls_public_key = bls_private_key.sk_to_pk();
        Ok(Wallet {
            secret_key,
            public_key,
            bls_private_key,
            bls_public_key,
            address,
        })
    }

    fn public_key_to_address(public_key: PublicKey) -> String {
        // 忽略第一个字节（表示前缀）
        let public_key_bytes = &public_key.serialize_uncompressed()[1..];

        //sha3
        let hash_result = Hasher::hash(public_key_bytes.to_vec());

        // 以太坊地址（最后 20 字节）
        let address = &hash_result[12..];
        format!("0x{}", encode(address))
    }

    pub fn sign(&self, msg: Vec<u8>) -> String {
        //hash first
        let hash_result = Hasher::hash(msg);
        let message = Message::from_digest(hash_result);

        //sign recoverable
        let secp = Secp256k1::new();
        let recoverable_signature = secp.sign_ecdsa_recoverable(&message, &self.secret_key);

        //以太坊签名(r, s, v), v = 27 + RecoveryId
        let (recovery_id, signature_bytes) = recoverable_signature.serialize_compact();
        let v = 27 + recovery_id as i32;
        format!("0x{}{:02x}", encode(signature_bytes), v)
    }

    pub fn sign_by_bls(&self, msg: Vec<u8>) -> String {
        let sign = self.bls_private_key.sign(msg.as_slice(), &[], &[]);
        format!("0x{}", encode(sign.to_bytes()))
    }

    fn recover_pubkey(msg: Vec<u8>, mut signature: String) -> Result<PublicKey, WalletError> {
        //使用签名和消息恢复公钥
        if signature.starts_with("0x") {
            signature = signature[2..].to_string();
        }
        let hash_result = Hasher::hash(msg);
        let message = Message::from_digest(hash_result);

        // 分解签名为 r, s 和 v
        let signature_bytes = decode(&signature[0..128])?;

        let v = u8::from_str_radix(&signature[128..130], 16)?;

        // 生成可恢复签名对象
        let recovery_id = RecoveryId::try_from((v - 27) as i32).expect("Valid RecoveryId");
        let recoverable_signature =
            RecoverableSignature::from_compact(&signature_bytes, recovery_id)
                .expect("Valid signature");

        // 从签名恢复公钥
        let secp = Secp256k1::new();
        let recovered_public_key = secp
            .recover_ecdsa(&message, &recoverable_signature)
            .expect("Recovered public key");
        Ok(recovered_public_key)
    }

    pub fn verify(&self, msg: Vec<u8>, signature: String) -> bool {
        //使用签名和消息恢复公钥，再判断公钥是否一致
        match Wallet::recover_pubkey(msg, signature) {
            Ok(recovered_public_key) => {
                // 验证公钥匹配
                recovered_public_key == self.public_key
            }
            Err(_) => false,
        }
    }

    #[allow(dead_code)]
    fn verify_bls(&self, msg: Vec<u8>, signature: String) -> bool {
        let signature = match Wallet::bls_signature_from_string(signature) {
            Ok(signature) => signature,
            Err(_e) => {
                return false;
            }
        };
        matches!(
            signature.verify(true, msg.as_slice(), &[], &[], &self.bls_public_key, true),
            BLST_ERROR::BLST_SUCCESS
        )
    }

    pub fn verify_by_address(msg: Vec<u8>, signature: String, address: String) -> bool {
        //使用签名和消息恢复公钥
        //再使用公钥生成地址，判断地址是否一致
        let pk = match Wallet::recover_pubkey(msg, signature) {
            Ok(pk) => pk,
            Err(_) => {
                return false;
            }
        };
        let recovery_address = Wallet::public_key_to_address(pk);
        recovery_address == address
    }

    pub fn verify_bls_with_pk(msg: Vec<u8>, signature: String, public_key: BlsPublicKey) -> bool {
        let signature = match Wallet::bls_signature_from_string(signature) {
            Ok(signature) => signature,
            Err(_e) => {
                return false;
            }
        };
        matches!(
            signature.verify(true, msg.as_slice(), &[], &[], &public_key, true),
            BLST_ERROR::BLST_SUCCESS
        )
    }

    pub fn bls_signature_from_string(mut signature: String) -> Result<Signature, WalletError> {
        if signature.starts_with("0x") {
            signature = signature[2..].to_string();
        }
        let signature_bytes = decode(&signature)?;

        Signature::from_bytes(signature_bytes.as_slice())
            .map_err(|_| WalletError::InvalidSignature)
    }

    pub fn bls_aggregated_sign(signatures: Vec<Signature>) -> String {
        if signatures.is_empty() {
            return String::new();
        }
        let mut agg_sig = AggregateSignature::from_signature(&signatures[0]);
        for sig in &signatures[1..] {
            agg_sig.add_signature(sig, true).unwrap();
        }
        format!("0x{}", encode(agg_sig.to_signature().to_bytes()))
    }

    pub fn bls_aggregated_verify(
        messages: Vec<Vec<u8>>,
        public_keys: Vec<BlsPublicKey>,
        signature: String,
    ) -> bool {
        let signature = match Wallet::bls_signature_from_string(signature) {
            Ok(signature) => signature,
            Err(_) => {
                return false;
            }
        };
        Wallet::bls_aggregated_verify_parsed(messages, public_keys, signature)
    }

    pub fn bls_aggregated_verify_parsed(
        messages: Vec<Vec<u8>>,
        public_keys: Vec<BlsPublicKey>,
        signature: Signature,
    ) -> bool {
        let messages: Vec<&[u8]> = messages.iter().map(|m| m.as_slice()).collect();
        let public_keys: Vec<&blst::min_sig::PublicKey> = public_keys.iter().collect();
        matches!(
            signature.aggregate_verify(
                true,
                messages.as_slice(),
                &[],
                public_keys.as_slice(),
                true,
            ),
            BLST_ERROR::BLST_SUCCESS
        )
    }

    #[allow(dead_code)]
    pub(crate) fn print(&self) {
        info!("Secret Key: 0x{}", encode(self.secret_key.secret_bytes()));
        let public_key_bytes = &self.public_key.serialize_uncompressed()[1..];
        info!("Public Key: 0x{}", encode(public_key_bytes));
        info!("Address: {}", &self.address);
    }
}

#[derive(Debug)]
pub enum WalletError {
    InvalidPrivateKeyString,
    InvalidSignature,
}

impl fmt::Display for WalletError {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        match *self {
            WalletError::InvalidPrivateKeyString => write!(f, "Invalid Private Key String Error"),
            WalletError::InvalidSignature => write!(f, "Invalid Signature Error"),
        }
    }
}

impl From<FromHexError> for WalletError {
    fn from(_: FromHexError) -> Self {
        WalletError::InvalidSignature
    }
}

impl From<ParseIntError> for WalletError {
    fn from(_: ParseIntError) -> Self {
        WalletError::InvalidSignature
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn new_wallet() {
        let wallet = Wallet::new();
        wallet.print();
    }

    //private_key,public_key,address
    const KEYPAIR:(&str,&str,&str) = (
        "0x862fe916208e8f6820c773e290c30ed1f04f2e283644f2ca2668335a3e9f569f",
        "0x807114576f8004aaaebff87f2e631662f1080e4fc07ff70ca7c43d5150fa069f0d3c0e0c30156ef5ebebf14efdbcc915824acc494f90e725e5fad600fd1966df",
        "0x62f6f90ee8955ebec3573841c932c64cedc54a1f"
    );

    #[test]
    fn new_wallet_from_secret_key_string() {
        let wallet = Wallet::from_secret_key_string(KEYPAIR.0.to_string()).unwrap();
        assert_eq!(KEYPAIR.2.to_string(), wallet.address);
    }

    #[test]
    fn test_verify_sign() {
        let message = b"hello world";
        let wallet = Wallet::from_secret_key_string(KEYPAIR.0.to_string()).unwrap();
        let signature = wallet.sign(message.to_vec());
        assert!(wallet.verify(message.to_vec(), signature));
    }

    #[test]
    fn test_verify_sign_by_address() {
        let message = b"hello world";
        let wallet = Wallet::from_secret_key_string(KEYPAIR.0.to_string()).unwrap();
        let signature = wallet.sign(message.to_vec());
        assert!(Wallet::verify_by_address(
            message.to_vec(),
            signature,
            wallet.address
        ));
    }

    #[test]
    fn test_verify_bls_sign() {
        let message = b"hello world";
        let wallet = Wallet::from_secret_key_string(KEYPAIR.0.to_string()).unwrap();
        let signature = wallet.sign_by_bls(message.to_vec());
        assert!(wallet.verify_bls(message.to_vec(), signature));
    }

    #[test]
    fn test_verify_bls_aggregated_sign() {
        let message1 = "hello world1";
        let message2 = "hello world2";
        let wallet1 = Wallet::new();
        let wallet2 = Wallet::new();
        let mut signatures = Vec::new();
        let mut public_keys = Vec::new();
        let signature1 = wallet1.sign_by_bls(message1.as_bytes().to_vec());
        signatures.push(signature1);
        let signature2 = wallet2.sign_by_bls(message2.as_bytes().to_vec());
        signatures.push(signature2);
        public_keys.push(wallet1.bls_public_key);
        public_keys.push(wallet2.bls_public_key);
        let signatures: Vec<Signature> = signatures
            .iter()
            .map(|s| Wallet::bls_signature_from_string(s.clone()).unwrap())
            .collect();
        let aggregated_signature = Wallet::bls_aggregated_sign(signatures);
        let messages = vec![message1.as_bytes().to_vec(), message2.as_bytes().to_vec()];
        let result = Wallet::bls_aggregated_verify(messages, public_keys, aggregated_signature);
        assert!(result);
    }
}
