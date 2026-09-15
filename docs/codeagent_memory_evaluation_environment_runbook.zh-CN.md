# CodeAgent 记忆评测环境运行手册

> 开始前先阅读[项目状态与下一步](codeagent_memory_project_status.zh-CN.md)。截至 2026-09-15，默认流程是按 CLI commit 独立留存的 `single` 单臂评测。通用黑盒摄取路径是 `trajectory_file` 和 `conversation_prompt`；modified-client `historical_session` 仅保留为 free-code 上限研究。在固定 10 题 calibration 通过前，不运行 full small。

被测 Agent 默认作为不可修改的黑盒。统一生命周期和闭源产品接入约束见[原生记忆 Agent 黑盒适配协议](native_memory_agent_adapter.zh-CN.md)。原版 CodeAgent/free-code 及其他 CLI 优先使用 `trajectory_file` 或 `conversation_prompt`；只有明确测试修改版 free-code importer 时才启用 `historical_session`。

## 1. 执行模型

同一个 CLI commit 的完整 small 由两个独立长任务组成：

```text
Web：100 条共享轨迹 → 构建并冻结 Web 记忆 → 回答 240 题
Enterprise：100 条共享轨迹 → 构建并冻结 Enterprise 记忆 → 回答 211 题
```

两个领域必须使用不同运行目录和 memory state。每次运行记录 commit、dirty 状态、launcher、提示词哈希、轨迹指纹、Token、费用、耗时和失败审计。修改前后版本分别运行，之后按相同领域、题单和配置离线配对。

执行入口只支持单次测评。修改前和修改后的包分别通过 `--launcher` 运行；不再由 runner 启动三臂或四象限任务。需要无记忆控制时，在同一命令上增加 `--memory-off`。无记忆模式只做极小 smoke 验证无泄漏，不运行完整 haystack/full-small。

## 2. 环境检查

在仓库根目录运行：

```bash
python -m pytest -q
node --version
codeagentcli --version
codeagentcli -p --output-format json --no-session-persistence --max-turns 1 "Reply OK only."
```

确认以下文件存在：

```text
data/longmemeval-v2/questions.jsonl
data/longmemeval-v2/trajectories.jsonl
data/longmemeval-v2/haystacks/lme_v2_small.json
```

## 3. 默认 single 命令

先用 `--dry-run` 和 smoke 检查选择、launcher 与输出目录。源码 launcher 可由 Git 仓库自动解析 commit：

```powershell
node evaluation/scripts/run_codeagent_memory_eval.mjs --preset smoke `
  --data-root data/longmemeval-v2 --output-root runs/codeagent_memory `
  --runtime free_code `
  --launcher '["bun","D:/aispace/free-code/src/entrypoints/cli.tsx"]' `
  --cli-repo D:/aispace/free-code --dry-run
```

打包 CLI 不在 Git checkout 中时必须传 `--commit-hash`。不要用无法追溯 commit 的结果进行版本对比。

校准通过后，分别运行两个领域：

```powershell
node evaluation/scripts/run_codeagent_memory_eval.mjs --preset small `
  --domain web --data-root data/longmemeval-v2 `
  --output-root runs/codeagent_memory --runtime free_code `
  --launcher '["bun","D:/aispace/free-code/src/entrypoints/cli.tsx"]' `
  --cli-repo D:/aispace/free-code --confirm-full-run

node evaluation/scripts/run_codeagent_memory_eval.mjs --preset small `
  --domain enterprise --data-root data/longmemeval-v2 `
  --output-root runs/codeagent_memory --runtime free_code `
  --launcher '["bun","D:/aispace/free-code/src/entrypoints/cli.tsx"]' `
  --cli-repo D:/aispace/free-code --confirm-full-run
```

每次运行产生：

```text
<OutputRoot>/<UTC时间>_<commit前12位>[_dirty]/
  runner_config.json
  build/memory_state/
  evaluate/per_question.jsonl
  evaluate/aggregated_metrics.json
  evaluation_result.json
  report.html
```

`evaluation_result.json` 是供 HTML/前端消费的完整 JSON 文档，包含运行身份、数据选择、聚合指标、构建信息和逐题记录；页面无需解析 JSONL。
直接打开任意一次运行目录中的 `report.html`，一次选择或拖入多份
`evaluation_result.json`，即可在同一页面比较总体/分类准确率、UNKNOWN、构建与查询耗时、Token，以及逐题改进和退化。页面只在浏览器本地读取文件，不上传数据。
仓库中的 `evaluation/codeagent_memory_results.html` 是同一个查看器，可直接用于已有 JSON 结果。

## 4. 当前时间与有效性边界

真实 trajectory-file 路径的 100 条构建实测为 12,729.5 秒（3.54 小时）。唯一完整单题查询样本约 287 秒；据此粗略外推，Web + Enterprise 串行约 43 小时，应保守预留 40～50 小时。该查询样本量只有 1，正式启动前必须先用冻结记忆连续跑固定 10 题重新估计。

historical-session PoC 的 100 条构建约 20～26 分钟，但它把 normalized events 包装成单个 stdin user message，只有 2/100 session 修改 memory，最终查询返回 `UNKNOWN`。它证明了速度方向，不证明记忆质量；默认 `single` 目前不使用该路径。

`conversation_prompt` 是新的通用快速路径：harness 外部把 trajectory 转为普通历史 browser session prompt，保存为 `conversation_prompt.txt`，再通过 CLI `-p` 传入短指令让 Agent 读取该转换结果。这样避开 Windows 长 argv 限制，同时保留可审计输入。它不要求修改客户端源码，可用于支持 headless prompt、文件读取和 memory 目录隔离的 CodeAgent/free-code/opencode/pi/闭源 CLI；但仍必须先通过固定门禁，不能直接视为 benchmark-valid。

## 5. 失败后恢复

single 恢复必须指定原运行目录，并保持其余参数不变：

```bash
node evaluation/scripts/run_codeagent_memory_eval.mjs --preset small ...原有参数... --resume --run-dir <上次运行目录>
```

恢复逻辑会跳过完整 memory state 和已有完整查询结果，并从 ingestion checkpoint 继续失败轨迹。新尝试使用连续 attempt 编号，不覆盖旧日志。

## 6. 校准与放行标准

- 数据校验退出码为 0；
- CLI commit、launcher、模型、提示词哈希和轨迹指纹可追溯；
- ingestion 无未解释失败，query 超时/失败为零；
- query session 看不到 trajectory，且不能修改冻结主记忆；
- Web 与 Enterprise memory state 完全独立；
- `conversation_prompt` 产物必须包含 `conversation_prompt.txt`，并按固定 3 条、完整 100 条单题、固定 10 题顺序放行；
- historical-session 只有在结构化 extraction 状态完整、固定事实覆盖合格且召回答案通过后才能启用；
- 依次通过固定 3 条、完整 100 条单题和固定 10 题 calibration，才允许启动 full small。

`conversation_prompt` 使用 `--ingestion-strategy conversation_prompt` 显式启用，不限制 runtime。先检查 smoke 命令拼装：

```powershell
node evaluation/scripts/run_codeagent_memory_eval.mjs --preset smoke --data-root data/longmemeval-v2 --output-root runs/conversation_prompt_gate_3 --ingestion-strategy conversation_prompt --launcher '["D:/builds/codeagentcli.exe"]' --commit-hash 0123456789abcdef --dry-run
```

真实 `Message[]` importer 使用 `--ingestion-strategy historical_session` 显式启用，仅支持 `--runtime free_code`。它是 modified-client 研究路径，不是通用黑盒入口。先检查 3 条门禁的命令拼装：

```powershell
node evaluation/scripts/run_codeagent_memory_eval.mjs --preset smoke --data-root data/longmemeval-v2 --output-root runs/message_importer_gate_3 --runtime free_code --ingestion-strategy historical_session --launcher '["D:/aispace/free-code/cli-dev.exe"]' --cli-repo D:/aispace/free-code --dry-run
```

去掉 `--dry-run` 会调用真实模型，必须先确认模型、凭据、全新输出目录和预算。每条产物都必须包含结构化 `historical_session_import`，`mainAgentTurns` 必须为 0，extraction 状态只能是 `saved` 或明确的 `no_memory_worthy`；任何 `not_initialized`、`gate_disabled`、`remote_mode`、`coalesced` 或 `failed` 都不得进入下一道门。

## 7. 无记忆单次测评

```powershell
node evaluation/scripts/run_codeagent_memory_eval.mjs --preset smoke `
  --data-root data/longmemeval-v2 --output-root runs/codeagent_memory `
  --launcher '["D:/builds/codeagentcli.exe"]' `
  --commit-hash 0123456789abcdef --memory-off
```

结果目录带 `_memory_off` 后缀，`evaluation_result.json.run.memory_enabled` 为 `false`。该模式仍保持摄取、查询和隔离检查语义，因此仅用于小规模控制测试。

## 8. 跨平台约定

- 正式入口只依赖 Node.js/Bun 标准库，不需要 npm install。
- 脚本自动选择 `.venv/bin/python`（Linux/macOS）或 `.venv/Scripts/python.exe`（Windows），也可用 `--python` 覆盖。
- launcher 使用 JSON argv 数组，子进程以 `shell=false` 启动，路径中的空格不会被再次拆词。
- 所有输出路径由 Node `path.resolve` 规范化；Python 侧使用 `pathlib`、`tempfile` 和参数数组。
- `SIGINT`/`SIGTERM` 会转发给当前 Python 子进程，退出码非零立即停止后续阶段。
- 可先加 `--dry-run` 查看所有子命令，不创建目录、不调用模型。
- 也可把命令首个单词从 `node` 换成 `bun`，其余参数不变。
