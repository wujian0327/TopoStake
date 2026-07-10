# Lighthouse TopoStake Integration Plan

This document is a feasibility spike for implementing TopoStake in Lighthouse.
It is intentionally scoped to source-code mapping and an incremental plan. It
does not implement TopoStake consensus.

Source snapshot inspected:

- Lighthouse checkout: `ethereum-topostake/lighthouse`
- Upstream repository: `https://github.com/sigp/lighthouse`
- Commit: `120c3c6`

Paths below are relative to the Lighthouse checkout unless noted otherwise.

## Executive Summary

The Prompt 3 prototype can remain outside Ethereum consensus because it carries
TopoStake path evidence as transaction calldata and measures deployment
overhead. A full TopoStake integration is different: proposer selection, beacon
state updates, block validity, and reward accounting are consensus behavior. If
any of those rules change, every consensus client in the devnet must run a
compatible fork, otherwise honest nodes will disagree about duties, reject each
other's blocks, or compute different beacon states.

The minimum realistic path is:

1. Keep path evidence external or as an optional non-consensus sidecar.
2. Add TopoStake Lighthouse instrumentation that is enabled by default in the
   custom image to observe propagation paths and export metrics.
3. Add a fork-gated TopoStake state extension for score snapshots only.
4. Add a fork-gated proposer-selection modification.
5. Only after that, add consensus reward settlement or block-body commitments.

## Located Lighthouse Modules

| Area | File | Functions / types | Why it matters |
|---|---|---|---|
| Proposer selection | `consensus/types/src/state/beacon_state.rs` | `BeaconState::compute_proposer_index`, `compute_proposer_indices`, `get_beacon_proposer_index` | Core beacon proposer index computation. Pre-Fulu computes from active validators, seed, and effective balance; Fulu can use proposer lookahead. |
| Proposer cache / duties | `beacon_node/beacon_chain/src/beacon_proposer_cache.rs` | `compute_proposer_duties_from_head`, `ensure_state_can_determine_proposers_for_epoch` | Beacon node derives per-epoch proposer duties from head state and caches them. |
| Proposer duties HTTP API | `beacon_node/http_api/src/proposer_duties.rs` | `proposer_duties`, `proposer_duties_v2`, `proposer_duties_internal`, `compute_and_cache_proposer_duties` | Validator clients call this API to know which local validator should propose. |
| Validator duties client | `validator_client/validator_services/src/duties_service.rs` | `fetch_and_store_proposer_duties` | Validator client downloads proposer duties for current and next epoch. |
| Block production API | `beacon_node/http_api/src/produce_block.rs` | `produce_block_v2`, `produce_block_v3`, `produce_block_v4` | HTTP handlers used by validator client to request unsigned blocks. |
| Block production core | `beacon_node/beacon_chain/src/beacon_chain.rs` | `produce_block_with_verification`, `produce_block_on_state` | Beacon node loads state, advances it, packs a block, and verifies produced block contents. |
| Validator block signing/publish | `validator_client/validator_services/src/block_service.rs` | `get_validator_block_and_publish_block`, `sign_and_publish_block` | Validator client checks returned block proposer index matches the local duty before signing and publishing. |
| Block publish / propagation | `beacon_node/http_api/src/publish_blocks.rs` | `publish_block` | Published blocks are gossip-verified before propagation. |
| Gossip block verification / metrics | `beacon_node/network/src/network_beacon_processor/gossip_methods.rs` | block gossip handler calling `verify_block_for_gossip`; metrics such as `BEACON_BLOCK_DELAY_GOSSIP` | Best insertion point for non-consensus propagation instrumentation. |
| Block verification/import | `beacon_node/beacon_chain/src/block_verification.rs` | `BlockError::IncorrectBlockProposer`, gossip verification path checking `expected_proposer`, `IntoFullyVerifiedBlock` path | A block with a proposer index that differs from local computation is invalid/faulty. |
| State transition block header check | `consensus/state_processing/src/per_block_processing.rs` | `process_block_header`, `verify_block_signature`, `process_randao` | State transition recomputes proposer index and rejects mismatched headers. |
| Consensus context cache | `consensus/state_processing/src/consensus_context.rs` | `ConsensusContext::get_proposer_index`, `get_proposer_index_from_epoch_state` | Shared cache for proposer index during block processing and signature verification. |
| Epoch transition | `consensus/state_processing/src/per_epoch_processing.rs` | `process_epoch` | Fork-aware entry point into per-epoch processing. |
| Pre-Altair epoch processing | `consensus/state_processing/src/per_epoch_processing/base.rs` | `process_epoch`, `process_rewards_and_penalties` | Shows canonical order: finalization, rewards, registry updates, slashings, resets. |
| Altair+ epoch processing | `consensus/state_processing/src/per_epoch_processing/altair.rs` | `process_epoch`, `process_epoch_single_pass` | Main path for modern devnets; TopoStake score update would need to integrate here or adjacent to it. |
| Reward accounting | `consensus/state_processing/src/per_epoch_processing/base/rewards_and_penalties.rs` and `single_pass.rs` | `process_rewards_and_penalties`, `get_inclusion_delay_delta`, `get_proposer_reward`, `process_single_reward_and_penalty` | Existing beacon rewards mutate validator balances. TopoStake relay settlement would need a new deterministic accounting rule. |

## What Can Stay External

These parts can be implemented without changing Lighthouse consensus:

- Path-evidence byte overhead: use calldata, logs, or external sidecar files and
  scan them with an off-chain verifier.
- BLS path aggregation benchmarks and verification-time measurements.
- Prometheus/Grafana metrics for observed block delay, gossip arrival delay, and
  propagation paths.
- Off-chain relay reward simulation after finality using Beacon API and
  execution RPC data.
- A devnet-only transaction wrapper that embeds `path_length`, relay identities,
  and aggregate-signature placeholders in transaction calldata.

This is the Prompt 3 boundary: useful for deployment overhead and data-path
measurement, but it does not change block validity or proposer selection.

## What Requires Consensus-Client Changes

These items require Lighthouse consensus changes, and eventually equivalent
changes in every other consensus client if the network is heterogeneous:

- Proposer selection from TopoStake weights:
  - `BeaconState::compute_proposer_index` or the Fulu proposer-lookahead
    generation must incorporate `W_i = stake_i * (1 + eta * bonus_i)`.
  - The proposer duty API and validator client will then naturally observe the
    modified proposer schedule, but only if the beacon node computes it.
- Beacon state fields:
  - Score history, normalized propagation scores, frozen stake snapshot,
    proposer-weight snapshot, pending relay settlements, and fork-gated config
    parameters need deterministic SSZ/state representation.
- Block body or sidecar commitment:
  - If path records are consensus data, the beacon block body or a committed
    sidecar must carry `AggregatedSignedPaths` or a root of it.
  - A plain external sidecar can measure overhead but cannot drive consensus
    rewards or proposer weights safely.
- Block verification:
  - Path record decoding and BLS aggregate verification must be deterministic.
  - The protocol must decide whether invalid path evidence invalidates the
    block or is deterministically ignored. The TopoStake paper prefers zero
    reward/score without invalidating the base block, so the consensus rule
    should treat syntactically valid but unverifiable path records as ignored.
    Malformed SSZ, duplicate records, or commitment mismatches still need clear
    validity rules.
- Epoch score update:
  - Finalized eligible path records must update epoch-level propagation scores
    at a deterministic point in `process_epoch`.
- Reward settlement:
  - Beacon rewards currently mutate validator balances. TopoStake relay fees
    are tied to transaction fees, which are execution-layer value. Full economic
    settlement crosses the EL/CL boundary and is the largest design risk.

## Why All Consensus Clients Must Match

Changing proposer selection is not a local optimization. Lighthouse verifies
incoming blocks by recomputing the expected proposer. In
`block_verification.rs`, a mismatched proposer returns
`BlockError::IncorrectBlockProposer`; in `per_block_processing.rs`,
`process_block_header` rejects a header whose proposer index differs from the
locally computed index.

Therefore, if one validator runs TopoStake-weighted selection and another runs
stock stake-weighted selection, they can disagree about who should propose a
slot. The stock node may reject the TopoStake block as invalid, gossip scoring
may punish the peer, and finality can stall or fork. For a devnet experiment,
all Lighthouse beacon nodes and validator clients must use the same custom
image and the same genesis/fork config.

## Minimal Viable Modification Route

### Stage 0: External Prototype

Status: implemented by Prompt 3.

- Keep Ethereum consensus unchanged.
- Carry path evidence in calldata.
- Verify and summarize off chain.
- Use this for paper overhead tables.

### Stage 1: Lighthouse Instrumentation Only

Goal: observe propagation without changing block validity.

- Add read-only TopoStake metrics in the block gossip handler around
  `gossip_methods.rs`.
- Export counters/histograms for observed block delay, peer/client source, and
  optional path-evidence sidecar arrival.
- Enable these observations by default in the custom TopoStake Lighthouse image;
  do not require a feature flag or environment-variable switch.
- Do not alter `BeaconBlock`, proposer selection, state transition, or rewards.

Implemented Prompt 6 files:

- `beacon_node/network/src/network_beacon_processor/gossip_methods.rs`
- `beacon_node/network/src/metrics.rs`

Implemented Prompt 6 metrics:

- `topostake_gossip_block_arrivals_total`
- `topostake_gossip_block_arrival_delay_milliseconds`
- `topostake_gossip_block_verification_delay_milliseconds`
- `topostake_gossip_block_info`

Validation:

- Build custom Lighthouse image.
- Run a custom-image Kurtosis devnet.
- Confirm `topostake_` metrics are exported without setting a TopoStake feature
  flag.
- Confirm the devnet produces blocks and finalizes normally.

Prompt 6 validation on 2026-07-04 passed with `topostake/lighthouse:dev`
(`120c3c6`): `head_slot=135`, `finalized_epoch=2`, and Prometheus series for
all four `topostake_` metrics across the four Lighthouse beacon nodes.

### Stage 2: Non-Consensus Sidecar With Deterministic Verifier

Goal: prototype path evidence close to Lighthouse without making it consensus
critical.

- Add a devnet-only sidecar receiver or HTTP endpoint.
- Decode TopoStake path records and run BLS verification.
- Export score/reward estimates via metrics or files.
- Keep invalid evidence as zero score only.

Validation:

- The beacon chain should still finalize if the sidecar is missing.
- Sidecar output should match the existing Python verifier on the same data.

### Stage 3: Fork-Gated Consensus State Skeleton

Goal: create deterministic state locations before changing selection.

Prompt 9 implements the first conservative slice:

- Add `TopoStakeConfig` behind a devnet-only fork epoch in `ChainSpec`.
- Add YAML parsing through `TOPOSTAKE_CONFIG`, default disabled.
- Add a non-SSZ `TopoStakeStateSkeleton` placeholder for zero-score snapshots.
- Add tests proving default/zero-score proposer duties and roots remain
  unchanged.
- Do not add BeaconState SSZ fields, proposer weighting, path evidence scoring,
  or reward settlement yet.

Future Stage 3 work can replace the non-SSZ skeleton with real fork-gated
BeaconState fields once the proposer-weight boundary is ready.

Validation:

- `cargo test -p types topostake -- --nocapture` passes.
- `cargo check -p types` passes.
- A tiny devnet with the same custom image should initialize, produce blocks,
  and finalize with zero scores.

### Stage 4: Fork-Gated Proposer Selection

Goal: use TopoStake weights for proposer choice.

- Add a fork-aware wrapper around proposer selection:
  - default path calls existing `compute_proposer_index`;
  - TopoStake path computes effective proposer weights from frozen stake and
    previous finalized score.
- Update proposer lookahead/cache code so `compute_proposer_duties_from_head`
  returns TopoStake-compatible duties.
- Ensure validator client does not need a special local algorithm; it should use
  beacon-node duties as today.

Validation:

- Deterministic unit tests: same state, same slot, same seed gives same
  proposer on all nodes.
- Bound tests: `W_i <= (1 + eta * bonus_cap) * stake_share_i`.
- Devnet: all 4 Lighthouse nodes run the same image and finalize.
- Negative test: stock Lighthouse should reject or diverge, proving this is a
  consensus change.

Prompt 10 implementation on 2026-07-04 added the minimal fixture-driven
selection fork in `ethereum-topostake/lighthouse`:

- `TopoStakeConfig.score_fixture` supplies deterministic per-validator scores.
- `BeaconState::get_beacon_proposer_index` and
  `BeaconState::get_beacon_proposer_indices` route through a fork-aware wrapper.
- The TopoStake path uses
  `W_i = effective_balance_i * (1 + eta * min(score_i, bonus_cap))`.
- The proposer sampling denominator is the maximum TopoStake proposer weight
  among active validators, preserving exact PoS equivalence when all scores are
  zero.
- Attestation, justification/finalization, rewards, block bodies, and
  BeaconState SSZ remain unchanged.

Prompt 10 validation passed:

```bash
cd ethereum-topostake/lighthouse
cargo fmt --check
cargo test -p types topostake -- --nocapture
cargo check -p types
cargo build --bin lighthouse --release --locked
```

The rebuilt `topostake/lighthouse:dev` image
`sha256:3c0f4a88d6c4b659276ee3dfb3ed4834feb114c95f2f8dd900de654bf10a2e96`
started a 4-node Kurtosis custom Lighthouse devnet. CL1 reached
`head_slot=144`, `current_justified_epoch=3`, and `finalized_epoch=2`.

Follow-up live fixture validation patched the local ethereum-package genesis
artifact generation path to append `TOPOSTAKE_CONFIG_YAML` into the generated
CL `config.yaml`, then started the historical fixture config
`kurtosis/topostake-devnet-custom-lighthouse-fixture.yaml`.
That YAML has since been deleted because Prompt 1-13 no longer need to be
reproduced.

The fixture boosted validators 0-3 with `ETA_SCALED=9000000000`,
`BONUS_CAP_SCALED=1000000000`, and `SCORE_SCALED=1000000000`. CL1 exposed the
fixture through `/eth/v1/config/spec`, and the downloaded genesis artifact
contained `TOPOSTAKE_CONFIG`.

The fixture devnet finalized at `finalized_epoch=2`. Proposer duties showed the
expected live frequency shift:

```text
epoch=0 duties=32 boosted_0_3=6
epoch=1 duties=32 boosted_0_3=10
epoch=4 duties=32 boosted_0_3=8
epoch=5 duties=32 boosted_0_3=12
current_window_boosted_share=0.3125
expected_equal_stake_share=0.0312
```

### Stage 5: Consensus Path Records And Score Update

Goal: make path evidence affect future scores.

- Choose one encoding:
  - beacon block body extension; or
  - committed sidecar root with deterministic availability rules.
- Add path record verification during block processing or epoch processing.
- Update scores only from finalized or safely settled data, matching the
  simulator rule that current epoch evidence affects future proposer weights.

Validation:

- Invalid path records produce zero score/reward without breaking base block
  processing, if that remains the intended protocol rule.
- Repeated validator identities and duplicate receive proofs are rejected for
  score.
- Score updates at epoch boundary and never affects the current epoch's
  already-frozen proposer schedule.

Prompt 11 implementation on 2026-07-04 added the first minimal score-update
skeleton in `ethereum-topostake/lighthouse`:

- A devnet-only graffiti marker `TPS1:<validator_csv>` is decoded from each
  processed beacon block body.
- Valid path identities must be unique validator indices and fit within
  `MAX_PATH_EVIDENCE_LEN`.
- Valid receiver observations add one fixed-point score unit, capped by
  `BONUS_CAP_SCALED`.
- Duplicate receiver proofs and malformed paths are counted and ignored for
  score.
- `BeaconState` proposer selection now queries dynamic evidence scores through
  the same fork-gated TopoStake proposer-weight wrapper used by Prompt 10.
- With `EVIDENCE_FINALITY_DEPTH=0`, evidence from epoch `e` can affect epoch
  `e + 1`; by default the config keeps a one-epoch delay.

Implemented Prompt 11 files:

- `consensus/types/src/core/chain_spec.rs`
- `consensus/types/src/core/mod.rs`
- `consensus/types/src/state/beacon_state.rs`
- `consensus/state_processing/src/metrics.rs`
- `consensus/state_processing/src/per_block_processing.rs`
- `consensus/types/tests/state.rs`
- `kurtosis/grafana-dashboards/topostake-evidence-score.json`
- historical `kurtosis/topostake-devnet-custom-lighthouse-evidence.yaml`
  (deleted after Prompt 1-13 cleanup)

Prompt 11 validation passed:

```bash
cd ethereum-topostake/lighthouse
cargo fmt --check
cargo test -p types topostake -- --nocapture
cargo check -p state_processing
cargo build --bin lighthouse --release --locked
```

The rebuilt `topostake/lighthouse:dev` image
`sha256:3717057fae8d0416900a22cd6d270519c9207b1482c18f6a26b3b5bacbe362a5`
started a 4-node Kurtosis custom Lighthouse devnet with graffiti evidence.
Recent blocks carried `TPS1:0,1,2,3`, CL1 reached `head_slot=133`,
`current_justified_epoch=3`, and `finalized_epoch=2`.

Live proposer duties showed path evidence changing future proposer weights:

```text
epoch=0 duties=32 boosted_0_3=1
epoch=2 duties=32 boosted_0_3=9
epoch=3 duties=32 boosted_0_3=10
epoch=4 duties=32 boosted_0_3=11
expected_equal_stake_share=0.0312
```

The Prompt 11 observability follow-up exports the score path to Prometheus and
loads a Grafana dashboard named `TopoStake Evidence Score`:

```text
topostake_evidence_paths_total
topostake_evidence_sources_total
topostake_evidence_epoch_valid_paths
topostake_evidence_epoch_invalid_paths
topostake_evidence_epoch_duplicate_receivers
topostake_evidence_epoch_scored_validators
topostake_evidence_epoch_max_score_scaled
topostake_evidence_epoch_bound_violation
topostake_epoch_score_scaled
topostake_proposer_weight_scaled
```

Validation observed `topostake_epoch_score_scaled=1000000000` for validators
0-3 in evidence epoch 0 and
`topostake_proposer_weight_scaled=320000000000000000000` for proposer epoch 1.
Grafana search returned dashboard UID `topostake-evidence-score`.

Prompt 11.5 then replaced the direct `TPS1:<validator_csv>` smoke path with a
devnet-only sidecar root fixture:

- Blocks carry `TPSR:5d9ec3b5d64db62e` in graffiti.
- `TOPOSTAKE_CONFIG.SIDECAR_FIXTURES` maps that root tag to
  `VALIDATOR_PATH=0,1,2,3`.
- Lighthouse accepts the record as `source="sidecar_fixture"` and exposes that
  through `topostake_evidence_sources_total`.
- Missing root fixtures are counted as `outcome="missing_sidecar"` and produce
  zero score.

Prompt 11.5 validation on the 4-node Kurtosis devnet reached
`finalized_epoch=5`. Prometheus observed:

```text
sum(topostake_evidence_sources_total{source="sidecar_fixture"}) = 32
sum(topostake_evidence_paths_total{outcome="valid"}) = 32
topostake_evidence_sources_total{source="inline_graffiti"} = empty
topostake_evidence_paths_total{outcome="missing_sidecar"} = empty
topostake_evidence_epoch_scored_validators{epoch="5"} = 4
topostake_epoch_score_scaled{evidence_epoch="5",validator_index="0..3"} = 1000000000
topostake_proposer_weight_scaled{proposer_epoch="6",validator_index="0..3"} = 320000000000000000000
```

Prompt 11.6 preserved the external Lighthouse changes as a repo-local patch:

```text
patches/lighthouse-topostake-prompts-6-11_5.patch
```

It also added a missing-sidecar negative devnet config, now kept only as a
historical note:

```text
kurtosis/topostake-devnet-custom-lighthouse-missing-sidecar.yaml
```

That deleted config emitted `TPSR:deadbeef` but provided no `SIDECAR_FIXTURES`. The
4-node negative devnet finalized to epoch 2 while Prometheus showed:

```text
sum(topostake_evidence_paths_total{outcome="missing_sidecar"}) = 636
sum(topostake_evidence_paths_total{outcome="valid"}) = empty
sum(topostake_evidence_sources_total{source="sidecar_fixture"}) = empty
topostake_epoch_score_scaled = empty
topostake_evidence_epoch_scored_validators{epoch="0..3"} = 0
topostake_evidence_epoch_max_score_scaled{epoch="0..3"} = 0
```

This is intentionally not the final Stage 5 design yet. The Prompt 11
accumulator is process-local runtime state. Prompt 11.5 adds a root-tag lookup
boundary, but the sidecar is still a `ChainSpec` fixture rather than a
network-gossiped SSZ sidecar, and the block carries only a short tag instead of
a full committed root. BLS aggregate path verification plus real sidecar/root
availability semantics still need to replace this before it can be treated as
real consensus evidence. The new Prometheus metrics are observability only and
are not consensus fields.

### Stage 6: Reward Settlement

Goal: settle relay rewards.

- For a devnet-only CL accounting prototype, track relay credits as runtime
  audit state and export them.
- For real ETH settlement, design an EL/CL bridge or contract-based settlement.
  This is much larger than a Lighthouse-only patch because execution-layer fee
  accounting is not owned by the consensus client.

Prompt 12 implementation on 2026-07-04 added the devnet-only runtime ledger:

- each valid path evidence record creates one scaled credit budget of
  `1000000000`;
- `PROPOSER_FEE_RATIO_SCALED` determines the proposer share;
- the remaining relay budget is split evenly across path validators;
- integer remainder is recorded as burned credit;
- `settlement_epoch = evidence_epoch + REWARD_SETTLEMENT_DEPTH`;
- records become `settled` once the state's finalized epoch reaches the
  settlement epoch;
- credits do not mutate validator balances, effective balances, beacon rewards,
  or finality voting weights.

Prompt 12 metrics:

```text
topostake_credit_epoch_records
topostake_credit_epoch_total_scaled
topostake_credit_validator_total_scaled
topostake_credit_epoch_conservation_violation
```

Prompt 12 validation passed:

```text
cargo fmt --check
cargo test -p types topostake -- --nocapture
cargo check -p state_processing
```

The new test `topostake_credit_ledger_records_valid_paths_only` verifies the
fixed path fixture, fee-budget conservation, per-validator proposer/relay
credits, and pending-to-settled transition.

The rebuilt Prompt 12 image
`sha256:bd1a2707bb9cfdd22712d255c8357953660ddee0a63cb1ac71b7ed1fa0e38e25`
started the `topostake-devnet-credit-ledger` Kurtosis devnet and finalized to
epoch 2. Prometheus observed:

```text
sum by (status) (topostake_credit_epoch_records) = total:20, pending:16, settled:4
sum by (role) (topostake_credit_epoch_total_scaled) = budget:20000000000, proposer:10000000000, relay:10000000000, burned:0
max(topostake_credit_epoch_conservation_violation) = 0
sum(topostake_evidence_sources_total{source="sidecar_fixture"}) = 20
sum(topostake_evidence_paths_total{outcome="valid"}) = 20
```

The Grafana dashboard `TopoStake Evidence Score` now includes credit ledger
panels for total credit roles, per-validator credits, settlement status, and
conservation violations.

Prompt 12.5 added the negative credit-ledger validation. The unit tests now
assert that missing sidecar evidence has zero credit records and zero credit
budget, and that duplicate/invalid path evidence does not create additional
relay credits. The missing-sidecar Kurtosis run
`topostake-devnet-credit-negative` finalized to epoch 2 and Prometheus observed:

```text
sum(topostake_evidence_paths_total{outcome="missing_sidecar"}) = 630
sum(topostake_evidence_paths_total{outcome="valid"}) = empty
sum(topostake_epoch_score_scaled) = empty
sum(topostake_credit_epoch_records{status="total"}) = 0
sum(topostake_credit_epoch_total_scaled{role="budget"}) = 0
sum(topostake_credit_validator_total_scaled) = empty
max(topostake_credit_epoch_conservation_violation) = 0
```

This locks the intended boundary: bad or unavailable evidence may be observed
for diagnostics, but it cannot affect score or credit accounting.

Prompt 13 then ran a short baseline-vs-TopoStake devnet smoke comparison with
fixed 32 ETH validator balances. Both runs reached `head_slot=161`,
`observed_blocks=161`, `missing_slots=0`, `finalized_epoch=3`, and
`current_justified_epoch=4`. In the stock baseline, validators `0..3` proposed
`4/161` blocks and no TopoStake metrics existed. In the TopoStake run,
validators `0..3` proposed `31/161` blocks; Prometheus observed
`valid_paths=21`, `sidecar_fixture=21`, `score_sum=84000000000`,
`credit_records=21`, `budget=21000000000`, `proposer=10500000000`,
`relay=10500000000`, `burned=0`, and conservation violation `0`.

This validates the current skeleton as an end-to-end devnet smoke path:
evidence reaches score/proposer weight/credit accounting and the chain still
finalizes. It is not yet a production fork because the evidence is still a
graffiti root tag plus local fixture, not a network-gossiped SSZ sidecar with
BLS aggregate path verification.

Validation:

- Fee-budget conservation: proposer share + relay share + burned remainder is
  deterministic and bounded.
- Settlement only happens after finality depth.

## Risk And Effort Estimate

| Work item | Risk | Effort | Notes |
|---|---|---:|---|
| Metrics/instrumentation | Low | 2-5 days | Safe because it is read-only observation in the custom image. Good first Lighthouse spike. |
| External sidecar verifier | Low/Medium | 1-2 weeks | Useful for experiments, not consensus. |
| Consensus state fields | Medium | 2-4 weeks | SSZ/fork/state migration work is delicate. |
| Proposer-selection fork | High | 3-6 weeks | Must touch proposer computation, duties, cache/lookahead, tests, devnet config. |
| Block/body path-record encoding | High | 4-8 weeks | Requires fork-gated SSZ changes and block verification rules. |
| Score update in epoch processing | High | 3-6 weeks | Must be deterministic and not circular with current epoch proposer selection. |
| Relay fee settlement | Very high | 6-12+ weeks | Crosses CL/EL economic accounting if using real transaction fees. |

## Suggested Task Breakdown

1. Add Lighthouse-only read-only metrics for TopoStake observations.
2. Build `topostake/lighthouse:dev` and run the existing Kurtosis custom-image
   devnet.
3. Add a non-consensus sidecar receiver and compare its decoded path evidence
   with `prototype/ethereum-overhead/verifier.py`.
4. Draft a TopoStake devnet fork spec:
   - fork epoch;
   - extra state fields;
   - path-record encoding;
   - invalid evidence policy;
   - proposer-weight formula;
   - score update timing.
   Status: drafted in `docs/TOPOSTAKE_ETHEREUM_FORK_SPEC.md`.
5. Implement consensus state skeleton with no proposer-selection change.
   Status: Prompt 9 skeleton implemented in `ethereum-topostake/lighthouse`; default-disabled
   config and zero-score behavior tests pass.
6. Implement TopoStake proposer schedule behind the fork flag.
   Status: Prompt 10 fixture-driven proposer selection implemented and
   validated in Kurtosis.
7. Add block/path verification and epoch score updates.
   Status: Prompt 11 graffiti evidence skeleton implemented and validated in
   Kurtosis. Still needs committed sidecar/root, SSZ state, and BLS path
   verification.
8. Treat real reward settlement as a separate project after proposer-selection
   and score semantics are stable.

## Validation Checklist For A Future Implementation

- `cargo test -p state_processing` or targeted state transition tests.
- Proposer selection deterministic test for multiple seeds and epochs.
- Duties endpoint test showing beacon node and validator client agree.
- Block verification test where wrong proposer is rejected.
- Default build/fork produces identical proposer duties to upstream.
- Kurtosis devnet with 4 custom Lighthouse nodes finalizes.
- Mixed custom/stock devnet is not considered supported once proposer selection
  changes.
