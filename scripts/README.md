```
cd ethereum-topostake/go-ethereum-topostake
make geth

GETH_BINARY=./ethereum-topostake/go-ethereum-topostake/build/bin/geth \
  ./scripts/geth_image.sh package-local
```

```
cd ethereum-topostake/lighthouse

cargo build --release \
  -p lighthouse \
  --features spec-minimal

cd ../../

LIGHTHOUSE_BINARY=ethereum-topostake/lighthouse/target/release/lighthouse \
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


python scripts/task.py frozen-devnet-main --dry-run

python scripts/task.py frozen-devnet-main \
  --package /home/wujian/ethereum-package \
  --nodes 8 \
  --loads 32 \
  --seeds 0 \
  --resume \
  --stop-on-failure

python scripts/task.py frozen-devnet-main \
  --package /home/wujian/ethereum-package \
  --resume
```

Use `--dry-run` first to inspect the matrix. Formal run directories contain the
Kurtosis args, workload summary, raw resource JSONL, acceptance report, and
runner status; aggregate CSVs are placed in `results/processed/`.

```
python - <<'PY'
import csv

path = "results/processed/frozen_v1_devnet_main.csv"
rows = list(csv.DictReader(open(path)))

print("rows:", len(rows))
print("status failures:", sum(r["status"] != "ok" for r in rows))
print("acceptance failures:", sum(r["acceptance_passed"] != "True" for r in rows))
print("quality failures:", sum(r["measurement_quality_passed"] != "True" for r in rows))
print("zero resource samples:", sum(int(float(r["resource_samples"])) == 0 for r in rows))
print("zero block samples:", sum(int(float(r["block_ssz_count"])) == 0 for r in rows))
PY
```
