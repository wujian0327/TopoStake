# Lighthouse Patch Artifacts

This directory stores patch artifacts for the external Lighthouse checkout used
by the Kurtosis TopoStake devnet work. The Lighthouse source itself stays
outside this repository.

## `lighthouse-topostake-prompts-6-11_5.patch`

Generated from:

```bash
git -C /tmp/lighthouse diff --binary
```

The patch covers the local Lighthouse changes through Prompt 11.5:

- Prompt 6 propagation/gossip instrumentation.
- Prompt 9-10 TopoStake config and proposer-weight skeleton.
- Prompt 11 path evidence score update.
- Prompt 11.5 `TPSR:` sidecar-root fixture path.

Validation:

```bash
git -C /tmp/lighthouse apply --reverse --check \
  /home/wujian/pog-rs/patches/lighthouse-topostake-prompts-6-11_5.patch
```

The reverse check verifies that the patch matches the current dirty Lighthouse
working tree.

## `lighthouse-topostake-prompts-6-12.patch`

Generated from the same `/tmp/lighthouse` checkout after Prompt 12.5:

```bash
git -C /tmp/lighthouse diff --binary
```

This patch supersedes the 6-11.5 patch for the current working tree and adds:

- devnet-only relay/proposer credit ledger;
- per-epoch credit summaries;
- per-validator proposer and relay credit totals;
- pending/settled credit record status using `reward_settlement_depth`;
- Prometheus metrics for credit totals and fee-budget conservation;
- negative tests proving missing sidecar, duplicate receiver, and invalid path
  evidence do not create score or credit.

Validation:

```bash
git -C /tmp/lighthouse apply --reverse --check \
  /home/wujian/pog-rs/patches/lighthouse-topostake-prompts-6-12.patch
```
