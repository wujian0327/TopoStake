use clap::Parser;
use serde::Serialize;
use std::fs;
use std::hint::black_box;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::Instant;
use topostake::blockchain::path::{AggregatedSignedPaths, TransactionPaths};
use topostake::blockchain::transaction::Transaction;
use topostake::wallet::Wallet;

const PROTOCOL_VERSION: &str = "frozen-v1";
const DEFAULT_EPOCH: u64 = 7;

#[derive(Debug, Parser)]
#[command(about = "Benchmark frozen-v1 path evidence cost and rejection behavior")]
struct Args {
    #[arg(long, default_value = "1,2,4,8,16")]
    hops: String,
    #[arg(long, default_value_t = 20)]
    warmup: usize,
    #[arg(long, default_value_t = 100)]
    repetitions: usize,
    #[arg(long, default_value_t = 5)]
    block_repetitions: usize,
    #[arg(long, default_value_t = 16)]
    max_path_hops: usize,
    #[arg(long, default_value_t = 4096)]
    evidence_work_limit: usize,
    #[arg(
        long,
        default_value = "results/processed/frozen_v1_evidence_benchmark_samples.csv"
    )]
    samples: PathBuf,
    #[arg(
        long,
        default_value = "results/processed/frozen_v1_evidence_benchmark_summary.csv"
    )]
    summary: PathBuf,
    #[arg(
        long,
        default_value = "results/processed/frozen_v1_evidence_benchmark_acceptance.json"
    )]
    report: PathBuf,
}

#[derive(Debug, Clone)]
struct Fixture {
    transaction: Transaction,
    paths: TransactionPaths,
    aggregate: AggregatedSignedPaths,
    invalid_aggregate: AggregatedSignedPaths,
    wallets: Vec<Wallet>,
    miner: String,
    epoch: u64,
}

#[derive(Debug, Clone, Serialize)]
struct Sample {
    protocol_version: &'static str,
    operation: String,
    hops: usize,
    iteration: usize,
    nanoseconds: u128,
    check_passed: bool,
}

#[derive(Debug, Clone, Serialize)]
struct SummaryRow {
    protocol_version: &'static str,
    operation: String,
    hops: usize,
    samples: usize,
    mean_us: f64,
    median_us: f64,
    p95_us: f64,
    stddev_us: f64,
    evidence_bytes: u64,
    json_bytes: u64,
    compressed_bytes: u64,
    signer_identities: usize,
    signature_bytes: usize,
    records_per_block: usize,
    work_units: usize,
    all_checks_passed: bool,
}

#[derive(Debug, Serialize)]
struct Report {
    protocol_version: &'static str,
    os: &'static str,
    architecture: &'static str,
    parallelism: usize,
    rustc_version: String,
    git_commit: String,
    warmup: usize,
    repetitions: usize,
    block_repetitions: usize,
    hops: Vec<usize>,
    max_path_hops: usize,
    evidence_work_limit: usize,
    records_at_work_limit: usize,
    at_limit_admitted: bool,
    over_limit_rejected: bool,
    malformed_encoding_rejected: bool,
    invalid_signature_rejected: bool,
    wrong_epoch_rejected: bool,
    repeated_identity_rejected: bool,
    failed_sample_checks: usize,
    passed: bool,
    samples_csv: String,
    summary_csv: String,
}

fn command_output(program: &str, args: &[&str]) -> String {
    Command::new(program)
        .args(args)
        .output()
        .ok()
        .filter(|output| output.status.success())
        .map(|output| String::from_utf8_lossy(&output.stdout).trim().to_string())
        .unwrap_or_else(|| "unknown".to_string())
}

fn ensure_parent(path: &Path) {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).expect("create evidence benchmark output directory");
    }
}

fn parse_hops(raw: &str, max_path_hops: usize) -> Vec<usize> {
    let mut values: Vec<usize> = raw
        .split(',')
        .map(|value| value.trim().parse::<usize>().expect("numeric --hops"))
        .collect();
    values.sort_unstable();
    values.dedup();
    assert!(!values.is_empty(), "--hops must not be empty");
    assert!(
        values.iter().all(|value| *value > 0 && *value <= max_path_hops),
        "all hop counts must be in 1..=max-path-hops"
    );
    values
}

fn build_paths(transaction: Transaction, wallets: &[Wallet], epoch: u64) -> TransactionPaths {
    let mut paths = TransactionPaths::new_with_epoch(transaction, epoch);
    for pair in wallets.windows(2) {
        assert!(paths.append_completed_hop(
            pair[1].address.clone(),
            pair[0].clone(),
            pair[1].clone(),
        ));
    }
    paths
}

fn fixture(hops: usize, seed: u64) -> Fixture {
    let wallets: Vec<Wallet> = (0..=hops)
        .map(|index| Wallet::new_deterministic(seed, index as u32))
        .collect();
    let transaction = Transaction::with_costs(
        wallets[hops].address.clone(),
        hops as i64,
        1.0,
        1.0,
        wallets[0].clone(),
    );
    let paths = build_paths(transaction.clone(), &wallets, DEFAULT_EPOCH);
    let aggregate = paths.to_aggregated_signed_paths();

    let other_transaction = Transaction::with_costs(
        wallets[hops].address.clone(),
        10_000 + hops as i64,
        1.0,
        1.0,
        wallets[0].clone(),
    );
    let other_paths = build_paths(other_transaction, &wallets, DEFAULT_EPOCH);
    let mut invalid_aggregate = aggregate.clone();
    invalid_aggregate.signature = other_paths.to_aggregated_signed_paths().signature;

    assert!(paths.verify_completed_hops());
    assert!(aggregate.verify_at_epoch_uncached(
        transaction.clone(),
        wallets[hops].address.clone(),
        DEFAULT_EPOCH,
    ));
    assert!(!invalid_aggregate.verify_at_epoch_uncached(
        transaction.clone(),
        wallets[hops].address.clone(),
        DEFAULT_EPOCH,
    ));

    Fixture {
        transaction,
        paths,
        aggregate,
        invalid_aggregate,
        wallets: wallets.clone(),
        miner: wallets[hops].address.clone(),
        epoch: DEFAULT_EPOCH,
    }
}

fn aggregate_signatures(paths: &TransactionPaths) -> String {
    let mut signatures = Vec::with_capacity(paths.paths.len() * 2);
    for hop in &paths.paths {
        signatures.push(
            Wallet::bls_signature_from_string(hop.sender_signature.clone())
                .expect("valid sender signature"),
        );
        signatures.push(
            Wallet::bls_signature_from_string(
                hop.receiver_signature
                    .clone()
                    .expect("completed receiver signature"),
            )
            .expect("valid receiver signature"),
        );
    }
    Wallet::bls_aggregated_sign(signatures)
}

fn measure<F>(
    operation: &str,
    hops: usize,
    warmup: usize,
    repetitions: usize,
    mut operation_fn: F,
) -> Vec<Sample>
where
    F: FnMut(usize) -> bool,
{
    for iteration in 0..warmup {
        black_box(operation_fn(iteration));
    }
    (0..repetitions)
        .map(|iteration| {
            let start = Instant::now();
            let check_passed = black_box(operation_fn(iteration + warmup));
            Sample {
                protocol_version: PROTOCOL_VERSION,
                operation: operation.to_string(),
                hops,
                iteration,
                nanoseconds: start.elapsed().as_nanos(),
                check_passed,
            }
        })
        .collect()
}

fn percentile(sorted: &[f64], quantile: f64) -> f64 {
    if sorted.is_empty() {
        return 0.0;
    }
    let position = (sorted.len() - 1) as f64 * quantile;
    let lower = position.floor() as usize;
    let upper = position.ceil() as usize;
    if lower == upper {
        sorted[lower]
    } else {
        let fraction = position - lower as f64;
        sorted[lower] * (1.0 - fraction) + sorted[upper] * fraction
    }
}

fn summarize(
    operation: &str,
    fixture: &Fixture,
    samples: &[Sample],
    records_per_block: usize,
    work_units: usize,
) -> SummaryRow {
    let mut micros: Vec<f64> = samples
        .iter()
        .map(|sample| sample.nanoseconds as f64 / 1_000.0)
        .collect();
    micros.sort_by(f64::total_cmp);
    let mean = micros.iter().sum::<f64>() / micros.len().max(1) as f64;
    let variance = if micros.len() > 1 {
        micros
            .iter()
            .map(|value| (value - mean).powi(2))
            .sum::<f64>()
            / (micros.len() - 1) as f64
    } else {
        0.0
    };
    SummaryRow {
        protocol_version: PROTOCOL_VERSION,
        operation: operation.to_string(),
        hops: fixture.paths.paths.len(),
        samples: samples.len(),
        mean_us: mean,
        median_us: percentile(&micros, 0.50),
        p95_us: percentile(&micros, 0.95),
        stddev_us: variance.sqrt(),
        evidence_bytes: fixture.aggregate.bytes(),
        json_bytes: fixture.aggregate.json_bytes(),
        compressed_bytes: fixture.aggregate.compress().len() as u64,
        signer_identities: fixture.aggregate.paths.len() + 1,
        signature_bytes: fixture.aggregate.signature.trim_start_matches("0x").len() / 2,
        records_per_block,
        work_units,
        all_checks_passed: samples.iter().all(|sample| sample.check_passed),
    }
}

fn work_budget_accepts(
    records: &[&AggregatedSignedPaths],
    miner: &str,
    max_path_hops: usize,
    work_limit: usize,
) -> bool {
    let mut work = 0usize;
    for record in records {
        let hops = record.full_path(miner.to_string()).len().saturating_sub(1);
        if hops > max_path_hops {
            return false;
        }
        let Some(next) = work.checked_add(hops) else {
            return false;
        };
        if next > work_limit {
            return false;
        }
        work = next;
    }
    true
}

fn write_samples(path: &Path, samples: &[Sample]) {
    ensure_parent(path);
    let mut output = String::from(
        "protocol_version,operation,hops,iteration,nanoseconds,check_passed\n",
    );
    for sample in samples {
        output.push_str(&format!(
            "{},{},{},{},{},{}\n",
            sample.protocol_version,
            sample.operation,
            sample.hops,
            sample.iteration,
            sample.nanoseconds,
            sample.check_passed,
        ));
    }
    fs::write(path, output).expect("write evidence benchmark samples");
}

fn write_summary(path: &Path, rows: &[SummaryRow]) {
    ensure_parent(path);
    let mut output = String::from(
        "protocol_version,operation,hops,samples,mean_us,median_us,p95_us,stddev_us,evidence_bytes,json_bytes,compressed_bytes,signer_identities,signature_bytes,records_per_block,work_units,all_checks_passed\n",
    );
    for row in rows {
        output.push_str(&format!(
            "{},{},{},{},{:.6},{:.6},{:.6},{:.6},{},{},{},{},{},{},{},{}\n",
            row.protocol_version,
            row.operation,
            row.hops,
            row.samples,
            row.mean_us,
            row.median_us,
            row.p95_us,
            row.stddev_us,
            row.evidence_bytes,
            row.json_bytes,
            row.compressed_bytes,
            row.signer_identities,
            row.signature_bytes,
            row.records_per_block,
            row.work_units,
            row.all_checks_passed,
        ));
    }
    fs::write(path, output).expect("write evidence benchmark summary");
}

fn main() {
    let args = Args::parse();
    assert!(args.repetitions > 0);
    assert!(args.block_repetitions > 0);
    assert!(args.max_path_hops >= 2);
    assert!(args.evidence_work_limit >= args.max_path_hops);
    let hops = parse_hops(&args.hops, args.max_path_hops);
    assert!(hops.contains(&args.max_path_hops));

    let fixtures: Vec<Fixture> = hops
        .iter()
        .map(|hop_count| fixture(*hop_count, 0x5450_5300 + *hop_count as u64))
        .collect();
    let mut samples = Vec::new();
    let mut summaries = Vec::new();

    for fixture in &fixtures {
        let hop_count = fixture.paths.paths.len();
        let construction_transactions: Vec<Transaction> =
            (0..args.warmup + args.repetitions)
                .map(|iteration| {
                    Transaction::with_costs(
                        fixture.miner.clone(),
                        100_000 + (hop_count * 1_000 + iteration) as i64,
                        1.0,
                        1.0,
                        fixture.wallets[0].clone(),
                    )
                })
                .collect();
        let build = measure(
            "construct_path",
            hop_count,
            args.warmup,
            args.repetitions,
            |iteration| {
                build_paths(
                    construction_transactions[iteration].clone(),
                    &fixture.wallets,
                    fixture.epoch,
                )
                .paths
                .len()
                    == hop_count
            },
        );
        summaries.push(summarize("construct_path", fixture, &build, 1, hop_count));
        samples.extend(build);

        let individual = measure(
            "verify_individual",
            hop_count,
            args.warmup,
            args.repetitions,
            |_| fixture.paths.verify_completed_hops(),
        );
        summaries.push(summarize(
            "verify_individual",
            fixture,
            &individual,
            1,
            hop_count,
        ));
        samples.extend(individual);

        let aggregate = measure("aggregate_only", hop_count, args.warmup, args.repetitions, |_| {
            !aggregate_signatures(&fixture.paths).is_empty()
        });
        summaries.push(summarize("aggregate_only", fixture, &aggregate, 1, hop_count));
        samples.extend(aggregate);

        let aggregate_verify = measure(
            "verify_aggregate_cold",
            hop_count,
            args.warmup,
            args.repetitions,
            |_| {
                fixture.aggregate.verify_at_epoch_uncached(
                    fixture.transaction.clone(),
                    fixture.miner.clone(),
                    fixture.epoch,
                )
            },
        );
        summaries.push(summarize(
            "verify_aggregate_cold",
            fixture,
            &aggregate_verify,
            1,
            hop_count,
        ));
        samples.extend(aggregate_verify);

        let encode = measure("encode_json", hop_count, args.warmup, args.repetitions, |_| {
            !black_box(fixture.aggregate.to_json()).is_empty()
        });
        summaries.push(summarize("encode_json", fixture, &encode, 1, hop_count));
        samples.extend(encode);
    }

    let maximum = fixtures
        .iter()
        .find(|fixture| fixture.paths.paths.len() == args.max_path_hops)
        .expect("fixture for max-path-hops");
    let records_at_work_limit = args.evidence_work_limit / args.max_path_hops;
    let at_limit_records = vec![&maximum.aggregate; records_at_work_limit];
    let mut over_limit_records = at_limit_records.clone();
    over_limit_records.push(&maximum.aggregate);
    let at_limit_admitted = work_budget_accepts(
        &at_limit_records,
        &maximum.miner,
        args.max_path_hops,
        args.evidence_work_limit,
    );
    let over_limit_rejected = !work_budget_accepts(
        &over_limit_records,
        &maximum.miner,
        args.max_path_hops,
        args.evidence_work_limit,
    );

    let block_verify = measure(
        "verify_block_at_work_limit",
        args.max_path_hops,
        1,
        args.block_repetitions,
        |_| {
            at_limit_records.iter().all(|record| {
                record.verify_at_epoch_uncached(
                    maximum.transaction.clone(),
                    maximum.miner.clone(),
                    maximum.epoch,
                )
            })
        },
    );
    summaries.push(summarize(
        "verify_block_at_work_limit",
        maximum,
        &block_verify,
        records_at_work_limit,
        records_at_work_limit * args.max_path_hops,
    ));
    samples.extend(block_verify);

    let admission_reject = measure(
        "reject_over_work_limit",
        args.max_path_hops,
        args.warmup,
        args.repetitions,
        |_| {
            !work_budget_accepts(
                &over_limit_records,
                &maximum.miner,
                args.max_path_hops,
                args.evidence_work_limit,
            )
        },
    );
    summaries.push(summarize(
        "reject_over_work_limit",
        maximum,
        &admission_reject,
        over_limit_records.len(),
        over_limit_records.len() * args.max_path_hops,
    ));
    samples.extend(admission_reject);

    let mut malformed = maximum.aggregate.clone();
    malformed.signature = "0x00".to_string();
    let malformed_encoding_rejected = !malformed.verify_at_epoch_uncached(
        maximum.transaction.clone(),
        maximum.miner.clone(),
        maximum.epoch,
    );
    let malformed_samples = measure(
        "reject_malformed_encoding",
        args.max_path_hops,
        args.warmup,
        args.repetitions,
        |_| {
            !malformed.verify_at_epoch_uncached(
                maximum.transaction.clone(),
                maximum.miner.clone(),
                maximum.epoch,
            )
        },
    );
    summaries.push(summarize(
        "reject_malformed_encoding",
        maximum,
        &malformed_samples,
        1,
        args.max_path_hops,
    ));
    samples.extend(malformed_samples);

    let invalid_signature_rejected = !maximum.invalid_aggregate.verify_at_epoch_uncached(
        maximum.transaction.clone(),
        maximum.miner.clone(),
        maximum.epoch,
    );
    let invalid_samples = measure(
        "reject_invalid_signature",
        args.max_path_hops,
        args.warmup,
        args.repetitions,
        |_| {
            !maximum.invalid_aggregate.verify_at_epoch_uncached(
                maximum.transaction.clone(),
                maximum.miner.clone(),
                maximum.epoch,
            )
        },
    );
    summaries.push(summarize(
        "reject_invalid_signature",
        maximum,
        &invalid_samples,
        1,
        args.max_path_hops,
    ));
    samples.extend(invalid_samples);

    let wrong_epoch_rejected = !maximum.aggregate.verify_at_epoch_uncached(
        maximum.transaction.clone(),
        maximum.miner.clone(),
        maximum.epoch + 1,
    );
    let wrong_epoch_samples = measure(
        "reject_wrong_epoch",
        args.max_path_hops,
        args.warmup,
        args.repetitions,
        |_| {
            !maximum.aggregate.verify_at_epoch_uncached(
                maximum.transaction.clone(),
                maximum.miner.clone(),
                maximum.epoch + 1,
            )
        },
    );
    summaries.push(summarize(
        "reject_wrong_epoch",
        maximum,
        &wrong_epoch_samples,
        1,
        args.max_path_hops,
    ));
    samples.extend(wrong_epoch_samples);

    let mut repeated = maximum.aggregate.clone();
    repeated.paths[1] = repeated.paths[0].clone();
    let repeated_identity_rejected = !repeated.verify_at_epoch_uncached(
        maximum.transaction.clone(),
        maximum.miner.clone(),
        maximum.epoch,
    );

    write_samples(&args.samples, &samples);
    write_summary(&args.summary, &summaries);
    let failed_sample_checks = samples.iter().filter(|sample| !sample.check_passed).count();
    let passed = at_limit_admitted
        && over_limit_rejected
        && malformed_encoding_rejected
        && invalid_signature_rejected
        && wrong_epoch_rejected
        && repeated_identity_rejected
        && failed_sample_checks == 0;
    let report = Report {
        protocol_version: PROTOCOL_VERSION,
        os: std::env::consts::OS,
        architecture: std::env::consts::ARCH,
        parallelism: std::thread::available_parallelism()
            .map(|value| value.get())
            .unwrap_or(1),
        rustc_version: command_output("rustc", &["--version", "--verbose"]),
        git_commit: command_output("git", &["rev-parse", "HEAD"]),
        warmup: args.warmup,
        repetitions: args.repetitions,
        block_repetitions: args.block_repetitions,
        hops,
        max_path_hops: args.max_path_hops,
        evidence_work_limit: args.evidence_work_limit,
        records_at_work_limit,
        at_limit_admitted,
        over_limit_rejected,
        malformed_encoding_rejected,
        invalid_signature_rejected,
        wrong_epoch_rejected,
        repeated_identity_rejected,
        failed_sample_checks,
        passed,
        samples_csv: args.samples.display().to_string(),
        summary_csv: args.summary.display().to_string(),
    };
    ensure_parent(&args.report);
    fs::write(
        &args.report,
        serde_json::to_string_pretty(&report).expect("serialize evidence benchmark report") + "\n",
    )
    .expect("write evidence benchmark report");
    println!(
        "frozen-v1 evidence benchmark: {} ({} samples; {} max-hop records at work limit)",
        if passed { "PASS" } else { "FAIL" },
        samples.len(),
        records_at_work_limit,
    );
    println!("summary={}", args.summary.display());
    if !passed {
        std::process::exit(1);
    }
}
