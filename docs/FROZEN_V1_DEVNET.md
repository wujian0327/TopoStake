# Frozen-v1 Ethereum devnet semantics

This document maps the frozen TDSC mechanism to the modified Geth and
Lighthouse clients. Shared defaults live in
`experiments/configs/protocol_frozen_v1.yaml`.

## Rebuild the client images

Build Geth from its checkout, then package the resulting binary from the
repository root:

```bash
cd ethereum-topostake/go-ethereum-topostake
make geth

cd ../..
GETH_BINARY="$PWD/ethereum-topostake/go-ethereum-topostake/build/bin/geth" \
  ./scripts/geth_image.sh package-local
./scripts/geth_image.sh verify
```

The Lighthouse devnet uses the minimal preset, so its release binary must be
built with `spec-minimal` before packaging:

```bash
cd ethereum-topostake/lighthouse
cargo build --release -p lighthouse --features spec-minimal

cd ../..
LIGHTHOUSE_BINARY="$PWD/ethereum-topostake/lighthouse/target/release/lighthouse" \
  ./scripts/lighthouse_image.sh package-local
./scripts/lighthouse_image.sh verify
```

Rebuild both images after any consensus/evidence schema change. The smoke
report records both image IDs, creation times, and revision labels.

## Evidence and cost fields

Geth commits two distinct monetary values for every included transaction:

- `priority_fee_wei = gas_used * effective_tip`, which is the distributable
  proposer/relay reward budget;
- `irrecoverable_cost_wei = gas_used * base_fee`, which backs long-term score.

Lighthouse carries both values in the block-inline evidence record. Relay
settlement uses only `priority_fee_wei`; score contribution is multiplied by
`q(tx) = min(1, irrecoverable_cost_wei / score_cost_reference_wei)`.

For the devnet, Geth derives the relay epoch from the canonical execution
head's timestamp relative to genesis using the configured seconds per slot and
slots per epoch. Only newly created certificates use the updated epoch;
already-signed evidence is never silently rebound across an epoch boundary.

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

## Automated acceptance

`experiments/frozen_devnet_acceptance.py` validates the shared fixed-point
profile and golden vectors without a running network. Given a devnet
`summary.json`, it also checks finality progress, evidence epoch freshness,
path and block work limits, positive irrecoverable cost carriage, score
activation delay, within-epoch proposer-weight stability, and the proposer
weight cap.

`experiments/run_frozen_devnet_smoke.py` runs baseline, path-observation, and
TopoStake enclaves sequentially and applies those checks to every artifact.
The runner is a smoke gate; its small sample is not paper evidence.
Each summary also records the source commit, Docker image IDs, creation times,
and image revision labels so results cannot silently mix current source with
stale client images.

## Remaining work

The frozen-v1 challenge payload, bond, deduplication key, and
`challenge_work_limit` processing path are not implemented by this migration
commit. The parameter is committed now so the subsequent challenge state
machine does not introduce another incompatible configuration format.
