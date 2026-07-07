use blst::min_sig::SecretKey as BlsSecretKey;
use hex::encode;
use serde::Serialize;
use sha2::{Digest, Sha256};
use std::env;
use std::fs;
use std::path::Path;

const DEFAULT_CHAIN_ID: u64 = 7_032_030;
const DEFAULT_COUNT: u64 = 4;
const DEFAULT_SEED: &str = "topostake-prompt14-relay-key-v1";

#[derive(Serialize)]
struct PublicRegistry {
    version: u64,
    chain_id: u64,
    signing_domain: &'static str,
    note: &'static str,
    relays: Vec<PublicRelay>,
}

#[derive(Serialize)]
struct PublicRelay {
    node_id: String,
    node_index: u64,
    service_name: String,
    validator_index: u64,
    relay_address: String,
    payout_address: String,
    relay_pubkey: String,
}

#[derive(Serialize)]
struct PrivateKeyFile {
    version: u64,
    chain_id: u64,
    signing_domain: &'static str,
    note: &'static str,
    relays: Vec<PrivateRelay>,
}

#[derive(Serialize)]
struct PrivateRelay {
    node_id: String,
    node_index: u64,
    service_name: String,
    validator_index: u64,
    relay_address: String,
    payout_address: String,
    relay_pubkey: String,
    relay_private_key: String,
}

fn parse_arg(args: &[String], name: &str, default: &str) -> String {
    args.windows(2)
        .find(|pair| pair[0] == name)
        .map(|pair| pair[1].clone())
        .unwrap_or_else(|| default.to_string())
}

fn derive_key(seed: &str, chain_id: u64, validator_index: u64) -> BlsSecretKey {
    let mut hasher = Sha256::new();
    hasher.update(seed.as_bytes());
    hasher.update(chain_id.to_be_bytes());
    hasher.update(validator_index.to_be_bytes());
    let ikm = hasher.finalize();
    BlsSecretKey::key_gen(ikm.as_slice(), &[]).expect("valid BLS IKM")
}

fn derive_address(seed: &str, chain_id: u64, validator_index: u64, label: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(seed.as_bytes());
    hasher.update(chain_id.to_be_bytes());
    hasher.update(validator_index.to_be_bytes());
    hasher.update(label.as_bytes());
    let digest = hasher.finalize();
    format!("0x{}", encode(&digest[12..32]))
}

fn write_json<T: Serialize>(path: &str, value: &T) {
    if let Some(parent) = Path::new(path).parent() {
        fs::create_dir_all(parent).expect("create output directory");
    }
    let json = serde_json::to_string_pretty(value).expect("serialize json");
    fs::write(path, json + "\n").expect("write json");
}

fn main() {
    let args: Vec<String> = env::args().collect();
    let chain_id = parse_arg(&args, "--chain-id", &DEFAULT_CHAIN_ID.to_string())
        .parse::<u64>()
        .expect("numeric --chain-id");
    let count = parse_arg(&args, "--count", &DEFAULT_COUNT.to_string())
        .parse::<u64>()
        .expect("numeric --count");
    let seed = parse_arg(&args, "--seed", DEFAULT_SEED);
    let public_out = parse_arg(
        &args,
        "--public-out",
        "results/processed/topostake_relay_key_registry.json",
    );
    let private_out = parse_arg(
        &args,
        "--private-out",
        "results/raw/topostake_relay_keys_private.json",
    );

    let mut public_relays = Vec::with_capacity(count as usize);
    let mut private_relays = Vec::with_capacity(count as usize);

    for index in 0..count {
        let secret = derive_key(&seed, chain_id, index);
        let public = secret.sk_to_pk();
        let relay_pubkey = format!("0x{}", encode(public.to_bytes()));
        let relay_private_key = format!("0x{}", encode(secret.to_bytes()));
        let relay_address = derive_address(&seed, chain_id, index, "relay-address");
        let payout_address = derive_address(&seed, chain_id, index, "payout-address");
        let node_id = format!("node-{}", index);
        let service_name = format!("el-{}-geth-lighthouse", index + 1);

        public_relays.push(PublicRelay {
            node_id: node_id.clone(),
            node_index: index,
            service_name: service_name.clone(),
            validator_index: index,
            relay_address: relay_address.clone(),
            payout_address: payout_address.clone(),
            relay_pubkey: relay_pubkey.clone(),
        });
        private_relays.push(PrivateRelay {
            node_id,
            node_index: index,
            service_name,
            validator_index: index,
            relay_address,
            payout_address,
            relay_pubkey,
            relay_private_key,
        });
    }

    let public_registry = PublicRegistry {
        version: 1,
        chain_id,
        signing_domain: "TOPOSTAKE_TX_PATH_V1",
        note: "Public TopoStake relay BLS registry for Prompt 14 devnet verification. These keys are independent from Ethereum validator consensus keys.",
        relays: public_relays,
    };
    let private_keys = PrivateKeyFile {
        version: 1,
        chain_id,
        signing_domain: "TOPOSTAKE_TX_PATH_V1",
        note: "Devnet-only TopoStake relay private keys. Mount exactly one private key into the matching custom execution client; do not mount Ethereum validator keys.",
        relays: private_relays,
    };

    write_json(&public_out, &public_registry);
    write_json(&private_out, &private_keys);

    println!("wrote {}", public_out);
    println!("wrote {}", private_out);
}
