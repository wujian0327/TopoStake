# Revision V2 Plan

## 1. Current/New Behavior Mapping

- Current `topostake` mixes real stake, balance, propagation score, and proposer
  probability through a virtual-stake rule.
- Revised `topostake` keeps economic stake as the security resource and uses
  propagation score only as a bounded proposer bonus.
- Current score updates happen inside proposer selection. Revised score updates
  happen only at epoch boundaries after the epoch's blocks are known.
- Current rewards are paid into validator stake and can immediately change future
  proposer probabilities. Revised rewards are paid into account balances or
  pending settlements and do not alter the current epoch stake snapshot.
- Current relay fees are distributed from a global virtual-stake view. Revised
  relay fees are distributed per path using gamma values.
- Current block headers commit only to transaction hashes. Revised block headers
  commit to both transactions and serialized path records.

## 2. Data-Model Changes

- `Validator.stake` is treated as economic stake.
- `WorldState` keeps an account-balance map separate from validators.
- Consensus reward distribution returns balance deltas instead of mutating
  validator stake.
- `TopoStakeConfig` contains the revised parameters:
  `initial_depth`, `beta`, `saturation_k`, `eta`, `bonus_cap`,
  `proposer_fee_ratio`, and `reward_settlement_depth`.
- `TopoStakeConsensus` stores epoch score history, normalized score, frozen
  proposer weights, the stake snapshot used for those weights, and pending
  reward settlements.

## 3. Epoch State-Transition Order

1. At epoch start, freeze the economic-stake snapshot.
2. Compute proposer weights from that snapshot and the previous finalized score.
3. During the epoch, proposer selection samples only from the frozen weights.
4. Block inclusion pays rewards into a pending settlement queue.
5. At epoch end, verify eligible path records from the epoch and compute raw
   gamma contributions.
6. Apply stake-scaled saturation and EMA to update `Score(e)`.
7. Normalize the updated score to prepare the next epoch's proposer weights.
8. Optionally update the target depth for the next epoch from finalized eligible
   path lengths.

## 4. Migration Risks

- Existing simulator code assumes `Validator.stake` is also account balance.
  This must be removed without breaking PoS, PoW, and Minotaur runs.
- Invalid path evidence should give zero score/reward rather than a base block
  failure.
- Sybil helper nodes share a runtime task with their controller in the current
  simulator, so balance notifications remain approximate for those synthetic
  identities.

## 5. Planned Tests

- Path budget sums to `B(m)` and `B(m) <= 1`.
- `B(m)` decreases with path length.
- `lambda * (1 + r) == 1` within tolerance.
- Score from epoch `e` does not affect proposer election inside epoch `e`.
- `W_i <= (1 + eta * bonus_cap) * S_hat_i`.
- Coalition proposer-weight bound.
- Fee-budget balance for proposer, relayers, and burned fees.
- Balance changes do not alter the current epoch stake snapshot.
- Changing a committed path record invalidates the block body commitment.
