可以，下面这套 prompt 你可以直接丢给 Codex。建议按顺序来，别一上来就让它改 Ethereum 共识。

**Prompt 1：先跑通 Kurtosis Ethereum Devnet**

```text
你现在在 TopoStake 项目的 revision-v2 分支工作。

目标：搭建一个 Kurtosis Ethereum private PoS devnet prototype，用来后续测试 TopoStake 的 path evidence / BLS overhead。当前不要修改 Ethereum 共识规则。

请完成：
1. 在仓库中新建 `kurtosis/` 目录。
2. 创建一个 Kurtosis args 文件，例如 `kurtosis/topostake-devnet.yaml`。
3. 配置一个小型 private Ethereum PoS devnet：
   - execution client: geth
   - consensus client: lighthouse
   - 4 个 participant/node
   - 启用 transaction spammer
   - 启用 Prometheus/Grafana 或 package 支持的 monitoring
4. 创建 `kurtosis/README.md`，写清楚：
   - 安装依赖：Docker、Kurtosis CLI
   - 启动命令
   - 查看服务端口命令
   - 停止/清理命令
   - 如何确认 devnet 正常出块和 finalize
5. 如果本机没有 Docker 或 Kurtosis，不要失败退出；请仍然生成配置和 README，并说明哪些命令未能实际运行。
6. 不要改 TopoStake simulator 代码，不要改 Ethereum client 源码。

验证：
- 如果环境支持，运行一次 Kurtosis devnet。
- 如果不能运行，至少执行配置文件结构检查或说明无法运行的原因。
```

**Prompt 2：支持自定义 Lighthouse 镜像**

```text
继续在 TopoStake revision-v2 仓库中工作。

目标：让 Kurtosis devnet 可以替换为自定义 Lighthouse consensus client image。当前仍然不要修改 Ethereum 共识，只做“可替换镜像”的工程准备。

请完成：
1. 修改或新增 `kurtosis/topostake-devnet-custom-lighthouse.yaml`。
2. 在 participant 配置中支持：
   - el_type: geth
   - cl_type: lighthouse
   - cl_image: 一个可配置的自定义 Lighthouse Docker image，例如 `topostake/lighthouse:dev`
3. 在 `kurtosis/README.md` 中新增章节：
   - 如何 clone Lighthouse
   - 如何 build 自定义 Docker image
   - 如何把 image 名称填入 Kurtosis args
   - 如何启动 custom Lighthouse devnet
4. 新增一个脚本 `scripts/kurtosis_devnet.sh` 或 `scripts/kurtosis_devnet.py`，支持：
   - `start-default`
   - `start-custom`
   - `status`
   - `clean`
5. 脚本要尽量跨平台；如果写 shell 脚本，README 里也给出手动命令。
6. 不要实现 TopoStake proposer selection，不要改 beacon state transition。

验证：
- 能 dry-run 或打印将要执行的 Kurtosis 命令。
- 如果 Kurtosis 可用，尝试启动 default devnet。
```

**Prompt 3：做 TopoStake-over-Ethereum 开销原型**

```text
继续在 TopoStake revision-v2 仓库中工作。

目标：做一个 TopoStake-over-Ethereum prototype，用 Ethereum private PoS devnet 测 path evidence / BLS / metadata overhead。不要改 Ethereum 共识规则。

设计原则：
- Ethereum consensus 保持原样。
- TopoStake path evidence 作为 external metadata / calldata / sidecar log 来测试开销。
- simulator 仍然负责完整激励和安全边界实验；Kurtosis devnet 只验证真实 PoS client 环境下的部署开销。

请完成：
1. 在 `prototype/ethereum-overhead/` 下新增原型代码。
2. 写一个 transaction spammer 或 wrapper：
   - 向 devnet 发送普通交易；
   - 每笔交易附带模拟 TopoStake path evidence metadata；
   - metadata 至少包含 path length、relay identities、aggregate signature placeholder 或真实 BLS bytes。
3. 写一个 verifier 工具：
   - 从交易 calldata 或日志中读取 metadata；
   - 测量每个 block 的 metadata bytes；
   - 测量 per-path verification time；
   - 估算 block-level verification overhead。
4. 输出 CSV 到 `results/processed/ethereum_devnet_overhead.csv`，至少包含：
   - run_id
   - block_number
   - tx_count
   - path_length
   - metadata_bytes_per_tx
   - metadata_bytes_per_block
   - verify_ms_per_path
   - estimated_verify_ms_per_block
5. 生成论文表格或 markdown summary：
   - `results/processed/ethereum_devnet_overhead_table.md`
6. 在 `kurtosis/README.md` 中说明：
   - 这个实验验证的是 deployment overhead；
   - 它不声称完整实现 TopoStake consensus；
   - proposer selection / relay reward / epoch score 仍在 simulator 中评估。

验证：
- 如果 devnet 可运行，跑一个小实验：4 nodes，若干 blocks，path length 1/2/4/8。
- 如果 devnet 不可运行，至少提供本地 dry-run 和 mock input 测试。
```

**Prompt 4：只做 Ethereum 共识修改可行性调研**

```text
继续在 TopoStake revision-v2 仓库中工作。

目标：调研如果要在 Lighthouse 中完整实现 TopoStake，需要改哪些模块。不要大规模改代码，只做最小 spike 和文档。

请完成：
1. clone 或定位 Lighthouse 源码。
2. 找出以下逻辑所在文件/模块：
   - proposer selection
   - validator duties
   - beacon state epoch transition
   - block production
   - block verification/import
   - reward accounting
   - gossip / block propagation metrics
3. 写文档 `docs/LIGHTHOUSE_TOPOSTAKE_INTEGRATION_PLAN.md`。
4. 文档中说明：
   - 哪些 TopoStake 功能可以作为外部 sidecar/prototype 实现；
   - 哪些必须修改 consensus client；
   - 如果修改 proposer selection，为什么所有 devnet consensus clients 都必须运行兼容版本；
   - 最小可行修改路线；
   - 风险和工作量估计。
5. 不要尝试一次性实现完整 TopoStake consensus。
6. 如果做代码 spike，只允许加 instrumentation 或 feature flag skeleton，不要破坏 Lighthouse 默认行为。

验证：
- 给出定位到的文件路径和函数名。
- 给出后续真正实现时的任务拆分。
```

我建议你先给 Codex 跑 **Prompt 1**。等它能生成配置并尽量跑通 devnet，再跑 Prompt 2。Prompt 3 才是能写进论文的 prototype overhead 实验。
