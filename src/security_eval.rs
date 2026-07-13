//! Deterministic evaluators for manuscript security claims.
//!
//! These helpers do not change protocol behavior. They replay the frozen
//! reward formulas on controlled inputs so an experiment can hold the path and
//! coalition positions fixed while varying only consecutive identity padding.

use crate::consensus::topostake::TopoStakeConsensus;
use serde::Serialize;

#[derive(Debug, Clone, Serialize)]
pub struct PaddingCaseResult {
    pub depth: usize,
    pub original_path_length: usize,
    pub relay_position: usize,
    pub inserted_identities: usize,
    pub coalition_assignments: u64,
    pub worst_original_positions: String,
    pub base_credit: f64,
    pub padded_credit: f64,
    pub max_ratio: f64,
    pub passed: bool,
}

fn credit(depth: usize, path_length: usize, positions: &[usize]) -> f64 {
    positions
        .iter()
        .map(|position| TopoStakeConsensus::gamma_for_depth(depth, *position, path_length))
        .sum()
}

fn positions_label(positions: &[usize]) -> String {
    positions
        .iter()
        .map(|position| position.to_string())
        .collect::<Vec<_>>()
        .join(";")
}

pub fn evaluate_padding_case(
    depth: usize,
    original_path_length: usize,
    relay_position: usize,
    inserted_identities: usize,
    tolerance: f64,
) -> PaddingCaseResult {
    assert!(depth > 0);
    assert!(original_path_length >= 2);
    assert!((1..original_path_length).contains(&relay_position));
    assert!(inserted_identities > 0);

    let other_positions: Vec<usize> = (1..original_path_length)
        .filter(|position| *position != relay_position)
        .collect();
    assert!(other_positions.len() < 63, "path too long for exhaustive masks");
    let assignments = 1u64 << other_positions.len();
    let padded_path_length = original_path_length + inserted_identities;
    let mut maximum = -1.0;
    let mut worst_base = 0.0;
    let mut worst_padded = 0.0;
    let mut worst_positions = Vec::new();

    for mask in 0..assignments {
        let mut original_positions = vec![relay_position];
        for (index, position) in other_positions.iter().enumerate() {
            if mask & (1u64 << index) != 0 {
                original_positions.push(*position);
            }
        }
        original_positions.sort_unstable();

        let mut padded_positions: Vec<usize> =
            (relay_position..=relay_position + inserted_identities).collect();
        for position in &original_positions {
            if *position == relay_position {
                continue;
            }
            padded_positions.push(if *position < relay_position {
                *position
            } else {
                *position + inserted_identities
            });
        }
        padded_positions.sort_unstable();

        let base = credit(depth, original_path_length, &original_positions);
        let padded = credit(depth, padded_path_length, &padded_positions);
        let ratio = padded / base;
        if ratio > maximum {
            maximum = ratio;
            worst_base = base;
            worst_padded = padded;
            worst_positions = original_positions;
        }
    }

    PaddingCaseResult {
        depth,
        original_path_length,
        relay_position,
        inserted_identities,
        coalition_assignments: assignments,
        worst_original_positions: positions_label(&worst_positions),
        base_credit: worst_base,
        padded_credit: worst_padded,
        max_ratio: maximum,
        passed: maximum <= 1.0 + tolerance,
    }
}

pub fn evaluate_padding_grid(
    depths: &[usize],
    max_path_hops: usize,
    tolerance: f64,
) -> Vec<PaddingCaseResult> {
    assert!(max_path_hops >= 3);
    let mut rows = Vec::new();
    for depth in depths {
        for original_path_length in 2..max_path_hops {
            for relay_position in 1..original_path_length {
                for inserted_identities in 1..=max_path_hops - original_path_length {
                    rows.push(evaluate_padding_case(
                        *depth,
                        original_path_length,
                        relay_position,
                        inserted_identities,
                        tolerance,
                    ));
                }
            }
        }
    }
    rows
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn frozen_depths_are_non_amplifying_for_all_coalition_masks() {
        let rows = evaluate_padding_grid(&[2, 4, 8], 16, 1e-12);
        assert!(!rows.is_empty());
        assert!(rows.iter().all(|row| row.passed));
        assert!(rows.iter().all(|row| row.max_ratio <= 1.0 + 1e-12));
    }

    #[test]
    fn padding_case_includes_the_replaced_relay_and_all_inserted_identities() {
        let row = evaluate_padding_case(4, 5, 2, 3, 1e-12);
        assert_eq!(row.coalition_assignments, 8);
        assert!(row.base_credit > 0.0);
        assert!(row.padded_credit > 0.0);
        assert!(row.passed);
    }
}
