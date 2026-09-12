# CodeAgent / free-code 长期记忆评测：项目状态与下一步

> 最后更新：2026-09-12。本文是本分支的权威状态入口。状态冲突时以本文为准。

## 1. 最终目标

建立一套可复现的 LongMemEval-V2 端到端回归评测，用于判断 CodeAgent / free-code 的原生长期记忆改造是否真正改善：

1. 历史工作 session 中值得复用的事实、流程、变化和失败经验能否被正确写入；
2. 后续全新 session 能否只依赖冻结记忆回答问题；
3. 改造前 baseline 与改造后 candidate 的准确率、UNKNOWN、耗时、Token、费用和失败率有何变化；
4. 变化来自写入、召回，还是两者交互；
5. 评测过程是否接近真实产品使用，而不是主要测量 agent 阅读离线日志文件的能力。

发布目标是完整 small（web 240 题、enterprise 211 题，共 451 题），但必须先通过固定 10 题 calibration。当前禁止直接把 experimental historical-session PoC 扩展到 small。

## 2. 当前代码能力

LongMemEval-V2 当前已经具备：

- `memory_off`、`baseline`、`candidate` 三组端到端回归；
- 写入 A/B × 召回 A/B 的 2×2 归因；
- smoke、固定 10 题 calibration 和 full small 入口；
- 完整 haystack、共享领域记忆、保存/加载冻结状态和 `--resume`；
- launcher、版本、提示词 SHA、trajectory 指纹、Token、费用、耗时和 memory snapshot 审计；
- `codeagent` 与 `free_code` 两种环境变量方言；
- Windows/Linux 下 Node/Bun 跨平台入口。

free-code PoC 分支额外加入 headless extraction 初始化、退出前 drain 和显式 benchmark historical-session gate。

## 3. 当前阻塞问题

### 3.1 正式文件摄取路径正确但过慢

正式 `codeagent_auto_memory` 为每条 trajectory 创建独立 session，把 `trajectory.json` 和截图放入临时目录，让主 agent 自行读取、理解并写入 native memory。

完整 100 条实测：构建 12,729.5 秒（3.54 小时）；1,599 turns，平均约 16 turns/trajectory；70 次有效写入、30 次空写入、1 次失败重试；单臂费用约 $46.56。session 隔离和顺序符合目标，但耗时混入大量文件探索、工具往返和主 agent 推理。

### 3.2 Historical-session PoC 快但记忆覆盖失败

PoC 将 trajectory 确定性转换成 normalized events，丢弃 thought，通过 stdin 注入独立 headless session，然后由 background `extractMemories` 写入共享 memory。

完整非图片题 `05cce9b3` 的 100 条验证：

- 100/100 session 最终成功；
- 成功 session 累计 1,235.6 秒（20.6 分钟）；计入一次 300 秒偶发超时约 25.6 分钟；
- 平均 12.36 秒，中位 9.48 秒，P95 27.45 秒；
- 只有 2/100 session 修改 memory，最终仅 1 个事实文件和 index；
- 查询 3.21 秒，返回 `UNKNOWN`，标准答案为 `Login as Customer`。

结论：速度比正式路径快约 8～10 倍，但“单个 stdin user message 包装 normalized events”不等价于真实多轮 transcript，不能用于正式评测。

### 3.3 其他已知问题

- 部分 accessibility tree 会超过上下文；PoC 的确定性字符预算可能丢失中部证据。
- 当前 PoC 为取得正常 `REPLHookContext` 仍有一次只回答 `OK` 的主模型调用。
- extraction fork 的 Token、费用和写入原因尚未进入结构化 stdout。
- full small runner 串行执行；在记忆正确性解决前不应优先做并发优化。
- `memory_off` 仍遍历 haystack，语义和成本可以进一步简化。

## 4. 已验证与未验证边界

已验证：每条 trajectory 可以使用独立 session 并只共享 auto-memory；headless extraction 可以写入指定 memory；query 前必须完成初始化，退出前必须 drain；Windows 输入必须使用 UTF-8；100 条可以断点续跑；当前单消息 PoC 速度可接受但答案能力不合格。

尚未验证：内部 `Message[]` importer 的记忆覆盖；synthetic browser tool schema 的兼容边界；10 题 calibration；真实 baseline/candidate A/B；完整 small 的稳定耗时和费用。

## 5. 下一阶段实施计划

### P0：真正的内部历史 Session Importer

1. 在 free-code 内增加 benchmark-only typed input schema；
2. 将 `goal` 转为 user message，将 observation/action 转为有序 synthetic tool result/tool use；
3. 每条 trajectory 构造真实内部 `Message[]` 和新 session ID；
4. 复用正常 CLI 初始化后的 context 与权限；
5. 直接调用 memory extraction，不调用主回答模型；
6. 等待 extraction 并输出结构化结果；
7. 区分无价值、无写入、超时和失败，禁止静默成功。

验收：固定 3 条中主模型 turns 为 0，关键事实覆盖不低于文件摄取路径，耗时降低 50% 以上。

### P1：输入预算和可比性

统计轨迹 Token 分布；优先使用消息级上下文管理而非头尾截断；保存截断规则、原始哈希和清单；baseline/candidate 使用字节一致输入；默认不注入 `thought`，截图策略单独版本化。

### P2：分级验证

依次运行固定 3 条、完整 100 条单题、固定 10 题 calibration、web/small、enterprise/small，最后开展 baseline/candidate 重复运行统计。任一级准确率、UNKNOWN、写入率、失败率或成本不达标，不进入下一级。

## 6. 新环境搭建

完整说明见[测评环境运行手册](codeagent_memory_evaluation_environment_runbook.zh-CN.md)。最小环境包括 Git、Python 3.11、Node.js 或 Bun、完整数据、可运行 CLI、模型凭据和全新隔离输出目录。

free-code：

```powershell
git clone https://github.com/Nick23rd/free-code.git D:/aispace/free-code
Set-Location D:/aispace/free-code
bun install
bun run build:dev:full
./cli-dev.exe --version
```

LongMemEval-V2：

```powershell
git clone https://github.com/Nick23rd/LongMemEval-V2.git D:/aispace/LongMemEval-V2
Set-Location D:/aispace/LongMemEval-V2
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -e .
./.venv/Scripts/python.exe data/validate_data.py --data-root data/longmemeval-v2 --tier small
node evaluation/scripts/run_codeagent_memory_eval.mjs regression --preset smoke --data-root data/longmemeval-v2 --output-root runs/environment_smoke --runtime free_code --memory-off-launcher '["D:/aispace/free-code/cli-dev.exe"]' --baseline-launcher '["D:/aispace/free-code/cli-dev.exe"]' --candidate-launcher '["D:/aispace/free-code/cli-dev.exe"]'
```

## 7. 环境就绪的确定标志

以下项目必须全部成立：

- 数据校验退出码为 0；
- CLI `--version` 已记录，launcher 使用绝对路径或完整 argv；
- `--dry-run` 中 domain、tier、题目、haystack 和 launcher 符合预期；
- smoke 生成 ingestion manifest/metrics、逐题 JSONL 和报告；
- `memory_off` memory 文件数和字节数均为 0；
- baseline/candidate memory 隔离，query session 不能访问 trajectory；
- prompt hash、trajectory fingerprints、版本标签和 detected version 非空；
- 失败、超时、空写入和重试数可从产物重算；
- 模型名称符合计划。本次 PoC 为 `deepseek-flash`，同一实验不得混入 Pro；
- experimental historical-session 必须返回结构化 extraction 状态且召回答案通过，才可标记成功。

## 8. 文档导航

- 设计背景：[目标](codeagent_memory_regression_evaluation_goal.zh-CN.md)、[设计](codeagent_memory_regression_evaluation_design.zh-CN.md)
- 环境与运行：[环境手册](codeagent_memory_evaluation_environment_runbook.zh-CN.md)、[手动测试](codeagent_auto_memory_manual_test.zh-CN.md)
- Historical-session：[方案与实验](free_code_historical_session_ingestion.zh-CN.md)
- 工程历史：[迁移计划](codeagent_memory_regression_migration_plan.zh-CN.md)
- 全部文档：[分类索引](README.zh-CN.md)
