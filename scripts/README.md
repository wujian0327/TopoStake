```
cd ethereum-topostake/go-ethereum-topostake
make geth

GETH_BINARY=.../build/bin/geth \
  ./scripts/geth_image.sh package-local
```

```
cd /home/wujian/pog-rs/ethereum-topostake/lighthouse

cargo build --release \
  -p lighthouse \
  --features spec-minimal

cd /home/wujian/pog-rs

LIGHTHOUSE_BINARY=/home/wujian/pog-rs/ethereum-topostake/lighthouse/target/release/lighthouse \
  ./scripts/lighthouse_image.sh package-local

./scripts/lighthouse_image.sh verify
```

The formal devnet runner also records inline evidence verification time, so
rebuild and repackage Lighthouse after instrumentation changes before running:

```bash
python scripts/task.py frozen-devnet-pilot \
  --package /home/wujian/ethereum-package \
  --resume --stop-on-failure

python scripts/task.py frozen-devnet-main \
  --package /home/wujian/ethereum-package \
  --resume
```

Use `--dry-run` first to inspect the matrix. Formal run directories contain the
Kurtosis args, workload summary, raw resource JSONL, acceptance report, and
runner status; aggregate CSVs are placed in `results/processed/`.
