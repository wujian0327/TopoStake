# TopoStake Ethereum Devnet Fork Spec

Status: draft for a devnet-only Lighthouse fork. This document is a design
specification only; it does not implement consensus code.

The goal is to define the smallest consensus boundary required for TopoStake to
affect Ethereum proposer selection safely. Prompt 3 and Prompt 7 calldata
experiments remain external measurement paths. They are useful for overhead and
observability, but they do not by themselves provide consensus data that can
drive beacon-state changes.

## Design Goals

- Keep economic stake as the security resource.
- Use propagation score only as a bounded proposer-selection bonus.
- Keep finality voting, attestation weight, slashing, activation, exit, and
  effective balance rules based on ordinary Ethereum stake.
- Freeze proposer weights before they are used for an epoch.
- Update propagation scores only after the evidence epoch is complete and
  sufficiently finalized.
- Treat missing or invalid path evidence as zero TopoStake score/reward, not as
  a reason to invalidate an otherwise valid Ethereum block.
- Make every consensus-affecting field deterministic, SSZ-serializable, and
  included in beacon state roots or block roots where appropriate.

## Fork Parameters

These parameters must be identical for all consensus clients in a TopoStake
devnet.

| Parameter | Type | Suggested devnet default | Consensus? | Meaning |
|---|---:|---:|---|---|
| `topostake_fork_epoch` | `Epoch` | disabled unless explicitly set | Yes | First epoch where TopoStake state fields and rules are active. |
| `eta` | fixed-point decimal, scaled `uint64` | `0.25` | Yes | Multiplier applied to normalized propagation bonus in proposer weight. |
| `bonus_cap` | fixed-point decimal, scaled `uint64` | `1.0` | Yes | Upper bound on a validator's normalized propagation bonus. |
| `score_ema_beta` | fixed-point decimal, scaled `uint64` | `0.8` | Yes | EMA retention for propagation score history. |
| `score_saturation_k` | fixed-point decimal, scaled `uint64` | `1.0` | Yes | Saturation parameter for converting raw path contributions into bounded score. |
| `score_initial_depth` | `uint64` | `4` | Yes | Initial target path depth used before finalized observations exist. |
| `reward_settlement_depth` | `uint64` epochs | `2` | Yes, if reward ledger is enabled | Minimum finality delay before relay credits are settled. |
| `max_path_evidence_len` | `uint64` | `32` validators | Yes | Maximum relay path length accepted for score/reward accounting. |
| `max_path_evidence_bytes` | `uint64` | `65536` bytes per block | Yes | Maximum serialized TopoStake evidence bytes accepted for a block/sidecar. |
| `max_paths_per_block` | `uint64` | `1024` | Yes | Maximum path records processed for one block. |
| `proposer_fee_ratio` | fixed-point decimal, scaled `uint64` | `0.5` | Yes, if reward ledger is enabled | Fraction of TopoStake reward budget retained by proposer before relay sharing. |
| `evidence_finality_depth` | `uint64` epochs | `1` | Yes | Number of finalized epochs to wait before evidence can update score. |

Fixed-point values should use one shared integer scale, for example
`TOPOS_FIXED_POINT_SCALE = 1_000_000_000`. Floating-point arithmetic must not be
used in consensus.

## Beacon State Field Draft

All fields in this section are consensus fields once `topostake_fork_epoch` is
active. They must be represented in SSZ and included in `hash_tree_root`.

The names are draft names, not final Lighthouse type names.

| Field | Draft SSZ type | Included in state root? | Purpose |
|---|---|---|---|
| `topostake_config` | `TopoStakeConfig` or fork config constants | Yes if stored in state; otherwise genesis/fork config | Parameters used by all deterministic TopoStake rules. |
| `topostake_score_epoch` | `Epoch` | Yes | Last epoch for which propagation scores were computed. |
| `topostake_raw_score_snapshot` | `List[uint64, VALIDATOR_REGISTRY_LIMIT]` | Yes | Raw/saturated propagation score per validator before normalization. |
| `topostake_normalized_score_snapshot` | `List[uint64, VALIDATOR_REGISTRY_LIMIT]` | Yes | Bounded score in `[0, bonus_cap]`, scaled integer. |
| `topostake_frozen_stake_snapshot` | `List[Gwei, VALIDATOR_REGISTRY_LIMIT]` | Yes | Economic stake snapshot used to compute an epoch's proposer weights. |
| `topostake_proposer_weight_snapshot` | `List[uint64, VALIDATOR_REGISTRY_LIMIT]` | Yes | Frozen proposer-sampling weights for the active/future epoch. |
| `topostake_pending_relay_settlements` | `List[TopoStakeSettlement, MAX_PENDING_TOPOSTAKE_SETTLEMENTS]` | Yes, if relay ledger is enabled | Deterministic queue of finalized relay/proposer credit deltas. |
| `topostake_path_evidence_accumulator` | `Root` | Yes, if evidence is accumulated in state | Optional root of accepted/ignored evidence summaries for auditability. |
| `topostake_latest_evidence_roots` | `Vector[Root, EPOCHS_PER_HISTORICAL_VECTOR]` | Yes, if committed sidecars are used | Per-epoch rolling roots of path evidence commitments. |

`topostake_frozen_stake_snapshot` must not be updated intra-epoch. It is copied
from normal economic stake/effective balance at a deterministic epoch boundary.
Reward settlement must not mutate this snapshot after it is frozen.

## Draft SSZ Containers

These containers are illustrative and should be refined against Lighthouse's
existing type system.

```text
container TopoStakeConfig:
    topostake_fork_epoch: Epoch
    eta_scaled: uint64
    bonus_cap_scaled: uint64
    score_ema_beta_scaled: uint64
    score_saturation_k_scaled: uint64
    score_initial_depth: uint64
    reward_settlement_depth: uint64
    max_path_evidence_len: uint64
    max_path_evidence_bytes: uint64
    max_paths_per_block: uint64
    proposer_fee_ratio_scaled: uint64
    evidence_finality_depth: uint64

container TopoStakePathRecord:
    tx_root: Root
    epoch: Epoch
    validator_path: List[ValidatorIndex, MAX_TOPOSTAKE_PATH_LEN]
    aggregate_signature: BLSSignature

container TopoStakeEvidenceSidecar:
    slot: Slot
    block_root: Root
    proposer_index: ValidatorIndex
    records: List[TopoStakePathRecord, MAX_TOPOSTAKE_PATHS_PER_BLOCK]

container TopoStakeSettlement:
    settlement_epoch: Epoch
    block_root: Root
    validator_index: ValidatorIndex
    credit: uint64
    role: uint8  # proposer or relay
```

## Block And Sidecar Encoding Options

### Option A: Beacon Block Body Extension

Add TopoStake path evidence or a compact evidence commitment directly to the
beacon block body.

Consensus properties:

- Included in beacon block SSZ and block root.
- All nodes verify the same bytes during block processing.
- A modified path record changes the block root.
- No separate availability protocol is needed if full evidence is in the block.

Pros:

- Simple consensus object graph.
- Strongest commitment and replay protection.
- Easier to write state transition tests.

Cons:

- Requires fork-gated beacon block body SSZ changes.
- Increases block size.
- Invalid encoding/oversized records can become block validity concerns.
- Harder to keep as a devnet-only experiment without touching many block types.

### Option B: Committed TopoStake Evidence Sidecar

Add a `topostake_evidence_root` commitment to the beacon block body and carry
the full `TopoStakeEvidenceSidecar` separately.

Consensus properties:

- The root is included in the beacon block root.
- The sidecar bytes are verified against the committed root.
- Availability rules must define when a block with a missing sidecar is
  acceptable or unacceptable.

Pros:

- Keeps beacon block body small.
- Closer to blob/data sidecar design patterns.
- Allows devnet to test evidence availability separately from block payload.

Cons:

- Requires sidecar gossip/availability plumbing.
- Missing sidecar semantics are subtle.
- More moving parts for the first consensus patch.

### Option C: Execution Calldata Only

Carry TopoStake path evidence as Ethereum transaction calldata, as in Prompt 3
and the mini Prompt 7 marker smoke test.

Consensus properties:

- Calldata is committed in the execution payload, but the consensus layer does
  not natively interpret it.
- Beacon nodes would need deterministic execution-payload scanning rules to use
  it for CL proposer weights.
- Without CL rules, it is external experiment data only.

Pros:

- No beacon SSZ changes.
- Easy to generate traffic on a Kurtosis devnet.
- Good for byte overhead, scanner, and instrumentation tests.

Cons:

- Not a clean CL consensus input.
- Hard to bind records to relay identities and BLS registry in beacon state.
- Hard to define sidecar availability, duplicate handling, and finality timing.
- Should not drive proposer selection without additional fork rules.

## Recommended Minimal Scheme

Use a two-step devnet path:

1. Prompt 9-10: implement only fork-gated state skeleton and proposer-weight
   snapshots from deterministic fixtures. Do not use live path evidence yet.
2. Prompt 11: add a committed evidence root. For the first implementation, the
   block body may carry only `topostake_evidence_root`; a devnet-only sidecar
   carries full `TopoStakeEvidenceSidecar`.

Rationale:

- Proposer selection can be tested independently from evidence parsing.
- The state root and proposer duties change only after the fork is explicitly
  enabled.
- Calldata experiments remain useful but cannot accidentally become implicit
  consensus inputs.
- A sidecar root is the cleanest long-term boundary between block commitment and
  larger path records.

For a very first skeleton, a block body extension with an empty or zero root is
acceptable if sidecar plumbing is too large. Execution calldata alone should
remain non-consensus.

Implementation note: Prompt 11 used an even thinner block-body skeleton for
the first live devnet check. It encodes path evidence in the existing beacon
block graffiti field as ASCII `TPS1:<validator_csv>`, for example
`TPS1:0,1,2,3`. This is useful for validating score-update timing and proposer
duty effects without changing SSZ block types, but it is not the recommended
final encoding. A real TopoStake fork should replace this with a committed
evidence root and/or fork-gated block body field.

Implementation note: Prompt 11.5 moves one step closer to the recommended
boundary without changing SSZ block types. Blocks carry a short graffiti root
tag, for example `TPSR:5d9ec3b5d64db62e`, and a devnet-only
`TOPOSTAKE_CONFIG.SIDECAR_FIXTURES` entry maps that tag to the full fixture path
`0,1,2,3`. The tag is derived from the fixture payload, but it is only a short
identifier constrained by graffiti size, not a full consensus-committed root.
The sidecar payload is local config, not a gossiped SSZ object.

Implementation note: Prompt 14 adds an execution-layer transaction propagation
carrier. Custom geth can attach an optional `TopoStake` metadata vector to
`NewPooledTransactionHashes`, `PooledTransactions`, and
`PooledTransactionsRLP`. This metadata is a devnet-only propagation envelope:
it is not included in signed transaction RLP, does not change `tx.Hash()`, and
does not affect EVM execution. When TopoStake is enabled, direct transaction
broadcast is routed through the pooled-transaction announcement/request/response
path so the metadata can travel with the transaction.

The Prompt 14 carrier is necessary but not sufficient for consensus scoring.
Consensus scoring still requires a deterministic EL -> CL handoff where the
block proposer commits the selected transactions' complete propagation evidence
through a sidecar root or fork-gated block field. Until that handoff exists,
`topostake_tx_metadata_*` metrics demonstrate transaction-gossip carriage only;
they must not be treated as accepted consensus evidence.

Prompt 14-D3 extends this carrier with a devnet execution-peer registry. The
registry maps fixed geth devp2p peer IDs to `validator_index`, while the relay
public-key registry maps `validator_index` to TopoStake relay BLS pubkey. With
both registries present, a custom geth can derive a per-peer outgoing edge,
sign `(local_validator -> remote_validator)` with its relay private key, and the
receiver can verify the sender proof before adding its receiver signature. This
is still a transaction-gossip proof, not accepted consensus evidence, until the
selected block transactions are handed from EL to CL and committed by the block
proposer.

## Consensus Rules

### Fork Activation

- Before `topostake_fork_epoch`, all TopoStake state fields are absent or
  ignored, and upstream Ethereum proposer selection is used.
- At `topostake_fork_epoch`, all nodes initialize TopoStake state fields from
  the same genesis/fork config.
- A node without this fork will compute different state roots or proposer
  duties once TopoStake consensus fields/rules are active.

### Proposer Weight Formula

Economic stake remains the base security weight. For validator `i` at epoch
`e`, define:

```text
S_i(e) = frozen economic stake snapshot
P_i(e) = normalized propagation score from finalized previous evidence
B_i(e) = min(P_i(e), bonus_cap)
W_i(e) = S_i(e) * (1 + eta * B_i(e))
```

All values are scaled integers. The mandatory bound is:

```text
W_i(e) <= S_i(e) * (1 + eta * bonus_cap)
```

If all scores are zero, proposer selection must be equivalent to ordinary PoS
for the same stake snapshot.

Implementation note: Prompt 10 implements this as a Lighthouse devnet-only
`ChainSpec` fixture path, not as finalized BeaconState SSZ score snapshots yet.
The fixture path is sufficient to validate deterministic proposer duties,
zero-score PoS equivalence, and bonus-cap bounds before adding real score
updates.

Implementation note: Prompt 11 extends the same devnet-only proposer-weight
path with runtime evidence scores decoded from `TPS1:` graffiti. The runtime
score is combined with the static fixture by taking the maximum bounded score
for each validator. This keeps the experiment simple, but it is not sufficient
for a production consensus fork because the evidence accumulator is not an SSZ
BeaconState field.

### Proposer Schedule Timing

- At epoch start, freeze `S_i(e)`.
- Compute `W_i(e)` from frozen stake and scores finalized before epoch `e`.
- During epoch `e`, proposer duties use only `topostake_proposer_weight_snapshot`
  for epoch `e`.
- Evidence observed in epoch `e` cannot affect proposer selection inside epoch
  `e`.
- Evidence from epoch `e` can affect proposer selection only in a future epoch
  after the configured finality/evidence depth.

Prompt 11 validation set `EVIDENCE_FINALITY_DEPTH=0` to make the local devnet
observable quickly. With that config, epoch `e` graffiti evidence first affects
epoch `e + 1` proposer sampling. The normal draft default remains a nonzero
delay so score changes are based on settled evidence.

### Finality Voting

Finality voting remains ordinary Ethereum PoS:

- attestation weights use economic stake/effective balance;
- justification/finalization uses economic stake;
- TopoStake propagation score does not increase finality voting power;
- relay credits do not change validator effective balance.

### Path Evidence Validity

A reward/score-eligible path record must satisfy the rules in
`docs/PATH_EVIDENCE.md`:

- starts at the transaction originator;
- ends at the block proposer;
- contains no repeated validator identities;
- contains all sender and receiver proofs;
- uses registered relay BLS keys;
- verifies the aggregate signature over all edge statements;
- uses the expected epoch for replay protection;
- fits within `max_path_evidence_len`, `max_path_evidence_bytes`, and
  `max_paths_per_block`.

Invalid evidence gives zero propagation score and zero relay reward for that
record. It does not invalidate the base block if the evidence container/root is
well-formed and matches the committed root.

Malformed consensus encoding, an oversized sidecar, an evidence root mismatch,
or an unavailable sidecar when availability is required is a block/sidecar
validity failure, not merely zero score.

Prompt 11 skeleton validity is intentionally weaker: non-`TPS1:` graffiti is
ignored, malformed `TPS1:` content increments an invalid-evidence counter, and
the base beacon block remains valid. This matches the zero-score policy for
bad path claims, but it does not yet test malformed committed sidecar/root
rules.

Prompt 11.5 adds a `TPSR:` graffiti path. Unknown or mismatched root tags are
counted as missing sidecar evidence and produce zero score, but they still do
not invalidate the base beacon block. That is deliberate for the devnet
skeleton; a real fork must decide whether a committed evidence root requires
sidecar availability for block validity.

Prompt 11.6 validated that boundary in Kurtosis: a devnet emitting
`TPSR:deadbeef` with no configured sidecar fixture finalized normally, produced
`missing_sidecar` metrics, and produced no score series. This confirms the
current skeleton's zero-score behavior; it should not be read as the final
availability rule for a consensus-committed sidecar.

### Duplicate Receiver Proofs

For a key:

```text
(tx_root, epoch, receiver_validator_index)
```

only one receiver proof can be reward/score eligible. If multiple records claim
different incoming edges for the same key:

- the first deterministic record order is not enough to choose a winner;
- all conflicting records for that key should be treated as invalid for
  score/reward;
- the base block remains valid if the sidecar/root is otherwise well-formed.

This avoids rewarding equivocation-like propagation claims.

Prompt 11 implements the minimal local version of this rule by allowing only
one score contribution per `(epoch, receiver_validator_index)` in the runtime
accumulator. A later committed sidecar implementation should include the
transaction root and deterministic conflict handling from the rule above.

### Score Update

Score update runs at a deterministic epoch transition after eligible evidence is
finalized enough:

```text
raw_i(e) = saturated path contribution for validator i from eligible evidence
score_i(e) = beta * score_i(e-1) + (1 - beta) * raw_i(e)
normalized_i(e) = min(score_i(e), bonus_cap)
```

The exact saturation function must be integer-only and monotonic. A suggested
shape is:

```text
saturated = raw / (raw + score_saturation_k * stake_snapshot)
```

implemented with scaled integer arithmetic. The final spec must include exact
rounding rules before implementation.

### Reward Settlement

Relay/proposer reward settlement is optional for the first proposer-selection
fork. If enabled:

- settlement happens only after `reward_settlement_depth`;
- settlements are stored in `topostake_pending_relay_settlements`;
- credits do not mutate validator effective balance;
- credits do not affect finality voting;
- credits do not modify the already-frozen stake snapshot for the current
  epoch;
- fee-budget conservation must be testable.

For real ETH settlement, a CL-only credit ledger is not enough. A production
design needs an EL contract or another deterministic EL/CL settlement bridge.

Prompt 12 implements the devnet-only audit version of this rule. Each accepted
path evidence record creates a scaled budget of `1000000000`; the proposer share
is `budget * proposer_fee_ratio_scaled / 1000000000`; the remaining relay
budget is split evenly across the validator identities in the path; any integer
remainder is recorded as burned credit. A record's settlement epoch is
`evidence_epoch + reward_settlement_depth`, and it becomes settled only once the
state's finalized epoch reaches that settlement epoch. This ledger is
process-local runtime state and Prometheus/CSV observability, not an SSZ
`topostake_pending_relay_settlements` field yet.

The Prompt 12 Kurtosis run finalized to epoch 2 and observed 20 credit records:
4 settled, 16 pending, total budget `20000000000`, proposer credit
`10000000000`, relay credit `10000000000`, burned credit `0`, and conservation
violation `0`. This validates the audit accounting rule but still does not
settle real ETH.

Prompt 12.5 validated the negative accounting boundary. Missing sidecar,
duplicate receiver, and invalid path evidence may be counted for diagnostics,
but they create no score and no relay/proposer credit. The missing-sidecar
Kurtosis run finalized to epoch 2 with `missing_sidecar=630`,
`valid=empty`, score series empty, credit records `0`, credit budget `0`, and
conservation violation `0`.

Prompt 13 validated the current skeleton end-to-end under fixed stake. A stock
baseline and a TopoStake devnet both reached `head_slot=161`, produced 161
blocks with no missing slots, and finalized to epoch 3. Validators `0..3`
proposed `4/161` blocks in the baseline and `31/161` blocks in the TopoStake
run. The TopoStake run observed `valid_paths=21`, `score_sum=84000000000`,
`credit_records=21`, `budget=21000000000`, `proposer=10500000000`,
`relay=10500000000`, `burned=0`, and conservation violation `0`.

The Prompt 13 live metadata overhead remains only the 21-byte graffiti root tag
`TPSR:5d9ec3b5d64db62e`; there is no real network SSZ sidecar or real BLS
aggregate path verification yet.

## State Root And External Data Boundary

Consensus-critical and included in SSZ/hash tree roots:

- TopoStake fork activation config, if stored in state.
- TopoStake score snapshots.
- Frozen economic stake snapshots.
- Frozen proposer weight snapshots.
- Pending relay settlement queue, if enabled.
- Evidence roots/accumulators, if used by score or rewards.
- Any block body field such as `topostake_evidence_root`.

Consensus-critical but possibly stored as fork/genesis constants rather than
state fields:

- `eta`.
- `bonus_cap`.
- score EMA/saturation parameters.
- max evidence sizes.
- reward settlement depth.

External experiment data only:

- Prompt 3 mock calldata JSONL files.
- Prompt 6 Prometheus/Grafana metrics.
- Prompt 7 marker smoke-test results under `results/`.
- Execution calldata scanned by off-chain tools, unless a future fork explicitly
  defines deterministic CL scanning and includes its result in beacon state.
- Non-committed sidecar logs or HTTP sidecar endpoints.

External data can inform experiments and dashboards. It must not influence
state roots, proposer duties, block validity, or rewards unless explicitly
committed and fork-gated.

## Why Mixed Stock And TopoStake Nodes Fork

Once TopoStake proposer selection is active, a TopoStake node computes proposer
duties from:

```text
topostake_proposer_weight_snapshot
```

A stock node computes proposer duties from ordinary effective balances. If the
weights differ, they can select different expected proposers for the same slot.
Then:

- a validator client attached to a TopoStake beacon node may sign a block for a
  proposer that stock Lighthouse does not expect;
- stock block verification recomputes the ordinary expected proposer and rejects
  the block as an incorrect proposer;
- fork choice, gossip scoring, and attestations diverge;
- finality can stall or the network can split.

Even before proposer selection changes, adding fork-gated SSZ state fields or a
block body evidence root changes state roots/block roots. A node that does not
understand the fork cannot validate those roots. Therefore a TopoStake consensus
devnet must run compatible consensus clients on all beacon nodes and validator
clients.

## Recommended Implementation Order

1. Add fork config and empty state skeleton. Default upstream behavior must be
   byte-for-byte unchanged when the fork is disabled.
2. Add tests that zero TopoStake score equals ordinary PoS.
3. Add fixture-driven proposer weights from deterministic config/state.
4. Update proposer duty caches, block production, and block verification to use
   the same fork-aware proposer calculation.
5. Add committed evidence root and empty sidecar validation.
6. Add path evidence decoding and score update after finality depth.
7. Add optional relay credit ledger.
8. Treat real ETH relay settlement as a separate EL/CL design.

## Required Tests Before Consensus Experiments

- Default fork disabled: state root, block root, and proposer duties match
  upstream for the same fixture.
- Fork enabled with all scores zero: proposer duties match ordinary PoS.
- Fork enabled with nonzero fixture score: proposer duties are deterministic
  across all nodes.
- Weight bound: `W_i <= S_i * (1 + eta * bonus_cap)`.
- Score timing: evidence from epoch `e` never affects epoch `e` proposer
  duties.
- Invalid evidence: zero score/reward and base block still valid when the
  evidence root/sidecar is well-formed.
- Malformed encoding or evidence-root mismatch: block/sidecar validation fails.
- Duplicate receiver proof: conflicting records get zero score/reward.
- Finality voting: TopoStake score does not alter attestation weight.
- Mixed stock/custom negative test: stock client rejects or diverges once
  TopoStake proposer selection or SSZ fields are active.
