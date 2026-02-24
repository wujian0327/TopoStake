## How to use

### 1.Install Rust

For windows：

https://www.rust-lang.org/tools/install

For linux:

```
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
```

### 2.Run

- `n` for number of nodes
- `t` for transactions per second
- `c` for consensus type [pos,TopoStake]

```
cargo run --release -- -n 100 -t 10 -c pos
```

```
 cargo run --release -- -n 50 -t 50 -c topostake -g 0.6 --base-reward 1.0 --slot-duration 3 --transaction-fee 0.00001 --max-tx-per-block 200 
```
