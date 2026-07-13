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
