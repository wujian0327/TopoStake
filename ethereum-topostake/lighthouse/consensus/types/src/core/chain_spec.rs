use std::{
    collections::{HashMap, HashSet},
    env,
    fs::File,
    path::Path,
    sync::{OnceLock, RwLock},
    time::Duration,
};

use educe::Educe;
use ethereum_hashing::hash;
use fixed_bytes::FixedBytesExtended;
use int_to_bytes::int_to_bytes4;
use safe_arith::{ArithError, SafeArith};
use serde::{Deserialize, Deserializer, Serialize, Serializer};
use serde_utils::quoted_u64::MaybeQuoted;
use ssz::Encode;
use ssz_types::RuntimeVariableList;
use tree_hash::TreeHash;

use crate::{
    consts::bellatrix::BASIS_POINTS,
    core::{
        APPLICATION_DOMAIN_BUILDER, Address, ApplicationDomain, EnrForkId, Epoch, EthSpec,
        EthSpecId, ExecutionBlockHash, Hash256, MainnetEthSpec, Slot, Uint256,
    },
    fork::{Fork, ForkData, ForkName},
    graffiti::Graffiti,
};

pub const TOPOSTAKE_FIXED_POINT_SCALE: u64 = 1_000_000_000;
pub const TOPOSTAKE_GRAFFITI_EVIDENCE_PREFIX: &str = "TPS1:";

/// Each of the BLS signature domains.
#[derive(Debug, PartialEq, Clone, Copy)]
pub enum Domain {
    BlsToExecutionChange,
    BeaconProposer,
    BeaconAttester,
    Randao,
    Deposit,
    VoluntaryExit,
    SelectionProof,
    AggregateAndProof,
    SyncCommittee,
    ContributionAndProof,
    SyncCommitteeSelectionProof,
    BeaconBuilder,
    PTCAttester,
    ProposerPreferences,
    ApplicationMask(ApplicationDomain),
}

/// Lighthouse's internal configuration struct.
///
/// Contains a mixture of "preset" and "config" values w.r.t to the EF definitions.
#[cfg_attr(feature = "arbitrary", derive(arbitrary::Arbitrary))]
#[derive(PartialEq, Debug, Clone)]
pub struct ChainSpec {
    /*
     * Config name
     */
    pub config_name: Option<String>,

    /*
     * Constants
     */
    pub genesis_slot: Slot,
    pub far_future_epoch: Epoch,
    pub base_rewards_per_epoch: u64,
    pub deposit_contract_tree_depth: u64,

    /*
     * Misc
     */
    pub max_committees_per_slot: usize,
    pub target_committee_size: usize,
    pub min_per_epoch_churn_limit: u64,
    pub max_per_epoch_activation_churn_limit: u64,
    pub churn_limit_quotient: u64,
    pub shuffle_round_count: u8,
    pub min_genesis_active_validator_count: u64,
    pub min_genesis_time: u64,
    pub hysteresis_quotient: u64,
    pub hysteresis_downward_multiplier: u64,
    pub hysteresis_upward_multiplier: u64,
    pub proportional_slashing_multiplier: u64,

    /*
     *  Gwei values
     */
    pub min_deposit_amount: u64,
    pub max_effective_balance: u64,
    pub ejection_balance: u64,
    pub effective_balance_increment: u64,

    /*
     * Initial Values
     */
    pub genesis_fork_version: [u8; 4],
    pub bls_withdrawal_prefix_byte: u8,
    pub eth1_address_withdrawal_prefix_byte: u8,
    pub compounding_withdrawal_prefix_byte: u8,
    pub builder_withdrawal_prefix_byte: u8,

    /*
     * Time parameters
     */
    pub genesis_delay: u64,
    seconds_per_slot: u64,
    // Private so that this value can't get changed except via the `set_slot_duration_ms` function.
    slot_duration_ms: u64,
    pub min_attestation_inclusion_delay: u64,
    pub min_seed_lookahead: Epoch,
    pub max_seed_lookahead: Epoch,
    pub min_epochs_to_inactivity_penalty: u64,
    pub min_validator_withdrawability_delay: Epoch,
    pub shard_committee_period: u64,
    pub proposer_reorg_cutoff_bps: u64,
    pub attestation_due_bps: u64,
    pub attestation_due_bps_gloas: u64,
    pub payload_due_bps: u64,
    pub payload_attestation_due_bps: u64,
    pub aggregate_due_bps: u64,
    pub sync_message_due_bps: u64,
    pub contribution_due_bps: u64,

    /*
     * Derived time values (computed at startup via `compute_derived_values()`)
     */
    pub unaggregated_attestation_due: Duration,
    pub unaggregated_attestation_due_gloas: Duration,
    pub payload_due: Duration,
    pub payload_attestation_due: Duration,
    pub aggregate_attestation_due: Duration,
    pub sync_message_due: Duration,
    pub contribution_and_proof_due: Duration,

    /*
     * Reward and penalty quotients
     */
    pub base_reward_factor: u64,
    pub whistleblower_reward_quotient: u64,
    pub proposer_reward_quotient: u64,
    pub inactivity_penalty_quotient: u64,
    pub min_slashing_penalty_quotient: u64,

    /*
     * Signature domains
     */
    pub(crate) domain_beacon_proposer: u32,
    pub(crate) domain_beacon_attester: u32,
    pub(crate) domain_randao: u32,
    pub(crate) domain_deposit: u32,
    pub(crate) domain_voluntary_exit: u32,
    pub(crate) domain_selection_proof: u32,
    pub(crate) domain_aggregate_and_proof: u32,
    pub(crate) domain_beacon_builder: u32,
    pub(crate) domain_ptc_attester: u32,
    pub(crate) domain_proposer_preferences: u32,

    /*
     * Fork choice
     */
    pub proposer_score_boost: u64,
    pub reorg_head_weight_threshold: u64,
    pub reorg_parent_weight_threshold: u64,
    pub reorg_max_epochs_since_finalization: u64,

    /*
     * Eth1
     */
    pub eth1_follow_distance: u64,
    pub seconds_per_eth1_block: u64,
    pub deposit_chain_id: u64,
    pub deposit_network_id: u64,
    pub deposit_contract_address: Address,

    /*
     * Execution Specs
     */
    pub gas_limit_adjustment_factor: u64,

    /*
     * Altair hard fork params
     */
    pub inactivity_penalty_quotient_altair: u64,
    pub min_slashing_penalty_quotient_altair: u64,
    pub proportional_slashing_multiplier_altair: u64,
    pub epochs_per_sync_committee_period: Epoch,
    pub inactivity_score_bias: u64,
    pub inactivity_score_recovery_rate: u64,
    pub min_sync_committee_participants: u64,
    pub update_timeout: u64,
    pub(crate) domain_sync_committee: u32,
    pub(crate) domain_sync_committee_selection_proof: u32,
    pub(crate) domain_contribution_and_proof: u32,
    pub altair_fork_version: [u8; 4],
    /// The Altair fork epoch is optional, with `None` representing "Altair never happens".
    pub altair_fork_epoch: Option<Epoch>,

    /*
     * Bellatrix hard fork params
     */
    pub inactivity_penalty_quotient_bellatrix: u64,
    pub min_slashing_penalty_quotient_bellatrix: u64,
    pub proportional_slashing_multiplier_bellatrix: u64,
    pub bellatrix_fork_version: [u8; 4],
    /// The Bellatrix fork epoch is optional, with `None` representing "Bellatrix never happens".
    pub bellatrix_fork_epoch: Option<Epoch>,
    pub terminal_total_difficulty: Uint256,
    pub terminal_block_hash: ExecutionBlockHash,
    pub terminal_block_hash_activation_epoch: Epoch,

    /*
     * Capella hard fork params
     */
    pub capella_fork_version: [u8; 4],
    /// The Capella fork epoch is optional, with `None` representing "Capella never happens".
    pub capella_fork_epoch: Option<Epoch>,
    pub max_validators_per_withdrawals_sweep: u64,

    /*
     * Deneb hard fork params
     */
    pub deneb_fork_version: [u8; 4],
    pub deneb_fork_epoch: Option<Epoch>,

    /*
     * Electra hard fork params
     */
    pub electra_fork_version: [u8; 4],
    /// The Electra fork epoch is optional, with `None` representing "Electra never happens".
    pub electra_fork_epoch: Option<Epoch>,
    pub unset_deposit_requests_start_index: u64,
    pub full_exit_request_amount: u64,
    pub min_activation_balance: u64,
    pub max_effective_balance_electra: u64,
    pub min_slashing_penalty_quotient_electra: u64,
    pub whistleblower_reward_quotient_electra: u64,
    pub max_pending_partials_per_withdrawals_sweep: u64,
    pub min_per_epoch_churn_limit_electra: u64,
    pub max_per_epoch_activation_exit_churn_limit: u64,

    /*
     * Fulu hard fork params
     */
    pub fulu_fork_version: [u8; 4],
    /// The Fulu fork epoch is optional, with `None` representing "Fulu never happens".
    pub fulu_fork_epoch: Option<Epoch>,
    pub number_of_custody_groups: u64,
    pub data_column_sidecar_subnet_count: u64,
    pub samples_per_slot: u64,
    pub custody_requirement: u64,
    pub validator_custody_requirement: u64,
    pub balance_per_additional_custody_group: u64,

    /*
     * Gloas hard fork params
     */
    pub gloas_fork_version: [u8; 4],
    /// The Gloas fork epoch is optional, with `None` representing "Gloas never happens".
    pub gloas_fork_epoch: Option<Epoch>,
    pub builder_payment_threshold_numerator: u64,
    pub builder_payment_threshold_denominator: u64,
    pub min_builder_withdrawability_delay: Epoch,
    pub churn_limit_quotient_gloas: u64,
    pub consolidation_churn_limit_quotient: u64,
    pub max_per_epoch_activation_churn_limit_gloas: u64,

    /*
     * TopoStake devnet-only fork params.
     *
     * These fields are config-only in the Prompt 10 minimal fork. They are not
     * embedded in BeaconState SSZ and therefore do not affect state roots, while
     * fork-gated proposer selection can read the deterministic score fixture.
     */
    pub topostake_config: TopoStakeConfig,

    /*
     * Networking
     */
    pub boot_nodes: Vec<String>,
    pub network_id: u8,
    pub target_aggregators_per_committee: u64,
    pub max_payload_size: u64,
    max_request_blocks: u64,
    pub min_epochs_for_block_requests: u64,
    pub ttfb_timeout: u64,
    pub resp_timeout: u64,
    pub attestation_propagation_slot_range: u64,
    pub maximum_gossip_clock_disparity: u64,
    pub message_domain_invalid_snappy: [u8; 4],
    pub message_domain_valid_snappy: [u8; 4],
    pub subnets_per_node: u8,
    pub epochs_per_subnet_subscription: u64,
    pub attestation_subnet_count: u64,
    pub attestation_subnet_extra_bits: u8,
    pub attestation_subnet_prefix_bits: u8,

    /*
     * Networking Deneb
     */
    max_request_blocks_deneb: u64,
    max_request_blob_sidecars: u64,
    pub max_request_data_column_sidecars: u64,
    pub min_epochs_for_blob_sidecars_requests: u64,
    blob_sidecar_subnet_count: u64,
    max_blobs_per_block: u64,

    /*
     * Networking Electra
     */
    max_blobs_per_block_electra: u64,
    blob_sidecar_subnet_count_electra: u64,
    max_request_blob_sidecars_electra: u64,

    /*
     * Networking Fulu
     */
    pub(crate) blob_schedule: BlobSchedule,
    pub min_epochs_for_data_column_sidecars_requests: u64,

    /*
     * Networking Gloas
     */
    pub max_request_payloads: u64,

    /*
     * Networking Derived
     *
     * When adding fields here, make sure any values are derived again during `apply_to_chain_spec`.
     */
    pub max_blocks_by_root_request: usize,
    pub max_blocks_by_root_request_deneb: usize,
    pub max_blobs_by_root_request: usize,
    pub max_data_columns_by_root_request: usize,
    pub max_payload_envelopes_by_root_request: usize,

    /*
     * Application params
     */
    pub(crate) domain_application_mask: u32,

    /*
     * Capella params
     */
    pub(crate) domain_bls_to_execution_change: u32,
}

impl ChainSpec {
    /// Construct a `ChainSpec` from a standard config.
    pub fn from_config<E: EthSpec>(config: &Config) -> Option<Self> {
        let spec = E::default_spec();
        config.apply_to_chain_spec::<E>(&spec)
    }

    /// Returns an `EnrForkId` for the given `slot`.
    pub fn enr_fork_id<E: EthSpec>(
        &self,
        slot: Slot,
        genesis_validators_root: Hash256,
    ) -> EnrForkId {
        EnrForkId {
            fork_digest: self
                .compute_fork_digest(genesis_validators_root, slot.epoch(E::slots_per_epoch())),
            next_fork_version: self.next_fork_version::<E>(slot),
            next_fork_epoch: self
                .next_digest_epoch(slot.epoch(E::slots_per_epoch()))
                .unwrap_or(self.far_future_epoch),
        }
    }

    /// Returns the `next_fork_version`.
    ///
    /// `next_fork_version = current_fork_version` if no future fork is planned,
    pub fn next_fork_version<E: EthSpec>(&self, slot: Slot) -> [u8; 4] {
        match self.next_fork_epoch::<E>(slot) {
            Some((fork, _)) => self.fork_version_for_name(fork),
            None => self.fork_version_for_name(self.fork_name_at_slot::<E>(slot)),
        }
    }

    /// Returns the epoch of the next scheduled fork along with its corresponding `ForkName`.
    ///
    /// If no future forks are scheduled, this function returns `None`.
    pub fn next_fork_epoch<E: EthSpec>(&self, slot: Slot) -> Option<(ForkName, Epoch)> {
        let current_fork_name = self.fork_name_at_slot::<E>(slot);
        let next_fork_name = current_fork_name.next_fork()?;
        let fork_epoch = self.fork_epoch(next_fork_name)?;
        Some((next_fork_name, fork_epoch))
    }

    /// Returns the name of the fork which is active at `slot`.
    pub fn fork_name_at_slot<E: EthSpec>(&self, slot: Slot) -> ForkName {
        self.fork_name_at_epoch(slot.epoch(E::slots_per_epoch()))
    }

    /// Returns the name of the fork which is active at `epoch`.
    pub fn fork_name_at_epoch(&self, epoch: Epoch) -> ForkName {
        let forks = [
            (self.gloas_fork_epoch, ForkName::Gloas),
            (self.fulu_fork_epoch, ForkName::Fulu),
            (self.electra_fork_epoch, ForkName::Electra),
            (self.deneb_fork_epoch, ForkName::Deneb),
            (self.capella_fork_epoch, ForkName::Capella),
            (self.bellatrix_fork_epoch, ForkName::Bellatrix),
            (self.altair_fork_epoch, ForkName::Altair),
        ];

        // Find the first fork where `epoch` is >= `fork_epoch`.
        for (fork_epoch_opt, fork_name) in forks.iter() {
            if let Some(fork_epoch) = fork_epoch_opt
                && epoch >= *fork_epoch
            {
                return *fork_name;
            }
        }

        ForkName::Base
    }

    /// Returns the fork version for a named fork.
    pub fn fork_version_for_name(&self, fork_name: ForkName) -> [u8; 4] {
        match fork_name {
            ForkName::Base => self.genesis_fork_version,
            ForkName::Altair => self.altair_fork_version,
            ForkName::Bellatrix => self.bellatrix_fork_version,
            ForkName::Capella => self.capella_fork_version,
            ForkName::Deneb => self.deneb_fork_version,
            ForkName::Electra => self.electra_fork_version,
            ForkName::Fulu => self.fulu_fork_version,
            ForkName::Gloas => self.gloas_fork_version,
        }
    }

    // This is `compute_fork_version` in the spec
    pub fn fork_version_for_epoch(&self, epoch: Epoch) -> [u8; 4] {
        self.fork_version_for_name(self.fork_name_at_epoch(epoch))
    }

    /// For a given fork name, return the epoch at which it activates.
    pub fn fork_epoch(&self, fork_name: ForkName) -> Option<Epoch> {
        match fork_name {
            ForkName::Base => Some(Epoch::new(0)),
            ForkName::Altair => self.altair_fork_epoch,
            ForkName::Bellatrix => self.bellatrix_fork_epoch,
            ForkName::Capella => self.capella_fork_epoch,
            ForkName::Deneb => self.deneb_fork_epoch,
            ForkName::Electra => self.electra_fork_epoch,
            ForkName::Fulu => self.fulu_fork_epoch,
            ForkName::Gloas => self.gloas_fork_epoch,
        }
    }

    pub fn inactivity_penalty_quotient_for_fork(&self, fork_name: ForkName) -> u64 {
        if fork_name >= ForkName::Bellatrix {
            self.inactivity_penalty_quotient_bellatrix
        } else if fork_name >= ForkName::Altair {
            self.inactivity_penalty_quotient_altair
        } else {
            self.inactivity_penalty_quotient
        }
    }

    pub fn max_effective_balance_for_fork(&self, fork_name: ForkName) -> u64 {
        if fork_name.electra_enabled() {
            self.max_effective_balance_electra
        } else {
            self.max_effective_balance
        }
    }

    /// Returns true if the given epoch is greater than or equal to the `FULU_FORK_EPOCH`.
    pub fn is_peer_das_enabled_for_epoch(&self, block_epoch: Epoch) -> bool {
        self.fulu_fork_epoch
            .is_some_and(|fulu_fork_epoch| block_epoch >= fulu_fork_epoch)
    }

    /// Returns true if PeerDAS is scheduled. Alias for [`Self::is_fulu_scheduled`]
    pub fn is_peer_das_scheduled(&self) -> bool {
        self.is_fulu_scheduled()
    }

    /// Returns true if `FULU_FORK_EPOCH` is set and is not set to `FAR_FUTURE_EPOCH`.
    pub fn is_fulu_scheduled(&self) -> bool {
        self.fulu_fork_epoch
            .is_some_and(|fulu_fork_epoch| fulu_fork_epoch != self.far_future_epoch)
    }

    /// Returns true if `GLOAS_FORK_EPOCH` is set and is not set to `FAR_FUTURE_EPOCH`.
    pub fn is_gloas_scheduled(&self) -> bool {
        self.gloas_fork_epoch
            .is_some_and(|gloas_fork_epoch| gloas_fork_epoch != self.far_future_epoch)
    }

    /// Returns true if the devnet-only TopoStake consensus skeleton is active.
    ///
    /// The current minimal TopoStake fork gates config/state skeleton access and
    /// proposer selection. It does not alter rewards, block processing, or
    /// BeaconState SSZ.
    pub fn is_topostake_enabled_at_epoch(&self, epoch: Epoch) -> bool {
        self.topostake_config.is_enabled_at_epoch(epoch)
    }

    /// Returns a full `Fork` struct for a given epoch.
    pub fn fork_at_epoch(&self, epoch: Epoch) -> Fork {
        let current_fork_name = self.fork_name_at_epoch(epoch);

        let fork_epoch = self
            .fork_epoch(current_fork_name)
            .unwrap_or_else(|| Epoch::new(0));

        // At genesis the Fork is initialised with two copies of the same value for both
        // `previous_version` and `current_version` (see `initialize_beacon_state_from_eth1`).
        let previous_fork_name = if fork_epoch == 0 {
            current_fork_name
        } else {
            current_fork_name.previous_fork().unwrap_or(ForkName::Base)
        };

        Fork {
            previous_version: self.fork_version_for_name(previous_fork_name),
            current_version: self.fork_version_for_name(current_fork_name),
            epoch: fork_epoch,
        }
    }

    /// Returns a full `Fork` struct for a given `ForkName` or `None` if the fork does not yet have
    /// an activation epoch.
    pub fn fork_for_name(&self, fork_name: ForkName) -> Option<Fork> {
        let previous_fork_name = fork_name.previous_fork().unwrap_or(ForkName::Base);
        let epoch = self.fork_epoch(fork_name)?;

        Some(Fork {
            previous_version: self.fork_version_for_name(previous_fork_name),
            current_version: self.fork_version_for_name(fork_name),
            epoch,
        })
    }

    /// Get the domain number, unmodified by the fork.
    ///
    /// Spec v0.12.1
    pub fn get_domain_constant(&self, domain: Domain) -> u32 {
        match domain {
            Domain::BeaconProposer => self.domain_beacon_proposer,
            Domain::BeaconAttester => self.domain_beacon_attester,
            Domain::Randao => self.domain_randao,
            Domain::Deposit => self.domain_deposit,
            Domain::VoluntaryExit => self.domain_voluntary_exit,
            Domain::SelectionProof => self.domain_selection_proof,
            Domain::AggregateAndProof => self.domain_aggregate_and_proof,
            Domain::BeaconBuilder => self.domain_beacon_builder,
            Domain::PTCAttester => self.domain_ptc_attester,
            Domain::ProposerPreferences => self.domain_proposer_preferences,
            Domain::SyncCommittee => self.domain_sync_committee,
            Domain::ContributionAndProof => self.domain_contribution_and_proof,
            Domain::SyncCommitteeSelectionProof => self.domain_sync_committee_selection_proof,
            Domain::ApplicationMask(application_domain) => application_domain.get_domain_constant(),
            Domain::BlsToExecutionChange => self.domain_bls_to_execution_change,
        }
    }

    /// Get the domain that represents the fork meta and signature domain.
    ///
    /// Spec v0.12.1
    pub fn get_domain(
        &self,
        epoch: Epoch,
        domain: Domain,
        fork: &Fork,
        genesis_validators_root: Hash256,
    ) -> Hash256 {
        let fork_version = fork.get_fork_version(epoch);
        self.compute_domain(domain, fork_version, genesis_validators_root)
    }

    /// Get the domain for a deposit signature.
    ///
    /// Deposits are valid across forks, thus the deposit domain is computed
    /// with the genesis fork version.
    ///
    /// Spec v0.12.1
    pub fn get_deposit_domain(&self) -> Hash256 {
        self.compute_domain(Domain::Deposit, self.genesis_fork_version, Hash256::zero())
    }

    // This should be updated to include the current fork and the genesis validators root, but discussion is ongoing:
    //
    // https://github.com/ethereum/builder-specs/issues/14
    //
    // NOTE: This domain is only used for out-of-protocol block building, DO NOT use it for Gloas/ePBS.
    pub fn get_builder_application_domain(&self) -> Hash256 {
        self.compute_domain(
            Domain::ApplicationMask(ApplicationDomain::Builder),
            self.genesis_fork_version,
            Hash256::zero(),
        )
    }

    /// Return the 32-byte fork data root for the `current_version` and `genesis_validators_root`.
    ///
    /// This is used primarily in signature domains to avoid collisions across forks/chains.
    ///
    /// Spec v0.12.1
    pub fn compute_fork_data_root(
        current_version: [u8; 4],
        genesis_validators_root: Hash256,
    ) -> Hash256 {
        ForkData {
            current_version,
            genesis_validators_root,
        }
        .tree_hash_root()
    }

    /// Return the 4-byte fork digest for the `current_version` and `genesis_validators_root`.
    ///
    /// This is a digest primarily used for domain separation on the p2p layer.
    /// 4-bytes suffices for practical separation of forks/chains.
    pub fn compute_fork_digest(&self, genesis_validators_root: Hash256, epoch: Epoch) -> [u8; 4] {
        let fork_version = self.fork_version_for_epoch(epoch);
        let mut base_digest = [0u8; 4];
        let root = Self::compute_fork_data_root(fork_version, genesis_validators_root);
        base_digest.copy_from_slice(
            root.as_slice()
                .get(0..4)
                .expect("root hash is at least 4 bytes"),
        );

        let Some(blob_parameters) = self.get_blob_parameters(epoch) else {
            return base_digest;
        };

        match self.fulu_fork_epoch {
            Some(fulu_epoch) if epoch >= fulu_epoch => {
                // Concatenate epoch and max_blobs_per_block as u64 bytes
                let mut input = Vec::with_capacity(16);
                input.extend_from_slice(&blob_parameters.epoch.as_u64().to_le_bytes());
                input.extend_from_slice(&blob_parameters.max_blobs_per_block.to_le_bytes());

                // Hash the concatenated bytes
                let hash = hash(&input);

                // XOR the base digest with the first 4 bytes of the hash
                let mut masked_digest = [0u8; 4];
                for (i, (a, b)) in base_digest.iter().zip(hash.iter()).enumerate() {
                    if let Some(x) = masked_digest.get_mut(i) {
                        *x = a ^ b;
                    }
                }
                masked_digest
            }
            _ => base_digest,
        }
    }

    pub fn all_digest_epochs(&self) -> impl std::iter::Iterator<Item = Epoch> {
        let mut relevant_epochs = ForkName::list_all_fork_epochs(self)
            .into_iter()
            .filter_map(|(_, epoch)| epoch)
            .collect::<std::collections::HashSet<_>>();

        if self.is_fulu_scheduled() {
            for blob_parameters in &self.blob_schedule {
                relevant_epochs.insert(blob_parameters.epoch);
            }
        }
        let mut vec = relevant_epochs.into_iter().collect::<Vec<_>>();
        vec.sort();
        vec.into_iter()
    }

    pub fn next_digest_epoch(&self, epoch: Epoch) -> Option<Epoch> {
        match self.fulu_fork_epoch {
            Some(fulu_epoch) if epoch >= fulu_epoch => self
                .all_digest_epochs()
                .find(|digest_epoch| *digest_epoch > epoch),
            _ => self
                .fork_name_at_epoch(epoch)
                .next_fork()
                .and_then(|fork_name| self.fork_epoch(fork_name)),
        }
    }

    /// Compute a domain by applying the given `fork_version`.
    pub fn compute_domain(
        &self,
        domain: Domain,
        fork_version: [u8; 4],
        genesis_validators_root: Hash256,
    ) -> Hash256 {
        let domain_constant = self.get_domain_constant(domain);

        let mut domain = [0; 32];
        domain[0..4].copy_from_slice(&int_to_bytes4(domain_constant));
        domain[4..].copy_from_slice(
            Self::compute_fork_data_root(fork_version, genesis_validators_root)
                .as_slice()
                .get(..28)
                .expect("fork has is 32 bytes so first 28 bytes should exist"),
        );

        Hash256::from(domain)
    }

    /// Compute the epoch used for activations prior to Deneb, and for exits under all forks.
    ///
    /// Spec: https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/beacon-chain.md#compute_activation_exit_epoch
    pub fn compute_activation_exit_epoch(&self, epoch: Epoch) -> Result<Epoch, ArithError> {
        epoch.safe_add(1)?.safe_add(self.max_seed_lookahead)
    }

    pub fn maximum_gossip_clock_disparity(&self) -> Duration {
        Duration::from_millis(self.maximum_gossip_clock_disparity)
    }

    pub fn ttfb_timeout(&self) -> Duration {
        Duration::from_secs(self.ttfb_timeout)
    }

    pub fn resp_timeout(&self) -> Duration {
        Duration::from_secs(self.resp_timeout)
    }

    pub fn max_blocks_by_root_request(&self, fork_name: ForkName) -> usize {
        if fork_name >= ForkName::Deneb {
            self.max_blocks_by_root_request_deneb
        } else {
            self.max_blocks_by_root_request
        }
    }

    pub fn max_request_blocks(&self, fork_name: ForkName) -> usize {
        if fork_name >= ForkName::Deneb {
            self.max_request_blocks_deneb as usize
        } else {
            self.max_request_blocks as usize
        }
    }

    pub fn max_request_payloads(&self) -> usize {
        self.max_request_payloads as usize
    }

    pub fn max_request_blob_sidecars(&self, fork_name: ForkName) -> usize {
        if fork_name.electra_enabled() {
            self.max_request_blob_sidecars_electra as usize
        } else {
            self.max_request_blob_sidecars as usize
        }
    }

    /// Returns the highest possible value for max_request_blobs based on enabled forks.
    ///
    /// This is useful for upper bounds in testing.
    pub fn max_request_blobs_upper_bound(&self) -> usize {
        if self.electra_fork_epoch.is_some() {
            self.max_request_blob_sidecars_electra as usize
        } else {
            self.max_request_blob_sidecars as usize
        }
    }

    /// Return the value of `MAX_BLOBS_PER_BLOCK` for the given `epoch`.
    /// NOTE: this function is *technically* not spec compliant, but
    /// I'm told this is what the other clients are doing for `devnet-0`..
    pub fn max_blobs_per_block(&self, epoch: Epoch) -> u64 {
        match self.fulu_fork_epoch {
            Some(fulu_epoch) if epoch >= fulu_epoch => self
                .blob_schedule
                .max_blobs_for_epoch(epoch)
                .unwrap_or(self.max_blobs_per_block_electra),
            _ => match self.electra_fork_epoch {
                Some(electra_epoch) if epoch >= electra_epoch => self.max_blobs_per_block_electra,
                _ => self.max_blobs_per_block,
            },
        }
    }

    /// Return the blob parameters at a given epoch.
    fn get_blob_parameters(&self, epoch: Epoch) -> Option<BlobParameters> {
        match self.fulu_fork_epoch {
            Some(fulu_epoch) if epoch >= fulu_epoch => self
                .blob_schedule
                .blob_parameters_for_epoch(epoch)
                .or_else(|| {
                    Some(BlobParameters {
                        epoch: self
                            .electra_fork_epoch
                            .expect("electra fork epoch must be set if fulu epoch is set"),
                        max_blobs_per_block: self.max_blobs_per_block_electra,
                    })
                }),
            _ => None,
        }
    }

    // TODO(EIP-7892): remove this once we have fork-version changes on BPO forks
    pub fn max_blobs_per_block_within_fork(&self, fork_name: ForkName) -> u64 {
        if !fork_name.fulu_enabled() {
            if fork_name.electra_enabled() {
                self.max_blobs_per_block_electra
            } else {
                self.max_blobs_per_block
            }
        } else {
            // Find the max blobs per block in the fork schedule
            // This logic will need to be more complex once there are forks beyond Fulu
            let mut max_blobs_per_block = self.max_blobs_per_block_electra;
            for entry in &self.blob_schedule {
                if entry.max_blobs_per_block > max_blobs_per_block {
                    max_blobs_per_block = entry.max_blobs_per_block;
                }
            }
            max_blobs_per_block
        }
    }

    /// Returns the `BLOB_SIDECAR_SUBNET_COUNT` at the given fork_name.
    pub fn blob_sidecar_subnet_count(&self, fork_name: ForkName) -> u64 {
        if fork_name.electra_enabled() {
            self.blob_sidecar_subnet_count_electra
        } else {
            self.blob_sidecar_subnet_count
        }
    }

    /// Returns the highest possible value of blob sidecar subnet count based on enabled forks.
    ///
    /// This is useful for upper bounds for the subnet count during a given run of lighthouse.
    pub fn blob_sidecar_subnet_count_max(&self) -> u64 {
        if self.electra_fork_epoch.is_some() {
            self.blob_sidecar_subnet_count_electra
        } else {
            self.blob_sidecar_subnet_count
        }
    }

    /// Returns the number of data columns per custody group.
    pub fn data_columns_per_group<E: EthSpec>(&self) -> u64 {
        (E::number_of_columns() as u64)
            .safe_div(self.number_of_custody_groups)
            .expect("Custody group count must be greater than 0")
    }

    /// Returns the number of column sidecars to sample per slot.
    pub fn sampling_size_columns<E: EthSpec>(
        &self,
        custody_group_count: u64,
    ) -> Result<usize, String> {
        let sampling_size_groups = self.sampling_size_custody_groups(custody_group_count)?;
        let columns_per_custody_group = self.data_columns_per_group::<E>();

        let sampling_size_columns = columns_per_custody_group
            .safe_mul(sampling_size_groups)
            .map_err(|_| "Computing sampling size should not overflow")?;

        Ok(sampling_size_columns as usize)
    }

    /// Returns the number of custody groups to sample per slot.
    pub fn sampling_size_custody_groups(&self, custody_group_count: u64) -> Result<u64, String> {
        Ok(std::cmp::max(custody_group_count, self.samples_per_slot))
    }

    /// Returns the min epoch for blob / data column sidecar requests based on the current epoch.
    /// Switch to use the column sidecar config once the `blob_retention_epoch` has passed Fulu fork epoch.
    /// Never uses the `blob_retention_epoch` for networks that started with Fulu enabled.
    pub fn min_epoch_data_availability_boundary(&self, current_epoch: Epoch) -> Option<Epoch> {
        let deneb_fork_epoch = self.deneb_fork_epoch?;
        let blob_retention_epoch =
            current_epoch.saturating_sub(self.min_epochs_for_blob_sidecars_requests);
        if let Some(fulu_fork_epoch) = self.fulu_fork_epoch
            && blob_retention_epoch >= fulu_fork_epoch
        {
            Some(current_epoch.saturating_sub(self.min_epochs_for_data_column_sidecars_requests))
        } else {
            Some(std::cmp::max(deneb_fork_epoch, blob_retention_epoch))
        }
    }

    /// Worst-case compressed length for a given payload of size n when using snappy.
    ///
    /// https://github.com/google/snappy/blob/32ded457c0b1fe78ceb8397632c416568d6714a0/snappy.cc#L218C1-L218C47
    /// https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/p2p-interface.md#max_compressed_len
    fn max_compressed_len_snappy(n: usize) -> Option<usize> {
        32_usize.checked_add(n)?.checked_add(n / 6)
    }

    /// Max compressed length of a message that we receive over gossip.
    pub fn max_compressed_len(&self) -> usize {
        Self::max_compressed_len_snappy(self.max_payload_size as usize)
            .expect("should not overflow")
    }

    /// Max allowed size of a raw, compressed message received over the network.
    ///
    /// https://github.com/ethereum/consensus-specs/blob/dev/specs/phase0/p2p-interface.md#max_compressed_len
    pub fn max_message_size(&self) -> usize {
        std::cmp::max(
            // 1024 to account for framing + encoding overhead
            Self::max_compressed_len_snappy(self.max_payload_size as usize)
                .expect("should not overflow")
                .safe_add(1024)
                .expect("should not overflow"),
            //1MB
            1024 * 1024,
        )
    }

    /// Get the duration into a slot in which an unaggregated attestation is due.
    /// Returns the pre-computed value from `compute_derived_values()`.
    pub fn get_unaggregated_attestation_due(&self) -> Duration {
        self.unaggregated_attestation_due
    }

    /// Spec: `get_attestation_due_ms`. Returns the epoch-appropriate threshold.
    pub fn get_attestation_due<E: EthSpec>(&self, slot: Slot) -> Duration {
        if self.fork_name_at_slot::<E>(slot).gloas_enabled() {
            self.unaggregated_attestation_due_gloas
        } else {
            self.unaggregated_attestation_due
        }
    }

    /// Spec: `get_payload_due_ms`.
    pub fn get_payload_due(&self) -> Duration {
        self.payload_due
    }

    /// Spec: `get_payload_attestation_due_ms`.
    pub fn get_payload_attestation_due(&self) -> Duration {
        self.payload_attestation_due
    }

    /// Get the duration into a slot in which an aggregated attestation is due.
    /// Returns the pre-computed value from `compute_derived_values()`.
    pub fn get_aggregate_attestation_due(&self) -> Duration {
        self.aggregate_attestation_due
    }

    /// Get the duration into a slot in which a `SignedContributionAndProof` is due.
    /// Returns the pre-computed value from `compute_derived_values()`.
    pub fn get_contribution_message_due(&self) -> Duration {
        self.contribution_and_proof_due
    }

    /// Get the duration into a slot in which a sync committee message is due.
    /// Returns the pre-computed value from `compute_derived_values()`.
    pub fn get_sync_message_due(&self) -> Duration {
        self.sync_message_due
    }

    /// Calculate the duration into a slot for a given slot component
    pub fn compute_slot_component_duration(
        &self,
        component_basis_points: u64,
    ) -> Result<Duration, ArithError> {
        Ok(Duration::from_millis(
            component_basis_points
                .safe_mul(self.slot_duration_ms)?
                .safe_div(BASIS_POINTS)?,
        ))
    }

    /// Get the duration of a slot
    pub fn get_slot_duration(&self) -> Duration {
        Duration::from_millis(self.slot_duration_ms)
    }

    /// Set the duration of a slot (in ms).
    pub fn set_slot_duration_ms<E: EthSpec>(mut self, slot_duration_ms: u64) -> Self {
        self.slot_duration_ms = slot_duration_ms;
        self.seconds_per_slot = slot_duration_ms.saturating_div(1000);
        self.compute_derived_values::<E>()
    }

    /// Compute values that are derived from other config values.
    ///
    /// Must be called after loading or modifying a ChainSpec's fields.
    ///
    /// Panics if any computation fails (indicates invalid config).
    pub fn compute_derived_values<E: EthSpec>(mut self) -> Self {
        assert!(
            self.attestation_due_bps <= BASIS_POINTS,
            "invalid chain spec: attestation_due_bps ({}) exceeds slot duration",
            self.attestation_due_bps
        );
        assert!(
            self.aggregate_due_bps <= BASIS_POINTS,
            "invalid chain spec: aggregate_due_bps ({}) exceeds slot duration",
            self.aggregate_due_bps
        );
        assert!(
            self.sync_message_due_bps <= BASIS_POINTS,
            "invalid chain spec: sync_message_due_bps ({}) exceeds slot duration",
            self.sync_message_due_bps
        );
        assert!(
            self.contribution_due_bps <= BASIS_POINTS,
            "invalid chain spec: contribution_due_bps ({}) exceeds slot duration",
            self.contribution_due_bps
        );

        self.unaggregated_attestation_due = self
            .compute_slot_component_duration(self.attestation_due_bps)
            .expect("invalid chain spec: cannot compute unaggregated_attestation_due");
        self.unaggregated_attestation_due_gloas = self
            .compute_slot_component_duration(self.attestation_due_bps_gloas)
            .expect("invalid chain spec: cannot compute unaggregated_attestation_due_gloas");
        self.payload_due = self
            .compute_slot_component_duration(self.payload_due_bps)
            .expect("invalid chain spec: cannot compute payload_due");
        self.payload_attestation_due = self
            .compute_slot_component_duration(self.payload_attestation_due_bps)
            .expect("invalid chain spec: cannot compute payload_attestation_due");
        self.aggregate_attestation_due = self
            .compute_slot_component_duration(self.aggregate_due_bps)
            .expect("invalid chain spec: cannot compute aggregate_attestation_due");
        self.sync_message_due = self
            .compute_slot_component_duration(self.sync_message_due_bps)
            .expect("invalid chain spec: cannot compute sync_message_due");
        self.contribution_and_proof_due = self
            .compute_slot_component_duration(self.contribution_due_bps)
            .expect("invalid chain spec: cannot compute contribution_and_proof_due");

        self.attestation_subnet_prefix_bits = compute_attestation_subnet_prefix_bits(
            self.attestation_subnet_count,
            self.attestation_subnet_extra_bits,
        );

        self.max_blocks_by_root_request =
            max_blocks_by_root_request_common(self.max_request_blocks);
        self.max_blocks_by_root_request_deneb =
            max_blocks_by_root_request_common(self.max_request_blocks_deneb);
        self.max_blobs_by_root_request =
            max_blobs_by_root_request_common(self.max_request_blob_sidecars);
        self.max_data_columns_by_root_request =
            max_data_columns_by_root_request_common::<E>(self.max_request_blocks_deneb);
        self.max_payload_envelopes_by_root_request =
            max_blocks_by_root_request_common(self.max_request_payloads);

        self
    }

    /// Returns the slot at which the proposer shuffling was decided.
    ///
    /// The block root at this slot can be used to key the proposer shuffling for the given epoch.
    pub fn proposer_shuffling_decision_slot<E: EthSpec>(&self, epoch: Epoch) -> Slot {
        // At the Fulu fork epoch itself, the shuffling is computed "the old way" with no lookahead.
        // Therefore for `epoch == fulu_fork_epoch` we must take the `else` branch. Checking if Fulu
        // is enabled at `epoch - 1` accomplishes this neatly.
        if self
            .fork_name_at_epoch(epoch.saturating_sub(1_u64))
            .fulu_enabled()
        {
            // Post-Fulu the proposer shuffling decision slot for epoch N is the slot at the end
            // of epoch N - 2 (note: min_seed_lookahead=1 in all current configs).
            epoch
                .saturating_sub(self.min_seed_lookahead)
                .start_slot(E::slots_per_epoch())
                .saturating_sub(1_u64)
        } else {
            // Pre-Fulu the proposer shuffling decision slot for epoch N is the slot at the end of
            // epoch N - 1 (note: +1 -1 for min_seed_lookahead=1 in all current configs).
            epoch
                .saturating_add(Epoch::new(1))
                .saturating_sub(self.min_seed_lookahead)
                .start_slot(E::slots_per_epoch())
                .saturating_sub(1_u64)
        }
    }

    /// Returns a `ChainSpec` compatible with the Ethereum Foundation specification.
    pub fn mainnet() -> Self {
        Self {
            /*
             * Config name
             */
            config_name: Some("mainnet".to_string()),
            /*
             * Constants
             */
            genesis_slot: Slot::new(0),
            far_future_epoch: Epoch::new(u64::MAX),
            base_rewards_per_epoch: 4,
            deposit_contract_tree_depth: 32,

            /*
             * Misc
             */
            max_committees_per_slot: 64,
            target_committee_size: 128,
            min_per_epoch_churn_limit: 4,
            max_per_epoch_activation_churn_limit: 8,
            churn_limit_quotient: 65_536,
            shuffle_round_count: 90,
            min_genesis_active_validator_count: 16_384,
            min_genesis_time: 1606824000, // Dec 1, 2020
            hysteresis_quotient: 4,
            hysteresis_downward_multiplier: 1,
            hysteresis_upward_multiplier: 5,

            /*
             *  Gwei values
             */
            min_deposit_amount: option_wrapper(|| {
                u64::checked_pow(2, 0)?.checked_mul(u64::checked_pow(10, 9)?)
            })
            .expect("calculation does not overflow"),
            max_effective_balance: option_wrapper(|| {
                u64::checked_pow(2, 5)?.checked_mul(u64::checked_pow(10, 9)?)
            })
            .expect("calculation does not overflow"),
            ejection_balance: option_wrapper(|| {
                u64::checked_pow(2, 4)?.checked_mul(u64::checked_pow(10, 9)?)
            })
            .expect("calculation does not overflow"),
            effective_balance_increment: option_wrapper(|| {
                u64::checked_pow(2, 0)?.checked_mul(u64::checked_pow(10, 9)?)
            })
            .expect("calculation does not overflow"),

            /*
             * Initial Values
             */
            genesis_fork_version: [0; 4],
            bls_withdrawal_prefix_byte: 0x00,
            eth1_address_withdrawal_prefix_byte: 0x01,
            compounding_withdrawal_prefix_byte: 0x02,
            builder_withdrawal_prefix_byte: 0x03,

            /*
             * Time parameters
             */
            genesis_delay: 604800, // 7 days
            seconds_per_slot: 12,
            slot_duration_ms: 12000,
            min_attestation_inclusion_delay: 1,
            min_seed_lookahead: Epoch::new(1),
            max_seed_lookahead: Epoch::new(4),
            min_epochs_to_inactivity_penalty: 4,
            min_validator_withdrawability_delay: Epoch::new(256),
            shard_committee_period: 256,
            proposer_reorg_cutoff_bps: 1667,
            attestation_due_bps: 3333,
            attestation_due_bps_gloas: 2500,
            payload_due_bps: 7500,
            payload_attestation_due_bps: 7500,
            aggregate_due_bps: 6667,
            sync_message_due_bps: 3333,
            contribution_due_bps: 6667,

            /*
             * Derived time values (set by `compute_derived_values()`)
             */
            unaggregated_attestation_due: Duration::from_millis(3999),
            unaggregated_attestation_due_gloas: Duration::from_millis(3000),
            payload_due: Duration::from_millis(9000),
            payload_attestation_due: Duration::from_millis(9000),
            aggregate_attestation_due: Duration::from_millis(8000),
            sync_message_due: Duration::from_millis(3999),
            contribution_and_proof_due: Duration::from_millis(8000),

            /*
             * Reward and penalty quotients
             */
            base_reward_factor: 64,
            whistleblower_reward_quotient: 512,
            proposer_reward_quotient: 8,
            inactivity_penalty_quotient: u64::checked_pow(2, 26).expect("pow does not overflow"),
            min_slashing_penalty_quotient: 128,
            proportional_slashing_multiplier: 1,

            /*
             * Signature domains
             */
            domain_beacon_proposer: 0,
            domain_beacon_attester: 1,
            domain_randao: 2,
            domain_deposit: 3,
            domain_voluntary_exit: 4,
            domain_selection_proof: 5,
            domain_aggregate_and_proof: 6,
            domain_beacon_builder: 0x0B,
            domain_ptc_attester: 0x0C,
            domain_proposer_preferences: 0x0D,

            /*
             * Fork choice
             */
            proposer_score_boost: 40,
            reorg_head_weight_threshold: 20,
            reorg_parent_weight_threshold: 160,
            reorg_max_epochs_since_finalization: 2,

            /*
             * Eth1
             */
            eth1_follow_distance: 2048,
            seconds_per_eth1_block: 14,
            deposit_chain_id: 1,
            deposit_network_id: 1,
            deposit_contract_address: "00000000219ab540356cbb839cbe05303d7705fa"
                .parse()
                .expect("chain spec deposit contract address"),

            /*
             * Execution Specs
             */
            gas_limit_adjustment_factor: 1024,

            /*
             * Altair hard fork params
             */
            inactivity_penalty_quotient_altair: option_wrapper(|| {
                u64::checked_pow(2, 24)?.checked_mul(3)
            })
            .expect("calculation does not overflow"),
            min_slashing_penalty_quotient_altair: u64::checked_pow(2, 6)
                .expect("pow does not overflow"),
            proportional_slashing_multiplier_altair: 2,
            inactivity_score_bias: 4,
            inactivity_score_recovery_rate: 16,
            min_sync_committee_participants: 1,
            update_timeout: 8192,
            epochs_per_sync_committee_period: Epoch::new(256),
            domain_sync_committee: 7,
            domain_sync_committee_selection_proof: 8,
            domain_contribution_and_proof: 9,
            altair_fork_version: [0x01, 0x00, 0x00, 0x00],
            altair_fork_epoch: Some(Epoch::new(74240)),

            /*
             * Bellatrix hard fork params
             */
            inactivity_penalty_quotient_bellatrix: u64::checked_pow(2, 24)
                .expect("pow does not overflow"),
            min_slashing_penalty_quotient_bellatrix: u64::checked_pow(2, 5)
                .expect("pow does not overflow"),
            proportional_slashing_multiplier_bellatrix: 3,
            bellatrix_fork_version: [0x02, 0x00, 0x00, 0x00],
            bellatrix_fork_epoch: Some(Epoch::new(144896)),
            terminal_total_difficulty: "58750000000000000000000"
                .parse()
                .expect("terminal_total_difficulty is a valid integer"),
            terminal_block_hash: ExecutionBlockHash::zero(),
            terminal_block_hash_activation_epoch: Epoch::new(u64::MAX),

            /*
             * Capella hard fork params
             */
            capella_fork_version: [0x03, 00, 00, 00],
            capella_fork_epoch: Some(Epoch::new(194048)),
            max_validators_per_withdrawals_sweep: 16384,

            /*
             * Deneb hard fork params
             */
            deneb_fork_version: [0x04, 0x00, 0x00, 0x00],
            deneb_fork_epoch: Some(Epoch::new(269568)),

            /*
             * Electra hard fork params
             */
            electra_fork_version: [0x05, 00, 00, 00],
            electra_fork_epoch: Some(Epoch::new(364032)),
            unset_deposit_requests_start_index: u64::MAX,
            full_exit_request_amount: 0,
            min_activation_balance: option_wrapper(|| {
                u64::checked_pow(2, 5)?.checked_mul(u64::checked_pow(10, 9)?)
            })
            .expect("calculation does not overflow"),
            max_effective_balance_electra: option_wrapper(|| {
                u64::checked_pow(2, 11)?.checked_mul(u64::checked_pow(10, 9)?)
            })
            .expect("calculation does not overflow"),
            min_slashing_penalty_quotient_electra: u64::checked_pow(2, 12)
                .expect("pow does not overflow"),
            whistleblower_reward_quotient_electra: u64::checked_pow(2, 12)
                .expect("pow does not overflow"),
            max_pending_partials_per_withdrawals_sweep: u64::checked_pow(2, 3)
                .expect("pow does not overflow"),
            min_per_epoch_churn_limit_electra: option_wrapper(|| {
                u64::checked_pow(2, 7)?.checked_mul(u64::checked_pow(10, 9)?)
            })
            .expect("calculation does not overflow"),
            max_per_epoch_activation_exit_churn_limit: option_wrapper(|| {
                u64::checked_pow(2, 8)?.checked_mul(u64::checked_pow(10, 9)?)
            })
            .expect("calculation does not overflow"),

            /*
             * Fulu hard fork params
             */
            fulu_fork_version: [0x06, 0x00, 0x00, 0x00],
            fulu_fork_epoch: Some(Epoch::new(411392)),
            custody_requirement: 4,
            number_of_custody_groups: 128,
            data_column_sidecar_subnet_count: 128,
            samples_per_slot: 8,
            validator_custody_requirement: 8,
            balance_per_additional_custody_group: 32000000000,

            /*
             * Gloas hard fork params
             */
            gloas_fork_version: [0x07, 0x00, 0x00, 0x00],
            gloas_fork_epoch: None,
            builder_payment_threshold_numerator: 6,
            builder_payment_threshold_denominator: 10,
            min_builder_withdrawability_delay: Epoch::new(8192),
            churn_limit_quotient_gloas: option_wrapper(|| u64::checked_pow(2, 15))
                .expect("calculation does not overflow"),
            consolidation_churn_limit_quotient: option_wrapper(|| u64::checked_pow(2, 16))
                .expect("calculation does not overflow"),
            max_per_epoch_activation_churn_limit_gloas: option_wrapper(|| {
                u64::checked_pow(2, 8)?.checked_mul(u64::checked_pow(10, 9)?)
            })
            .expect("calculation does not overflow"),
            max_request_payloads: 128,
            topostake_config: TopoStakeConfig::disabled(),

            /*
             * Network specific
             */
            boot_nodes: vec![],
            network_id: 1, // mainnet network id
            attestation_propagation_slot_range: default_attestation_propagation_slot_range(),
            epochs_per_subnet_subscription: 256,
            attestation_subnet_count: 64,
            attestation_subnet_extra_bits: 0,
            subnets_per_node: 2,
            maximum_gossip_clock_disparity: default_maximum_gossip_clock_disparity(),
            target_aggregators_per_committee: 16,
            max_payload_size: default_max_payload_size(),
            min_epochs_for_block_requests: default_min_epochs_for_block_requests(),
            ttfb_timeout: default_ttfb_timeout(),
            resp_timeout: default_resp_timeout(),
            message_domain_invalid_snappy: default_message_domain_invalid_snappy(),
            message_domain_valid_snappy: default_message_domain_valid_snappy(),
            attestation_subnet_prefix_bits: compute_attestation_subnet_prefix_bits(
                default_attestation_subnet_count(),
                default_attestation_subnet_extra_bits(),
            ),
            max_request_blocks: default_max_request_blocks(),

            /*
             * Networking Deneb Specific
             */
            max_request_blocks_deneb: default_max_request_blocks_deneb(),
            max_request_blob_sidecars: default_max_request_blob_sidecars(),
            max_request_data_column_sidecars: default_max_request_data_column_sidecars(),
            min_epochs_for_blob_sidecars_requests: default_min_epochs_for_blob_sidecars_requests(),
            blob_sidecar_subnet_count: default_blob_sidecar_subnet_count(),
            max_blobs_per_block: default_max_blobs_per_block(),

            /*
             * Derived Deneb Specific
             */
            max_blocks_by_root_request: default_max_blocks_by_root_request(),
            max_blocks_by_root_request_deneb: default_max_blocks_by_root_request_deneb(),
            max_blobs_by_root_request: default_max_blobs_by_root_request(),

            /*
             * Networking Electra specific
             */
            max_blobs_per_block_electra: default_max_blobs_per_block_electra(),
            blob_sidecar_subnet_count_electra: default_blob_sidecar_subnet_count_electra(),
            max_request_blob_sidecars_electra: default_max_request_blob_sidecars_electra(),

            /*
             * Networking Fulu specific
             */
            blob_schedule: BlobSchedule::new(vec![
                BlobParameters {
                    epoch: Epoch::new(412672),
                    max_blobs_per_block: 15,
                },
                BlobParameters {
                    epoch: Epoch::new(419072),
                    max_blobs_per_block: 21,
                },
            ]),
            min_epochs_for_data_column_sidecars_requests:
                default_min_epochs_for_data_column_sidecars_requests(),
            max_data_columns_by_root_request: default_data_columns_by_root_request(),
            max_payload_envelopes_by_root_request: default_max_payload_envelopes_by_root_request(),

            /*
             * Application specific
             */
            domain_application_mask: APPLICATION_DOMAIN_BUILDER,

            /*
             * Capella params
             */
            domain_bls_to_execution_change: 10,
        }
    }

    /// Ethereum Foundation minimal spec, as defined in the eth2.0-specs repo.
    pub fn minimal() -> Self {
        // Note: bootnodes to be updated when static nodes exist.
        let boot_nodes = vec![];

        Self {
            config_name: None,
            max_committees_per_slot: 4,
            target_committee_size: 4,
            min_per_epoch_churn_limit: 2,
            max_per_epoch_activation_churn_limit: 4,
            churn_limit_quotient: 32,
            shuffle_round_count: 10,
            min_genesis_active_validator_count: 64,
            min_genesis_time: 1578009600,
            eth1_follow_distance: 16,
            genesis_fork_version: [0x00, 0x00, 0x00, 0x01],
            shard_committee_period: 64,
            genesis_delay: 300,
            seconds_per_slot: 6,
            slot_duration_ms: 6000,
            inactivity_penalty_quotient: u64::checked_pow(2, 25).expect("pow does not overflow"),
            min_slashing_penalty_quotient: 64,
            proportional_slashing_multiplier: 2,
            // Altair
            epochs_per_sync_committee_period: Epoch::new(8),
            update_timeout: 64,
            altair_fork_version: [0x01, 0x00, 0x00, 0x01],
            altair_fork_epoch: None,
            // Bellatrix
            bellatrix_fork_version: [0x02, 0x00, 0x00, 0x01],
            bellatrix_fork_epoch: None,
            terminal_total_difficulty: Uint256::MAX
                .checked_sub(Uint256::from(2u64.pow(10)))
                .expect("subtraction does not overflow")
                // Add 1 since the spec declares `2**256 - 2**10` and we use
                // `Uint256::MAX` which is `2*256- 1`.
                .checked_add(Uint256::from(2u64.pow(0)))
                .expect("addition does not overflow"),
            // Capella
            capella_fork_version: [0x03, 0x00, 0x00, 0x01],
            capella_fork_epoch: None,
            max_validators_per_withdrawals_sweep: 16,
            // Deneb
            deneb_fork_version: [0x04, 0x00, 0x00, 0x01],
            deneb_fork_epoch: None,
            // Electra
            electra_fork_version: [0x05, 0x00, 0x00, 0x01],
            electra_fork_epoch: None,
            max_pending_partials_per_withdrawals_sweep: u64::checked_pow(2, 1)
                .expect("pow does not overflow"),
            min_per_epoch_churn_limit_electra: option_wrapper(|| {
                u64::checked_pow(2, 6)?.checked_mul(u64::checked_pow(10, 9)?)
            })
            .expect("calculation does not overflow"),
            max_per_epoch_activation_exit_churn_limit: option_wrapper(|| {
                u64::checked_pow(2, 7)?.checked_mul(u64::checked_pow(10, 9)?)
            })
            .expect("calculation does not overflow"),
            // Fulu
            fulu_fork_version: [0x06, 0x00, 0x00, 0x01],
            fulu_fork_epoch: None,
            // Gloas
            gloas_fork_version: [0x07, 0x00, 0x00, 0x01],
            gloas_fork_epoch: None,
            min_builder_withdrawability_delay: Epoch::new(2),
            churn_limit_quotient_gloas: option_wrapper(|| u64::checked_pow(2, 4))
                .expect("calculation does not overflow"),
            consolidation_churn_limit_quotient: option_wrapper(|| u64::checked_pow(2, 5))
                .expect("calculation does not overflow"),
            max_per_epoch_activation_churn_limit_gloas: option_wrapper(|| {
                u64::checked_pow(2, 7)?.checked_mul(u64::checked_pow(10, 9)?)
            })
            .expect("calculation does not overflow"),

            /*
             * Derived time values (set by `compute_derived_values()`)
             * Precomputed for 6000ms slot: 3333 bps = 1999ms, 6667 bps = 4000ms
             */
            unaggregated_attestation_due: Duration::from_millis(1999),
            unaggregated_attestation_due_gloas: Duration::from_millis(1500),
            payload_due: Duration::from_millis(4500),
            payload_attestation_due: Duration::from_millis(4500),
            aggregate_attestation_due: Duration::from_millis(4000),
            sync_message_due: Duration::from_millis(1999),
            contribution_and_proof_due: Duration::from_millis(4000),

            // Networking Fulu
            blob_schedule: BlobSchedule::default(),

            // Other
            network_id: 2, // lighthouse testnet network id
            deposit_chain_id: 5,
            deposit_network_id: 5,
            deposit_contract_address: "1234567890123456789012345678901234567890"
                .parse()
                .expect("minimal chain spec deposit address"),
            boot_nodes,
            ..ChainSpec::mainnet()
        }
    }

    /// Returns a `ChainSpec` compatible with the Gnosis Beacon Chain specification.
    pub fn gnosis() -> Self {
        Self {
            config_name: Some("gnosis".to_string()),
            /*
             * Constants
             */
            genesis_slot: Slot::new(0),
            far_future_epoch: Epoch::new(u64::MAX),
            base_rewards_per_epoch: 4,
            deposit_contract_tree_depth: 32,

            /*
             * Misc
             */
            max_committees_per_slot: 64,
            target_committee_size: 128,
            min_per_epoch_churn_limit: 4,
            max_per_epoch_activation_churn_limit: 2,
            churn_limit_quotient: 4_096,
            shuffle_round_count: 90,
            min_genesis_active_validator_count: 4_096,
            min_genesis_time: 1638968400, // Dec 8, 2020
            hysteresis_quotient: 4,
            hysteresis_downward_multiplier: 1,
            hysteresis_upward_multiplier: 5,

            /*
             *  Gwei values
             */
            min_deposit_amount: option_wrapper(|| {
                u64::checked_pow(2, 0)?.checked_mul(u64::checked_pow(10, 9)?)
            })
            .expect("calculation does not overflow"),
            max_effective_balance: option_wrapper(|| {
                u64::checked_pow(2, 5)?.checked_mul(u64::checked_pow(10, 9)?)
            })
            .expect("calculation does not overflow"),
            ejection_balance: option_wrapper(|| {
                u64::checked_pow(2, 4)?.checked_mul(u64::checked_pow(10, 9)?)
            })
            .expect("calculation does not overflow"),
            effective_balance_increment: option_wrapper(|| {
                u64::checked_pow(2, 0)?.checked_mul(u64::checked_pow(10, 9)?)
            })
            .expect("calculation does not overflow"),

            /*
             * Initial Values
             */
            genesis_fork_version: [0x00, 0x00, 0x00, 0x64],
            bls_withdrawal_prefix_byte: 0x00,
            eth1_address_withdrawal_prefix_byte: 0x01,
            compounding_withdrawal_prefix_byte: 0x02,
            builder_withdrawal_prefix_byte: 0x03,

            /*
             * Time parameters
             */
            genesis_delay: 6000, // 100 minutes
            seconds_per_slot: 5,
            slot_duration_ms: 5000,
            min_attestation_inclusion_delay: 1,
            min_seed_lookahead: Epoch::new(1),
            max_seed_lookahead: Epoch::new(4),
            min_epochs_to_inactivity_penalty: 4,
            min_validator_withdrawability_delay: Epoch::new(256),
            shard_committee_period: 256,
            proposer_reorg_cutoff_bps: 1667,
            attestation_due_bps: 3333,
            attestation_due_bps_gloas: 2500,
            payload_due_bps: 7500,
            payload_attestation_due_bps: 7500,
            aggregate_due_bps: 6667,

            /*
             * Derived time values (set by `compute_derived_values()`)
             * Precomputed for 5000ms slot: 3333 bps = 1666ms, 6667 bps = 3333ms
             */
            unaggregated_attestation_due: Duration::from_millis(1666),
            unaggregated_attestation_due_gloas: Duration::from_millis(1250),
            payload_due: Duration::from_millis(3750),
            payload_attestation_due: Duration::from_millis(3750),
            aggregate_attestation_due: Duration::from_millis(3333),
            sync_message_due: Duration::from_millis(1666),
            contribution_and_proof_due: Duration::from_millis(3333),

            /*
             * Reward and penalty quotients
             */
            base_reward_factor: 25,
            whistleblower_reward_quotient: 512,
            proposer_reward_quotient: 8,
            inactivity_penalty_quotient: u64::checked_pow(2, 26).expect("pow does not overflow"),
            min_slashing_penalty_quotient: 128,
            proportional_slashing_multiplier: 1,

            /*
             * Signature domains
             */
            domain_beacon_proposer: 0,
            domain_beacon_attester: 1,
            domain_randao: 2,
            domain_deposit: 3,
            domain_voluntary_exit: 4,
            domain_selection_proof: 5,
            domain_aggregate_and_proof: 6,
            domain_beacon_builder: 0x0B,
            domain_ptc_attester: 0x0C,
            domain_proposer_preferences: 0x0D,

            /*
             * Fork choice
             */
            proposer_score_boost: 40,
            reorg_head_weight_threshold: 20,
            reorg_parent_weight_threshold: 160,
            reorg_max_epochs_since_finalization: 2,

            /*
             * Eth1
             */
            eth1_follow_distance: 1024,
            seconds_per_eth1_block: 6,
            deposit_chain_id: 100,
            deposit_network_id: 100,
            deposit_contract_address: "0B98057eA310F4d31F2a452B414647007d1645d9"
                .parse()
                .expect("chain spec deposit contract address"),

            /*
             * Execution Specs
             */
            gas_limit_adjustment_factor: 1024,

            /*
             * Altair hard fork params
             */
            inactivity_penalty_quotient_altair: option_wrapper(|| {
                u64::checked_pow(2, 24)?.checked_mul(3)
            })
            .expect("calculation does not overflow"),
            min_slashing_penalty_quotient_altair: u64::checked_pow(2, 6)
                .expect("pow does not overflow"),
            proportional_slashing_multiplier_altair: 2,
            inactivity_score_bias: 4,
            inactivity_score_recovery_rate: 16,
            min_sync_committee_participants: 1,
            update_timeout: 8192,
            epochs_per_sync_committee_period: Epoch::new(512),
            domain_sync_committee: 7,
            domain_sync_committee_selection_proof: 8,
            domain_contribution_and_proof: 9,
            altair_fork_version: [0x01, 0x00, 0x00, 0x64],
            altair_fork_epoch: Some(Epoch::new(512)),
            sync_message_due_bps: 3333,
            contribution_due_bps: 6667,

            /*
             * Bellatrix hard fork params
             */
            inactivity_penalty_quotient_bellatrix: u64::checked_pow(2, 24)
                .expect("pow does not overflow"),
            min_slashing_penalty_quotient_bellatrix: u64::checked_pow(2, 5)
                .expect("pow does not overflow"),
            proportional_slashing_multiplier_bellatrix: 3,
            bellatrix_fork_version: [0x02, 0x00, 0x00, 0x64],
            bellatrix_fork_epoch: Some(Epoch::new(385536)),
            terminal_total_difficulty: "8626000000000000000000058750000000000000000000"
                .parse()
                .expect("terminal_total_difficulty is a valid integer"),
            terminal_block_hash: ExecutionBlockHash::zero(),
            terminal_block_hash_activation_epoch: Epoch::new(u64::MAX),

            /*
             * Capella hard fork params
             */
            capella_fork_version: [0x03, 0x00, 0x00, 0x64],
            capella_fork_epoch: Some(Epoch::new(648704)),
            max_validators_per_withdrawals_sweep: 8192,

            /*
             * Deneb hard fork params
             */
            deneb_fork_version: [0x04, 0x00, 0x00, 0x64],
            deneb_fork_epoch: Some(Epoch::new(889856)),

            /*
             * Electra hard fork params
             */
            electra_fork_version: [0x05, 0x00, 0x00, 0x64],
            electra_fork_epoch: Some(Epoch::new(1337856)),
            unset_deposit_requests_start_index: u64::MAX,
            full_exit_request_amount: 0,
            min_activation_balance: option_wrapper(|| {
                u64::checked_pow(2, 5)?.checked_mul(u64::checked_pow(10, 9)?)
            })
            .expect("calculation does not overflow"),
            max_effective_balance_electra: option_wrapper(|| {
                u64::checked_pow(2, 11)?.checked_mul(u64::checked_pow(10, 9)?)
            })
            .expect("calculation does not overflow"),
            min_slashing_penalty_quotient_electra: u64::checked_pow(2, 12)
                .expect("pow does not overflow"),
            whistleblower_reward_quotient_electra: u64::checked_pow(2, 12)
                .expect("pow does not overflow"),
            max_pending_partials_per_withdrawals_sweep: 6,
            min_per_epoch_churn_limit_electra: option_wrapper(|| {
                u64::checked_pow(2, 7)?.checked_mul(u64::checked_pow(10, 9)?)
            })
            .expect("calculation does not overflow"),
            max_per_epoch_activation_exit_churn_limit: option_wrapper(|| {
                u64::checked_pow(2, 6)?.checked_mul(u64::checked_pow(10, 9)?)
            })
            .expect("calculation does not overflow"),

            /*
             * Fulu hard fork params
             */
            fulu_fork_version: [0x06, 0x00, 0x00, 0x64],
            fulu_fork_epoch: Some(Epoch::new(1714688)),
            custody_requirement: 4,
            number_of_custody_groups: 128,
            data_column_sidecar_subnet_count: 128,
            samples_per_slot: 8,
            validator_custody_requirement: 8,
            balance_per_additional_custody_group: 32000000000,

            /*
             * Gloas hard fork params
             */
            gloas_fork_version: [0x07, 0x00, 0x00, 0x64],
            gloas_fork_epoch: None,
            builder_payment_threshold_numerator: 6,
            builder_payment_threshold_denominator: 10,
            min_builder_withdrawability_delay: Epoch::new(8192),
            churn_limit_quotient_gloas: option_wrapper(|| u64::checked_pow(2, 15))
                .expect("calculation does not overflow"),
            consolidation_churn_limit_quotient: option_wrapper(|| u64::checked_pow(2, 16))
                .expect("calculation does not overflow"),
            max_per_epoch_activation_churn_limit_gloas: option_wrapper(|| {
                u64::checked_pow(2, 8)?.checked_mul(u64::checked_pow(10, 9)?)
            })
            .expect("calculation does not overflow"),
            max_request_payloads: 128,
            topostake_config: TopoStakeConfig::disabled(),

            /*
             * Network specific
             */
            boot_nodes: vec![],
            network_id: 100, // Gnosis Chain network id
            attestation_propagation_slot_range: default_attestation_propagation_slot_range(),
            epochs_per_subnet_subscription: 256,
            attestation_subnet_count: 64,
            attestation_subnet_extra_bits: 0,
            subnets_per_node: 4, // Make this larger than usual to avoid network damage
            maximum_gossip_clock_disparity: default_maximum_gossip_clock_disparity(),
            target_aggregators_per_committee: 16,
            max_payload_size: default_max_payload_size(),
            min_epochs_for_block_requests: 33024,
            ttfb_timeout: default_ttfb_timeout(),
            resp_timeout: default_resp_timeout(),
            message_domain_invalid_snappy: default_message_domain_invalid_snappy(),
            message_domain_valid_snappy: default_message_domain_valid_snappy(),
            max_request_blocks: default_max_request_blocks(),
            attestation_subnet_prefix_bits: compute_attestation_subnet_prefix_bits(
                default_attestation_subnet_count(),
                default_attestation_subnet_extra_bits(),
            ),

            /*
             * Networking Deneb Specific
             */
            max_request_blocks_deneb: default_max_request_blocks_deneb(),
            max_request_blob_sidecars: default_max_request_blob_sidecars(),
            max_request_data_column_sidecars: default_max_request_data_column_sidecars(),
            min_epochs_for_blob_sidecars_requests: 16384,
            blob_sidecar_subnet_count: default_blob_sidecar_subnet_count(),
            max_blobs_per_block: 2,

            /*
             * Derived Deneb Specific
             */
            max_blocks_by_root_request: default_max_blocks_by_root_request(),
            max_blocks_by_root_request_deneb: default_max_blocks_by_root_request_deneb(),
            max_blobs_by_root_request: default_max_blobs_by_root_request(),

            /*
             * Networking Electra specific
             */
            max_blobs_per_block_electra: 2,
            blob_sidecar_subnet_count_electra: 2,
            max_request_blob_sidecars_electra: 256,

            /*
             * Networking Fulu specific
             */
            blob_schedule: BlobSchedule::default(),
            min_epochs_for_data_column_sidecars_requests: 16384,
            max_data_columns_by_root_request: default_data_columns_by_root_request(),
            max_payload_envelopes_by_root_request: default_max_payload_envelopes_by_root_request(),

            /*
             * Application specific
             */
            domain_application_mask: APPLICATION_DOMAIN_BUILDER,

            /*
             * Capella params
             */
            domain_bls_to_execution_change: 10,
        }
    }
}

impl Default for ChainSpec {
    fn default() -> Self {
        Self::mainnet()
    }
}

/// Consensus configuration for the devnet-only TopoStake fork.
///
/// This type deliberately lives in `ChainSpec` config for the minimal fork.
/// Adding it here lets devnets agree on activation, deterministic fixture
/// scores, and bounded proposer weights without changing BeaconState SSZ,
/// block roots, attestation/finality accounting, or reward accounting.
#[cfg_attr(feature = "arbitrary", derive(arbitrary::Arbitrary))]
#[derive(Serialize, Deserialize, Debug, PartialEq, Clone)]
#[serde(rename_all = "UPPERCASE")]
pub struct TopoStakeConfig {
    #[serde(default)]
    #[serde(serialize_with = "serialize_optional_epoch")]
    #[serde(deserialize_with = "deserialize_optional_epoch")]
    pub topostake_fork_epoch: Option<Epoch>,
    #[serde(default = "default_topostake_eta_scaled")]
    #[serde(with = "serde_utils::quoted_u64")]
    pub eta_scaled: u64,
    #[serde(default = "default_topostake_bonus_cap_scaled")]
    #[serde(with = "serde_utils::quoted_u64")]
    pub bonus_cap_scaled: u64,
    #[serde(default = "default_topostake_score_ema_beta_scaled")]
    #[serde(with = "serde_utils::quoted_u64")]
    pub score_ema_beta_scaled: u64,
    #[serde(default = "default_topostake_score_saturation_k_scaled")]
    #[serde(with = "serde_utils::quoted_u64")]
    pub score_saturation_k_scaled: u64,
    #[serde(
        default = "default_topostake_score_target_depth",
        alias = "SCORE_INITIAL_DEPTH"
    )]
    #[serde(with = "serde_utils::quoted_u64")]
    pub score_target_depth: u64,
    #[serde(default = "default_topostake_score_cost_reference_wei")]
    #[serde(with = "serde_utils::quoted_u64")]
    pub score_cost_reference_wei: u64,
    #[serde(default = "default_topostake_score_floor_kappa_scaled")]
    #[serde(with = "serde_utils::quoted_u64")]
    pub score_floor_kappa_scaled: u64,
    #[serde(default = "default_topostake_bonus_zeta_scaled")]
    #[serde(with = "serde_utils::quoted_u64")]
    pub bonus_zeta_scaled: u64,
    #[serde(default = "default_topostake_reward_settlement_depth")]
    #[serde(with = "serde_utils::quoted_u64")]
    pub reward_settlement_depth: u64,
    #[serde(default = "default_topostake_max_path_evidence_len")]
    #[serde(with = "serde_utils::quoted_u64")]
    pub max_path_evidence_len: u64,
    #[serde(default = "default_topostake_max_path_evidence_bytes")]
    #[serde(with = "serde_utils::quoted_u64")]
    pub max_path_evidence_bytes: u64,
    #[serde(default = "default_topostake_max_paths_per_block")]
    #[serde(with = "serde_utils::quoted_u64")]
    pub max_paths_per_block: u64,
    #[serde(default = "default_topostake_proposer_fee_ratio_scaled")]
    #[serde(with = "serde_utils::quoted_u64")]
    pub proposer_fee_ratio_scaled: u64,
    #[serde(default = "default_topostake_evidence_finality_depth")]
    #[serde(with = "serde_utils::quoted_u64")]
    pub evidence_finality_depth: u64,
    #[serde(default = "default_topostake_score_activation_delay_epochs")]
    #[serde(with = "serde_utils::quoted_u64")]
    pub score_activation_delay_epochs: u64,
    #[serde(default = "default_topostake_evidence_work_limit")]
    #[serde(with = "serde_utils::quoted_u64")]
    pub evidence_work_limit: u64,
    #[serde(default = "default_topostake_challenge_work_limit")]
    #[serde(with = "serde_utils::quoted_u64")]
    pub challenge_work_limit: u64,
    #[serde(default)]
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub score_fixture: Vec<TopoStakeScoreFixture>,
}

impl TopoStakeConfig {
    pub fn disabled() -> Self {
        Self {
            topostake_fork_epoch: None,
            eta_scaled: default_topostake_eta_scaled(),
            bonus_cap_scaled: default_topostake_bonus_cap_scaled(),
            score_ema_beta_scaled: default_topostake_score_ema_beta_scaled(),
            score_saturation_k_scaled: default_topostake_score_saturation_k_scaled(),
            score_target_depth: default_topostake_score_target_depth(),
            score_cost_reference_wei: default_topostake_score_cost_reference_wei(),
            score_floor_kappa_scaled: default_topostake_score_floor_kappa_scaled(),
            bonus_zeta_scaled: default_topostake_bonus_zeta_scaled(),
            reward_settlement_depth: default_topostake_reward_settlement_depth(),
            max_path_evidence_len: default_topostake_max_path_evidence_len(),
            max_path_evidence_bytes: default_topostake_max_path_evidence_bytes(),
            max_paths_per_block: default_topostake_max_paths_per_block(),
            proposer_fee_ratio_scaled: default_topostake_proposer_fee_ratio_scaled(),
            evidence_finality_depth: default_topostake_evidence_finality_depth(),
            score_activation_delay_epochs: default_topostake_score_activation_delay_epochs(),
            evidence_work_limit: default_topostake_evidence_work_limit(),
            challenge_work_limit: default_topostake_challenge_work_limit(),
            score_fixture: vec![],
        }
    }

    pub fn devnet_enabled_at(fork_epoch: Epoch) -> Self {
        Self {
            topostake_fork_epoch: Some(fork_epoch),
            ..Self::disabled()
        }
    }

    pub fn is_disabled(&self) -> bool {
        self.topostake_fork_epoch.is_none() && topostake_env_epoch("TOPOSTAKE_FORK_EPOCH").is_none()
    }

    pub fn is_enabled_at_epoch(&self, epoch: Epoch) -> bool {
        self.topostake_fork_epoch
            .or_else(|| topostake_env_epoch("TOPOSTAKE_FORK_EPOCH"))
            .is_some_and(|fork_epoch| epoch >= fork_epoch)
    }

    pub fn evidence_finality_depth(&self) -> u64 {
        topostake_env_u64("TOPOSTAKE_EVIDENCE_FINALITY_DEPTH")
            .unwrap_or(self.evidence_finality_depth)
    }

    pub fn score_activation_delay_epochs(&self) -> u64 {
        topostake_env_u64("TOPOSTAKE_SCORE_ACTIVATION_DELAY_EPOCHS")
            .unwrap_or(self.score_activation_delay_epochs)
            .max(1)
    }

    pub fn score_for_validator(&self, validator_index: usize) -> u64 {
        self.score_fixture
            .iter()
            .filter(|fixture| fixture.validator_index as usize == validator_index)
            .map(|fixture| fixture.score_scaled)
            .chain(
                topostake_env_score_fixture()
                    .into_iter()
                    .filter(move |(index, _)| *index == validator_index)
                    .map(|(_, score)| score),
            )
            .max()
            .unwrap_or(0)
    }

    pub fn score_for_validator_at_epoch(&self, epoch: Epoch, validator_index: usize) -> u64 {
        self.score_for_validator(validator_index).max(
            topostake_evidence_scores_for_epoch(epoch, self.score_activation_delay_epochs())
                .get(&validator_index)
                .copied()
                .unwrap_or(0),
        )
    }

    pub fn score_total_at_epoch(&self, epoch: Epoch) -> u64 {
        let mut scores =
            self.score_fixture
                .iter()
                .fold(HashMap::<usize, u64>::new(), |mut scores, fixture| {
                    let entry = scores.entry(fixture.validator_index as usize).or_insert(0);
                    *entry = (*entry).max(fixture.score_scaled);
                    scores
                });
        for (validator_index, score) in topostake_env_score_fixture() {
            let entry = scores.entry(validator_index).or_insert(0);
            *entry = (*entry).max(score);
        }
        for (validator_index, score) in
            topostake_evidence_scores_for_epoch(epoch, self.score_activation_delay_epochs())
        {
            let entry = scores.entry(validator_index).or_insert(0);
            *entry = (*entry).max(score);
        }
        scores.values().copied().sum()
    }

    pub fn score_total_for_validators_at_epoch(
        &self,
        epoch: Epoch,
        validator_indices: &[usize],
    ) -> u64 {
        validator_indices
            .iter()
            .map(|validator_index| self.score_for_validator_at_epoch(epoch, *validator_index))
            .fold(0u64, u64::saturating_add)
    }

    pub fn bonus_scaled_at_epoch(
        &self,
        epoch: Epoch,
        effective_balance: u64,
        total_active_balance: u64,
        validator_index: usize,
    ) -> u64 {
        let score_total = self.score_total_at_epoch(epoch);
        self.bonus_scaled_at_epoch_with_score_total(
            epoch,
            effective_balance,
            total_active_balance,
            validator_index,
            score_total,
        )
    }

    pub fn bonus_scaled_at_epoch_with_score_total(
        &self,
        epoch: Epoch,
        effective_balance: u64,
        total_active_balance: u64,
        validator_index: usize,
        active_score_total: u64,
    ) -> u64 {
        let score = self.score_for_validator_at_epoch(epoch, validator_index);
        if score == 0 || effective_balance == 0 || total_active_balance == 0 {
            return 0;
        }
        let scale = TOPOSTAKE_FIXED_POINT_SCALE as u128;
        let damped_denominator = u128::from(self.score_floor_kappa_scaled)
            .saturating_add(u128::from(active_score_total));
        if damped_denominator == 0 {
            return 0;
        }
        let damped_score_scaled = u128::from(score).saturating_mul(scale) / damped_denominator;
        let stake_share_scaled =
            u128::from(effective_balance).saturating_mul(scale) / u128::from(total_active_balance);
        if stake_share_scaled == 0 {
            return 0;
        }
        let score_to_stake_scaled = damped_score_scaled.saturating_mul(scale) / stake_share_scaled;
        self.concave_bonus_scaled(
            score_to_stake_scaled.min(u128::from(u64::MAX)) as u64,
        )
    }

    pub fn concave_bonus_scaled(&self, score_to_stake_scaled: u64) -> u64 {
        let bonus_denominator =
            u128::from(self.bonus_zeta_scaled).saturating_add(u128::from(score_to_stake_scaled));
        if bonus_denominator == 0 {
            return 0;
        }
        u128::from(self.bonus_cap_scaled)
            .saturating_mul(u128::from(score_to_stake_scaled))
            .checked_div(bonus_denominator)
            .unwrap_or(0)
            .min(u128::from(u64::MAX)) as u64
    }

    pub fn bonus_multiplier_scaled_at_epoch(
        &self,
        epoch: Epoch,
        effective_balance: u64,
        total_active_balance: u64,
        validator_index: usize,
    ) -> u64 {
        let bonus_scaled = self.bonus_scaled_at_epoch(
            epoch,
            effective_balance,
            total_active_balance,
            validator_index,
        );
        self.bonus_multiplier_from_bonus_scaled(bonus_scaled)
    }

    pub fn bonus_multiplier_from_bonus_scaled(&self, bonus_scaled: u64) -> u64 {
        let capped_bonus = bonus_scaled.min(self.bonus_cap_scaled) as u128;
        let eta_scaled = topostake_env_u64("TOPOSTAKE_ETA_SCALED")
            .unwrap_or(self.eta_scaled)
            .min(TOPOSTAKE_FIXED_POINT_SCALE) as u128;
        let scale = TOPOSTAKE_FIXED_POINT_SCALE as u128;
        let bonus = eta_scaled.saturating_mul(capped_bonus) / scale;
        (scale.saturating_add(bonus)).min(u64::MAX as u128) as u64
    }

    pub fn proposer_weight_scaled_at_epoch(
        &self,
        epoch: Epoch,
        effective_balance: u64,
        total_active_balance: u64,
        validator_index: usize,
    ) -> u128 {
        let multiplier = self.bonus_multiplier_scaled_at_epoch(
            epoch,
            effective_balance,
            total_active_balance,
            validator_index,
        );
        u128::from(effective_balance).saturating_mul(u128::from(multiplier))
    }

    pub fn proposer_weight_scaled_at_epoch_with_score_total(
        &self,
        epoch: Epoch,
        effective_balance: u64,
        total_active_balance: u64,
        validator_index: usize,
        active_score_total: u64,
    ) -> u128 {
        let bonus_scaled = self.bonus_scaled_at_epoch_with_score_total(
            epoch,
            effective_balance,
            total_active_balance,
            validator_index,
            active_score_total,
        );
        let multiplier = self.bonus_multiplier_from_bonus_scaled(bonus_scaled);
        u128::from(effective_balance).saturating_mul(u128::from(multiplier))
    }

    pub fn max_proposer_weight_scaled(&self, max_effective_balance: u64) -> u128 {
        let multiplier = self.bonus_multiplier_from_bonus_scaled(self.bonus_cap_scaled);
        u128::from(max_effective_balance).saturating_mul(u128::from(multiplier))
    }

    pub fn zero_score_state_skeleton(
        &self,
        epoch: Epoch,
        validator_count: usize,
    ) -> Option<TopoStakeStateSkeleton> {
        self.is_enabled_at_epoch(epoch)
            .then_some(TopoStakeStateSkeleton::zero_scores(epoch, validator_count))
    }
}

fn topostake_env_epoch(name: &str) -> Option<Epoch> {
    topostake_env_u64(name).map(Epoch::new)
}

fn topostake_env_u64(name: &str) -> Option<u64> {
    env::var(name)
        .ok()
        .and_then(|value| value.trim().parse::<u64>().ok())
}

fn topostake_env_score_fixture() -> Vec<(usize, u64)> {
    env::var("TOPOSTAKE_SCORE_FIXTURE")
        .ok()
        .map(|value| {
            value
                .split(',')
                .filter_map(|entry| {
                    let (validator_index, score_scaled) = entry.trim().split_once(':')?;
                    Some((
                        validator_index.trim().parse::<usize>().ok()?,
                        score_scaled.trim().parse::<u64>().ok()?,
                    ))
                })
                .collect()
        })
        .unwrap_or_default()
}

#[derive(Debug, PartialEq, Eq, Clone, Copy)]
pub enum TopoStakeEvidenceSource {
    InlineGraffiti,
    TxGossipMetadata,
}

impl TopoStakeEvidenceSource {
    pub fn as_metrics_label(self) -> &'static str {
        match self {
            Self::InlineGraffiti => "inline_graffiti",
            Self::TxGossipMetadata => "tx_gossip_metadata",
        }
    }
}

#[derive(Debug, PartialEq, Eq, Clone, Default)]
pub struct TopoStakeEvidenceEpochSummary {
    pub epoch: Epoch,
    pub valid_paths: u64,
    pub invalid_paths: u64,
    pub duplicate_receiver_proofs: u64,
    pub scored_validators: usize,
    pub max_score_scaled: u64,
    pub bound_violation: bool,
}

#[derive(Debug, PartialEq, Eq, Clone, Default)]
pub struct TopoStakeValidatorCredit {
    pub validator_index: usize,
    pub credit_scaled: u64,
}

#[derive(Debug, PartialEq, Eq, Clone, Default)]
pub struct TopoStakeValidatorFeeSettlement {
    pub validator_index: usize,
    pub amount_wei: u64,
}

#[derive(Debug, PartialEq, Eq, Clone)]
pub struct TopoStakePathEvidence {
    pub tx_hash: String,
    pub path: Vec<usize>,
    pub fee_budget_wei: u64,
    pub irrecoverable_cost_wei: u64,
}

#[derive(Debug, PartialEq, Eq, Clone)]
pub struct TopoStakeScoreUpdate {
    pub validator_index: usize,
    pub raw_contribution_scaled: u64,
    pub saturated_contribution_scaled: u64,
    pub score_scaled: u64,
}

#[derive(Debug, PartialEq, Eq, Clone)]
pub struct TopoStakeSettledEpochScores {
    pub epoch: Epoch,
    pub score_total_scaled: u64,
    pub updates: Vec<TopoStakeScoreUpdate>,
}

#[derive(Debug, PartialEq, Eq, Clone, Default)]
pub struct TopoStakeCreditEpochSummary {
    pub epoch: Epoch,
    pub credit_records: u64,
    pub pending_records: u64,
    pub settled_records: u64,
    pub total_budget_scaled: u64,
    pub proposer_credit_scaled: u64,
    pub relay_credit_scaled: u64,
    pub burned_credit_scaled: u64,
    pub conservation_violation: bool,
    pub proposer_credits: Vec<TopoStakeValidatorCredit>,
    pub relay_credits: Vec<TopoStakeValidatorCredit>,
}

#[derive(Debug, PartialEq, Eq, Clone, Default)]
pub struct TopoStakeFeeSettlementEpochSummary {
    pub epoch: Epoch,
    pub settlement_records: u64,
    pub pending_records: u64,
    pub settled_records: u64,
    pub total_amount_wei: u64,
    pub proposer_amount_wei: u64,
    pub relay_amount_wei: u64,
    pub burned_amount_wei: u64,
    pub conservation_violation: bool,
    pub proposer_settlements: Vec<TopoStakeValidatorFeeSettlement>,
    pub relay_settlements: Vec<TopoStakeValidatorFeeSettlement>,
}

#[derive(Debug, PartialEq, Eq, Clone)]
pub enum TopoStakeEvidenceRecordOutcome {
    Disabled,
    NoEvidence,
    Valid {
        epoch: Epoch,
        source: TopoStakeEvidenceSource,
        receiver: usize,
        score_updates: Vec<(usize, u64)>,
        summary: TopoStakeEvidenceEpochSummary,
    },
    Invalid {
        epoch: Epoch,
        summary: TopoStakeEvidenceEpochSummary,
    },
    DuplicateReceiver {
        epoch: Epoch,
        source: TopoStakeEvidenceSource,
        receiver: usize,
        summary: TopoStakeEvidenceEpochSummary,
    },
    DuplicateTransaction {
        epoch: Epoch,
        source: TopoStakeEvidenceSource,
        tx_hash: String,
        summary: TopoStakeEvidenceEpochSummary,
    },
}

#[derive(Debug, Default)]
struct TopoStakeEvidenceEpochRuntime {
    valid_paths: u64,
    invalid_paths: u64,
    duplicate_receiver_proofs: u64,
    raw_contributions: HashMap<usize, u64>,
    saturated_contributions: HashMap<usize, u64>,
    scores: HashMap<usize, u64>,
    score_settled: bool,
    accepted_tx_hashes: HashSet<String>,
    credit_records: Vec<TopoStakeCreditRecordRuntime>,
    proposer_credits: HashMap<usize, u64>,
    relay_credits: HashMap<usize, u64>,
    total_credit_budget_scaled: u64,
    burned_credit_scaled: u64,
}

impl TopoStakeEvidenceEpochRuntime {
    fn summary(&self, epoch: Epoch, _bonus_cap_scaled: u64) -> TopoStakeEvidenceEpochSummary {
        let max_score_scaled = self
            .scores
            .values()
            .chain(self.raw_contributions.values())
            .copied()
            .max()
            .unwrap_or(0);
        TopoStakeEvidenceEpochSummary {
            epoch,
            valid_paths: self.valid_paths,
            invalid_paths: self.invalid_paths,
            duplicate_receiver_proofs: self.duplicate_receiver_proofs,
            scored_validators: self
                .scores
                .keys()
                .chain(self.raw_contributions.keys())
                .collect::<HashSet<_>>()
                .len(),
            max_score_scaled,
            // Raw score is intentionally not capped. Influence is bounded only
            // after kappa damping and the concave proposer bonus.
            bound_violation: false,
        }
    }

    fn credit_summary(&self, epoch: Epoch) -> TopoStakeCreditEpochSummary {
        let settled_records = self
            .credit_records
            .iter()
            .filter(|record| record.settled)
            .count() as u64;
        let credit_records = self.credit_records.len() as u64;
        let proposer_credit_scaled = self.proposer_credits.values().copied().sum::<u64>();
        let relay_credit_scaled = self.relay_credits.values().copied().sum::<u64>();
        let accounted = proposer_credit_scaled
            .saturating_add(relay_credit_scaled)
            .saturating_add(self.burned_credit_scaled);
        TopoStakeCreditEpochSummary {
            epoch,
            credit_records,
            pending_records: credit_records.saturating_sub(settled_records),
            settled_records,
            total_budget_scaled: self.total_credit_budget_scaled,
            proposer_credit_scaled,
            relay_credit_scaled,
            burned_credit_scaled: self.burned_credit_scaled,
            conservation_violation: accounted != self.total_credit_budget_scaled,
            proposer_credits: sorted_topostake_credits(&self.proposer_credits),
            relay_credits: sorted_topostake_credits(&self.relay_credits),
        }
    }

    fn fee_settlement_summary(&self, epoch: Epoch) -> TopoStakeFeeSettlementEpochSummary {
        let credit = self.credit_summary(epoch);
        TopoStakeFeeSettlementEpochSummary {
            epoch,
            settlement_records: credit.credit_records,
            pending_records: credit.pending_records,
            settled_records: credit.settled_records,
            total_amount_wei: credit.total_budget_scaled,
            proposer_amount_wei: credit.proposer_credit_scaled,
            relay_amount_wei: credit.relay_credit_scaled,
            burned_amount_wei: credit.burned_credit_scaled,
            conservation_violation: credit.conservation_violation,
            proposer_settlements: credit
                .proposer_credits
                .into_iter()
                .map(|credit| TopoStakeValidatorFeeSettlement {
                    validator_index: credit.validator_index,
                    amount_wei: credit.credit_scaled,
                })
                .collect(),
            relay_settlements: credit
                .relay_credits
                .into_iter()
                .map(|credit| TopoStakeValidatorFeeSettlement {
                    validator_index: credit.validator_index,
                    amount_wei: credit.credit_scaled,
                })
                .collect(),
        }
    }
}

#[derive(Debug, Clone)]
struct TopoStakeCreditRecordRuntime {
    settlement_epoch: Epoch,
    settled: bool,
}

#[derive(Debug, Default)]
struct TopoStakeEvidenceRuntime {
    epochs: HashMap<u64, TopoStakeEvidenceEpochRuntime>,
    latest_settled_epoch: Option<u64>,
    latest_scores: HashMap<usize, u64>,
    activated_scores_by_proposer_epoch: HashMap<u64, HashMap<usize, u64>>,
    accepted_tx_hashes: HashSet<String>,
}

static TOPOSTAKE_EVIDENCE_RUNTIME: OnceLock<RwLock<TopoStakeEvidenceRuntime>> = OnceLock::new();

fn topostake_evidence_runtime() -> &'static RwLock<TopoStakeEvidenceRuntime> {
    TOPOSTAKE_EVIDENCE_RUNTIME.get_or_init(|| RwLock::new(TopoStakeEvidenceRuntime::default()))
}

pub fn reset_topostake_evidence_runtime() {
    if let Ok(mut runtime) = topostake_evidence_runtime().write() {
        *runtime = TopoStakeEvidenceRuntime::default();
    }
}

pub fn decode_topostake_graffiti_evidence(
    graffiti: &Graffiti,
    spec: &ChainSpec,
) -> Result<Option<Vec<usize>>, String> {
    let raw = std::str::from_utf8(&graffiti.0)
        .map_err(|_| "graffiti is not valid utf8".to_string())?
        .trim_matches(char::from(0))
        .trim();

    if let Some(path_csv) = raw.strip_prefix(TOPOSTAKE_GRAFFITI_EVIDENCE_PREFIX) {
        return parse_topostake_validator_path(path_csv, spec).map(Some);
    }

    Ok(None)
}

fn parse_topostake_validator_path(path_csv: &str, spec: &ChainSpec) -> Result<Vec<usize>, String> {
    if path_csv.is_empty() {
        return Err("empty TopoStake path".to_string());
    }

    let mut path = vec![];
    for item in path_csv.split(',') {
        let validator_index = item
            .trim()
            .parse::<usize>()
            .map_err(|_| format!("invalid validator index: {item}"))?;
        path.push(validator_index);
    }

    validate_topostake_validator_path(&path, spec)?;
    Ok(path)
}

fn validate_topostake_validator_path(path: &[usize], spec: &ChainSpec) -> Result<(), String> {
    if path.is_empty() {
        return Err("empty TopoStake path".to_string());
    }
    if path.len() > spec.topostake_config.max_path_evidence_len as usize {
        return Err(format!(
            "TopoStake path length {} exceeds max {}",
            path.len(),
            spec.topostake_config.max_path_evidence_len
        ));
    }

    let mut seen = HashSet::new();
    for validator_index in path {
        if !seen.insert(*validator_index) {
            return Err(format!(
                "repeated validator identity in TopoStake path: {validator_index}"
            ));
        }
    }

    Ok(())
}

pub fn record_topostake_graffiti_evidence(
    epoch: Epoch,
    proposer_index: usize,
    graffiti: &Graffiti,
    spec: &ChainSpec,
) -> TopoStakeEvidenceRecordOutcome {
    if !spec.is_topostake_enabled_at_epoch(epoch) {
        return TopoStakeEvidenceRecordOutcome::Disabled;
    }

    let decoded = decode_topostake_graffiti_evidence_record(graffiti, spec);
    let Ok(mut runtime) = topostake_evidence_runtime().write() else {
        return TopoStakeEvidenceRecordOutcome::Disabled;
    };
    let epoch_runtime = runtime.epochs.entry(epoch.as_u64()).or_default();

    match decoded {
        Ok(Some(decoded)) => record_topostake_path(
            epoch_runtime,
            epoch,
            decoded.source,
            None,
            decoded.path,
            TOPOSTAKE_FIXED_POINT_SCALE,
            0,
            proposer_index,
            spec,
        ),
        Ok(None) => TopoStakeEvidenceRecordOutcome::NoEvidence,
        Err(TopoStakeEvidenceDecodeError::Invalid) => {
            epoch_runtime.invalid_paths = epoch_runtime.invalid_paths.saturating_add(1);
            TopoStakeEvidenceRecordOutcome::Invalid {
                epoch,
                summary: epoch_runtime.summary(epoch, spec.topostake_config.bonus_cap_scaled),
            }
        }
    }
}

pub fn record_topostake_tx_gossip_metadata_evidence(
    epoch: Epoch,
    proposer_index: usize,
    paths: Vec<TopoStakePathEvidence>,
    spec: &ChainSpec,
) -> Vec<TopoStakeEvidenceRecordOutcome> {
    if !spec.is_topostake_enabled_at_epoch(epoch) {
        return vec![TopoStakeEvidenceRecordOutcome::Disabled];
    }
    if paths.is_empty() {
        return vec![TopoStakeEvidenceRecordOutcome::NoEvidence];
    }

    let Ok(mut runtime) = topostake_evidence_runtime().write() else {
        return vec![TopoStakeEvidenceRecordOutcome::Disabled];
    };
    let max_paths = spec.topostake_config.max_paths_per_block as usize;
    let mut outcomes = Vec::new();
    for path in paths.into_iter().take(max_paths) {
        if validate_topostake_validator_path(&path.path, spec).is_err() {
            let epoch_runtime = runtime.epochs.entry(epoch.as_u64()).or_default();
            epoch_runtime.invalid_paths = epoch_runtime.invalid_paths.saturating_add(1);
            outcomes.push(TopoStakeEvidenceRecordOutcome::Invalid {
                epoch,
                summary: epoch_runtime.summary(epoch, spec.topostake_config.bonus_cap_scaled),
            });
            continue;
        }

        if runtime.accepted_tx_hashes.contains(&path.tx_hash) {
            let epoch_runtime = runtime.epochs.entry(epoch.as_u64()).or_default();
            epoch_runtime.duplicate_receiver_proofs =
                epoch_runtime.duplicate_receiver_proofs.saturating_add(1);
            outcomes.push(TopoStakeEvidenceRecordOutcome::DuplicateTransaction {
                epoch,
                source: TopoStakeEvidenceSource::TxGossipMetadata,
                tx_hash: path.tx_hash,
                summary: epoch_runtime.summary(epoch, spec.topostake_config.bonus_cap_scaled),
            });
            continue;
        }

        let tx_hash = path.tx_hash.clone();
        let (outcome, accepted) = {
            let epoch_runtime = runtime.epochs.entry(epoch.as_u64()).or_default();
            let outcome = record_topostake_path(
                epoch_runtime,
                epoch,
                TopoStakeEvidenceSource::TxGossipMetadata,
                Some(path.tx_hash),
                path.path,
                path.fee_budget_wei,
                path.irrecoverable_cost_wei,
                proposer_index,
                spec,
            );
            let accepted = matches!(outcome, TopoStakeEvidenceRecordOutcome::Valid { .. });
            (outcome, accepted)
        };
        if accepted {
            runtime.accepted_tx_hashes.insert(tx_hash);
        }
        outcomes.push(outcome);
    }
    outcomes
}

pub fn record_topostake_invalid_tx_gossip_metadata_evidence(
    epoch: Epoch,
    count: usize,
    spec: &ChainSpec,
) -> Vec<TopoStakeEvidenceRecordOutcome> {
    if !spec.is_topostake_enabled_at_epoch(epoch) {
        return vec![TopoStakeEvidenceRecordOutcome::Disabled];
    }
    if count == 0 {
        return vec![TopoStakeEvidenceRecordOutcome::NoEvidence];
    }

    let Ok(mut runtime) = topostake_evidence_runtime().write() else {
        return vec![TopoStakeEvidenceRecordOutcome::Disabled];
    };
    let epoch_runtime = runtime.epochs.entry(epoch.as_u64()).or_default();
    let capped_count = count.min(spec.topostake_config.max_paths_per_block as usize);
    let mut outcomes = Vec::with_capacity(capped_count);
    for _ in 0..capped_count {
        epoch_runtime.invalid_paths = epoch_runtime.invalid_paths.saturating_add(1);
        outcomes.push(TopoStakeEvidenceRecordOutcome::Invalid {
            epoch,
            summary: epoch_runtime.summary(epoch, spec.topostake_config.bonus_cap_scaled),
        });
    }
    outcomes
}

struct DecodedTopoStakeEvidence {
    source: TopoStakeEvidenceSource,
    path: Vec<usize>,
}

enum TopoStakeEvidenceDecodeError {
    Invalid,
}

fn decode_topostake_graffiti_evidence_record(
    graffiti: &Graffiti,
    spec: &ChainSpec,
) -> Result<Option<DecodedTopoStakeEvidence>, TopoStakeEvidenceDecodeError> {
    let raw = std::str::from_utf8(&graffiti.0)
        .map_err(|_| TopoStakeEvidenceDecodeError::Invalid)?
        .trim_matches(char::from(0))
        .trim();

    if let Some(path_csv) = raw.strip_prefix(TOPOSTAKE_GRAFFITI_EVIDENCE_PREFIX) {
        return parse_topostake_validator_path(path_csv, spec)
            .map(|path| {
                Some(DecodedTopoStakeEvidence {
                    source: TopoStakeEvidenceSource::InlineGraffiti,
                    path,
                })
            })
            .map_err(|_| TopoStakeEvidenceDecodeError::Invalid);
    }

    Ok(None)
}

fn record_topostake_path(
    epoch_runtime: &mut TopoStakeEvidenceEpochRuntime,
    epoch: Epoch,
    source: TopoStakeEvidenceSource,
    tx_hash: Option<String>,
    path: Vec<usize>,
    fee_budget_wei: u64,
    irrecoverable_cost_wei: u64,
    proposer_index: usize,
    spec: &ChainSpec,
) -> TopoStakeEvidenceRecordOutcome {
    let Some(&receiver) = path.last() else {
        epoch_runtime.invalid_paths = epoch_runtime.invalid_paths.saturating_add(1);
        return TopoStakeEvidenceRecordOutcome::Invalid {
            epoch,
            summary: epoch_runtime.summary(epoch, spec.topostake_config.bonus_cap_scaled),
        };
    };

    let tx_identity = tx_hash.unwrap_or_else(|| {
        format!(
            "{}:{}:{}",
            source.as_metrics_label(),
            "inline",
            path.iter()
                .map(|validator| validator.to_string())
                .collect::<Vec<_>>()
                .join("-")
        )
    });
    if !epoch_runtime.accepted_tx_hashes.insert(tx_identity.clone()) {
        epoch_runtime.duplicate_receiver_proofs =
            epoch_runtime.duplicate_receiver_proofs.saturating_add(1);
        return TopoStakeEvidenceRecordOutcome::DuplicateTransaction {
            epoch,
            source,
            tx_hash: tx_identity,
            summary: epoch_runtime.summary(epoch, spec.topostake_config.bonus_cap_scaled),
        };
    }

    epoch_runtime.valid_paths = epoch_runtime.valid_paths.saturating_add(1);
    let credit_weight_scaled = topostake_transaction_credit_weight_scaled(
        irrecoverable_cost_wei,
        spec.topostake_config.score_cost_reference_wei,
    );
    let relay_contributions = topostake_path_relay_contributions(&path, spec)
        .into_iter()
        .map(|(validator_index, contribution_scaled)| {
            (
                validator_index,
                scaled_mul_div(
                    contribution_scaled,
                    credit_weight_scaled,
                    TOPOSTAKE_FIXED_POINT_SCALE,
                ),
            )
        })
        .filter(|(_, contribution_scaled)| *contribution_scaled > 0)
        .collect::<Vec<_>>();
    let mut score_updates = Vec::with_capacity(relay_contributions.len());
    for (validator_index, contribution_scaled) in relay_contributions {
        let raw_contribution = epoch_runtime
            .raw_contributions
            .entry(validator_index)
            .or_default();
        *raw_contribution = raw_contribution.saturating_add(contribution_scaled);
        score_updates.push((validator_index, *raw_contribution));
    }
    record_topostake_credit(
        epoch_runtime,
        epoch,
        proposer_index,
        &path,
        fee_budget_wei,
        spec,
    );
    TopoStakeEvidenceRecordOutcome::Valid {
        epoch,
        source,
        receiver,
        score_updates,
        summary: epoch_runtime.summary(epoch, spec.topostake_config.bonus_cap_scaled),
    }
}

pub fn topostake_transaction_credit_weight_scaled(
    irrecoverable_cost_wei: u64,
    reference_cost_wei: u64,
) -> u64 {
    if irrecoverable_cost_wei == 0 || reference_cost_wei == 0 {
        return 0;
    }
    scaled_mul_div(
        irrecoverable_cost_wei,
        TOPOSTAKE_FIXED_POINT_SCALE,
        reference_cost_wei,
    )
    .min(TOPOSTAKE_FIXED_POINT_SCALE)
}

fn topostake_path_relay_contributions(path: &[usize], spec: &ChainSpec) -> Vec<(usize, u64)> {
    let Some(edge_count) = path.len().checked_sub(1) else {
        return vec![];
    };
    if edge_count <= 1 {
        return vec![];
    }

    let budget = topostake_path_budget_scaled(edge_count, spec);
    if budget == 0 {
        return vec![];
    }

    let relay_count = edge_count.saturating_sub(1);
    let depth = spec.topostake_config.score_target_depth.max(1) as u128;
    let r_scaled = (depth.saturating_mul(u128::from(TOPOSTAKE_FIXED_POINT_SCALE))
        / depth.saturating_mul(2).saturating_add(1))
    .min(u128::from(u64::MAX)) as u64;
    let weights = (0..relay_count)
        .map(|position| fixed_pow_scaled(r_scaled, position as u64))
        .collect::<Vec<_>>();
    let weight_sum = weights.iter().copied().map(u128::from).sum::<u128>();
    if weight_sum == 0 {
        return vec![];
    }

    path.iter()
        .copied()
        .skip(1)
        .take(relay_count)
        .zip(weights)
        .map(|(validator_index, weight)| {
            let contribution = u128::from(budget).saturating_mul(u128::from(weight)) / weight_sum;
            (
                validator_index,
                contribution.min(u128::from(u64::MAX)) as u64,
            )
        })
        .filter(|(_, contribution)| *contribution > 0)
        .collect()
}

fn topostake_path_budget_scaled(edge_count: usize, spec: &ChainSpec) -> u64 {
    if edge_count == 0 {
        return 0;
    }
    let depth = spec.topostake_config.score_target_depth.max(1) as u128;
    let edge_count_u128 = edge_count as u128;
    let depth_factor = if depth >= edge_count_u128 {
        u128::from(TOPOSTAKE_FIXED_POINT_SCALE)
    } else {
        depth.saturating_mul(u128::from(TOPOSTAKE_FIXED_POINT_SCALE)) / edge_count_u128
    };
    let lambda_scaled = ((depth.saturating_mul(2).saturating_add(1))
        .saturating_mul(u128::from(TOPOSTAKE_FIXED_POINT_SCALE))
        / depth.saturating_mul(3).saturating_add(1))
    .min(u128::from(u64::MAX)) as u64;
    let decay = fixed_pow_scaled(
        lambda_scaled,
        edge_count.saturating_sub(1) as u64,
    );
    (depth_factor.saturating_mul(u128::from(decay)) / u128::from(TOPOSTAKE_FIXED_POINT_SCALE))
        .min(u128::from(u64::MAX)) as u64
}

fn fixed_pow_scaled(base_scaled: u64, exp: u64) -> u64 {
    let mut out = u128::from(TOPOSTAKE_FIXED_POINT_SCALE);
    let base = u128::from(base_scaled);
    for _ in 0..exp {
        out = out.saturating_mul(base) / u128::from(TOPOSTAKE_FIXED_POINT_SCALE);
    }
    out.min(u128::from(u64::MAX)) as u64
}

fn record_topostake_credit(
    epoch_runtime: &mut TopoStakeEvidenceEpochRuntime,
    evidence_epoch: Epoch,
    proposer_index: usize,
    path: &[usize],
    fee_budget_wei: u64,
    spec: &ChainSpec,
) {
    let budget = fee_budget_wei;
    if budget == 0 {
        return;
    }
    let proposer_credit = scaled_mul_div(
        budget,
        spec.topostake_config.proposer_fee_ratio_scaled,
        TOPOSTAKE_FIXED_POINT_SCALE,
    );
    let relay_budget = budget.saturating_sub(proposer_credit);
    let relay_credits = topostake_path_relay_contributions(path, spec)
        .into_iter()
        .map(|(validator_index, contribution_scaled)| {
            (
                validator_index,
                scaled_mul_div(
                    relay_budget,
                    contribution_scaled,
                    TOPOSTAKE_FIXED_POINT_SCALE,
                ),
            )
        })
        .filter(|(_, amount)| *amount > 0)
        .collect::<Vec<_>>();
    let relay_distributed = relay_credits.iter().map(|(_, amount)| *amount).sum::<u64>();
    let burned_credit = relay_budget.saturating_sub(relay_distributed);

    *epoch_runtime
        .proposer_credits
        .entry(proposer_index)
        .or_default() = epoch_runtime
        .proposer_credits
        .get(&proposer_index)
        .copied()
        .unwrap_or(0)
        .saturating_add(proposer_credit);
    for (validator_index, relay_credit) in relay_credits {
        *epoch_runtime
            .relay_credits
            .entry(validator_index)
            .or_default() = epoch_runtime
            .relay_credits
            .get(&validator_index)
            .copied()
            .unwrap_or(0)
            .saturating_add(relay_credit);
    }
    epoch_runtime.total_credit_budget_scaled = epoch_runtime
        .total_credit_budget_scaled
        .saturating_add(budget);
    epoch_runtime.burned_credit_scaled = epoch_runtime
        .burned_credit_scaled
        .saturating_add(burned_credit);
    epoch_runtime
        .credit_records
        .push(TopoStakeCreditRecordRuntime {
            settlement_epoch: Epoch::new(
                evidence_epoch
                    .as_u64()
                    .saturating_add(spec.topostake_config.reward_settlement_depth),
            ),
            settled: false,
        });
}

fn scaled_mul_div(value: u64, multiplier: u64, divisor: u64) -> u64 {
    if divisor == 0 {
        return 0;
    }
    (u128::from(value).saturating_mul(u128::from(multiplier)) / u128::from(divisor))
        .min(u128::from(u64::MAX)) as u64
}

fn sorted_topostake_credits(credits: &HashMap<usize, u64>) -> Vec<TopoStakeValidatorCredit> {
    let mut credits = credits
        .iter()
        .map(
            |(&validator_index, &credit_scaled)| TopoStakeValidatorCredit {
                validator_index,
                credit_scaled,
            },
        )
        .collect::<Vec<_>>();
    credits.sort_by_key(|credit| credit.validator_index);
    credits
}

pub fn topostake_settle_scores_through_epoch(
    finalized_epoch: Epoch,
    validator_effective_balances: &[(usize, u64)],
    total_active_balance: u64,
    spec: &ChainSpec,
) -> Vec<TopoStakeSettledEpochScores> {
    if total_active_balance == 0 {
        return vec![];
    }
    let Ok(mut runtime) = topostake_evidence_runtime().write() else {
        return vec![];
    };
    let balance_by_validator = validator_effective_balances
        .iter()
        .copied()
        .collect::<HashMap<_, _>>();
    let Some(max_settle_epoch) = finalized_epoch
        .as_u64()
        .checked_sub(spec.topostake_config.evidence_finality_depth())
    else {
        return vec![];
    };
    let mut epochs = runtime
        .epochs
        .iter()
        .filter_map(|(&epoch, epoch_runtime)| {
            (!epoch_runtime.score_settled && epoch <= max_settle_epoch).then_some(epoch)
        })
        .collect::<Vec<_>>();
    epochs.sort_unstable();

    let mut settled_epochs = Vec::with_capacity(epochs.len());
    for epoch in epochs {
        let previous_scores = runtime.latest_scores.clone();
        let Some(epoch_runtime) = runtime.epochs.get_mut(&epoch) else {
            continue;
        };
        let mut validator_indices = epoch_runtime
            .raw_contributions
            .keys()
            .chain(previous_scores.keys())
            .copied()
            .collect::<HashSet<_>>()
            .into_iter()
            .collect::<Vec<_>>();
        validator_indices.sort_unstable();

        let mut updates = Vec::with_capacity(validator_indices.len());
        let mut next_scores = HashMap::with_capacity(validator_indices.len());
        let beta_scaled = spec
            .topostake_config
            .score_ema_beta_scaled
            .min(TOPOSTAKE_FIXED_POINT_SCALE);
        let one_minus_beta_scaled = TOPOSTAKE_FIXED_POINT_SCALE.saturating_sub(beta_scaled);

        for validator_index in validator_indices {
            let raw_contribution_scaled = epoch_runtime
                .raw_contributions
                .get(&validator_index)
                .copied()
                .unwrap_or(0);
            let effective_balance = balance_by_validator
                .get(&validator_index)
                .copied()
                .unwrap_or(0);
            let saturated_contribution_scaled = topostake_saturate_contribution_scaled(
                raw_contribution_scaled,
                effective_balance,
                total_active_balance,
                spec.topostake_config.score_saturation_k_scaled,
            );
            let previous_score_scaled = previous_scores.get(&validator_index).copied().unwrap_or(0);
            let score_scaled = scaled_mul_div(
                saturated_contribution_scaled,
                beta_scaled,
                TOPOSTAKE_FIXED_POINT_SCALE,
            )
            .saturating_add(scaled_mul_div(
                previous_score_scaled,
                one_minus_beta_scaled,
                TOPOSTAKE_FIXED_POINT_SCALE,
            ));

            if saturated_contribution_scaled > 0 {
                epoch_runtime
                    .saturated_contributions
                    .insert(validator_index, saturated_contribution_scaled);
            }
            if score_scaled > 0 {
                epoch_runtime.scores.insert(validator_index, score_scaled);
                next_scores.insert(validator_index, score_scaled);
            }
            updates.push(TopoStakeScoreUpdate {
                validator_index,
                raw_contribution_scaled,
                saturated_contribution_scaled,
                score_scaled,
            });
        }
        epoch_runtime.score_settled = true;
        runtime.latest_settled_epoch = Some(epoch);
        runtime.latest_scores = next_scores;
        let score_total_scaled = updates
            .iter()
            .map(|update| update.score_scaled)
            .sum::<u64>();
        settled_epochs.push(TopoStakeSettledEpochScores {
            epoch: Epoch::new(epoch),
            score_total_scaled,
            updates,
        });
    }
    settled_epochs
}

fn topostake_saturate_contribution_scaled(
    raw_contribution_scaled: u64,
    effective_balance: u64,
    total_active_balance: u64,
    saturation_k_scaled: u64,
) -> u64 {
    if raw_contribution_scaled == 0
        || effective_balance == 0
        || total_active_balance == 0
        || saturation_k_scaled == 0
    {
        return 0;
    }
    let stake_share_scaled = scaled_mul_div(
        effective_balance,
        TOPOSTAKE_FIXED_POINT_SCALE,
        total_active_balance,
    );
    if stake_share_scaled == 0 {
        return 0;
    }
    let denominator = scaled_mul_div(
        saturation_k_scaled,
        stake_share_scaled,
        TOPOSTAKE_FIXED_POINT_SCALE,
    );
    if denominator == 0 {
        return 0;
    }
    let ratio_scaled = scaled_mul_div(
        raw_contribution_scaled,
        TOPOSTAKE_FIXED_POINT_SCALE,
        denominator,
    );
    let ln_scaled = fixed_ln_1p_scaled(ratio_scaled);
    scaled_mul_div(stake_share_scaled, ln_scaled, TOPOSTAKE_FIXED_POINT_SCALE)
}

fn fixed_ln_1p_scaled(x_scaled: u64) -> u64 {
    if x_scaled == 0 {
        return 0;
    }
    let scale = TOPOSTAKE_FIXED_POINT_SCALE as u128;
    let x = x_scaled as u128;
    let z = x.saturating_mul(scale) / (x.saturating_add(scale));
    let mut term = z;
    let mut sum = 0u128;
    for n in 1..=24u128 {
        sum = sum.saturating_add(term / n);
        term = term.saturating_mul(z) / scale;
        if term == 0 {
            break;
        }
    }
    sum.min(u64::MAX as u128) as u64
}

pub fn topostake_evidence_score_for_epoch(
    proposer_epoch: Epoch,
    validator_index: usize,
    activation_delay_epochs: u64,
) -> u64 {
    topostake_evidence_scores_for_epoch(proposer_epoch, activation_delay_epochs)
        .get(&validator_index)
        .copied()
        .unwrap_or(0)
}

pub fn topostake_evidence_scores_for_epoch(
    proposer_epoch: Epoch,
    activation_delay_epochs: u64,
) -> HashMap<usize, u64> {
    let proposer_epoch_u64 = proposer_epoch.as_u64();
    let Some(eligible_epoch) = proposer_epoch
        .as_u64()
        .checked_sub(activation_delay_epochs.max(1))
    else {
        return HashMap::new();
    };

    let Ok(mut runtime) = topostake_evidence_runtime().write() else {
        return HashMap::new();
    };
    if let Some(scores) = runtime
        .activated_scores_by_proposer_epoch
        .get(&proposer_epoch_u64)
    {
        return scores.clone();
    }

    let activated_scores = if let Some(scores) = runtime
        .epochs
        .get(&eligible_epoch)
        .filter(|epoch| epoch.score_settled && !epoch.scores.is_empty())
        .map(|epoch| epoch.scores.clone())
    {
        scores
    } else {
        let latest_eligible_epoch = runtime
            .epochs
            .iter()
            .filter(|(epoch, epoch_runtime)| {
                **epoch <= eligible_epoch
                    && epoch_runtime.score_settled
                    && !epoch_runtime.scores.is_empty()
            })
            .map(|(epoch, epoch_runtime)| (*epoch, epoch_runtime.scores.clone()))
            .max_by_key(|(epoch, _)| *epoch);

        if let Some((epoch, scores)) = latest_eligible_epoch {
            if runtime
                .latest_settled_epoch
                .is_some_and(|latest_epoch| latest_epoch == epoch)
            {
                runtime.latest_scores.clone()
            } else {
                scores
            }
        } else {
            HashMap::new()
        }
    };

    runtime
        .activated_scores_by_proposer_epoch
        .insert(proposer_epoch_u64, activated_scores.clone());
    activated_scores
}

pub fn topostake_evidence_epoch_summary(
    epoch: Epoch,
    spec: &ChainSpec,
) -> TopoStakeEvidenceEpochSummary {
    let Ok(runtime) = topostake_evidence_runtime().read() else {
        return TopoStakeEvidenceEpochSummary {
            epoch,
            ..Default::default()
        };
    };
    runtime
        .epochs
        .get(&epoch.as_u64())
        .map(|epoch_runtime| epoch_runtime.summary(epoch, spec.topostake_config.bonus_cap_scaled))
        .unwrap_or(TopoStakeEvidenceEpochSummary {
            epoch,
            ..Default::default()
        })
}

pub fn topostake_settle_credits_through_epoch(finalized_epoch: Epoch) {
    let Ok(mut runtime) = topostake_evidence_runtime().write() else {
        return;
    };
    for epoch_runtime in runtime.epochs.values_mut() {
        for record in &mut epoch_runtime.credit_records {
            if record.settlement_epoch <= finalized_epoch {
                record.settled = true;
            }
        }
    }
}

pub fn topostake_credit_epoch_summaries() -> Vec<TopoStakeCreditEpochSummary> {
    let Ok(runtime) = topostake_evidence_runtime().read() else {
        return vec![];
    };
    let mut epochs = runtime.epochs.keys().copied().collect::<Vec<_>>();
    epochs.sort_unstable();
    epochs
        .into_iter()
        .map(|epoch| {
            let epoch = Epoch::new(epoch);
            runtime
                .epochs
                .get(&epoch.as_u64())
                .expect("epoch key should exist")
                .credit_summary(epoch)
        })
        .collect()
}

pub fn topostake_fee_settlement_epoch_summaries() -> Vec<TopoStakeFeeSettlementEpochSummary> {
    let Ok(runtime) = topostake_evidence_runtime().read() else {
        return vec![];
    };
    let mut epochs = runtime.epochs.keys().copied().collect::<Vec<_>>();
    epochs.sort_unstable();
    epochs
        .into_iter()
        .map(|epoch| {
            let epoch = Epoch::new(epoch);
            runtime
                .epochs
                .get(&epoch.as_u64())
                .expect("epoch key should exist")
                .fee_settlement_summary(epoch)
        })
        .collect()
}

pub fn topostake_evidence_csv_snapshot(spec: &ChainSpec) -> String {
    let mut rows = vec![
        "epoch,valid_paths,invalid_paths,duplicate_receiver_proofs,scored_validators,max_score_scaled,bound_violation,raw_contribution_total_scaled,saturated_contribution_total_scaled,score_total_scaled"
            .to_string(),
    ];
    let Ok(runtime) = topostake_evidence_runtime().read() else {
        return rows.join("\n");
    };
    let mut epochs = runtime.epochs.keys().copied().collect::<Vec<_>>();
    epochs.sort_unstable();
    for epoch in epochs {
        let epoch = Epoch::new(epoch);
        let epoch_runtime = runtime
            .epochs
            .get(&epoch.as_u64())
            .expect("epoch key should exist");
        let summary = epoch_runtime.summary(epoch, spec.topostake_config.bonus_cap_scaled);
        let raw_contribution_total_scaled = epoch_runtime
            .raw_contributions
            .values()
            .copied()
            .sum::<u64>();
        let saturated_contribution_total_scaled = epoch_runtime
            .saturated_contributions
            .values()
            .copied()
            .sum::<u64>();
        let score_total_scaled = epoch_runtime.scores.values().copied().sum::<u64>();
        rows.push(format!(
            "{},{},{},{},{},{},{},{},{},{}",
            summary.epoch,
            summary.valid_paths,
            summary.invalid_paths,
            summary.duplicate_receiver_proofs,
            summary.scored_validators,
            summary.max_score_scaled,
            summary.bound_violation,
            raw_contribution_total_scaled,
            saturated_contribution_total_scaled,
            score_total_scaled
        ));
    }
    rows.join("\n")
}

pub fn topostake_credit_csv_snapshot() -> String {
    let mut rows = vec![
        "epoch,credit_records,pending_records,settled_records,total_budget_scaled,proposer_credit_scaled,relay_credit_scaled,burned_credit_scaled,conservation_violation"
            .to_string(),
    ];
    for summary in topostake_credit_epoch_summaries() {
        rows.push(format!(
            "{},{},{},{},{},{},{},{},{}",
            summary.epoch,
            summary.credit_records,
            summary.pending_records,
            summary.settled_records,
            summary.total_budget_scaled,
            summary.proposer_credit_scaled,
            summary.relay_credit_scaled,
            summary.burned_credit_scaled,
            summary.conservation_violation,
        ));
    }
    rows.join("\n")
}

pub fn topostake_fee_settlement_csv_snapshot() -> String {
    let mut rows = vec![
        "epoch,settlement_records,pending_records,settled_records,total_amount_wei,proposer_amount_wei,relay_amount_wei,burned_amount_wei,conservation_violation"
            .to_string(),
    ];
    for summary in topostake_fee_settlement_epoch_summaries() {
        rows.push(format!(
            "{},{},{},{},{},{},{},{},{}",
            summary.epoch,
            summary.settlement_records,
            summary.pending_records,
            summary.settled_records,
            summary.total_amount_wei,
            summary.proposer_amount_wei,
            summary.relay_amount_wei,
            summary.burned_amount_wei,
            summary.conservation_violation,
        ));
    }
    rows.join("\n")
}

#[cfg_attr(feature = "arbitrary", derive(arbitrary::Arbitrary))]
#[derive(Serialize, Deserialize, Debug, PartialEq, Eq, Clone)]
#[serde(rename_all = "UPPERCASE")]
pub struct TopoStakeScoreFixture {
    #[serde(with = "serde_utils::quoted_u64")]
    pub validator_index: u64,
    #[serde(with = "serde_utils::quoted_u64")]
    pub score_scaled: u64,
}

impl Default for TopoStakeConfig {
    fn default() -> Self {
        Self::disabled()
    }
}

/// Non-SSZ placeholder for the future fork-gated BeaconState extension.
#[cfg_attr(feature = "arbitrary", derive(arbitrary::Arbitrary))]
#[derive(Debug, PartialEq, Eq, Clone)]
pub struct TopoStakeStateSkeleton {
    pub score_epoch: Epoch,
    pub validator_count: usize,
    pub raw_scores_are_zero: bool,
    pub normalized_scores_are_zero: bool,
}

impl TopoStakeStateSkeleton {
    pub fn zero_scores(score_epoch: Epoch, validator_count: usize) -> Self {
        Self {
            score_epoch,
            validator_count,
            raw_scores_are_zero: true,
            normalized_scores_are_zero: true,
        }
    }
}

#[cfg_attr(feature = "arbitrary", derive(arbitrary::Arbitrary))]
#[derive(Serialize, Deserialize, Debug, PartialEq, Clone)]
#[serde(rename_all = "UPPERCASE")]
pub struct BlobParameters {
    pub epoch: Epoch,
    #[serde(with = "serde_utils::quoted_u64")]
    pub max_blobs_per_block: u64,
}

// A wrapper around a vector of BlobParameters to ensure that the vector is reverse
// sorted by epoch.
#[cfg_attr(feature = "arbitrary", derive(arbitrary::Arbitrary))]
#[derive(Debug, Educe, Clone)]
#[educe(PartialEq)]
pub struct BlobSchedule {
    schedule: Vec<BlobParameters>,
    // This is a hack to prevent the blob schedule being serialized on the /eth/v1/config/spec
    // endpoint prior to the Fulu fork being scheduled.
    //
    // We can remove this once Fulu is live on mainnet.
    #[educe(PartialEq(ignore))]
    skip_serializing: bool,
}

impl<'de> Deserialize<'de> for BlobSchedule {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let vec = Vec::<BlobParameters>::deserialize(deserializer)?;
        Ok(BlobSchedule::new(vec))
    }
}

impl BlobSchedule {
    pub fn new(mut vec: Vec<BlobParameters>) -> Self {
        // reverse sort by epoch
        vec.sort_by_key(|b| std::cmp::Reverse(b.epoch));
        Self {
            schedule: vec,
            skip_serializing: false,
        }
    }

    pub fn is_empty(&self) -> bool {
        self.schedule.is_empty()
    }

    pub fn skip_serializing(&self) -> bool {
        self.skip_serializing
    }

    pub fn set_skip_serializing(&mut self) {
        self.skip_serializing = true;
    }

    pub fn max_blobs_for_epoch(&self, epoch: Epoch) -> Option<u64> {
        self.schedule
            .iter()
            .find(|entry| epoch >= entry.epoch)
            .map(|entry| entry.max_blobs_per_block)
    }

    pub fn blob_parameters_for_epoch(&self, epoch: Epoch) -> Option<BlobParameters> {
        self.schedule
            .iter()
            .find(|entry| epoch >= entry.epoch)
            .cloned()
    }

    pub const fn default() -> Self {
        // TODO(EIP-7892): think about what the default should be
        Self {
            schedule: vec![],
            skip_serializing: false,
        }
    }

    pub fn as_vec(&self) -> &Vec<BlobParameters> {
        &self.schedule
    }
}

impl Serialize for BlobSchedule {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let mut schedule = self.schedule.clone();
        // reversing the list to get an ascending order
        schedule.reverse();
        schedule.serialize(serializer)
    }
}

impl<'a> IntoIterator for &'a BlobSchedule {
    type Item = &'a BlobParameters;
    type IntoIter = std::slice::Iter<'a, BlobParameters>;

    fn into_iter(self) -> Self::IntoIter {
        self.schedule.iter()
    }
}

impl IntoIterator for BlobSchedule {
    type Item = BlobParameters;
    type IntoIter = std::vec::IntoIter<BlobParameters>;

    fn into_iter(self) -> Self::IntoIter {
        self.schedule.into_iter()
    }
}

/// Exact implementation of the *config* object from the Ethereum spec (YAML/JSON).
///
/// Fields relevant to hard forks after Altair should be optional so that we can continue
/// to parse Altair configs. This default approach turns out to be much simpler than trying to
/// make `Config` a superstruct because of the hassle of deserializing an untagged enum.
#[derive(Serialize, Deserialize, Debug, PartialEq, Clone)]
#[serde(rename_all = "UPPERCASE")]
pub struct Config {
    #[serde(default)]
    #[serde(skip_serializing_if = "Option::is_none")]
    pub config_name: Option<String>,

    #[serde(default)]
    pub preset_base: String,

    #[serde(default = "default_terminal_total_difficulty")]
    #[serde(with = "serde_utils::quoted_u256")]
    pub terminal_total_difficulty: Uint256,
    #[serde(default = "default_terminal_block_hash")]
    pub terminal_block_hash: ExecutionBlockHash,
    #[serde(default = "default_terminal_block_hash_activation_epoch")]
    pub terminal_block_hash_activation_epoch: Epoch,

    #[serde(with = "serde_utils::quoted_u64")]
    min_genesis_active_validator_count: u64,
    #[serde(with = "serde_utils::quoted_u64")]
    min_genesis_time: u64,
    #[serde(with = "serde_utils::bytes_4_hex")]
    genesis_fork_version: [u8; 4],
    #[serde(with = "serde_utils::quoted_u64")]
    genesis_delay: u64,

    #[serde(with = "serde_utils::bytes_4_hex")]
    altair_fork_version: [u8; 4],
    #[serde(serialize_with = "serialize_fork_epoch")]
    #[serde(deserialize_with = "deserialize_fork_epoch")]
    pub altair_fork_epoch: Option<MaybeQuoted<Epoch>>,

    #[serde(default = "default_bellatrix_fork_version")]
    #[serde(with = "serde_utils::bytes_4_hex")]
    bellatrix_fork_version: [u8; 4],
    #[serde(default)]
    #[serde(serialize_with = "serialize_fork_epoch")]
    #[serde(deserialize_with = "deserialize_fork_epoch")]
    pub bellatrix_fork_epoch: Option<MaybeQuoted<Epoch>>,

    #[serde(default = "default_capella_fork_version")]
    #[serde(with = "serde_utils::bytes_4_hex")]
    capella_fork_version: [u8; 4],
    #[serde(default)]
    #[serde(serialize_with = "serialize_fork_epoch")]
    #[serde(deserialize_with = "deserialize_fork_epoch")]
    pub capella_fork_epoch: Option<MaybeQuoted<Epoch>>,

    #[serde(default = "default_deneb_fork_version")]
    #[serde(with = "serde_utils::bytes_4_hex")]
    deneb_fork_version: [u8; 4],
    #[serde(default)]
    #[serde(serialize_with = "serialize_fork_epoch")]
    #[serde(deserialize_with = "deserialize_fork_epoch")]
    pub deneb_fork_epoch: Option<MaybeQuoted<Epoch>>,

    #[serde(default = "default_electra_fork_version")]
    #[serde(with = "serde_utils::bytes_4_hex")]
    electra_fork_version: [u8; 4],
    #[serde(default)]
    #[serde(serialize_with = "serialize_fork_epoch")]
    #[serde(deserialize_with = "deserialize_fork_epoch")]
    pub electra_fork_epoch: Option<MaybeQuoted<Epoch>>,

    #[serde(default = "default_fulu_fork_version")]
    #[serde(with = "serde_utils::bytes_4_hex")]
    fulu_fork_version: [u8; 4],
    #[serde(default)]
    #[serde(serialize_with = "serialize_fork_epoch")]
    #[serde(deserialize_with = "deserialize_fork_epoch")]
    pub fulu_fork_epoch: Option<MaybeQuoted<Epoch>>,

    #[serde(default = "default_gloas_fork_version")]
    #[serde(with = "serde_utils::bytes_4_hex")]
    gloas_fork_version: [u8; 4],
    #[serde(default)]
    #[serde(serialize_with = "serialize_fork_epoch")]
    #[serde(deserialize_with = "deserialize_fork_epoch")]
    pub gloas_fork_epoch: Option<MaybeQuoted<Epoch>>,

    #[serde(default)]
    #[serde(skip_serializing_if = "Option::is_none")]
    seconds_per_slot: Option<MaybeQuoted<u64>>,
    #[serde(default)]
    #[serde(skip_serializing_if = "Option::is_none")]
    slot_duration_ms: Option<MaybeQuoted<u64>>,
    #[serde(with = "serde_utils::quoted_u64")]
    seconds_per_eth1_block: u64,
    #[serde(with = "serde_utils::quoted_u64")]
    min_validator_withdrawability_delay: Epoch,
    #[serde(with = "serde_utils::quoted_u64")]
    shard_committee_period: u64,
    #[serde(with = "serde_utils::quoted_u64")]
    eth1_follow_distance: u64,
    #[serde(default = "default_subnets_per_node")]
    #[serde(with = "serde_utils::quoted_u8")]
    subnets_per_node: u8,

    #[serde(with = "serde_utils::quoted_u64")]
    inactivity_score_bias: u64,
    #[serde(with = "serde_utils::quoted_u64")]
    inactivity_score_recovery_rate: u64,
    #[serde(with = "serde_utils::quoted_u64")]
    ejection_balance: u64,
    #[serde(with = "serde_utils::quoted_u64")]
    min_per_epoch_churn_limit: u64,
    #[serde(default = "default_max_per_epoch_activation_churn_limit")]
    #[serde(with = "serde_utils::quoted_u64")]
    max_per_epoch_activation_churn_limit: u64,
    #[serde(with = "serde_utils::quoted_u64")]
    churn_limit_quotient: u64,

    #[serde(skip_serializing_if = "Option::is_none")]
    proposer_score_boost: Option<MaybeQuoted<u64>>,

    #[serde(default = "default_reorg_head_weight_threshold")]
    #[serde(with = "serde_utils::quoted_u64")]
    reorg_head_weight_threshold: u64,
    #[serde(default = "default_reorg_parent_weight_threshold")]
    #[serde(with = "serde_utils::quoted_u64")]
    reorg_parent_weight_threshold: u64,
    #[serde(default = "default_reorg_max_epochs_since_finalization")]
    #[serde(with = "serde_utils::quoted_u64")]
    reorg_max_epochs_since_finalization: u64,

    #[serde(with = "serde_utils::quoted_u64")]
    deposit_chain_id: u64,
    #[serde(with = "serde_utils::quoted_u64")]
    deposit_network_id: u64,
    #[serde(with = "serde_utils::address_hex")]
    deposit_contract_address: Address,

    #[serde(default = "default_gas_limit_adjustment_factor")]
    #[serde(with = "serde_utils::quoted_u64")]
    gas_limit_adjustment_factor: u64,

    #[serde(default = "default_max_payload_size")]
    #[serde(with = "serde_utils::quoted_u64")]
    max_payload_size: u64,
    #[serde(default = "default_max_request_blocks")]
    #[serde(with = "serde_utils::quoted_u64")]
    max_request_blocks: u64,
    #[serde(default = "default_min_epochs_for_block_requests")]
    #[serde(with = "serde_utils::quoted_u64")]
    min_epochs_for_block_requests: u64,
    #[serde(default = "default_ttfb_timeout")]
    #[serde(with = "serde_utils::quoted_u64")]
    ttfb_timeout: u64,
    #[serde(default = "default_resp_timeout")]
    #[serde(with = "serde_utils::quoted_u64")]
    resp_timeout: u64,
    #[serde(default = "default_attestation_propagation_slot_range")]
    #[serde(with = "serde_utils::quoted_u64")]
    attestation_propagation_slot_range: u64,
    #[serde(default = "default_maximum_gossip_clock_disparity")]
    #[serde(with = "serde_utils::quoted_u64")]
    maximum_gossip_clock_disparity: u64,
    #[serde(default = "default_message_domain_invalid_snappy")]
    #[serde(with = "serde_utils::bytes_4_hex")]
    message_domain_invalid_snappy: [u8; 4],
    #[serde(default = "default_message_domain_valid_snappy")]
    #[serde(with = "serde_utils::bytes_4_hex")]
    message_domain_valid_snappy: [u8; 4],
    #[serde(default = "default_epochs_per_subnet_subscription")]
    #[serde(with = "serde_utils::quoted_u64")]
    epochs_per_subnet_subscription: u64,
    #[serde(default = "default_attestation_subnet_count")]
    #[serde(with = "serde_utils::quoted_u64")]
    attestation_subnet_count: u64,
    #[serde(default = "default_attestation_subnet_extra_bits")]
    #[serde(with = "serde_utils::quoted_u8")]
    attestation_subnet_extra_bits: u8,
    #[serde(default = "default_max_request_blocks_deneb")]
    #[serde(with = "serde_utils::quoted_u64")]
    max_request_blocks_deneb: u64,
    #[serde(default = "default_max_request_blob_sidecars")]
    #[serde(with = "serde_utils::quoted_u64")]
    max_request_blob_sidecars: u64,
    #[serde(default = "default_max_request_data_column_sidecars")]
    #[serde(with = "serde_utils::quoted_u64")]
    max_request_data_column_sidecars: u64,
    #[serde(default = "default_min_epochs_for_blob_sidecars_requests")]
    #[serde(with = "serde_utils::quoted_u64")]
    min_epochs_for_blob_sidecars_requests: u64,
    #[serde(default = "default_blob_sidecar_subnet_count")]
    #[serde(with = "serde_utils::quoted_u64")]
    blob_sidecar_subnet_count: u64,
    #[serde(default = "default_max_blobs_per_block")]
    #[serde(with = "serde_utils::quoted_u64")]
    max_blobs_per_block: u64,

    #[serde(default = "default_min_per_epoch_churn_limit_electra")]
    #[serde(with = "serde_utils::quoted_u64")]
    min_per_epoch_churn_limit_electra: u64,
    #[serde(default = "default_max_per_epoch_activation_exit_churn_limit")]
    #[serde(with = "serde_utils::quoted_u64")]
    max_per_epoch_activation_exit_churn_limit: u64,
    #[serde(default = "default_max_blobs_per_block_electra")]
    #[serde(with = "serde_utils::quoted_u64")]
    max_blobs_per_block_electra: u64,
    #[serde(default = "default_blob_sidecar_subnet_count_electra")]
    #[serde(with = "serde_utils::quoted_u64")]
    pub blob_sidecar_subnet_count_electra: u64,
    #[serde(default = "default_max_request_blob_sidecars_electra")]
    #[serde(with = "serde_utils::quoted_u64")]
    max_request_blob_sidecars_electra: u64,

    #[serde(default = "default_number_of_custody_groups")]
    #[serde(with = "serde_utils::quoted_u64")]
    number_of_custody_groups: u64,
    #[serde(default = "default_data_column_sidecar_subnet_count")]
    #[serde(with = "serde_utils::quoted_u64")]
    data_column_sidecar_subnet_count: u64,
    #[serde(default = "default_samples_per_slot")]
    #[serde(with = "serde_utils::quoted_u64")]
    samples_per_slot: u64,
    #[serde(default = "default_custody_requirement")]
    #[serde(with = "serde_utils::quoted_u64")]
    custody_requirement: u64,
    #[serde(default = "BlobSchedule::default")]
    #[serde(skip_serializing_if = "BlobSchedule::skip_serializing")]
    pub blob_schedule: BlobSchedule,
    #[serde(default = "default_validator_custody_requirement")]
    #[serde(with = "serde_utils::quoted_u64")]
    validator_custody_requirement: u64,
    #[serde(default = "default_balance_per_additional_custody_group")]
    #[serde(with = "serde_utils::quoted_u64")]
    balance_per_additional_custody_group: u64,
    #[serde(default = "default_min_epochs_for_data_column_sidecars_requests")]
    #[serde(with = "serde_utils::quoted_u64")]
    min_epochs_for_data_column_sidecars_requests: u64,

    #[serde(default = "default_proposer_reorg_cutoff_bps")]
    #[serde(with = "serde_utils::quoted_u64")]
    proposer_reorg_cutoff_bps: u64,
    #[serde(default = "default_attestation_due_bps")]
    #[serde(with = "serde_utils::quoted_u64")]
    attestation_due_bps: u64,
    #[serde(default = "default_attestation_due_bps_gloas")]
    #[serde(with = "serde_utils::quoted_u64")]
    attestation_due_bps_gloas: u64,
    #[serde(default = "default_payload_due_bps")]
    #[serde(with = "serde_utils::quoted_u64")]
    payload_due_bps: u64,
    #[serde(default = "default_payload_attestation_due_bps")]
    #[serde(with = "serde_utils::quoted_u64")]
    payload_attestation_due_bps: u64,
    #[serde(default = "default_aggregate_due_bps")]
    #[serde(with = "serde_utils::quoted_u64")]
    aggregate_due_bps: u64,
    #[serde(default = "default_sync_message_due_bps")]
    #[serde(with = "serde_utils::quoted_u64")]
    sync_message_due_bps: u64,
    #[serde(default = "default_contribution_due_bps")]
    #[serde(with = "serde_utils::quoted_u64")]
    contribution_due_bps: u64,

    #[serde(default = "default_min_builder_withdrawability_delay")]
    #[serde(with = "serde_utils::quoted_u64")]
    min_builder_withdrawability_delay: u64,

    #[serde(default = "default_churn_limit_quotient_gloas")]
    #[serde(with = "serde_utils::quoted_u64")]
    churn_limit_quotient_gloas: u64,
    #[serde(default = "default_consolidation_churn_limit_quotient")]
    #[serde(with = "serde_utils::quoted_u64")]
    consolidation_churn_limit_quotient: u64,
    #[serde(default = "default_max_per_epoch_activation_churn_limit_gloas")]
    #[serde(with = "serde_utils::quoted_u64")]
    max_per_epoch_activation_churn_limit_gloas: u64,

    #[serde(default = "TopoStakeConfig::disabled")]
    #[serde(skip_serializing_if = "TopoStakeConfig::is_disabled")]
    pub topostake_config: TopoStakeConfig,
}

fn default_bellatrix_fork_version() -> [u8; 4] {
    // This value shouldn't be used.
    [0xff, 0xff, 0xff, 0xff]
}

fn default_capella_fork_version() -> [u8; 4] {
    [0xff, 0xff, 0xff, 0xff]
}

fn default_deneb_fork_version() -> [u8; 4] {
    // This value shouldn't be used.
    [0xff, 0xff, 0xff, 0xff]
}

fn default_electra_fork_version() -> [u8; 4] {
    // This value shouldn't be used.
    [0xff, 0xff, 0xff, 0xff]
}

fn default_fulu_fork_version() -> [u8; 4] {
    // This value shouldn't be used.
    [0xff, 0xff, 0xff, 0xff]
}

fn default_gloas_fork_version() -> [u8; 4] {
    // This value shouldn't be used.
    [0xff, 0xff, 0xff, 0xff]
}

/// Placeholder value: 2^256-2^10 (115792089237316195423570985008687907853269984665640564039457584007913129638912).
///
/// Taken from https://github.com/ethereum/consensus-specs/blob/d5e4828aecafaf1c57ef67a5f23c4ae7b08c5137/configs/mainnet.yaml#L15-L16
const fn default_terminal_total_difficulty() -> Uint256 {
    Uint256::from_limbs([
        18446744073709550592,
        18446744073709551615,
        18446744073709551615,
        18446744073709551615,
    ])
}

fn default_terminal_block_hash() -> ExecutionBlockHash {
    ExecutionBlockHash::zero()
}

fn default_terminal_block_hash_activation_epoch() -> Epoch {
    Epoch::new(u64::MAX)
}

fn default_subnets_per_node() -> u8 {
    2u8
}

const fn default_epochs_per_subnet_subscription() -> u64 {
    256
}

const fn default_attestation_subnet_count() -> u64 {
    64
}

const fn default_attestation_subnet_extra_bits() -> u8 {
    0
}

/// Compute attestation_subnet_prefix_bits dynamically as:
/// ceillog2(ATTESTATION_SUBNET_COUNT) + ATTESTATION_SUBNET_EXTRA_BITS
fn compute_attestation_subnet_prefix_bits(
    attestation_subnet_count: u64,
    attestation_subnet_extra_bits: u8,
) -> u8 {
    let default_attestation_subnet_prefix_bits = 6u8;

    // ceillog2() = next_power_of_two().ilog2()
    // casting to u8 is fine given ilog2(u64::MAX) = 63
    let min_bits_needed = attestation_subnet_count
        .checked_next_power_of_two()
        .and_then(|x| x.checked_ilog2())
        .unwrap_or(default_attestation_subnet_prefix_bits as u32) as u8;

    min_bits_needed
        .safe_add(attestation_subnet_extra_bits)
        .unwrap_or(default_attestation_subnet_prefix_bits)
}

const fn default_max_per_epoch_activation_churn_limit() -> u64 {
    8
}

const fn default_gas_limit_adjustment_factor() -> u64 {
    1024
}

const fn default_max_payload_size() -> u64 {
    10485760
}

const fn default_min_epochs_for_block_requests() -> u64 {
    33024
}

const fn default_ttfb_timeout() -> u64 {
    5
}

const fn default_resp_timeout() -> u64 {
    10
}

const fn default_message_domain_invalid_snappy() -> [u8; 4] {
    [0, 0, 0, 0]
}

const fn default_message_domain_valid_snappy() -> [u8; 4] {
    [1, 0, 0, 0]
}

const fn default_max_request_blocks() -> u64 {
    1024
}

const fn default_max_request_blocks_deneb() -> u64 {
    128
}

const fn default_max_request_blob_sidecars() -> u64 {
    768
}

const fn default_max_request_data_column_sidecars() -> u64 {
    16384
}

const fn default_min_epochs_for_blob_sidecars_requests() -> u64 {
    4096
}

const fn default_blob_sidecar_subnet_count() -> u64 {
    6
}

/// Its important to keep this consistent with the deneb preset value for
/// `MAX_BLOBS_PER_BLOCK` else we might run into consensus issues.
const fn default_max_blobs_per_block() -> u64 {
    6
}

const fn default_blob_sidecar_subnet_count_electra() -> u64 {
    9
}

const fn default_max_request_blob_sidecars_electra() -> u64 {
    1152
}

const fn default_min_per_epoch_churn_limit_electra() -> u64 {
    128_000_000_000
}

const fn default_max_per_epoch_activation_exit_churn_limit() -> u64 {
    256_000_000_000
}

const fn default_max_blobs_per_block_electra() -> u64 {
    9
}

const fn default_attestation_propagation_slot_range() -> u64 {
    32
}

const fn default_maximum_gossip_clock_disparity() -> u64 {
    500
}

const fn default_custody_requirement() -> u64 {
    4
}

const fn default_data_column_sidecar_subnet_count() -> u64 {
    128
}

const fn default_number_of_custody_groups() -> u64 {
    128
}

const fn default_samples_per_slot() -> u64 {
    8
}

const fn default_validator_custody_requirement() -> u64 {
    8
}

const fn default_balance_per_additional_custody_group() -> u64 {
    32000000000
}

const fn default_min_epochs_for_data_column_sidecars_requests() -> u64 {
    4096
}

const fn default_proposer_reorg_cutoff_bps() -> u64 {
    1667
}

const fn default_attestation_due_bps() -> u64 {
    3333
}

const fn default_attestation_due_bps_gloas() -> u64 {
    2500
}

const fn default_payload_due_bps() -> u64 {
    7500
}

const fn default_payload_attestation_due_bps() -> u64 {
    7500
}

const fn default_aggregate_due_bps() -> u64 {
    6667
}

const fn default_sync_message_due_bps() -> u64 {
    3333
}

const fn default_contribution_due_bps() -> u64 {
    6667
}

const fn default_min_builder_withdrawability_delay() -> u64 {
    8192
}

const fn default_churn_limit_quotient_gloas() -> u64 {
    32_768
}

const fn default_consolidation_churn_limit_quotient() -> u64 {
    65_536
}

const fn default_max_per_epoch_activation_churn_limit_gloas() -> u64 {
    256_000_000_000
}

const fn default_topostake_eta_scaled() -> u64 {
    TOPOSTAKE_FIXED_POINT_SCALE / 2
}

const fn default_topostake_bonus_cap_scaled() -> u64 {
    TOPOSTAKE_FIXED_POINT_SCALE
}

const fn default_topostake_score_ema_beta_scaled() -> u64 {
    TOPOSTAKE_FIXED_POINT_SCALE * 8 / 10
}

const fn default_topostake_score_saturation_k_scaled() -> u64 {
    TOPOSTAKE_FIXED_POINT_SCALE
}

const fn default_topostake_score_target_depth() -> u64 {
    4
}

const fn default_topostake_score_cost_reference_wei() -> u64 {
    21_000_000_000_000
}

const fn default_topostake_score_floor_kappa_scaled() -> u64 {
    TOPOSTAKE_FIXED_POINT_SCALE
}

const fn default_topostake_bonus_zeta_scaled() -> u64 {
    TOPOSTAKE_FIXED_POINT_SCALE
}

const fn default_topostake_reward_settlement_depth() -> u64 {
    2
}

const fn default_topostake_max_path_evidence_len() -> u64 {
    16
}

const fn default_topostake_max_path_evidence_bytes() -> u64 {
    65_536
}

const fn default_topostake_max_paths_per_block() -> u64 {
    1024
}

const fn default_topostake_proposer_fee_ratio_scaled() -> u64 {
    TOPOSTAKE_FIXED_POINT_SCALE / 2
}

const fn default_topostake_evidence_finality_depth() -> u64 {
    1
}

const fn default_topostake_score_activation_delay_epochs() -> u64 {
    2
}

const fn default_topostake_evidence_work_limit() -> u64 {
    4096
}

const fn default_topostake_challenge_work_limit() -> u64 {
    1024
}

const fn default_reorg_head_weight_threshold() -> u64 {
    20
}

const fn default_reorg_parent_weight_threshold() -> u64 {
    160
}

const fn default_reorg_max_epochs_since_finalization() -> u64 {
    2
}

fn max_blocks_by_root_request_common(max_request_blocks: u64) -> usize {
    let max_request_blocks = max_request_blocks as usize;
    RuntimeVariableList::<Hash256>::new(
        vec![Hash256::zero(); max_request_blocks],
        max_request_blocks,
    )
    .expect("creating a RuntimeVariableList of size `max_request_blocks` should succeed")
    .as_ssz_bytes()
    .len()
}

// Simplified function which precomputes the size of a `List` of `BlobIdentifiers`.
pub(crate) fn max_blobs_by_root_request_common(max_request_blob_sidecars: u64) -> usize {
    // BlobIdentifier is a fixed-size struct with two fields:
    // - block_root: Hash256 (32 bytes)
    // - index: u64 (8 bytes)
    // Total per element: 32 + 8 = 40 bytes
    // Since BlobIdentifier is fixed-size, the outer List does not add any byte overhead.
    let blob_identifier_ssz_size = 40_usize;

    (max_request_blob_sidecars as usize)
        .safe_mul(blob_identifier_ssz_size)
        .expect("should not overflow")
}

// Simplified function which precomputes the size of a `List` of `DataColumnIdentifiers`.
pub(crate) fn max_data_columns_by_root_request_common<E: EthSpec>(
    max_request_blocks: u64,
) -> usize {
    // DataColumnsByRootIdentifier is a variable-size struct with two fields:
    // - block_root: Hash256 (32 bytes)
    // - columns: List<ColumnIndex, NumberOfColumns> (4 byte offset + n × 8 bytes)
    // Since DataColumnsByRootIdentifier is variable-size, the outer List adds a
    // 4-byte offset per element.
    // Total per element: 4 (outer offset) + 32 (block_root) + 4 (columns offset) + n × 8
    let column_index_ssz_size = 8_usize;
    let ssz_fixed_size = 40_usize;

    let data_columns_by_root_identifier_ssz_size = column_index_ssz_size
        .safe_mul(E::number_of_columns())
        .and_then(|b| b.safe_add(ssz_fixed_size))
        .expect("should not overflow");

    (max_request_blocks as usize)
        .safe_mul(data_columns_by_root_identifier_ssz_size)
        .expect("should not overflow")
}

fn default_max_blocks_by_root_request() -> usize {
    max_blocks_by_root_request_common(default_max_request_blocks())
}

fn default_max_blocks_by_root_request_deneb() -> usize {
    max_blocks_by_root_request_common(default_max_request_blocks_deneb())
}

fn default_max_blobs_by_root_request() -> usize {
    max_blobs_by_root_request_common(default_max_request_blob_sidecars())
}

fn default_data_columns_by_root_request() -> usize {
    max_data_columns_by_root_request_common::<MainnetEthSpec>(default_max_request_blocks_deneb())
}

fn default_max_payload_envelopes_by_root_request() -> usize {
    max_blocks_by_root_request_common(default_max_request_payloads())
}

fn default_max_request_payloads() -> u64 {
    128
}

impl Default for Config {
    fn default() -> Self {
        let chain_spec = MainnetEthSpec::default_spec();
        Config::from_chain_spec::<MainnetEthSpec>(&chain_spec)
    }
}

/// Util function to serialize a `None` fork epoch value
/// as `Epoch::max_value()`.
fn serialize_fork_epoch<S>(val: &Option<MaybeQuoted<Epoch>>, s: S) -> Result<S::Ok, S::Error>
where
    S: Serializer,
{
    match val {
        None => MaybeQuoted {
            value: Epoch::max_value(),
        }
        .serialize(s),
        Some(epoch) => epoch.serialize(s),
    }
}

/// Util function to deserialize a u64::max() fork epoch as `None`.
fn deserialize_fork_epoch<'de, D>(deserializer: D) -> Result<Option<MaybeQuoted<Epoch>>, D::Error>
where
    D: Deserializer<'de>,
{
    let decoded: Option<MaybeQuoted<Epoch>> = serde::de::Deserialize::deserialize(deserializer)?;
    if let Some(fork_epoch) = decoded
        && fork_epoch.value != Epoch::max_value()
    {
        return Ok(Some(fork_epoch));
    }
    Ok(None)
}

fn serialize_optional_epoch<S>(val: &Option<Epoch>, s: S) -> Result<S::Ok, S::Error>
where
    S: Serializer,
{
    match val {
        None => Option::<MaybeQuoted<Epoch>>::None.serialize(s),
        Some(epoch) => Some(MaybeQuoted { value: *epoch }).serialize(s),
    }
}

fn deserialize_optional_epoch<'de, D>(deserializer: D) -> Result<Option<Epoch>, D::Error>
where
    D: Deserializer<'de>,
{
    let decoded: Option<MaybeQuoted<Epoch>> = serde::de::Deserialize::deserialize(deserializer)?;
    Ok(decoded.map(|epoch| epoch.value))
}

impl Config {
    /// Maps `self` to an identifier for an `EthSpec` instance.
    ///
    /// Returns `None` if there is no match.
    pub fn eth_spec_id(&self) -> Option<EthSpecId> {
        match self.preset_base.as_str() {
            "minimal" => Some(EthSpecId::Minimal),
            "mainnet" => Some(EthSpecId::Mainnet),
            "gnosis" => Some(EthSpecId::Gnosis),
            _ => None,
        }
    }

    pub fn from_chain_spec<E: EthSpec>(spec: &ChainSpec) -> Self {
        Self {
            config_name: spec.config_name.clone(),
            preset_base: E::spec_name().to_string(),

            terminal_total_difficulty: spec.terminal_total_difficulty,
            terminal_block_hash: spec.terminal_block_hash,
            terminal_block_hash_activation_epoch: spec.terminal_block_hash_activation_epoch,

            min_genesis_active_validator_count: spec.min_genesis_active_validator_count,
            min_genesis_time: spec.min_genesis_time,
            genesis_fork_version: spec.genesis_fork_version,
            genesis_delay: spec.genesis_delay,

            altair_fork_version: spec.altair_fork_version,
            altair_fork_epoch: spec
                .altair_fork_epoch
                .map(|epoch| MaybeQuoted { value: epoch }),

            bellatrix_fork_version: spec.bellatrix_fork_version,
            bellatrix_fork_epoch: spec
                .bellatrix_fork_epoch
                .map(|epoch| MaybeQuoted { value: epoch }),

            capella_fork_version: spec.capella_fork_version,
            capella_fork_epoch: spec
                .capella_fork_epoch
                .map(|epoch| MaybeQuoted { value: epoch }),

            deneb_fork_version: spec.deneb_fork_version,
            deneb_fork_epoch: spec
                .deneb_fork_epoch
                .map(|epoch| MaybeQuoted { value: epoch }),

            electra_fork_version: spec.electra_fork_version,
            electra_fork_epoch: spec
                .electra_fork_epoch
                .map(|epoch| MaybeQuoted { value: epoch }),

            fulu_fork_version: spec.fulu_fork_version,
            fulu_fork_epoch: spec
                .fulu_fork_epoch
                .map(|epoch| MaybeQuoted { value: epoch }),

            gloas_fork_version: spec.gloas_fork_version,
            gloas_fork_epoch: spec
                .gloas_fork_epoch
                .map(|epoch| MaybeQuoted { value: epoch }),

            seconds_per_slot: Some(MaybeQuoted {
                value: spec.seconds_per_slot,
            }),
            slot_duration_ms: Some(MaybeQuoted {
                value: spec.slot_duration_ms,
            }),
            seconds_per_eth1_block: spec.seconds_per_eth1_block,
            min_validator_withdrawability_delay: spec.min_validator_withdrawability_delay,
            shard_committee_period: spec.shard_committee_period,
            eth1_follow_distance: spec.eth1_follow_distance,
            subnets_per_node: spec.subnets_per_node,
            epochs_per_subnet_subscription: spec.epochs_per_subnet_subscription,
            attestation_subnet_count: spec.attestation_subnet_count,
            attestation_subnet_extra_bits: spec.attestation_subnet_extra_bits,

            inactivity_score_bias: spec.inactivity_score_bias,
            inactivity_score_recovery_rate: spec.inactivity_score_recovery_rate,
            ejection_balance: spec.ejection_balance,
            churn_limit_quotient: spec.churn_limit_quotient,
            min_per_epoch_churn_limit: spec.min_per_epoch_churn_limit,
            max_per_epoch_activation_churn_limit: spec.max_per_epoch_activation_churn_limit,

            proposer_score_boost: Some(MaybeQuoted {
                value: spec.proposer_score_boost,
            }),
            reorg_head_weight_threshold: spec.reorg_head_weight_threshold,
            reorg_parent_weight_threshold: spec.reorg_parent_weight_threshold,
            reorg_max_epochs_since_finalization: spec.reorg_max_epochs_since_finalization,

            deposit_chain_id: spec.deposit_chain_id,
            deposit_network_id: spec.deposit_network_id,
            deposit_contract_address: spec.deposit_contract_address,

            gas_limit_adjustment_factor: spec.gas_limit_adjustment_factor,

            max_payload_size: spec.max_payload_size,
            max_request_blocks: spec.max_request_blocks,
            min_epochs_for_block_requests: spec.min_epochs_for_block_requests,
            ttfb_timeout: spec.ttfb_timeout,
            resp_timeout: spec.resp_timeout,
            attestation_propagation_slot_range: spec.attestation_propagation_slot_range,
            maximum_gossip_clock_disparity: spec.maximum_gossip_clock_disparity,
            message_domain_invalid_snappy: spec.message_domain_invalid_snappy,
            message_domain_valid_snappy: spec.message_domain_valid_snappy,
            max_request_blocks_deneb: spec.max_request_blocks_deneb,
            max_request_blob_sidecars: spec.max_request_blob_sidecars,
            max_request_data_column_sidecars: spec.max_request_data_column_sidecars,
            min_epochs_for_blob_sidecars_requests: spec.min_epochs_for_blob_sidecars_requests,
            blob_sidecar_subnet_count: spec.blob_sidecar_subnet_count,
            max_blobs_per_block: spec.max_blobs_per_block,

            min_per_epoch_churn_limit_electra: spec.min_per_epoch_churn_limit_electra,
            max_per_epoch_activation_exit_churn_limit: spec
                .max_per_epoch_activation_exit_churn_limit,
            max_blobs_per_block_electra: spec.max_blobs_per_block_electra,
            blob_sidecar_subnet_count_electra: spec.blob_sidecar_subnet_count_electra,
            max_request_blob_sidecars_electra: spec.max_request_blob_sidecars_electra,

            number_of_custody_groups: spec.number_of_custody_groups,
            data_column_sidecar_subnet_count: spec.data_column_sidecar_subnet_count,
            samples_per_slot: spec.samples_per_slot,
            custody_requirement: spec.custody_requirement,
            blob_schedule: spec.blob_schedule.clone(),
            validator_custody_requirement: spec.validator_custody_requirement,
            balance_per_additional_custody_group: spec.balance_per_additional_custody_group,
            min_epochs_for_data_column_sidecars_requests: spec
                .min_epochs_for_data_column_sidecars_requests,

            proposer_reorg_cutoff_bps: spec.proposer_reorg_cutoff_bps,
            attestation_due_bps: spec.attestation_due_bps,
            attestation_due_bps_gloas: spec.attestation_due_bps_gloas,
            payload_due_bps: spec.payload_due_bps,
            payload_attestation_due_bps: spec.payload_attestation_due_bps,
            aggregate_due_bps: spec.aggregate_due_bps,
            sync_message_due_bps: spec.sync_message_due_bps,
            contribution_due_bps: spec.contribution_due_bps,

            min_builder_withdrawability_delay: spec.min_builder_withdrawability_delay.as_u64(),

            churn_limit_quotient_gloas: spec.churn_limit_quotient_gloas,
            consolidation_churn_limit_quotient: spec.consolidation_churn_limit_quotient,
            max_per_epoch_activation_churn_limit_gloas: spec
                .max_per_epoch_activation_churn_limit_gloas,

            topostake_config: spec.topostake_config.clone(),
        }
    }

    pub fn from_file(filename: &Path) -> Result<Self, String> {
        let f = File::open(filename)
            .map_err(|e| format!("Error opening spec at {}: {:?}", filename.display(), e))?;
        yaml_serde::from_reader(f)
            .map_err(|e| format!("Error parsing spec at {}: {:?}", filename.display(), e))
    }

    pub fn apply_to_chain_spec<E: EthSpec>(&self, chain_spec: &ChainSpec) -> Option<ChainSpec> {
        // Pattern match here to avoid missing any fields.
        let &Config {
            ref config_name,
            ref preset_base,
            terminal_total_difficulty,
            terminal_block_hash,
            terminal_block_hash_activation_epoch,
            min_genesis_active_validator_count,
            min_genesis_time,
            genesis_fork_version,
            genesis_delay,
            altair_fork_version,
            altair_fork_epoch,
            bellatrix_fork_epoch,
            bellatrix_fork_version,
            capella_fork_epoch,
            capella_fork_version,
            deneb_fork_epoch,
            deneb_fork_version,
            electra_fork_epoch,
            electra_fork_version,
            fulu_fork_epoch,
            fulu_fork_version,
            gloas_fork_version,
            gloas_fork_epoch,
            seconds_per_slot,
            slot_duration_ms,
            seconds_per_eth1_block,
            min_validator_withdrawability_delay,
            shard_committee_period,
            eth1_follow_distance,
            subnets_per_node,
            epochs_per_subnet_subscription,
            attestation_subnet_count,
            attestation_subnet_extra_bits,
            inactivity_score_bias,
            inactivity_score_recovery_rate,
            ejection_balance,
            min_per_epoch_churn_limit,
            max_per_epoch_activation_churn_limit,
            churn_limit_quotient,
            proposer_score_boost,
            reorg_head_weight_threshold,
            reorg_parent_weight_threshold,
            reorg_max_epochs_since_finalization,
            deposit_chain_id,
            deposit_network_id,
            deposit_contract_address,
            gas_limit_adjustment_factor,
            max_payload_size,
            min_epochs_for_block_requests,
            ttfb_timeout,
            resp_timeout,
            message_domain_invalid_snappy,
            message_domain_valid_snappy,
            max_request_blocks,
            attestation_propagation_slot_range,
            maximum_gossip_clock_disparity,
            max_request_blocks_deneb,
            max_request_blob_sidecars,
            max_request_data_column_sidecars,
            min_epochs_for_blob_sidecars_requests,
            blob_sidecar_subnet_count,
            max_blobs_per_block,

            min_per_epoch_churn_limit_electra,
            max_per_epoch_activation_exit_churn_limit,
            max_blobs_per_block_electra,
            blob_sidecar_subnet_count_electra,
            max_request_blob_sidecars_electra,
            number_of_custody_groups,
            data_column_sidecar_subnet_count,
            samples_per_slot,
            custody_requirement,
            ref blob_schedule,
            validator_custody_requirement,
            balance_per_additional_custody_group,
            min_epochs_for_data_column_sidecars_requests,
            proposer_reorg_cutoff_bps,
            attestation_due_bps,
            attestation_due_bps_gloas,
            payload_due_bps,
            payload_attestation_due_bps,
            aggregate_due_bps,
            sync_message_due_bps,
            contribution_due_bps,
            min_builder_withdrawability_delay,
            churn_limit_quotient_gloas,
            consolidation_churn_limit_quotient,
            max_per_epoch_activation_churn_limit_gloas,
            ref topostake_config,
        } = self;

        if preset_base != E::spec_name().to_string().as_str() {
            return None;
        }

        // Fail if seconds_per_slot and slot_duration_ms are both set but are inconsistent.
        if let (Some(seconds_per_slot), Some(slot_duration_ms)) =
            (seconds_per_slot, slot_duration_ms)
            && seconds_per_slot.value.saturating_mul(1000) != slot_duration_ms.value
        {
            return None;
        }

        let spec = ChainSpec {
            config_name: config_name.clone(),
            min_genesis_active_validator_count,
            min_genesis_time,
            genesis_fork_version,
            genesis_delay,
            altair_fork_version,
            altair_fork_epoch: altair_fork_epoch.map(|q| q.value),
            bellatrix_fork_epoch: bellatrix_fork_epoch.map(|q| q.value),
            bellatrix_fork_version,
            capella_fork_epoch: capella_fork_epoch.map(|q| q.value),
            capella_fork_version,
            deneb_fork_epoch: deneb_fork_epoch.map(|q| q.value),
            deneb_fork_version,
            electra_fork_epoch: electra_fork_epoch.map(|q| q.value),
            electra_fork_version,
            fulu_fork_epoch: fulu_fork_epoch.map(|q| q.value),
            fulu_fork_version,
            gloas_fork_version,
            gloas_fork_epoch: gloas_fork_epoch.map(|q| q.value),
            seconds_per_slot: seconds_per_slot
                .map(|q| q.value)
                .or_else(|| slot_duration_ms.and_then(|q| q.value.checked_div(1000)))?,
            slot_duration_ms: slot_duration_ms
                .map(|q| q.value)
                .or_else(|| seconds_per_slot.map(|q| q.value.saturating_mul(1000)))?,
            seconds_per_eth1_block,
            min_validator_withdrawability_delay,
            shard_committee_period,
            eth1_follow_distance,
            subnets_per_node,
            epochs_per_subnet_subscription,
            attestation_subnet_count,
            attestation_subnet_extra_bits,
            inactivity_score_bias,
            inactivity_score_recovery_rate,
            ejection_balance,
            min_per_epoch_churn_limit,
            max_per_epoch_activation_churn_limit,
            churn_limit_quotient,
            proposer_score_boost: proposer_score_boost
                .map(|q| q.value)
                .unwrap_or(chain_spec.proposer_score_boost),
            reorg_head_weight_threshold,
            reorg_parent_weight_threshold,
            reorg_max_epochs_since_finalization,
            deposit_chain_id,
            deposit_network_id,
            deposit_contract_address,
            gas_limit_adjustment_factor,
            terminal_total_difficulty,
            terminal_block_hash,
            terminal_block_hash_activation_epoch,
            max_payload_size,
            min_epochs_for_block_requests,
            ttfb_timeout,
            resp_timeout,
            message_domain_invalid_snappy,
            message_domain_valid_snappy,
            max_request_blocks,
            attestation_propagation_slot_range,
            maximum_gossip_clock_disparity,
            max_request_blocks_deneb,
            max_request_blob_sidecars,
            max_request_data_column_sidecars,
            min_epochs_for_blob_sidecars_requests,
            blob_sidecar_subnet_count,
            max_blobs_per_block,

            min_per_epoch_churn_limit_electra,
            max_per_epoch_activation_exit_churn_limit,
            max_blobs_per_block_electra,
            max_request_blob_sidecars_electra,
            blob_sidecar_subnet_count_electra,

            number_of_custody_groups,
            data_column_sidecar_subnet_count,
            samples_per_slot,
            custody_requirement,
            blob_schedule: blob_schedule.clone(),
            validator_custody_requirement,
            balance_per_additional_custody_group,
            min_epochs_for_data_column_sidecars_requests,

            proposer_reorg_cutoff_bps,
            attestation_due_bps,
            attestation_due_bps_gloas,
            payload_due_bps,
            payload_attestation_due_bps,
            aggregate_due_bps,
            sync_message_due_bps,
            contribution_due_bps,

            min_builder_withdrawability_delay: Epoch::new(min_builder_withdrawability_delay),

            churn_limit_quotient_gloas,
            consolidation_churn_limit_quotient,
            max_per_epoch_activation_churn_limit_gloas,
            topostake_config: topostake_config.clone(),

            ..chain_spec.clone()
        };
        Some(spec.compute_derived_values::<E>())
    }
}

/// A simple wrapper to permit the in-line use of `?`.
fn option_wrapper<F, T>(f: F) -> Option<T>
where
    F: Fn() -> Option<T>,
{
    f()
}

#[cfg(test)]
mod tests {
    use super::*;
    use itertools::Itertools;

    #[test]
    fn test_mainnet_spec_can_be_constructed() {
        let _ = ChainSpec::mainnet();
    }

    #[allow(clippy::useless_vec)]
    fn test_domain(domain_type: Domain, raw_domain: u32, spec: &ChainSpec) {
        let previous_version = [0, 0, 0, 1];
        let current_version = [0, 0, 0, 2];
        let genesis_validators_root = Hash256::from_low_u64_le(77);
        let fork_epoch = Epoch::new(1024);
        let fork = Fork {
            previous_version,
            current_version,
            epoch: fork_epoch,
        };

        for (epoch, version) in vec![
            (fork_epoch - 1, previous_version),
            (fork_epoch, current_version),
            (fork_epoch + 1, current_version),
        ] {
            let domain1 = spec.get_domain(epoch, domain_type, &fork, genesis_validators_root);
            let domain2 = spec.compute_domain(domain_type, version, genesis_validators_root);

            assert_eq!(domain1, domain2);
            assert_eq!(&domain1.as_slice()[0..4], &int_to_bytes4(raw_domain)[..]);
        }
    }

    #[test]
    fn test_get_domain() {
        let spec = ChainSpec::mainnet();

        test_domain(Domain::BeaconProposer, spec.domain_beacon_proposer, &spec);
        test_domain(Domain::BeaconAttester, spec.domain_beacon_attester, &spec);
        test_domain(Domain::Randao, spec.domain_randao, &spec);
        test_domain(Domain::Deposit, spec.domain_deposit, &spec);
        test_domain(Domain::VoluntaryExit, spec.domain_voluntary_exit, &spec);
        test_domain(Domain::SelectionProof, spec.domain_selection_proof, &spec);
        test_domain(
            Domain::AggregateAndProof,
            spec.domain_aggregate_and_proof,
            &spec,
        );
        test_domain(Domain::SyncCommittee, spec.domain_sync_committee, &spec);
        test_domain(Domain::BeaconBuilder, spec.domain_beacon_builder, &spec);
        test_domain(Domain::PTCAttester, spec.domain_ptc_attester, &spec);

        // The builder domain index is zero
        let builder_domain_pre_mask = [0; 4];
        test_domain(
            Domain::ApplicationMask(ApplicationDomain::Builder),
            apply_bit_mask(builder_domain_pre_mask, &spec),
            &spec,
        );

        test_domain(
            Domain::BlsToExecutionChange,
            spec.domain_bls_to_execution_change,
            &spec,
        );
    }

    fn apply_bit_mask(domain_bytes: [u8; 4], spec: &ChainSpec) -> u32 {
        let mut domain = [0; 4];
        let mask_bytes = int_to_bytes4(spec.domain_application_mask);

        // Apply application bit mask
        for (i, (domain_byte, mask_byte)) in domain_bytes.iter().zip(mask_bytes.iter()).enumerate()
        {
            domain[i] = domain_byte | mask_byte;
        }

        u32::from_le_bytes(domain)
    }

    // Test that `fork_name_at_epoch` and `fork_epoch` are consistent.
    #[test]
    fn fork_name_at_epoch_consistency() {
        let spec = ChainSpec::mainnet();

        for fork_name in ForkName::list_all() {
            if let Some(fork_epoch) = spec.fork_epoch(fork_name) {
                assert_eq!(spec.fork_name_at_epoch(fork_epoch), fork_name);
            }
        }
    }

    // Test that `next_fork_epoch` is consistent with the other functions.
    #[test]
    fn next_fork_epoch_consistency() {
        type E = MainnetEthSpec;
        let spec = ChainSpec::mainnet();

        let mut last_fork_slot = Slot::new(0);

        for (_, fork) in ForkName::list_all().into_iter().tuple_windows() {
            if let Some(fork_epoch) = spec.fork_epoch(fork) {
                last_fork_slot = fork_epoch.start_slot(E::slots_per_epoch());

                // Fork is activated at non-zero epoch: check that `next_fork_epoch` returns
                // the correct result.
                if let Ok(prior_slot) = last_fork_slot.safe_sub(1) {
                    let (next_fork, next_fork_epoch) =
                        spec.next_fork_epoch::<E>(prior_slot).unwrap();
                    assert_eq!(fork, next_fork);
                    assert_eq!(spec.fork_epoch(fork).unwrap(), next_fork_epoch);
                }
            } else {
                // Fork is not activated, check that `next_fork_epoch` returns `None`.
                assert_eq!(spec.next_fork_epoch::<E>(last_fork_slot), None);
            }
        }
    }

    #[test]
    fn test_compute_min_bits_for_n_values_edge_cases() {
        assert_eq!(compute_attestation_subnet_prefix_bits(64, 0), 6);
        assert_eq!(compute_attestation_subnet_prefix_bits(65, 0), 7);
        assert_eq!(compute_attestation_subnet_prefix_bits(0, 1), 1);
    }
}

#[cfg(test)]
mod yaml_tests {
    use super::*;
    use crate::core::MinimalEthSpec;
    use paste::paste;
    use std::collections::BTreeSet;
    use std::env;
    use std::path::PathBuf;
    use std::sync::{Arc, LazyLock, Mutex};
    use tempfile::NamedTempFile;

    static TOPOSTAKE_TEST_LOCK: LazyLock<Mutex<()>> = LazyLock::new(|| Mutex::new(()));

    #[test]
    fn minimal_round_trip() {
        // create temp file
        let tmp_file = NamedTempFile::new().expect("failed to create temp file");
        let writer = File::options()
            .read(false)
            .write(true)
            .open(tmp_file.as_ref())
            .expect("error opening file");
        let minimal_spec = ChainSpec::minimal();

        let yamlconfig = Config::from_chain_spec::<MinimalEthSpec>(&minimal_spec);
        // write fresh minimal config to file
        yaml_serde::to_writer(writer, &yamlconfig).expect("failed to write or serialize");

        let reader = File::options()
            .read(true)
            .write(false)
            .open(tmp_file.as_ref())
            .expect("error while opening the file");
        // deserialize minimal config from file
        let from: Config = yaml_serde::from_reader(reader).expect("error while deserializing");
        assert_eq!(from, yamlconfig);
    }

    #[test]
    fn mainnet_round_trip() {
        let tmp_file = NamedTempFile::new().expect("failed to create temp file");
        let writer = File::options()
            .read(false)
            .write(true)
            .open(tmp_file.as_ref())
            .expect("error opening file");
        let mainnet_spec = ChainSpec::mainnet();
        let yamlconfig = Config::from_chain_spec::<MainnetEthSpec>(&mainnet_spec);
        yaml_serde::to_writer(writer, &yamlconfig).expect("failed to write or serialize");

        let reader = File::options()
            .read(true)
            .write(false)
            .open(tmp_file.as_ref())
            .expect("error while opening the file");
        let from: Config = yaml_serde::from_reader(reader).expect("error while deserializing");
        assert_eq!(from, yamlconfig);
    }

    #[test]
    fn slot_duration_fallback_both_fields() {
        let mainnet = ChainSpec::mainnet();
        let mut config = Config::from_chain_spec::<MainnetEthSpec>(&mainnet);
        config.seconds_per_slot = Some(MaybeQuoted { value: 12 });
        config.slot_duration_ms = Some(MaybeQuoted { value: 12000 });
        let spec = config
            .apply_to_chain_spec::<MainnetEthSpec>(&mainnet)
            .unwrap();
        assert_eq!(spec.seconds_per_slot, 12);
        assert_eq!(spec.slot_duration_ms, 12000);
    }

    #[test]
    fn slot_duration_fallback_both_fields_inconsistent() {
        let mainnet = ChainSpec::mainnet();
        let mut config = Config::from_chain_spec::<MainnetEthSpec>(&mainnet);
        config.seconds_per_slot = Some(MaybeQuoted { value: 10 });
        config.slot_duration_ms = Some(MaybeQuoted { value: 12000 });
        assert_eq!(config.apply_to_chain_spec::<MainnetEthSpec>(&mainnet), None);
    }

    #[test]
    fn slot_duration_fallback_seconds_only() {
        let mainnet = ChainSpec::mainnet();
        let mut config = Config::from_chain_spec::<MainnetEthSpec>(&mainnet);
        config.seconds_per_slot = Some(MaybeQuoted { value: 12 });
        config.slot_duration_ms = None;
        let spec = config
            .apply_to_chain_spec::<MainnetEthSpec>(&mainnet)
            .unwrap();
        assert_eq!(spec.seconds_per_slot, 12);
        assert_eq!(spec.slot_duration_ms, 12000);
    }

    #[test]
    fn slot_duration_fallback_ms_only() {
        let mainnet = ChainSpec::mainnet();
        let mut config = Config::from_chain_spec::<MainnetEthSpec>(&mainnet);
        config.seconds_per_slot = None;
        config.slot_duration_ms = Some(MaybeQuoted { value: 12000 });
        let spec = config
            .apply_to_chain_spec::<MainnetEthSpec>(&mainnet)
            .unwrap();
        assert_eq!(spec.seconds_per_slot, 12);
        assert_eq!(spec.slot_duration_ms, 12000);
    }

    #[test]
    fn slot_duration_fallback_neither() {
        let mainnet = ChainSpec::mainnet();
        let mut config = Config::from_chain_spec::<MainnetEthSpec>(&mainnet);
        config.seconds_per_slot = None;
        config.slot_duration_ms = None;
        assert!(
            config
                .apply_to_chain_spec::<MainnetEthSpec>(&mainnet)
                .is_none()
        );
    }

    #[test]
    fn blob_schedule_max_blobs_per_block() {
        let spec_contents = r#"
        PRESET_BASE: 'mainnet'
        MIN_GENESIS_ACTIVE_VALIDATOR_COUNT: 384
        MIN_GENESIS_TIME: 1748264340
        GENESIS_FORK_VERSION: 0x10355025
        GENESIS_DELAY: 60
        SECONDS_PER_SLOT: 12
        SLOT_DURATION_MS: 12000
        SECONDS_PER_ETH1_BLOCK: 12
        MIN_VALIDATOR_WITHDRAWABILITY_DELAY: 256
        SHARD_COMMITTEE_PERIOD: 256
        ETH1_FOLLOW_DISTANCE: 2048
        INACTIVITY_SCORE_BIAS: 4
        INACTIVITY_SCORE_RECOVERY_RATE: 16
        EJECTION_BALANCE: 16000000000
        MIN_PER_EPOCH_CHURN_LIMIT: 4
        CHURN_LIMIT_QUOTIENT: 65536
        MAX_PER_EPOCH_ACTIVATION_CHURN_LIMIT: 8
        PROPOSER_SCORE_BOOST: 40
        REORG_HEAD_WEIGHT_THRESHOLD: 20
        REORG_PARENT_WEIGHT_THRESHOLD: 160
        REORG_MAX_EPOCHS_SINCE_FINALIZATION: 2
        EPOCHS_PER_SUBNET_SUBSCRIPTION: 256
        ATTESTATION_SUBNET_COUNT: 64
        ATTESTATION_SUBNET_EXTRA_BITS: 0
        DEPOSIT_CHAIN_ID: 7042643276
        DEPOSIT_NETWORK_ID: 7042643276
        DEPOSIT_CONTRACT_ADDRESS: 0x00000000219ab540356cBB839Cbe05303d7705Fa

        ALTAIR_FORK_VERSION: 0x20355025
        ALTAIR_FORK_EPOCH: 0
        BELLATRIX_FORK_VERSION: 0x30355025
        BELLATRIX_FORK_EPOCH: 0
        CAPELLA_FORK_VERSION: 0x40355025
        CAPELLA_FORK_EPOCH: 0
        DENEB_FORK_VERSION: 0x50355025
        DENEB_FORK_EPOCH: 64
        ELECTRA_FORK_VERSION: 0x60355025
        ELECTRA_FORK_EPOCH: 128
        FULU_FORK_VERSION: 0x70355025
        FULU_FORK_EPOCH: 256
        GLOAS_FORK_VERSION: 0x80355025
        GLOAS_FORK_EPOCH: 512
        BLOB_SCHEDULE:
          - EPOCH: 512
            MAX_BLOBS_PER_BLOCK: 12
          - EPOCH: 768
            MAX_BLOBS_PER_BLOCK: 15
          - EPOCH: 1024
            MAX_BLOBS_PER_BLOCK: 18
          - EPOCH: 1280
            MAX_BLOBS_PER_BLOCK: 9
          - EPOCH: 1584
            MAX_BLOBS_PER_BLOCK: 20
        "#;
        let config: Config =
            yaml_serde::from_str(spec_contents).expect("error while deserializing");
        let spec =
            ChainSpec::from_config::<MainnetEthSpec>(&config).expect("error while creating spec");

        // test out max_blobs_per_block(epoch)
        assert_eq!(
            spec.max_blobs_per_block(Epoch::new(64)),
            default_max_blobs_per_block()
        );
        assert_eq!(
            spec.max_blobs_per_block(Epoch::new(127)),
            default_max_blobs_per_block()
        );
        assert_eq!(
            spec.max_blobs_per_block(Epoch::new(128)),
            default_max_blobs_per_block_electra()
        );
        assert_eq!(
            spec.max_blobs_per_block(Epoch::new(255)),
            default_max_blobs_per_block_electra()
        );
        assert_eq!(
            spec.max_blobs_per_block(Epoch::new(256)),
            default_max_blobs_per_block_electra()
        );
        assert_eq!(
            spec.max_blobs_per_block(Epoch::new(511)),
            default_max_blobs_per_block_electra()
        );
        assert_eq!(spec.max_blobs_per_block(Epoch::new(512)), 12);
        assert_eq!(spec.max_blobs_per_block(Epoch::new(767)), 12);
        assert_eq!(spec.max_blobs_per_block(Epoch::new(768)), 15);
        assert_eq!(spec.max_blobs_per_block(Epoch::new(1023)), 15);
        assert_eq!(spec.max_blobs_per_block(Epoch::new(1024)), 18);
        assert_eq!(spec.max_blobs_per_block(Epoch::new(1279)), 18);
        assert_eq!(spec.max_blobs_per_block(Epoch::new(1280)), 9);
        assert_eq!(spec.max_blobs_per_block(Epoch::new(1583)), 9);
        assert_eq!(spec.max_blobs_per_block(Epoch::new(1584)), 20);
        assert_eq!(
            spec.max_blobs_per_block(Epoch::new(18446744073709551615)),
            20
        );

        // blob schedule is reverse sorted by epoch
        assert_eq!(
            config.blob_schedule.as_vec(),
            &vec![
                BlobParameters {
                    epoch: Epoch::new(1584),
                    max_blobs_per_block: 20
                },
                BlobParameters {
                    epoch: Epoch::new(1280),
                    max_blobs_per_block: 9
                },
                BlobParameters {
                    epoch: Epoch::new(1024),
                    max_blobs_per_block: 18
                },
                BlobParameters {
                    epoch: Epoch::new(768),
                    max_blobs_per_block: 15
                },
                BlobParameters {
                    epoch: Epoch::new(512),
                    max_blobs_per_block: 12
                },
            ]
        );

        // test max_blobs_per_block_within_fork
        assert_eq!(
            spec.max_blobs_per_block_within_fork(ForkName::Deneb),
            default_max_blobs_per_block()
        );
        assert_eq!(
            spec.max_blobs_per_block_within_fork(ForkName::Electra),
            default_max_blobs_per_block_electra()
        );
        assert_eq!(spec.max_blobs_per_block_within_fork(ForkName::Fulu), 20);

        // Check that serialization is in ascending order
        let yaml = yaml_serde::to_string(&spec.blob_schedule).expect("should serialize");

        // Deserialize back to Vec<BlobParameters> to check order
        let deserialized: Vec<BlobParameters> =
            yaml_serde::from_str(&yaml).expect("should deserialize");

        // Should be in ascending order by epoch
        assert!(
            deserialized.iter().map(|bp| bp.epoch.as_u64()).is_sorted(),
            "BlobSchedule should serialize in ascending order by epoch"
        );
    }

    #[test]
    fn blob_schedule_fork_digest() {
        let spec_contents = r#"
        PRESET_BASE: 'mainnet'
        MIN_GENESIS_ACTIVE_VALIDATOR_COUNT: 384
        MIN_GENESIS_TIME: 1748264340
        GENESIS_FORK_VERSION: 0x10355025
        GENESIS_DELAY: 60
        SECONDS_PER_SLOT: 12
        SLOT_DURATION_MS: 12000
        SECONDS_PER_ETH1_BLOCK: 12
        MIN_VALIDATOR_WITHDRAWABILITY_DELAY: 256
        SHARD_COMMITTEE_PERIOD: 256
        ETH1_FOLLOW_DISTANCE: 2048
        INACTIVITY_SCORE_BIAS: 4
        INACTIVITY_SCORE_RECOVERY_RATE: 16
        EJECTION_BALANCE: 16000000000
        MIN_PER_EPOCH_CHURN_LIMIT: 4
        CHURN_LIMIT_QUOTIENT: 65536
        MAX_PER_EPOCH_ACTIVATION_CHURN_LIMIT: 8
        PROPOSER_SCORE_BOOST: 40
        REORG_HEAD_WEIGHT_THRESHOLD: 20
        REORG_PARENT_WEIGHT_THRESHOLD: 160
        REORG_MAX_EPOCHS_SINCE_FINALIZATION: 2
        EPOCHS_PER_SUBNET_SUBSCRIPTION: 256
        ATTESTATION_SUBNET_COUNT: 64
        ATTESTATION_SUBNET_EXTRA_BITS: 0
        DEPOSIT_CHAIN_ID: 7042643276
        DEPOSIT_NETWORK_ID: 7042643276
        DEPOSIT_CONTRACT_ADDRESS: 0x00000000219ab540356cBB839Cbe05303d7705Fa

        ALTAIR_FORK_VERSION: 0x20355025
        ALTAIR_FORK_EPOCH: 0
        BELLATRIX_FORK_VERSION: 0x30355025
        BELLATRIX_FORK_EPOCH: 0
        CAPELLA_FORK_VERSION: 0x40355025
        CAPELLA_FORK_EPOCH: 0
        DENEB_FORK_VERSION: 0x50355025
        DENEB_FORK_EPOCH: 0
        ELECTRA_FORK_VERSION: 0x60000000
        ELECTRA_FORK_EPOCH: 9
        FULU_FORK_VERSION: 0x06000000
        FULU_FORK_EPOCH: 100
        BLOB_SCHEDULE:
          - EPOCH: 9
            MAX_BLOBS_PER_BLOCK: 9
          - EPOCH: 100
            MAX_BLOBS_PER_BLOCK: 100
          - EPOCH: 150
            MAX_BLOBS_PER_BLOCK: 175
          - EPOCH: 200
            MAX_BLOBS_PER_BLOCK: 200
          - EPOCH: 250
            MAX_BLOBS_PER_BLOCK: 275
          - EPOCH: 300
            MAX_BLOBS_PER_BLOCK: 300
        "#;
        let config: Config =
            yaml_serde::from_str(spec_contents).expect("error while deserializing");
        let spec =
            ChainSpec::from_config::<MainnetEthSpec>(&config).expect("error while creating spec");

        let genesis_validators_root = Hash256::from_slice(&[0; 32]);

        let digest = spec.compute_fork_digest(genesis_validators_root, Epoch::new(100));
        assert_eq!(digest, [0xdf, 0x67, 0x55, 0x7b]);
        let digest = spec.compute_fork_digest(genesis_validators_root, Epoch::new(101));
        assert_eq!(digest, [0xdf, 0x67, 0x55, 0x7b]);
        let digest = spec.compute_fork_digest(genesis_validators_root, Epoch::new(150));
        assert_eq!(digest, [0x8a, 0xb3, 0x8b, 0x59]);
        let digest = spec.compute_fork_digest(genesis_validators_root, Epoch::new(199));
        assert_eq!(digest, [0x8a, 0xb3, 0x8b, 0x59]);
        let digest = spec.compute_fork_digest(genesis_validators_root, Epoch::new(200));
        assert_eq!(digest, [0xd9, 0xb8, 0x14, 0x38]);
        let digest = spec.compute_fork_digest(genesis_validators_root, Epoch::new(201));
        assert_eq!(digest, [0xd9, 0xb8, 0x14, 0x38]);
        let digest = spec.compute_fork_digest(genesis_validators_root, Epoch::new(250));
        assert_eq!(digest, [0x4e, 0xf3, 0x2a, 0x62]);
        let digest = spec.compute_fork_digest(genesis_validators_root, Epoch::new(299));
        assert_eq!(digest, [0x4e, 0xf3, 0x2a, 0x62]);
        let digest = spec.compute_fork_digest(genesis_validators_root, Epoch::new(300));
        assert_eq!(digest, [0xca, 0x10, 0x0d, 0x64]);
        let digest = spec.compute_fork_digest(genesis_validators_root, Epoch::new(301));
        assert_eq!(digest, [0xca, 0x10, 0x0d, 0x64]);
    }

    #[test]
    fn apply_to_spec() {
        let mut spec = ChainSpec::minimal();
        let yamlconfig = Config::from_chain_spec::<MinimalEthSpec>(&spec);

        // modifying the original spec
        spec.min_genesis_active_validator_count += 1;
        spec.deposit_chain_id += 1;
        spec.deposit_network_id += 1;
        // Applying a yaml config with incorrect EthSpec should fail
        let res = yamlconfig.apply_to_chain_spec::<MainnetEthSpec>(&spec);
        assert_eq!(res, None);

        // Applying a yaml config with correct EthSpec should NOT fail
        let new_spec = yamlconfig
            .apply_to_chain_spec::<MinimalEthSpec>(&spec)
            .expect("should have applied spec");
        assert_eq!(new_spec, ChainSpec::minimal());
    }

    #[test]
    fn test_defaults() {
        // Spec yaml string. Fields that serialize/deserialize with a default value are commented out.
        let spec = r#"
        PRESET_BASE: 'mainnet'
        #TERMINAL_TOTAL_DIFFICULTY: 115792089237316195423570985008687907853269984665640564039457584007913129638911
        #TERMINAL_BLOCK_HASH: 0x0000000000000000000000000000000000000000000000000000000000000001
        #TERMINAL_BLOCK_HASH_ACTIVATION_EPOCH: 18446744073709551614
        MIN_GENESIS_ACTIVE_VALIDATOR_COUNT: 16384
        MIN_GENESIS_TIME: 1606824000
        GENESIS_FORK_VERSION: 0x00000000
        GENESIS_DELAY: 604800
        ALTAIR_FORK_VERSION: 0x01000000
        ALTAIR_FORK_EPOCH: 74240
        #BELLATRIX_FORK_VERSION: 0x02000000
        #BELLATRIX_FORK_EPOCH: 18446744073709551614
        SHARDING_FORK_VERSION: 0x03000000
        SHARDING_FORK_EPOCH: 18446744073709551615
        SECONDS_PER_SLOT: 12
        SLOT_DURATION_MS: 12000
        SECONDS_PER_ETH1_BLOCK: 14
        MIN_VALIDATOR_WITHDRAWABILITY_DELAY: 256
        SHARD_COMMITTEE_PERIOD: 256
        ETH1_FOLLOW_DISTANCE: 2048
        INACTIVITY_SCORE_BIAS: 4
        INACTIVITY_SCORE_RECOVERY_RATE: 16
        EJECTION_BALANCE: 16000000000
        MIN_PER_EPOCH_CHURN_LIMIT: 4
        MAX_PER_EPOCH_ACTIVATION_CHURN_LIMIT: 8
        CHURN_LIMIT_QUOTIENT: 65536
        PROPOSER_SCORE_BOOST: 40
        EPOCHS_PER_SUBNET_SUBSCRIPTION: 256
        ATTESTATION_SUBNET_COUNT: 64
        ATTESTATION_SUBNET_EXTRA_BITS: 0
        DEPOSIT_CHAIN_ID: 1
        DEPOSIT_NETWORK_ID: 1
        DEPOSIT_CONTRACT_ADDRESS: 0x00000000219ab540356cBB839Cbe05303d7705Fa
        CUSTODY_REQUIREMENT: 1
        DATA_COLUMN_SIDECAR_SUBNET_COUNT: 128
        SAMPLES_PER_SLOT: 8
        "#;

        let chain_spec: Config = yaml_serde::from_str(spec).unwrap();

        // Asserts that `chain_spec.$name` and `default_$name()` are equal.
        macro_rules! check_default {
            ($name: ident) => {
                paste! {
                    assert_eq!(
                        chain_spec.$name,
                        [<default_ $name>](),
                        "{} does not match default", stringify!($name));
                }
            };
        }

        check_default!(terminal_total_difficulty);
        check_default!(terminal_block_hash);
        check_default!(terminal_block_hash_activation_epoch);
        check_default!(bellatrix_fork_version);
        check_default!(max_payload_size);
        check_default!(min_epochs_for_block_requests);
        check_default!(ttfb_timeout);
        check_default!(resp_timeout);
        check_default!(message_domain_invalid_snappy);
        check_default!(message_domain_valid_snappy);

        assert_eq!(chain_spec.bellatrix_fork_epoch, None);
    }

    #[test]
    fn topostake_config_defaults_disabled() {
        let spec = ChainSpec::mainnet();

        assert!(spec.topostake_config.is_disabled());
        assert!(!spec.is_topostake_enabled_at_epoch(Epoch::new(0)));
        assert_eq!(spec.topostake_config.eta_scaled, 500_000_000);
        assert_eq!(
            spec.topostake_config.bonus_cap_scaled,
            TOPOSTAKE_FIXED_POINT_SCALE
        );
        assert_eq!(
            spec.topostake_config
                .zero_score_state_skeleton(Epoch::new(0), 64),
            None
        );
    }

    #[test]
    fn topostake_config_yaml_activation() {
        let mainnet = ChainSpec::mainnet();
        let mut config = Config::from_chain_spec::<MainnetEthSpec>(&mainnet);
        config.topostake_config = TopoStakeConfig::devnet_enabled_at(Epoch::new(2));
        config.topostake_config.score_fixture = vec![TopoStakeScoreFixture {
            validator_index: 7,
            score_scaled: TOPOSTAKE_FIXED_POINT_SCALE,
        }];

        let yaml = yaml_serde::to_string(&config).expect("should serialize");
        assert!(yaml.contains("TOPOSTAKE_CONFIG"));
        assert!(yaml.contains("SCORE_FIXTURE"));

        let decoded: Config = yaml_serde::from_str(&yaml).expect("should deserialize");
        let spec = decoded
            .apply_to_chain_spec::<MainnetEthSpec>(&mainnet)
            .expect("should apply config");

        assert!(!spec.is_topostake_enabled_at_epoch(Epoch::new(1)));
        assert!(spec.is_topostake_enabled_at_epoch(Epoch::new(2)));
        assert_eq!(
            spec.topostake_config
                .zero_score_state_skeleton(Epoch::new(2), 64),
            Some(TopoStakeStateSkeleton::zero_scores(Epoch::new(2), 64))
        );
        assert_eq!(
            spec.topostake_config.score_for_validator(7),
            TOPOSTAKE_FIXED_POINT_SCALE
        );
    }

    fn topostake_enabled_spec_for_tests() -> ChainSpec {
        let mainnet = ChainSpec::mainnet();
        let mut config = Config::from_chain_spec::<MainnetEthSpec>(&mainnet);
        config.topostake_config = TopoStakeConfig::devnet_enabled_at(Epoch::new(0));
        config
            .apply_to_chain_spec::<MainnetEthSpec>(&mainnet)
            .expect("topostake config should apply")
    }

    #[test]
    fn topostake_direct_path_has_no_relay_contribution() {
        let _guard = TOPOSTAKE_TEST_LOCK.lock().unwrap();
        reset_topostake_evidence_runtime();
        let spec = topostake_enabled_spec_for_tests();
        let outcomes = record_topostake_tx_gossip_metadata_evidence(
            Epoch::new(0),
            1,
            vec![TopoStakePathEvidence {
                tx_hash: "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
                    .into(),
                path: vec![0, 1],
                fee_budget_wei: TOPOSTAKE_FIXED_POINT_SCALE,
                irrecoverable_cost_wei: spec.topostake_config.score_cost_reference_wei,
            }],
            &spec,
        );

        assert!(matches!(
            outcomes.as_slice(),
            [TopoStakeEvidenceRecordOutcome::Valid { .. }]
        ));
        assert_eq!(topostake_evidence_score_for_epoch(Epoch::new(1), 0, 0), 0);
        assert_eq!(topostake_evidence_score_for_epoch(Epoch::new(1), 1, 0), 0);
        let credit = topostake_credit_epoch_summaries()
            .into_iter()
            .find(|summary| summary.epoch == Epoch::new(0))
            .expect("credit summary should exist");
        assert_eq!(credit.relay_credit_scaled, 0);
        assert_eq!(
            credit.burned_credit_scaled,
            TOPOSTAKE_FIXED_POINT_SCALE
                .saturating_sub(spec.topostake_config.proposer_fee_ratio_scaled)
        );
        reset_topostake_evidence_runtime();
    }

    #[test]
    fn topostake_fee_settlement_uses_committed_tx_fee_budget() {
        let _guard = TOPOSTAKE_TEST_LOCK.lock().unwrap();
        reset_topostake_evidence_runtime();
        let spec = topostake_enabled_spec_for_tests();
        let fee_budget_wei = 123_456_789;
        let outcomes = record_topostake_tx_gossip_metadata_evidence(
            Epoch::new(0),
            3,
            vec![TopoStakePathEvidence {
                tx_hash: "0xabbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
                    .into(),
                path: vec![0, 1, 3],
                fee_budget_wei,
                irrecoverable_cost_wei: spec.topostake_config.score_cost_reference_wei,
            }],
            &spec,
        );

        assert!(matches!(
            outcomes.as_slice(),
            [TopoStakeEvidenceRecordOutcome::Valid { .. }]
        ));
        let settlement = topostake_fee_settlement_epoch_summaries()
            .into_iter()
            .find(|summary| summary.epoch == Epoch::new(0))
            .expect("fee settlement summary should exist");
        assert_eq!(settlement.total_amount_wei, fee_budget_wei);
        assert_eq!(
            settlement.proposer_amount_wei,
            scaled_mul_div(
                fee_budget_wei,
                spec.topostake_config.proposer_fee_ratio_scaled,
                TOPOSTAKE_FIXED_POINT_SCALE,
            )
        );
        assert_eq!(
            settlement
                .proposer_amount_wei
                .saturating_add(settlement.relay_amount_wei)
                .saturating_add(settlement.burned_amount_wei),
            fee_budget_wei
        );
        assert!(!settlement.conservation_violation);
        reset_topostake_evidence_runtime();
    }

    #[test]
    fn topostake_path_padding_does_not_increase_total_contribution() {
        let spec = topostake_enabled_spec_for_tests();
        let short_total = topostake_path_relay_contributions(&[0, 1, 3], &spec)
            .into_iter()
            .map(|(_, contribution)| contribution)
            .sum::<u64>();
        let padded_total = topostake_path_relay_contributions(&[0, 1, 2, 3], &spec)
            .into_iter()
            .map(|(_, contribution)| contribution)
            .sum::<u64>();

        assert!(short_total > 0);
        assert!(padded_total > 0);
        assert!(padded_total <= short_total);
    }

    #[test]
    fn topostake_score_credit_is_backed_by_irrecoverable_cost() {
        let reference = 42_000;
        assert_eq!(topostake_transaction_credit_weight_scaled(0, reference), 0);
        assert_eq!(
            topostake_transaction_credit_weight_scaled(reference / 2, reference),
            TOPOSTAKE_FIXED_POINT_SCALE / 2
        );
        assert_eq!(
            topostake_transaction_credit_weight_scaled(reference * 2, reference),
            TOPOSTAKE_FIXED_POINT_SCALE
        );
    }

    #[test]
    fn topostake_distinct_txs_with_same_receiver_are_not_duplicates() {
        let _guard = TOPOSTAKE_TEST_LOCK.lock().unwrap();
        reset_topostake_evidence_runtime();
        let spec = topostake_enabled_spec_for_tests();
        let outcomes = record_topostake_tx_gossip_metadata_evidence(
            Epoch::new(0),
            3,
            vec![
                TopoStakePathEvidence {
                    tx_hash: "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
                        .into(),
                    path: vec![0, 1, 3],
                    fee_budget_wei: TOPOSTAKE_FIXED_POINT_SCALE,
                    irrecoverable_cost_wei: spec.topostake_config.score_cost_reference_wei,
                },
                TopoStakePathEvidence {
                    tx_hash: "0xcccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
                        .into(),
                    path: vec![2, 1, 3],
                    fee_budget_wei: TOPOSTAKE_FIXED_POINT_SCALE,
                    irrecoverable_cost_wei: spec.topostake_config.score_cost_reference_wei,
                },
            ],
            &spec,
        );

        assert_eq!(outcomes.len(), 2);
        assert!(
            outcomes
                .iter()
                .all(|outcome| matches!(outcome, TopoStakeEvidenceRecordOutcome::Valid { .. }))
        );
        let summary = topostake_evidence_epoch_summary(Epoch::new(0), &spec);
        assert_eq!(summary.valid_paths, 2);
        assert_eq!(summary.duplicate_receiver_proofs, 0);
        reset_topostake_evidence_runtime();
    }

    #[test]
    fn topostake_duplicate_tx_only_accepts_one_path() {
        let _guard = TOPOSTAKE_TEST_LOCK.lock().unwrap();
        reset_topostake_evidence_runtime();
        let spec = topostake_enabled_spec_for_tests();
        let tx_hash =
            "0xdddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd".to_string();
        let outcomes = record_topostake_tx_gossip_metadata_evidence(
            Epoch::new(0),
            3,
            vec![
                TopoStakePathEvidence {
                    tx_hash: tx_hash.clone(),
                    path: vec![0, 1, 3],
                    fee_budget_wei: TOPOSTAKE_FIXED_POINT_SCALE,
                    irrecoverable_cost_wei: spec.topostake_config.score_cost_reference_wei,
                },
                TopoStakePathEvidence {
                    tx_hash,
                    path: vec![0, 2, 3],
                    fee_budget_wei: TOPOSTAKE_FIXED_POINT_SCALE,
                    irrecoverable_cost_wei: spec.topostake_config.score_cost_reference_wei,
                },
            ],
            &spec,
        );

        assert!(matches!(
            outcomes.as_slice(),
            [
                TopoStakeEvidenceRecordOutcome::Valid { .. },
                TopoStakeEvidenceRecordOutcome::DuplicateTransaction { .. }
            ]
        ));
        let summary = topostake_evidence_epoch_summary(Epoch::new(0), &spec);
        assert_eq!(summary.valid_paths, 1);
        assert_eq!(summary.duplicate_receiver_proofs, 1);
        reset_topostake_evidence_runtime();
    }

    #[test]
    fn topostake_duplicate_tx_across_epochs_is_not_counted_again() {
        let _guard = TOPOSTAKE_TEST_LOCK.lock().unwrap();
        reset_topostake_evidence_runtime();
        let spec = topostake_enabled_spec_for_tests();
        let tx_hash =
            "0xdfdfdfdfdfdfdfdfdfdfdfdfdfdfdfdfdfdfdfdfdfdfdfdfdfdfdfdfdfdfdfdf".to_string();

        let first = record_topostake_tx_gossip_metadata_evidence(
            Epoch::new(4),
            3,
            vec![TopoStakePathEvidence {
                tx_hash: tx_hash.clone(),
                path: vec![0, 1, 2, 3],
                fee_budget_wei: TOPOSTAKE_FIXED_POINT_SCALE,
                irrecoverable_cost_wei: spec.topostake_config.score_cost_reference_wei,
            }],
            &spec,
        );
        let second = record_topostake_tx_gossip_metadata_evidence(
            Epoch::new(5),
            3,
            vec![TopoStakePathEvidence {
                tx_hash,
                path: vec![0, 1, 2, 3],
                fee_budget_wei: TOPOSTAKE_FIXED_POINT_SCALE,
                irrecoverable_cost_wei: spec.topostake_config.score_cost_reference_wei,
            }],
            &spec,
        );

        assert!(matches!(
            first.as_slice(),
            [TopoStakeEvidenceRecordOutcome::Valid { .. }]
        ));
        assert!(matches!(
            second.as_slice(),
            [TopoStakeEvidenceRecordOutcome::DuplicateTransaction { .. }]
        ));
        assert_eq!(
            topostake_evidence_epoch_summary(Epoch::new(4), &spec).valid_paths,
            1
        );
        assert_eq!(
            topostake_evidence_epoch_summary(Epoch::new(5), &spec).valid_paths,
            0
        );
        assert_eq!(
            topostake_evidence_epoch_summary(Epoch::new(5), &spec).duplicate_receiver_proofs,
            1
        );
        reset_topostake_evidence_runtime();
    }

    #[test]
    fn topostake_no_evidence_score_stays_zero() {
        let _guard = TOPOSTAKE_TEST_LOCK.lock().unwrap();
        reset_topostake_evidence_runtime();
        let spec = topostake_enabled_spec_for_tests();

        let settled = topostake_settle_scores_through_epoch(
            Epoch::new(0),
            &[(0, 32_000_000_000), (1, 32_000_000_000)],
            64_000_000_000,
            &spec,
        );

        assert!(settled.is_empty());
        assert_eq!(topostake_evidence_score_for_epoch(Epoch::new(2), 0, 1), 0);
        reset_topostake_evidence_runtime();
    }

    #[test]
    fn topostake_saturation_has_diminishing_returns() {
        let stake = 32_000_000_000;
        let total = 128_000_000_000;
        let k = TOPOSTAKE_FIXED_POINT_SCALE;
        let one =
            topostake_saturate_contribution_scaled(TOPOSTAKE_FIXED_POINT_SCALE, stake, total, k);
        let two = topostake_saturate_contribution_scaled(
            TOPOSTAKE_FIXED_POINT_SCALE.saturating_mul(2),
            stake,
            total,
            k,
        );
        let four = topostake_saturate_contribution_scaled(
            TOPOSTAKE_FIXED_POINT_SCALE.saturating_mul(4),
            stake,
            total,
            k,
        );

        assert!(one > 0);
        assert!(two > one);
        assert!(four > two);
        assert!(two.saturating_sub(one) > four.saturating_sub(two));
    }

    #[test]
    fn topostake_small_stake_repeated_contribution_is_not_linear() {
        let total = 128_000_000_000;
        let k = TOPOSTAKE_FIXED_POINT_SCALE;
        let small_once = topostake_saturate_contribution_scaled(
            TOPOSTAKE_FIXED_POINT_SCALE,
            16_000_000_000,
            total,
            k,
        );
        let small_many = topostake_saturate_contribution_scaled(
            TOPOSTAKE_FIXED_POINT_SCALE.saturating_mul(4),
            16_000_000_000,
            total,
            k,
        );

        assert!(small_once > 0);
        assert!(small_many > small_once);
        assert!(small_many < small_once.saturating_mul(4));
    }

    #[test]
    fn topostake_score_settlement_waits_for_finalized_epoch() {
        let _guard = TOPOSTAKE_TEST_LOCK.lock().unwrap();
        reset_topostake_evidence_runtime();
        let spec = topostake_enabled_spec_for_tests();
        let outcomes = record_topostake_tx_gossip_metadata_evidence(
            Epoch::new(1),
            3,
            vec![TopoStakePathEvidence {
                tx_hash: "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
                    .into(),
                path: vec![0, 1, 3],
                fee_budget_wei: TOPOSTAKE_FIXED_POINT_SCALE,
                irrecoverable_cost_wei: spec.topostake_config.score_cost_reference_wei,
            }],
            &spec,
        );
        assert!(matches!(
            outcomes.as_slice(),
            [TopoStakeEvidenceRecordOutcome::Valid { .. }]
        ));
        assert!(
            topostake_settle_scores_through_epoch(
                Epoch::new(0),
                &[
                    (0, 32_000_000_000),
                    (1, 32_000_000_000),
                    (3, 32_000_000_000)
                ],
                96_000_000_000,
                &spec,
            )
            .is_empty()
        );

        assert!(
            topostake_settle_scores_through_epoch(
                Epoch::new(1),
                &[
                    (0, 32_000_000_000),
                    (1, 32_000_000_000),
                    (3, 32_000_000_000),
                ],
                96_000_000_000,
                &spec,
            )
            .is_empty()
        );

        let settled = topostake_settle_scores_through_epoch(
            Epoch::new(2),
            &[
                (0, 32_000_000_000),
                (1, 32_000_000_000),
                (3, 32_000_000_000),
            ],
            96_000_000_000,
            &spec,
        );
        assert_eq!(settled.len(), 1);
        assert_eq!(settled[0].epoch, Epoch::new(1));
        assert!(
            settled[0]
                .updates
                .iter()
                .any(|update| update.validator_index == 1 && update.score_scaled > 0)
        );
        reset_topostake_evidence_runtime();
    }

    #[test]
    fn topostake_selection_uses_latest_settled_score_before_next_scored_epoch() {
        let _guard = TOPOSTAKE_TEST_LOCK.lock().unwrap();
        reset_topostake_evidence_runtime();
        let spec = topostake_enabled_spec_for_tests();
        let outcomes = record_topostake_tx_gossip_metadata_evidence(
            Epoch::new(0),
            2,
            vec![TopoStakePathEvidence {
                tx_hash: "0xffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
                    .into(),
                path: vec![0, 1, 2],
                fee_budget_wei: TOPOSTAKE_FIXED_POINT_SCALE,
                irrecoverable_cost_wei: spec.topostake_config.score_cost_reference_wei,
            }],
            &spec,
        );
        assert!(matches!(
            outcomes.as_slice(),
            [TopoStakeEvidenceRecordOutcome::Valid { .. }]
        ));

        let settled = topostake_settle_scores_through_epoch(
            Epoch::new(1),
            &[
                (0, 32_000_000_000),
                (1, 32_000_000_000),
                (2, 32_000_000_000),
            ],
            96_000_000_000,
            &spec,
        );
        assert_eq!(settled.len(), 1);

        assert!(
            topostake_evidence_score_for_epoch(Epoch::new(2), 1, 1) > 0,
            "settled score should affect the first eligible proposer epoch"
        );
        assert!(
            topostake_evidence_score_for_epoch(Epoch::new(3), 1, 1) > 0,
            "latest settled score should remain usable when the exact score epoch has no records"
        );
        reset_topostake_evidence_runtime();
    }

    #[test]
    fn test_total_terminal_difficulty() {
        assert_eq!(
            Ok(default_terminal_total_difficulty()),
            "115792089237316195423570985008687907853269984665640564039457584007913129638912"
                .parse()
        );
    }

    #[test]
    fn test_domain_builder() {
        assert_eq!(
            int_to_bytes4(ApplicationDomain::Builder.get_domain_constant()),
            [0, 0, 0, 1]
        );
    }

    #[test]
    fn test_max_network_limits_overflow() {
        let mut spec = MainnetEthSpec::default_spec();
        // Should not overflow
        let _ = spec.max_message_size();
        let _ = spec.max_compressed_len();

        spec.max_payload_size *= 10;
        // Should not overflow even with a 10x increase in max
        let _ = spec.max_message_size();
        let _ = spec.max_compressed_len();
    }

    #[test]
    fn min_epochs_for_data_sidecar_requests_deneb() {
        type E = MainnetEthSpec;
        let spec = Arc::new(ForkName::Deneb.make_genesis_spec(E::default_spec()));
        let blob_retention_epochs = spec.min_epochs_for_blob_sidecars_requests;

        // `min_epochs_for_data_sidecar_requests` cannot be earlier than Deneb fork epoch.
        assert_eq!(
            spec.deneb_fork_epoch,
            spec.min_epoch_data_availability_boundary(Epoch::new(blob_retention_epochs / 2))
        );

        let current_epoch = Epoch::new(blob_retention_epochs * 2);
        let expected_min_blob_epoch = current_epoch - blob_retention_epochs;
        assert_eq!(
            Some(expected_min_blob_epoch),
            spec.min_epoch_data_availability_boundary(current_epoch)
        );
    }

    #[test]
    fn min_epochs_for_data_sidecar_requests_fulu() {
        type E = MainnetEthSpec;
        let spec = {
            let mut spec = ForkName::Deneb.make_genesis_spec(E::default_spec());
            // 4096 * 2 = 8192
            spec.fulu_fork_epoch = Some(Epoch::new(spec.min_epochs_for_blob_sidecars_requests * 2));
            // set a different value for testing purpose, 4096 / 2 = 2048
            spec.min_epochs_for_data_column_sidecars_requests =
                spec.min_epochs_for_blob_sidecars_requests / 2;
            Arc::new(spec)
        };
        let blob_retention_epochs = spec.min_epochs_for_blob_sidecars_requests;
        let data_column_retention_epochs = spec.min_epochs_for_data_column_sidecars_requests;

        // `min_epochs_for_data_sidecar_requests` at fulu fork epoch still uses `min_epochs_for_blob_sidecars_requests`
        let fulu_fork_epoch = spec.fulu_fork_epoch.unwrap();
        let expected_blob_retention_epoch = fulu_fork_epoch - blob_retention_epochs;
        assert_eq!(
            Some(expected_blob_retention_epoch),
            spec.min_epoch_data_availability_boundary(fulu_fork_epoch)
        );

        // Now, the blob retention period starts still before the fulu fork epoch, so the boundary
        // should respect the blob retention period.
        let half_blob_retention_epoch_after_fulu = fulu_fork_epoch + (blob_retention_epochs / 2);
        let expected_blob_retention_epoch =
            half_blob_retention_epoch_after_fulu - blob_retention_epochs;
        assert_eq!(
            Some(expected_blob_retention_epoch),
            spec.min_epoch_data_availability_boundary(half_blob_retention_epoch_after_fulu)
        );

        // If the retention period starts with the fulu fork epoch, there are no more blobs to
        // retain, and the return value will be based on the data column retention period.
        let current_epoch = fulu_fork_epoch + blob_retention_epochs;
        let expected_data_column_retention_epoch = current_epoch - data_column_retention_epochs;
        assert_eq!(
            Some(expected_data_column_retention_epoch),
            spec.min_epoch_data_availability_boundary(current_epoch)
        );
    }

    #[test]
    fn min_epochs_for_data_sidecar_requests_fulu_genesis() {
        type E = MainnetEthSpec;
        let spec = {
            // fulu active at genesis
            let mut spec = ForkName::Fulu.make_genesis_spec(E::default_spec());
            // set a different value for testing purpose, 4096 / 2 = 2048
            spec.min_epochs_for_data_column_sidecars_requests =
                spec.min_epochs_for_blob_sidecars_requests / 2;
            Arc::new(spec)
        };
        let blob_retention_epochs = spec.min_epochs_for_blob_sidecars_requests;
        let data_column_retention_epochs = spec.min_epochs_for_data_column_sidecars_requests;

        // If Fulu is activated at genesis, the column retention period should always be used.
        let assert_correct_boundary = |epoch| {
            let epoch = Epoch::new(epoch);
            assert_eq!(
                Some(epoch.saturating_sub(data_column_retention_epochs)),
                spec.min_epoch_data_availability_boundary(epoch)
            )
        };

        assert_correct_boundary(0);
        assert_correct_boundary(1);
        assert_correct_boundary(blob_retention_epochs - 1);
        assert_correct_boundary(blob_retention_epochs);
        assert_correct_boundary(blob_retention_epochs + 1);
        assert_correct_boundary(data_column_retention_epochs - 1);
        assert_correct_boundary(data_column_retention_epochs);
        assert_correct_boundary(data_column_retention_epochs + 1);
    }

    #[test]
    fn proposer_shuffling_decision_root_around_epoch_boundary() {
        type E = MainnetEthSpec;
        let fulu_fork_epoch = 5;
        let gloas_fork_epoch = 10;
        let spec = {
            let mut spec = ForkName::Electra.make_genesis_spec(E::default_spec());
            spec.fulu_fork_epoch = Some(Epoch::new(fulu_fork_epoch));
            spec.gloas_fork_epoch = Some(Epoch::new(gloas_fork_epoch));
            Arc::new(spec)
        };

        // For epochs prior to AND including the Fulu fork epoch, the decision slot is the end
        // of the previous epoch (i.e. only 1 slot lookahead).
        for epoch in (0..=fulu_fork_epoch).map(Epoch::new) {
            assert_eq!(
                spec.proposer_shuffling_decision_slot::<E>(epoch),
                epoch.start_slot(E::slots_per_epoch()) - 1
            );
        }

        // For epochs after Fulu, the decision slot is the end of the epoch two epochs prior.
        for epoch in ((fulu_fork_epoch + 1)..=(gloas_fork_epoch + 1)).map(Epoch::new) {
            assert_eq!(
                spec.proposer_shuffling_decision_slot::<E>(epoch),
                (epoch - 1).start_slot(E::slots_per_epoch()) - 1
            );
        }
    }

    #[test]
    fn test_slot_component_duration_calculations() {
        let spec = ChainSpec::mainnet().compute_derived_values::<MainnetEthSpec>();

        // Test unaggregated attestation (3333 bps = 33.33% of 12s = 4s)
        let unagg_due = spec.get_unaggregated_attestation_due();
        assert_eq!(unagg_due, Duration::from_millis(3999)); // 12000 * 3333 / 10000

        // Test aggregate attestation (6667 bps = 66.67% of 12s = 8s)
        let agg_due = spec.get_aggregate_attestation_due();
        assert_eq!(agg_due, Duration::from_millis(8000)); // 12000 * 6667 / 10000

        // Test sync message (3333 bps = 33.33% of 12s = 4s)
        let sync_msg_due = spec.get_sync_message_due();
        assert_eq!(sync_msg_due, Duration::from_millis(3999)); // 12000 * 3333 / 10000

        // Test contribution message (6667 bps = 66.67% of 12s = 8s)
        let contribution_due = spec.get_contribution_message_due();
        assert_eq!(contribution_due, Duration::from_millis(8000)); // 12000 * 6667 / 10000

        // Test slot duration
        let slot_duration = spec.get_slot_duration();
        assert_eq!(slot_duration, Duration::from_millis(12000));

        // Test edge cases with custom spec
        let mut custom_spec = spec.clone();

        // Edge case: 0 bps should give 0 duration
        custom_spec.attestation_due_bps = 0;
        let custom_spec = custom_spec.compute_derived_values::<MainnetEthSpec>();
        let zero_due = custom_spec.get_unaggregated_attestation_due();
        assert_eq!(zero_due, Duration::from_millis(0));

        // Edge case: 10000 bps (100%) should give full slot duration
        let mut custom_spec = custom_spec;
        custom_spec.attestation_due_bps = 10_000;
        let custom_spec = custom_spec.compute_derived_values::<MainnetEthSpec>();
        let full_due = custom_spec.get_unaggregated_attestation_due();
        assert_eq!(full_due, Duration::from_millis(12000));

        // Edge case: 5000 bps (50%) should give half slot duration
        let mut custom_spec = custom_spec;
        custom_spec.attestation_due_bps = 5_000;
        let custom_spec = custom_spec.compute_derived_values::<MainnetEthSpec>();
        let half_due = custom_spec.get_unaggregated_attestation_due();
        assert_eq!(half_due, Duration::from_millis(6000));

        // Test with different slot duration (Gnosis: 5s slots)
        let mut custom_spec = custom_spec;
        custom_spec.slot_duration_ms = 5000;
        custom_spec.attestation_due_bps = 3333;
        let custom_spec = custom_spec.compute_derived_values::<MainnetEthSpec>();
        let gnosis_due = custom_spec.get_unaggregated_attestation_due();
        assert_eq!(gnosis_due, Duration::from_millis(1666)); // 5000 * 3333 / 10000

        // Test with very small slot duration
        let mut custom_spec = custom_spec;
        custom_spec.slot_duration_ms = 1000; // 1 second
        custom_spec.attestation_due_bps = 3333;
        let custom_spec = custom_spec.compute_derived_values::<MainnetEthSpec>();
        let small_due = custom_spec.get_unaggregated_attestation_due();
        assert_eq!(small_due, Duration::from_millis(333)); // 1000 * 3333 / 10000

        // Test rounding behavior with non-divisible values
        let mut custom_spec = custom_spec;
        custom_spec.slot_duration_ms = 12000;
        custom_spec.attestation_due_bps = 1; // 0.01%
        let custom_spec = custom_spec.compute_derived_values::<MainnetEthSpec>();
        let tiny_due = custom_spec.get_unaggregated_attestation_due();
        assert_eq!(tiny_due, Duration::from_millis(1)); // 12000 * 1 / 10000 = 1.2 -> 1

        // Test payload due (7500 bps = 75% of 12s = 9s)
        let spec = ChainSpec::mainnet().compute_derived_values::<MainnetEthSpec>();
        let payload_due = spec.get_payload_due();
        assert_eq!(payload_due, Duration::from_millis(9000)); // 12000 * 7500 / 10000

        // Test payload attestation due (7500 bps = 75% of 12s = 9s)
        let payload_att_due = spec.get_payload_attestation_due();
        assert_eq!(payload_att_due, Duration::from_millis(9000)); // 12000 * 7500 / 10000

        // Test gloas attestation due (2500 bps = 25% of 12s = 3s)
        assert_eq!(
            spec.unaggregated_attestation_due_gloas,
            Duration::from_millis(3000)
        ); // 12000 * 2500 / 10000

        // Test gloas with custom bps
        let mut custom_spec = spec;
        custom_spec.attestation_due_bps_gloas = 5000;
        let custom_spec = custom_spec.compute_derived_values::<MainnetEthSpec>();
        assert_eq!(
            custom_spec.unaggregated_attestation_due_gloas,
            Duration::from_millis(6000)
        ); // 12000 * 5000 / 10000
    }

    #[test]
    fn test_default_duration_values_without_compute_derived_values() {
        // Verify that mainnet, minimal, and gnosis have correct pre-computed defaults
        // without needing to call compute_derived_values()
        let mainnet = ChainSpec::mainnet();
        assert_eq!(
            mainnet.get_unaggregated_attestation_due(),
            Duration::from_millis(3999)
        );
        assert_eq!(
            mainnet.get_aggregate_attestation_due(),
            Duration::from_millis(8000)
        );
        assert_eq!(mainnet.get_sync_message_due(), Duration::from_millis(3999));
        assert_eq!(
            mainnet.get_contribution_message_due(),
            Duration::from_millis(8000)
        );

        // Mainnet payload due: 12000ms slots, 7500 bps = 9000ms
        assert_eq!(mainnet.get_payload_due(), Duration::from_millis(9000));
        assert_eq!(
            mainnet.get_payload_attestation_due(),
            Duration::from_millis(9000)
        );

        // Mainnet gloas: 12000ms slots, 2500 bps = 3000ms
        assert_eq!(
            mainnet.unaggregated_attestation_due_gloas,
            Duration::from_millis(3000)
        );

        // Minimal spec: 6000ms slots, 3333 bps = 1999ms, 6667 bps = 4000ms
        let minimal = ChainSpec::minimal();
        assert_eq!(
            minimal.get_unaggregated_attestation_due(),
            Duration::from_millis(1999)
        );
        assert_eq!(
            minimal.get_aggregate_attestation_due(),
            Duration::from_millis(4000)
        );
        assert_eq!(minimal.get_sync_message_due(), Duration::from_millis(1999));
        assert_eq!(
            minimal.get_contribution_message_due(),
            Duration::from_millis(4000)
        );
        // Minimal payload due: 6000ms slots, 7500 bps = 4500ms
        assert_eq!(minimal.get_payload_due(), Duration::from_millis(4500));
        assert_eq!(
            minimal.get_payload_attestation_due(),
            Duration::from_millis(4500)
        );

        // Minimal gloas: 6000ms slots, 2500 bps = 1500ms
        assert_eq!(
            minimal.unaggregated_attestation_due_gloas,
            Duration::from_millis(1500)
        );

        // Gnosis spec: 5000ms slots, 3333 bps = 1666ms, 6667 bps = 3333ms
        let gnosis = ChainSpec::gnosis();
        assert_eq!(
            gnosis.get_unaggregated_attestation_due(),
            Duration::from_millis(1666)
        );
        assert_eq!(
            gnosis.get_aggregate_attestation_due(),
            Duration::from_millis(3333)
        );
        assert_eq!(gnosis.get_sync_message_due(), Duration::from_millis(1666));
        assert_eq!(
            gnosis.get_contribution_message_due(),
            Duration::from_millis(3333)
        );
        // Gnosis payload due: 5000ms slots, 7500 bps = 3750ms
        assert_eq!(gnosis.get_payload_due(), Duration::from_millis(3750));
        assert_eq!(
            gnosis.get_payload_attestation_due(),
            Duration::from_millis(3750)
        );

        // Gnosis gloas: 5000ms slots, 2500 bps = 1250ms
        assert_eq!(
            gnosis.unaggregated_attestation_due_gloas,
            Duration::from_millis(1250)
        );
    }

    #[test]
    #[should_panic(expected = "exceeds slot duration")]
    fn test_compute_derived_values_panics_on_invalid_bps_values() {
        let mut spec = ChainSpec::mainnet();
        // 15000 bps = 150% of slot duration, which is invalid
        spec.attestation_due_bps = 15000;
        spec.compute_derived_values::<MainnetEthSpec>();
    }

    fn configs_base_path() -> PathBuf {
        env::var("CARGO_MANIFEST_DIR")
            .expect("should know manifest dir")
            .parse::<PathBuf>()
            .expect("should parse manifest dir as path")
            .join("configs")
    }

    /// Upstream config keys that Lighthouse intentionally does not include in its
    /// `Config` struct. These are forks/features not yet implemented. Update this
    /// list as new forks are added.
    const UPSTREAM_KEYS_NOT_IN_LIGHTHOUSE: &[&str] = &[
        // Forks not yet implemented
        "HEZE_FORK_VERSION",
        "HEZE_FORK_EPOCH",
        "EIP7928_FORK_VERSION",
        "EIP7928_FORK_EPOCH",
        // Gloas params not yet in Config
        "AGGREGATE_DUE_BPS_GLOAS",
        "SYNC_MESSAGE_DUE_BPS_GLOAS",
        "CONTRIBUTION_DUE_BPS_GLOAS",
        "MAX_REQUEST_PAYLOADS",
        // Heze networking
        "INCLUSION_LIST_DUE_BPS",
        "MAX_REQUEST_INCLUSION_LIST",
        "MAX_BYTES_PER_INCLUSION_LIST",
    ];

    /// Compare a `ChainSpec` against an upstream consensus-specs config YAML file.
    ///
    /// 1. Extracts keys from the raw YAML text (to avoid yaml_serde's inability
    ///    to parse integers > u64 into `Value`/`Mapping` types) and checks that
    ///    every key is either known to `Config` or explicitly listed in
    ///    `UPSTREAM_KEYS_NOT_IN_LIGHTHOUSE`.
    /// 2. Deserializes the upstream YAML as `Config` (which has custom
    ///    deserializers for large values like `TERMINAL_TOTAL_DIFFICULTY`) and
    ///    compares against `Config::from_chain_spec`.
    fn config_test<E: EthSpec>(spec: &ChainSpec, config_name: &str) {
        let file_path = configs_base_path().join(format!("{config_name}.yaml"));
        let upstream_yaml = std::fs::read_to_string(&file_path)
            .unwrap_or_else(|e| panic!("failed to read {}: {e}", file_path.display()));

        // Extract top-level keys from the raw YAML text. We can't parse as
        // yaml_serde::Mapping because yaml_serde cannot represent integers
        // exceeding u64 (e.g. TERMINAL_TOTAL_DIFFICULTY). Config YAML uses a
        // simple `KEY: value` format with no indentation for top-level keys.
        let upstream_keys: BTreeSet<String> = upstream_yaml
            .lines()
            .filter_map(|line| {
                // Skip comments, blank lines, and indented lines (nested YAML).
                if line.is_empty()
                    || line.starts_with('#')
                    || line.starts_with(' ')
                    || line.starts_with('\t')
                {
                    return None;
                }
                line.split(':').next().map(|k| k.to_string())
            })
            .collect();

        // Get the set of keys that Config knows about by serializing and collecting
        // keys. Also include keys for optional fields that may be skipped during
        // serialization (e.g. CONFIG_NAME).
        let our_config = Config::from_chain_spec::<E>(spec);
        let our_yaml = yaml_serde::to_string(&our_config).expect("failed to serialize Config");
        let our_mapping: yaml_serde::Mapping =
            yaml_serde::from_str(&our_yaml).expect("failed to re-parse our Config");
        let mut known_keys: BTreeSet<String> = our_mapping
            .keys()
            .filter_map(|k| k.as_str().map(String::from))
            .collect();
        // Fields that Config knows but may skip during serialization.
        known_keys.insert("CONFIG_NAME".to_string());

        // Check for upstream keys that our Config doesn't know about.
        let mut missing_keys: Vec<&String> = upstream_keys
            .iter()
            .filter(|k| {
                !known_keys.contains(k.as_str())
                    && !UPSTREAM_KEYS_NOT_IN_LIGHTHOUSE.contains(&k.as_str())
            })
            .collect();
        missing_keys.sort();

        assert!(
            missing_keys.is_empty(),
            "Upstream {config_name} config has keys not present in Lighthouse Config \
             (add to Config or to UPSTREAM_KEYS_NOT_IN_LIGHTHOUSE): {missing_keys:?}"
        );

        // Compare values for all fields Config knows about.
        let mut upstream_config: Config = yaml_serde::from_str(&upstream_yaml)
            .unwrap_or_else(|e| panic!("failed to parse {config_name} as Config: {e}"));

        // CONFIG_NAME is network metadata (not a spec parameter), so align it
        // before comparing.
        upstream_config.config_name = our_config.config_name.clone();
        // SECONDS_PER_SLOT is deprecated upstream but we still emit it, so
        // fill it in if the upstream YAML omitted it.
        if upstream_config.seconds_per_slot.is_none() {
            upstream_config.seconds_per_slot = our_config.seconds_per_slot;
        }
        assert_eq!(
            upstream_config, our_config,
            "Config mismatch for {config_name}"
        );
    }

    #[test]
    fn mainnet_config_consistent() {
        let spec = ChainSpec::mainnet();
        config_test::<MainnetEthSpec>(&spec, "mainnet");
    }

    #[test]
    fn minimal_config_consistent() {
        let spec = ChainSpec::minimal();
        config_test::<MinimalEthSpec>(&spec, "minimal");
    }
}
