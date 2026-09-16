# CodeAgent / free-code 长期记忆评测：项目状态与下一步

> 最后更新：2026-09-15。本文是本分支的权威状态入口。状态冲突时以本文为准。

## 1. 最终目标

建立一套可复现的 LongMemEval-V2 端到端回归评测。被测 Agent 可以开源或闭源，统一视为不可修改的黑盒；产品适配代码只放在 LongMemEval-V2 中。评测用于判断 CodeAgent / free-code 及其他 Agent 的原生长期记忆是否真正有效：

1. 历史工作 session 中值得复用的事实、流程、变化和失败经验能否被正确写入；
2. 后续全新 session 能否只依赖冻结记忆回答问题；
3. 不同 CodeAgent commit 独立留存的单臂结果在准确率、UNKNOWN、耗时、Token、费用和失败率上有何变化；
4. 修改前后由不同包分别执行，结果在运行外按相同题单和配置比较；
5. 评测过程是否接近真实产品使用，而不是主要测量 agent 阅读离线日志文件的能力。

发布目标是完整 small（web 240 题、enterprise 211 题，共 451 题）。同一个 commit 分别运行 Web 和 Enterprise 两个独立长任务：每个领域先从共享的 100 条轨迹构建一份冻结记忆，再回答该领域全部问题。进入 full small 前必须先通过固定 10 题 calibration；当前禁止直接把 experimental historical-session PoC 扩展到 small。

## 2. 当前代码能力

LongMemEval-V2 当前已经具备：

- 通用 `NativeMemoryAgent` 黑盒生命周期和 `NativeMemoryCapabilities` 能力声明；
- harness 通过通用 native-memory 类型注入隔离目录、加载冻结状态和恢复构建，不再以 `codeagent_auto_memory` 产品名硬编码这些行为；
- `codeagent_auto_memory` 已作为 `codeagent_cli` 适配器接入；默认 `trajectory_file` 可直接调用未修改的原版 CLI；新增 `conversation_prompt` 黑盒快速路径，可将一批 trajectory 在 harness 外部确定性转换为 compact 历史 session prompt 文件后，通过一次 CLI `-p` 短指令批量摄取；
- 默认按 CLI commit 独立执行、留存和恢复的 `single` 单臂评测；
- Web 与 Enterprise 分领域构建、冻结和加载各自的共享记忆；
- `--memory-off` 可将同一个 single 入口切换为无记忆单次测评；
- 每次完成后生成 `evaluation_result.json` 和 `report.html`；页面可同时加载多次独立结果进行比较；
- smoke、固定 10 题 calibration 和 full small 入口；
- 完整 haystack、共享领域记忆、保存/加载冻结状态和 `--resume`；
- launcher、版本、提示词 SHA、trajectory 指纹、Token、费用、耗时和 memory snapshot 审计；
- `codeagent` 与 `free_code` 两种环境变量方言；
- Windows/Linux 下 Node/Bun 跨平台入口。

free-code PoC 分支额外加入 headless extraction 初始化、退出前 drain、显式 benchmark historical-session gate，以及 benchmark-only typed `Message[]` importer。LongMemEval runner 已可通过 `--ingestion-strategy historical_session` 选择该路径，并结构化留存 extraction 状态、turns、Token、费用、写入路径和 `mainAgentTurns=0` 断言。该路径现在只作为修改版客户端研究分支，不是通用协议要求；闭源 Agent 和原版 CLI 应优先使用 `trajectory_file` 或 `conversation_prompt`。

## 3. 当前阻塞问题

### 3.1 正式文件摄取路径正确但过慢

正式 `codeagent_auto_memory` 为每条 trajectory 创建独立 session，把 `trajectory.json` 和截图放入临时目录，让主 agent 自行读取、理解并写入 native memory。

完整 100 条实测：构建 12,729.5 秒（3.54 小时）；1,599 turns，平均约 16 turns/trajectory；70 次有效写入、30 次空写入、1 次失败重试；单臂费用约 $46.56。session 隔离和顺序符合目标，但耗时混入大量文件探索、工具往返和主 agent 推理。

### 3.2 旧单消息 Historical-session PoC 快但记忆覆盖失败

PoC 将 trajectory 确定性转换成 normalized events，丢弃 thought，通过 stdin 注入独立 headless session，然后由 background `extractMemories` 写入共享 memory。

完整非图片题 `05cce9b3` 的 100 条验证：

- 100/100 session 最终成功；
- 成功 session 累计 1,235.6 秒（20.6 分钟）；计入一次 300 秒偶发超时约 25.6 分钟；
- 平均 12.36 秒，中位 9.48 秒，P95 27.45 秒；
- 只有 2/100 session 修改 memory，最终仅 1 个事实文件和 index；
- 查询 3.21 秒，返回 `UNKNOWN`，标准答案为 `Login as Customer`。

结论：速度比正式路径快约 8～10 倍，但“单个 stdin user message 包装 normalized events”不等价于真实多轮 transcript，不能用于正式评测。

2026-09-14 已完成替代实现：Python 将 trajectory 确定性转换为成对的 synthetic `browser_observe` / `browser_action` tool use/result，free-code 在正常 headless 初始化后直接校验 typed schema、构造内部 `Message[]` 并调用 extraction，不再进行返回 `OK` 的主模型调用。无模型单元测试、完整 Python 测试和 `dev-full` 构建已通过；尚未进行真实 3 条门禁，因此不能宣称记忆覆盖问题已经解决。

### 3.3 Conversation-prompt 黑盒快速路径

2026-09-15 已新增 `conversation_prompt` ingestion strategy。最初版本逐 trajectory 调用 agent，真实 smoke 显示单题耗时和 turn 数仍会随轨迹数线性增长。2026-09-16 已改为 batch ingestion：LongMemEval-V2 侧先把同一 haystack 的多条 trajectory 确定性转换为 `conversation_prompt_batch.txt`，只保留 goal、URL、action、关键可见文本、控件、表单值、alert 和 outcome，再经 CLI `-p` 传入短指令要求被测 Agent 读取该外部转换结果并写入 native memory。该路径不再每条轨迹调用一次 agent；`ingestion_metrics.attempt_count` 记录 agent 调用次数，`trajectory_count` 记录覆盖轨迹数。

该路径不要求修改客户端源码，理论上可用于 CodeAgent、free-code、opencode、pi 和闭源 CLI；但它仍是 prompt 翻译后的历史记录，不是原生 tool transcript。进入正式对比前必须先通过固定 3 条、完整 100 条单题和固定 10 题 calibration，不能把 `--haystack-limit` 或未门禁结果当 benchmark score。

### 3.4 其他已知问题

- 部分 accessibility tree 会超过上下文；PoC 的确定性字符预算可能丢失中部证据。
- 当前 PoC 为取得正常 `REPLHookContext` 仍有一次只回答 `OK` 的主模型调用。
- extraction fork 的 Token、费用和写入原因尚未进入结构化 stdout。
- full small runner 串行执行；在记忆正确性解决前不应优先做并发优化。
- `memory_off` 在隔离的新问题 session 中没有记忆文件，也没有其他轨迹上下文。完整遍历 haystack 不会改变查询可用信息，因此不再作为日常 full-small 对照；只保留极小 smoke 验证无隐藏持久化和无记忆写入。

## 4. 已验证与未验证边界

已验证：每条 trajectory 可以使用独立 session 并只共享 auto-memory；headless extraction 可以写入指定 memory；query 前必须完成初始化，退出前必须 drain；Windows 输入必须使用 UTF-8；100 条可以断点续跑；当前单消息 PoC 速度可接受但答案能力不合格。

已实现但尚未通过真实门禁：`conversation_prompt` 黑盒快速路径；内部 `Message[]` importer、synthetic browser tool schema、结构化 extraction 结果及 runner 集成。尚未验证：固定 3 条的记忆覆盖与速度；完整 100 条单题召回；10 题 calibration；修改前后两个包的独立 single 结果；完整 small 的稳定耗时和费用。

## 5. 下一阶段实施计划

### P0：黑盒原生记忆适配层

1. [x] 新增通用 `NativeMemoryAgent` 生命周期基类；
2. [x] 新增可审计的 `NativeMemoryCapabilities`；
3. [x] harness 去除 native-memory runtime 注入和 resume 判定中的产品名硬编码；
4. [x] 将现有 CodeAgent/free-code 实现迁移为 `codeagent_cli` 适配器；
5. [x] 在 ingestion manifest 中记录适配器和能力；
6. [ ] 增加首个非 CodeAgent 或闭源 Agent 适配器，验证协议的第二实现。

完整接入边界见[原生记忆 Agent 黑盒适配协议](native_memory_agent_adapter.zh-CN.md)。

### 可选研究：真正的内部历史 Session Importer

1. [x] 在 free-code 内增加 benchmark-only typed input schema；
2. [x] 将 `goal` 转为 user message，将 observation/action 转为有序 synthetic tool result/tool use；
3. [x] 每条 trajectory 构造真实内部 `Message[]` 和确定性独立 session ID；
4. [x] 复用正常 CLI 初始化后的 context 与权限；
5. [x] 直接调用 memory extraction，不调用主回答模型；
6. [x] 等待 extraction 并输出结构化结果；
7. [x] 区分无价值、跳过、未初始化和失败，禁止静默成功；
8. [ ] 用真实模型通过固定 3 条门禁。

验收：固定 3 条中主模型 turns 为 0，关键事实覆盖不低于文件摄取路径，耗时降低 50% 以上。

### P1：输入预算和可比性

统计轨迹 Token 分布；优先使用消息级上下文管理而非头尾截断；保存截断规则、原始哈希和清单；修改前后两个包使用字节一致输入；默认不注入 `thought`，截图策略单独版本化。`conversation_prompt` 与 `trajectory_file` 是当前最可行的通用黑盒路径；`historical_session` 仅用于修改版 free-code 上限研究。

### P2：分级验证

依次运行固定 3 条、完整 100 条单题、固定 10 题 calibration、web/small、enterprise/small。每个 CLI commit 独立留存 `evaluation_result.json`，HTML/离线工具再按相同题单和配置加载两个单次结果；关键版本需要重复运行以估计随机波动。任一级准确率、UNKNOWN、写入率、失败率或成本不达标，不进入下一级。

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
node evaluation/scripts/run_codeagent_memory_eval.mjs --preset smoke --data-root data/longmemeval-v2 --output-root runs/environment_smoke --runtime free_code --launcher '["D:/aispace/free-code/cli-dev.exe"]' --cli-repo D:/aispace/free-code
```

## 7. 环境就绪的确定标志

以下项目必须全部成立：

- 数据校验退出码为 0；
- CLI `--version` 已记录，launcher 使用绝对路径或完整 argv；
- `--dry-run` 中 domain、tier、题目、haystack 和 launcher 符合预期；
- single smoke 生成 ingestion manifest/metrics、逐题 JSONL、`evaluation_result.json` 和 `report.html`；
- Web/Enterprise 使用独立 memory state，query session 不能访问 trajectory；
- prompt hash、trajectory fingerprints、版本标签和 detected version 非空；
- 失败、超时、空写入和重试数可从产物重算；
- 模型名称符合计划。本次 PoC 为 `deepseek-flash`，同一实验不得混入 Pro；
- `conversation_prompt` 必须保存 `conversation_prompt_batch.txt`，且固定门禁中 `attempt_count` 不能随轨迹数线性增长，才可进入正式 small；
- experimental historical-session 必须返回结构化 extraction 状态且召回答案通过，才可标记成功。

## 8. 文档导航

- 设计背景：[目标](codeagent_memory_regression_evaluation_goal.zh-CN.md)、[设计](codeagent_memory_regression_evaluation_design.zh-CN.md)
- 环境与运行：[环境手册](codeagent_memory_evaluation_environment_runbook.zh-CN.md)、[手动测试](codeagent_auto_memory_manual_test.zh-CN.md)
- Historical-session：[方案与实验](free_code_historical_session_ingestion.zh-CN.md)
- 工程历史：[迁移计划](codeagent_memory_regression_migration_plan.zh-CN.md)
- 全部文档：[分类索引](README.zh-CN.md)
