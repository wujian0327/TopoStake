# TopoStake Ethereum/Kurtosis Progress Notes

说明：Prompt 1-13 已整理为合并摘要。它们主要是环境、可行性、instrumentation、fixture/smoke 验证阶段，保留复现入口、关键结果和边界即可；真正开始按 TopoStake 论文思路改交易传播路径的是 Prompt 14。

**Prompt 1-13：环境与验证阶段合并摘要**

复现说明：Prompt 1-13 只作为历史验证记录保留，后续不需要复现，也不需要再次按这些 prompt 实现；当前主线从 Prompt 14 的真实交易路径追踪开始。

阶段定位：
- Prompt 1-4：搭建 Kurtosis Ethereum private PoS devnet、支持自定义 Lighthouse 镜像、做非共识 overhead prototype、调研 Lighthouse 共识改造入口。
- Prompt 5-8：固化本地 Lighthouse fork/image 工作流，添加 propagation instrumentation，做非共识 marker smoke，写 TopoStake Ethereum fork spec。
- Prompt 9-13：做 Lighthouse TopoStake consensus skeleton、fixture proposer selection、fixture/sidecar score update、devnet-only credit ledger 和端到端 smoke。
- 这些 prompt 的共同边界是“把实验环境和最小骨架跑通”，不是论文版 TopoStake path protocol 的完整实现。

保留成果：
- Kurtosis devnet 配置已可跑 geth + Lighthouse private PoS devnet，并可切换自定义 Lighthouse 镜像。
- 本地 Lighthouse 已能编译、打镜像，并在 Kurtosis devnet 中作为 consensus client 启动。
- Prometheus/Grafana 已能采集 Lighthouse 自定义指标，用来观察 propagation、evidence score、credit ledger 等数据。
- `prototype/ethereum-overhead/` 保留了非共识 overhead 原型，用于测试 metadata / BLS / verifier 开销，不影响 Ethereum consensus。
- `docs/LIGHTHOUSE_TOPOSTAKE_INTEGRATION_PLAN.md` 和 `docs/TOPOSTAKE_ETHEREUM_FORK_SPEC.md` 保留了共识改造设计记录。
- Lighthouse 中已有 TopoStake skeleton：配置 fixture、score state、proposer weight hook、epoch score update、devnet-only credit ledger、相关 metrics。

历史复现入口状态：
- Prompt 1-13 对应的 Kurtosis YAML 已删除，不需要复现。
- 旧 baseline/custom Lighthouse/fixture/evidence/missing-sidecar 配置都不再作为主线入口。
- 当前主线复现从 Prompt 14-18 开始，使用 `results/raw/topostake-devnet-4node-1validator-custom-geth-private.yaml`。
- 镜像脚本：`scripts/lighthouse_image.sh`、`scripts/geth_image.sh`
- Kurtosis 辅助脚本：`scripts/kurtosis_devnet.sh`
- overhead prototype：`prototype/ethereum-overhead/` 仅保留历史参考，不参与当前主线。

关键验证结论：
- stock image 和 custom Lighthouse image 的 devnet 行为无可观察差异：都能出块并 finalize。
- 自定义 Lighthouse 的 propagation instrumentation 能通过 Prometheus/Grafana 看到指标。
- fixture evidence 能进入 Lighthouse runtime state，并影响 score/proposer weight/credit ledger。
- Prompt 13 的 smoke 中，baseline 与 TopoStake skeleton 都能 finalize，说明 skeleton 没破坏 devnet finality。
- Prompt 13 的短窗口观测里，TopoStake fixture path validators `0..3` 的 proposer frequency 明显高于 baseline，说明 proposer weight hook 生效。
- credit ledger 在 devnet-only 模式下守恒：budget/proposer/relay/burned 指标一致，未发现 conservation violation。

Prompt 13 代表性结果：
- devnet 规模：4 个节点，每个节点 32 个 validators，总计 128 validators。
- baseline 与 TopoStake skeleton 均能到 finalized epoch 3 / current justified epoch 4。
- baseline validators `0..3` proposer count：`4/161`。
- TopoStake validators `0..3` proposer count：`31/161`。
- valid path records：`21`。
- duplicate receiver records：`774`，原因是固定 fixture 每个区块都使用同一条 path `0,1,2,3`，同 epoch 内重复 receiver proof 会被去重。
- credit budget：`21000000000` scaled units。
- conservation violation：`0`。

重要边界：
- Prompt 1-13 没有实现真实交易传播路径跟随交易增长。
- Prompt 1-13 的 evidence 主要来自 marker、graffiti root tag、ChainSpec fixture 或 runtime fixture，不是从 geth tx gossip 中自然产生的路径。
- Prompt 1-13 没有把完整 path evidence payload 写进 beacon block，也没有实现 CL P2P sidecar 随区块传播。
- Prompt 1-13 live run 中 BLS signature 仍有 placeholder 阶段，不能当作真实 aggregate BLS verifier 的最终结果。
- Prompt 12 的 credit ledger 是 devnet-only accounting，不改变 validator balance，不做真实 ETH settlement。
- 在 block-level committed evidence 真正接入前，`ETA_SCALED` 仍建议保持 `0` 或只在 devnet fixture 中开启，避免误以为已进入安全的共识路径。

后续阅读顺序：
- Prompt 14：开始把 TopoStake path metadata 嵌入交易传播结构。
- Prompt 15：把路径证明升级到 block-level committed evidence 和 aggregate BLS verification。
- Prompt 16：引入 beacon block body evidence root。
- Prompt 17：做 CL HTTP sidecar payload 最小传输层。
- Prompt 18：做 CL P2P sidecar transport skeleton。

**Prompt 14-18：真实交易路径追踪实现阶段合并摘要**

阶段定位：
- Prompt 14-18 是当前真正按 TopoStake 思路改交易传播路径的阶段。
- 目标是让 path metadata 跟随交易传播增长，进入 block-level evidence object，再由 beacon block commitment 和 CL sidecar 传播给验证节点。
- 这套实现是 custom geth + custom Lighthouse 的 devnet-only fork，不保持 stock client 兼容，也不混跑 stock Lighthouse。
- 当前仍不改变 Ethereum signed transaction RLP、EVM 执行语义、validator balance、finality/attestation weight，也不做真实 ETH reward settlement。

整体链路：
1. custom geth 在 tx gossip envelope 中携带 TopoStake metadata，signed tx bytes 和 tx hash 保持不变。
2. 每个 relay 节点使用独立 TopoStake relay BLS key 对 `chain_id + epoch + tx_hash + edge` 签名，不复用 Ethereum validator consensus key。
3. tx 被选入 block 时，geth 从 block 内交易的 metadata 生成 block evidence object。
4. block evidence object 包含 origin proof、edge sender/receiver proofs、`evidence_root`、aggregate BLS signature。
5. Lighthouse proposer 把 `topostake_evidence_root` 写入 beacon block body，使 evidence root 进入 SSZ/tree hash/block signing root。
6. full evidence payload 不直接塞进 beacon block body，而是通过 CL sidecar cache/API 和后续 CL gossipsub sidecar 按 root 传播。
7. block processing 按 committed root 获取 payload，验证 object root、逐条 BLS signature、aggregate BLS signature，通过后才进入 evidence score/credit 统计。

关键实现约束：
- TopoStake metadata 不写进 signed transaction 本体，所以不会改变 tx hash / sender signature / EVM 执行。
- Ethereum EOA sender 不等于 TopoStake relay identity；path 起点是首次向 devnet gossip 注入该 tx 的 relay validator。
- relay key registry 使用 `validator_index -> relay_pubkey` 映射，score/credit 最终仍映射回 validator index。
- TopoStake path signing 使用独立 domain，例如 `TOPOSTAKE_TX_PATH_V1`，block aggregate 使用 `TOPOSTAKE_BLOCK_EVIDENCE_V1`。
- path evidence 绑定 `chain_id`、`epoch`、`tx_hash`，跨 epoch replay 或签名不匹配都不能进入 score/credit。
- 当前默认 devnet 形态是 `4 nodes * 1 validator * 1 relay key`，避免一个 execution client 代表多个 validators 时 relay identity 不清晰。

Prompt 14 实现摘要：tx gossip metadata carrier
- 工作目录：`clients/go-ethereum-topostake-prompt14`、`clients/lighthouse`。
- go-ethereum tx gossip envelope 增加可选 TopoStake metadata；metadata 跟随 gossip 传播，但不进入 signed tx RLP。
- geth 转发前生成 sender proof，接收方验证 sender proof 后补 receiver proof。
- geth 在 block tx selection / canonical write 时记录 block 内交易的 evidence，并暴露调试 RPC：
  - `topostake_getBlockEvidence(block_hash)`
  - `topostake_latestBlockEvidence()`
- Lighthouse 能从 paired EL RPC 拉取 tx gossip evidence，解析为 `source="tx_gossip_metadata"`，并接入 score/credit metrics。
- Lighthouse 已做真实 BLS path signature verification；坏签名计入 `invalid_signature`，不进入 score/credit。
- 结论：Prompt 14 做到了“交易传播路径随 tx gossip 增长”和“逐条 BLS 验签”，但还没有 beacon block committed root。

Prompt 15 实现摘要：block evidence object + aggregate BLS verification
- geth block evidence object 新增：
  - `evidence_root`
  - `aggregate_signature`
  - `aggregate_signature_count`
- geth 从 block 内 tx metadata 重建 origin proof、edge sender proof、edge receiver proof。
- geth 使用 block evidence domain 计算 root，并聚合 block 内 origin/sender/receiver BLS signatures。
- Lighthouse 拉取 evidence object 后会重算 root、检查 proof count，并执行 aggregate BLS verification。
- 修复了 origin-only tx metadata 的 aggregate 验证边界：origin-only proof 参与 block aggregate，但不进入 relay path score。
- 结论：Prompt 15 完成 object 级 root + aggregate BLS verification；早期 graffiti root tag 方案能 smoke，但仍不是 deterministic block commitment。

Prompt 16 实现摘要：beacon block body evidence root fork
- Lighthouse beacon block body 增加 `topostake_evidence_root: Hash256`。
- 该字段参与 SSZ encode/decode、TreeHash、block body root、block signing root。
- proposer Lighthouse 从 paired/proposer geth 获取 evidence root，并写入 block body。
- graffiti `TPSR:<tag>` 只保留为 debug marker，不再作为唯一 commitment。
- geth evidence store 增加 root index，并暴露：
  - `topostake_getBlockEvidenceByRoot(root)`
- block processing 优先读取 block body 中的 `topostake_evidence_root`，按 root 获取 payload 并验证 root/BLS/aggregate。
- 修复了 custom block body schema 与 stock genesis state 的 body root 不一致问题：custom Lighthouse 启动时归一 genesis latest block header body root。
- 结论：evidence root 已成为 beacon block body 的共识字段；payload 仍主要依赖 geth RPC 按 root 查询。

Prompt 17 实现摘要：CL-owned sidecar cache/API
- Lighthouse 增加 devnet-only CL sidecar cache：`evidence_root -> raw evidence object`。
- proposer block production 阶段从 geth 获取完整 payload 后，把 payload 缓存在 CL sidecar cache。
- Lighthouse HTTP API 增加：
  - `GET /eth/v1/topostake/evidence/{root}`
- block processing 的获取顺序变为：
  - proposer CL sidecar endpoint；
  - local CL sidecar cache/API；
  - proposer geth root-indexed RPC；
  - local geth root-indexed RPC。
- 从 CL sidecar 或 geth RPC 得到的 payload 共用同一套 object root、per-record BLS、aggregate BLS 验证逻辑。
- 结论：full evidence payload 不再只能通过 geth RPC 查；CL 已经能持有并按 committed root 提供 payload。

Prompt 18 实现摘要：CL P2P sidecar transport skeleton
- Lighthouse `lighthouse_network` 增加 `topostake_evidence_sidecar` gossipsub topic。
- 增加 `PubsubMessage::TopoStakeEvidenceSidecar`。
- sidecar payload 携带：
  - `evidence_root: Hash256`
  - payload bytes / JSON bytes
- custom Lighthouse 默认订阅 TopoStake sidecar topic，不加 feature flag。
- proposer Lighthouse 在 block production / block publish 后发布 TopoStake evidence sidecar。
- receiver CL 收到 sidecar 后按 root 写入 CL sidecar cache，block processing 后续从 cache 命中并验证。
- 修复 gossipsub whitelist 后，Topostake sidecar topic 可以被 peers 接受订阅。
- metrics 区分：
  - `local_cache_ok`
  - `cl_sidecar_ok`
  - `p2p_sidecar_ok`
- 结论：full evidence payload 已经可以通过 Lighthouse CL gossipsub sidecar 扩散；验证节点收到 sidecar 后缓存、按 committed root 验证，并进入 TopoStake evidence 统计。

保留的复现配置与工作区：
- custom geth：`clients/go-ethereum-topostake-prompt14`
- custom Lighthouse：`clients/lighthouse`
- 4 nodes * 1 validator args：`results/raw/topostake-devnet-4node-1validator-custom-geth-private.yaml`
- relay public registry：`results/processed/topostake_relay_key_registry.json`
- relay private registry：`results/raw/topostake_relay_keys_private.json`
- geth image：`topostake/geth:dev`
- Lighthouse image：`topostake/lighthouse:dev`
- patch 记录：
  - `patches/go-ethereum-topostake-tx-metadata-carrier.patch`
  - `patches/lighthouse-topostake-prompts-6-14.patch`

最小复现命令：

```bash
cargo run --bin topostake_relay_registry -- \
  --chain-id 7032030 \
  --count 4 \
  --public-out results/processed/topostake_relay_key_registry.json \
  --private-out results/raw/topostake_relay_keys_private.json

cd clients/go-ethereum-topostake-prompt14
GOCACHE=/tmp/go-build-cache GOTMPDIR=/tmp go test ./eth/topostake ./core -count=1
GOCACHE=/tmp/go-build-cache GOTMPDIR=/tmp make geth

cd /home/wujian/pog-rs/clients/lighthouse
cargo fmt --check
cargo check -p lighthouse_network -p network -p http_api -p state_processing -p beacon_chain
cargo test -p lighthouse_network topostake -- --nocapture
cargo test -p state_processing topostake_tx_gossip_metadata_requires_real_bls_signatures -- --nocapture
cargo build -p lighthouse --release

cd /home/wujian/pog-rs
GETH_BINARY=/home/wujian/pog-rs/clients/go-ethereum-topostake-prompt14/build/bin/geth ./scripts/geth_image.sh package-local
./scripts/lighthouse_image.sh package-local
./scripts/geth_image.sh verify
./scripts/lighthouse_image.sh verify

kurtosis enclave rm -f topostake-devnet-prompt18-p2p-sidecar
HOME=/tmp \
KURTOSIS_PACKAGE=/tmp/ethereum-package \
CUSTOM_ARGS=/home/wujian/pog-rs/results/raw/topostake-devnet-4node-1validator-custom-geth-private.yaml \
CUSTOM_ENCLAVE=topostake-devnet-prompt18-p2p-sidecar \
./scripts/kurtosis_devnet.sh start-custom
```

关键验收指标：

```text
beacon_finalized_epoch
beacon_participation_prev_epoch_source_attesting_gwei_total
topostake_tx_metadata_created
topostake_tx_metadata_forwarded
topostake_tx_metadata_received
topostake_tx_metadata_signed_origin
topostake_tx_metadata_signed_sender
topostake_tx_metadata_signed_receiver
topostake_tx_metadata_verified_sender_ok
topostake_tx_metadata_verified_sender_fail
topostake_tx_metadata_invalid
topostake_block_evidence_recorded
topostake_block_evidence_txs
topostake_tx_evidence_paths_fetched_total{outcome="p2p_sidecar_ok"}
topostake_tx_evidence_paths_fetched_total{outcome="cl_sidecar_ok"}
topostake_tx_evidence_paths_fetched_total{outcome="local_cache_ok"}
topostake_tx_evidence_paths_fetched_total{outcome="invalid_signature"}
topostake_tx_evidence_paths_fetched_total{outcome="invalid_block_aggregate"}
topostake_tx_evidence_paths_fetched_total{outcome="invalid_committed_root"}
topostake_evidence_sources_total{source="tx_gossip_metadata"}
topostake_evidence_paths_total{outcome="valid"}
topostake_evidence_paths_total{outcome="duplicate_receiver"}
topostake_evidence_epoch_invalid_paths
```

代表性 smoke 结果：
- Prompt 14：4 nodes * 1 validator devnet 能出块并 finalize；tx metadata created/forwarded/received 与 BLS signed edge 指标非空。
- Prompt 15：aggregate BLS verification smoke 后，`invalid_block_aggregate` 和 `invalid_signature` 未出现，`tx_gossip_metadata` valid evidence 非空。
- Prompt 16：head block body 可看到非零 `topostake_evidence_root`；用该 root 调 `topostake_getBlockEvidenceByRoot(root)` 能拿回完全匹配的 payload。
- Prompt 17：`GET /eth/v1/topostake/evidence/{root}` 能按 committed root 返回 full evidence object；`cl_sidecar_ok` 增长。
- Prompt 18：`p2p_sidecar_ok`、`local_cache_ok`、`cl_sidecar_ok` 都能增长；`valid` evidence 非空；`invalid_signature`、`invalid_block_aggregate`、`invalid_committed_root` 未观察到。

当前完成度：
- 已完成真实 tx gossip path metadata carrier。
- 已完成 per-hop BLS signing / verification。
- 已完成 block-level evidence object。
- 已完成 aggregate BLS verification。
- 已完成 beacon block body evidence root commitment。
- 已完成 CL-owned sidecar cache/API。
- 已完成 CL gossipsub sidecar transport skeleton。
- 已完成 evidence root -> payload -> root/BLS/aggregate verification -> score/credit metrics 的闭环。

当前边界与风险：
- full payload 仍是 devnet-minimal sidecar，尚不是正式以太坊规范级 data availability / req-resp 设计。
- payload 缺失或验证失败目前只丢弃 TopoStake evidence，不拒绝 Ethereum block。
- `ETA_SCALED` 仍建议保持 `0`，除非明确进入“committed evidence 驱动 proposer selection”的专门实验。
- 4 nodes * 1 validator / mainnet preset 下 finality 可能不稳定；这属于极小 validator 配置问题，不一定代表 sidecar 传播失败。若要把 finality 作为强验收，应改回更多 validators 或调最小化 preset。
- 当前不做 BA 拓扑、网络延迟注入、10-node 扩展、真实 relay reward settlement。
- 当前不改变 validator balance，也不把 TopoStake credit 结算成真实 ETH 奖励。

下一步建议：
- 若目标是论文实现完整度：补 CL req-resp sidecar retrieval，解决 sidecar miss 时的可恢复获取问题。
- 若目标是实验评估：先固定 validators 数量和 preset，跑稳定 finality + overhead + propagation latency 数据。
- 若目标是进入激励实验：在 committed evidence 稳定后，再单独打开 `ETA_SCALED`，让 proposer selection 读取 TopoStake score。
