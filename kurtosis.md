# TopoStake Ethereum/Kurtosis Reproduction Notes

本文档是当前 TopoStake Ethereum fork 的主线复现说明。它不再按 Prompt 流水展开，而是按协议实现拆成四个部分：

1. 路径传播
2. Score 与 proposer 选举
3. Reward 分配
4. 网络拓扑实现

最后一节单独归纳目前实验进展。当前实验结果仍属于 devnet/smoke 阶段，论文实验表还需要多 seed、多 topology、多 sender workload 和吞吐分档后再固定。

当前实现是 custom geth + custom Lighthouse 的 devnet fork，不保持 stock client 混跑兼容。主实验建议使用 `1 validator / node`，minimal preset，3s slot，16 slots/epoch。旧的 `4 nodes * 16 validators` 只作为历史 smoke/finality 验证入口保留。

## 当前状态

已完成：
- signed tx bytes / tx hash 不变，TopoStake path metadata 随 geth tx gossip envelope 同步传播。
- EL proposer 在 `engine_getPayload` 返回 execution payload 的同时返回 payload 对应的 TopoStake evidence。
- CL 将 bounded path records 写入 beacon block body 的 `topostake_evidence_records`。
- 旧 sidecar/latest/root fallback 已清理，不再通过 `topostake_latestBlockEvidence`、root RPC、CL sidecar HTTP/gossipsub 补 path。
- Lighthouse block processing 会按 block-level aggregate signature 验证 block-inline path records；验证失败的 records 不进入 score/reward。
- Score 只给 intermediate relayers，经过 finalized gate、stake-scaled saturation、EMA 后进入 proposer selection。
- Proposer selection 使用论文版 bounded bonus，只改 proposer weight，不改 attestation/finality voting weight。
- Reward 使用真实 priority fee budget，fee 先进入 escrow/system address，finalized 后按 block-visible settlement root 执行 proposer/relay payout 与 burn。
- `8 nodes * 1 validator` devnet 已能启动、出块、finalized；BA(m=2) single-origin workload 下真实 inclusion delay 稳定在 `1-2 slots`，relay payout 非零，settlement conservation 为 0。

仍未完全完成：
- 最终论文版 block-inline record schema 还需要固定，尤其是 aggregate signature 是否保留 block-level aggregate，还是改成 per-record/per-path aggregate。
- settlement records 仍依赖 devnet-minimal preload/RPC data path；block 只承诺 settlement root。若做成正式协议，需要定义 settlement records availability。
- 实验尚未稳定：baseline/TopoStake 对照、多 seed、多 topology、多 sender workload、吞吐分档还需要重跑和整理。
- 旧 receipt latency 口径已废弃；论文应使用 `send_slot -> included_slot` 的 inclusion delay。
- 多入口 workload 需要 multiple funded senders，不能再用单 sender round-robin 作为吞吐/延迟结论，因为它会引入账户 nonce gap。

## 复现约束

每次启动新的 Kurtosis devnet 前，必须先清理旧 devnet/enclave，避免旧服务、旧端口和旧 metrics 污染结果。

```bash
XDG_DATA_HOME=/tmp/kurtosis-data kurtosis enclave ls
XDG_DATA_HOME=/tmp/kurtosis-data kurtosis enclave rm -f <old-enclave-name>
```

Kurtosis CLI 在当前环境需要使用 `XDG_DATA_HOME=/tmp/kurtosis-data`，否则可能尝试写入只读 home 路径。

推荐主实验配置：
- nodes：`8`
- validators：`1 / node`
- preset：`minimal`
- slot：`seconds_per_slot=3`
- epoch：`slots_per_epoch=16`
- geth image：`topostake/geth:dev`
- Lighthouse image：`topostake/lighthouse:dev`

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
- 当前主实验推荐默认使用。

`round_robin` / `random` origin：
- 适合多入口实验；
- 但不能用单 sender 连续 nonce，否则会引入账户 nonce gap；
- 后续应改成 multiple funded senders，每个 origin 使用独立 nonce 序列。

延迟口径：
- 旧的 `send -> receipt query returns` 是 observed receipt latency，会被 `--wait-receipts-after-send` 放大；
- 论文应使用 `send_slot -> included_slot` 的 inclusion delay；
- runner 已增加 `send_slot_estimate`、`included_slot`、`inclusion_delay_slots`、`inclusion_delay_seconds`。

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

### 当前实验缺口

还需要补：
- baseline vs TopoStake 重新对照，使用 inclusion delay，不使用旧 receipt latency；
- `1 validator / node` 下的 baseline args 和 TopoStake args 成对实验；
- multiple funded senders workload；
- topology suite：linear/ring/star/ER/BA；
- 多 seed 重复；
- tx rate 分档：例如 `4 TPS`, `8 TPS`, `16 TPS`, `32 TPS`；
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
```
