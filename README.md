# TopoStake Rust Simulator

## How to Run

### Install Rust

Windows:

https://www.rust-lang.org/tools/install

Linux/macOS:

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
```


### Run a Simulation

Use release mode for normal experiments:

```bash
cargo run --release -- -n 100 -t 10 -c pos
```

TopoStake example:

```bash
cargo run --release -- -n 100 -t 100 -c topostake -g 0.6 --base-reward 1.0 --slot-duration 2 --transaction-fee 0.00001 --max-tx-per-block 250
```

PoW example:

```bash
cargo run --release -- -n 100 -t 10 -c pow --pow-difficulty 20 --pow-max-threads 2
```

Minotaur example:

```bash
cargo run --release -- -n 100 -t 10 -c minotaur
```

## Common Options

- `-n, --node-num`: number of nodes, default `20`
- `-t, --trans-num`: transactions per second, default `10`
- `-c, --consensus`: consensus algorithm, one of `pos`, `topostake`, `pow`, `minotaur`
- `--topology`: network topology, one of `er`, `ba`, `ws`, default `ba`
- `-g, --gini`: initial Gini coefficient, default `0.6`
- `--slot-duration`: slot duration in seconds, default `2`
- `--slot-per-epoch`: number of slots per epoch, default `5`
- `--max-epochs`: maximum number of epochs to run, default `100`
- `--metrics-prefix`: prefix for the metrics output file, default `metrics`

## Output Files

After running, the simulator generates or updates these files in the project root:

- `output.log`: runtime log
- `graph.json`: generated network topology
- `<metrics-prefix>_<consensus>_n_<node_num>_t_<trans_num>_<topology>.csv`: metrics data
