use crate::consensus_context::ConsensusContext;
use errors::{
    BlockOperationError, BlockProcessingError, ExecutionPayloadBidInvalid, HeaderInvalid,
};
use rayon::prelude::*;
use safe_arith::{ArithError, SafeArith};
use serde::Deserialize;
use serde_json::Value;
use signature_sets::{
    block_proposal_signature_set, execution_payload_bid_signature_set,
    get_builder_pubkey_from_state, get_pubkey_from_state, randao_signature_set,
};
use std::{
    borrow::Cow,
    collections::{HashMap, HashSet},
    io::{Read, Write},
    net::{IpAddr, TcpStream, ToSocketAddrs, UdpSocket},
    sync::{OnceLock, RwLock},
    time::{Duration, Instant},
};
use tree_hash::TreeHash;
use typenum::Unsigned;
use types::{consts::gloas::BUILDER_INDEX_SELF_BUILD, *};

pub use self::verify_attester_slashing::{
    get_slashable_indices, get_slashable_indices_modular, verify_attester_slashing,
};
pub use self::verify_proposer_slashing::verify_proposer_slashing;
pub use altair::sync_committee::process_sync_aggregate;
pub use block_signature_verifier::{BlockSignatureVerifier, ParallelSignatureSets};
pub use is_valid_indexed_attestation::is_valid_indexed_attestation;
pub use is_valid_indexed_payload_attestation::is_valid_indexed_payload_attestation;
pub use process_operations::process_operations;
pub use verify_attestation::{
    verify_attestation_for_block_inclusion, verify_attestation_for_state,
};
pub use verify_bls_to_execution_change::verify_bls_to_execution_change;
pub use verify_deposit::{
    get_existing_validator_index, is_valid_deposit_signature, verify_deposit_merkle_proof,
};
pub use verify_exit::verify_exit;
pub use withdrawals::get_expected_withdrawals;

pub mod altair;
pub mod block_signature_verifier;
pub mod builder;
pub mod deneb;
pub mod errors;
mod is_valid_indexed_attestation;
mod is_valid_indexed_payload_attestation;
pub mod process_operations;
pub mod signature_sets;
pub mod tests;
mod verify_attestation;
mod verify_attester_slashing;
mod verify_bls_to_execution_change;
mod verify_deposit;
mod verify_exit;
mod verify_payload_attestation;
mod verify_proposer_slashing;
pub mod withdrawals;

use crate::common::update_progressive_balances_cache::{
    initialize_progressive_balances_cache, update_progressive_balances_metrics,
};
use crate::epoch_cache::initialize_epoch_cache;
use crate::metrics as state_processing_metrics;
#[cfg(feature = "arbitrary")]
use arbitrary::Arbitrary;
use ethereum_hashing::hash;
use tracing::instrument;

const TOPOSTAKE_TX_PATH_DOMAIN: &str = "TOPOSTAKE_TX_PATH_V1";
#[cfg(test)]
const TOPOSTAKE_BLOCK_EVIDENCE_DOMAIN: &str = "TOPOSTAKE_BLOCK_EVIDENCE_V1";

/// The strategy to be used when validating the block's signatures.
#[cfg_attr(feature = "arbitrary", derive(Arbitrary))]
#[derive(PartialEq, Clone, Copy, Debug)]
pub enum BlockSignatureStrategy {
    /// Do not validate any signature. Use with caution.
    NoVerification,
    /// Validate each signature individually, as its object is being processed.
    VerifyIndividual,
    /// Validate only the randao reveal signature.
    VerifyRandao,
    /// Verify all signatures in bulk at the beginning of block processing.
    VerifyBulk,
}

/// The strategy to be used when validating the block's signatures.
#[cfg_attr(feature = "arbitrary", derive(Arbitrary))]
#[derive(PartialEq, Clone, Copy)]
pub enum VerifySignatures {
    /// Validate all signatures encountered.
    True,
    /// Do not validate any signature. Use with caution.
    False,
}

impl VerifySignatures {
    pub fn is_true(self) -> bool {
        self == VerifySignatures::True
    }
}

/// Control verification of the latest block header.
#[cfg_attr(feature = "arbitrary", derive(Arbitrary))]
#[derive(PartialEq, Clone, Copy)]
pub enum VerifyBlockRoot {
    True,
    False,
}

/// Updates the state for a new block, whilst validating that the block is valid, optionally
/// checking the block proposer signature.
///
/// Returns `Ok(())` if the block is valid and the state was successfully updated. Otherwise
/// returns an error describing why the block was invalid or how the function failed to execute.
///
/// If `block_root` is `Some`, this root is used for verification of the proposer's signature. If it
/// is `None` the signing root is computed from scratch. This parameter only exists to avoid
/// re-calculating the root when it is already known. Note `block_root` should be equal to the
/// tree hash root of the block, NOT the signing root of the block. This function takes
/// care of mixing in the domain.
#[instrument(skip_all)]
pub fn per_block_processing<E: EthSpec, Payload: AbstractExecPayload<E>>(
    state: &mut BeaconState<E>,
    signed_block: &SignedBeaconBlock<E, Payload>,
    block_signature_strategy: BlockSignatureStrategy,
    verify_block_root: VerifyBlockRoot,
    ctxt: &mut ConsensusContext<E>,
    spec: &ChainSpec,
) -> Result<(), BlockProcessingError> {
    let block = signed_block.message();

    // Verify that the `SignedBeaconBlock` instantiation matches the fork at `signed_block.slot()`.
    let fork_name = signed_block
        .fork_name(spec)
        .map_err(BlockProcessingError::InconsistentBlockFork)?;

    // Verify that the `BeaconState` instantiation matches the fork at `state.slot()`.
    state
        .fork_name(spec)
        .map_err(BlockProcessingError::InconsistentStateFork)?;

    // Process deferred execution requests from the parent's envelope.
    if fork_name.gloas_enabled() {
        process_parent_execution_payload(state, block, spec)?;
    }

    // Build epoch cache if it hasn't already been built, or if it is no longer valid
    initialize_epoch_cache(state, spec)?;
    initialize_progressive_balances_cache(state, spec)?;
    state.build_slashings_cache()?;

    let verify_signatures = match block_signature_strategy {
        BlockSignatureStrategy::VerifyBulk => {
            // Verify all signatures in the block at once.
            block_verify!(
                BlockSignatureVerifier::verify_entire_block(
                    state,
                    |i| get_pubkey_from_state(state, i),
                    |pk_bytes| pk_bytes.decompress().ok().map(Cow::Owned),
                    signed_block,
                    ctxt,
                    spec
                )
                .is_ok(),
                BlockProcessingError::BulkSignatureVerificationFailed
            );
            VerifySignatures::False
        }
        BlockSignatureStrategy::VerifyIndividual => VerifySignatures::True,
        BlockSignatureStrategy::NoVerification => VerifySignatures::False,
        BlockSignatureStrategy::VerifyRandao => VerifySignatures::False,
    };

    let proposer_index = process_block_header(
        state,
        block.temporary_block_header(),
        verify_block_root,
        ctxt,
        spec,
    )?;

    if verify_signatures.is_true() {
        verify_block_signature(state, signed_block, ctxt, spec)?;
    }

    let verify_randao = if let BlockSignatureStrategy::VerifyRandao = block_signature_strategy {
        VerifySignatures::True
    } else {
        verify_signatures
    };
    // Ensure the current and previous epoch committee caches are built.
    state.build_committee_cache(RelativeEpoch::Previous, spec)?;
    state.build_committee_cache(RelativeEpoch::Current, spec)?;

    // The call to the `process_execution_payload` must happen before the call to the
    // `process_randao` as the former depends on the `randao_mix` computed with the reveal of the
    // previous block.
    if is_execution_enabled(state, block.body()) {
        let body = block.body();
        if state.fork_name_unchecked().gloas_enabled() {
            withdrawals::gloas::process_withdrawals::<E>(state, spec)?;
            process_execution_payload_bid(state, block, verify_signatures, spec)?;
        } else {
            if state.fork_name_unchecked().capella_enabled() {
                withdrawals::capella_electra::process_withdrawals::<E, Payload>(
                    state,
                    body.execution_payload()?,
                    spec,
                )?;
            }
            process_execution_payload::<E, Payload>(state, body, spec)?;
        }
    }

    process_randao(state, block, verify_randao, ctxt, spec)?;
    process_eth1_data(state, block.body().eth1_data())?;
    process_operations(state, block.body(), verify_signatures, ctxt, spec)?;
    for topostake_tx_evidence_outcome in record_topostake_tx_gossip_metadata_for_block::<E, Payload>(
        &block,
        proposer_index as usize,
        spec,
    ) {
        update_topostake_evidence_metrics(topostake_tx_evidence_outcome);
    }
    update_topostake_finality_dependent_metrics::<E>(state, spec);

    if let Ok(sync_aggregate) = block.body().sync_aggregate() {
        process_sync_aggregate(
            state,
            sync_aggregate,
            proposer_index,
            verify_signatures,
            spec,
        )?;
    }

    if is_progressive_balances_enabled(state) {
        update_progressive_balances_metrics(state.progressive_balances_cache())?;
    }

    Ok(())
}

fn record_topostake_tx_gossip_metadata_for_block<E: EthSpec, Payload: AbstractExecPayload<E>>(
    block: &BeaconBlockRef<'_, E, Payload>,
    proposer_index: usize,
    spec: &ChainSpec,
) -> Vec<TopoStakeEvidenceRecordOutcome> {
    let epoch = block.slot().epoch(E::slots_per_epoch());
    if !spec.is_topostake_enabled_at_epoch(epoch) {
        return vec![];
    }

    let inline_records = block.body().topostake_evidence_records();
    if inline_records.is_empty() {
        return vec![];
    }
    if inline_records
        .iter()
        .any(|record| record.epoch > epoch.as_u64())
    {
        return record_topostake_invalid_tx_gossip_metadata_evidence(
            epoch,
            inline_records.len(),
            spec,
        );
    }
    let registry = topostake_relay_public_registry();
    let verify_started = Instant::now();
    let verified =
        verify_topostake_inline_block_aggregate(inline_records.as_ref(), registry, spec);
    metrics::observe_duration(
        &state_processing_metrics::TOPOSTAKE_INLINE_EVIDENCE_VERIFY_SECONDS,
        verify_started.elapsed(),
    );
    if !verified {
        return record_topostake_invalid_tx_gossip_metadata_evidence(
            epoch,
            inline_records.len(),
            spec,
        );
    }

    let stale_count = inline_records
        .iter()
        .filter(|record| record.epoch < epoch.as_u64())
        .count();
    let inline_paths = inline_records
        .iter()
        .filter(|record| record.epoch == epoch.as_u64())
        .filter_map(topostake_path_evidence_from_inline_record)
        .collect::<Vec<_>>();
    let mut outcomes = if stale_count == 0 {
        Vec::new()
    } else {
        record_topostake_invalid_tx_gossip_metadata_evidence(epoch, stale_count, spec)
    };
    if !inline_paths.is_empty() {
        outcomes.extend(record_topostake_tx_gossip_metadata_evidence(
            epoch,
            proposer_index,
            inline_paths,
            spec,
        ));
    }
    outcomes
}

fn topostake_path_evidence_from_inline_record<E: EthSpec>(
    record: &TopoStakeInlineEvidenceRecord<E>,
) -> Option<TopoStakePathEvidence> {
    let path = record
        .relay_path
        .iter()
        .copied()
        .map(usize::try_from)
        .collect::<Result<Vec<_>, _>>()
        .ok()?;
    if path.is_empty() {
        return None;
    }
    Some(TopoStakePathEvidence {
        tx_hash: hash256_hex(record.tx_hash),
        path,
        fee_budget_wei: record.priority_fee_wei,
        irrecoverable_cost_wei: record.irrecoverable_cost_wei,
    })
}

fn verify_topostake_inline_block_aggregate<E: EthSpec>(
    records: &[TopoStakeInlineEvidenceRecord<E>],
    registry: &TopoStakeRelayPublicRegistry,
    spec: &ChainSpec,
) -> bool {
    if records.is_empty() {
        return true;
    }
    let evidence_work_units = records.iter().fold(0u64, |work, record| {
        work.saturating_add(record.relay_path.len() as u64)
    });
    if evidence_work_units > spec.topostake_config.evidence_work_limit {
        return false;
    }
    let mut aggregate_signature = None;
    let mut signature_records = Vec::new();
    for record in records {
        if !topostake_inline_record_requires_signature(record) {
            continue;
        }
        let Some(record_signature) = topostake_inline_aggregate_signature(record) else {
            return false;
        };
        if let Some(expected_signature) = aggregate_signature {
            if record_signature != expected_signature {
                return false;
            }
        } else {
            aggregate_signature = Some(record_signature);
        }
        let Some(mut per_tx_records) =
            topostake_inline_signature_records(record, registry, spec.deposit_chain_id)
        else {
            return false;
        };
        signature_records.append(&mut per_tx_records);
    }
    let Some(aggregate_signature) = aggregate_signature else {
        return true;
    };
    verify_topostake_aggregate_signature_bytes(registry, &aggregate_signature, &signature_records)
}

fn topostake_inline_record_requires_signature<E: EthSpec>(
    record: &TopoStakeInlineEvidenceRecord<E>,
) -> bool {
    !record.relay_path.is_empty()
}

fn topostake_inline_aggregate_signature<E: EthSpec>(
    record: &TopoStakeInlineEvidenceRecord<E>,
) -> Option<[u8; 48]> {
    record.aggregate_signature.as_ref().try_into().ok()
}

fn topostake_inline_signature_records<E: EthSpec>(
    record: &TopoStakeInlineEvidenceRecord<E>,
    registry: &TopoStakeRelayPublicRegistry,
    chain_id: u64,
) -> Option<Vec<TopoStakeSignatureRecord>> {
    let tx_hash = *record.tx_hash.as_ref();
    let path = record.relay_path.iter().copied().collect::<Vec<_>>();
    if path.is_empty() {
        return None;
    }
    let addresses = path
        .iter()
        .map(|validator_index| registry.address_for_validator(*validator_index, None))
        .collect::<Vec<_>>();
    if addresses
        .iter()
        .any(|address| registry.pubkey(address).is_none())
    {
        return None;
    }

    let origin_statement = origin_statement(chain_id, record.epoch, &tx_hash, &addresses[0]);
    let mut signature_records = vec![TopoStakeSignatureRecord {
        signer: addresses[0].clone(),
        statement: origin_statement,
        signature: [0; 48],
    }];

    if path.len() == 1 {
        return Some(signature_records);
    }

    for edge_index in 0..addresses.len().saturating_sub(1) {
        let prefix = chain_value(&tx_hash, chain_id, record.epoch, &addresses, edge_index);
        let statement = edge_statement(&prefix, &addresses[edge_index], &addresses[edge_index + 1]);
        signature_records.push(TopoStakeSignatureRecord {
            signer: addresses[edge_index].clone(),
            statement,
            signature: [0; 48],
        });
        signature_records.push(TopoStakeSignatureRecord {
            signer: addresses[edge_index + 1].clone(),
            statement,
            signature: [0; 48],
        });
    }
    Some(signature_records)
}

fn topostake_el_rpc_url() -> Option<String> {
    if let Ok(url) = std::env::var("TOPOSTAKE_EL_RPC_URL") {
        let url = url.trim();
        if !url.is_empty() {
            return Some(url.to_string());
        }
    }
    let registry = std::env::var("TOPOSTAKE_EL_RPC_REGISTRY_JSON").ok()?;
    select_topostake_el_rpc_url_from_registry(&registry).ok()
}

fn topostake_el_rpc_urls() -> Vec<String> {
    if let Ok(url) = std::env::var("TOPOSTAKE_EL_RPC_URL") {
        let url = url.trim();
        if !url.is_empty() {
            return vec![url.to_string()];
        }
    }
    let Ok(raw) = std::env::var("TOPOSTAKE_EL_RPC_REGISTRY_JSON") else {
        return topostake_el_rpc_url().into_iter().collect();
    };
    let Ok(registry) = serde_json::from_str::<TopoStakeElRpcRegistry>(&raw) else {
        return topostake_el_rpc_url().into_iter().collect();
    };
    let mut urls = Vec::new();
    for endpoint in registry.endpoints {
        if !endpoint.el_rpc_url.trim().is_empty() && !urls.contains(&endpoint.el_rpc_url) {
            urls.push(endpoint.el_rpc_url);
        }
    }
    if urls.is_empty() {
        topostake_el_rpc_url().into_iter().collect()
    } else {
        urls
    }
}

#[derive(Deserialize)]
struct TopoStakeElRpcRegistry {
    endpoints: Vec<TopoStakeElRpcEndpoint>,
}

#[derive(Deserialize)]
struct TopoStakeElRpcEndpoint {
    cl_service_name: String,
    el_rpc_url: String,
}

fn select_topostake_el_rpc_url_from_registry(raw: &str) -> Result<String, String> {
    let registry: TopoStakeElRpcRegistry =
        serde_json::from_str(raw).map_err(|e| format!("invalid EL RPC registry json: {e}"))?;
    if let Ok(local_service_name) = std::env::var("TOPOSTAKE_CL_SERVICE_NAME") {
        let local_service_name = local_service_name.trim();
        if !local_service_name.is_empty() {
            for endpoint in &registry.endpoints {
                if endpoint.cl_service_name == local_service_name {
                    return Ok(endpoint.el_rpc_url.clone());
                }
            }
        }
    }
    let local_ip = local_ip_for_registry(&registry)?;
    for endpoint in &registry.endpoints {
        if resolve_ips(&endpoint.cl_service_name)
            .iter()
            .any(|ip| *ip == local_ip)
        {
            return Ok(endpoint.el_rpc_url.clone());
        }
    }
    Err("no matching TopoStake EL RPC registry endpoint for local CL".to_string())
}

fn local_ip_for_registry(registry: &TopoStakeElRpcRegistry) -> Result<IpAddr, String> {
    for endpoint in &registry.endpoints {
        let parsed = TopoStakeHttpEndpoint::parse(&endpoint.el_rpc_url)?;
        if let Ok(socket) = UdpSocket::bind("0.0.0.0:0") {
            if socket.connect((parsed.host.as_str(), parsed.port)).is_ok() {
                if let Ok(addr) = socket.local_addr() {
                    return Ok(addr.ip());
                }
            }
        }
    }
    Err("could not determine local CL IP for TopoStake EL RPC registry".to_string())
}

fn resolve_ips(host: &str) -> Vec<IpAddr> {
    (host, 0)
        .to_socket_addrs()
        .map(|addrs| addrs.map(|addr| addr.ip()).collect())
        .unwrap_or_default()
}

fn decode_chunked_http_body(body: &str) -> Result<String, String> {
    let mut decoded = String::new();
    let mut rest = body;
    loop {
        let (size_hex, after_size) = rest
            .split_once("\r\n")
            .ok_or_else(|| "invalid chunked response: missing chunk size".to_string())?;
        let size = usize::from_str_radix(size_hex.trim(), 16)
            .map_err(|_| "invalid chunked response: bad chunk size".to_string())?;
        if size == 0 {
            return Ok(decoded);
        }
        if after_size.len() < size + 2 {
            return Err("invalid chunked response: truncated chunk".to_string());
        }
        decoded.push_str(&after_size[..size]);
        rest = &after_size[size + 2..];
    }
}

struct TopoStakeHttpEndpoint {
    host: String,
    port: u16,
    path: String,
}

impl TopoStakeHttpEndpoint {
    fn parse(raw: &str) -> Result<Self, String> {
        let without_scheme = raw
            .strip_prefix("http://")
            .ok_or_else(|| "TOPOSTAKE_EL_RPC_URL must use http://".to_string())?;
        let (authority, path) = match without_scheme.split_once('/') {
            Some((authority, path)) => (authority, format!("/{path}")),
            None => (without_scheme, "/".to_string()),
        };
        if authority.is_empty() {
            return Err("TOPOSTAKE_EL_RPC_URL is missing host".to_string());
        }
        let (host, port) = match authority.rsplit_once(':') {
            Some((host, port)) => {
                let port = port
                    .parse::<u16>()
                    .map_err(|_| "TOPOSTAKE_EL_RPC_URL has invalid port".to_string())?;
                (host.to_string(), port)
            }
            None => (authority.to_string(), 8545),
        };
        if host.is_empty() {
            return Err("TOPOSTAKE_EL_RPC_URL is missing host".to_string());
        }
        Ok(Self { host, port, path })
    }

    fn host_header(&self) -> String {
        format!("{}:{}", self.host, self.port)
    }
}

#[cfg(test)]
#[derive(Deserialize)]
struct TopoStakeBlockEvidence {
    block_hash: Option<String>,
    block_number: Option<u64>,
    evidence_root: Option<String>,
    aggregate_signature: Option<String>,
    aggregate_signature_count: Option<usize>,
    #[serde(default)]
    transactions: Vec<TopoStakeTxEvidence>,
}

#[cfg(test)]
impl TopoStakeBlockEvidence {
    fn evidence_root_hex(&self) -> Option<String> {
        normalize_topostake_evidence_root(self.evidence_root.as_ref()?)
    }

    fn verify_block_commitment(
        &self,
        verified: &[TopoStakeVerifiedTxEvidence],
        registry: &TopoStakeRelayPublicRegistry,
    ) -> bool {
        if self.transactions.is_empty()
            && self.evidence_root.is_none()
            && self.aggregate_signature.is_none()
            && self.aggregate_signature_count.is_none()
        {
            return true;
        }
        let (Some(block_hash), Some(block_number), Some(evidence_root)) = (
            self.block_hash.as_ref(),
            self.block_number,
            self.evidence_root.as_ref(),
        ) else {
            return false;
        };
        let Some(block_hash) = hex_bytes_exact::<32>(block_hash) else {
            return false;
        };
        let records = verified
            .iter()
            .flat_map(|evidence| evidence.records.iter().cloned())
            .collect::<Vec<_>>();
        let computed_root =
            block_evidence_root(&block_hash, block_number, &records, &self.transactions);
        if hex_bytes_exact::<32>(evidence_root) != Some(computed_root) {
            return false;
        }
        if records.is_empty() {
            return self.aggregate_signature_count.unwrap_or_default() == 0;
        }
        if self.aggregate_signature_count != Some(records.len()) {
            return false;
        }
        let Some(aggregate_signature) = self.aggregate_signature.as_ref() else {
            return false;
        };
        verify_topostake_aggregate_signature(registry, aggregate_signature, &records)
    }
}

#[cfg(test)]
#[derive(Deserialize)]
struct TopoStakeTxEvidence {
    #[serde(default)]
    index: u64,
    #[serde(default)]
    tx_hash: Option<String>,
    #[serde(default)]
    gas_used: u64,
    #[serde(default)]
    effective_gas_tip_wei: Option<String>,
    #[serde(default)]
    priority_fee_wei: Option<String>,
    #[serde(default)]
    base_fee_wei: Option<String>,
    #[serde(default)]
    irrecoverable_cost_wei: Option<String>,
    #[serde(default)]
    fee_recipient: Option<String>,
    #[serde(default)]
    escrow_recipient: Option<String>,
    metadata: TopoStakeTxMetadata,
}

#[cfg(test)]
#[derive(Deserialize)]
struct TopoStakeTxMetadata {
    domain: String,
    chain_id: u64,
    epoch: u64,
    tx_hash: String,
    #[serde(default)]
    origin_relay_address: Option<String>,
    origin_relay_validator_index: u64,
    origin_relay_pubkey: String,
    origin_signature: String,
    #[serde(default)]
    paths: Vec<TopoStakeTxPathEdge>,
}

#[cfg(test)]
impl TopoStakeTxMetadata {
    fn verified_evidence(
        &self,
        registry: &TopoStakeRelayPublicRegistry,
    ) -> Option<TopoStakeVerifiedTxEvidence> {
        if self.domain != TOPOSTAKE_TX_PATH_DOMAIN {
            return None;
        }
        let tx_hash = hex_bytes_exact::<32>(&self.tx_hash)?;
        let origin_address = registry.address_for_validator(
            self.origin_relay_validator_index,
            self.origin_relay_address.as_deref(),
        );
        let origin_validator_index = registry.validator_index(&origin_address)?;
        let mut records = Vec::new();
        let origin_statement =
            origin_statement(self.chain_id, self.epoch, &tx_hash, &origin_address);
        if !verify_topostake_signature(
            registry.pubkey(&origin_address).or_else(|| {
                hex_bytes_exact::<96>(&self.origin_relay_pubkey).map(|bytes| bytes.to_vec())
            }),
            &self.origin_signature,
            &origin_statement,
        ) {
            return None;
        }
        records.push(TopoStakeSignatureRecord {
            signer: origin_address.clone(),
            statement: origin_statement,
            signature: hex_bytes_exact::<48>(&self.origin_signature)?,
        });

        let address_sequence = self.address_sequence(registry)?;
        let mut expected_from = self.origin_relay_validator_index;
        let mut expected_from_address = origin_address.clone();
        let mut path = vec![usize::try_from(origin_validator_index).ok()?];
        for (idx, edge) in self.paths.iter().enumerate() {
            if edge.from != expected_from {
                return None;
            }
            let from_address =
                registry.address_for_validator(edge.from, edge.from_address.as_deref());
            let to_address = registry.address_for_validator(edge.to, edge.to_address.as_deref());
            if from_address != expected_from_address || from_address != address_sequence[idx] {
                return None;
            }
            if to_address != address_sequence[idx + 1] {
                return None;
            }
            let expected_prefix =
                chain_value(&tx_hash, self.chain_id, self.epoch, &address_sequence, idx);
            if hex_bytes_exact::<32>(&edge.prefix)? != expected_prefix {
                return None;
            }
            let statement = edge_statement(&expected_prefix, &from_address, &to_address);
            if !verify_topostake_signature(
                registry.pubkey(&from_address),
                &edge.sender_signature,
                &statement,
            ) {
                return None;
            }
            records.push(TopoStakeSignatureRecord {
                signer: from_address,
                statement,
                signature: hex_bytes_exact::<48>(&edge.sender_signature)?,
            });
            if !verify_topostake_signature(
                registry.pubkey(&to_address),
                edge.receiver_signature.as_deref()?,
                &statement,
            ) {
                return None;
            }
            records.push(TopoStakeSignatureRecord {
                signer: to_address.clone(),
                statement,
                signature: hex_bytes_exact::<48>(edge.receiver_signature.as_deref()?)?,
            });
            path.push(usize::try_from(registry.validator_index(&to_address)?).ok()?);
            expected_from = edge.to;
            expected_from_address = to_address;
        }

        Some(TopoStakeVerifiedTxEvidence {
            tx_hash: hex_bytes(&tx_hash),
            path,
            records,
        })
    }

    fn address_sequence(&self, registry: &TopoStakeRelayPublicRegistry) -> Option<Vec<String>> {
        let mut nodes = Vec::with_capacity(self.paths.len().saturating_add(1));
        nodes.push(registry.address_for_validator(
            self.origin_relay_validator_index,
            self.origin_relay_address.as_deref(),
        ));
        for edge in &self.paths {
            nodes.push(registry.address_for_validator(edge.to, edge.to_address.as_deref()));
        }
        Some(nodes)
    }
}

#[derive(Clone)]
#[allow(dead_code)]
struct TopoStakeSignatureRecord {
    signer: String,
    statement: [u8; 32],
    signature: [u8; 48],
}

#[cfg(test)]
struct TopoStakeVerifiedTxEvidence {
    tx_hash: String,
    path: Vec<usize>,
    records: Vec<TopoStakeSignatureRecord>,
}

#[cfg(test)]
#[derive(Deserialize)]
struct TopoStakeTxPathEdge {
    from: u64,
    to: u64,
    #[serde(default)]
    from_address: Option<String>,
    #[serde(default)]
    to_address: Option<String>,
    prefix: String,
    sender_signature: String,
    receiver_signature: Option<String>,
}

#[derive(Default)]
#[allow(dead_code)]
struct TopoStakeRelayPublicRegistry {
    pubkeys_by_address: HashMap<String, Vec<u8>>,
    validator_addresses: HashMap<u64, String>,
    payout_addresses: HashMap<u64, String>,
    address_validators: HashMap<String, u64>,
    el_rpc_urls: HashMap<u64, String>,
    cl_http_urls: HashMap<u64, String>,
}

#[allow(dead_code)]
impl TopoStakeRelayPublicRegistry {
    fn pubkey(&self, address: &str) -> Option<Vec<u8>> {
        let address = normalize_topostake_relay_address(address)?;
        self.pubkeys_by_address.get(&address).cloned()
    }

    fn validator_index(&self, address: &str) -> Option<u64> {
        let address = normalize_topostake_relay_address(address)?;
        self.address_validators.get(&address).copied()
    }

    fn address_for_validator(&self, validator_index: u64, address: Option<&str>) -> String {
        normalize_topostake_relay_address(address.unwrap_or(""))
            .or_else(|| self.validator_addresses.get(&validator_index).cloned())
            .unwrap_or_else(|| fallback_topostake_relay_address(validator_index))
    }

    fn payout_address_for_validator(&self, validator_index: u64) -> String {
        self.payout_addresses
            .get(&validator_index)
            .cloned()
            .or_else(|| self.validator_addresses.get(&validator_index).cloned())
            .unwrap_or_else(|| fallback_topostake_relay_address(validator_index))
    }

    fn el_rpc_url(&self, validator_index: u64) -> Option<String> {
        self.el_rpc_urls.get(&validator_index).cloned()
    }

    fn cl_http_url(&self, validator_index: u64) -> Option<String> {
        self.cl_http_urls.get(&validator_index).cloned()
    }
}

#[derive(Deserialize)]
struct TopoStakeRelayPublicRegistryFile {
    #[serde(default)]
    relays: Vec<TopoStakeRelayPublicRegistryEntry>,
}

#[derive(Deserialize)]
struct TopoStakeRelayPublicRegistryEntry {
    validator_index: u64,
    #[serde(default)]
    relay_address: Option<String>,
    #[serde(default)]
    payout_address: Option<String>,
    #[serde(default)]
    service_name: Option<String>,
    #[serde(default)]
    cl_service_name: Option<String>,
    relay_pubkey: String,
}

fn topostake_relay_public_registry() -> &'static TopoStakeRelayPublicRegistry {
    static REGISTRY: OnceLock<TopoStakeRelayPublicRegistry> = OnceLock::new();
    REGISTRY.get_or_init(load_topostake_relay_public_registry)
}

fn load_topostake_relay_public_registry() -> TopoStakeRelayPublicRegistry {
    let raw = std::env::var("TOPOSTAKE_RELAY_PUBLIC_REGISTRY_JSON")
        .ok()
        .filter(|value| !value.trim().is_empty())
        .or_else(|| {
            std::env::var("TOPOSTAKE_RELAY_PUBLIC_REGISTRY")
                .ok()
                .and_then(|path| std::fs::read_to_string(path).ok())
        });
    let Some(raw) = raw else {
        return TopoStakeRelayPublicRegistry::default();
    };
    let Ok(registry) = serde_json::from_str::<TopoStakeRelayPublicRegistryFile>(&raw) else {
        return TopoStakeRelayPublicRegistry::default();
    };
    let mut el_rpc_urls = HashMap::new();
    let mut cl_http_urls = HashMap::new();
    let mut pubkeys_by_address = HashMap::new();
    let mut validator_addresses = HashMap::new();
    let mut payout_addresses = HashMap::new();
    let mut address_validators = HashMap::new();
    for relay in registry.relays {
        let Some(pubkey) = hex_bytes_exact::<96>(&relay.relay_pubkey) else {
            continue;
        };
        let address = normalize_topostake_relay_address(
            relay
                .relay_address
                .as_deref()
                .or(relay.payout_address.as_deref())
                .unwrap_or(""),
        )
        .unwrap_or_else(|| fallback_topostake_relay_address(relay.validator_index));
        validator_addresses.insert(relay.validator_index, address.clone());
        if let Some(payout_address) = relay
            .payout_address
            .as_deref()
            .and_then(normalize_topostake_relay_address)
        {
            payout_addresses.insert(relay.validator_index, payout_address);
        }
        address_validators.insert(address.clone(), relay.validator_index);
        pubkeys_by_address.insert(address.clone(), pubkey.to_vec());
        if let Some(service_name) = relay.service_name.as_ref() {
            let service_name = service_name.trim();
            if !service_name.is_empty() {
                el_rpc_urls.insert(relay.validator_index, format!("http://{service_name}:8545"));
            }
        }
        let cl_service_name = relay
            .cl_service_name
            .as_deref()
            .map(str::trim)
            .filter(|service_name| !service_name.is_empty())
            .map(str::to_string)
            .or_else(|| {
                relay
                    .service_name
                    .as_deref()
                    .and_then(derive_topostake_cl_service_name)
            });
        if let Some(cl_service_name) = cl_service_name {
            cl_http_urls.insert(
                relay.validator_index,
                format!("http://{cl_service_name}:4000"),
            );
        }
    }
    TopoStakeRelayPublicRegistry {
        pubkeys_by_address,
        validator_addresses,
        payout_addresses,
        address_validators,
        el_rpc_urls,
        cl_http_urls,
    }
}

fn derive_topostake_cl_service_name(el_service_name: &str) -> Option<String> {
    let service_name = el_service_name.trim();
    let node = service_name
        .strip_prefix("el-")?
        .strip_suffix("-geth-lighthouse")?;
    Some(format!("cl-{node}-lighthouse-geth"))
}

#[allow(dead_code)]
fn verify_topostake_signature(
    pubkey: Option<Vec<u8>>,
    signature: &str,
    statement: &[u8; 32],
) -> bool {
    let Some(pubkey) = pubkey else {
        return false;
    };
    let Some(signature) = hex_bytes_exact::<48>(signature) else {
        return false;
    };
    let Ok(pubkey) = blst::min_sig::PublicKey::from_bytes(&pubkey) else {
        return false;
    };
    let Ok(signature) = blst::min_sig::Signature::from_bytes(&signature) else {
        return false;
    };
    signature.verify(
        true,
        statement,
        TOPOSTAKE_TX_PATH_DOMAIN.as_bytes(),
        &[],
        &pubkey,
        false,
    ) == blst::BLST_ERROR::BLST_SUCCESS
}

#[allow(dead_code)]
fn verify_topostake_aggregate_signature(
    registry: &TopoStakeRelayPublicRegistry,
    signature: &str,
    records: &[TopoStakeSignatureRecord],
) -> bool {
    let Some(signature) = hex_bytes_exact::<48>(signature) else {
        return false;
    };
    verify_topostake_aggregate_signature_bytes(registry, &signature, records)
}

fn verify_topostake_aggregate_signature_bytes(
    registry: &TopoStakeRelayPublicRegistry,
    signature: &[u8; 48],
    records: &[TopoStakeSignatureRecord],
) -> bool {
    let Ok(signature) = blst::min_sig::Signature::from_bytes(signature) else {
        return false;
    };
    let mut pubkeys = Vec::with_capacity(records.len());
    for record in records {
        let Some(pubkey) = registry.pubkey(&record.signer) else {
            return false;
        };
        let Ok(pubkey) = blst::min_sig::PublicKey::from_bytes(&pubkey) else {
            return false;
        };
        pubkeys.push(pubkey);
    }
    let msg_refs = records
        .iter()
        .map(|record| record.statement.as_slice())
        .collect::<Vec<_>>();
    let pubkey_refs = pubkeys.iter().collect::<Vec<_>>();
    signature.aggregate_verify(
        true,
        &msg_refs,
        TOPOSTAKE_TX_PATH_DOMAIN.as_bytes(),
        &pubkey_refs,
        false,
    ) == blst::BLST_ERROR::BLST_SUCCESS
}

#[cfg(test)]
fn block_evidence_root(
    block_hash: &[u8; 32],
    block_number: u64,
    records: &[TopoStakeSignatureRecord],
    transactions: &[TopoStakeTxEvidence],
) -> [u8; 32] {
    let mut input = Vec::with_capacity(
        TOPOSTAKE_BLOCK_EVIDENCE_DOMAIN.len()
            + 32
            + 8
            + 8
            + transactions.len() * (8 + 32 + 8 + 8 * 5)
            + 8
            + records.len() * 96,
    );
    input.extend_from_slice(TOPOSTAKE_BLOCK_EVIDENCE_DOMAIN.as_bytes());
    input.extend_from_slice(block_hash);
    input.extend_from_slice(&block_number.to_be_bytes());
    input.extend_from_slice(&(transactions.len() as u64).to_be_bytes());
    for tx in transactions {
        input.extend_from_slice(&tx.index.to_be_bytes());
        let tx_hash = tx
            .tx_hash
            .as_deref()
            .and_then(hex_bytes_exact::<32>)
            .unwrap_or([0u8; 32]);
        input.extend_from_slice(&tx_hash);
        input.extend_from_slice(&tx.gas_used.to_be_bytes());
        write_evidence_string(
            &mut input,
            tx.effective_gas_tip_wei.as_deref().unwrap_or(""),
        );
        write_evidence_string(&mut input, tx.priority_fee_wei.as_deref().unwrap_or(""));
        write_evidence_string(&mut input, tx.base_fee_wei.as_deref().unwrap_or(""));
        write_evidence_string(
            &mut input,
            tx.irrecoverable_cost_wei.as_deref().unwrap_or(""),
        );
        write_evidence_string(
            &mut input,
            &normalize_topostake_evidence_address(tx.fee_recipient.as_deref().unwrap_or("")),
        );
        write_evidence_string(
            &mut input,
            &normalize_topostake_evidence_address(tx.escrow_recipient.as_deref().unwrap_or("")),
        );
    }
    input.extend_from_slice(&(records.len() as u64).to_be_bytes());
    for record in records {
        input.extend_from_slice(&hash_identity(&record.signer));
        input.extend_from_slice(&record.statement);
        input.extend_from_slice(&record.signature);
    }
    sha256_array(&input)
}

#[cfg(test)]
fn write_evidence_string(input: &mut Vec<u8>, value: &str) {
    input.extend_from_slice(&(value.len() as u64).to_be_bytes());
    input.extend_from_slice(value.as_bytes());
}

fn origin_statement(chain_id: u64, epoch: u64, tx_hash: &[u8; 32], address: &str) -> [u8; 32] {
    let mut input = Vec::with_capacity(TOPOSTAKE_TX_PATH_DOMAIN.len() + 8 + 8 + 32 + 32);
    input.extend_from_slice(TOPOSTAKE_TX_PATH_DOMAIN.as_bytes());
    input.extend_from_slice(&chain_id.to_be_bytes());
    input.extend_from_slice(&epoch.to_be_bytes());
    input.extend_from_slice(tx_hash);
    input.extend_from_slice(&hash_identity(address));
    sha256_array(&input)
}

fn chain_value(
    tx_hash: &[u8; 32],
    chain_id: u64,
    epoch: u64,
    nodes: &[String],
    node_idx: usize,
) -> [u8; 32] {
    let mut input = Vec::with_capacity(TOPOSTAKE_TX_PATH_DOMAIN.len() + 8 + 32 + 8);
    input.extend_from_slice(TOPOSTAKE_TX_PATH_DOMAIN.as_bytes());
    input.extend_from_slice(&chain_id.to_be_bytes());
    input.extend_from_slice(tx_hash);
    input.extend_from_slice(&epoch.to_be_bytes());
    if nodes.is_empty() {
        return sha256_array(&input);
    }
    input.extend_from_slice(&hash_identity(&nodes[0]));
    let mut chain = sha256_array(&input);
    let capped = node_idx.min(nodes.len().saturating_sub(1));
    for node in &nodes[1..=capped] {
        let mut hop_input = Vec::with_capacity(64);
        hop_input.extend_from_slice(&chain);
        hop_input.extend_from_slice(&hash_identity(node));
        chain = sha256_array(&hop_input);
    }
    chain
}

fn edge_statement(prefix: &[u8; 32], from: &str, to: &str) -> [u8; 32] {
    let mut input = Vec::with_capacity(TOPOSTAKE_TX_PATH_DOMAIN.len() + 32 + 32 + 32);
    input.extend_from_slice(TOPOSTAKE_TX_PATH_DOMAIN.as_bytes());
    input.extend_from_slice(prefix);
    input.extend_from_slice(&hash_identity(from));
    input.extend_from_slice(&hash_identity(to));
    sha256_array(&input)
}

fn hash_identity(identity: &str) -> [u8; 32] {
    sha256_array(
        normalize_topostake_relay_address(identity)
            .unwrap_or_else(|| identity.trim().to_ascii_lowercase())
            .as_bytes(),
    )
}

fn fallback_topostake_relay_address(validator_index: u64) -> String {
    let mut bytes = [0u8; 20];
    bytes[12..20].copy_from_slice(&validator_index.saturating_add(1).to_be_bytes());
    format!("0x{}", hex_bytes(&bytes))
}

fn normalize_topostake_relay_address(address: &str) -> Option<String> {
    let trimmed = address.trim();
    if trimmed.is_empty() {
        return None;
    }
    let hex = trimmed.strip_prefix("0x").unwrap_or(trimmed);
    if hex.len() == 40 && hex.chars().all(|c| c.is_ascii_hexdigit()) {
        Some(format!("0x{}", hex.to_ascii_lowercase()))
    } else {
        Some(trimmed.to_ascii_lowercase())
    }
}

#[cfg(test)]
fn normalize_topostake_evidence_address(address: &str) -> String {
    normalize_topostake_relay_address(address)
        .unwrap_or_else(|| address.trim().to_ascii_lowercase())
}

fn sha256_array(input: &[u8]) -> [u8; 32] {
    let digest = hash(input);
    let mut out = [0u8; 32];
    out.copy_from_slice(&digest);
    out
}

fn hex_bytes_exact<const N: usize>(input: &str) -> Option<[u8; N]> {
    let hex = input.trim().strip_prefix("0x").unwrap_or(input.trim());
    if hex.len() != N.saturating_mul(2) || !hex.chars().all(|c| c.is_ascii_hexdigit()) {
        return None;
    }
    let mut out = [0u8; N];
    for i in 0..N {
        out[i] = u8::from_str_radix(&hex[i * 2..i * 2 + 2], 16).ok()?;
    }
    Some(out)
}

#[cfg(test)]
fn execution_block_hash_hex(block_hash: ExecutionBlockHash) -> String {
    hash256_hex(block_hash.into_root())
}

fn hash256_hex(root: Hash256) -> String {
    let bytes: &[u8; 32] = root.as_ref();
    hex_bytes(bytes)
}

fn hex_bytes(bytes: &[u8]) -> String {
    let mut out = String::with_capacity(66);
    out.push_str("0x");
    for byte in bytes {
        out.push(hex_char(byte >> 4));
        out.push(hex_char(byte & 0x0f));
    }
    out
}

#[cfg(test)]
fn normalize_topostake_evidence_root(root: &str) -> Option<String> {
    let hex = root.trim().strip_prefix("0x").unwrap_or(root.trim());
    if hex.len() == 64 && hex.chars().all(|c| c.is_ascii_hexdigit()) {
        Some(format!("0x{}", hex.to_ascii_lowercase()))
    } else {
        None
    }
}

fn hex_char(nibble: u8) -> char {
    match nibble {
        0 => '0',
        1 => '1',
        2 => '2',
        3 => '3',
        4 => '4',
        5 => '5',
        6 => '6',
        7 => '7',
        8 => '8',
        9 => '9',
        10 => 'a',
        11 => 'b',
        12 => 'c',
        13 => 'd',
        14 => 'e',
        _ => 'f',
    }
}

#[cfg(test)]
mod topostake_tx_gossip_tests {
    use super::*;

    fn hex_string(bytes: &[u8]) -> String {
        let mut out = String::with_capacity(bytes.len().saturating_mul(2).saturating_add(2));
        out.push_str("0x");
        for byte in bytes {
            out.push(hex_char(byte >> 4));
            out.push(hex_char(byte & 0x0f));
        }
        out
    }

    fn secret(seed: &[u8]) -> blst::min_sig::SecretKey {
        blst::min_sig::SecretKey::key_gen(seed, &[]).expect("seed should produce key")
    }

    #[test]
    fn topostake_tx_gossip_metadata_requires_real_bls_signatures() {
        let chain_id = 7_032_030;
        let epoch = 7;
        let tx_hash = [0x42; 32];
        let sender = secret(b"topostake lighthouse tx gossip sender key");
        let receiver = secret(b"topostake lighthouse tx gossip receiver key");
        let sender_pubkey = sender.sk_to_pk().to_bytes();
        let receiver_pubkey = receiver.sk_to_pk().to_bytes();
        let sender_address = fallback_topostake_relay_address(0);
        let receiver_address = fallback_topostake_relay_address(1);
        let origin_statement = origin_statement(chain_id, epoch, &tx_hash, &sender_address);
        let origin_signature =
            sender.sign(&origin_statement, TOPOSTAKE_TX_PATH_DOMAIN.as_bytes(), &[]);
        let path_addresses = vec![sender_address.clone(), receiver_address.clone()];
        let prefix = chain_value(&tx_hash, chain_id, epoch, &path_addresses, 0);
        let edge_statement = edge_statement(&prefix, &sender_address, &receiver_address);
        let sender_signature =
            sender.sign(&edge_statement, TOPOSTAKE_TX_PATH_DOMAIN.as_bytes(), &[]);
        let receiver_signature =
            receiver.sign(&edge_statement, TOPOSTAKE_TX_PATH_DOMAIN.as_bytes(), &[]);
        let registry = TopoStakeRelayPublicRegistry {
            pubkeys_by_address: HashMap::from([
                (sender_address.clone(), sender_pubkey.to_vec()),
                (receiver_address.clone(), receiver_pubkey.to_vec()),
            ]),
            validator_addresses: HashMap::from([
                (0, sender_address.clone()),
                (1, receiver_address.clone()),
            ]),
            payout_addresses: HashMap::new(),
            address_validators: HashMap::from([
                (sender_address.clone(), 0),
                (receiver_address.clone(), 1),
            ]),
            el_rpc_urls: HashMap::new(),
            cl_http_urls: HashMap::new(),
        };
        let metadata = TopoStakeTxMetadata {
            domain: TOPOSTAKE_TX_PATH_DOMAIN.to_string(),
            chain_id,
            epoch,
            tx_hash: hex_string(&tx_hash),
            origin_relay_address: Some(sender_address.clone()),
            origin_relay_validator_index: 0,
            origin_relay_pubkey: hex_string(&sender_pubkey),
            origin_signature: hex_string(&origin_signature.to_bytes()),
            paths: vec![TopoStakeTxPathEdge {
                from: 0,
                to: 1,
                from_address: Some(sender_address.clone()),
                to_address: Some(receiver_address.clone()),
                prefix: hex_string(&prefix),
                sender_signature: hex_string(&sender_signature.to_bytes()),
                receiver_signature: Some(hex_string(&receiver_signature.to_bytes())),
            }],
        };

        let verified = metadata
            .verified_evidence(&registry)
            .expect("metadata should verify");
        assert_eq!(verified.path, vec![0, 1]);
        assert_eq!(verified.records.len(), 3);

        let sig_refs = [&origin_signature, &sender_signature, &receiver_signature];
        let aggregate = blst::min_sig::AggregateSignature::aggregate(&sig_refs, true)
            .expect("aggregate signature should build")
            .to_signature();
        assert!(verify_topostake_aggregate_signature(
            &registry,
            &hex_string(&aggregate.to_bytes()),
            &verified.records,
        ));

        let block_hash = [0x99; 32];
        let root = block_evidence_root(&block_hash, 12, &verified.records, &[]);
        let block_evidence = TopoStakeBlockEvidence {
            block_hash: Some(hex_string(&block_hash)),
            block_number: Some(12),
            evidence_root: Some(hex_string(&root)),
            aggregate_signature: Some(hex_string(&aggregate.to_bytes())),
            aggregate_signature_count: Some(verified.records.len()),
            transactions: vec![],
        };
        assert!(block_evidence.verify_block_commitment(&[verified], &registry));

        let mut bad_receiver = metadata;
        bad_receiver.paths[0].receiver_signature = Some(hex_string(&sender_signature.to_bytes()));
        assert!(bad_receiver.verified_evidence(&registry).is_none());
    }

    #[test]
    fn topostake_origin_only_metadata_verifies_for_block_aggregate() {
        let chain_id = 7_032_030;
        let epoch = 7;
        let tx_hash = [0x24; 32];
        let origin = secret(b"topostake lighthouse origin only key");
        let origin_pubkey = origin.sk_to_pk().to_bytes();
        let origin_address = fallback_topostake_relay_address(0);
        let origin_statement = origin_statement(chain_id, epoch, &tx_hash, &origin_address);
        let origin_signature =
            origin.sign(&origin_statement, TOPOSTAKE_TX_PATH_DOMAIN.as_bytes(), &[]);
        let registry = TopoStakeRelayPublicRegistry {
            pubkeys_by_address: HashMap::from([(origin_address.clone(), origin_pubkey.to_vec())]),
            validator_addresses: HashMap::from([(0, origin_address.clone())]),
            payout_addresses: HashMap::new(),
            address_validators: HashMap::from([(origin_address.clone(), 0)]),
            el_rpc_urls: HashMap::new(),
            cl_http_urls: HashMap::new(),
        };
        let metadata = TopoStakeTxMetadata {
            domain: TOPOSTAKE_TX_PATH_DOMAIN.to_string(),
            chain_id,
            epoch,
            tx_hash: hex_string(&tx_hash),
            origin_relay_address: Some(origin_address.clone()),
            origin_relay_validator_index: 0,
            origin_relay_pubkey: hex_string(&origin_pubkey),
            origin_signature: hex_string(&origin_signature.to_bytes()),
            paths: vec![],
        };

        let verified = metadata
            .verified_evidence(&registry)
            .expect("origin-only metadata should verify for block aggregate");
        assert_eq!(verified.path, vec![0]);
        assert_eq!(verified.records.len(), 1);

        let sig_refs = [&origin_signature];
        let aggregate = blst::min_sig::AggregateSignature::aggregate(&sig_refs, true)
            .expect("aggregate signature should build")
            .to_signature();
        let block_hash = [0x33; 32];
        let transactions = vec![TopoStakeTxEvidence {
            index: 0,
            tx_hash: Some(hex_string(&tx_hash)),
            gas_used: 21_000,
            effective_gas_tip_wei: Some("3".to_string()),
            priority_fee_wei: Some("63000".to_string()),
            base_fee_wei: Some("1".to_string()),
            irrecoverable_cost_wei: Some("21000".to_string()),
            fee_recipient: Some("0x000000000000000000000000000000000000c0de".to_string()),
            escrow_recipient: Some("0x0000000000000000000000000000000000705000".to_string()),
            metadata,
        }];
        let root = block_evidence_root(&block_hash, 14, &verified.records, &transactions);
        let block_evidence = TopoStakeBlockEvidence {
            block_hash: Some(hex_string(&block_hash)),
            block_number: Some(14),
            evidence_root: Some(hex_string(&root)),
            aggregate_signature: Some(hex_string(&aggregate.to_bytes())),
            aggregate_signature_count: Some(verified.records.len()),
            transactions,
        };
        assert!(block_evidence.verify_block_commitment(&[verified], &registry));
    }

    fn inline_record(
        tx_hash: [u8; 32],
        epoch: u64,
        relay_path: Vec<u64>,
        aggregate_signature: [u8; 48],
    ) -> TopoStakeInlineEvidenceRecord<MinimalEthSpec> {
        TopoStakeInlineEvidenceRecord {
            tx_hash: Hash256::from_slice(&tx_hash),
            epoch,
            priority_fee_wei: 42_000,
            irrecoverable_cost_wei: 21_000,
            relay_path: ssz_types::VariableList::new(relay_path).expect("path length should fit"),
            aggregate_signature: ssz_types::FixedVector::new(aggregate_signature.to_vec())
                .expect("signature length should fit"),
        }
    }

    #[test]
    fn topostake_inline_block_aggregate_verifies_and_rejects_tampering() {
        let chain_id = 7_032_030;
        let epoch = 9;
        let tx_hash = [0x51; 32];
        let origin = secret(b"topostake lighthouse inline origin key material");
        let receiver = secret(b"topostake lighthouse inline receiver key material");
        let origin_pubkey = origin.sk_to_pk().to_bytes();
        let receiver_pubkey = receiver.sk_to_pk().to_bytes();
        let origin_address = fallback_topostake_relay_address(0);
        let receiver_address = fallback_topostake_relay_address(1);
        let registry = TopoStakeRelayPublicRegistry {
            pubkeys_by_address: HashMap::from([
                (origin_address.clone(), origin_pubkey.to_vec()),
                (receiver_address.clone(), receiver_pubkey.to_vec()),
            ]),
            validator_addresses: HashMap::from([
                (0, origin_address.clone()),
                (1, receiver_address.clone()),
            ]),
            payout_addresses: HashMap::new(),
            address_validators: HashMap::from([
                (origin_address.clone(), 0),
                (receiver_address.clone(), 1),
            ]),
            el_rpc_urls: HashMap::new(),
            cl_http_urls: HashMap::new(),
        };
        let addresses = vec![origin_address.clone(), receiver_address.clone()];
        let origin_statement_bytes = origin_statement(chain_id, epoch, &tx_hash, &origin_address);
        let edge_prefix = chain_value(&tx_hash, chain_id, epoch, &addresses, 0);
        let edge_statement = edge_statement(&edge_prefix, &origin_address, &receiver_address);
        let origin_signature = origin.sign(
            &origin_statement_bytes,
            TOPOSTAKE_TX_PATH_DOMAIN.as_bytes(),
            &[],
        );
        let sender_signature =
            origin.sign(&edge_statement, TOPOSTAKE_TX_PATH_DOMAIN.as_bytes(), &[]);
        let receiver_signature =
            receiver.sign(&edge_statement, TOPOSTAKE_TX_PATH_DOMAIN.as_bytes(), &[]);
        let sig_refs = [&origin_signature, &sender_signature, &receiver_signature];
        let aggregate = blst::min_sig::AggregateSignature::aggregate(&sig_refs, true)
            .expect("aggregate signature should build")
            .to_signature()
            .to_bytes();
        let mut spec = ChainSpec::minimal();
        spec.deposit_chain_id = chain_id;
        spec.topostake_config = TopoStakeConfig::devnet_enabled_at(Epoch::new(0));

        let record = inline_record(tx_hash, epoch, vec![0, 1], aggregate);
        assert!(verify_topostake_inline_block_aggregate(
            &[record.clone()],
            &registry,
            &spec
        ));

        let mut work_limited_spec = spec.clone();
        work_limited_spec.topostake_config.evidence_work_limit = 1;
        assert!(!verify_topostake_inline_block_aggregate(
            &[record.clone()],
            &registry,
            &work_limited_spec
        ));

        let origin_only_tx_hash = [0x52; 32];
        let origin_only_statement =
            origin_statement(chain_id, epoch, &origin_only_tx_hash, &origin_address);
        let origin_only_signature = origin.sign(
            &origin_only_statement,
            TOPOSTAKE_TX_PATH_DOMAIN.as_bytes(),
            &[],
        );
        let mixed_sig_refs = [
            &origin_signature,
            &sender_signature,
            &receiver_signature,
            &origin_only_signature,
        ];
        let mixed_aggregate = blst::min_sig::AggregateSignature::aggregate(&mixed_sig_refs, true)
            .expect("mixed aggregate signature should build")
            .to_signature()
            .to_bytes();
        let relayed_record = inline_record(tx_hash, epoch, vec![0, 1], mixed_aggregate);
        let origin_only_record =
            inline_record(origin_only_tx_hash, epoch, vec![0], mixed_aggregate);
        assert!(verify_topostake_inline_block_aggregate(
            &[relayed_record, origin_only_record],
            &registry,
            &spec
        ));

        let tampered_path = inline_record(tx_hash, epoch, vec![1, 0], aggregate);
        assert!(!verify_topostake_inline_block_aggregate(
            &[tampered_path],
            &registry,
            &spec
        ));

        let unknown_relay = inline_record(tx_hash, epoch, vec![0, 2], aggregate);
        assert!(!verify_topostake_inline_block_aggregate(
            &[unknown_relay],
            &registry,
            &spec
        ));

        let mut bad_signature = aggregate;
        bad_signature[0] ^= 0x01;
        let bad_signature_record = inline_record(tx_hash, epoch, vec![0, 1], bad_signature);
        assert!(!verify_topostake_inline_block_aggregate(
            &[bad_signature_record],
            &registry,
            &spec
        ));
    }

    #[test]
    fn topostake_derives_cl_service_name_from_el_service_name() {
        assert_eq!(
            derive_topostake_cl_service_name("el-3-geth-lighthouse").as_deref(),
            Some("cl-3-lighthouse-geth")
        );
        assert!(derive_topostake_cl_service_name("cl-3-lighthouse-geth").is_none());
    }

    #[test]
    fn topostake_registry_prefers_payout_address_for_settlement() {
        let relay_address = "0x0000000000000000000000000000000000000001".to_string();
        let payout_address = "0x000000000000000000000000000000000000beef".to_string();
        let registry = TopoStakeRelayPublicRegistry {
            pubkeys_by_address: HashMap::new(),
            validator_addresses: HashMap::from([(1, relay_address.clone())]),
            payout_addresses: HashMap::from([(1, payout_address.clone())]),
            address_validators: HashMap::new(),
            el_rpc_urls: HashMap::new(),
            cl_http_urls: HashMap::new(),
        };
        assert_eq!(registry.address_for_validator(1, None), relay_address);
        assert_eq!(registry.payout_address_for_validator(1), payout_address);
    }
}

fn update_topostake_finality_dependent_metrics<E: EthSpec>(
    state: &BeaconState<E>,
    spec: &ChainSpec,
) {
    topostake_settle_credits_through_epoch(state.finalized_checkpoint().epoch);
    submit_topostake_finalized_settlements(state.finalized_checkpoint().epoch);
    update_topostake_settled_score_metrics::<E>(state, spec);
    update_topostake_credit_metrics();
}

fn update_topostake_evidence_metrics(outcome: TopoStakeEvidenceRecordOutcome) {
    match outcome {
        TopoStakeEvidenceRecordOutcome::Disabled | TopoStakeEvidenceRecordOutcome::NoEvidence => {}
        TopoStakeEvidenceRecordOutcome::Valid {
            epoch,
            source,
            score_updates,
            summary,
            ..
        } => {
            state_processing_metrics::inc_counter_vec(
                &state_processing_metrics::TOPOSTAKE_EVIDENCE_PATHS_TOTAL,
                &["valid"],
            );
            state_processing_metrics::inc_counter_vec(
                &state_processing_metrics::TOPOSTAKE_EVIDENCE_SOURCES_TOTAL,
                &[source.as_metrics_label()],
            );
            update_topostake_evidence_epoch_summary_metrics(&summary);
            update_topostake_raw_contribution_metrics(epoch, &score_updates);
        }
        TopoStakeEvidenceRecordOutcome::Invalid { summary, .. } => {
            state_processing_metrics::inc_counter_vec(
                &state_processing_metrics::TOPOSTAKE_EVIDENCE_PATHS_TOTAL,
                &["invalid"],
            );
            update_topostake_evidence_epoch_summary_metrics(&summary);
        }
        TopoStakeEvidenceRecordOutcome::DuplicateReceiver { summary, .. } => {
            state_processing_metrics::inc_counter_vec(
                &state_processing_metrics::TOPOSTAKE_EVIDENCE_PATHS_TOTAL,
                &["duplicate_receiver"],
            );
            update_topostake_evidence_epoch_summary_metrics(&summary);
        }
        TopoStakeEvidenceRecordOutcome::DuplicateTransaction { summary, .. } => {
            state_processing_metrics::inc_counter_vec(
                &state_processing_metrics::TOPOSTAKE_EVIDENCE_PATHS_TOTAL,
                &["duplicate_tx"],
            );
            update_topostake_evidence_epoch_summary_metrics(&summary);
        }
    }
}

fn update_topostake_evidence_epoch_summary_metrics(summary: &TopoStakeEvidenceEpochSummary) {
    let epoch = summary.epoch.as_u64().to_string();
    let labels = &[epoch.as_str()];
    state_processing_metrics::set_gauge_vec(
        &state_processing_metrics::TOPOSTAKE_EVIDENCE_EPOCH_VALID_PATHS,
        labels,
        u64_to_i64(summary.valid_paths),
    );
    state_processing_metrics::set_gauge_vec(
        &state_processing_metrics::TOPOSTAKE_EVIDENCE_EPOCH_INVALID_PATHS,
        labels,
        u64_to_i64(summary.invalid_paths),
    );
    state_processing_metrics::set_gauge_vec(
        &state_processing_metrics::TOPOSTAKE_EVIDENCE_EPOCH_DUPLICATE_RECEIVERS,
        labels,
        u64_to_i64(summary.duplicate_receiver_proofs),
    );
    state_processing_metrics::set_gauge_vec(
        &state_processing_metrics::TOPOSTAKE_EVIDENCE_EPOCH_SCORED_VALIDATORS,
        labels,
        usize_to_i64(summary.scored_validators),
    );
    state_processing_metrics::set_gauge_vec(
        &state_processing_metrics::TOPOSTAKE_EVIDENCE_EPOCH_MAX_SCORE_SCALED,
        labels,
        u64_to_i64(summary.max_score_scaled),
    );
    state_processing_metrics::set_gauge_vec(
        &state_processing_metrics::TOPOSTAKE_EVIDENCE_EPOCH_BOUND_VIOLATION,
        labels,
        i64::from(summary.bound_violation),
    );
}

fn update_topostake_raw_contribution_metrics(evidence_epoch: Epoch, raw_updates: &[(usize, u64)]) {
    let evidence_epoch_label = evidence_epoch.as_u64().to_string();

    for (validator_index, raw_contribution_scaled) in raw_updates {
        let validator_label = validator_index.to_string();
        state_processing_metrics::set_gauge_vec(
            &state_processing_metrics::TOPOSTAKE_EPOCH_RAW_CONTRIBUTION_SCALED,
            &[evidence_epoch_label.as_str(), validator_label.as_str()],
            u64_to_i64(*raw_contribution_scaled),
        );
    }
}

fn update_topostake_settled_score_metrics<E: EthSpec>(state: &BeaconState<E>, spec: &ChainSpec) {
    let finalized_epoch = state.finalized_checkpoint().epoch;
    let total_active_balance = state.get_total_active_balance().unwrap_or_else(|_| {
        state
            .validators()
            .iter()
            .map(|validator| validator.effective_balance)
            .sum::<u64>()
    });
    let validator_effective_balances = state
        .validators()
        .iter()
        .enumerate()
        .map(|(validator_index, validator)| (validator_index, validator.effective_balance))
        .collect::<Vec<_>>();

    for settled_epoch in topostake_settle_scores_through_epoch(
        finalized_epoch,
        &validator_effective_balances,
        total_active_balance,
        spec,
    ) {
        let evidence_epoch_label = settled_epoch.epoch.as_u64().to_string();
        state_processing_metrics::set_gauge_vec(
            &state_processing_metrics::TOPOSTAKE_EPOCH_SCORE_TOTAL_SCALED,
            &[evidence_epoch_label.as_str()],
            u64_to_i64(settled_epoch.score_total_scaled),
        );
        for update in settled_epoch.updates {
            let validator_label = update.validator_index.to_string();
            state_processing_metrics::set_gauge_vec(
                &state_processing_metrics::TOPOSTAKE_EPOCH_SATURATED_CONTRIBUTION_SCALED,
                &[evidence_epoch_label.as_str(), validator_label.as_str()],
                u64_to_i64(update.saturated_contribution_scaled),
            );
            state_processing_metrics::set_gauge_vec(
                &state_processing_metrics::TOPOSTAKE_EPOCH_SCORE_SCALED,
                &[evidence_epoch_label.as_str(), validator_label.as_str()],
                u64_to_i64(update.score_scaled),
            );
            let score_share_scaled =
                scaled_score_share(update.score_scaled, settled_epoch.score_total_scaled);
            state_processing_metrics::set_gauge_vec(
                &state_processing_metrics::TOPOSTAKE_EPOCH_SCORE_SHARE_SCALED,
                &[evidence_epoch_label.as_str(), validator_label.as_str()],
                u64_to_i64(score_share_scaled),
            );
        }
    }
}

fn scaled_score_share(score_scaled: u64, total_score_scaled: u64) -> u64 {
    if total_score_scaled == 0 {
        return 0;
    }
    (u128::from(score_scaled).saturating_mul(u128::from(TOPOSTAKE_FIXED_POINT_SCALE))
        / u128::from(total_score_scaled))
    .min(u128::from(u64::MAX)) as u64
}

fn update_topostake_credit_metrics() {
    for summary in topostake_credit_epoch_summaries() {
        let epoch = summary.epoch.as_u64().to_string();
        state_processing_metrics::set_gauge_vec(
            &state_processing_metrics::TOPOSTAKE_CREDIT_EPOCH_RECORDS,
            &[epoch.as_str(), "total"],
            u64_to_i64(summary.credit_records),
        );
        state_processing_metrics::set_gauge_vec(
            &state_processing_metrics::TOPOSTAKE_CREDIT_EPOCH_RECORDS,
            &[epoch.as_str(), "pending"],
            u64_to_i64(summary.pending_records),
        );
        state_processing_metrics::set_gauge_vec(
            &state_processing_metrics::TOPOSTAKE_CREDIT_EPOCH_RECORDS,
            &[epoch.as_str(), "settled"],
            u64_to_i64(summary.settled_records),
        );
        state_processing_metrics::set_gauge_vec(
            &state_processing_metrics::TOPOSTAKE_CREDIT_EPOCH_TOTAL_SCALED,
            &[epoch.as_str(), "budget"],
            u64_to_i64(summary.total_budget_scaled),
        );
        state_processing_metrics::set_gauge_vec(
            &state_processing_metrics::TOPOSTAKE_CREDIT_EPOCH_TOTAL_SCALED,
            &[epoch.as_str(), "proposer"],
            u64_to_i64(summary.proposer_credit_scaled),
        );
        state_processing_metrics::set_gauge_vec(
            &state_processing_metrics::TOPOSTAKE_CREDIT_EPOCH_TOTAL_SCALED,
            &[epoch.as_str(), "relay"],
            u64_to_i64(summary.relay_credit_scaled),
        );
        state_processing_metrics::set_gauge_vec(
            &state_processing_metrics::TOPOSTAKE_CREDIT_EPOCH_TOTAL_SCALED,
            &[epoch.as_str(), "burned"],
            u64_to_i64(summary.burned_credit_scaled),
        );
        state_processing_metrics::set_gauge_vec(
            &state_processing_metrics::TOPOSTAKE_CREDIT_EPOCH_CONSERVATION_VIOLATION,
            &[epoch.as_str()],
            i64::from(summary.conservation_violation),
        );

        for credit in summary.proposer_credits {
            let validator = credit.validator_index.to_string();
            state_processing_metrics::set_gauge_vec(
                &state_processing_metrics::TOPOSTAKE_CREDIT_VALIDATOR_TOTAL_SCALED,
                &[epoch.as_str(), "proposer", validator.as_str()],
                u64_to_i64(credit.credit_scaled),
            );
        }
        for credit in summary.relay_credits {
            let validator = credit.validator_index.to_string();
            state_processing_metrics::set_gauge_vec(
                &state_processing_metrics::TOPOSTAKE_CREDIT_VALIDATOR_TOTAL_SCALED,
                &[epoch.as_str(), "relay", validator.as_str()],
                u64_to_i64(credit.credit_scaled),
            );
        }
    }

    for summary in topostake_fee_settlement_epoch_summaries() {
        let epoch = summary.epoch.as_u64().to_string();
        state_processing_metrics::set_gauge_vec(
            &state_processing_metrics::TOPOSTAKE_FEE_SETTLEMENT_RECORDS_TOTAL,
            &[epoch.as_str(), "total", "all"],
            u64_to_i64(summary.settlement_records),
        );
        state_processing_metrics::set_gauge_vec(
            &state_processing_metrics::TOPOSTAKE_FEE_SETTLEMENT_RECORDS_TOTAL,
            &[epoch.as_str(), "pending", "all"],
            u64_to_i64(summary.pending_records),
        );
        state_processing_metrics::set_gauge_vec(
            &state_processing_metrics::TOPOSTAKE_FEE_SETTLEMENT_RECORDS_TOTAL,
            &[epoch.as_str(), "settled", "all"],
            u64_to_i64(summary.settled_records),
        );
        state_processing_metrics::set_gauge_vec(
            &state_processing_metrics::TOPOSTAKE_FEE_SETTLEMENT_AMOUNT_WEI,
            &[epoch.as_str(), "budget"],
            u64_to_i64(summary.total_amount_wei),
        );
        state_processing_metrics::set_gauge_vec(
            &state_processing_metrics::TOPOSTAKE_FEE_SETTLEMENT_AMOUNT_WEI,
            &[epoch.as_str(), "proposer"],
            u64_to_i64(summary.proposer_amount_wei),
        );
        state_processing_metrics::set_gauge_vec(
            &state_processing_metrics::TOPOSTAKE_FEE_SETTLEMENT_AMOUNT_WEI,
            &[epoch.as_str(), "relay"],
            u64_to_i64(summary.relay_amount_wei),
        );
        state_processing_metrics::set_gauge_vec(
            &state_processing_metrics::TOPOSTAKE_FEE_SETTLEMENT_AMOUNT_WEI,
            &[epoch.as_str(), "burned"],
            u64_to_i64(summary.burned_amount_wei),
        );
        state_processing_metrics::set_gauge_vec(
            &state_processing_metrics::TOPOSTAKE_FEE_BURNED_AMOUNT_WEI,
            &[epoch.as_str()],
            u64_to_i64(summary.burned_amount_wei),
        );
        state_processing_metrics::set_gauge_vec(
            &state_processing_metrics::TOPOSTAKE_FEE_CONSERVATION_VIOLATION,
            &[epoch.as_str()],
            i64::from(summary.conservation_violation),
        );

        for settlement in summary.proposer_settlements {
            let validator = settlement.validator_index.to_string();
            state_processing_metrics::set_gauge_vec(
                &state_processing_metrics::TOPOSTAKE_FEE_VALIDATOR_AMOUNT_WEI,
                &[epoch.as_str(), validator.as_str(), "proposer"],
                u64_to_i64(settlement.amount_wei),
            );
        }
        for settlement in summary.relay_settlements {
            let validator = settlement.validator_index.to_string();
            state_processing_metrics::set_gauge_vec(
                &state_processing_metrics::TOPOSTAKE_FEE_VALIDATOR_AMOUNT_WEI,
                &[epoch.as_str(), validator.as_str(), "relay"],
                u64_to_i64(settlement.amount_wei),
            );
        }
    }
}

fn submitted_topostake_settlement_epochs() -> &'static RwLock<HashSet<u64>> {
    static SUBMITTED: OnceLock<RwLock<HashSet<u64>>> = OnceLock::new();
    SUBMITTED.get_or_init(|| RwLock::new(HashSet::new()))
}

fn submit_topostake_finalized_settlements(finalized_epoch: Epoch) {
    let rpc_urls = topostake_el_rpc_urls();
    if rpc_urls.is_empty() {
        return;
    }
    for summary in topostake_fee_settlement_epoch_summaries() {
        let epoch = summary.epoch.as_u64();
        if epoch > finalized_epoch.as_u64()
            || summary.settled_records == 0
            || summary.pending_records != 0
            || summary.conservation_violation
        {
            continue;
        }
        if submitted_topostake_settlement_epochs()
            .read()
            .map(|submitted| submitted.contains(&epoch))
            .unwrap_or(true)
        {
            continue;
        }
        let mut submitted_all = true;
        for rpc_url in &rpc_urls {
            if submit_topostake_settlement_summary(rpc_url, finalized_epoch, &summary).is_err() {
                submitted_all = false;
            }
        }
        if submitted_all {
            if let Ok(mut submitted) = submitted_topostake_settlement_epochs().write() {
                submitted.insert(epoch);
            }
        }
    }
}

fn submit_topostake_settlement_summary(
    rpc_url: &str,
    finalized_epoch: Epoch,
    summary: &TopoStakeFeeSettlementEpochSummary,
) -> Result<(), String> {
    let registry = topostake_relay_public_registry();
    let epoch = summary.epoch.as_u64();
    let mut records = Vec::new();
    for settlement in &summary.proposer_settlements {
        let validator_index = settlement.validator_index as u64;
        let payout_address = registry.payout_address_for_validator(validator_index);
        records.push(serde_json::json!({
            "id": format!("{epoch}:proposer:{validator_index}:{payout_address}:{}", settlement.amount_wei),
            "epoch": epoch,
            "role": "proposer",
            "validator_index": validator_index,
            "payout_address": payout_address,
            "amount_wei": settlement.amount_wei.to_string(),
        }));
    }
    for settlement in &summary.relay_settlements {
        let validator_index = settlement.validator_index as u64;
        let payout_address = registry.payout_address_for_validator(validator_index);
        records.push(serde_json::json!({
            "id": format!("{epoch}:relay:{validator_index}:{payout_address}:{}", settlement.amount_wei),
            "epoch": epoch,
            "role": "relay",
            "validator_index": validator_index,
            "payout_address": payout_address,
            "amount_wei": settlement.amount_wei.to_string(),
        }));
    }
    if summary.burned_amount_wei > 0 {
        records.push(serde_json::json!({
            "id": format!("{epoch}:burned:0::{}", summary.burned_amount_wei),
            "epoch": epoch,
            "role": "burned",
            "validator_index": 0u64,
            "amount_wei": summary.burned_amount_wei.to_string(),
        }));
    }
    if records.is_empty() {
        return Ok(());
    }
    let payload = serde_json::json!({
        "domain": "TOPOSTAKE_FEE_SETTLEMENT_V1",
        "finalized_epoch": finalized_epoch.as_u64(),
        "epoch": epoch,
        "records": records,
    });
    let body = serde_json::json!({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "topostake_submitSettlement",
        "params": [payload],
    })
    .to_string();
    submit_topostake_json_rpc(rpc_url, &body)
}

fn submit_topostake_json_rpc(rpc_url: &str, body: &str) -> Result<(), String> {
    let endpoint = TopoStakeHttpEndpoint::parse(rpc_url)?;
    let mut stream = TcpStream::connect((endpoint.host.as_str(), endpoint.port))
        .map_err(|e| format!("connect failed: {e}"))?;
    stream
        .set_read_timeout(Some(Duration::from_secs(2)))
        .map_err(|e| format!("set read timeout failed: {e}"))?;
    stream
        .set_write_timeout(Some(Duration::from_secs(2)))
        .map_err(|e| format!("set write timeout failed: {e}"))?;
    let request = format!(
        "POST {} HTTP/1.1\r\nHost: {}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
        endpoint.path,
        endpoint.host_header(),
        body.len(),
        body
    );
    stream
        .write_all(request.as_bytes())
        .map_err(|e| format!("write failed: {e}"))?;
    let mut response = String::new();
    stream
        .read_to_string(&mut response)
        .map_err(|e| format!("read failed: {e}"))?;
    let (headers, json_body) = response
        .split_once("\r\n\r\n")
        .ok_or_else(|| "missing HTTP response body".to_string())?;
    if !headers.starts_with("HTTP/1.1 200") && !headers.starts_with("HTTP/1.0 200") {
        return Err("TopoStake settlement RPC returned non-200".to_string());
    }
    let json_body = if headers
        .to_ascii_lowercase()
        .contains("transfer-encoding: chunked")
    {
        decode_chunked_http_body(json_body)?
    } else {
        json_body.to_string()
    };
    let response_value: Value =
        serde_json::from_str(&json_body).map_err(|e| format!("invalid settlement json: {e}"))?;
    if response_value.get("error").is_some() {
        return Err("TopoStake settlement RPC returned error".to_string());
    }
    if response_value.get("result").is_none() {
        return Err("TopoStake settlement RPC missing result".to_string());
    }
    Ok(())
}

fn u64_to_i64(value: u64) -> i64 {
    i64::try_from(value).unwrap_or(i64::MAX)
}

fn usize_to_i64(value: usize) -> i64 {
    i64::try_from(value).unwrap_or(i64::MAX)
}

/// Processes the block header, returning the proposer index.
pub fn process_block_header<E: EthSpec>(
    state: &mut BeaconState<E>,
    block_header: BeaconBlockHeader,
    verify_block_root: VerifyBlockRoot,
    ctxt: &mut ConsensusContext<E>,
    spec: &ChainSpec,
) -> Result<u64, BlockOperationError<HeaderInvalid>> {
    // Verify that the slots match
    verify!(
        block_header.slot == state.slot(),
        HeaderInvalid::StateSlotMismatch
    );

    // Verify that the block is newer than the latest block header
    verify!(
        block_header.slot > state.latest_block_header().slot,
        HeaderInvalid::OlderThanLatestBlockHeader {
            block_slot: block_header.slot,
            latest_block_header_slot: state.latest_block_header().slot,
        }
    );

    // Verify that proposer index is the correct index
    let proposer_index = block_header.proposer_index;
    let state_proposer_index = ctxt.get_proposer_index(state, spec)?;
    verify!(
        proposer_index == state_proposer_index,
        HeaderInvalid::ProposerIndexMismatch {
            block_proposer_index: proposer_index,
            state_proposer_index,
        }
    );

    if verify_block_root == VerifyBlockRoot::True {
        let expected_previous_block_root = state.latest_block_header().tree_hash_root();
        verify!(
            block_header.parent_root == expected_previous_block_root,
            HeaderInvalid::ParentBlockRootMismatch {
                state: expected_previous_block_root,
                block: block_header.parent_root,
            }
        );
    }

    state
        .slashings_cache_mut()
        .update_latest_block_slot(block_header.slot);
    *state.latest_block_header_mut() = block_header;

    // Verify proposer is not slashed
    verify!(
        !state.get_validator(proposer_index as usize)?.slashed,
        HeaderInvalid::ProposerSlashed(proposer_index)
    );

    Ok(proposer_index)
}

/// Verifies the signature of a block.
///
/// Spec v0.12.1
pub fn verify_block_signature<E: EthSpec, Payload: AbstractExecPayload<E>>(
    state: &BeaconState<E>,
    block: &SignedBeaconBlock<E, Payload>,
    ctxt: &mut ConsensusContext<E>,
    spec: &ChainSpec,
) -> Result<(), BlockOperationError<HeaderInvalid>> {
    let block_root = Some(ctxt.get_current_block_root(block)?);
    let proposer_index = Some(ctxt.get_proposer_index(state, spec)?);
    verify!(
        block_proposal_signature_set(
            state,
            |i| get_pubkey_from_state(state, i),
            block,
            block_root,
            proposer_index,
            spec
        )?
        .verify(),
        HeaderInvalid::ProposalSignatureInvalid
    );

    Ok(())
}

/// Verifies the `randao_reveal` against the block's proposer pubkey and updates
/// `state.latest_randao_mixes`.
pub fn process_randao<E: EthSpec, Payload: AbstractExecPayload<E>>(
    state: &mut BeaconState<E>,
    block: BeaconBlockRef<'_, E, Payload>,
    verify_signatures: VerifySignatures,
    ctxt: &mut ConsensusContext<E>,
    spec: &ChainSpec,
) -> Result<(), BlockProcessingError> {
    if verify_signatures.is_true() {
        // Verify RANDAO reveal signature.
        let proposer_index = ctxt.get_proposer_index(state, spec)?;
        block_verify!(
            randao_signature_set(
                state,
                |i| get_pubkey_from_state(state, i),
                block,
                Some(proposer_index),
                spec
            )?
            .verify(),
            BlockProcessingError::RandaoSignatureInvalid
        );
    }

    // Update the current epoch RANDAO mix.
    state.update_randao_mix(state.current_epoch(), block.body().randao_reveal())?;

    Ok(())
}

/// Update the `state.eth1_data_votes` based upon the `eth1_data` provided.
pub fn process_eth1_data<E: EthSpec>(
    state: &mut BeaconState<E>,
    eth1_data: &Eth1Data,
) -> Result<(), BeaconStateError> {
    if let Some(new_eth1_data) = get_new_eth1_data(state, eth1_data)? {
        *state.eth1_data_mut() = new_eth1_data;
    }

    state.eth1_data_votes_mut().push(eth1_data.clone())?;

    Ok(())
}

/// Returns `Ok(Some(eth1_data))` if adding the given `eth1_data` to `state.eth1_data_votes` would
/// result in a change to `state.eth1_data`.
pub fn get_new_eth1_data<E: EthSpec>(
    state: &BeaconState<E>,
    eth1_data: &Eth1Data,
) -> Result<Option<Eth1Data>, ArithError> {
    let num_votes = state
        .eth1_data_votes()
        .iter()
        .filter(|vote| *vote == eth1_data)
        .count();

    // The +1 is to account for the `eth1_data` supplied to the function.
    if num_votes.safe_add(1)?.safe_mul(2)? > E::SlotsPerEth1VotingPeriod::to_usize() {
        Ok(Some(eth1_data.clone()))
    } else {
        Ok(None)
    }
}

/// Performs *partial* verification of the `payload`.
///
/// The verification is partial, since the execution payload is not verified against an execution
/// engine. That is expected to be performed by an upstream function.
///
/// ## Specification
///
/// Contains a partial set of checks from the `process_execution_payload` function:
///
/// https://github.com/ethereum/consensus-specs/blob/v1.1.5/specs/merge/beacon-chain.md#process_execution_payload
pub fn partially_verify_execution_payload<E: EthSpec, Payload: AbstractExecPayload<E>>(
    state: &BeaconState<E>,
    block_slot: Slot,
    body: BeaconBlockBodyRef<E, Payload>,
    spec: &ChainSpec,
) -> Result<(), BlockProcessingError> {
    let payload = body.execution_payload()?;
    if is_merge_transition_complete(state) {
        block_verify!(
            payload.parent_hash() == state.latest_execution_payload_header()?.block_hash(),
            BlockProcessingError::ExecutionHashChainIncontiguous {
                expected: state.latest_execution_payload_header()?.block_hash(),
                found: payload.parent_hash(),
            }
        );
    }
    block_verify!(
        payload.prev_randao() == *state.get_randao_mix(state.current_epoch())?,
        BlockProcessingError::ExecutionRandaoMismatch {
            expected: *state.get_randao_mix(state.current_epoch())?,
            found: payload.prev_randao(),
        }
    );

    let timestamp = compute_timestamp_at_slot(state, block_slot, spec)?;
    block_verify!(
        payload.timestamp() == timestamp,
        BlockProcessingError::ExecutionInvalidTimestamp {
            expected: timestamp,
            found: payload.timestamp(),
        }
    );

    if let Ok(blob_commitments) = body.blob_kzg_commitments() {
        // Verify commitments are under the limit.
        let max_blobs_per_block =
            spec.max_blobs_per_block(block_slot.epoch(E::slots_per_epoch())) as usize;
        block_verify!(
            blob_commitments.len() <= max_blobs_per_block,
            BlockProcessingError::ExecutionInvalidBlobsLen {
                max: max_blobs_per_block,
                actual: blob_commitments.len(),
            }
        );
    }

    Ok(())
}

/// Calls `partially_verify_execution_payload` and then updates the payload header in the `state`.
///
/// ## Specification
///
/// Partially equivalent to the `process_execution_payload` function:
///
/// https://github.com/ethereum/consensus-specs/blob/v1.1.5/specs/merge/beacon-chain.md#process_execution_payload
pub fn process_execution_payload<E: EthSpec, Payload: AbstractExecPayload<E>>(
    state: &mut BeaconState<E>,
    body: BeaconBlockBodyRef<E, Payload>,
    spec: &ChainSpec,
) -> Result<(), BlockProcessingError> {
    partially_verify_execution_payload::<E, Payload>(state, state.slot(), body, spec)?;
    let payload = body.execution_payload()?;
    match state.latest_execution_payload_header_mut()? {
        ExecutionPayloadHeaderRefMut::Bellatrix(header_mut) => {
            match payload.to_execution_payload_header() {
                ExecutionPayloadHeader::Bellatrix(header) => *header_mut = header,
                _ => return Err(BlockProcessingError::IncorrectStateType),
            }
        }
        ExecutionPayloadHeaderRefMut::Capella(header_mut) => {
            match payload.to_execution_payload_header() {
                ExecutionPayloadHeader::Capella(header) => *header_mut = header,
                _ => return Err(BlockProcessingError::IncorrectStateType),
            }
        }
        ExecutionPayloadHeaderRefMut::Deneb(header_mut) => {
            match payload.to_execution_payload_header() {
                ExecutionPayloadHeader::Deneb(header) => *header_mut = header,
                _ => return Err(BlockProcessingError::IncorrectStateType),
            }
        }
        ExecutionPayloadHeaderRefMut::Electra(header_mut) => {
            match payload.to_execution_payload_header() {
                ExecutionPayloadHeader::Electra(header) => *header_mut = header,
                _ => return Err(BlockProcessingError::IncorrectStateType),
            }
        }
        ExecutionPayloadHeaderRefMut::Fulu(header_mut) => {
            match payload.to_execution_payload_header() {
                ExecutionPayloadHeader::Fulu(header) => *header_mut = header,
                _ => return Err(BlockProcessingError::IncorrectStateType),
            }
        }
    }

    Ok(())
}

/// These functions will definitely be called before the merge. Their entire purpose is to check if
/// the merge has happened or if we're on the transition block. Thus we don't want to propagate
/// errors from the `BeaconState` being an earlier variant than `BeaconStateBellatrix` as we'd have to
/// repeatedly write code to treat these errors as false.
/// https://github.com/ethereum/consensus-specs/blob/dev/specs/bellatrix/beacon-chain.md#is_merge_transition_complete
pub fn is_merge_transition_complete<E: EthSpec>(state: &BeaconState<E>) -> bool {
    // TODO(EIP7732): check this cause potuz modified this function for god knows what reason
    if state.fork_name_unchecked().capella_enabled() {
        true
    } else if state.fork_name_unchecked().bellatrix_enabled() {
        // We must check defaultness against the payload header with 0x0 roots, as that's what's meant
        // by `ExecutionPayloadHeader()` in the spec.
        state
            .latest_execution_payload_header()
            .map(|header| !header.is_default_with_zero_roots())
            .unwrap_or(false)
    } else {
        false
    }
}
/// https://github.com/ethereum/consensus-specs/blob/dev/specs/bellatrix/beacon-chain.md#is_merge_transition_block
pub fn is_merge_transition_block<E: EthSpec, Payload: AbstractExecPayload<E>>(
    state: &BeaconState<E>,
    body: BeaconBlockBodyRef<E, Payload>,
) -> bool {
    // For execution payloads in blocks (which may be headers) we must check defaultness against
    // the payload with `transactions_root` equal to the tree hash of the empty list.
    body.execution_payload()
        .map(|payload| {
            !is_merge_transition_complete(state) && !payload.is_default_with_empty_roots()
        })
        .unwrap_or(false)
}
/// https://github.com/ethereum/consensus-specs/blob/dev/specs/bellatrix/beacon-chain.md#is_execution_enabled
pub fn is_execution_enabled<E: EthSpec, Payload: AbstractExecPayload<E>>(
    state: &BeaconState<E>,
    body: BeaconBlockBodyRef<E, Payload>,
) -> bool {
    is_merge_transition_block(state, body) || is_merge_transition_complete(state)
}

/// https://github.com/ethereum/consensus-specs/blob/dev/specs/bellatrix/beacon-chain.md#compute_timestamp_at_slot
pub fn compute_timestamp_at_slot<E: EthSpec>(
    state: &BeaconState<E>,
    block_slot: Slot,
    spec: &ChainSpec,
) -> Result<u64, ArithError> {
    let slots_since_genesis = block_slot.as_u64().safe_sub(spec.genesis_slot.as_u64())?;
    slots_since_genesis
        .safe_mul(spec.get_slot_duration().as_secs())
        .and_then(|since_genesis| state.genesis_time().safe_add(since_genesis))
}

/// Process the parent block's deferred execution payload effects.
///
/// This implements the spec's `process_parent_execution_payload` function, which validates
/// the parent execution requests and delegates to `apply_parent_execution_payload` if the
/// parent block was full. This is called at the beginning of block processing, before
/// `process_block_header`.
///
/// `process_parent_execution_payload` must be called before `process_execution_payload_bid`
/// (which overwrites `state.latest_execution_payload_bid`).
pub fn process_parent_execution_payload<E: EthSpec, Payload: AbstractExecPayload<E>>(
    state: &mut BeaconState<E>,
    block: BeaconBlockRef<'_, E, Payload>,
    spec: &ChainSpec,
) -> Result<(), BlockProcessingError> {
    let bid_parent_block_hash = block
        .body()
        .signed_execution_payload_bid()?
        .message
        .parent_block_hash;
    let parent_bid = state.latest_execution_payload_bid()?;
    let requests = block.body().parent_execution_requests()?;

    if bid_parent_block_hash != parent_bid.block_hash {
        // Parent was EMPTY -- no execution requests expected
        block_verify!(
            *requests == ExecutionRequests::default(),
            BlockProcessingError::NonEmptyParentExecutionRequests
        );
        return Ok(());
    }

    // Parent was FULL -- verify the bid commitment and apply the payload
    let requests_root = requests.tree_hash_root();
    block_verify!(
        requests_root == parent_bid.execution_requests_root,
        BlockProcessingError::ExecutionRequestsRootMismatch {
            expected: parent_bid.execution_requests_root,
            found: requests_root,
        }
    );

    apply_parent_execution_payload(state, requests, spec)
}

/// Apply the parent execution payload's deferred effects to the state.
///
/// This implements the spec's `apply_parent_execution_payload` function:
/// 1. Processes deposits, withdrawals, and consolidations from execution requests
/// 2. Queues the builder pending payment from the parent's committed bid
/// 3. Updates `execution_payload_availability` and `latest_block_hash`
pub fn apply_parent_execution_payload<E: EthSpec>(
    state: &mut BeaconState<E>,
    requests: &ExecutionRequests<E>,
    spec: &ChainSpec,
) -> Result<(), BlockProcessingError> {
    let parent_bid = state.latest_execution_payload_bid()?.clone();
    let parent_slot = parent_bid.slot;
    let parent_epoch = parent_slot.epoch(E::slots_per_epoch());

    // Process execution requests from the parent's payload
    process_operations::process_deposit_requests_post_gloas(state, &requests.deposits, spec)?;
    process_operations::process_withdrawal_requests(state, &requests.withdrawals, spec)?;
    process_operations::process_consolidation_requests(state, &requests.consolidations, spec)?;

    // Queue the builder payment
    if parent_epoch == state.current_epoch() {
        let payment_index = E::slots_per_epoch()
            .safe_add(parent_slot.as_u64().safe_rem(E::slots_per_epoch())?)?
            as usize;
        settle_builder_payment(state, payment_index)?;
    } else if parent_epoch == state.previous_epoch() {
        let payment_index = parent_slot.as_u64().safe_rem(E::slots_per_epoch())? as usize;
        settle_builder_payment(state, payment_index)?;
    } else if parent_bid.value > 0 {
        // Parent is older than previous epoch -- payment entry has already been
        // settled or evicted by process_builder_pending_payments at epoch boundaries.
        // Append the withdrawal directly from the bid.
        state
            .builder_pending_withdrawals_mut()?
            .push(BuilderPendingWithdrawal {
                fee_recipient: parent_bid.fee_recipient,
                amount: parent_bid.value,
                builder_index: parent_bid.builder_index,
            })
            .map_err(|e| BlockProcessingError::BeaconStateError(e.into()))?;
    }

    // Update execution payload availability for the parent slot
    let availability_index = parent_slot
        .as_usize()
        .safe_rem(E::slots_per_historical_root())?;
    state
        .execution_payload_availability_mut()?
        .set(availability_index, true)
        .map_err(BlockProcessingError::BitfieldError)?;

    // Update latest_block_hash to the parent bid's block_hash
    *state.latest_block_hash_mut()? = parent_bid.block_hash;

    Ok(())
}

/// Spec: `settle_builder_payment`.
///
/// Moves a pending payment from `builder_pending_payments[payment_index]` into
/// `builder_pending_withdrawals`, then clears the slot.
pub fn settle_builder_payment<E: EthSpec>(
    state: &mut BeaconState<E>,
    payment_index: usize,
) -> Result<(), BlockProcessingError> {
    let payment_mut = state
        .builder_pending_payments_mut()?
        .get_mut(payment_index)
        .ok_or(BlockProcessingError::BuilderPaymentIndexOutOfBounds(
            payment_index,
        ))?;

    let withdrawal = payment_mut.withdrawal.clone();
    *payment_mut = BuilderPendingPayment::default();

    if withdrawal.amount > 0 {
        state
            .builder_pending_withdrawals_mut()?
            .push(withdrawal)
            .map_err(|e| BlockProcessingError::BeaconStateError(e.into()))?;
    }

    Ok(())
}

pub fn process_execution_payload_bid<E: EthSpec, Payload: AbstractExecPayload<E>>(
    state: &mut BeaconState<E>,
    block: BeaconBlockRef<'_, E, Payload>,
    verify_signatures: VerifySignatures,
    spec: &ChainSpec,
) -> Result<(), BlockProcessingError> {
    // Verify the bid signature
    let signed_bid = block.body().signed_execution_payload_bid()?;

    let bid = &signed_bid.message;
    let amount = bid.value;
    let builder_index = bid.builder_index;

    // For self-builds, amount must be zero regardless of withdrawal credential prefix
    if builder_index == BUILDER_INDEX_SELF_BUILD {
        block_verify!(
            amount == 0,
            ExecutionPayloadBidInvalid::SelfBuildNonZeroAmount.into()
        );
        block_verify!(
            signed_bid.signature.is_infinity(),
            ExecutionPayloadBidInvalid::BadSignature.into()
        );
    } else {
        let builder = state.get_builder(builder_index)?;

        // Verify that the builder is active
        block_verify!(
            state.is_active_builder(builder_index, spec)?,
            ExecutionPayloadBidInvalid::BuilderNotActive(builder_index).into()
        );

        // Verify that the builder has funds to cover the bid
        block_verify!(
            state.can_builder_cover_bid(builder_index, amount, spec)?,
            ExecutionPayloadBidInvalid::InsufficientBalance {
                builder_index,
                builder_balance: builder.balance,
                bid_value: amount,
            }
            .into()
        );

        if verify_signatures.is_true() {
            block_verify!(
                // We know this is NOT a self-build, so there MUST be a signature set (func does not
                // return None).
                execution_payload_bid_signature_set(
                    state,
                    |i| get_builder_pubkey_from_state(state, i),
                    signed_bid,
                    spec
                )?
                .ok_or(ExecutionPayloadBidInvalid::BadSignature)?
                .verify(),
                ExecutionPayloadBidInvalid::BadSignature.into()
            );
        }
    }

    // Verify commitments are under limit
    let max_blobs_per_block = spec.max_blobs_per_block(state.current_epoch()) as usize;
    block_verify!(
        bid.blob_kzg_commitments.len() <= max_blobs_per_block,
        ExecutionPayloadBidInvalid::ExcessBlobCommitments {
            max: max_blobs_per_block,
            bid: bid.blob_kzg_commitments.len(),
        }
        .into()
    );

    // Verify that the bid is for the current slot
    block_verify!(
        bid.slot == block.slot(),
        ExecutionPayloadBidInvalid::SlotMismatch {
            bid_slot: bid.slot,
            block_slot: block.slot(),
        }
        .into()
    );

    // Verify that the bid is for the right parent block
    let latest_block_hash = state.latest_block_hash()?;
    block_verify!(
        bid.parent_block_hash == *latest_block_hash,
        ExecutionPayloadBidInvalid::ParentBlockHashMismatch {
            state_block_hash: *latest_block_hash,
            bid_parent_hash: bid.parent_block_hash,
        }
        .into()
    );

    block_verify!(
        bid.parent_block_root == block.parent_root(),
        ExecutionPayloadBidInvalid::ParentBlockRootMismatch {
            block_parent_root: block.parent_root(),
            bid_parent_root: bid.parent_block_root,
        }
        .into()
    );

    let expected_randao = *state.get_randao_mix(state.current_epoch())?;
    block_verify!(
        bid.prev_randao == expected_randao,
        ExecutionPayloadBidInvalid::PrevRandaoMismatch {
            expected: expected_randao,
            bid: bid.prev_randao,
        }
        .into()
    );

    // Record the pending payment if there is some payment
    if amount > 0 {
        let pending_payment = BuilderPendingPayment {
            weight: 0,
            withdrawal: BuilderPendingWithdrawal {
                fee_recipient: bid.fee_recipient,
                amount,
                builder_index,
            },
        };

        let payment_index = E::SlotsPerEpoch::to_usize()
            .safe_add(bid.slot.as_usize().safe_rem(E::SlotsPerEpoch::to_usize())?)?;

        *state
            .builder_pending_payments_mut()?
            .get_mut(payment_index)
            .ok_or(BlockProcessingError::BeaconStateError(
                BeaconStateError::InvalidBuilderPendingPaymentsIndex(payment_index),
            ))? = pending_payment;
    }

    // Cache the execution bid
    *state.latest_execution_payload_bid_mut()? = bid.clone();

    Ok(())
}
