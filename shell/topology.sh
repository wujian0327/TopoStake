cargo run --release -- -n 100 -t 100 -c topostake -g 0.6 --base-reward 1.0 --slot-duration 2 --transaction-fee 0.00001 --max-tx-per-block 250 --max-epochs 100 --topology ws
cargo run --release -- -n 100 -t 100 -c topostake -g 0.6 --base-reward 1.0 --slot-duration 2 --transaction-fee 0.00001 --max-tx-per-block 250 --max-epochs 100 --topology er

cargo run --release -- -n 100 -t 100 -c pos -g 0.6 --base-reward 1.0 --slot-duration 2 --transaction-fee 0.00001 --max-tx-per-block 250 --max-epochs 100 --topology ws
cargo run --release -- -n 100 -t 100 -c pos -g 0.6 --base-reward 1.0 --slot-duration 2 --transaction-fee 0.00001 --max-tx-per-block 250 --max-epochs 100 --topology er


cargo run --release -- -n 100 -t 100 -c pow -g 0.6 --base-reward 1.0 --slot-duration 2 --transaction-fee 0.00001 --max-tx-per-block 250 --max-epochs 100 --topology ws
cargo run --release -- -n 100 -t 100 -c pow -g 0.6 --base-reward 1.0 --slot-duration 2 --transaction-fee 0.00001 --max-tx-per-block 250 --max-epochs 100 --topology er


cargo run --release -- -n 100 -t 100 -c minotaur -g 0.6 --base-reward 1.0 --slot-duration 2 --transaction-fee 0.00001 --max-tx-per-block 250 --max-epochs 100 --topology ws
cargo run --release -- -n 100 -t 100 -c minotaur -g 0.6 --base-reward 1.0 --slot-duration 2 --transaction-fee 0.00001 --max-tx-per-block 250 --max-epochs 100 --topology er