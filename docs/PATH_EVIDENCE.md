# TopoStake Path Evidence

This document describes the revised path evidence implemented for TopoStake.

## In-Flight Representation

`TransactionPaths` is the in-memory transaction propagation record. It stores:

- the transaction;
- the epoch used for replay protection;
- edge-centric hops.

Each hop stores:

- `from`;
- `to`;
- `prefix`, the chain value `c_i`;
- `sender_signature`;
- optional `receiver_signature`.

A sender appends a pending outgoing hop with `append_outgoing_hop`. The receiver
verifies the prefix and sender signature, checks the receipt commitment cache,
and adds the receiver signature with `complete_pending_hop`.

## Prefix Chain

For transaction `tx` in epoch `e` and path `v0,...,vm`:

```text
c0 = H(H(tx) || e || H(v0))
ci = H(c{i-1} || H(vi)) for i > 0
```

For edge `(vi, v{i+1})`:

```text
Mi = ci || H(vi) || H(v{i+1})
```

Both endpoints sign the same edge statement. An `m`-hop path therefore produces
`2m` signer-message pairs.

## Block Record

`AggregatedSignedPaths` is the block-level record:

- `signature`: one BLS aggregate signature over all sender and receiver proofs;
- `paths`: the non-proposer validator sequence.

The proposer identity is taken from the block header and is not repeated in the
path record. Verifiers reconstruct the full path by appending the block miner.
Path verification uses the block epoch, so replaying a path record in another
epoch fails.

## Validity Rules

A reward-eligible path must:

- verify the transaction;
- start with the transaction originator;
- end at the block proposer;
- contain no repeated validator identities;
- have all sender and receiver signatures;
- use registered BLS relay keys;
- verify the aggregate signature over all `2m` signer-message pairs.

Invalid or missing evidence gives zero relay reward and zero propagation score.
It does not invalidate an otherwise valid base block.

## Receipt Cache

The simulator maintains a receipt-commitment cache keyed by:

```text
(transaction_hash, epoch, receiver)
```

A validator may create multiple outgoing sender proofs, but only one
reward-eligible receiving proof for the same transaction and epoch. A second
receiving proof with a different edge statement is rejected and counted as a
conflict.

## BLS Key Registry

The simulator uses a trusted BLS relay-key registry abstraction in
`wallet::register_trusted_bls_pub_key`. Wallet creation inserts locally derived
BLS keys into this registry. A production deployment should replace this with a
registration flow that verifies proof-of-possession. The verifier does not
silently accept unregistered keys; missing keys make path verification fail.
