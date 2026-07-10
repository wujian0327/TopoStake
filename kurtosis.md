# TopoStake Ethereum/Kurtosis Reproduction Notes

本文档是当前 TopoStake Ethereum fork 的主线复现说明。它不再按 Prompt 流水展开，而是按协议实现拆成四个部分：

1. 路径传播
2. Score 与 proposer 选举
3. Reward 分配
4. 网络拓扑实现

最后一节单独归纳目前实验进展。当前实验结果仍属于 devnet/smoke 阶段，论文实验表还需要多 seed、多 topology、多 sender workload 和吞吐分档后再固定。

当前实现是 custom geth + custom Lighthouse 的 devnet fork，不保持 stock client 混跑兼容。主实验建议使用 `1 validator / node`，minimal preset，3s slot，8 slots/epoch。旧的 `4 nodes * 16 validators` 只作为历史 smoke/finality 验证入口保留。

## 当前状态

已完成：
- signed tx bytes / tx hash 不变，TopoStake path metadata 随 geth tx gossip envelope 同步传播。
- EL proposer 在 `engine_getPayload` 返回 execution payload 的同时返回 payload 对应的 TopoStake evidence。
- CL 将 bounded path records 写入 beacon block body 的 `topostake_evidence_records`。
- 旧 sidecar/latest/root fallback 已清理，不再通过 `topostake_latestBlockEvidence`、root RPC、CL sidecar HTTP/gossipsub 补 path。
- Lighthouse block processing 会按 block-level aggregate signature 验证 block-inline path records；验证失败的 records 不进入 score/reward。
- Score 只给 intermediate relayers，经过 finalized gate、stake-scaled saturation、EMA 后进入 proposer selection。
- Proposer selection 使用论文版 bounded bonus，只改 proposer weight，不改 attestation/finality voting weight。
- Reward 使用真实 priority fee budget，fee 先进入 escrow/system address，finalized 后按 block-visible settlement root + block-carried settlement records 执行 proposer/relay payout 与 burn。
- `8 nodes * 1 validator` devnet 已能启动、出块、finalized；BA(m=2) single-origin workload 下 slot-level inclusion delay 稳定在 `1-2 slots`，relay payout 非零，settlement conservation 为 0。
- `16 nodes * 1 validator` devnet 在 local path 修正后，Linear/Star/ER/BA 四个 single-origin workload 都达到 `3840 tx / 3840 valid path records / 3840 nonzero fee records`。
- 8-node BA overhead load sweep 已完成 `60-300 tx/slot` 正常区间；TopoStake 与 PoS-Beacon achieved tx/slot 基本一致，p95 inclusion delay 增量约 `0.7-0.8s`。
- 固定窗口 TPS probe 已完成 `32/64/96/128/160 TPS`：按 measurement 固定 `120s` 窗口计算 achieved ratio；`32-128 TPS` 区间 TopoStake 与 PoS-Beacon 接近，`160 TPS` 已进入本机/workload stress 区间。
- 高负载探测显示当前 8-node BA devnet 的瓶颈在 `360-420 tx/slot` 区间开始显现：TopoStake `360 tx/slot` 还能完成但 achieved tx/slot 降到约 `323.07`，`420 tx/slot` p95 inclusion delay 升到约 `58.94s`，`480 tx/slot` 出现 receipt timeout 与部分 EL 明显落后。
- warmup 后低负载 node-count sweep 已完成 `8/12/16 nodes`，固定 `BA(m=2), 32 tx/slot, 1 epoch measurement`，三种模式 `PoS-Beacon / PoS+PathObs / TopoStake` 均达到 `512/512` included。TopoStake 相比 PoS+PathObs 的吞吐接近，p95 inclusion delay 保持在 `4.6-4.9s`；平均 path length 随节点数从约 `2.27` 增至约 `2.83`。
- Prompt 44 已完成 16-node ER/BA TopoStake 真实 fee mutation 修复验证；ER 与 BA 均能 finalized，且 Path Rec. / Fee Rec. 达到 `2560/2560`，fee conservation violation 为 `0`。
- Prompt 41 已按 `10 nodes, 32 tx/slot, measurement 5 epochs` 重跑 topology impact；PoS-Beacon/PoS+PathObs 使用 `3 epochs` warmup，TopoStake 使用 `5 epochs` warmup。Linear/ER/BA 三拓扑均 `1280/1280` included，Path Rec. / Fee Rec. 在 PathObs 和 TopoStake 中均达到 `1280/1280`；TopoStake 平均 path 在三拓扑下均略短于 PathObs。

仍未完全完成：
- 最终论文版 block-inline record schema 还需要固定，尤其是 aggregate signature 是否保留 block-level aggregate，还是改成 per-record/per-path aggregate。
- settlement records 已进入 geth block body / Engine API / Lighthouse ExecutionPayload，但 devnet 仍保留 local-store fallback；若做成正式协议，需要去掉 preload/RPC 依赖，并定义 settlement records availability 与重复 settlement 的 state-level 防重规则。
- 实验尚未完全稳定：当前 devnet 结果仍是 single seed；多 seed、多 topology、不同 offered load 与 warmup 长度还需要继续重跑和整理。
- 如果论文主张 TopoStake path 更短，当前 10-node single-seed Prompt 41 已出现正确方向，但仍需在 16-node、多 seed 和更长 measurement 下确认稳定性。
- 旧 receipt latency 口径已废弃；论文应使用 `included_block_timestamp - send_unix` 的 inclusion delay。
- 多入口 workload 需要 multiple funded senders，不能再用单 sender round-robin 作为吞吐/延迟结论，因为它会引入账户 nonce gap。
- 高负载下 TopoStake evidence coverage 会下降，需要继续区分 block-inline evidence bytes cap、节点落后和 block collection window 三个因素；低负载 warmup 实验已用 measurement tx hash 过滤 records，避免 warmup 尾部记录污染平均 path length。

## 复现约束

每次启动新的 Kurtosis devnet 前，必须先清理旧 devnet/enclave，避免旧服务、旧端口和旧 metrics 污染结果。

```bash
XDG_DATA_HOME=/tmp/kurtosis-data kurtosis enclave ls
XDG_DATA_HOME=/tmp/kurtosis-data kurtosis enclave rm -f <old-enclave-name>
```

Kurtosis CLI 在当前环境需要使用 `XDG_DATA_HOME=/tmp/kurtosis-data`，否则可能尝试写入只读 home 路径。

Kurtosis ethereum-package 已在本机 `/tmp/ethereum-package` 有本地 checkout。后续启动 devnet 优先使用本地 package 路径，避免 Kurtosis engine 每次从 GitHub clone：

```bash
XDG_DATA_HOME=/tmp/kurtosis-data kurtosis run --enclave <enclave-name> /tmp/ethereum-package --args-file <args.yaml>
```

推荐主实验配置：
- nodes：`8`
- validators：`1 / node`
- preset：`minimal`
- slot：`seconds_per_slot=3`
- epoch：`slots_per_epoch=8`
- geth image：`topostake/geth:dev`
- Lighthouse image：`topostake/lighthouse:dev`
- additional services：默认关闭 `Prometheus/Grafana/ethereum-metrics-exporter`

Prometheus/Grafana 使用原则：
- 默认 devnet 压测和 missed-slot 诊断不启动 Prometheus/Grafana；
- 主指标从 runner 输出的 `summary.json`、`block_records.csv`、Beacon API、EL/CL/VC logs 计算；
- 只有需要跨 CL runtime gauge/counter，例如 proposer score、selection weight、settlement counter spread 时，才单独开启 Prometheus/Grafana；
- 原因是 Prometheus/Grafana 会增加容器数、scrape 压力和本机调度噪声，在 `3s slot`、多 EL/CL/VC 本机实验里可能放大 timing 抖动；
- 若某轮开启 Prometheus/Grafana，必须在 prompt/summary 中明确标注，不能和默认 no-prometheus run 直接混合比较。

历史稳定 smoke 配置：
- args：`results/raw/topostake-devnet-4node-16validator-natural-topology.yaml`
- validators：`4 nodes * 16 validators`

## 路径传播

目标是对齐论文语义：交易和路径一起传播，区块和路径一起传播。

### 交易传播

geth 的 signed transaction RLP 不变，因此：
- tx hash 不变；
- sender signature 不变；
- EVM 执行语义不变。

TopoStake metadata 作为 tx gossip envelope 的附加字段传播：
- origin relay 对 `chain_id + epoch + tx_hash + origin` 签名；
- relay 转发前补 sender proof；
- receiver 验证 sender proof 后补 receiver proof；
- path identity 使用 relay Ethereum address / payout identity，再映射到 devnet validator index。

关键边界：
- Ethereum EOA sender 不等于 TopoStake relay identity。
- originator 和 proposer/receiver 不拿 relay score/reward。
- direct path 不产生 relay contribution。
- 每笔 tx 最多接受一条 reward/score-eligible path。

### 区块传播

当前路径：

```text
geth tx gossip envelope
  -> TopoStake path metadata 随 tx 逐跳增长
  -> EL proposer 选 tx 构造 payload evidence
  -> engine_getPayload 返回 execution payload + topostakeBlockEvidence
  -> Lighthouse 写入 beacon block body topostake_evidence_records
  -> block processing 只消费 inline records
```

`topostake_evidence_records` 是 bounded block-inline path records。当前字段包括：
- `tx_hash`
- `epoch`
- `priority_fee_wei`
- relay path sequence
- `aggregate_signature`

当前保留 `topostake_evidence_root` 作为 block-visible commitment/兼容字段，但它不再驱动 sidecar lookup。

已删除或停用的旧路径：
- `topostake_latestBlockEvidence`
- `topostake_getBlockEvidenceByRoot`
- CL `/eth/v1/topostake/evidence/{root}`
- Lighthouse `TopoStakeEvidenceSidecar` gossipsub topic/cache/API
- block processing 中的 root/graffiti/RPC/latest fallback
- `TPS1:` / `TPSR:` graffiti evidence 生产消费路径

保留的调试入口：
- `topostake_getBlockEvidence(block_hash)`

### Evidence Verification

Lighthouse block processing 会验证 block-inline path evidence：
- geth 当前生成 block-level aggregate signature；
- inline record 中每条 tx record 携带同一个 `aggregate_signature`；
- Lighthouse 按 block 内全部 inline records 重建签名 statements，再做一次 aggregate verify；
- message 规则与 geth `TOPOSTAKE_TX_PATH_V1` 对齐：
  - origin statement；
  - edge sender statement；
  - edge receiver statement。

验证结果：
- valid records 进入 score/reward；
- invalid / unknown relay / malformed path 只计入 invalid evidence metrics，不进入 score/reward；
- Prompt 28 devnet 中 `invalid=0`，真实 block-inline path records 通过 aggregate BLS verification。

### 历史演进

Prompt 14-18 做过早期 evidence root、CL sidecar cache/API/gossipsub 方案；Prompt 25-26 改成 block-inline bounded records 后，sidecar/root/latest fallback 支线已清理。当前主线以 block body inline records 为准。

## Score 与 Proposer 选举

Score 只来自已经被 block-inline records 接受、并且经过 finalized gate 的 path evidence。

### Path Contribution

path 语义：

```text
path = [v0, v1, ..., vm]
```

其中：
- `v0` 是 origin relay；
- `vm` 是 proposer/receiver 端；
- relay credit set 是 `{v1, ..., v(m-1)}`。

direct path 不给 relay 贡献：

```text
m <= 1 => relay contribution = 0
```

每笔 tx 的 path budget：

```text
B_e(m) = min(1, D_e / m) * lambda_e^(m-1)
```

intermediate relayers 按 positional weights 分配：

```text
gamma(v_k, p) = B_e(m) * alpha_k^(m,e)
```

当前实现使用 deterministic fixed-point arithmetic。

### Finality Gate

未 finalized 的 path 不能影响 proposer selection。

当前 score settlement 条件：

```text
evidence_epoch + evidence_finality_depth <= finalized_epoch
```

因此：
- path 先进入 raw contribution / pending fee ledger；
- finalized 后才结算成 score；
- reorg 或 evidence 缺失不会提前影响 proposer duties。

### Saturation 与 EMA

raw contribution `A_i(e)` 先经过 stake-scaled logarithmic saturation：

```text
C_i(e) = S_i(e) * log(1 + A_i(e) / (K * S_i(e)))
```

再进入 EMA：

```text
Score_i(e) = beta * C_i(e) + (1 - beta) * Score_i(e-1)
```

实现状态：
- `raw_contributions`：记录 `A_i(e)`；
- `saturated_contributions`：记录 `C_i(e)`；
- `scores`：记录 finalized 后的 EMA `Score_i(e)`。

### Proposer Selection

论文版 bounded bonus：

```text
C_hat_i = Score_i / sum_j Score_j
S_hat_i = effective_balance_i / total_active_balance
b_i = min(b_max, max(C_hat_i / S_hat_i - 1, 0))
W_i = effective_balance_i * (1 + eta * b_i)
```

安全边界：
- 只改 proposer selection weight；
- 不改 attestation weight；
- 不改 finality voting weight；
- 不改 validator effective balance；
- `ETA_SCALED=0` 时退化为普通 PoS。

当前状态：
- 机制骨架已实现；
- direct path、padding、duplicate tx、unfinalized path 都有本地测试覆盖；
- devnet 已能在 finalized 后产生 score/reward 相关 metrics；
- 论文实验仍需要系统采集 proposer frequency、score share 与 topology centrality 的关系。

## Reward 分配

目标是按论文语义做 finalized 后的 relay reward settlement，而不是在 tx execution 时提前分账。

### Fee Budget

每笔 accepted tx path 的 budget 来自 committed priority fee input。

当前实现中：
- geth evidence JSON 提供 `priority_fee_wei = gas_used * effective_gas_tip`；
- Lighthouse block production 将它写入 block-inline `topostake_evidence_records.priority_fee_wei`；
- block processing 再用该值作为 settlement budget；
- zero-fee path 仍可产生 score contribution，但不会凭空生成 settlement payout。

Prompt 27 修复点：
- 初次复测发现 block-inline path record 已出现，但 `priority_fee_wei=0`；
- 根因是 geth `engine_getPayload` 附加 evidence 时没有传 receipts，无法计算 `gas_used * effective_gas_tip`；
- 修复后 `Payload` 保存 full block receipts，`attachTopoStakeBlockEvidence` 用 receipts 构造 evidence。

### Fee Split

当前分账语义：

```text
proposer_amount = theta * fee
relay_budget = (1 - theta) * fee
relay_amount_i = relay_budget * gamma(v_i, p)
burned = relay_budget - sum(relay_amount_i)
```

direct path：

```text
relay_amount = 0
burned = relay_budget
```

守恒要求：

```text
proposer + relay + burned == total_topostake_fee_budget
topostake_fee_conservation_violation == 0
```

### Escrow / System Address

当前采用 escrow/system-address 路线：

```text
0x0000000000000000000000000000000000705000
```

当 `TOPOSTAKE_FEE_ESCROW=1` 时：
- tx execution 阶段，priority fee 不直接进入 coinbase；
- 可分配 fee 进入 TopoStake escrow/system address；
- finalized 后根据 settlement records 从 escrow 分给 proposer / relay payout address；
- burned share 从 escrow 扣除但不加给任何地址。

### Settlement Commitment

早期 CL -> EL 本地 RPC side effect 会造成 state root mismatch，因为不同 EL 可能在不同高度执行 settlement。

当前修正：
- Lighthouse finalized 后生成 deterministic settlement payload；
- geth preload settlement records，并计算 settlement root；
- proposer 构块时把 32-byte settlement root 写入 execution payload/header `extraData`；
- EL state transition 只执行当前 block 明确承诺的 settlement root；
- verifier/import 也只按 block-visible root 执行 payout；
- import 成功后才标记 root executed，避免重复执行。

当前边界：
- settlement records 仍通过 devnet-minimal preload/RPC 到达 EL；
- block 只承诺 root；
- 若未来要协议化，需要为 settlement records 定义正式 data availability / req-resp / gossip 路径。

### 已验证结果

Prompt 27 devnet：
- nonzero `priority_fee_wei` records：`8`
- per-record fee：`42000000000000 wei`
- inline fee sum：`336000000000000 wei`
- Prometheus aggregate budget：`1344000000000000`
- relay amount 非零；
- conservation violation 为 0。

Prompt 28 devnet：
- non-empty records：`14`
- nonzero fee records：`14`
- inline fee sum：`588000000000000 wei`
- valid evidence aggregate：`56`
- invalid evidence aggregate：`0`
- settled records aggregate：`56`
- pending aggregate：`0`
- conservation violation 为 0。

8-node / 1-validator smoke：
- block-inline records：`32`
- priority fee sum：`1344000000000000 wei`
- relay payout 非零；
- conservation violation 为 0。

## 网络拓扑实现

网络拓扑是实验层，不应该混进 TopoStake 协议核心逻辑。协议核心只要求：
- path metadata 随交易传播；
- proposer 将当前 payload 的 path records 写入 block；
- finalized 后 score/reward 按 block-inline records 结算。

拓扑实验层负责控制交易会经过哪些 EL peer，从而生成不同 path 分布。

### 控制方式

优先不改 geth 底层转发逻辑，而是控制 EL peer graph：
- 关闭/绕开 full-mesh discovery；
- 使用 geth `admin_addPeer` / `admin_removePeer` 应用目标 edge list；
- 用 runner 检查实际 peer graph 是否匹配目标拓扑。

4-node linear smoke：

```text
EL1 <-> EL2 <-> EL3 <-> EL4
```

目标 peer count：

```text
EL1 = 1
EL2 = 2
EL3 = 2
EL4 = 1
```

8-node BA(m=2) smoke 中 peer counts：

```text
[3, 6, 6, 2, 2, 3, 2, 2]
```

### Runner

入口：
- `experiments/topostake_devnet_runner.py topology`：生成 deterministic edge list；
- `experiments/topostake_devnet_runner.py apply`：对运行中的 Kurtosis devnet 应用拓扑；
- `experiments/topostake_devnet_runner.py collect`：只采集 block/path/Prometheus 证据；
- `experiments/topostake_devnet_runner.py run`：应用拓扑、发 workload、等待 finality、采集证据并落盘。

已支持拓扑：
- `linear`
- `ring`
- `star`
- `er`
- `random_regular`
- `ba`

已采集指标：
- target/observed peer graph；
- inclusion delay；
- tx success；
- block-inline path records；
- path length histogram；
- relay counts；
- priority fee sum；
- finality；
- missed slots；
- TopoStake Prometheus metrics。

输出：

```text
results/raw/devnet_topology/<run-id>/summary.json
results/raw/devnet_topology/<run-id>/block_records.csv
```

### Workload 口径

`single` origin：
- 只从一个 EL RPC 发交易；
- 适合观察自然 path expansion；
- 只用于专门的 single-entry 对照，不作为主实验默认入口。

`round_robin` / `random` origin：
- 适合多入口实验；
- 主实验默认使用 `round_robin`，让交易入口覆盖当前 devnet 的所有 EL；
- 任意节点数 `n` 下，sender 数、发送并发、receipt 并发都应默认等于 `n`；
- 不能用单 sender 连续 nonce 分散到多个 EL，否则会引入账户 nonce gap；
- runner 已把 `--sender-count 0 --send-concurrency 0 --receipt-concurrency 0` 解释为自动等于当前 EL 节点数；
- summary 会记录 `origin_counts` / `success_origin_counts`，每轮实验必须检查各 EL 入口交易数是否均匀。对于不能被 `n` 整除的 tx count，各节点最多只应相差 1 笔。

延迟口径：
- 旧的 `send -> receipt query returns` 是 observed receipt latency，会被 `--wait-receipts-after-send` 放大；
- 论文应使用 `included_block_timestamp - send_unix` 的 inclusion delay；
- runner 保留 `send_slot_estimate`、`included_slot`、`inclusion_delay_slots` 作为辅助字段，但 `inclusion_delay_seconds` 使用真实秒级时间差。

## 实验进展

这一节只归纳目前进展，不作为最终论文实验结论。实验部分仍需要重跑和稳定。

### 复现命令与构建

构建 geth：

```bash
cd /home/wujian/pog-rs/ethereum-topostake/go-ethereum-topostake
GOCACHE=/tmp/pog-go-build-cache GOTMPDIR=/tmp make geth
```

构建 Lighthouse minimal binary：

```bash
cd /home/wujian/pog-rs/ethereum-topostake/lighthouse
cargo build --release --bin lighthouse --features spec-minimal
```

打包镜像：

```bash
cd /home/wujian/pog-rs
GETH_BINARY=/home/wujian/pog-rs/ethereum-topostake/go-ethereum-topostake/build/bin/geth \
  ./scripts/geth_image.sh package-local

LIGHTHOUSE_BINARY=/home/wujian/pog-rs/ethereum-topostake/lighthouse/target/release/lighthouse \
  ./scripts/lighthouse_image.sh package-local
```

生成 8-node args：

```bash
cargo run --bin topostake_relay_registry -- \
  --count 8 \
  --public-out results/processed/topostake_relay_key_registry_8.json \
  --private-out results/raw/topostake_relay_keys_private_8.json

python3 scripts/topostake_devnet_args.py \
  --mode topostake \
  --count 8 \
  --validator-count 1 \
  --maxpeers 8 \
  --label topostake-8node-1validator \
  --public-registry results/processed/topostake_relay_key_registry_8.json \
  --private-registry results/raw/topostake_relay_keys_private_8.json \
  --out results/raw/topostake-devnet-8node-1validator-minimal.yaml
```

启动前清理旧 enclave：

```bash
XDG_DATA_HOME=/tmp/kurtosis-data kurtosis enclave rm -f <old-enclave-name>
```

### Prompt 26-28 协议验证

Prompt 26 clean inline-only：
- workload：`32` tx sent to EL1，receipts `32/32`
- non-empty records：`25`
- path lengths：`2 / 3 / 4`
- finalized epoch：`15`
- settled aggregate：`100`
- pending aggregate：`0`
- relay amount 非零；
- conservation violation 为 0；
- old sidecar/latest/root entrypoints 均不可用。

Prompt 27 real priority fee reward：
- workload：`16` tx，receipts `16/16`
- nonzero fee records：`8`
- per-record fee：`42000000000000 wei`
- inline fee sum：`336000000000000 wei`
- relay amount 非零；
- conservation violation 为 0。

Prompt 28 aggregate BLS verification：
- workload：`16` tx，receipts `16/16`
- non-empty records：`14`
- nonzero fee records：`14`
- invalid evidence：`0`
- settled aggregate：`56`
- pending aggregate：`0`
- budget/proposer/relay/burned 守恒。

### Prompt 29 topology runner

4-node linear natural multi-hop：
- target edges：`(0,1), (1,2), (2,3)`
- observed edges：`(0,1), (1,2), (2,3)`
- peer counts：`[1, 2, 2, 1]`
- `matches_target=true`
- records：`8`
- path histogram：`len2=5, len3=1, len4=2`
- priority fee sum：`336000000000000 wei`
- relay counts：`relay1=3, relay2=2`

结论：
- runner 可以复现自然 multi-hop workload；
- 4-node BA(m=1) 在 seed 0 下退化成 linear；
- 真正 BA/hub 实验需要至少 8/16 节点。

### Prompt 30A 8-node mini overhead

配置：
- `8 nodes * 16 validators`
- topology：`BA(m=2), seed=0`
- workload：`64 tx`, `0.25s` interval, `round_robin` origin

原始结果：

| run | tx success | observed receipt throughput | observed receipt p50 | observed receipt p95 | inline records |
| --- | ---: | ---: | ---: | ---: | ---: |
| baseline | `64/64` | `3.14 TPS` | `8.24s` | `15.50s` | `0` |
| TopoStake | `64/64` | `1.16 TPS` | `20.41s` | `36.51s` | `50` |

解释：
- 这张表中的 latency 是 observed receipt latency，不是交易实际进块延迟；
- 该结果不能作为论文延迟结论。

inclusion delay 修正后：

| run | origin mode | tx success | inclusion throughput | inclusion p50 | inclusion p95 | inline records |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `prompt30-topostake-8node-ba-m2-tx32-single-inclusion` | `single` | `32/32` | `3.27 TPS` | `2 slots / 6s` | `2 slots / 6s` | `32` |
| `prompt30-topostake-8node-ba-m2-tx32-roundrobin-inclusion` | `round_robin` | `32/32` | `1.16 TPS` | `4 slots / 12s` | `6.45 slots / 19.35s` | `28` |

结论：
- single origin 下真实进块延迟只有 `1-2 slots`；
- round_robin 变差主要是单 sender 连续 nonce 分散到不同 EL 后产生 nonce gap；
- 后续多入口实验要使用 multiple funded senders。

### Prompt 30B 8-node / 1-validator-per-node

配置：
- enclave：`topostake-devnet-prompt30-topostake-8node-1validator`
- args：`results/raw/topostake-devnet-8node-1validator-minimal.yaml`
- nodes：`8`
- validators：`1 / node`
- topology：`BA(m=2), seed=0`
- workload：`32 tx`, `0.25s` interval, `single` origin

结果：

| tx success | inclusion throughput | inclusion p50 | inclusion p95 | inline records | priority fee |
| ---: | ---: | ---: | ---: | ---: | ---: |
| `32/32` | `2.87 TPS` | `2 slots / 6s` | `2 slots / 6s` | `32` | `1344000000000000 wei` |

post-finality collect：
- scanned slots：`24..88`
- missed slots：`4`
- records：`32`
- nonzero fee records：`32`
- path histogram：`len3=32`
- relay counts：`relay1=6`, `relay2=26`
- conservation violation 为 0；
- relay payout amount 非零。

结论：
- `8 nodes * 1 validator` 可以正常启动、出块并 finalized；
- one node / one validator 的身份映射更贴近论文；
- 后续主实验建议默认使用 `1 validator / node`；
- 吞吐实验如需多入口，应使用 multiple funded senders。

### Prompt 31 8-node BA / 64 TPS smoke

配置：
- enclave：`topostake-devnet-prompt31-topostake-8node-ba64`
- args：`results/raw/topostake-devnet-8node-1validator-minimal.yaml`
- nodes：`8`
- validators：`1 / node`
- topology：`BA(m=2), seed=0`
- workload：`3840 tx`, `single` origin，目标约 `64 tx/s * 60s`

第一轮按理论间隔 `0.015625s` 发送：
- 实际发送窗口：`85.17s`
- 实际发送吞吐：`45.09 TPS`
- 交易全部进链：`3840/3840`
- inclusion p50/p95：`2 slots / 6s`
- 原因：runner 是同步 RPC 逐笔发送，单笔发送开销约 `6ms`，叠加 sleep 后无法达到真实 64 TPS。

第二轮将发送间隔校准为 `0.009s`：

| tx sent | tx included | actual send window | send TPS | inclusion throughput | inclusion p50 | inclusion p95 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `3840` | `3840` | `59.28s` | `64.77 TPS` | `62.13 TPS` | `2 slots / 6s` | `2 slots / 6s` |

链上状态：
- sender latest nonce = pending nonce = `7680`
- txpool pending = `0`，queued = `0`
- inclusion block range：`114..134`
- inclusion slot range：`141..161`
- delay histogram：`1 slot = 1887 tx`, `2 slots = 1953 tx`
- finalized after collect：`finalized_epoch=20`

block-inline path records：
- collect range：`slot 136..177`
- records：`2689`
- nonzero fee records：`2689`
- priority fee sum：`112938000000000000 wei`
- path histogram：`len2=1766`, `len3=923`
- relay counts：`relay1=531`, `relay2=392`

重要观察：
- 交易吞吐和 inclusion delay 这次是有效数据：`3840/3840` 全部进链，p95 为 `2 slots / 6s`；
- path record 不是每笔交易都有：未写 path record 的 `1151` 笔全部来自 proposer 为 node/validator `0` 的 slot；
- 未写 path record 的 slot：`145, 146, 149, 152, 158`，这些 slot proposer 都是 `0`；
- 这符合当前协议语义：空 path 表示发起交易者就是区块打包者，不产生 relay path；只有一个节点的 path 表示该节点是发起者；
- 因此这里不是交易/evidence 丢失，而是 local-origin proposer 的零跳路径口径；
- reward/score 统计时需要把空 path 视为 valid local-origin case，但不应产生 relay reward。

### Prompt 32 16-node BA / 64 TPS smoke

配置：
- enclave：`topostake-devnet-prompt32-topostake-16node-ba64`
- args：`results/raw/topostake-devnet-16node-1validator-minimal.yaml`
- nodes：`16`
- validators：`1 / node`
- topology：`BA(m=2), seed=0`
- workload：`3840 tx`, `single` origin，目标约 `64 tx/s * 60s`

本轮先补了两个 16 节点启动问题：
- ethereum-package 在 `count >= 10` 时服务名使用 `el-01` / `cl-01` 这种 zero-padded 格式，因此 registry 和 EL RPC registry 也必须同步使用 zero-padded service name；
- geth TopoStake 启动时会解析 registry 里的所有 EL service name，16 节点下第一个 EL 启动时其他服务还不存在，Docker DNS 查询会阻塞，导致 Kurtosis health check 超时；已把 service lookup 改成短超时，后续由 refresh 继续补全映射。

运行结果：

| tx sent | tx included | actual send window | send TPS | inclusion throughput | inclusion p50 | inclusion p95 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `3840` | `3840` | `65.91s` | `58.26 TPS` | `55.39 TPS` | `2 slots / 6s` | `2 slots / 6s` |

链上状态：
- sender latest nonce = pending nonce = `3840`
- inclusion block range：`33..55`
- nonempty blocks：`23`
- txs / nonempty block：min `92`, max `233`, mean `166.96`
- delay histogram：`1 slot = 984 tx`, `2 slots = 2856 tx`
- reconstructed after workload：`finalized_epoch=8`
- post-finality collect：`finalized_epoch=9`

block-inline path records：
- records：`3840`
- nonzero fee records：`3840`
- priority fee sum：`161280000000000000 wei`
- path histogram：`len2=765`, `len3=1267`, `len4=1808`
- relay counts：`relay1=1148`, `relay2=1927`, `relay4=460`, `relay5=317`, `relay7=997`, `relay9=34`

重要观察：
- 16-node BA devnet 可以正常启动、出块、finalize，并产生完整 block-inline path / reward evidence；
- 这次目标是 `64 TPS`，但 Python runner 在 16 节点环境下实际只打到 `58.26 TPS`，所以这轮只能记为 16-node 近 64 TPS smoke，不应作为最终 64 TPS 数据；
- runner 在 receipt polling 阶段遇到一次 EL HTTP connection reset，但交易已经全部进链；本轮指标来自链上 nonce、block scan 和 post-finality collect 重建；
- 下一步需要把 workload generator 改成更稳的多 sender / 并发发送或异步发送，保证 16 节点也能真实达到目标 rate。

### Prompt 33 16-node strict topology table

目标：
- 为论文表格 `TopoStake devnet validation and end-to-end overhead across network topologies` 跑同口径数据；
- nodes：`16`
- validators：`1 / node`
- workload：`3840 tx`, `single` origin，发送间隔 `0.009s`
- slot：`3s`
- topologies：`Linear`, `Star`, `ER(degree=2.0, seed=0)`, `BA(m=2, seed=0)`

先修正了 runner 的两个实验稳定性问题：
- receipt polling 增加 retry/backoff，避免 EL HTTP connection reset 导致实验中途崩掉；
- topology apply 改成多轮收敛，重复移除目标外 peer 并补齐目标边；所有 Prompt 33 strict run 的 `matches_target=true`。

严格拓扑运行结果：

| topology | tx included | finalized | valid path records | relay payout | fee violation | throughput | incl. delay p50 / p95 |
| --- | ---: | --- | ---: | --- | ---: | ---: | ---: |
| Linear | `3840/3840` | Yes | `2719` | Yes | `0` | `54.24 TPS` | `12 / 27s` |
| Star | `3840/3840` | Yes | `3445` | No | `0` | `58.66 TPS` | `6 / 9s` |
| ER | `3840/3840` | Yes | `2530` | Yes | `0` | `58.56 TPS` | `9 / 15s` |
| BA | `3840/3840` | Yes | `3840` | Yes | `0` | `54.29 TPS` | `6 / 9s` |

重要观察：
- 原论文表不能预填 `Valid Rec. = Tx`；当前实现里 `Valid Rec.` 更准确地表示 finalized block 中可见的 non-empty block-inline path records；
- local-origin / direct path 不一定产生 relay payout；例如 Star 拓扑里 `single origin = node 0`，而 node 0 是中心节点，路径多为直接传播，没有中间 relay，所以 relay payout 为 No；
- Linear strict run 在本轮 finalized epoch window 内出现 nonzero invalid-path metric；这说明如果论文表要声明所有拓扑 `Invalid Rec.=0`，需要使用 clean devnet + per-run metric delta 重新确认，或者调整 workload origin / path bound / 拓扑参数；
- throughput 和 delay 应使用 inclusion throughput 与 inclusion delay，不使用 receipt latency；receipt latency 主要受 RPC polling 影响。

Prompt 34 local path semantics fix：
- `path=[origin]` / zero-hop local evidence 是合法 path record，不应表现为缺失或异常；
- Lighthouse block production 不再丢弃 `len(path)==1` 的 inline evidence record；
- block processing 会把 `len(path)==1` 计为 valid evidence；
- aggregate signature verification 只要求 `len(path)>=2` 的 relay path 参与签名校验，local path 不需要 relay aggregate signature；
- relay contribution/reward 逻辑保持不变：local/direct path 没有中间 relay，因此不产生 relay payout。

Prompt 35 local path fix 后复跑 16-node topology workload：
- 重新构建 Lighthouse minimal binary，并重新打包 `topostake/lighthouse:dev`；
- 清理旧 enclave 后启动 `topostake-devnet-prompt35-topology-localpath`；
- nodes：`16`
- validators：`1 / node`
- workload：`3840 tx`, `single` origin，发送间隔 `0.009s`
- slot：`3s`
- 每条 accepted record 的 priority fee：`42000000000000 wei`
- 每轮 expected fee sum：`161280000000000000 wei`

复跑结果：

| topology | tx included | finalized epoch | valid path records | nonzero fee records | fee sum | throughput | incl. delay p50 / p95 | path length histogram |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| Linear | `3840/3840` | `9` | `3840` | `3840` | `161280000000000000` | `54.13 TPS` | `9 / 15s` | `len2=231, len3=544, len5=523, len7=445, len8=307, len9=357, len10=218, len11=713, len12=140, len15=362` |
| Star | `3840/3840` | `15` | `3840` | `3840` | `161280000000000000` | `58.07 TPS` | `6 / 6s` | `len2=3840` |
| ER | `3840/3840` | `22` | `3840` | `3840` | `161280000000000000` | `55.18 TPS` | `6 / 9s` | `len2=551, len3=1538, len4=614, len5=753, len6=384` |
| BA | `3840/3840` | `31` | `3840` | `3840` | `161280000000000000` | `55.72 TPS` | `6 / 6s` | `len1=243, len2=1414, len3=1691, len4=492` |

关键结论：
- `path=[origin]` 已经进入 finalized block-inline evidence 口径；BA 复跑中出现 `len1=243`，并且总 record 数仍为 `3840`；
- `Valid Rec.` 现在可以按论文语义写成 finalized block 中合法 path records，包括 local path；
- local/direct path 不产生 relay payout 是正确语义，不应被记为 reward 失败；
- Linear 和 BA 本轮 stdout 显示 `matches_target=true`；
- Star/ER 的 tx/evidence/finality 指标有效，但本轮 stdout 显示 `matches_target=false`。这属于实验层 peer graph 收敛问题，不是协议 path/reward 失败；runner 后续需要把 `matches_target` 和 observed peer counts 写入 `summary.json`，并对拓扑 apply 增加更强 retry/settle。

建议的论文表口径：
- `Throughput`：first included tx 到 last included tx 的 inclusion throughput；
- `Incl. Delay`：transaction submission 到 block inclusion 的 p50 / p95 delay；
- `Valid Rec.`：finalized block 中通过处理并写入 block body 的 path records，包括合法的 local path；
- `Relay Payout`：finalized settlement 后是否存在非零 relay role payout。没有中间 relay 的直接路径不应产生 relay payout。

### 正式论文 devnet overhead 实验设计

目标：
- 用真实 PoS devnet 评估 TopoStake 相对普通 PoS beacon chain 的端到端开销；
- 重点展示 throughput 与 inclusion delay，而不是只展示协议功能是否跑通；
- baseline 和 TopoStake 必须使用同一套 custom geth/Lighthouse devnet stack，避免 stock client 与 fork client 的实现差异污染对比。

Baseline 定义：

```text
PoS-Beacon = 同一套 modified geth/Lighthouse devnet
             关闭 TopoStake evidence generation
             关闭 reward settlement
             关闭 proposer-score adjustment
```

Instrumented baseline：

```text
PoS+PathObs = 同一套 modified geth/Lighthouse devnet
              开启 tx/path co-propagation
              开启 block-inline path records
              关闭 reward settlement
              关闭 finalized score update
              关闭 proposer-score adjustment
```

用途：
- `PoS-Beacon` 是纯普通 PoS 对照，协议可见 path length 为 `N/A`；
- `PoS+PathObs` 用来隔离“只记录 path evidence”的开销，并给 baseline 环境下的 `Avg. Path Len.` 提供实验观测值；
- `TopoStake` 用来评估完整协议，包括 reward、score 和 proposer selection。

TopoStake 配置：

```text
TopoStake = 同一套 modified geth/Lighthouse devnet
            开启 tx/path co-propagation
            开启 block-inline path records
            开启 finalized score update
            开启 reward settlement
            开启 proposer-score adjustment
```

图中只放两条线：

```latex
PoS-Beacon
TopoStake
```

如果单独分析 path recording overhead，可以额外画或制表：

```latex
PoS-Beacon
PoS+PathObs
TopoStake
```

建议 Figure 设计：

| panel | x-axis | y-axis | fixed condition |
| --- | --- | --- | --- |
| (a) | Offered load | Achieved tx/slot | fixed node count, e.g. `8 nodes` |
| (b) | Offered load | Inclusion delay p95 | fixed node count, e.g. `8 nodes` |
| (c) | Number of nodes | Achieved tx/slot | fixed offered load: `60 TPS = 180 tx/slot` |
| (d) | Number of nodes | Inclusion delay p95 | fixed offered load: `60 TPS` |

附加表格指标：
- `Avg. Path Len.`：TopoStake / PoS+PathObs 从 block-inline `path_length_histogram` 计算；
- `PoS-Beacon` 的 `Avg. Path Len.` 记为 `N/A`，因为普通 PoS block 不承诺传播路径；
- 若使用 hop count，则 `Avg. Hops = Avg. Path Len. - 1`，local path `len=1` 对应 `0 hop`。

注意：
- (c)(d) 应该是 `TPS vs nodes` 和 `latency vs nodes`；
- 不要让 (d) 继续做 `latency vs load`，否则会和 (b) 重复；
- 如果本机最多只能稳定到 `8 nodes`，(c)(d) 不要称为 large-scale scalability，改称 `node-count sensitivity`；
- 大规模 scalability 放到后续 calibrated simulation。

LaTeX 图模板：

```latex
\begin{figure*}[t]
\centering
\subfloat[Achieved transactions per slot under increasing load.]{
    \includegraphics[width=0.48\linewidth]{figs/devnet_tps_load.pdf}
}
\subfloat[Inclusion delay under increasing load.]{
    \includegraphics[width=0.48\linewidth]{figs/devnet_delay_load.pdf}
}

\subfloat[Achieved transactions per slot under increasing node count.]{
    \includegraphics[width=0.48\linewidth]{figs/devnet_tps_nodes.pdf}
}
\subfloat[Inclusion delay under increasing node count.]{
    \includegraphics[width=0.48\linewidth]{figs/devnet_delay_nodes.pdf}
}
\caption{End-to-end devnet overhead of TopoStake compared with the PoS-Beacon baseline.
Panels (a) and (b) vary the offered transaction load under a fixed node count.
Panels (c) and (d) vary the number of devnet nodes under a fixed offered load.
Throughput is reported as successfully included transactions per slot.
Delay reports p95 inclusion delay from transaction submission time to included block timestamp.}
\label{fig:devnet-overhead}
\end{figure*}
```

正文模板：

```latex
Figure~\ref{fig:devnet-overhead} compares TopoStake with the PoS-Beacon baseline.
We use the same modified Ethereum client stack for both configurations and disable
TopoStake evidence generation, reward settlement, and proposer-score adjustment in
the PoS-Beacon baseline. This ensures that the comparison isolates the overhead
introduced by TopoStake rather than differences between client implementations.

Figures~\ref{fig:devnet-overhead}(a) and (b) vary the offered transaction load under
a fixed node count. TopoStake achieves throughput close to the PoS-Beacon baseline
across the tested loads, while introducing only a modest increase in p95 inclusion
delay. Figures~\ref{fig:devnet-overhead}(c) and (d) vary the number of devnet nodes
under a fixed offered load. The results show that TopoStake remains stable as the
devnet size increases, with throughput and inclusion delay following the same trend
as the baseline. The remaining gap is primarily caused by TopoStake's additional
path-evidence generation, block inclusion, verification, and settlement logic.
```

建议实验矩阵：

| experiment | values | fixed condition | metric |
| --- | --- | --- | --- |
| load sweep | `60, 120, 180, 240, 300 tx/slot` | `8 nodes`, BA topology | achieved tx/slot, p95 inclusion delay |
| high-load stress | `360, 420, 480 tx/slot` | `8 nodes`, BA topology | bottleneck point, timeout/desync evidence |
| node sweep | `8, 12, 16 nodes` | `180 tx/slot`, BA topology | achieved tx/slot, p95 inclusion delay |

统一参数：
- topology：`BA(m=2)`；
- validators：`1 / node`；
- preset：`minimal`；
- slot：`3s`；
- epoch：`16 slots`；
- workload duration：每个配置压测 `180s`；
- latency metric：p95 inclusion delay，使用 `included_block_timestamp - send_unix`，不使用 receipt latency；
- aggregation：当前阶段每个点只跑 `1 seed`；论文中明确说明这是 single-seed devnet measurement，不画 seed error bars。

执行前需要补齐：
- PoS-Beacon baseline 开关，确保关闭 TopoStake evidence/reward/selection 后仍使用同一套 binary/image；
- multiple funded senders 或 async sender，避免单 sender nonce gap 和同步 RPC 发送瓶颈；
- runner summary 必须持久化 `matches_target`、observed peer counts、missed slots、finalized epoch、included tx count；
- 每次 devnet 启动前清理旧 enclave，避免旧 metrics 污染；
- 每个数据点尽量使用 clean devnet 或严格按 run window 计算 metric delta。

### Node-count sensitivity 设计

剩余两个图用于回答：在同样 workload 下，TopoStake 随真实 PoS devnet 节点数增加时是否保持接近 PoS-Beacon baseline。

固定条件：
- topology：`BA(m=2), seed=0`；
- offered load：`180 tx/slot` (`60 TPS` under 3s slots)；
- workload duration：`180s`；
- slot：`3s`；
- preset：`minimal`；
- validators：`1 / node`；
- sender：固定 `8 funded senders`；
- origin：`round_robin` 分散到当前 devnet 的 `n` 个 EL；
- receipt：`--wait-receipts-after-send`；
- latency：`included_block_timestamp - send_unix` 的 p95 inclusion delay。

节点数：

```text
8, 12, 16 nodes
```

如果 `16 nodes` 在本机上出现明显积压或 timeout，论文主图只画稳定区间，并把 16-node 结果作为 local-devnet resource limit / overload evidence 说明。

图 (c)：`devnet_tps_nodes.pdf`
- x-axis：`Number of nodes`
- y-axis：`Achieved tx/slot`
- 两条线：`PoS-Beacon`, `TopoStake`
- y 轴可先用普通 `0-105%`；如果两条线过于贴近，再改成和 load 图一致的断轴。

图 (d)：`devnet_delay_nodes.pdf`
- x-axis：`Number of nodes`
- y-axis：`p95 inclusion delay (s)`
- 两条线：`PoS-Beacon`, `TopoStake`
- y 轴从 `0` 开始，避免夸大差异。

每个点建议记录：
- `tx_count / tx_success`
- `actual_send_tps`
- `inclusion_throughput_tps`
- `achieved_tx_per_slot = inclusion_throughput_tps * seconds_per_slot`
- `throughput_ratio` as auxiliary diagnostic
- `p50/p95 inclusion delay`
- `missed_slots`
- `matches_target`
- observed EL peer counts
- TopoStake path records / fee records
- optional：CPU/txpool monitor，用来解释异常点。

解释口径：
- 这不是 large-scale scalability，只称为 `node-count sensitivity`；
- 如果 achieved tx/slot 随节点数基本稳定，说明 TopoStake 没有明显放大节点数带来的 devnet overhead；
- 如果 delay 随节点数升高，优先检查 BA peer diameter、EL txpool propagation、CPU 和 missed slots，再判断是否是 TopoStake 协议开销。

### Prompt 36 8-node load sweep / 180s single-seed

目标：
- 开始正式论文 devnet overhead 图的 panel (a)(b)；
- 固定节点数为 `8 nodes`；
- 固定拓扑为 `BA(m=2), seed=0`；
- 每个点压测 `180s`；
- 比较 `PoS-Beacon` baseline 与 `TopoStake`。

资源处理：
- 清理旧 enclave：`topostake-devnet-prompt35-topology-localpath`；
- 生成 `4/6/8/10/12` 节点 baseline/topostake args；
- 先启动 `devnet-overhead-baseline-8node-ba` 跑完整 load sweep；
- baseline 完成后清理该 enclave；
- 再启动 `devnet-overhead-topostake-8node-ba` 跑完整 load sweep。

runner 修复：
- 60 TPS baseline 首次运行时，`eth_sendRawTransaction` 遇到 EL HTTP connection reset，runner 中断；
- 已给 `send_raw_transaction` 增加 retry/backoff；
- 同一笔 signed raw tx 的 hash 是确定的，如果重试时返回 `already known` 或 `nonce too low`，按前一次发送已被 EL 接受处理；
- 修复后 60/80 TPS baseline 和 TopoStake 都完成。
- 100 TPS 单点补跑时发现默认“send 后立刻 wait receipt”会把 offered load 串行化，nonce 进度只有约 `210/18000`；已中断并清理该污染 devnet；
- load sweep 后续必须使用 `--wait-receipts-after-send`，即先按目标间隔发送全部交易，再统一等待 receipts/finality；
- 进一步修复 workload 入口：
  - `--sender-count 8`：使用 8 个 prefunded accounts，避免单账户连续 nonce 成为高 TPS 瓶颈；
  - `--origin-mode round_robin`：交易按 round-robin 发到 8 个 EL RPC，避免单个 EL RPC/txpool 入口成为瓶颈；
  - `--send-concurrency 64 --receipt-concurrency 64`：发送和 receipt 等待并发化；
- Kurtosis ethereum-package 优先使用本机 `/tmp/ethereum-package`，避免 engine 每次从 GitHub clone。

2026-07-07 重跑口径：
- fixed `8 nodes`, `BA(m=2)`, `seed=0`, `180s` per load；
- offered load：`60/120/180/240/300 tx/slot`，对应 3s slot 下 `20/40/60/80/100 TPS`；
- inclusion delay = `included_block_timestamp - send_unix`；
- path/fee records 用本轮 workload 的 tx hash 精确过滤，避免复用 devnet 时 collection window 扫到上一轮尾部。

load sweep 结果：

| mode | offered load | tx included | achieved tx/slot | p50 incl. delay | p95 incl. delay | path records | fee sum |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| PoS-Beacon | `60 tx/slot` | `3600/3600` | `59.55` | `2.52s` | `3.87s` | `0` | `0` |
| PoS-Beacon | `120 tx/slot` | `7200/7200` | `117.76` | `2.57s` | `3.92s` | `0` | `0` |
| PoS-Beacon | `180 tx/slot` | `10800/10800` | `178.59` | `2.53s` | `3.88s` | `0` | `0` |
| PoS-Beacon | `240 tx/slot` | `14400/14400` | `235.70` | `2.55s` | `3.90s` | `0` | `0` |
| PoS-Beacon | `300 tx/slot` | `18000/18000` | `294.20` | `2.54s` | `3.89s` | `0` | `0` |
| TopoStake | `60 tx/slot` | `3600/3600` | `58.48` | `3.17s` | `4.67s` | `3600` | `151200000000000000` |
| TopoStake | `120 tx/slot` | `7200/7200` | `118.34` | `3.11s` | `4.61s` | `7200` | `302400000000000000` |
| TopoStake | `180 tx/slot` | `10800/10800` | `177.56` | `3.12s` | `4.62s` | `10800` | `453600000000000000` |
| TopoStake | `240 tx/slot` | `14400/14400` | `235.64` | `3.13s` | `4.63s` | `14400` | `604800000000000000` |
| TopoStake | `300 tx/slot` | `18000/18000` | `294.79` | `3.16s` | `4.68s` | `18000` | `756000000000000000` |

high-load stress 结果：

| mode | offered load | tx included | achieved tx/slot | p50 incl. delay | p95 incl. delay | path records | fee sum | status |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| PoS-Beacon | `360 tx/slot` | `21600/21600` | `357.28` | `2.55s` | `3.91s` | `0` | `0` | completed |
| PoS-Beacon | `420 tx/slot` | `25200/25200` | `339.93` | `3.83s` | `40.75s` | `0` | `0` | bottleneck |
| PoS-Beacon | `480 tx/slot` | `28800/28800` | `335.04` | `22.15s` | `54.77s` | `0` | `0` | overload |
| TopoStake | `360 tx/slot` | `21600/21600` | `323.07` | `3.54s` | `6.07s` | `21579` | `906318000000000000` | completed, near limit |
| TopoStake | `420 tx/slot` | `25200/25200` | `298.56` | `19.55s` | `58.94s` | `19761` | `829962000000000000` | bottleneck |
| TopoStake | `480 tx/slot` | incomplete | timeout | timeout | timeout | incomplete | incomplete | overload timeout |

160 TPS TopoStake 诊断：
- runner 等待 receipt 超过 `480s`，某笔 tx 未进入链；
- 中断前 EL 状态显示部分节点明显落后：EL3 在 block `243`、EL8 在 block `200`，其他节点约 block `504`；
- EL8 txpool 有约 `0x1400` pending 和 `0x200` queued；
- CL 大部分节点仍在 finalizing，说明不是全网 finality 崩溃，而是高负载下部分 EL/entry 节点积压和落后；
- 该点不应作为正常 throughput datapoint，只能作为 overload/bottleneck evidence。

120 TPS TopoStake 瓶颈诊断复跑：
- run id：`diagnose-topostake-8node-ba-load120-180s-seed0`
- monitor：`results/raw/devnet_overhead/diagnose-topostake-8node-ba-load120-180s-seed0-monitor.jsonl`
- actual send TPS：`119.31`，说明 Python workload 注入基本打满目标，不是主要瓶颈；
- inclusion TPS：`111.76`，p95 inclusion delay：`12.28s`；
- workload 发送阶段 Docker CPU：EL+CL+VC 总 CPU 平均约 `829.7%`，峰值约 `1325.4%`；
- workload 发送阶段 EL CPU 平均约 `655.1%`，峰值约 `869.9%`；
- 单个容器 CPU 峰值约 `154.1%`，主要来自 geth EL；
- workload 发送阶段 txpool pending 总量平均约 `2799.5`，峰值约 `7065`，queued 峰值 `211`；
- EL block lag 最大 `1`，CL head lag 最大 `1`，missed slots 为 `0`；
- 发送结束后 txpool 很快清空，CPU 回落。

结论：
- `120 TPS` 点不是 Python 发送端瓶颈；
- 也不是共识/finality 已经崩掉，因为 EL/CL head 基本同步，missed slots 为 0；
- 更像是本机 8-node devnet 中 geth EL/txpool/TopoStake evidence 处理接近上限，短时间积压导致 inclusion throughput 低于 offered load；
- 因此 `120 TPS` 可以作为主图里的 near-limit 点，但论文正文应说明这是本机 devnet 的压力边界，不是协议理论吞吐上限。

20-100 TPS 正常区间所有 run：
- `matches_target=true`；
- `tx_success == tx_count`；
- TopoStake `path records == tx_count`；
- TopoStake fee records 全部非零；
- inclusion delay 口径为 `included_block_timestamp - send_unix`，即交易发起到被打包 block timestamp 的真实秒级差值；
- `inclusion_delay_slots` 仅保留为粗粒度辅助口径，不用于论文图。

初步结论：
- 在 8-node BA devnet 上，TopoStake achieved tx/slot 与 PoS-Beacon 基本一致；
- TopoStake 的 p95 inclusion delay 比 PoS-Beacon 增加约 `0.69-0.80s`；
- TopoStake 的 p50 inclusion delay 比 PoS-Beacon 增加约 `0.56-0.65s`；
- 修复 multi-sender + multi-entry 后，`240/300 tx/slot` 不再塌到约 `180 tx/slot`，说明之前低吞吐主要是 workload 注入瓶颈，不是链处理能力；
- 当前 `300 tx/slot` 下 PoS-Beacon 和 TopoStake 都能达到约 `294 tx/slot`，TopoStake 额外开销主要体现在亚秒级 inclusion delay 增量。
- 当前 8-node BA high-load stress 显示瓶颈在 `360-420 tx/slot` 区间出现；`420 tx/slot` 时两组都开始积压，但 TopoStake 更早出现 evidence coverage 下降和更高 p95 delay；
- `480 tx/slot` 已超过当前本机 devnet 的稳定测量区间，不建议放进主图作为完成点，可在正文/脚注说明为 overload stress。

已生成图：
- `analysis/plot_devnet_overhead.py`
- `figures/devnet_tps_load.pdf`：x 轴为 `Offered load (tx/slot)`，y 轴为 `Achieved tx/slot`
- `figures/devnet_delay_load.pdf`
- 对应 PNG 预览：`figures/devnet_tps_load.png`, `figures/devnet_delay_load.png`
- load 图只画 `60/120/180/240/300/360 tx/slot`；`420/480 tx/slot` 只作为 high-load stress 表格记录，不进入主图。

旧版已生成但暂不进入论文主图：
- `figures/devnet_tps_nodes.pdf`
- `figures/devnet_delay_nodes.pdf`

原因是这组图来自 Prompt 37 的 `60 TPS = 180 tx/slot` 高负载尝试，`12/16 nodes` 出现明显积压，不能和低负载稳定区间混在一起作为正常 overhead 曲线。新的 Prompt 38 已改成 `32 tx/slot + 5 epoch warmup`，可作为 node-count sensitivity 主图候选，但需要重新生成对应 figure。

### Prompt 37 node-count sensitivity attempt

目标：固定 `BA(m=2), seed=0, 60 TPS, 180s, 1 validator / node`，把节点数改成 `8, 12, 16` 跑一轮，观察本机 devnet 的节点数敏感性。该小节是高负载历史尝试，已被 Prompt 38 的低负载 warmup 实验补充。

本轮有效结果：

| mode | nodes | tx included | achieved TPS | throughput ratio | p50 incl. delay | p95 incl. delay | status |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| PoS-Beacon | `8` | `10800/10800` | `59.53` | `99.22%` | `2.53s` | `3.88s` | completed |
| TopoStake | `8` | `10800/10800` | `59.19` | `98.65%` | `3.12s` | `4.62s` | completed |
| PoS-Beacon | `12` | `10800/10800` | `50.79` | `84.65%` | `3.92s` | `30.12s` | completed, delayed |
| TopoStake | `12` | incomplete | timeout / no summary | -- | -- | -- | runner hung after send/finality wait; not a valid datapoint |
| PoS-Beacon | `16` | `10800/10800` | `18.67` | `31.11%` | `95.10s` | `362.52s` | completed, overload |
| TopoStake | `16` | not run | -- | -- | -- | -- | skipped because 12-node TopoStake hung and 16-node baseline was already overloaded |

观察：
- `12 nodes` baseline 已经出现明显排队，说明节点数增加后，在当前 BA peer graph、entry round-robin、8 sender、60 TPS 参数下，传播/txpool/本机资源会放大 inclusion delay；
- `16 nodes` baseline 虽然最终全部 included/finalized，但 p95 delay 达到 `362.52s`，已经不适合作为正常 overhead 对比点；
- TopoStake 12-node 本轮没有生成有效 summary，不能和 baseline 做数值对比；
- 因此这组 `60 TPS` node-count 图不应作为正常 overhead 主图；如果保留，应作为 high-load stress/overload evidence。低负载稳定曲线见 Prompt 38。

### Prompt 38 warmup node-count sensitivity

目标：把节点数敏感性实验改成更温和且更符合 TopoStake 语义的配置，先 warmup 让 score/reward evidence 进入 finalized state，再只测一个 epoch 的正式 workload。

实验参数：
- topology：`BA(m=2), seed=0`
- nodes：`8, 12, 16`
- validators：`1 validator / node`
- slot/epoch：`3s slot`, `16 slots/epoch`
- warmup：`5 epochs = 2560 tx`, `32 tx/slot`
- measurement：`1 epoch = 512 tx`, `32 tx/slot`
- sender/origin：`sender_count = node_count`, `origin_mode = round_robin`
- modes：
  - `PoS-Beacon`：同一套 modified geth/Lighthouse binary，但关闭 TopoStake evidence/reward/selection。
  - `PoS+PathObs`：开启 tx/path co-propagation 与 block-inline path records，关闭 fee escrow，`ETA=0`，用于隔离 path observation overhead。
  - `TopoStake`：开启 path evidence、fee escrow/finalized settlement、score update 与 proposer-score adjustment。

执行中修复：
- 首轮 registry 误用 `--validators`，而 `topostake_relay_registry` 实际参数是 `--count`，导致 registry fallback 到默认 `4 relays`。
- 这个问题会让 `8 nodes` 只记录部分 evidence，`12/16 nodes` 几乎没有 evidence。
- 已改用 `--count 8/12/16` 重新生成 registry 和 args，并重跑 `PoS+PathObs / TopoStake`。
- `12/16 nodes` 的 service name 使用 zero-padded `el-01...el-16` / `cl-01...cl-16`，registry 和 EL RPC registry 均已匹配。

统计口径：
- Throughput：`inclusion_throughput_tps * 3s`，即 achieved tx/slot。
- Inclusion delay：`included_block_timestamp - send_unix`，只统计 measurement 512 笔交易。
- Avg. Path Len.：从 block-inline records 中按 measurement tx hash 过滤后计算，避免 pre-scan slot 混入 warmup 尾部 records。
- `PoS-Beacon` 没有 path evidence，因此 Avg. Path Len. 记为 `N/A`。

修复后结果：

| mode | nodes | tx included | achieved tx/slot | p50 incl. delay | p95 incl. delay | path records | avg path len |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| PoS-Beacon | `8` | `512/512` | `30.57` | `2.52s` | `3.88s` | `0` | N/A |
| PoS+PathObs | `8` | `512/512` | `31.32` | `2.97s` | `4.38s` | `512` | `2.225` |
| TopoStake | `8` | `512/512` | `29.93` | `3.05s` | `4.64s` | `512` | `2.271` |
| PoS-Beacon | `12` | `512/512` | `31.88` | `2.44s` | `3.84s` | `0` | N/A |
| PoS+PathObs | `12` | `512/512` | `30.22` | `3.32s` | `4.91s` | `512` | `2.732` |
| TopoStake | `12` | `512/512` | `29.36` | `3.33s` | `4.83s` | `512` | `2.725` |
| PoS-Beacon | `16` | `512/512` | `31.05` | `2.52s` | `3.91s` | `0` | N/A |
| PoS+PathObs | `16` | `512/512` | `31.19` | `3.40s` | `4.95s` | `512` | `2.918` |
| TopoStake | `16` | `512/512` | `29.92` | `3.36s` | `4.92s` | `512` | `2.828` |

观察：
- 低负载 `32 tx/slot` 下，`8/12/16 nodes` 全部 finalized，并且三种模式都能完整包含 `512/512` measurement transactions。
- `PoS+PathObs` 相比 `PoS-Beacon` 的主要成本体现在 p95 inclusion delay 增加约 `0.5-1.1s`，说明 path evidence 生成和 block-inline inclusion 是主要可观测开销来源。
- `TopoStake` 相比 `PoS+PathObs` 的吞吐略低但同量级，p95 inclusion delay 基本持平；在这组低负载参数下，reward settlement 和 proposer-score adjustment 没有造成明显额外排队。
- Avg. Path Len. 随节点数增加而增大，符合 BA 拓扑下多入口传播路径变长的直觉。
- 本轮是 single seed，不能作为最终 error-bar 图；但它已经说明当前本机可以稳定跑 `8/12/16` 的低负载 node-count sensitivity。

### Prompt 39 uniform 50ms devnet delay

目标：在 Prompt 38 的 `16 nodes, BA(m=2), 32 tx/slot, 5 epoch warmup + 1 epoch measurement` 基础上，对所有 EL/CL 容器统一加入 `50ms` Linux `tc netem` delay，观察网络延迟下 `PoS-Beacon / PoS+PathObs / TopoStake` 的变化。

实现方式：
- 新增 `experiments/apply_devnet_netem.py`。
- 启动 Kurtosis devnet 后，通过 `kurtosis enclave inspect` 获取 service names，再映射到 Docker containers。
- 使用宿主机 `sudo -n nsenter -t <pid> -n tc qdisc replace dev eth0 root netem delay 50ms` 给容器 `eth0` 加 delay。
- 本轮作用对象是全部 `el-*` 与 `cl-*` 容器，共 `32 containers`。

注意：
- 这是 devnet-level uniform container delay，不是严格 per-edge P2P delay。
- 它会同时影响 EL P2P、CL P2P、CL HTTP/RPC、Engine API 等容器出入口流量。
- 因此这轮适合作为 delay stress / implementation bottleneck 观察，不宜直接等同于论文里理想化的 “edge latency graph”。

本轮完成结果：

| mode | nodes | delay | tx included | achieved tx/slot | p50 incl. delay | p95 incl. delay | path records | avg path len | peer graph |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| PoS-Beacon | `16` | `50ms` | `512/512` | `30.90` | `2.74s` | `4.15s` | `0` | N/A | matched |
| PoS+PathObs | `16` | `50ms` | `512/512` | `28.81` | `3.72s` | `5.50s` | `512` | `2.854` | not matched |
| TopoStake | `16` | `50ms` | incomplete | timeout | -- | -- | incomplete | -- | unstable / EL divergence |

TopoStake 失败诊断：
- `TopoStake + 50ms` 在 measurement receipt wait 阶段超时，`receipt-timeout=360s`。
- 查询 still-running devnet 时发现 EL 视图明显分化：
  - 部分 EL 已到 block `173`；
  - 部分 EL 仍在 block `130` / `117` / `82`；
  - 一个 EL 仍有 `pending=508`；
  - CL head slot 约 `304`，finalized epoch 为 `9`。
- 失败交易在多数 EL 上能查到 receipt，但不同 EL 返回的 block number 不一致，说明这不是简单 RPC polling 慢，而是全容器 delay + TopoStake workload 下出现了明显 EL propagation/sync divergence。

观察：
- `50ms` uniform delay 下，PoS-Beacon 仍能完成 `512/512`，p95 从无 delay 的 `3.91s` 增至 `4.15s`。
- `PoS+PathObs` 完成 `512/512`，但 p95 从无 delay 的 `4.95s` 增至 `5.50s`，且 peer graph 未完全匹配目标 BA；说明延迟会放大 topology maintenance 与 path evidence 的额外成本。
- `TopoStake` 在本轮未形成有效完成点；这提示当前实现的 evidence/settlement/proposer-score pipeline 在全容器 delay 下可能放大 EL 同步不一致，后续需要区分：
  - delay 作用范围过宽，影响了 CL HTTP/Engine API/RPC；
  - BA peer graph 在 delay 后未完全稳定；
  - block production 时 evidence verification / settlement 处理导致 proposer 更容易错过 slot；
  - runner receipt 只按 origin EL 等待，在 EL divergence 时会放大 timeout。

下一步建议：
- 先做更干净的 delay 注入：只作用 EL P2P 端口，避免影响 CL HTTP/RPC/Engine API。
- delay sweep 从 `10ms / 25ms / 50ms` 开始，不要直接只看 50ms。
- runner 需要记录 missed slots、per-EL head block、per-EL txpool status，并在 receipt timeout 时自动从所有 EL 查询 tx receipt。
- 若要论证 TopoStake 在网络延迟下变好，优先展示 `score/proposer share/topology centrality/path length` 等机制指标；吞吐和 delay 需要在更可控的 per-edge delay 环境下重新跑。

### Prompt 40 EL P2P-only 50ms delay sanity

目标：验证更干净的 delay 注入方式，只延迟 EL P2P 端口，不污染 workload RPC、Engine API、CL HTTP/RPC。

实现更新：
- `experiments/apply_devnet_netem.py` 增加 `--mode p2p-port`：
  - root qdisc 使用 `prio`；
  - `netem delay 50ms` 挂在 `1:3`；
  - `tc filter u32` 只匹配 `sport/dport 30303`；
  - 本轮只作用 `roles=el`，不作用 CL/VC。
- `experiments/apply_devnet_netem.py` 增加 `--mode clear`，用于清除 devnet 容器 qdisc。
- `experiments/topostake_devnet_runner.py run` 增加 `--skip-apply-topology`，用于“先建拓扑，再加 delay，再跑 workload”的流程。

关键发现：
- 如果先加 P2P-only delay，再让 runner apply BA topology，`admin_addPeer` 返回 `true`，但 geth peer graph 不收敛：
  - observed peer counts：`[0, 2, 2, 0, 0, 1, 1, 2]`
  - `matches_target=false`
  - 512/512 仍能 included/finalized，但 p95 inclusion delay 被拉到 `83.63s`，不能作为有效 topology delay 数据。
- 清除 qdisc 后，同一个 devnet 重新 apply BA topology 立即恢复：
  - observed peer counts：`[3, 6, 6, 2, 2, 3, 2, 2]`
  - `matches_target=true`

正确流程：

```text
1. 启动 devnet。
2. apply BA topology，并确认 matches_target=true。
3. 对 el-* 容器应用 P2P-only delay：sport/dport 30303 -> netem 50ms。
4. workload runner 使用 --skip-apply-topology，只检查现有 peer graph，不再重建拓扑。
```

PoS-Beacon sanity 结果：

| mode | nodes | topology | delay scope | tx included | achieved tx/slot | p50 incl. delay | p95 incl. delay | peer graph | finalized epoch |
| --- | ---: | --- | --- | ---: | ---: | ---: | ---: | --- | ---: |
| PoS-Beacon | `8` | BA(m=2) | EL P2P `30303` only, `50ms` | `512/512` | `30.05` | `2.69s` | `4.05s` | matched | `32` |

TopoStake warmup 结果：

参数：
- `8 nodes`, BA(m=2), seed 0；
- 先 apply BA topology，确认 `matches_target=true`；
- 再对 `el-*` 容器的 EL P2P `30303` 加 `50ms` delay；
- runner 使用 `--skip-apply-topology`；
- warmup：`5 epochs = 2560 tx`；
- measurement：`1 epoch = 512 tx`, `32 tx/slot`。

结果：

| mode | nodes | topology | delay scope | tx included | achieved tx/slot | p50 incl. delay | p95 incl. delay | path records | avg path len | fee records | fee viol. | peer graph | finalized epoch |
| --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| TopoStake | `8` | BA(m=2) | EL P2P `30303` only, `50ms` | `512/512` | `29.93` | `3.32s` | `5.01s` | `512` | `2.268` | `512` | `0` | matched | `14` |

说明：
- runner raw `record_count=607` 包含 pre-scan 附近额外 block records；按 measurement 512 笔 tx hash 过滤后是 `512` 条 path records。
- filtered path histogram：`{1: 85, 2: 214, 3: 204, 4: 9}`。
- filtered priority fee sum：`21504000000000000 wei`。
- `topostake_fee_conservation_violation` Prometheus sum/max 都为 `0`。
- 与 Prompt 38 无 delay TopoStake 8-node 结果相比，p95 inclusion delay 从约 `4.64s` 增到 `5.01s`；吞吐仍接近 `30 tx/slot`。

结论：
- EL P2P-only delay 是可行的，且不会像 uniform container delay 一样污染 CL HTTP/RPC、Engine API、workload RPC。
- 但 topology 必须先建立并确认，再加 delay；否则 P2P handshake/peer establishment 会被 delay 注入影响，导致 BA graph 不完整。
- TopoStake 在该流程下可以完成 `8-node, BA, 50ms P2P-only delay` 测试；这说明上一轮 uniform container delay 的失败主要来自 delay 作用范围过宽与拓扑建连被干扰，而不是 TopoStake 在延迟下必然无法完成。
- 后续还需补 `PoS+PathObs` 同流程结果，并可做 `10/25/50ms` sweep。

### Prompt 41 10-node topology impact bar charts

目标：做一组专门展示“网络拓扑影响”的 devnet 实验。固定节点数和负载，只改变拓扑，比较 `PoS-Beacon / PoS+PathObs / TopoStake` 三种模式在吞吐达成率、交易打包延迟、交易路径长度上的差异。

实验固定条件：
- 节点数：`10 nodes`
- 所有 topology 都固定为 10 节点；`Linear` 也是 10-node linear chain。
- validator：`1 validator / node`
- slot：`3s`
- epoch：minimal preset，`8 slots`
- workload：`32 tx/slot`
- offered TPS：`10.67 TPS`
- topology seed：`0`
- sender：`10 prefunded senders`
- origin：`round_robin` 分散到 10 个 EL
- sender/concurrency：`sender_count = send_concurrency = receipt_concurrency = 10`；runner 中使用 `0` 自动等于当前节点数。
- measurement：`5 epochs = 40 slots = 1280 tx`
- warmup：
  - `PoS-Beacon`：`3 epochs = 24 slots = 768 tx`
  - `PoS+PathObs`：`3 epochs = 24 slots = 768 tx`
  - `TopoStake`：`5 epochs = 40 slots = 1280 tx`
- 每个 run 都需要 clean enclave；不复用链状态。
- additional services：默认关闭 `Prometheus/Grafana/ethereum-metrics-exporter`。

拓扑：
- `Linear`
- `ER`
- `BA`

ER/BA 参数：
- `ER`: 使用 runner 当前 `degree=2.0`，并通过 `ensure_connected` 保证连通。
- `BA`: 使用 `ba_m=2`。

三种模式：
- `PoS-Beacon`
  - 同一套 modified geth/Lighthouse devnet stack。
  - 关闭 TopoStake evidence、reward settlement、proposer-score adjustment。
  - 不记录 path evidence，因此 path 图中该模式标为 `N/A`；如果柱状图必须三组柱，PoS-Beacon 可画为 `0` 并用 hatch/注释说明 `not observed`。
- `PoS+PathObs`
  - 开启 tx/path co-propagation 与 block-inline path records。
  - 关闭 fee escrow / settlement。
  - `ETA=0`，不调整 proposer selection。
  - 用来隔离 path observation overhead。
- `TopoStake`
  - 开启 path evidence、fee escrow / finalized settlement、score update、proposer-score adjustment。

每个 run 的执行流程：

```text
1. 清理旧 enclave。
2. 启动对应 mode 的 10-node devnet。
3. apply 指定 topology，并要求 matches_target=true。
4. 跑 warmup：PoS-Beacon/PoS+PathObs 为 3 epochs，TopoStake 为 5 epochs，均为 32 tx/slot。
5. 等待 warmup finality。
6. 跑 measurement：5 epochs, 32 tx/slot。
7. 等待 measurement finality。
8. 采集 summary.json、block_records.csv、必要时采集容器日志；默认不采集 Prometheus TopoStake metrics。
9. 清理 enclave。
```

注意：
- 本组实验暂时不加额外 network delay；只看拓扑本身的影响。
- 本组使用 `32 tx/slot`，目标是避免 high-load stress 干扰，主要观察 topology 对 path length、inclusion delay 和 achieved tx/slot 的影响。
- TopoStake 需要更长 warmup 来让 finalized evidence 进入 score/selection；PoS-Beacon 与 PoS+PathObs 不使用 score adjustment，因此只保留 3 epochs warmup 做链稳定与 txpool 预热。
- 如果某个 run receipt timeout，保留 partial diagnostics：per-EL head block、txpool pending/queued、CL head/finality、peer graph。

执行备注：
- 曾按旧口径 `warmup=10 epochs` 完成 `baseline-linear` 与 `pathobs-linear` 两个 10-node run；
- 这两个旧结果不和新口径混用；
- 更新脚本后，Prompt 41 已使用 mode-specific warmup 重新开始并完成整轮 `9/9` run。

本轮结果（2026-07-09）：

| Topology | Mode | Tx | Achieved tx/slot | Incl. delay p95 | Avg. path | Path Rec. | Fee Rec. | Missed slots | Finalized epoch | Warmup tx |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Linear | PoS-Beacon | 1280/1280 | 100.9% | 3.82s | 0.00 | 0 | 0 | 0 | 8 | 768 |
| Linear | PoS+PathObs | 1280/1280 | 98.9% | 6.41s | 3.51 | 1280 | 1280 | 0 | 8 | 768 |
| Linear | TopoStake | 1280/1280 | 99.4% | 6.32s | 3.49 | 1280 | 1280 | 0 | 10 | 1280 |
| ER | PoS-Beacon | 1280/1280 | 100.3% | 3.94s | 0.00 | 0 | 0 | 0 | 8 | 768 |
| ER | PoS+PathObs | 1280/1280 | 101.4% | 6.23s | 3.47 | 1280 | 1280 | 0 | 8 | 768 |
| ER | TopoStake | 1280/1280 | 99.2% | 6.03s | 3.34 | 1280 | 1280 | 0 | 10 | 1280 |
| BA | PoS-Beacon | 1280/1280 | 102.6% | 3.89s | 0.00 | 0 | 0 | 0 | 8 | 768 |
| BA | PoS+PathObs | 1280/1280 | 103.9% | 4.80s | 2.51 | 1280 | 1280 | 0 | 8 | 768 |
| BA | TopoStake | 1280/1280 | 100.8% | 5.35s | 2.48 | 1280 | 1280 | 3 | 10 | 1280 |

结论：
- 新 warmup 口径生效：PoS-Beacon / PoS+PathObs 的 `warmup_tx_count=768`，TopoStake 的 `warmup_tx_count=1280`。
- 三个 topology、三种 mode 都完成 `1280/1280` measurement tx，finality 正常，当前没有遗留 running enclave。
- TopoStake 的平均 path length 相比 PoS+PathObs 都略短：Linear `3.49 < 3.51`，ER `3.34 < 3.47`，BA `2.48 < 2.51`。
- BA TopoStake 出现 `missed_slots=3`，但没有导致 receipt timeout、finality failure 或 record coverage 下降；后续若论文主图使用该点，需要在多 seed 或更长 measurement 中确认 missed slot 是否稳定存在。

指标定义：

1. `Achieved tx/slot ratio`

```text
achieved_tx_per_slot = inclusion_throughput_tps * seconds_per_slot
achieved_ratio = achieved_tx_per_slot / offered_tx_per_slot
offered_tx_per_slot = 32
```

图中 y-axis 使用百分比：

```text
Achieved tx/slot (% of offered)
```

2. `Inclusion delay`

使用真实 inclusion delay：

```text
included_block_timestamp - send_unix
```

主图建议用 `p95 inclusion delay (s)`，必要时表格补 `p50/p95`。

3. `Average path length`

只统计 measurement 交易：

```text
filtered_path_records = block_records filtered by measurement tx_hash
avg_path_len = mean(path_len)
```

`PoS-Beacon` 不产生 path records，因此 path 图中应标为 `N/A` 或以 `0` hatch bar 表示 “not observed”，不要解释成路径真的为 0。

输出图：

```text
figures/devnet_topology_achieved_ratio.pdf
figures/devnet_topology_delay.pdf
figures/devnet_topology_path_length.pdf
```

图设计：
- x-axis：`Linear`, `ER`, `BA`
- 每个 topology 下三组 bar：
  - `PoS-Beacon`
  - `PoS+PathObs`
  - `TopoStake`
- 三张图分别展示：
  1. achieved tx/slot ratio；
  2. p95 inclusion delay；
  3. average path length。

建议 LaTeX：

```latex
\begin{figure*}[t]
\centering
\subfloat[Achieved transaction throughput.]{
    \includegraphics[width=0.32\linewidth]{figs/devnet_topology_achieved_ratio.pdf}
}
\subfloat[Inclusion delay.]{
    \includegraphics[width=0.32\linewidth]{figs/devnet_topology_delay.pdf}
}
\subfloat[Observed transaction path length.]{
    \includegraphics[width=0.32\linewidth]{figs/devnet_topology_path_length.pdf}
}
\caption{Impact of network topology on an 8-node Ethereum devnet under a fixed offered load of 180 transactions per slot. Throughput is reported as the achieved fraction of the offered load. Inclusion delay is measured from transaction submission time to the timestamp of the including block. Path length is computed from block-inline TopoStake path records for the measurement transactions.}
\label{fig:devnet-topology-impact}
\end{figure*}
```

预期观察：
- Linear 的传播路径最长，可能带来更高 p95 inclusion delay 和更低 achieved ratio。
- ER/BA 应该更接近，因为平均距离更短。
- `PoS+PathObs` 和 `TopoStake` 的 avg path length 应反映 topology 差异；`TopoStake` 可能因为 proposer-score adjustment 让路径略短或分布改变。
- 如果 `TopoStake` path 更短但 delay 更高，需要解释为 path evidence/verification/settlement/proposer-score pipeline 的额外处理成本，而不是传播路径更长。

### Prompt 42 load and node-count bar charts

目标：做另一组 devnet 图，展示固定 BA 拓扑下的负载敏感性与节点数对 path length 的影响。与 Prompt 41 的 topology impact 区分开：Prompt 41 改拓扑，Prompt 42 固定 BA 后改 offered load 或 node count。

全局设置：
- topology：`BA(m=2), seed=0`
- network delay：`0ms`，本组不注入额外延迟。
- slot：`3s`
- epoch：minimal preset，`8 slots`
- validator：`1 validator / node`
- origin：`round_robin`，交易入口均匀覆盖当前 run 的所有 EL；
- sender/concurrency：
  - load sweep 固定 `8 nodes`，自动覆盖 `8` 个 EL；
  - node-count sweep 使用 `sender_count = send_concurrency = receipt_concurrency = node_count`；
  - runner 中可用 `0` 表示自动等于当前节点数；
  - 每轮 summary 需要检查 `origin_counts`，确认所有节点入口交易数均匀。
- warmup：所有模式统一 `3 epochs`
- measurement：所有 run 统一 `5 epochs`
- 每个 run 使用 clean enclave。
- measurement 后必须 wait finality。
- path/fee 统计必须按 measurement tx hash 过滤。

图 1：load sensitivity

固定条件：
- nodes：`8`
- topology：`BA(m=2)`
- warmup：`3 epochs`
- measurement：`5 epochs`

x-axis：

```text
Offered load (tx/slot): 32, 64, 128, 160
```

y-axis：

```text
Included measurement tx ratio
```

两组 bar：
- `PoS-Beacon`
- `TopoStake`

指标：

```text
offered_tx_per_slot in {32,64,128,160}
tx_interval_seconds = 3 / offered_tx_per_slot
measurement_tx_count = offered_tx_per_slot * 8 * 5
warmup_tx_count = offered_tx_per_slot * 8 * 3
included_ratio = tx_success / measurement_tx_count
```

说明：这里不再使用旧的 `achieved_ratio = inclusion_tps * 3 / offered_tx_per_slot`，因为该口径会受 inclusion window 影响并可能超过 `100%`；Prompt 42 load 图统一使用 measurement tx 完成率。

输出：

```text
figures/devnet_load_included_ratio_bar.pdf
```

图 2：node-count path-length sensitivity

固定条件：
- offered load：`32 tx/slot`
- topology：`BA(m=2)`
- warmup：`3 epochs`
- measurement：`5 epochs`

x-axis：

```text
Number of nodes: 6, 9, 12, 16
```

y-axis：

```text
Average transaction path length
```

两组 bar：
- `PoS+PathObs`
- `TopoStake`

指标：

```text
measurement_tx_count = 32 * 8 * 5 = 1280
warmup_tx_count = 32 * 8 * 3 = 768
avg_path_len = mean(path_len) over measurement tx block-inline path records
```

输出：

```text
figures/devnet_nodes_path_length_bar.pdf
figures/devnet_nodes_path_length_line.pdf
```

说明：`PoS-Beacon` 不产生 TopoStake path records，因此 node-count path-length 图只比较 `PoS+PathObs` 与 `TopoStake`。

建议 LaTeX：

```latex
\begin{figure}[t]
\centering
\subfloat[Load sensitivity.]{
    \includegraphics[width=0.48\linewidth]{figs/devnet_load_included_ratio_bar.pdf}
}
\subfloat[Node-count path sensitivity.]{
    \includegraphics[width=0.48\linewidth]{figs/devnet_nodes_path_length_line.pdf}
}
\caption{Devnet sensitivity of TopoStake under varying offered load and node count without additional network-delay injection. Panel (a) fixes the network size to 8 nodes and varies the offered transaction load. The y-axis reports the fraction of measurement transactions included during the run. Panel (b) fixes the offered load to 32 transactions per slot and varies the number of nodes. Path length is computed from block-inline TopoStake evidence records.}
\label{fig:devnet-sensitivity}
\end{figure}
```

Run matrix：

```text
load sensitivity:
  4 loads * 2 modes = 8 runs

node path sensitivity:
  4 node counts * 2 modes = 8 runs

total = 16 runs
```

本轮结果（2026-07-09）：

| Figure | Mode | Nodes | Tx/slot | Tx | Included ratio | Incl. delay p95 | Avg. path | Path Rec. | Fee Rec. | Missed slots | Finalized epoch |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Load | PoS-Beacon | 8 | 32 | 1280/1280 | 100% | 3.88s | 0.00 | 0 | 0 | 0 | 7 |
| Load | TopoStake | 8 | 32 | 1280/1280 | 100% | 4.45s | 2.19 | 1280 | 1280 | 1 | 8 |
| Load | PoS-Beacon | 8 | 64 | 2560/2560 | 100% | 3.87s | 0.00 | 0 | 0 | 0 | 8 |
| Load | TopoStake | 8 | 64 | 2560/2560 | 100% | 4.54s | 2.19 | 2560 | 2560 | 0 | 9 |
| Load | PoS-Beacon | 8 | 128 | 5120/5120 | 100% | 3.87s | 0.00 | 0 | 0 | 0 | 8 |
| Load | TopoStake | 8 | 128 | 5120/5120 | 100% | 4.89s | 2.16 | 5120 | 5120 | 3 | 8 |
| Load | PoS-Beacon | 8 | 160 | 6400/6400 | 100% | 4.10s | 0.00 | 0 | 0 | 1 | 9 |
| Load | TopoStake | 8 | 160 | 6400/6400 | 100% | 4.75s | 2.29 | 6400 | 6400 | 2 | 9 |
| Nodes | PoS+PathObs | 6 | 32 | 1280/1280 | 100% | 4.47s | 2.11 | 1280 | 1280 | 0 | 8 |
| Nodes | TopoStake | 6 | 32 | 1280/1280 | 100% | 4.37s | 2.01 | 1280 | 1280 | 1 | 8 |
| Nodes | PoS+PathObs | 9 | 32 | 1280/1280 | 100% | 4.75s | 2.42 | 1280 | 1280 | 0 | 8 |
| Nodes | TopoStake | 9 | 32 | 1280/1280 | 100% | 4.71s | 2.35 | 1280 | 1280 | 1 | 8 |
| Nodes | PoS+PathObs | 12 | 32 | 1280/1280 | 100% | 4.96s | 2.69 | 1280 | 1280 | 0 | 8 |
| Nodes | TopoStake | 12 | 32 | 1280/1280 | 100% | 5.28s | 2.58 | 1280 | 1280 | 4 | 8 |
| Nodes | PoS+PathObs | 16 | 32 | 1280/1280 | 100% | 4.98s | 2.87 | 1280 | 1280 | 0 | 11 |
| Nodes | TopoStake | 16 | 32 | 1280/1280 | 100% | 5.08s | 2.78 | 1280 | 1280 | 0 | 14 |

高负载 included-ratio probe（2026-07-09）：

| Mode | Nodes | Tx/slot | Tx | Included ratio | Achieved ratio | Incl. delay p95 | Avg. path | Path Rec. | Fee Rec. | Missed slots | Finalized epoch |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| PoS-Beacon | 8 | 192 | 7680/7680 | 100% | 97.84% | 3.91s | 0.00 | 0 | 0 | 0 | 9 |
| TopoStake | 8 | 192 | 7680/7680 | 100% | 97.65% | 4.76s | 2.25 | 7680 | 7680 | 1 | 9 |
| PoS-Beacon | 8 | 224 | 8960/8960 | 100% | 97.48% | 3.89s | 0.00 | 0 | 0 | 0 | 11 |
| TopoStake | 8 | 224 | 8960/8960 | 100% | 97.64% | 4.79s | 2.26 | 8960 | 8960 | 1 | 9 |
| PoS-Beacon | 8 | 256 | 10240/10240 | 100% | 98.26% | 3.88s | 0.00 | 0 | 0 | 0 | 10 |
| TopoStake | 8 | 256 | 10240/10240 | 100% | 96.58% | 4.93s | 2.24 | 10240 | 10240 | 3 | 15 |
| PoS-Beacon | 8 | 288 | 11520/11520 | 100% | 97.18% | 3.91s | 0.00 | 0 | 0 | 0 | 12 |
| TopoStake | 8 | 288 | 11520/11520 | 100% | 97.81% | 4.57s | 2.18 | 11520 | 11520 | 1 | 10 |

结论：
- `included_ratio` 新口径生效：所有 Prompt 42 measurement tx 都成功 included，图 1 不再使用会超过 `100%` 的旧 `achieved_ratio`。
- load sweep 下 TopoStake 在 `32/64/128/160 tx/slot` 均完成 `100%` inclusion；额外 probe 显示 `192/224/256/288 tx/slot` 也仍是 `100%` included。TopoStake p95 inclusion delay 比 PoS-Beacon 高约 `0.6-1.1s`。
- node-count path sweep 下，TopoStake 在 `6/9/12/16` 节点均比 PathObs 短；9-node 重跑后从旧结果 `2.40 > 2.38` 变为 `2.35 < 2.42`，说明之前的 9-node 反例更像 single-run 波动。
- 所有 path/fee records 均按 measurement tx hash 过滤，PathObs/TopoStake 的 Path Rec. 与 Fee Rec. 都等于 measurement tx 数。
- 交易入口覆盖均匀：8 节点每节点 `160/320/640/800`，6 节点 `213-214`，9 节点 `142-143`，12 节点 `106-107`，16 节点每节点 `80`。

Fixed-window achieved TPS probe（2026-07-09）：

目的：把 load 图从 `tx/slot ratio` 口径切换到真实固定窗口吞吐口径。measurement 仍为 `5 epochs = 40 slots = 120s`，offered TPS 转换为 `tx/slot = TPS * 3s`，交易入口继续 round-robin 覆盖 8 个 EL。

计算口径：

```text
window_achieved_tps = measurement tx included by first_send_unix + 120s / 120s
window_achieved_ratio = window_achieved_tps / offered_tps
```

参数：

```text
nodes = 8
topology = BA(m=2), seed=0
slot = 3s
epoch = 8 slots
warmup = 3 epochs
measurement = 5 epochs
modes = PoS-Beacon, TopoStake
offered TPS = 32, 64, 96, 128, 160
```

结果：

| Mode | Offered TPS | Tx/slot | Tx | Window achieved TPS | Window ratio | Actual send TPS | p95 incl. delay | Avg. path | Missed slots |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| PoS-Beacon | 32 | 96 | 3840/3840 | 31.48 | 98.36% | 32.01 | 3.93s | 0.00 | 0 |
| TopoStake | 32 | 96 | 3840/3840 | 31.00 | 96.88% | 32.01 | 4.94s | 2.22 | 2 |
| PoS-Beacon | 64 | 192 | 7680/7680 | 62.59 | 97.80% | 64.00 | 3.94s | 0.00 | 0 |
| TopoStake | 64 | 192 | 7680/7680 | 62.27 | 97.29% | 64.00 | 4.58s | 2.21 | 0 |
| PoS-Beacon | 96 | 288 | 11520/11520 | 94.55 | 98.49% | 96.00 | 3.90s | 0.00 | 0 |
| TopoStake | 96 | 288 | 11520/11520 | 94.53 | 98.47% | 95.99 | 6.77s | 2.23 | 5 |
| PoS-Beacon | 128 | 384 | 15360/15360 | 125.65 | 98.16% | 128.00 | 3.89s | 0.00 | 0 |
| TopoStake | 128 | 384 | 15360/15360 | 123.83 | 96.74% | 127.69 | 4.84s | 2.23 | 1 |
| PoS-Beacon | 160 | 480 | 19200/19200 | 142.77 | 89.23% | 143.90 | 3.90s | 0.00 | 0 |
| TopoStake | 160 | 480 | 19200/19200 | 126.94 | 79.34% | 128.82 | 4.68s | 2.23 | 1 |

输出：

```text
figures/devnet_load_window_achieved_ratio_line.pdf
figures/devnet_load_window_achieved_ratio_line.png
```

结论：
- `32/64/96/128 TPS` 下所有 measurement transactions 最终都成功 included，且 fixed-window achieved ratio 仍接近 `97-98%`；主图使用 fixed-window achieved ratio 作为 y 轴百分比，因为它固定观测窗口，不会被 inclusion span 拉高或超过 100%。
- `160 TPS = 480 tx/slot` 开始暴露本机/workload 注入压力：PoS-Beacon actual send TPS 只有 `143.90`，TopoStake 只有 `128.82`，因此该点可作为 high-load stress 点，但不应解释为纯协议容量上限。
- 低到中负载区间 PoS-Beacon 和 TopoStake 曲线接近；TopoStake 在 `160 TPS` 的 fixed-window ratio 明显更低，主要反映 path evidence、score/selection、settlement pipeline 和本机调度共同带来的额外开销。

### 当前实验缺口

还需要补：
- node-count sweep：当前 `32 tx/slot` + warmup 版本已稳定；若论文主图使用该配置，需要生成对应 `tx/slot vs nodes` 和 `delay vs nodes` 图；
- 高负载 node-count sweep：`60 TPS = 180 tx/slot` 下 12/16 节点曾出现明显积压，后续若要展示高负载敏感性，需要单独作为 overload/stress 图，而不是和低负载稳定图混在一起；
- evidence/path records 的 per-run delta 需要工具化；当前已在分析时按 measurement tx hash 过滤，但 runner summary 仍同时保存了 pre-scan block records；
- delay 实验：EL P2P-only uniform delay sanity 已通过；还需用同一流程补 `PoS-Beacon / PoS+PathObs / TopoStake` 三线，以及更严格的 per-edge delay；
- topology suite：linear/star/ER/BA 已有 strict 16-node smoke；还需补 ring 和多 seed；
- topology table 如果要宣称所有行 `Invalid Rec.=0` / `Relay Payout=Yes`，需要 clean devnet per topology 或 per-run metric delta；
- 多 seed 重复；
- load sweep 目前是 single seed；论文最终版如需 error bar，需要补 seed 重复；
- proposer frequency、score share、relay reward share 与 topology centrality 的对应关系；
- 资源占用和 missed slots；
- finality 稳定性。

### Prompt 映射

```text
Prompt 1-13   环境、Kurtosis、custom Lighthouse image、instrumentation、fixture skeleton
Prompt 14-18  早期 tx gossip metadata、block evidence root、CL sidecar/cache/gossipsub
Prompt 19-21  path contribution、finalized score、paper proposer selection formula
Prompt 22     fee settlement ledger、address identity、64-validator finality smoke
Prompt 23     escrow/system address、real EL payout、settlement root in extraData
Prompt 24     natural multi-hop topology/workload、minimal 3s-slot devnet
Prompt 25     block-inline path records、engine_getPayload evidence
Prompt 26     删除旧 sidecar/latestBlockEvidence path propagation，验证 clean inline-only path
Prompt 27     reward 输入从固定 budget 改为 block-inline committed priority fee
Prompt 28     block-inline path aggregate BLS verification
Prompt 29     reproducible devnet topology experiment runner
Prompt 30     8-node scaling, inclusion-delay correction, 1-validator/node smoke
Prompt 31     8-node BA 64 TPS smoke, local-origin empty-path semantics
Prompt 32     16-node BA 64 TPS smoke, >=10 service name fix, startup DNS timeout fix
Prompt 33     16-node strict topology table, inclusion throughput/delay, table semantics correction
Prompt 34     local path evidence is valid: path=[origin] counts as valid record, no relay payout
Prompt 35     local path fix 后复跑 16-node topology workload，四个拓扑均达到 3840/3840 valid records
Prompt 36     8-node BA load sweep，multi-sender/multi-entry 修复，tx/slot 图
Prompt 37     60 TPS node-count stress，发现 12/16 节点高负载积压
Prompt 38     5-epoch warmup + 32 tx/slot node-count sensitivity，三模式对照与 avg path length
Prompt 39     16-node uniform 50ms delay stress，baseline/pathobs 完成，TopoStake 出现 EL divergence
Prompt 40     EL P2P-only 50ms delay sanity，确认正确流程为先建拓扑再加 delay，并用 --skip-apply-topology 跑 workload
Prompt 41     16-node topology impact bar charts：Linear/ER/BA，32 tx/slot，warmup 10 epochs，measurement 5 epochs，PoS-Beacon/PoS+PathObs/TopoStake 三模式对照
Prompt 42     load/node-count sensitivity charts：load=32/64/128/160 tx/slot，8-node BA，PoS-Beacon vs TopoStake；nodes=6/9/12/16 at 32 tx/slot，PoS+PathObs vs TopoStake；ratio 使用 included_ratio；workload 默认 round_robin 覆盖所有 EL，sender/concurrency 随节点数自动匹配
Prompt 43     protocol-grade settlement records：扩展 geth block body / Engine API ExecutionPayload 与 Lighthouse ExecutionPayload SSZ/JSON，携带 topostakeSettlementRecords，使 finalized settlement 记录跟随区块/EL payload 传播；TopoStake 模式下重新打开真实余额 mutation
Prompt 44     settlement records body recovery fix：getPayloadBodiesByHash/Range 与 Lighthouse ExecutionPayloadBodyV1 保留 topostakeSettlementRecords，修复 16-node ER TopoStake state-root divergence
```

### Prompt 43 验证记录

目标：把 reward settlement 从“CL 通过 RPC 提交到各 EL 的本地内存，然后 EL 按 extraData settlement root 本地执行”升级为协议级 payload 字段。这样 proposer 构造 payload 时把 settlement records 写入 block body / ExecutionPayload，其他 EL 在 `engine_newPayload` 时直接从 payload 读取同一批 records，避免因为某个 EL 没有本地 settlement store 而执行出不同 state root。

实现要点：
- geth `types.Body` / `types.Block` 增加 `TopoStakeSettlementRecords`，RLP body、`ExecutableData` JSON、`ExecutableDataToBlock`、`BlockToExecutableData` 都带上该字段；
- geth block execution 改为 `ApplyCommittedSettlementRecords(root, block.TopoStakeSettlementRecords(), statedb, ...)`，当 `TOPOSTAKE_SETTLEMENT_MUTATION=1` 且 committed root 非空时，缺少 records 会返回 invalid；
- proposer build 时从 pending settlement root 查出 records，先放进 body，再用同一份 records 执行 state mutation；
- Lighthouse `ExecutionPayload` 增加 bounded `topostake_settlement_records` SSZ 字段，Engine API JSON 边界映射 geth 的 `topostakeSettlementRecords`；
- `scripts/topostake_devnet_args.py` 只在 `mode=topostake` 时设置 `TOPOSTAKE_FEE_ESCROW=1` 和 `TOPOSTAKE_SETTLEMENT_MUTATION=1`，`pos/pathobs` 不做真实余额 mutation。

已验证：
- `go test ./eth/topostake ./beacon/engine ./core/types`
- `cargo check -p types -p execution_layer -p beacon_chain`
- `cargo check --bin lighthouse --features spec-minimal`

下一步：重建 geth/Lighthouse dev images，跑 8-node BA TopoStake devnet，确认 finalized 后 settlement records 随 payload 到达所有 EL，且不再出现 `invalid merkle root` / execution payload divergence。

补充验证（2026-07-08）：
- 重建并打包本地 `topostake/geth:dev` 与 `topostake/lighthouse:dev` 后，启动 `prompt43_path_length_16node_topostake_ba_n16_txslot32_seed0`；
- 参数确认：`TOPOSTAKE_FEE_ESCROW=1`、`TOPOSTAKE_SETTLEMENT_MUTATION=1`，即 TopoStake 模式默认开启真实 fee mutation；
- devnet 成功启动 16 EL + 16 CL + 16 VC，BA topology workload 开始后链在 EL block 123 / CL head slot 128 附近停止前进；
- EL/CL 日志显示从 block 124 开始 payload 被拒绝：
  `failed to apply topostake settlement: missing topostake settlement records for committed root ...`；
- 结论：当前 settlement root 已随 block extraData 提交，但 `topostakeSettlementRecords` 没有稳定随最终 CL block / Engine `newPayload` 回到所有 EL；真实余额 mutation 开启后这会导致 execution payload invalid。问题不是资源瓶颈，而是 Prompt 43 的 settlement records payload 传递路径还缺一处闭环。

下一步修复方向：
- 优先确认 geth `engine_getPayload` 返回的 `executionPayload.topostakeSettlementRecords` 是否非空；
- 若 geth 返回非空，则继续查 Lighthouse `GetPayloadResponse -> BlockProposalContents -> BeaconBlockBody execution_payload -> NewPayloadRequest` 是否在 full/blinded payload 转换中丢字段；
- 修复后先跑 8-node BA / 32 tx-slot TopoStake smoke，再回到 16-node BA / 32 tx-slot。

修复结果（2026-07-08）：
- 问题定位：真实 mutation 开启后，EL 在执行 committed settlement root 时过早要求 block payload 一定携带 records；但当前 CL 仍会通过 `topostake_submitSettlement` 预先把 settlement summary 写入本地 EL store。若 `engine_newPayload` 边界 records 为空，应该先按 committed root 查询本地 store，只有 block records 和本地 store 都缺失时才判 invalid；
- geth `ApplyCommittedSettlementRecords` 增加 local-store fallback：`topostakeSettlementRecords` 非空时按 payload records 验 root 并执行；records 为空时按 root 查 `settlementsByRoot`；`TOPOSTAKE_SETTLEMENT_MUTATION=1` 且两边都缺失时仍返回 `missing topostake settlement records...`；
- 新增单测覆盖：
  - records 为空但本地 store 有 settlement 时，真实扣 escrow / 加 payout 成功；
  - records 和本地 store 都缺失时，mutation 模式返回错误；
- 验证通过：
  - `go test ./eth/topostake ./beacon/engine ./core/types`
  - `cargo check -p types -p execution_layer -p beacon_chain`
  - 重建 `topostake/geth:dev` 后跑 8-node BA smoke：512/512 tx included，finalized epoch 17，BA topology match；
  - 复跑 16-node BA / 32 tx-slot / warmup 5 epoch / measurement 5 epoch / `mode=topostake`：
    - `TOPOSTAKE_FEE_ESCROW=1`、`TOPOSTAKE_SETTLEMENT_MUTATION=1`；
    - tx success `2560/2560`；
    - Path Rec. `2560/2560`，Fee Rec. `2560/2560`；
    - achieved `31.59 tx/slot`，ratio `0.987`；
    - inclusion delay p50/p95 `3.78s / 13.63s`;
    - avg path length `3.02`;
    - finalized epoch `14`;
    - fee conservation violation `0`;
    - Kurtosis enclave 已清理，无残留运行资源；
- 结论：当前协议级 settlement records + local-store fallback 已能支撑 TopoStake 默认开启真实 fee mutation 的 16-node BA devnet workload。后续如果要完全去掉 local RPC settlement 依赖，需要继续把 settlement records 的 CL block body / Engine API 往返路径做成唯一来源。

### Prompt 44 settlement records body recovery fix

目标：修复 16-node ER TopoStake 在真实 fee mutation 开启后仍可能出现 `invalid merkle root` / finality 卡住的问题。上一轮定位显示 proposer payload 里有 committed settlement root，但部分 payload body recovery 路径会丢失 `topostakeSettlementRecords`，导致其他 EL 只能依赖本地 fallback，最终同一 payload 执行出不同 state root。

修复内容：
- geth `ExecutionPayloadBody` 增加 `topostakeSettlementRecords` 字段；
- geth `engine_getPayloadBodiesByHashV1/V2` 与 `engine_getPayloadBodiesByRangeV1/V2` 返回 block body 时携带 `block.TopoStakeSettlementRecords()`；
- Lighthouse `ExecutionPayloadBodyV1` 增加 `topostake_settlement_records`；
- Lighthouse Engine API JSON body decode/encode 增加 `topostakeSettlementRecords` 映射；
- Lighthouse `ExecutionPayloadBodyV1::to_payload()` 不再把 `topostake_settlement_records` 置空，而是带入重建后的 `ExecutionPayload`。

验证：
- `cargo check -p execution_layer`
- `GOCACHE=/tmp/go-build-cache go test ./beacon/engine ./core/types ./eth/topostake`
- `GOCACHE=/tmp/go-build-cache go test ./eth/catalyst -run '^$'`
- `eth/catalyst` 完整测试在当前沙箱会因监听 `127.0.0.1:0` 被拒绝，属于环境限制；编译检查已通过。
- 重建本地二进制并重新打包：
  - `topostake/geth:dev`
  - `topostake/lighthouse:dev`
- 复跑 `prompt44_topology_16node_topostake_er_n16_txslot32_seed0`：
  - topology：`ER`
  - nodes：`16`
  - mode：`TopoStake`
  - load：`32 tx/slot`
  - warmup：`5 epochs`
  - measurement：`5 epochs`
  - tx success：`2560/2560`
  - finalized epoch：`21`
  - achieved：`31.44 tx/slot`
  - p50/p95 inclusion delay：`4.18s / 6.53s`
  - avg path length：`3.85`
  - Path Rec. / Fee Rec.：`2560 / 2560`
  - priority fee sum：`107520000000000000 wei`
  - fee conservation violation：`0`
  - topology match：`true`
  - Kurtosis enclave 已清理，无残留运行资源。

结论：这次 ER 16-node TopoStake 已经不再复现 `invalid merkle root`，说明 settlement records 在 Engine payload body recovery 路径中的丢失问题已修复。后续可以继续补 BA/Linear 的完整 Prompt 44 数据，或者回到 Prompt 41/42 六张图的数据重跑。

### Prompt 44 BA 16-node 三模式补充

目标：补齐 `16 nodes, BA(m=2), 32 tx/slot, 5 epoch warmup + 5 epoch measurement` 下的 `PoS-Beacon / PoS+PathObs / TopoStake` 三模式对照数据。

首次复跑 TopoStake BA 时发现一个新的 state-root divergence：
- baseline 与 pathobs 均完成；
- TopoStake 在 slot 54 附近出现 `Invalid execution payload`，EL 报 `invalid merkle root`；
- CL head 继续推进但 finalized 卡在 epoch 4，说明这是 payload validation divergence，不是资源或等待时间问题。

根因：
- geth `executedSettlements` 是本地内存去重；
- 在 BA 拓扑下出现 competing fork / side-chain block replay 时，某个节点可能已经在本地把同一 settlement key 标记为 executed；
- 后续验证另一个携带同一 settlement records 的 block 时，本地 skip 了 settlement mutation，导致 validator 计算出的 state root 和 proposer header root 不一致；
- 这类本地去重不能参与 block validation。只要 block body 携带 `topostakeSettlementRecords`，EL 必须根据 block records 和 pre-state 重新执行，不能被本地 memory marker 污染。

修复：
- geth `ApplyCommittedSettlementRecords` 改为：
  - `blockRecords` 非空时，总是按 block records 验 root 并执行 settlement mutation；
  - 只有 `blockRecords` 为空、走 local-store fallback 时，才允许 `executedSettlements` 跳过；
- 新增回归测试：先用 local fallback 标记 settlement executed，再用 block-carried records 在 fresh state 上 replay，必须仍然执行。

验证：
- `GOCACHE=/tmp/go-build-cache go test ./eth/topostake ./core ./miner ./eth/catalyst`
  - `eth/topostake`、`core`、`miner` 通过；
  - `eth/catalyst` 完整测试在当前 sandbox 因监听 `0.0.0.0:0` / `127.0.0.1:0` 被拒绝失败，属于环境限制，不是编译或 settlement 逻辑失败；
- 重建并打包 `topostake/geth:dev`；
- 复跑 `prompt44_topology_16node_topostake_ba_n16_txslot32_seed0` 成功 finalized。

最终 BA 三模式数据：

| Mode | Tx | Achieved tx/slot | Achieved ratio | Incl. delay p50/p95 | Avg. path | Path Rec. | Fee Rec. | Finalized | Fee Viol. |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| PoS-Beacon | `2560/2560` | `31.62` | `98.81%` | `2.62s / 3.93s` | `0.00` | `0` | `0` | `21` | `0` |
| PoS+PathObs | `2560/2560` | `31.31` | `97.85%` | `3.41s / 4.91s` | `2.86` | `2560` | `2560` | `21` | `0` |
| TopoStake | `2560/2560` | `30.66` | `95.81%` | `3.85s / 9.48s` | `2.89` | `2560` | `2560` | `21` | `0` |

产物：
- summary CSV：`results/processed/devnet_prompt41_42_summary.csv`
- raw summary：`results/raw/devnet_prompt41_42/prompt44_topology_16node_topostake_ba_n16_txslot32_seed0/summary.json`
- Kurtosis enclave 已清理，无残留运行资源。

结论：修复后 BA 16-node TopoStake 在真实 fee mutation 开启下可以完成 workload 并 finalized；Path/Fee records 完整，fee conservation 为 0。TopoStake 相比 PathObs 的 achieved tx/slot 略低，p95 inclusion delay 明显更高，这部分更像 score/settlement/proposer-selection pipeline 在 BA competing fork 场景下的额外开销，后续画图时应保留并解释。

### Prompt 45 BA warm10 no-wait path 对照

目标：验证“更长 warmup、但 warm 后不额外等待”的设置是否能让 TopoStake 在 BA 拓扑下产生更短的 measurement path。只比较 `PoS+PathObs` 和 `TopoStake`，不跑 PoS-Beacon。

参数：
- topology：`BA(m=2), seed=0`
- nodes：`16`
- sender/origin：`16 senders`, `origin_mode=round_robin`
- slot/epoch：`3s slot`, `16 slots/epoch`
- load：`32 tx/slot`
- warmup：`10 epochs = 5120 tx`
- warmup 后额外等待：`0 finalized epoch`
- measurement：`5 epochs = 2560 tx`
- measurement 后等待：`1 finalized epoch`
- fee mutation：TopoStake 模式默认开启真实 fee mutation

结果：

| Mode | Tx | Achieved tx/slot | Incl. delay p50/p95 | Avg. path | Path length histogram | Finalized | Topology |
| --- | ---: | ---: | ---: | ---: | --- | ---: | --- |
| PoS+PathObs | `2560/2560` | `31.57` | `3.51s / 5.11s` | `2.878` | `{1:206, 2:585, 3:1121, 4:613, 5:36}` | `32` | match |
| TopoStake | `2560/2560` | `30.46` | `4.33s / 13.33s` | `2.949` | `{1:193, 2:544, 3:1063, 4:722, 5:39}` | `25` | match |

产物：
- PathObs summary：`results/raw/devnet_warm10_path_compare/prompt45_warm10_pathobs_ba_n16_txslot32_seed0/summary.json`
- TopoStake summary：`results/raw/devnet_warm10_path_compare/prompt45_warm10_topostake_ba_n16_txslot32_seed0/summary.json`
- 两轮 Kurtosis enclave 均已清理，无残留运行资源。

结论：
- 这轮没有支持“TopoStake path 更短”的预期；TopoStake 平均 path 比 PathObs 长 `0.071`，且 p95 inclusion delay 高出约 `8.23s`。
- `warmup 10 epochs` 只能提供更多历史 evidence，但当前 proposer score 使用 finalized-gated historical score，默认 `evidence_finality_depth=1` 时 proposer epoch `E` 读取 `E-2` 的 evidence score；warm 后不额外等待会让 measurement 前半段仍受较早 evidence 影响。
- 更关键的是，当前 score 奖励的是 finalized historical relay contribution，不是直接最小化当前 tx path length。BA 拓扑里 hub already-short path 很强，TopoStake 选出的 proposer 未必就是当前 batch 的最短接收者。
- 若论文目标是“TopoStake 牺牲少量吞吐/延迟，但 path 一定更短”，下一步应调整 selection objective：把 proposer weight 与 candidate proposer 对当前/近期 origin 的 path-distance 或 relay-position score 更直接绑定，而不是只用历史 relay contribution。

### Prompt 46 block-inline aggregate verification coverage fix

问题：
- Prompt 41/44/45 的 TopoStake 数据里，block body 已经携带大量 `path_records`，但 score 覆盖率异常低；
- BA 16-node run 中 `path_records=2560`，但最终只有 validator 7 的一批 evidence 进入 raw contribution / score；
- ER 16-node run 中 `path_records=2560`，但 `valid evidence=0`，导致 proposer score 全 0、proposer weight 全相同，TopoStake selection 实际退化成普通 PoS。

定位：
- `per_block_processing.rs` 的 inline block aggregate verification 是 block-level aggregate，一旦 aggregate 验证失败，就把整个 block 的 inline records 全部记为 invalid；
- geth 侧 block aggregate 会包含 origin-only transaction 的 origin signature；
- Lighthouse 侧 `topostake_inline_record_requires_signature()` 原先只对 `relay_path.len() >= 2` 的 record 重建签名集合，跳过了 `path_len=1` 的 origin-only record；
- 当一个 block 同时包含 `path_len=1` 和 `path_len>=2` records 时，CL 验证的是 aggregate 的子集，而 EL 给的是全集 aggregate，容易导致整块 evidence 被拒绝。

修复：
- Lighthouse inline aggregate verification 改为：所有非空 `relay_path` 都需要参与 aggregate signature verification；
- `path_len=1` record 只重建 origin signature record，不重建 edge signature；
- scoring 语义不变：`path_len=1` 不产生 relay score，因为没有中继边；它只用于让 block-level aggregate 的签名集合与 geth 保持一致。

验证：
- 新增混合 block 测试：同一个 inline block aggregate 同时包含 relayed record `[0,1]` 与 origin-only record `[0]`，验证必须通过；
- 已通过：

```bash
cd ethereum-topostake/lighthouse
cargo test -p state_processing topostake_inline_block_aggregate_verifies_and_rejects_tampering
```

后续：
- 旧 Prompt 41/44/45 的 ER/BA TopoStake score/selection 结论需要在重建 Lighthouse 镜像后重跑；
- 尤其是 ER 数据，修复前不能用于证明 TopoStake score/selection 生效；
- 重跑后需要检查：
  - `path_records == fee_records == tx_count`
  - `topostake_evidence_epoch_valid_paths > 0`
  - `topostake_epoch_score_scaled` 覆盖多个 validator
  - `topostake_proposer_weight_scaled` 出现非均匀权重
  - 高 score/weight validator 的 proposer selection share 是否上升。

### Prompt 47 settlement epoch dedup 与 ER/BA score 验证

目标：在 Prompt 46 修复 inline aggregate verification 后，重跑 `16 nodes, TopoStake, 32 tx/slot, 10 epoch warmup + 5 epoch measurement` 的 ER 与 BA 拓扑，确认 score、selection、reward settlement 在真实 devnet 中是否按论文设计生效。

首次 ER 复跑时发现确定性 EL payload build 错误：

```text
Failed to build payload err="insufficient topostake escrow balance ... have 7896000000000000 need 15876000000000000"
```

根因：
- geth pending settlement 的 key 使用了 `(finalized_epoch, evidence_epoch)`；
- 同一个 evidence epoch 可能被不同 CL 节点在不同 finalized epoch 首次提交；
- 这样会为同一个 evidence epoch 生成多个 pending settlement root；
- 第一次 payout 会消耗 escrow，第二次 duplicate payout 再执行时就会出现 `insufficient topostake escrow balance`；
- 因此 settlement 的支付身份必须是 evidence epoch，而不是 `(finalized_epoch, evidence_epoch)`。

修复：
- geth `settlementPayloadKey` 改为只按 evidence epoch 去重；
- 若同一个 evidence epoch 的 pending settlement 被新 root 替换，删除旧 root；
- 若该 evidence epoch 已经 executed，再次提交直接跳过，不再生成新的 pending payout；
- `finalized_epoch` 仍然保留在 settlement payload/root 中，用于审计和 block record 语义，但不参与 payout identity。

回归测试与镜像：

```bash
cd ethereum-topostake/go-ethereum-topostake
GOCACHE=/tmp/go-build-cache go test ./eth/topostake ./core/types
GOCACHE=/tmp/pog-go-build-cache GOTMPDIR=/tmp make geth
GETH_BINARY=/home/wujian/pog-rs/ethereum-topostake/go-ethereum-topostake/build/bin/geth ./scripts/geth_image.sh package-local
./scripts/geth_image.sh verify
```

同时把 `experiments/topostake_devnet_runner.py` 的 Beacon API `get_json()` 改为 `30s timeout + 3 retries`，避免单次 CL API 抖动直接中断实验。

复跑参数：
- modes：`TopoStake`
- topologies：`ER`, `BA`
- nodes：`16`
- sender/origin：`16 senders`, `origin_mode=round_robin`，measurement 中每个节点各发 `160 tx`
- load：`32 tx/slot`
- slot/epoch：`3s slot`, `16 slots/epoch`
- warmup：`10 epochs`
- measurement：`5 epochs`
- package：使用本地 `/tmp` ethereum-package 与本地 `topostake/geth:dev`、`topostake/lighthouse:dev`

验证结果：

| Topology | Tx | Finalized | Path Rec. | Fee Rec. | Invalid Evidence | Fee Viol. | Avg. Path | Incl. Delay p50/p95 | Score Epoch Used | Max Weight/Base | Weight-Selection Corr. | Top-Weight Path |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: | --- |
| ER | `2560/2560` | `32` | `2560` | `2560` | `0` | `0` | `3.813` | `4.67s / 27.22s` | `21..31` | `1.71x` | `0.444` | `3.125` vs all `3.813` |
| BA | `2560/2560` | `40` | `2560` | `2560` | `0` | `0` | `2.795` | `4.13s / 45.48s` | `30..40` | `1.95x` | `0.667` | `2.49` vs all `2.795` |

ER 结论：
- `path_records == fee_records == tx_count`；
- 所有 measurement epoch 的 invalid evidence 为 `0`；
- fee conservation violation 为 `0`；
- 每个 measurement epoch 的 valid paths 在 CL 间一致，score 覆盖稳定；
- proposer selection 使用 finalized historical score，measurement slot 中没有退化成 all-base weight；
- 高权重 proposer 打包的交易平均 path 明显短于全局平均值。

BA 结论：
- 链可以 finalized，真实 fee mutation 开启，path/fee records 完整，fee conservation 为 `0`；
- `cl-01` 观察到 proposer weight 非均匀，max/base 接近 `1.95x`，weight 与 selected count 的相关性约 `0.667`；
- BA 下 top-weight proposers 的 path 平均值 `2.49`，短于全局平均 `2.795`，说明 score/selection 对 path 有正向效果；
- 但 BA 的跨 CL Prometheus 指标仍有局部不一致：部分 epoch 中不同 CL 的 valid/settled metric spread 不完全相同，个别 CL 显示 pending 未及时 settle；
- 因此 BA 当前可以证明“链上 block records、fee settlement、selection 在 observed proposer 侧生效”，但还不能声称“所有 CL 本地 score/settlement metrics 完全一致”。后续应优先区分这是 Prometheus scrape/本地 runtime 指标滞后，还是 CL-local score state 仍有 canonicalization 问题。

产物：
- ER raw summary：`results/raw/devnet_prompt41_42/prompt41_topology_topostake_er_n16_txslot32_seed0/summary.json`
- ER block records：`results/raw/devnet_prompt41_42/prompt41_topology_topostake_er_n16_txslot32_seed0/block_records.csv`
- BA raw summary：`results/raw/devnet_prompt41_42/prompt41_topology_topostake_ba_n16_txslot32_seed0/summary.json`
- BA block records：`results/raw/devnet_prompt41_42/prompt41_topology_topostake_ba_n16_txslot32_seed0/block_records.csv`
- 两轮 Kurtosis enclave 均已清理，无残留运行资源。

后续：
- 若论文图表只需要链上结果，ER/BA 这轮可以作为 Prompt 41 TopoStake 修复后的候选数据；
- 若要证明“每个 CL 的 score state 完全一致”，需要新增一个 canonical score audit：从 finalized block body records 重放每个 evidence epoch 的 score，而不是只读各 CL 的 Prometheus runtime counter；
- BA 仍建议再补一次 score audit，再进入最终画图。

### Prompt 48 measurement score/election audit

目标：专门检查 Prompt 47 的 ER/BA 两轮中，measurement 阶段的 score 与 proposer election 是否真的起作用，特别是“实验 5 个 epoch”内的 selection 是否符合 TopoStake 设计。

先修正一个实验口径：
- `experiments/run_devnet_prompt41_42.py` 里把 `SLOTS_PER_EPOCH` 写成 `16`，所以 `5 measurement epochs` 被换算成 `32 tx/slot * 16 slots * 5 = 2560 tx`；
- 但当前 Kurtosis/Lighthouse 使用的是 `preset: minimal`，真实 CL epoch 是 `8 slots/epoch`；
- 因此这轮所谓 `10 warmup + 5 measurement` 在交易量上等价于 `20 minimal CL epochs warmup + 10 minimal CL epochs measurement`；
- 这不影响这轮 score/election 是否生效的判断，但后续论文实验需要把术语改成 `measurement workload = 2560 tx`，或真正把 devnet 配成 `16 slots/epoch` 后再叫 `5 epochs`。

按真实 CL epoch 口径：

| Topology | Measurement included slots | Measurement CL epochs | Score epochs used by selection |
| --- | --- | --- | --- |
| ER | `188..270` | `23..33` | `21..31` |
| BA | `257..337` | `32..42` | `30..40` |

这说明 selection 使用的是 finalized historical score，约落后当前 proposer epoch `2` 个 minimal epochs，符合当前 `EVIDENCE_FINALITY_DEPTH=1` 加 finalized-gated score 的设计。

ER audit：
- actual block slots：`74`
- majority election 与 block body proposer：`74/74` 匹配；
- `cl-01` 与 actual proposer：`74/74` 匹配；
- `15/16` 个 CL 与 actual proposer：`74/74` 匹配；
- `cl-12` 偏离：`10/74` 匹配，说明它的本地 selection metric/视图异常；
- measurement evidence：
  - valid paths 在 CL 间一致：epoch `11..16` 的 spread 均为 `min=max`
  - invalid paths：全部 `0`
  - scored validators：每个 measurement workload epoch 均为 `10`
- weight：
  - non-base weight validators：每 slot 约 `9..10`
  - max/base weight ratio：约 `1.66x..1.83x`
  - weight-selection correlation：`0.444`
  - top-weight proposer 的 path 均值：`3.125`，短于全局 `3.813`

ER 结论：score/election 主路径正常。少数 CL metric 偏离存在，但 majority election、`cl-01` election、block body proposer 三者一致，ER 数据可用于说明 TopoStake selection 生效。

BA audit：
- actual block slots：`64`
- majority election 与 block body proposer：`64/64` 匹配；
- `cl-01` 与 actual proposer：`64/64` 匹配；
- `13/16` 个 CL 与 actual proposer：`64/64` 匹配；
- `cl-03`、`cl-11`、`cl-16` 偏离明显：
  - `cl-03`: `5/64`
  - `cl-11`: `5/64`
  - `cl-16`: `2/64`
- measurement evidence：
  - invalid paths：全部 `0`
  - valid paths 在部分 epoch 有 spread，例如 workload epoch `20` 为 `64..254`
  - scored validators 在部分 epoch 也有 spread，例如 `7..10`
- weight：
  - non-base weight validators：每 slot 约 `6..9`
  - max/base weight ratio：约 `1.88x..2.00x`
  - weight-selection correlation：`0.667`
  - top-weight proposer 的 path 均值：`2.49`，短于全局 `2.795`

BA 结论：链上 actual proposer 与 majority/`cl-01` selection 一致，score 确实改变了 proposer weight，并且高权重 proposer 的 path 更短；但 BA 下有 `3/16` 个 CL 的本地 selection/evidence metric 与 majority 明显偏离。因此 BA 不能直接用于证明“所有 CL 本地 score state 完全一致”，只能证明“canonical chain 上的 observed election 生效”。

下一步修复方向：
- 优先补 canonical score audit：从 finalized block body 的 path records 离线重放 score，得到每个 evidence epoch 的 canonical score；
- 把 CL Prometheus runtime score 与 canonical replay score 对比，定位 `cl-03/cl-11/cl-16/cl-12` 是 metric 滞后、fork-view 暂态，还是本地 score state 没有 canonical 化；
- 修正实验脚本的 epoch 口径：要么把 `SLOTS_PER_EPOCH` 改成 `8` 匹配 minimal，要么真正配置 devnet 为 `16 slots/epoch`。

### Prompt 49 minimal epoch 口径统一

目标：把后续 devnet 实验的 epoch 口径统一到 Lighthouse `minimal` preset，避免脚本按 `16 slots/epoch` 计算交易量，而共识层实际按 `8 slots/epoch` 推进。

变更：
- `experiments/run_devnet_prompt41_42.py`
  - `SLOTS_PER_EPOCH = 16` 改为 `SLOTS_PER_EPOCH = 8`

影响：
- 从 Prompt 49 之后，新实验里 `32 tx/slot, measurement 5 epochs` 会发送：

```text
32 tx/slot * 8 slots/epoch * 5 epochs = 1280 tx
```

- `warmup 10 epochs` 会发送：

```text
32 tx/slot * 8 slots/epoch * 10 epochs = 2560 tx
```

- 这和当前 Kurtosis/Lighthouse `preset: minimal` 的真实 CL epoch 对齐；
- Prompt 47/48 之前的旧结果不回写改数值，它们仍然表示旧脚本下的 `2560 tx measurement workload`，约等于 `10` 个 minimal CL epochs；
- 后续论文图表如果引用旧结果，应写成 `2560 measurement transactions over 80 slots`，不要写成 `5 epochs`；
- 后续新跑结果可以直接写 `5 minimal epochs`。

后续：
- 重新跑 Prompt 41/42/44 类实验时，默认使用 minimal 统一口径；
- 图表 caption 建议显式写：

```text
minimal preset, 3s slots, 8 slots per epoch
```

### Prompt 50 score/election 偏离根因分析

问题：Prompt 47/48 中 ER/BA 主链 proposer 与 majority election 匹配，但少数 CL 的本地 `topostake_selected_proposer` / evidence metric 偏离。需要确认这是实验采集问题，还是协议实现问题。

结论：这是当前 devnet 实现的协议状态边界问题，不只是画图或 Prometheus 展示问题。

证据：
- `topostake_selected_proposer`、`topostake_proposer_weight_scaled`、`topostake_selection_score_epoch` 在 `BeaconState::compute_topostake_proposer_index()` 中写入；
- 这些 metrics 的 labels 只有 `slot / proposer_epoch / score_epoch / validator_index`，没有 `block_root / head_root / state_root`；
- 如果某个 CL 对 side fork、旧 head 或非最终 canonical view 计算过同一个 slot 的 proposer，Prometheus gauge 会被最后一次本地计算覆盖；
- block body 里的 actual proposer 仍然和 majority election 匹配，说明 canonical 链的主路径选举没有错；
- 但少数 CL 的本地 gauge 可能留下 fork-view 结果，所以会出现 `cl-12`、`cl-03`、`cl-11`、`cl-16` 这类局部偏离。

更深层根因：
- TopoStake score 当前不在 `BeaconState` 里；
- `TopoStakeStateSkeleton` 仍只是 non-SSZ placeholder；
- 真实 score 存在 `chain_spec.rs` 的进程级全局 runtime：

```rust
static TOPOSTAKE_EVIDENCE_RUNTIME: OnceLock<RwLock<TopoStakeEvidenceRuntime>>
```

- block processing 看到 block-inline path records 后，会直接更新这个本地 runtime；
- 该 runtime 不是 state root 的一部分，不能随 fork choice / block replay 自动回滚；
- `accepted_tx_hashes` 也是 runtime 级去重：某节点如果先在 side fork 中接受了某 tx，后续 canonical block 中同一个 tx 可能会被本地当成 duplicate 跳过；
- BA 拓扑下 fork/late-view 更多，所以 evidence valid paths 和 scored validators 的 CL 间 spread 更明显。

因此：
- 当前结果能说明 canonical chain 上 TopoStake score/election 生效；
- 但不能证明所有 CL 的本地 score state 完全一致；
- 更严格地说，当前 score 作为 proposer selection 输入仍不是完全 protocol-grade，因为它依赖 CL process-local runtime，而不是 canonical BeaconState。

短期可接受口径：
- 论文 devnet 图表可以使用 canonical block records 统计 path、fee、actual proposer；
- selection 生效性应以 block body actual proposer 与 majority/canonical replay 结果为准；
- 不应把所有 CL 的 Prometheus runtime metric 当作 canonical truth。

协议级修复方向：
1. 把 TopoStake score/settled score 正式放进 BeaconState SSZ 字段，参与 state root。
2. 在 epoch transition 或 finalized checkpoint processing 中，从 finalized block-inline path records 计算 canonical score。
3. proposer selection 只读取 BeaconState 中的 canonical score。
4. duplicate tx/path 去重必须按 canonical evidence epoch + block/root 语义处理，不能用进程全局 `accepted_tx_hashes` 直接决定共识 score。
5. Prometheus metrics 只从 canonical state 导出，或者 label 加上 `head_root/state_root`，避免 fork-view 覆盖 canonical-view 指标。

短期工程修复方向：
- 先做 `canonical score audit`：从 finalized block body records 离线重放 score，输出每个 epoch/validator 的 canonical score；
- 把 CL runtime metric 与 canonical replay score 对比，量化偏离；
- 后续再把 runtime score 替换为 BeaconState-backed score。

### Prompt 51 missed slot 根因分析

问题：TopoStake runs 中出现明显更多 `missed_slots`，例如：
- Prompt 41 TopoStake ER：`11`
- Prompt 41 TopoStake BA：`20`
- Prompt 41 TopoStake Linear：`7`
- PathObs/Baseline 多数为 `0..3`

先明确当前 `missed_slots` 口径：
- runner 只从 `cl-01` 调 `/eth/v2/beacon/blocks/{slot}`；
- 返回 `404` 就记为 missed；
- 这表示 `cl-01` 当前 canonical view 中该 slot 没有 block；
- 它大概率是 skipped proposal / missed proposal，但旧 summary 没保存具体 slot list，所以还不能逐 slot 对齐 proposer duty。

已补观测：
- `experiments/topostake_devnet_runner.py::collect_blocks()` 新增 `missed_slot_list`；
- 后续每轮 summary 会保存具体 404 slot，方便和 `topostake_selected_proposer`、actual block proposer、VC duty 对齐。

当前最可能根因：
- TopoStake proposer selection 依赖每个 CL 进程本地的 TopoStake runtime score；
- 少数 CL 的本地 score/selection metric 已经证明会偏离 majority；
- validator 是否提议区块，取决于它连接的本地 CL/VC 认为自己是不是该 slot 的 proposer；
- 如果 canonical majority 认为 validator X 应该提议，但 validator X 自己的 CL 本地 runtime 偏了，认为该 slot proposer 是 Y，那么 X 不会出块；
- 其他节点即使算对 proposer，也不能替 X 签块；
- 结果就是该 slot 在 canonical chain 上 skipped/missed。

为什么 TopoStake 更容易出现：
- Baseline/PathObs proposer election 不读 TopoStake score，所有 CL 用同一套标准 PoS proposer selection；
- TopoStake 当前 score 是进程级 runtime，不是 BeaconState canonical state；
- BA/ER 拓扑更容易产生 late view / side fork / block replay；
- 这些非 canonical 处理会污染部分 CL 的本地 score runtime，进而污染该 CL 的 proposer duty 判断；
- 所以 TopoStake 下 missed slot 增多，和 Prompt 50 的 score/election 本地偏离是同一个根因的两个表现。

这不是最终协议应有行为：
- 如果 score 正式进入 BeaconState 并参与 state root，所有 honest CL 在同一 canonical state 上会得到同一个 proposer duty；
- missed slot 应显著下降到接近 baseline/pathobs，只剩真实资源/网络/validator offline 导致的 miss。

下一步验证：
1. 重跑 TopoStake BA/ER，使用新的 `missed_slot_list`。
2. 对每个 missed slot：
   - 查 majority selection 认为的 proposer；
   - 查该 proposer 所属 CL 的本地 `topostake_selected_proposer`；
   - 如果该 CL 本地没有选自己，就能直接证明 missed slot 来自本地 proposer duty divergence。
3. 之后做协议级修复：把 score/settled score 迁入 BeaconState-backed canonical state，再重跑比较 missed slots。

### Prompt 52 fee mutation isolation: BA missed/fork check

目标：先把 TopoStake 的真实 fee balance mutation 暂时关掉，只保留 path evidence、score/selection 与 fee accounting metrics，重跑 16-node BA，区分：
- 之前的 fork/invalid root 是否来自真实余额 mutation；
- 当前 missed slot 是否仍然存在；
- 如果仍然存在，问题更偏向 proposer duty / timing / resource，而不是 fee settlement state mutation。

实验配置：
- mode：`TopoStake`
- topology：`BA(m=2), seed=0`
- nodes：`16`
- validators：`1 validator / node`
- preset：`minimal`
- slot/epoch：`3s slot, 8 slots/epoch`
- warmup：`10 epochs = 2560 tx`
- measurement：`5 epochs = 1280 tx`
- workload：`32 tx/slot`
- origin：`round_robin`，16 个 EL 入口均匀发交易
- fee mutation isolation：

```yaml
TOPOSTAKE_FEE_ESCROW: "0"
TOPOSTAKE_SETTLEMENT_MUTATION: "0"
```

结果：
- peer graph matches target：`true`
- tx success：`1280 / 1280`
- finalized：从 measurement 前 `finalized_epoch=22` 推进到 `finalized_epoch=37`
- inclusion throughput：`3.92 TPS`
- inclusion delay：
  - p50：`3 slots / 6.08s`
  - p95：`45.05 slots / 134.21s`
- measurement window：slot `202..318`
- missed slots：`51`
- missed slot list：

```text
202, 204, 205, 209, 211, 213, 216, 218, 219, 220, 222, 224, 225,
229, 231, 232, 234, 236, 237, 242, 256, 257, 259, 261, 265, 266,
267, 269, 270, 271, 274, 276, 278, 281, 283, 284, 285, 288, 290,
293, 294, 295, 304, 305, 307, 308, 311, 312, 314, 316, 317
```

Path/fee record 口径：
- block-inline path records：`178`
- nonzero fee records：`178`
- priority fee sum：`7476000000000000 wei`
- avg path length：`1.62`
- path length histogram：`{1: 75, 2: 96, 3: 7}`

注意：
- `TOPOSTAKE_SETTLEMENT_MUTATION=0` 关闭的是真实余额 mutation；
- Prometheus 里 `topostake_fee_*` 仍会出现非零 accounting metrics，因为 block record 中仍带 `priority_fee_wei`，CL 仍可计算 settlement ledger / fee conservation；
- 这轮不应该把这些 metrics 解读成真实余额已发生 mutation。

日志检查：
- `merkle`：`0`
- payload/state-root 级别的 invalid：未发现；
- 日志里的 `invalid` 计数来自 geth 启动期的 `Sanitizing invalid node buffer size`，不是 block invalid；
- CL 日志出现大量：
  - `Producing block at incorrect slot`
  - `Block was broadcast too late`
  - `Duplicate payload cached`
- 计数：
  - `broadcast_too_late / broadcast delayed`：`120`
  - `incorrect_slot`：`123`
  - `duplicate_payload`：`128`
  - `engine_connect / forkchoice engine call failed`：存在多次 CL->EL connection 抖动

结论：
- 关掉真实 fee mutation 后，没有复现 `invalid merkle root` / execution state-root 分叉；
- 因此之前真实 fee settlement records 的 bug 修复方向是对的，fee balance mutation 已不再是这轮 observed fork 的主因；
- 但 missed slot 仍然非常严重，说明当前主要问题已经转移到 proposer production timing / local proposer duty divergence / 本机资源压力；
- 特别是 3s slot + 16 EL/CL/VC + TopoStake score/selection 逻辑下，多个 CL 出现 late block 和 incorrect slot，导致 canonical view 中大量 slot 查不到 block；
- 下一步应优先做 missed slot 对齐分析：
  1. 对每个 missed slot 找 canonical/majority TopoStake selected proposer；
  2. 查该 proposer 所属 CL/VC 当时是否认为自己该出块；
  3. 检查 block production 是否卡在 proposer selection、payload build、path verification、Engine API，还是系统负载；
  4. 如果 duty divergence 成立，优先把 TopoStake score 从 process-local runtime 迁入 BeaconState-backed canonical state；
  5. 如果 duty 一致但出块过晚，则优化 block production critical path，尤其是 path record collection/verification 和 payload preparation。

### Prompt 53 missed slot alignment audit

目标：对 Prompt 52 的 `51` 个 missed slots 做离线对齐，确认：
- majority/canonical TopoStake selection 每个 missed slot 选了谁；
- 该 proposer 自己连接的 CL 是否也认为自己该出块；
- missed slots 更像 election/duty divergence，还是 block production timing / Engine API / resource 问题。

数据源：
- `results/raw/devnet_prompt41_42/prompt52_nofee_topostake_ba_n16_txslot32_seed0/summary.json`
- `blocks.missed_slot_list`
- Prometheus `topostake_selected_proposer`
- Prometheus `topostake_proposer_weight_scaled`

重要限制：
- Prompt 52 结束后 enclave 已清理；
- 因此本轮只能用 summary 中保存的 metrics 做 selection/duty 对齐；
- 无法再逐 slot 拉 Docker logs 来确认每个 missed slot 的 payload build / Engine API / validator API 具体耗时；
- Prompt 52 运行时日志曾观察到大量 `Producing block at incorrect slot` 与 `Block was broadcast too late`，但这些日志没有逐 slot 持久化到 summary。

对齐结果：

| Scope | slots | owner self-selected | owner mismatch | all CL agree | avg majority count |
| --- | ---: | ---: | ---: | ---: | ---: |
| all measurement slots | `117` | `115` | `2` | `109` | `15.62 / 16` |
| missed slots | `51` | `50` | `1` | `47` | `15.67 / 16` |
| non-missed slots | `66` | `65` | `1` | `62` | `15.59 / 16` |

解释：
- `47/51` missed slots 中，16 个 CL 完全一致地选中同一个 proposer；
- `50/51` missed slots 中，被 majority 选中的 proposer，其自己连接的 CL 也认为“自己就是 proposer”；
- 只有 slot `232` 出现 owner mismatch：majority 选 validator `2`，但 validator `2` 所属 CL 本地选到 validator `1`；
- 因此 missed slots 的主因不像是 TopoStake score/election 本地分叉导致 proposer 不知道自己该出块；
- 更可能发生在 proposer duty 已确定之后：validator client 请求 block、CL 生产 block、EL payload build、path verification、Engine API、或者本机资源调度没赶上 3s slot。

missed slots majority proposer 分布：

| Validator | selected slots | missed slots | miss rate |
| ---: | ---: | ---: | ---: |
| 0 | 9 | 5 | 55.56% |
| 1 | 14 | 10 | 71.43% |
| 2 | 10 | 9 | 90.00% |
| 3 | 7 | 1 | 14.29% |
| 4 | 4 | 1 | 25.00% |
| 5 | 4 | 4 | 100.00% |
| 6 | 8 | 2 | 25.00% |
| 7 | 6 | 3 | 50.00% |
| 8 | 7 | 3 | 42.86% |
| 9 | 7 | 4 | 57.14% |
| 10 | 7 | 0 | 0.00% |
| 11 | 10 | 3 | 30.00% |
| 12 | 7 | 1 | 14.29% |
| 13 | 5 | 2 | 40.00% |
| 14 | 6 | 2 | 33.33% |
| 15 | 6 | 1 | 16.67% |

观察：
- miss 明显集中在 validator `1/2/5`，不是所有 proposer 均匀失败；
- high weight 不是直接原因：多数 missed slots 的 selected proposer weight 仍是 base `1.00x`，少数为 `2.00x`；
- 这说明“TopoStake 把某些高分节点选太多导致 miss”的解释不够强；
- 更值得查的是这些 validator 对应 CL/EL/VC 的 block production path 是否慢，或它们在 BA topology/资源调度下更容易产生 delayed proposal。

当前结论：
- Prompt 52 的 missed slot 主因暂时不支持“selection/duty divergence”；
- 更支持“duty 已对齐，但 proposer production 过晚或 block orphaned”；
- 之前日志中的 `incorrect slot` / `broadcast too late` 与这个结论一致；
- 下一轮需要保留逐 slot 日志，才能判断具体卡在 payload build、path verification、Engine API 还是 validator API。

下一步 instrumentation：
1. runner 在每轮结束前保存所有 CL/EL/VC 的 Docker logs 到 run output 目录。
2. `collect_blocks()` 不只保存 path records，还要保存每个 slot 的 block presence、block root、proposer index、execution payload block hash。
3. 对 missed slot 保存 majority proposer、owner CL local proposer、owner VC logs、owner CL block production logs、owner EL payload build logs。
4. 给 Lighthouse block production 增加 TopoStake scoped timing：
   - proposer selection time；
   - path record selection/packing time；
   - path verification time；
   - Engine API `forkchoiceUpdated/getPayload/newPayload` time；
   - broadcast time。
5. 重跑 `16-node BA, 32 tx/slot, warmup 10 epochs, measurement 5 epochs`，再逐 slot 判定真正瓶颈。

### Prompt 54 16 tx/slot interrupted missed-slot diagnosis

目标：把 Prompt 52 的负载从 `32 tx/slot` 降到 `16 tx/slot`，确认 missed slot 是否只是因为交易负载太满。

实验配置：
- mode：`TopoStake`
- topology：`BA(m=2), seed=0`
- nodes：`16`
- preset：`minimal`
- slot/epoch：`3s slot, 8 slots/epoch`
- workload：`16 tx/slot`
- warmup：`10 epochs = 1280 tx`
- measurement：计划 `5 epochs = 640 tx`
- origin：`round_robin`，16 个 EL 入口均匀发交易
- fee mutation isolation：

```yaml
TOPOSTAKE_FEE_ESCROW: "0"
TOPOSTAKE_SETTLEMENT_MUTATION: "0"
```

状态：
- workload 在 warmup receipt waiting 阶段被手动停止；
- 因此没有可用的 measurement summary；
- Kurtosis enclave 名称：`ts-prompt54-nofee-topostake-ba-n16-txslot16-seed0`。

现场日志观察：
- 所有 EL/CL/VC 容器均为 `RUNNING`，没有容器退出或重启；
- RAM 正常：`23Gi` total，约 `14Gi` available；
- CPU 线程：`32`；
- host load average：约 `13.24, 9.73, 4.81`；
- 每个 CL 都出现：
  - `ForkChoiceSignalOutOfOrder`：约 `14` 次；
  - `Block was broadcast too late`：`0..5` 次；
  - `Producing block at incorrect slot`：`0..3` 次；
  - `empty` slot 日志几十次；
- 每个 VC 都出现大量：
  - `Proposer duties re-org`：约 `154..166` 次；
- EL 日志没有 payload invalid / state-root invalid；
- EL payload import/build 很快，常见耗时为微秒到数毫秒级，例如 `Updated payload ... elapsed="333µs"`、`Imported new potential chain segment ... elapsed=1..7ms`。

解释：
- `Block was broadcast too late` 在 Lighthouse 中表示 block 从 slot 开始到 publish 的 delay 超过 attestation due threshold，日志文本明确提示 `system may be overloaded, block likely to be orphaned`；
- 因此 `empty slot` 不是“没有交易”，而是 canonical view 中该 slot 没有成功落地的 block；
- `16 tx/slot` 仍然出现 late/empty/re-org，说明问题不是 `32 tx/slot` 太满；
- fee mutation 已关闭，且 EL 没有 invalid payload/state-root，说明这轮也不是真实余额 mutation 导致的分叉；
- geth payload build 不是主要瓶颈：EL 多数 payload/chain import 是毫秒级；
- 更可能的链路是：

```text
3s slot + 16 EL/CL/VC + exporter/Prometheus + TopoStake CL logic
    -> host scheduler / CL fork-choice timing 抖动
    -> VC 频繁重拉 proposer duties，出现 proposer duties re-org
    -> proposer 出块窗口被压缩或 block 基于旧/变化中的 head 生成
    -> block publish 过晚或被 orphaned
    -> canonical view 中表现为 empty/missed slot
```

当前结论：
- 这轮支持 Prompt 53 的判断：missed slot 的主因更像 proposer duty 已对齐后的 production/broadcast timing 问题，而不是 selection 完全分叉；
- 但 `Proposer duties re-org` 频率异常高，说明 CL/VC 对 dependent root/head 的视图非常不稳定，需要进一步拆分：
  1. 这是 3s minimal + 16 组客户端在本机上的调度压力；
  2. 还是 TopoStake proposer selection/runtime metric 触发了更多 fork-choice churn；
  3. 或者两者叠加。

下一步建议：
1. 先做一个低风险 sanity：`16 nodes, BA, 16 tx/slot` 下把 slot 从 `3s` 临时调到 `6s` 或 `12s`。如果 miss 大幅下降，说明主要是 timing/resource budget。
2. 同样配置下跑 `PoS-Beacon` / `PoS+PathObs` / `TopoStake` 三模式对照，确认 `Proposer duties re-org` 是否 TopoStake 独有。
3. 给 block production path 增加持久 timing 日志：
   - VC request block time；
   - CL proposer selection time；
   - Engine API `forkchoiceUpdated/getPayload` time；
   - TopoStake evidence packing/verification time；
   - publish block time。
4. 如果 `6s/12s` 明显稳定，再决定论文 devnet 是否继续用 `3s slot`；否则 3s slot 下 16-node 结果更多是在测本机时序压力，不适合作为协议 overhead 主图。

### Prompt 55 block production timing instrumentation

目标：继续查 Prompt 54 的 `empty slot` / `broadcast too late`，不能只用“加长 slot”解释。给 TopoStake block production 增加阶段耗时日志，并用 16-node BA 复现。

代码改动：
- `ethereum-topostake/lighthouse/validator_client/validator_services/src/block_service.rs`
  - 记录 `randao_ms`
  - 记录 VC 请求 unsigned block 的 `unsigned_block_ms`
  - 记录 signing + publish 的 `sign_publish_ms`
  - 记录整次 proposer duty 的 `total_duty_ms`
  - 记录各阶段发生时的 `slot_elapsed_ms`
- `ethereum-topostake/lighthouse/beacon_node/beacon_chain/src/beacon_chain.rs`
  - 记录 block body 中 TopoStake evidence root / records 转换耗时：
    - `root_ms`
    - `records_ms`
    - `total_ms`
    - `evidence_records`
    - `slot_elapsed_ms`

验证：

```bash
cd ethereum-topostake/lighthouse
cargo check -p validator_services -p beacon_chain
cargo build --release --bin lighthouse --features spec-minimal
LIGHTHOUSE_BINARY=/home/wujian/pog-rs/ethereum-topostake/lighthouse/target/release/lighthouse \
  scripts/lighthouse_image.sh package-local
```

备注：
- 本轮启动 devnet 时，`/tmp/ethereum-package` 顶层 import 了未使用的 MEV launcher，导致 Kurtosis 试图拉远端 `redis-package` / `postgres-package`；
- 已在 `/tmp/ethereum-package` 临时副本中把 unused flashbots/helix MEV remote dependency stub 掉；
- 这个 patch 只影响 `/tmp` 本地 package，不影响仓库代码。

短跑 sanity：
- run id：`prompt55_timing_topostake_ba_n16_txslot16`
- topology：`BA(m=2), seed=0`
- nodes：`16`
- workload：warmup `128 tx`，measurement `256 tx`
- fee mutation：关闭
- 结果：
  - `tx_success = 256 / 256`
  - `missed_slots = 0`
  - inclusion delay p95：`4.85s`
  - `Block was broadcast too late = 0`
  - `Producing block at incorrect slot = 0`

短跑 timing：

| Metric | count | p50 | p95 | max |
| --- | ---: | ---: | ---: | ---: |
| `unsigned_block_ms` | `56` | `16ms` | `30ms` | `158ms` |
| `total_duty_ms` | `52` | `73ms` | `91ms` | `205ms` |
| `sign_publish_ms` | `52` | `54ms` | `68ms` | `72ms` |
| `evidence_total_ms` | `76` | `0ms` | `0ms` | `0ms` |

长跑复现：
- run id：`prompt55_timing_long_topostake_ba_n16_txslot16`
- topology：沿用同一 16-node BA devnet，`--skip-apply-topology`
- workload：warmup `1280 tx`，measurement `640 tx`
- fee mutation：关闭
- 结果：
  - `tx_success = 640 / 640`
  - finalized：`finalized_epoch = 28`
  - `missed_slots = 11`
  - missed slot list：`196, 197, 201, 207, 216, 219, 220, 222, 224, 235, 237`
  - inclusion delay p50：`4.12s`
  - inclusion delay p95：`36.62s`
  - inclusion delay max：`130.89s`

长跑 timing：

| Metric | count | p50 | p95 | p99 | max |
| --- | ---: | ---: | ---: | ---: | ---: |
| `unsigned_block_ms` | `255` | `18ms` | `57ms` | `1064ms` | `3118ms` |
| `total_duty_ms` | `239` | `79ms` | `161ms` | `3062ms` | `3168ms` |
| `sign_publish_ms` | `239` | `55ms` | `98ms` | `181ms` | `3071ms` |
| `evidence_total_ms` | `331` | `0ms` | `0ms` | `1ms` | `10ms` |
| `evidence_records` | `332` | `12` | `39` | `76` | `609` |

关键原始日志：

```text
slot 135: cl-03 Producing block at incorrect slot current_slot=136
slot 135: vc-03 unsigned_block_ms=3016, total_duty_ms=3062
slot 135: cl-03 Block was broadcast too late delay_ms=3047

slot 206: cl-03 Producing block at incorrect slot current_slot=207
slot 206: vc-03 unsigned_block_ms=3118, total_duty_ms=3168
slot 206: cl-03 Block was broadcast too late delay_ms=3135

slot 222: vc-16 sign_publish_ms=3071, total_duty_ms=3093
slot 222: cl-16 Block was broadcast too late delay_ms=3054

slot 201: vc-09 unsigned_block_ms=1064, total_duty_ms=1124
slot 201: cl-09 Block was broadcast too late delay_ms=1093
```

结论：
- 这轮把原因进一步缩小了：TopoStake block evidence packing 不是 missed slot 的主瓶颈；
  - 即使 `evidence_records=609`，`evidence_total_ms` 也只有 `7ms`；
  - p95 为 `0ms`，max 为 `10ms`。
- EL payload build/import 也不是主瓶颈；
  - geth 日志里 payload update/import 多数仍是微秒到数毫秒级。
- 真正导致 late 的 outlier 在 VC/BN proposal chain：
  - 一类是 `unsigned_block_ms` 直接接近或超过 `3s`，说明 VC 向 BN 请求 unsigned block 时，BN 没能在 slot budget 内返回；
  - 另一类是 `sign_publish_ms` 接近 `3s`，说明签名后 publish signed block 到 BN / BN publish to gossip 的链路卡住；
  - 这些 outlier 与 `Block was broadcast too late` 的 `delay_ms` 对齐。
- 因此“missed slot”不是交易负载太高，也不是 path evidence 解析太慢，而是 3s slot 下偶发的 block proposal HTTP/publish/fork-choice 链路 outlier。
- `Proposer duties re-org` 和 `ForkChoiceSignalOutOfOrder` 仍然非常多：
  - 长跑 `VC proposer duties re-org = 3179`
  - `CL ForkChoiceSignalOutOfOrder = 336`
  - 这说明 fork-choice/dependent-root 仍在频繁抖动，可能压缩了 proposer production 的稳定窗口。

下一步：
1. 继续细化 CL 侧 timing：在 BN HTTP block production handler 中记录：
   - request received slot elapsed；
   - wait fork-choice time；
   - load state time；
   - prepare/get payload time；
   - complete block time；
   - HTTP response write time。
2. 在 publish signed block handler 中记录：
   - BN 收到 signed block 的 slot elapsed；
   - local validation time；
   - gossip publish time；
   - late logging delay。
3. 跑同配置的 `PoS+PathObs` 对照；如果也出现同类 `unsigned_block_ms/sign_publish_ms` outlier，则这是 16-node/3s local devnet timing 问题；如果 TopoStake 独有，再继续查 TopoStake selection/fork-choice runtime 是否放大 head churn。

补充判断：
- 由于 `PoS-Beacon` 同类实验基本稳定，后续不能只按“slot 太短”解释；
- 必须优先查 TopoStake 相比 PoS 独有或半独有的链路：
  - `PoS+PathObs` 与 `TopoStake` 共有：EL 交易传播 path metadata、block-inline path evidence、CL block processing 里的 inline evidence verification；
  - `TopoStake` 独有：`ETA_SCALED > 0` 后 proposer-score adjustment 和 proposer selection metrics；
  - `TopoStake` 可选独有：fee settlement / balance mutation / settlement records，当前 timing 复现时已临时关闭，避免把 fee mutation 和 proposer timing 混在一起。
- 因此下一轮应该跑同配置 `PathObs` 和 `TopoStake`，并比较：
  - `load_state_ms`
  - `partial_block_ms`
  - `payload_wait_ms`
  - `complete_block_ms`
  - `gossip_verify_ms`
  - `sidecar_wait_ms`
  - `process_block_ms`
  - `publish_api_elapsed_ms`
- 如果 `PathObs` 无 outlier、`TopoStake` 有 outlier，重点查 proposer-score selection 是否造成 duty/head/fork-choice 抖动；
- 如果两者都有 outlier，重点查 path metadata / inline evidence 这条 shared path；
- 如果只有 fee settlement 打开时出现 outlier，再回到 settlement records / state mutation。

### Prompt 56：TopoStake 10-node BA miss/latency sanity

目的：
- 单独跑 `TopoStake`，把节点数降到 `10`，检查 `BA` 网络、`32 tx/slot` 下是否仍出现明显 missed slot / late broadcast / 高延迟；
- fee mutation 暂时关闭，避免 settlement state mutation 干扰 proposer timing 判断。

配置：
- mode：`topostake`
- topology：`BA(m=2), seed=0`
- nodes：`10`
- validator：`1 validator / node`
- sender/origin：`round_robin`，覆盖全部 `10` 个 EL 节点
- slot/epoch：`3s slot`，minimal `8 slots/epoch`
- workload：
  - warmup：`10 epochs = 2560 tx`
  - measurement：`5 epochs = 1280 tx`
  - load：`32 tx/slot = 10.67 TPS`
- fee settlement：关闭
- additional services：关闭 `Prometheus/Grafana/ethereum-metrics-exporter`
- run id：`prompt56_timing_topostake_ba_n10_txslot32`

结果：

| Metric | Value |
| --- | ---: |
| tx success | `1280 / 1280` |
| finalized epoch | `13` |
| actual send TPS | `10.67` |
| inclusion throughput | `10.91 TPS` |
| inclusion delay p50 | `3.31s` |
| inclusion delay p95 | `6.78s` |
| inclusion delay max | `10.02s` |
| inclusion delay p50 slots | `2` |
| inclusion delay p95 slots | `3` |
| missed slots | `5` |
| missed slot list | `94, 95, 106, 122, 124` |
| path records | `1362` |
| nonzero fee records | `1362` |
| avg path len | `2.41` |
| path len p95 | `4` |

Timing 结果：

| Metric | count | p50 | p95 | p99 | max |
| --- | ---: | ---: | ---: | ---: | ---: |
| `unsigned_block_ms` | `159` | `20ms` | `34ms` | `39ms` | `45ms` |
| `total_duty_ms` | `146` | `85ms` | `117ms` | `137ms` | `145ms` |
| `sign_publish_ms` | `146` | `63ms` | `83ms` | `98ms` | `109ms` |
| `payload_wait_ms` | `211` | `5ms` | `9ms` | `11ms` | `13ms` |
| `complete_block_ms` | `159` | `11ms` | `22ms` | `29ms` | `36ms` |
| `process_block_ms` | `146` | `31ms` | `50ms` | `65ms` | `72ms` |
| `publish_api_elapsed_ms` | `730` | `1ms` | `36ms` | `52ms` | `74ms` |
| `evidence_records` | `211` | `30` | `58` | `75` | `86` |
| `evidence_records_ms` | `211` | `0ms` | `0ms` | `0ms` | `4ms` |

日志计数：
- `Block was broadcast too late = 0`
- `Block broadcast was delayed = 0`
- `Producing block at incorrect slot = 0`
- `ForkChoiceSignalOutOfOrder = 130`
- `Proposer duties re-org = 1320`

结论：
- 这轮 `10-node BA + 32 tx/slot` 没有复现 16-node 长跑里的 `~3s` proposer/publish outlier；
- TopoStake 独有的 path evidence / block processing 在本轮仍是低开销：
  - `evidence_records_ms p95 = 0ms, max = 4ms`
  - `process_block_ms p95 = 50ms, max = 72ms`
  - `total_duty_ms max = 145ms`
- 因此本轮的 `missed_slots=5` 更像是 canonical block collection window / fork-choice head churn / proposer-duty reorg 造成的空槽或统计口径问题，而不是 TopoStake block production 超时：
  - `canonical block collection window`：runner 只按 measurement window 附近扫描 canonical head 链上的 block；如果某个 slot 的 block 被短暂生产但之后没有进入最终 canonical chain，统计上会表现为 missed/empty；
  - `fork-choice/head churn`：CL 在短时间内切换 head/dependent root，可能导致 proposer duty 重新计算或已生产 block 被 orphan；
  - `proposer-duty reorg`：VC 观察到 dependent root 变化后重新拉 proposer duties；如果 reorg 频繁，即使没有 block production 慢，也会让某些 slot 在最终 canonical view 中看起来是空槽。
- 但 `Proposer duties re-org` 与 `ForkChoiceSignalOutOfOrder` 仍然偏多，后续仍应把重点放在 TopoStake 独有的 proposer-score/selection 是否放大 fork-choice/dependent-root 抖动。

信号解释：
- `Proposer duties re-org`：validator client 发现当前 head/dependent root 改变，之前缓存的 proposer duties 不再对应新的链视图，于是重新查询/更新 duties。少量出现是正常的，频繁出现说明 head view 在抖动，可能压缩 proposer 出块准备窗口。
- `ForkChoiceSignalOutOfOrder`：CL 收到或处理 fork-choice/engine 信号时，信号顺序落后于当前已处理的 slot/head 状态，旧信号被忽略或降级处理。它通常表示 fork-choice / Engine API / slot progression 存在时序交错，不等价于分叉 bug，但大量出现说明本机 devnet 的 head/fork-choice pipeline 不够平稳。

Score/selection 结果侧审计：
- 本轮默认关闭 Prometheus/Grafana，因此不能直接读取每个 CL 的 runtime `score` / `proposer_weight` gauge；
- 只能从 canonical block records 做结果侧判断：哪些 proposer 实际出块、这些 proposer 打包交易的平均 path 是否更短。

| Validator | selected slots | records | avg path len | relay intermediate count |
| ---: | ---: | ---: | ---: | ---: |
| `0` | `2` | `58` | `2.500` | `22` |
| `1` | `7` | `223` | `2.076` | `309` |
| `2` | `8` | `286` | `2.168` | `159` |
| `3` | `1` | `29` | `2.655` | `0` |
| `4` | `5` | `235` | `2.477` | `68` |
| `5` | `4` | `156` | `2.353` | `83` |
| `6` | `3` | `111` | `2.712` | `0` |
| `7` | `2` | `60` | `2.550` | `52` |
| `8` | `3` | `87` | `2.862` | `20` |
| `9` | `2` | `117` | `2.761` | `0` |

观察：
- canonical produced slots 中，validator `2` 和 `1` 被选中最多，分别是 `8` 和 `7` 个 slot；
- 它们的平均 path length 也是最低的两组：`2.168` 和 `2.076`；
- selected slot count 与 avg path length 的 Pearson 相关约为 `-0.804`，Spearman 相关约为 `-0.671`；
- 也就是从最终结果看，短 path proposer 的选中率确实更高；
- validator `1` 的 relay intermediate count 最高，说明它在 BA 图中承担 hub/relay 角色，也符合 TopoStake score 应该提高其 proposer weight 的方向。

限制：
- 这不是完整 score 正确性证明，因为没有 Prometheus runtime score/weight；
- 只能说明本轮 canonical 结果和 TopoStake 设计方向一致：高 relay/path advantage 节点被更多选中，且打包 path 更短；
- 若要证明“score 和 election 每个 epoch 都按论文公式正常生效”，需要开启 Prometheus 或新增 canonical score replay，从 finalized block records 重放每个 epoch 的 score/weight。
