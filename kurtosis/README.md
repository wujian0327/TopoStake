# TopoStake Kurtosis Notes

This directory now only keeps Kurtosis-adjacent assets that are still useful for the current TopoStake devnet work.

## Current Status

Prompt 1-13 were environment, fixture, and smoke-validation stages. Their Kurtosis YAML files have been removed on purpose:

- `topostake-devnet.yaml`
- `topostake-devnet-custom-lighthouse.yaml`
- `topostake-devnet-4node-1validator.yaml`
- `topostake-devnet-custom-lighthouse-fixture.yaml`
- `topostake-devnet-custom-lighthouse-evidence.yaml`
- `topostake-devnet-custom-lighthouse-missing-sidecar.yaml`

Do not reproduce Prompt 1-13 from this directory. The current implementation line starts at Prompt 14.

## Current Mainline Devnet

Prompt 14-18 use custom geth + custom Lighthouse and a generated private args file:

```text
results/raw/topostake-devnet-4node-1validator-custom-geth-private.yaml
```

That file is kept under `results/raw/` because it includes devnet-only relay private keys and local registry data. It is not meant to be a clean committed config.

The current smoke command is:

```bash
HOME=/tmp \
KURTOSIS_PACKAGE=/tmp/ethereum-package \
CUSTOM_ARGS=/home/wujian/pog-rs/results/raw/topostake-devnet-4node-1validator-custom-geth-private.yaml \
CUSTOM_ENCLAVE=topostake-devnet-prompt18-p2p-sidecar \
./scripts/kurtosis_devnet.sh start-custom
```

Before each run, clean the old enclave:

```bash
kurtosis enclave rm -f topostake-devnet-prompt18-p2p-sidecar
```

## Remaining Assets

- `grafana-dashboards/topostake-evidence-score.json`
- `grafana-dashboards/topostake-propagation.json`

These dashboards are still useful for observing TopoStake evidence and propagation metrics.

## Main Documentation

See `../kurtosis.md` for the compact project history and the Prompt 14-18 current implementation summary.
