pub use metrics::*;
use std::sync::LazyLock;

/*
 * Participation Metrics
 */
pub static PARTICIPATION_PREV_EPOCH_HEAD_ATTESTING_GWEI_TOTAL: LazyLock<Result<IntGauge>> =
    LazyLock::new(|| {
        try_create_int_gauge(
            "beacon_participation_prev_epoch_head_attesting_gwei_total",
            "Total effective balance (gwei) of validators who attested to the head in the previous epoch",
        )
    });
pub static PARTICIPATION_PREV_EPOCH_TARGET_ATTESTING_GWEI_TOTAL: LazyLock<Result<IntGauge>> =
    LazyLock::new(|| {
        try_create_int_gauge(
            "beacon_participation_prev_epoch_target_attesting_gwei_total",
            "Total effective balance (gwei) of validators who attested to the target in the previous epoch",
        )
    });
pub static PARTICIPATION_PREV_EPOCH_SOURCE_ATTESTING_GWEI_TOTAL: LazyLock<Result<IntGauge>> =
    LazyLock::new(|| {
        try_create_int_gauge(
            "beacon_participation_prev_epoch_source_attesting_gwei_total",
            "Total effective balance (gwei) of validators who attested to the source in the previous epoch",
        )
    });
pub static PARTICIPATION_CURRENT_EPOCH_TOTAL_ACTIVE_GWEI_TOTAL: LazyLock<Result<IntGauge>> =
    LazyLock::new(|| {
        try_create_int_gauge(
            "beacon_participation_current_epoch_active_gwei_total",
            "Total effective balance (gwei) of validators who are active in the current epoch",
        )
    });
/*
 * Processing metrics
 */
pub static PROCESS_EPOCH_TIME: LazyLock<Result<Histogram>> = LazyLock::new(|| {
    try_create_histogram(
        "beacon_state_processing_process_epoch",
        "Time required for process_epoch",
    )
});
pub static BUILD_EPOCH_CACHE_TIME: LazyLock<Result<Histogram>> = LazyLock::new(|| {
    try_create_histogram(
        "beacon_state_processing_epoch_cache",
        "Time required to build the epoch cache",
    )
});
pub static BUILD_PROGRESSIVE_BALANCES_CACHE_TIME: LazyLock<Result<Histogram>> =
    LazyLock::new(|| {
        try_create_histogram(
            "beacon_state_processing_progressive_balances_cache",
            "Time required to build the progressive balances cache",
        )
    });

/*
 * TopoStake devnet evidence metrics
 */
pub static TOPOSTAKE_EVIDENCE_PATHS_TOTAL: LazyLock<Result<IntCounterVec>> = LazyLock::new(|| {
    try_create_int_counter_vec(
        "topostake_evidence_paths_total",
        "Total number of TopoStake path evidence records observed during block processing",
        &["outcome"],
    )
});

pub static TOPOSTAKE_EVIDENCE_SOURCES_TOTAL: LazyLock<Result<IntCounterVec>> =
    LazyLock::new(|| {
        try_create_int_counter_vec(
            "topostake_evidence_sources_total",
            "Total number of valid TopoStake path evidence records by evidence source",
            &["source"],
        )
    });

pub static TOPOSTAKE_EVIDENCE_EPOCH_VALID_PATHS: LazyLock<Result<IntGaugeVec>> =
    LazyLock::new(|| {
        try_create_int_gauge_vec(
            "topostake_evidence_epoch_valid_paths",
            "Number of valid TopoStake path evidence records observed for an evidence epoch",
            &["epoch"],
        )
    });

pub static TOPOSTAKE_EVIDENCE_EPOCH_INVALID_PATHS: LazyLock<Result<IntGaugeVec>> =
    LazyLock::new(|| {
        try_create_int_gauge_vec(
            "topostake_evidence_epoch_invalid_paths",
            "Number of invalid TopoStake path evidence records observed for an evidence epoch",
            &["epoch"],
        )
    });

pub static TOPOSTAKE_EVIDENCE_EPOCH_DUPLICATE_RECEIVERS: LazyLock<Result<IntGaugeVec>> =
    LazyLock::new(|| {
        try_create_int_gauge_vec(
            "topostake_evidence_epoch_duplicate_receivers",
            "Number of duplicate TopoStake receiver proofs observed for an evidence epoch",
            &["epoch"],
        )
    });

pub static TOPOSTAKE_EVIDENCE_EPOCH_SCORED_VALIDATORS: LazyLock<Result<IntGaugeVec>> =
    LazyLock::new(|| {
        try_create_int_gauge_vec(
            "topostake_evidence_epoch_scored_validators",
            "Number of validators with non-zero TopoStake evidence score for an evidence epoch",
            &["epoch"],
        )
    });

pub static TOPOSTAKE_EVIDENCE_EPOCH_MAX_SCORE_SCALED: LazyLock<Result<IntGaugeVec>> =
    LazyLock::new(|| {
        try_create_int_gauge_vec(
            "topostake_evidence_epoch_max_score_scaled",
            "Maximum scaled TopoStake evidence score observed for an evidence epoch",
            &["epoch"],
        )
    });

pub static TOPOSTAKE_EVIDENCE_EPOCH_BOUND_VIOLATION: LazyLock<Result<IntGaugeVec>> = LazyLock::new(
    || {
        try_create_int_gauge_vec(
            "topostake_evidence_epoch_bound_violation",
            "Whether any TopoStake evidence score exceeds the configured bonus cap for an evidence epoch",
            &["epoch"],
        )
    },
);

pub static TOPOSTAKE_EPOCH_SCORE_SCALED: LazyLock<Result<IntGaugeVec>> = LazyLock::new(|| {
    try_create_int_gauge_vec(
        "topostake_epoch_score_scaled",
        "Scaled TopoStake propagation score by evidence epoch and validator",
        &["evidence_epoch", "validator_index"],
    )
});

pub static TOPOSTAKE_EPOCH_RAW_CONTRIBUTION_SCALED: LazyLock<Result<IntGaugeVec>> =
    LazyLock::new(|| {
        try_create_int_gauge_vec(
            "topostake_epoch_raw_contribution_scaled",
            "Scaled raw TopoStake path contribution by evidence epoch and validator",
            &["evidence_epoch", "validator_index"],
        )
    });

pub static TOPOSTAKE_EPOCH_SATURATED_CONTRIBUTION_SCALED: LazyLock<Result<IntGaugeVec>> =
    LazyLock::new(|| {
        try_create_int_gauge_vec(
            "topostake_epoch_saturated_contribution_scaled",
            "Scaled saturated TopoStake contribution by evidence epoch and validator",
            &["evidence_epoch", "validator_index"],
        )
    });

pub static TOPOSTAKE_EPOCH_SCORE_TOTAL_SCALED: LazyLock<Result<IntGaugeVec>> =
    LazyLock::new(|| {
        try_create_int_gauge_vec(
            "topostake_epoch_score_total_scaled",
            "Total scaled TopoStake propagation score by evidence epoch",
            &["evidence_epoch"],
        )
    });

pub static TOPOSTAKE_EPOCH_SCORE_SHARE_SCALED: LazyLock<Result<IntGaugeVec>> =
    LazyLock::new(|| {
        try_create_int_gauge_vec(
            "topostake_epoch_score_share_scaled",
            "Scaled share of total TopoStake propagation score by evidence epoch and validator",
            &["evidence_epoch", "validator_index"],
        )
    });

#[allow(dead_code)]
pub static TOPOSTAKE_PROPOSER_WEIGHT_SCALED: LazyLock<Result<GaugeVec>> = LazyLock::new(|| {
    try_create_float_gauge_vec(
        "topostake_proposer_weight_scaled",
        "Scaled TopoStake proposer weight for the proposer epoch affected by evidence",
        &["proposer_epoch", "validator_index"],
    )
});

pub static TOPOSTAKE_CREDIT_EPOCH_RECORDS: LazyLock<Result<IntGaugeVec>> = LazyLock::new(|| {
    try_create_int_gauge_vec(
        "topostake_credit_epoch_records",
        "Number of TopoStake devnet credit ledger records by evidence epoch and settlement status",
        &["epoch", "status"],
    )
});

pub static TOPOSTAKE_CREDIT_EPOCH_TOTAL_SCALED: LazyLock<Result<IntGaugeVec>> =
    LazyLock::new(|| {
        try_create_int_gauge_vec(
            "topostake_credit_epoch_total_scaled",
            "Scaled TopoStake devnet credit ledger totals by evidence epoch and role",
            &["epoch", "role"],
        )
    });

pub static TOPOSTAKE_CREDIT_VALIDATOR_TOTAL_SCALED: LazyLock<Result<IntGaugeVec>> =
    LazyLock::new(|| {
        try_create_int_gauge_vec(
            "topostake_credit_validator_total_scaled",
            "Scaled TopoStake devnet credit ledger totals by evidence epoch, role, and validator",
            &["epoch", "role", "validator_index"],
        )
    });

pub static TOPOSTAKE_CREDIT_EPOCH_CONSERVATION_VIOLATION: LazyLock<Result<IntGaugeVec>> =
    LazyLock::new(|| {
        try_create_int_gauge_vec(
            "topostake_credit_epoch_conservation_violation",
            "Whether TopoStake devnet credit ledger accounting violates fee-budget conservation",
            &["epoch"],
        )
    });

pub static TOPOSTAKE_FEE_SETTLEMENT_RECORDS_TOTAL: LazyLock<Result<IntGaugeVec>> = LazyLock::new(
    || {
        try_create_int_gauge_vec(
            "topostake_fee_settlement_records_total",
            "Number of TopoStake fee settlement records by evidence epoch, settlement state, and role",
            &["epoch", "state", "role"],
        )
    },
);

pub static TOPOSTAKE_FEE_SETTLEMENT_AMOUNT_WEI: LazyLock<Result<IntGaugeVec>> =
    LazyLock::new(|| {
        try_create_int_gauge_vec(
            "topostake_fee_settlement_amount_wei",
            "TopoStake fee settlement amount by evidence epoch and role",
            &["epoch", "role"],
        )
    });

pub static TOPOSTAKE_FEE_VALIDATOR_AMOUNT_WEI: LazyLock<Result<IntGaugeVec>> =
    LazyLock::new(|| {
        try_create_int_gauge_vec(
            "topostake_fee_validator_amount_wei",
            "TopoStake fee settlement amount by evidence epoch, validator, and role",
            &["epoch", "validator_index", "role"],
        )
    });

pub static TOPOSTAKE_FEE_BURNED_AMOUNT_WEI: LazyLock<Result<IntGaugeVec>> = LazyLock::new(|| {
    try_create_int_gauge_vec(
        "topostake_fee_burned_amount_wei",
        "TopoStake burned fee settlement amount by evidence epoch",
        &["epoch"],
    )
});

pub static TOPOSTAKE_FEE_CONSERVATION_VIOLATION: LazyLock<Result<IntGaugeVec>> =
    LazyLock::new(|| {
        try_create_int_gauge_vec(
            "topostake_fee_conservation_violation",
            "Whether TopoStake fee settlement accounting violates conservation",
            &["epoch"],
        )
    });

/*
 * Participation Metrics (progressive balances)
 */
pub static PARTICIPATION_PREV_EPOCH_TARGET_ATTESTING_GWEI_PROGRESSIVE_TOTAL: LazyLock<
    Result<IntGauge>,
> = LazyLock::new(|| {
    try_create_int_gauge(
        "beacon_participation_prev_epoch_target_attesting_gwei_progressive_total",
        "Progressive total effective balance (gwei) of validators who attested to the target in the previous epoch",
    )
});
pub static PARTICIPATION_CURR_EPOCH_TARGET_ATTESTING_GWEI_PROGRESSIVE_TOTAL: LazyLock<
    Result<IntGauge>,
> = LazyLock::new(|| {
    try_create_int_gauge(
        "beacon_participation_curr_epoch_target_attesting_gwei_progressive_total",
        "Progressive total effective balance (gwei) of validators who attested to the target in the current epoch",
    )
});
