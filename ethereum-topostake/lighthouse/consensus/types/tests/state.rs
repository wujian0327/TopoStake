#![cfg(test)]
use std::ops::Mul;
use std::sync::{LazyLock, Mutex};

use arbitrary::Arbitrary;
use beacon_chain::test_utils::{BeaconChainHarness, EphemeralHarnessType};
use bls::Keypair;
use fixed_bytes::FixedBytesExtended;
use milhouse::Vector;
use ssz::Encode;
use ssz_types::{FixedVector, VariableList};
use swap_or_not_shuffle::compute_shuffled_index;
use types::test_utils::generate_deterministic_keypairs;
use types::*;

pub const MAX_VALIDATOR_COUNT: usize = 129;
pub const SLOT_OFFSET: Slot = Slot::new(1);

/// A cached set of keys.
static KEYPAIRS: LazyLock<Vec<Keypair>> =
    LazyLock::new(|| generate_deterministic_keypairs(MAX_VALIDATOR_COUNT));
static TOPOSTAKE_EVIDENCE_TEST_LOCK: Mutex<()> = Mutex::new(());

async fn get_harness<E: EthSpec>(
    validator_count: usize,
    slot: Slot,
) -> BeaconChainHarness<EphemeralHarnessType<E>> {
    let harness = BeaconChainHarness::builder(E::default())
        .default_spec()
        .keypairs(KEYPAIRS[0..validator_count].to_vec())
        .fresh_ephemeral_store()
        .mock_execution_layer()
        .build();

    let skip_to_slot = slot - SLOT_OFFSET;
    if skip_to_slot > Slot::new(0) {
        let slots = (skip_to_slot.as_u64()..=slot.as_u64())
            .map(Slot::new)
            .collect::<Vec<_>>();
        let state = harness.get_current_state();
        harness
            .add_attested_blocks_at_slots(
                state,
                slots.as_slice(),
                (0..validator_count).collect::<Vec<_>>().as_slice(),
            )
            .await;
    }
    harness
}

async fn build_state<E: EthSpec>(validator_count: usize) -> BeaconState<E> {
    get_harness(validator_count, Slot::new(0))
        .await
        .chain
        .head_beacon_state_cloned()
}

async fn test_beacon_proposer_index<E: EthSpec>() {
    let spec = E::default_spec();

    // Get the i'th candidate proposer for the given state and slot
    let ith_candidate = |state: &BeaconState<E>, slot: Slot, i: usize, spec: &ChainSpec| {
        let epoch = slot.epoch(E::slots_per_epoch());
        let seed = state.get_beacon_proposer_seed(slot, spec).unwrap();
        let active_validators = state.get_active_validator_indices(epoch, spec).unwrap();
        active_validators[compute_shuffled_index(
            i,
            active_validators.len(),
            &seed,
            spec.shuffle_round_count,
        )
        .unwrap()]
    };

    // Run a test on the state.
    let test = |state: &BeaconState<E>, slot: Slot, candidate_index: usize| {
        assert_eq!(
            state.get_beacon_proposer_index(slot, &spec),
            Ok(ith_candidate(state, slot, candidate_index, &spec))
        );
    };

    // Test where we have one validator per slot.
    // 0th candidate should be chosen every time.
    let state = build_state(E::slots_per_epoch() as usize).await;
    for i in 0..E::slots_per_epoch() {
        test(&state, Slot::from(i), 0);
    }

    // Test where we have two validators per slot.
    // 0th candidate should be chosen every time.
    let state = build_state((E::slots_per_epoch() as usize).mul(2)).await;
    for i in 0..E::slots_per_epoch() {
        test(&state, Slot::from(i), 0);
    }

    // Test with two validators per slot, first validator has zero balance.
    let mut state = build_state::<E>((E::slots_per_epoch() as usize).mul(2)).await;
    let slot0_candidate0 = ith_candidate(&state, Slot::new(0), 0, &spec);
    state
        .validators_mut()
        .get_mut(slot0_candidate0)
        .unwrap()
        .effective_balance = 0;
    test(&state, Slot::new(0), 1);
    for i in 1..E::slots_per_epoch() {
        test(&state, Slot::from(i), 0);
    }
}

#[tokio::test]
async fn beacon_proposer_index() {
    test_beacon_proposer_index::<MinimalEthSpec>().await;
}

#[tokio::test]
async fn topostake_skeleton_preserves_default_proposers_and_roots() {
    type E = MinimalEthSpec;

    let spec = E::default_spec();
    let mut topostake_spec = spec.clone();
    topostake_spec.topostake_config = TopoStakeConfig::devnet_enabled_at(Epoch::new(0));

    let state = build_state::<E>((E::slots_per_epoch() as usize).mul(2)).await;
    let epoch = state.current_epoch();

    assert!(topostake_spec.is_topostake_enabled_at_epoch(epoch));
    assert_eq!(
        topostake_spec
            .topostake_config
            .zero_score_state_skeleton(epoch, state.validators().len()),
        Some(TopoStakeStateSkeleton::zero_scores(
            epoch,
            state.validators().len()
        ))
    );

    let default_proposers = state
        .get_beacon_proposer_indices(epoch, &spec)
        .expect("default proposer duties should compute");
    let topostake_zero_score_proposers = state
        .get_beacon_proposer_indices(epoch, &topostake_spec)
        .expect("topostake zero-score proposer duties should compute");
    assert_eq!(default_proposers, topostake_zero_score_proposers);

    let mut default_state = state.clone();
    let default_state_root = default_state.canonical_root().unwrap();
    let default_latest_block_root = default_state.get_latest_block_root(default_state_root);

    let mut topostake_state = state.clone();
    let topostake_state_root = topostake_state.canonical_root().unwrap();
    let topostake_latest_block_root = topostake_state.get_latest_block_root(topostake_state_root);

    assert_eq!(default_state_root, topostake_state_root);
    assert_eq!(default_latest_block_root, topostake_latest_block_root);
}

#[test]
fn topostake_block_body_evidence_root_changes_body_root() {
    type E = MinimalEthSpec;

    let spec = E::default_spec();
    let mut block = BeaconBlock::<E>::empty(&spec);
    let zero_body_root = block.body_root();
    assert!(block.body().topostake_evidence_root().is_zero());

    *block.body_mut().topostake_evidence_root_mut() = Hash256::repeat_byte(0x42);

    assert_eq!(
        *block.body().topostake_evidence_root(),
        Hash256::repeat_byte(0x42)
    );
    assert_ne!(zero_body_root, block.body_root());
}

#[test]
fn topostake_inline_evidence_record_changes_body_root() {
    type E = MinimalEthSpec;

    let spec = E::default_spec();
    let mut block = BeaconBlock::<E>::empty(&spec);
    let zero_body_root = block.body_root();
    assert!(block.body().topostake_evidence_records().is_empty());

    block
        .body_mut()
        .topostake_evidence_records_mut()
        .push(TopoStakeInlineEvidenceRecord {
            tx_hash: Hash256::repeat_byte(0x11),
            epoch: 3,
            priority_fee_wei: 123_456,
            irrecoverable_cost_wei: 654_321,
            relay_path: VariableList::new(vec![0, 1, 2]).expect("valid relay path"),
            aggregate_signature: FixedVector::new(vec![0x55; 48]).expect("valid signature bytes"),
        })
        .expect("record fits bounded list");

    assert_eq!(block.body().topostake_evidence_records().len(), 1);
    assert_ne!(zero_body_root, block.body_root());
}

#[tokio::test]
async fn topostake_zero_score_preserves_default_proposer_duties() {
    type E = MinimalEthSpec;

    let spec = E::default_spec();
    let mut topostake_spec = spec.clone();
    topostake_spec.topostake_config = TopoStakeConfig::devnet_enabled_at(Epoch::new(0));
    topostake_spec.topostake_config.score_fixture = vec![
        TopoStakeScoreFixture {
            validator_index: 1,
            score_scaled: 0,
        },
        TopoStakeScoreFixture {
            validator_index: 2,
            score_scaled: 0,
        },
    ];

    let state = build_state::<E>((E::slots_per_epoch() as usize).mul(2)).await;
    let epoch = state.current_epoch();

    assert_eq!(
        state.get_beacon_proposer_indices(epoch, &spec).unwrap(),
        state
            .get_beacon_proposer_indices(epoch, &topostake_spec)
            .unwrap()
    );
}

#[tokio::test]
async fn topostake_fixture_changes_proposer_duties_deterministically() {
    type E = MinimalEthSpec;

    let spec = E::default_spec();
    let mut topostake_spec = spec.clone();
    topostake_spec.topostake_config = TopoStakeConfig::devnet_enabled_at(Epoch::new(0));
    topostake_spec.topostake_config.eta_scaled = TOPOSTAKE_FIXED_POINT_SCALE;
    topostake_spec.topostake_config.bonus_cap_scaled = TOPOSTAKE_FIXED_POINT_SCALE;

    let mut state = build_state::<E>((E::slots_per_epoch() as usize).mul(2)).await;
    let epoch = state.current_epoch();
    let max_balance = spec.max_effective_balance_for_fork(state.fork_name_unchecked());

    let mut changed_slot = None;
    for slot in epoch.slot_iter(E::slots_per_epoch()) {
        let seed = state.get_beacon_proposer_seed(slot, &spec).unwrap();
        let active_validators = state.get_active_validator_indices(epoch, &spec).unwrap();
        let first_candidate = active_validators[compute_shuffled_index(
            0,
            active_validators.len(),
            &seed,
            spec.shuffle_round_count,
        )
        .unwrap()];

        state
            .validators_mut()
            .get_mut(first_candidate)
            .unwrap()
            .effective_balance = max_balance / 2;
        topostake_spec.topostake_config.score_fixture = vec![TopoStakeScoreFixture {
            validator_index: first_candidate as u64,
            score_scaled: TOPOSTAKE_FIXED_POINT_SCALE,
        }];

        let default_proposer = state.get_beacon_proposer_index(slot, &spec).unwrap();
        let topostake_proposer = state
            .get_beacon_proposer_index(slot, &topostake_spec)
            .unwrap();
        if default_proposer != topostake_proposer {
            changed_slot = Some((slot, first_candidate, default_proposer, topostake_proposer));
            break;
        }

        state
            .validators_mut()
            .get_mut(first_candidate)
            .unwrap()
            .effective_balance = max_balance;
    }

    let (slot, boosted_validator, default_proposer, topostake_proposer) =
        changed_slot.expect("fixture should change at least one proposer duty");
    assert_eq!(topostake_proposer, boosted_validator);
    assert_ne!(default_proposer, topostake_proposer);
    assert_eq!(
        state
            .get_beacon_proposer_index(slot, &topostake_spec)
            .unwrap(),
        topostake_proposer,
        "same state/slot/seed should produce the same TopoStake proposer"
    );
}

#[test]
fn topostake_bonus_cap_bound() {
    let mut config = TopoStakeConfig::devnet_enabled_at(Epoch::new(0));
    config.eta_scaled = TOPOSTAKE_FIXED_POINT_SCALE / 4;
    config.bonus_cap_scaled = TOPOSTAKE_FIXED_POINT_SCALE;
    config.score_fixture = vec![TopoStakeScoreFixture {
        validator_index: 0,
        score_scaled: TOPOSTAKE_FIXED_POINT_SCALE * 10,
    }];

    let balance = 32_000_000_000;
    let total_active_balance = balance * 4;
    let expected_multiplier: u64 = 1_196_078_431;
    assert_eq!(
        config.proposer_weight_scaled_at_epoch(Epoch::new(0), balance, total_active_balance, 0),
        u128::from(balance) * u128::from(expected_multiplier)
    );
    assert!(
        config.proposer_weight_scaled_at_epoch(Epoch::new(0), balance, total_active_balance, 0)
            <= config.max_proposer_weight_scaled(balance)
    );
}

#[test]
fn topostake_proposer_bonus_uses_damped_score_over_stake_share() {
    let mut config = TopoStakeConfig::devnet_enabled_at(Epoch::new(0));
    config.eta_scaled = TOPOSTAKE_FIXED_POINT_SCALE;
    config.bonus_cap_scaled = TOPOSTAKE_FIXED_POINT_SCALE;
    config.score_fixture = vec![
        TopoStakeScoreFixture {
            validator_index: 0,
            score_scaled: TOPOSTAKE_FIXED_POINT_SCALE,
        },
        TopoStakeScoreFixture {
            validator_index: 1,
            score_scaled: TOPOSTAKE_FIXED_POINT_SCALE * 4,
        },
    ];

    let balance = 32_000_000_000;
    let total_active_balance = balance * 2;

    assert_eq!(
        config.bonus_scaled_at_epoch(Epoch::new(0), balance, total_active_balance, 0),
        249_999_999,
        "damped score mass uses the concave bonus without a positive-part threshold"
    );
    assert_eq!(
        config.bonus_scaled_at_epoch(Epoch::new(0), balance, total_active_balance, 1),
        571_428_571,
        "larger damped score-to-stake ratio yields a larger concave bonus"
    );
}

#[test]
fn topostake_bonus_denominator_excludes_inactive_validators() {
    let mut config = TopoStakeConfig::devnet_enabled_at(Epoch::new(0));
    config.score_fixture = vec![
        TopoStakeScoreFixture {
            validator_index: 0,
            score_scaled: TOPOSTAKE_FIXED_POINT_SCALE,
        },
        TopoStakeScoreFixture {
            validator_index: 2,
            score_scaled: TOPOSTAKE_FIXED_POINT_SCALE * 100,
        },
    ];

    let balance = 32_000_000_000;
    let total_active_balance = balance * 2;
    let active_score_total = config.score_total_for_validators_at_epoch(Epoch::new(0), &[0, 1]);
    let active_set_bonus = config.bonus_scaled_at_epoch_with_score_total(
        Epoch::new(0),
        balance,
        total_active_balance,
        0,
        active_score_total,
    );
    let registry_wide_bonus =
        config.bonus_scaled_at_epoch(Epoch::new(0), balance, total_active_balance, 0);

    assert_eq!(active_score_total, TOPOSTAKE_FIXED_POINT_SCALE);
    assert!(active_set_bonus > registry_wide_bonus);
}

#[test]
fn topostake_frozen_v1_matches_shared_golden_vectors() {
    let vectors: serde_json::Value = serde_json::from_str(include_str!(
        "../../../../../experiments/golden/frozen_v1_vectors.yaml"
    ))
    .expect("shared frozen-v1 vectors should parse");
    for vector in vectors["credit_weights"]
        .as_array()
        .expect("credit weight vectors should be an array")
    {
        let irrecoverable_cost = vector["irrecoverable_cost"]
            .as_f64()
            .expect("irrecoverable cost should be numeric");
        let reference_cost = vector["reference_cost"]
            .as_f64()
            .expect("reference cost should be numeric");
        let expected = vector["expected"]
            .as_f64()
            .expect("expected credit weight should be numeric");
        let actual = topostake_transaction_credit_weight_scaled(
            (irrecoverable_cost * 1_000.0).round() as u64,
            (reference_cost * 1_000.0).round() as u64,
        );
        assert_eq!(
            actual,
            (expected * TOPOSTAKE_FIXED_POINT_SCALE as f64) as u64
        );
    }

    let config = TopoStakeConfig::devnet_enabled_at(Epoch::new(0));
    for vector in vectors["bonuses"]
        .as_array()
        .expect("bonus vectors should be an array")
    {
        let ratio = vector["score_to_stake"]
            .as_f64()
            .expect("score-to-stake ratio should be numeric");
        let expected = vector["expected"]
            .as_f64()
            .expect("expected bonus should be numeric");
        let actual = config
            .concave_bonus_scaled((ratio * TOPOSTAKE_FIXED_POINT_SCALE as f64).round() as u64);
        let expected_scaled = (expected * TOPOSTAKE_FIXED_POINT_SCALE as f64).round() as u64;
        assert!(actual.abs_diff(expected_scaled) <= 1);
    }
}

#[test]
fn topostake_unfinalized_path_score_does_not_affect_proposer_weight() {
    let _guard = TOPOSTAKE_EVIDENCE_TEST_LOCK.lock().unwrap();
    reset_topostake_evidence_runtime();

    let mut spec = MinimalEthSpec::default_spec();
    spec.topostake_config = TopoStakeConfig::devnet_enabled_at(Epoch::new(0));
    spec.topostake_config.eta_scaled = TOPOSTAKE_FIXED_POINT_SCALE;
    spec.topostake_config.evidence_finality_depth = 1;
    record_topostake_tx_gossip_metadata_evidence(
        Epoch::new(0),
        2,
        vec![TopoStakePathEvidence {
            tx_hash: "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
                .to_string(),
            path: vec![0, 1, 2],
            fee_budget_wei: TOPOSTAKE_FIXED_POINT_SCALE,
            irrecoverable_cost_wei: spec.topostake_config.score_cost_reference_wei,
        }],
        &spec,
    );

    let balance = 32_000_000_000;
    let total_active_balance = balance * 3;
    assert_eq!(
        spec.topostake_config.bonus_scaled_at_epoch(
            Epoch::new(1),
            balance,
            total_active_balance,
            1,
        ),
        0,
        "epoch 0 path evidence is not selectable before its activation snapshot"
    );

    let early_settled = topostake_settle_scores_through_epoch(
        Epoch::new(0),
        &[(0, balance), (1, balance), (2, balance)],
        total_active_balance,
        &spec,
    );
    assert!(early_settled.is_empty());
    assert_eq!(
        spec.topostake_config.bonus_scaled_at_epoch(
            Epoch::new(2),
            balance,
            total_active_balance,
            1,
        ),
        0,
        "finalized epoch 0 has not reached its activation snapshot"
    );

    topostake_settle_scores_through_epoch(
        Epoch::new(1),
        &[(0, balance), (1, balance), (2, balance)],
        total_active_balance,
        &spec,
    );
    assert_eq!(
        spec.topostake_config.bonus_scaled_at_epoch(
            Epoch::new(2),
            balance,
            total_active_balance,
            1,
        ),
        0,
        "the proposer-weight snapshot remains frozen for the rest of epoch 2"
    );
    assert!(
        spec.topostake_config.bonus_scaled_at_epoch(
            Epoch::new(3),
            balance,
            total_active_balance,
            1,
        ) > 0,
        "the settled root can affect the first later proposer snapshot that observes it"
    );
    reset_topostake_evidence_runtime();
}

fn topostake_test_graffiti(value: &str) -> Graffiti {
    let mut bytes = [0; GRAFFITI_BYTES_LEN];
    bytes[..value.len()].copy_from_slice(value.as_bytes());
    Graffiti::from(bytes)
}

#[test]
fn topostake_costless_graffiti_evidence_does_not_purchase_score() {
    let _guard = TOPOSTAKE_EVIDENCE_TEST_LOCK.lock().unwrap();
    reset_topostake_evidence_runtime();

    let mut spec = MinimalEthSpec::default_spec();
    spec.topostake_config = TopoStakeConfig::devnet_enabled_at(Epoch::new(0));
    spec.topostake_config.evidence_finality_depth = 1;

    let valid = topostake_test_graffiti("TPS1:0,1,2,3");
    assert_eq!(
        decode_topostake_graffiti_evidence(&valid, &spec).unwrap(),
        Some(vec![0, 1, 2, 3])
    );
    let outcome = record_topostake_graffiti_evidence(Epoch::new(0), 42, &valid, &spec);
    assert!(matches!(
        outcome,
        TopoStakeEvidenceRecordOutcome::Valid { receiver: 3, .. }
    ));

    let summary = topostake_evidence_epoch_summary(Epoch::new(0), &spec);
    assert_eq!(summary.valid_paths, 1);
    assert_eq!(summary.invalid_paths, 0);
    assert_eq!(summary.duplicate_receiver_proofs, 0);
    assert_eq!(summary.scored_validators, 0);
    assert_eq!(summary.max_score_scaled, 0);
    assert!(!summary.bound_violation);

    assert_eq!(
        spec.topostake_config
            .score_for_validator_at_epoch(Epoch::new(0), 1),
        0,
        "evidence should not affect the same epoch"
    );
    assert_eq!(
        spec.topostake_config
            .score_for_validator_at_epoch(Epoch::new(1), 1),
        0,
        "default finality depth delays score application by one extra epoch"
    );
    assert!(
        topostake_settle_scores_through_epoch(
            Epoch::new(0),
            &[
                (0, 32_000_000_000),
                (1, 32_000_000_000),
                (2, 32_000_000_000),
                (3, 32_000_000_000)
            ],
            128_000_000_000,
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
                (2, 32_000_000_000),
                (3, 32_000_000_000)
            ],
            128_000_000_000,
            &spec,
        )
        .len()
            == 1
    );
    assert_eq!(
        spec.topostake_config
            .score_for_validator_at_epoch(Epoch::new(2), 1),
        0,
        "evidence without a protocol-visible irrecoverable cost earns no score"
    );
    assert_eq!(
        spec.topostake_config
            .score_for_validator_at_epoch(Epoch::new(2), 0),
        0,
        "origin relay should not receive path score"
    );
}

#[test]
fn topostake_credit_ledger_records_valid_paths_only() {
    let _guard = TOPOSTAKE_EVIDENCE_TEST_LOCK.lock().unwrap();
    reset_topostake_evidence_runtime();

    let mut spec = MinimalEthSpec::default_spec();
    spec.topostake_config = TopoStakeConfig::devnet_enabled_at(Epoch::new(0));
    spec.topostake_config.reward_settlement_depth = 2;
    spec.topostake_config.proposer_fee_ratio_scaled = TOPOSTAKE_FIXED_POINT_SCALE / 2;

    let valid = topostake_test_graffiti("TPS1:0,1,2,3");
    let outcome = record_topostake_graffiti_evidence(Epoch::new(0), 9, &valid, &spec);
    assert!(matches!(
        outcome,
        TopoStakeEvidenceRecordOutcome::Valid { .. }
    ));

    let summaries = topostake_credit_epoch_summaries();
    assert_eq!(summaries.len(), 1);
    let summary = &summaries[0];
    assert_eq!(summary.epoch, Epoch::new(0));
    assert_eq!(summary.credit_records, 1);
    assert_eq!(summary.pending_records, 1);
    assert_eq!(summary.settled_records, 0);
    assert_eq!(summary.total_budget_scaled, TOPOSTAKE_FIXED_POINT_SCALE);
    assert_eq!(
        summary.proposer_credit_scaled,
        TOPOSTAKE_FIXED_POINT_SCALE / 2
    );
    assert_eq!(summary.relay_credit_scaled, 239_644_969);
    assert_eq!(summary.burned_credit_scaled, 260_355_031);
    assert!(!summary.conservation_violation);
    assert_eq!(
        summary.proposer_credits,
        vec![TopoStakeValidatorCredit {
            validator_index: 9,
            credit_scaled: TOPOSTAKE_FIXED_POINT_SCALE / 2,
        }]
    );
    assert_eq!(
        summary.relay_credits,
        vec![
            TopoStakeValidatorCredit {
                validator_index: 1,
                credit_scaled: 165_908_056,
            },
            TopoStakeValidatorCredit {
                validator_index: 2,
                credit_scaled: 73_736_913,
            },
        ]
    );

    topostake_settle_credits_through_epoch(Epoch::new(1));
    let summary = topostake_credit_epoch_summaries()
        .pop()
        .expect("credit summary should exist");
    assert_eq!(summary.pending_records, 1);
    assert_eq!(summary.settled_records, 0);

    topostake_settle_credits_through_epoch(Epoch::new(2));
    let summary = topostake_credit_epoch_summaries()
        .pop()
        .expect("credit summary should exist");
    assert_eq!(summary.pending_records, 0);
    assert_eq!(summary.settled_records, 1);

    let csv = topostake_credit_csv_snapshot();
    assert!(csv.contains("epoch,credit_records,pending_records"));
    assert!(csv.contains("0,1,0,1,1000000000,500000000,239644969,260355031,false"));

    let fee_csv = topostake_fee_settlement_csv_snapshot();
    assert!(fee_csv.contains("epoch,settlement_records,pending_records"));
    assert!(fee_csv.contains("0,1,0,1,1000000000,500000000,239644969,260355031,false"));

    let fee_summary = topostake_fee_settlement_epoch_summaries()
        .pop()
        .expect("fee settlement summary should exist");
    assert_eq!(fee_summary.settlement_records, 1);
    assert_eq!(fee_summary.pending_records, 0);
    assert_eq!(fee_summary.settled_records, 1);
    assert_eq!(
        fee_summary.proposer_amount_wei,
        TOPOSTAKE_FIXED_POINT_SCALE / 2
    );
    assert_eq!(fee_summary.relay_amount_wei, 239_644_969);
    assert_eq!(fee_summary.burned_amount_wei, 260_355_031);
    assert!(!fee_summary.conservation_violation);
}

#[test]
fn topostake_invalid_and_duplicate_evidence_do_not_add_score() {
    let _guard = TOPOSTAKE_EVIDENCE_TEST_LOCK.lock().unwrap();
    reset_topostake_evidence_runtime();

    let mut spec = MinimalEthSpec::default_spec();
    spec.topostake_config = TopoStakeConfig::devnet_enabled_at(Epoch::new(0));

    let valid = topostake_test_graffiti("TPS1:0,1,2,3");
    let duplicate_receiver = topostake_test_graffiti("TPS1:0,1,2,3");
    let repeated_identity = topostake_test_graffiti("TPS1:5,5");

    assert!(matches!(
        record_topostake_graffiti_evidence(Epoch::new(0), 42, &valid, &spec),
        TopoStakeEvidenceRecordOutcome::Valid { .. }
    ));
    assert!(matches!(
        record_topostake_graffiti_evidence(Epoch::new(0), 42, &duplicate_receiver, &spec),
        TopoStakeEvidenceRecordOutcome::DuplicateTransaction {
            source: TopoStakeEvidenceSource::InlineGraffiti,
            ..
        }
    ));
    assert!(matches!(
        record_topostake_graffiti_evidence(Epoch::new(0), 42, &repeated_identity, &spec),
        TopoStakeEvidenceRecordOutcome::Invalid { .. }
    ));

    let summary = topostake_evidence_epoch_summary(Epoch::new(0), &spec);
    assert_eq!(summary.valid_paths, 1);
    assert_eq!(summary.duplicate_receiver_proofs, 1);
    assert_eq!(summary.invalid_paths, 1);
    assert_eq!(
        spec.topostake_config
            .score_for_validator_at_epoch(Epoch::new(2), 4),
        0,
        "duplicate receiver proof should not add a second score"
    );
    assert_eq!(
        spec.topostake_config
            .score_for_validator_at_epoch(Epoch::new(2), 5),
        0,
        "invalid repeated identity evidence should produce zero score"
    );

    let credit_summary = topostake_credit_epoch_summaries()
        .pop()
        .expect("valid evidence should create one credit summary");
    assert_eq!(credit_summary.credit_records, 1);
    assert_eq!(
        credit_summary.total_budget_scaled,
        TOPOSTAKE_FIXED_POINT_SCALE
    );
    assert_eq!(credit_summary.proposer_credits.len(), 1);
    assert_eq!(credit_summary.proposer_credits[0].validator_index, 42);
    assert!(
        !credit_summary
            .relay_credits
            .iter()
            .any(|credit| matches!(credit.validator_index, 4 | 5)),
        "duplicate and invalid evidence should not add relay credits"
    );

    let csv = topostake_evidence_csv_snapshot(&spec);
    assert!(csv.contains("epoch,valid_paths,invalid_paths"));
    assert!(csv.contains("0,1,1,1,0,"), "unexpected CSV: {csv}");
}

/// Test that
///
/// 1. Using the cache before it's built fails.
/// 2. Using the cache after it's build passes.
/// 3. Using the cache after it's dropped fails.
fn test_cache_initialization<E: EthSpec>(
    state: &mut BeaconState<E>,
    relative_epoch: RelativeEpoch,
    spec: &ChainSpec,
) {
    let slot = relative_epoch
        .into_epoch(state.slot().epoch(E::slots_per_epoch()))
        .start_slot(E::slots_per_epoch());

    // Build the cache.
    state.build_committee_cache(relative_epoch, spec).unwrap();

    // Assert a call to a cache-using function passes.
    state.get_beacon_committee(slot, 0).unwrap();

    // Drop the cache.
    state.drop_committee_cache(relative_epoch).unwrap();

    // Assert a call to a cache-using function fail.
    assert_eq!(
        state.get_beacon_committee(slot, 0),
        Err(BeaconStateError::CommitteeCacheUninitialized(Some(
            relative_epoch
        )))
    );
}

#[tokio::test]
async fn cache_initialization() {
    let spec = MinimalEthSpec::default_spec();

    let mut state = build_state::<MinimalEthSpec>(16).await;

    *state.slot_mut() =
        (MinimalEthSpec::genesis_epoch() + 1).start_slot(MinimalEthSpec::slots_per_epoch());

    test_cache_initialization(&mut state, RelativeEpoch::Previous, &spec);
    test_cache_initialization(&mut state, RelativeEpoch::Current, &spec);
    test_cache_initialization(&mut state, RelativeEpoch::Next, &spec);
}

/// Tests committee-specific components
#[cfg(test)]
mod committees {
    use super::*;
    use std::ops::{Add, Div};
    use swap_or_not_shuffle::shuffle_list;

    fn execute_committee_consistency_test<E: EthSpec>(
        state: BeaconState<E>,
        epoch: Epoch,
        validator_count: usize,
        spec: &ChainSpec,
    ) {
        let active_indices: Vec<usize> = (0..validator_count).collect();
        let seed = state.get_seed(epoch, Domain::BeaconAttester, spec).unwrap();
        let relative_epoch = RelativeEpoch::from_epoch(state.current_epoch(), epoch).unwrap();

        let mut ordered_indices = state
            .get_cached_active_validator_indices(relative_epoch)
            .unwrap()
            .to_vec();
        ordered_indices.sort_unstable();
        assert_eq!(
            active_indices, ordered_indices,
            "Validator indices mismatch"
        );

        let shuffling =
            shuffle_list(active_indices, spec.shuffle_round_count, &seed[..], false).unwrap();

        let mut expected_indices_iter = shuffling.iter();

        // Loop through all slots in the epoch being tested.
        for slot in epoch.slot_iter(E::slots_per_epoch()) {
            let beacon_committees = state.get_beacon_committees_at_slot(slot).unwrap();

            // Assert that the number of committees in this slot is consistent with the reported number
            // of committees in an epoch.
            assert_eq!(
                beacon_committees.len() as u64,
                state
                    .get_epoch_committee_count(relative_epoch)
                    .unwrap()
                    .div(E::slots_per_epoch())
            );

            for (committee_index, bc) in beacon_committees.iter().enumerate() {
                // Assert that indices are assigned sequentially across committees.
                assert_eq!(committee_index as u64, bc.index);
                // Assert that a committee lookup via slot is identical to a committee lookup via
                // index.
                assert_eq!(state.get_beacon_committee(bc.slot, bc.index).unwrap(), *bc);

                // Loop through each validator in the committee.
                for (committee_i, validator_i) in bc.committee.iter().enumerate() {
                    // Assert the validators are assigned contiguously across committees.
                    assert_eq!(
                        *validator_i,
                        *expected_indices_iter.next().unwrap(),
                        "Non-sequential validators."
                    );
                    // Assert a call to `get_attestation_duties` is consistent with a call to
                    // `get_beacon_committees_at_slot`
                    let attestation_duty = state
                        .get_attestation_duties(*validator_i, relative_epoch)
                        .unwrap()
                        .unwrap();
                    assert_eq!(attestation_duty.slot, slot);
                    assert_eq!(attestation_duty.index, bc.index);
                    assert_eq!(attestation_duty.committee_position, committee_i);
                    assert_eq!(attestation_duty.committee_len, bc.committee.len());
                }
            }
        }

        // Assert that all validators were assigned to a committee.
        assert!(expected_indices_iter.next().is_none());
    }

    async fn committee_consistency_test<E: EthSpec>(
        validator_count: usize,
        state_epoch: Epoch,
        cache_epoch: RelativeEpoch,
    ) {
        let spec = &E::default_spec();

        let slot = state_epoch.start_slot(E::slots_per_epoch());
        let harness = get_harness::<E>(validator_count, slot).await;
        let mut new_head_state = harness.get_current_state();

        let distinct_hashes =
            (0..E::epochs_per_historical_vector()).map(|i| Hash256::from_low_u64_be(i as u64));
        *new_head_state.randao_mixes_mut() = Vector::try_from_iter(distinct_hashes).unwrap();

        new_head_state
            .force_build_committee_cache(RelativeEpoch::Previous, spec)
            .unwrap();
        new_head_state
            .force_build_committee_cache(RelativeEpoch::Current, spec)
            .unwrap();
        new_head_state
            .force_build_committee_cache(RelativeEpoch::Next, spec)
            .unwrap();

        let cache_epoch = cache_epoch.into_epoch(state_epoch);

        execute_committee_consistency_test(new_head_state, cache_epoch, validator_count, spec);
    }

    async fn committee_consistency_test_suite<E: EthSpec>(cached_epoch: RelativeEpoch) {
        let spec = E::default_spec();

        let validator_count = spec
            .max_committees_per_slot
            .mul(E::slots_per_epoch() as usize)
            .mul(spec.target_committee_size)
            .add(1);

        committee_consistency_test::<E>(validator_count, Epoch::new(0), cached_epoch).await;

        committee_consistency_test::<E>(validator_count, E::genesis_epoch() + 4, cached_epoch)
            .await;

        committee_consistency_test::<E>(
            validator_count,
            E::genesis_epoch()
                + (E::slots_per_historical_root() as u64)
                    .mul(E::slots_per_epoch())
                    .mul(4),
            cached_epoch,
        )
        .await;
    }

    #[tokio::test]
    async fn current_epoch_committee_consistency() {
        committee_consistency_test_suite::<MinimalEthSpec>(RelativeEpoch::Current).await;
    }

    #[tokio::test]
    async fn previous_epoch_committee_consistency() {
        committee_consistency_test_suite::<MinimalEthSpec>(RelativeEpoch::Previous).await;
    }

    #[tokio::test]
    async fn next_epoch_committee_consistency() {
        committee_consistency_test_suite::<MinimalEthSpec>(RelativeEpoch::Next).await;
    }
}

#[test]
fn decode_base_and_altair() {
    type E = MainnetEthSpec;
    let spec = E::default_spec();

    let mut u = types::test_utils::test_unstructured();

    let fork_epoch = spec.altair_fork_epoch.unwrap();

    let base_epoch = fork_epoch.saturating_sub(1_u64);
    let base_slot = base_epoch.end_slot(E::slots_per_epoch());
    let altair_epoch = fork_epoch;
    let altair_slot = altair_epoch.start_slot(E::slots_per_epoch());

    // BeaconStateBase
    {
        let good_base_state: BeaconState<MainnetEthSpec> = BeaconState::Base(BeaconStateBase {
            slot: base_slot,
            ..<_>::arbitrary(&mut u).unwrap()
        });
        // It's invalid to have a base state with a slot higher than the fork slot.
        let bad_base_state = {
            let mut bad = good_base_state.clone();
            *bad.slot_mut() = altair_slot;
            bad
        };

        assert_eq!(
            BeaconState::from_ssz_bytes(&good_base_state.as_ssz_bytes(), &spec)
                .expect("good base state can be decoded"),
            good_base_state
        );
        <BeaconState<MainnetEthSpec>>::from_ssz_bytes(&bad_base_state.as_ssz_bytes(), &spec)
            .expect_err("bad base state cannot be decoded");
    }

    // BeaconStateAltair
    {
        let good_altair_state: BeaconState<MainnetEthSpec> =
            BeaconState::Altair(BeaconStateAltair {
                slot: altair_slot,
                ..<_>::arbitrary(&mut u).unwrap()
            });
        // It's invalid to have an Altair state with a slot lower than the fork slot.
        let bad_altair_state = {
            let mut bad = good_altair_state.clone();
            *bad.slot_mut() = base_slot;
            bad
        };

        assert_eq!(
            BeaconState::from_ssz_bytes(&good_altair_state.as_ssz_bytes(), &spec)
                .expect("good altair state can be decoded"),
            good_altair_state
        );
        <BeaconState<MainnetEthSpec>>::from_ssz_bytes(&bad_altair_state.as_ssz_bytes(), &spec)
            .expect_err("bad altair state cannot be decoded");
    }
}
