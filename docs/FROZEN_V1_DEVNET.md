# Frozen-v1 Ethereum devnet semantics

This document maps the frozen TDSC mechanism to the modified Geth and
Lighthouse clients. Shared defaults live in
`experiments/configs/protocol_frozen_v1.yaml`.

## Evidence and cost fields

Geth commits two distinct monetary values for every included transaction:

- `priority_fee_wei = gas_used * effective_tip`, which is the distributable
  proposer/relay reward budget;
- `irrecoverable_cost_wei = gas_used * base_fee`, which backs long-term score.

Lighthouse carries both values in the block-inline evidence record. Relay
settlement uses only `priority_fee_wei`; score contribution is multiplied by
`q(tx) = min(1, irrecoverable_cost_wei / score_cost_reference_wei)`.

## Score and proposer weight

- `D` is fixed and the path budget uses the frozen exponential factor
  `lambda=(2D+1)/(3D+1)`.
- Relay positions use the geometric factor `r=D/(2D+1)`.
- Score mass is damped by `kappa + sum(active_validator_scores)`.
- The proposer bonus is `b_max*x/(zeta+x)` without the legacy positive-part
  threshold.
- Proposer selection computes the score denominator over the target epoch's
  active validator indices.

## Activation

Score settlement still requires a finalized canonical epoch. Proposer epoch
`e` considers only settled score roots at or before
`e - score_activation_delay_epochs`; if that exact root is unavailable, the
latest older eligible settled root is reused. This models activation stalls
without changing an already computed epoch's proposer duties. The first lookup
for proposer epoch `e` caches its activated score map, so later settlement or
reorganization observations cannot change that epoch's weights.

## Evidence bounds

Path length is checked before signature verification. The aggregate verifier
also rejects evidence whose total path work exceeds `evidence_work_limit`.
Stale records whose tagged epoch differs from the containing block epoch are
recorded as invalid evidence and earn neither score nor relay credit.

## Remaining work

The frozen-v1 challenge payload, bond, deduplication key, and
`challenge_work_limit` processing path are not implemented by this migration
commit. The parameter is committed now so the subsequent challenge state
machine does not introduce another incompatible configuration format.
