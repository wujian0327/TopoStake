use clap::Parser;
use serde::Serialize;
use std::fs;
use std::path::{Path, PathBuf};
use topostake::security_eval::{evaluate_padding_grid, PaddingCaseResult};

#[derive(Debug, Parser)]
#[command(about = "Exhaustively check frozen-v1 fixed-path padding non-amplification")]
struct Args {
    #[arg(long, default_value = "2,4,8")]
    depths: String,
    #[arg(long, default_value_t = 16)]
    max_path_hops: usize,
    #[arg(long, default_value_t = 1e-12)]
    tolerance: f64,
    #[arg(
        long,
        default_value = "results/processed/frozen_v1_padding_fixed_path.csv"
    )]
    csv: PathBuf,
    #[arg(
        long,
        default_value = "results/processed/frozen_v1_padding_fixed_path_acceptance.json"
    )]
    report: PathBuf,
}

#[derive(Serialize)]
struct Report {
    protocol_version: &'static str,
    depths: Vec<usize>,
    max_path_hops: usize,
    tolerance: f64,
    cases: usize,
    coalition_assignments: u64,
    violations: usize,
    maximum_ratio: f64,
    passed: bool,
    csv: String,
}

fn ensure_parent(path: &Path) {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).expect("create fixed-path output directory");
    }
}

fn parse_depths(raw: &str) -> Vec<usize> {
    let depths: Vec<usize> = raw
        .split(',')
        .map(|value| value.trim().parse::<usize>().expect("numeric --depths"))
        .collect();
    assert!(!depths.is_empty());
    assert!(depths.iter().all(|depth| *depth > 0));
    depths
}

fn write_csv(path: &Path, rows: &[PaddingCaseResult]) {
    ensure_parent(path);
    let mut output = String::from(
        "depth,original_path_length,relay_position,inserted_identities,coalition_assignments,worst_original_positions,base_credit,padded_credit,max_ratio,passed\n",
    );
    for row in rows {
        output.push_str(&format!(
            "{},{},{},{},{},{},{:.15},{:.15},{:.15},{}\n",
            row.depth,
            row.original_path_length,
            row.relay_position,
            row.inserted_identities,
            row.coalition_assignments,
            row.worst_original_positions,
            row.base_credit,
            row.padded_credit,
            row.max_ratio,
            row.passed,
        ));
    }
    fs::write(path, output).expect("write fixed-path CSV");
}

fn main() {
    let args = Args::parse();
    assert!(args.max_path_hops >= 3);
    assert!(args.max_path_hops < 63);
    assert!(args.tolerance >= 0.0 && args.tolerance.is_finite());
    let depths = parse_depths(&args.depths);
    let rows = evaluate_padding_grid(&depths, args.max_path_hops, args.tolerance);
    write_csv(&args.csv, &rows);

    let violations = rows.iter().filter(|row| !row.passed).count();
    let report = Report {
        protocol_version: "frozen-v1",
        depths,
        max_path_hops: args.max_path_hops,
        tolerance: args.tolerance,
        cases: rows.len(),
        coalition_assignments: rows.iter().map(|row| row.coalition_assignments).sum(),
        violations,
        maximum_ratio: rows
            .iter()
            .map(|row| row.max_ratio)
            .fold(0.0_f64, f64::max),
        passed: violations == 0,
        csv: args.csv.display().to_string(),
    };
    ensure_parent(&args.report);
    fs::write(
        &args.report,
        serde_json::to_string_pretty(&report).expect("serialize fixed-path report") + "\n",
    )
    .expect("write fixed-path report");
    println!(
        "fixed-path padding: {} ({} cases, maximum ratio {:.12})",
        if report.passed { "PASS" } else { "FAIL" },
        report.cases,
        report.maximum_ratio
    );
    if !report.passed {
        std::process::exit(1);
    }
}
