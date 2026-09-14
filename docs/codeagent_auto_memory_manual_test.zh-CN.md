# CodeAgent Auto Memory 手动测试手册

> 当前只保留按 CLI commit 独立执行和留存的单次评测。修改前后使用
> 不同的包分别运行；三臂和四象限入口已移除。需要关闭记忆时使用
> 同一个 single 入口的 `--memory-off` 选项。

## 默认：单 CLI、单臂留存评测

源码 launcher 可从其 Git 仓库自动读取 commit：

```powershell
node evaluation/scripts/run_codeagent_memory_eval.mjs --preset smoke `
  --data-root data/longmemeval-v2 `
  --output-root runs/codeagent_memory `
  --runtime free_code `
  --launcher '["bun","D:/aispace/free-code/src/entrypoints/cli.tsx"]' `
  --cli-repo D:/aispace/free-code
```

打包后的 CLI 若不在 Git 工作区中，显式传入构建对应的 commit：

```powershell
node evaluation/scripts/run_codeagent_memory_eval.mjs --preset smoke `
  --data-root data/longmemeval-v2 `
  --output-root runs/codeagent_memory `
  --launcher '["D:/builds/codeagentcli.exe"]' `
  --commit-hash 0123456789abcdef0123456789abcdef01234567
```

每次新运行自动创建：

```text
<OutputRoot>/<UTC时间>_<commit前12位>[_dirty]/
  runner_config.json
  build/
  evaluate/
  evaluation_result.json
  report.html
```

`runner_config.json` 保存 commit、launcher、CLI 仓库、dirty 状态和启动时间。
正常运行记录为 `single`，关闭记忆时记录为 `memory_off`；不再使用
`baseline` 或 `candidate` 作为运行模式。
中断恢复时使用原参数，并增加 `--resume --run-dir <上次运行目录>`。
`evaluation_result.json` 是标准 JSON 文档，聚合运行身份、数据选择、构建指标、
总指标和逐题记录，可直接交给 HTML/前端解析，不需要在浏览器中处理 JSONL。
打开任意运行目录中的 `report.html`，可一次加载多份 `evaluation_result.json`，
以第一份为差值基准查看总体指标、分类指标和逐题变化。
也可以直接打开仓库中的 `evaluation/codeagent_memory_results.html`；两者功能相同。

一个 commit 的完整 small 需要两个独立运行目录：

```powershell
# Web：100 条共享轨迹构建一份记忆，然后回答 240 题
node evaluation/scripts/run_codeagent_memory_eval.mjs --preset small `
  --domain web --data-root data/longmemeval-v2 `
  --output-root runs/codeagent_memory --runtime free_code `
  --launcher '["bun","D:/aispace/free-code/src/entrypoints/cli.tsx"]' `
  --cli-repo D:/aispace/free-code --confirm-full-run

# Enterprise：另建一份记忆，然后回答 211 题
node evaluation/scripts/run_codeagent_memory_eval.mjs --preset small `
  --domain enterprise --data-root data/longmemeval-v2 `
  --output-root runs/codeagent_memory --runtime free_code `
  --launcher '["bun","D:/aispace/free-code/src/entrypoints/cli.tsx"]' `
  --cli-repo D:/aispace/free-code --confirm-full-run
```

两个领域不能共享 memory state。当前真实文件摄取路径曾实测每 100 条构建约 3.54 小时；单题冻结记忆回答样本曾耗时约 287 秒，因此在进一步校准前，Web + Enterprise 串行应保守预留 40～50 小时。experimental historical-session 虽能在约 20～26 分钟转换 100 条轨迹，但当前只是单 user message 包装，不是真实内部多轮 `Message[]`，且召回测试返回 `UNKNOWN`，不能替代默认路径。

> 本文是命令参考，不代表当前方案已具备发布条件。运行 calibration 或 full small 前，请检查[项目状态与下一步](codeagent_memory_project_status.zh-CN.md)中的阻塞项和环境就绪标志。

本文说明如何在 Windows PowerShell 中验证 `codeagent_auto_memory`。建议按“静态检查 → fake CLI 单元测试 → 真实构建冒烟 → 加载记忆评测”的顺序执行。前两步不调用模型；真实构建和评测会产生模型用量。

## 1. 进入仓库并选择 Python

```powershell
Set-Location D:\aispace\LongMemEval-V2

$Python = '.\.venv\Scripts\python.exe'
if (-not (Test-Path $Python)) { $Python = 'python' }
& $Python --version
```

项目要求 Python 3.11 或更高版本。若尚未安装依赖：

```powershell
& $Python -m pip install -r requirements.txt
& $Python -m pip install pytest
```

## 2. 检查 CodeAgent

当前本地构建路径为：

```powershell
$env:CODEAGENT_AUTO_MEMORY_BINARY = 'D:\workspace\CodeAgent\packages\codeagent\codeagentcli.exe'
& $env:CODEAGENT_AUTO_MEMORY_BINARY --version
```

预期能看到类似输出：

```text
1.2605.00 (codeAgentCLI)
```

真实测试还要求 CodeAgent 已配置可用的模型与认证。请从平时能正常运行 CodeAgent 的 PowerShell 会话启动测试。凭据只放在环境变量或本机安全配置中，不要写入 `evaluation/memory_configs/*.json`。

## 3. 不调用模型的本地检查

先检查 Python 语法和评测参数：

```powershell
& $Python -m compileall -q memory_modules evaluation tests
& $Python evaluation/run_eval.py --help | Select-String 'codeagent_auto_memory|CodeAgent|save-memory|load-memory'
```

运行 fake CLI 单元测试：

```powershell
& $Python -m pytest tests/test_codeagent_auto_memory.py -q
```

该测试验证：

- backend 已注册；
- ingestion 与 query 使用不同进程调用；
- 命令不包含 `--resume`、`--continue` 或 `--bare`；
- 每次 ingestion 在独立临时目录中运行，成功后才提交到主 auto-memory；
- query 在系统临时目录运行，看不到 trajectory；
- 每题使用独立 memory 快照；
- query 写入不会修改主记忆；
- save/load 后记忆内容与 trajectory 顺序不变。

预期结果：

```text
4 passed
```

## 4. 准备数据集

如果数据尚未准备：

```powershell
$env:DATA_ROOT = 'D:\aispace\LongMemEval-V2\data\longmemeval-v2'

& $Python data/download_data.py --data-root $env:DATA_ROOT
& $Python data/prepare_data.py --data-root $env:DATA_ROOT --mode symlink
& $Python data/validate_data.py --data-root $env:DATA_ROOT --tier small
```

没有创建符号链接的权限时，按照 `prepare_data.py --help` 选择复制模式。继续之前至少确认以下文件存在：

```powershell
Test-Path "$env:DATA_ROOT\trajectories.jsonl"
```

## 5. 真实单臂构建冒烟测试

`--limit 1` 表示选择一道评测题，不表示只处理一条 trajectory。该题 Small haystack 中的全部 trajectory 都会依次形成记忆，因此仍可能耗时并产生较多用量。

如果只需要验证工程链路，可使用 `--haystack-limit` 截取每个 haystack 的前 N 条轨迹。该参数会改变正式评测数据，产物中的 `runtime_inputs/data_selection.json` 会标记 `structural_smoke_only: true`，因此结果不得作为 benchmark 分数。

默认使用 Node/Bun 通用的单臂入口：

```bash
node evaluation/scripts/run_codeagent_memory_eval.mjs --preset smoke --data-root data/longmemeval-v2 --output-root runs/codeagent_memory --launcher '["codeagentcli"]' --commit-hash 0123456789abcdef0123456789abcdef01234567 --haystack-limit 1
```

脚本依次执行：

```text
single 构建并保存冻结记忆
→ 从冻结记忆启动独立问题 session
→ 保存逐题结果、运行身份和 evaluation_result.json
```

默认选择真实题目 `05cce9b3`。不同版本分别执行 single，之后按 commit 和相同配置离线比较。

### 5.1 无记忆选项

无记忆控制也只运行一个包：

```bash
node evaluation/scripts/run_codeagent_memory_eval.mjs --preset smoke --data-root data/longmemeval-v2 --output-root runs/codeagent_memory --launcher '["D:/builds/codeagentcli.exe"]' --commit-hash 0123456789abcdef --memory-off
```

目录名增加 `_memory_off`，结果中的 `run.experiment_mode` 为 `memory_off`、
`run.memory_enabled` 为 `false`。该模式仍执行隔离检查，只用于极小 smoke；
不要为它运行完整 haystack/full-small。

修改前和修改后的包分别重复 single 命令，并确保 domain、tier、题单、模型和
prompt 一致。runner 不再接受 `regression`、`attribution`、baseline/candidate
launcher 或写入/召回交叉组合参数。

先用一道题验证完整的记忆形成和保存链路：

```powershell
$BuildDir = 'runs\codeagent_auto_memory_smoke_build'

& $Python evaluation/run_eval.py `
  --method codeagent_auto_memory `
  --data-root $env:DATA_ROOT `
  --domain web `
  --tier small `
  --limit 1 `
  --output-dir $BuildDir `
  --codeagent-auto-memory-binary $env:CODEAGENT_AUTO_MEMORY_BINARY `
  --codeagent-auto-memory-ingest-max-turns 10 `
  --codeagent-auto-memory-query-max-turns 10 `
  --codeagent-auto-memory-ingest-max-attempts 1 `
  --codeagent-auto-memory-query-max-attempts 1 `
  --save-memory `
  --skip-evaluation
```

输出目录必须是新目录。若同名目录已存在，改用新名称，例如在末尾加日期或序号；框架会拒绝覆盖既有 memory workspace/state。

构建完成后检查：

```powershell
Get-ChildItem "$BuildDir\memory_state\auto_memory" -Recurse
Get-Content "$BuildDir\memory_state\ingestion_metrics.json"
Get-Content "$BuildDir\memory_state\ingestion_manifest.json" -TotalCount 80
```

重点关注：

- `trajectory_count` 是否符合所选 haystack；
- `success_count`、`empty_ingestion_count` 和 `failed_attempt_count`；
- `memory_file_count` 与 `memory_total_bytes` 是否大于零；
- `usage_totals` 和 `total_duration_seconds` 是否被记录；
- `trajectory_ids` 是否保持 haystack 顺序；
- `auto_memory/MEMORY.md` 或 topic memory 文件是否存在。

每次历史会话的详细记录位于：

```text
<BuildDir>/memory_workspaces/shared/ingestion_sessions/
```

其中包含当前 trajectory、`stdout.log`、`stderr.log` 和 `summary.json`。若 `require_memory_write=false`，没有写入记忆的会话会记录为 `empty_ingestion` 并继续构建。需要把这种情况直接视为错误时，加上：

```text
--codeagent-auto-memory-require-memory-write
```

构建中断后，可用同一个输出目录恢复。必须保持其余构建参数一致，并增加：

```text
--codeagent-auto-memory-resume-build
```

框架会核对已完成 trajectory 的内容指纹并跳过它们；最后一次失败的尝试不会写入主记忆。

## 6. 加载冻结记忆进行评测

阶段 B 会加载阶段 A 保存的 `memory_state`，不会重新 ingestion。使用新的输出目录：

```powershell
$env:READER_BASE_URL = 'http://localhost:8023/v1'
$env:READER_MODEL = 'Qwen/Qwen3.5-9B'
$env:OPENAI_API_KEY = '<本地服务所需的值>'

$MemoryState = Resolve-Path "$BuildDir\memory_state"
$EvalDir = 'runs\codeagent_auto_memory_smoke_evaluate'

& $Python evaluation/run_eval.py `
  --method codeagent_auto_memory `
  --data-root $env:DATA_ROOT `
  --domain web `
  --tier small `
  --limit 1 `
  --output-dir $EvalDir `
  --codeagent-auto-memory-binary $env:CODEAGENT_AUTO_MEMORY_BINARY `
  --codeagent-auto-memory-ingest-max-turns 10 `
  --codeagent-auto-memory-query-max-turns 10 `
  --codeagent-auto-memory-ingest-max-attempts 1 `
  --codeagent-auto-memory-query-max-attempts 1 `
  --reader-base-url $env:READER_BASE_URL `
  --reader-model $env:READER_MODEL `
  --load-memory-dir $MemoryState
```

阶段 B 的 CodeAgent 参数必须与阶段 A 一致，包括 binary、model、turn limits、重试次数和 `require_memory_write`。不一致时框架会拒绝加载，防止把不同实验配置混在一起。

完成后检查：

```powershell
Get-Content "$EvalDir\aggregated_metrics.json"
Get-Content "$EvalDir\per_question.jsonl" -TotalCount 3
Get-ChildItem "$EvalDir\memory_workspaces\shared\query_sessions" -Recurse -Filter summary.json
```

每道题的查询会从冻结主记忆复制独立快照。查询结束后，`summary.json` 中的 `main_memory_unchanged` 应为 `true`。

## 7. 使用包装脚本运行两阶段流程

安装了 Git Bash 或 WSL 时，也可以使用包装脚本。

阶段 A：

```powershell
$env:PHASE = 'build'
$env:DOMAIN = 'web'
$env:TIER = 'small'
$env:OUTPUT_DIR = 'runs/codeagent_auto_memory_build_01'
bash evaluation/scripts/run_codeagent_auto_memory.sh --limit 1 --codeagent-auto-memory-ingest-max-turns 10
```

阶段 B：

```powershell
$env:PHASE = 'evaluate'
$env:MEMORY_STATE = (Resolve-Path 'runs/codeagent_auto_memory_build_01/memory_state').Path
$env:OUTPUT_DIR = 'runs/codeagent_auto_memory_evaluate_01'
bash evaluation/scripts/run_codeagent_auto_memory.sh --limit 1 --codeagent-auto-memory-ingest-max-turns 10
```

不设置 `OUTPUT_DIR` 时，默认分别使用：

```text
runs/codeagent_auto_memory_build
runs/codeagent_auto_memory_evaluate
```

## 8. 扩展到 Small tier

冒烟测试通过后，去掉 `--limit 1`，先构建一次可复用 memory state，再分别运行评测。不要直接从 Medium tier 开始。

建议按以下顺序扩展：

1. `web / small` 阶段 A；
2. 检查 memory write rate、失败日志、Token 和费用；
3. `web / small` 阶段 B；
4. 使用同样流程运行 `enterprise / small`；
5. 分别运行 `no_retrieval` 与 `codeagent`，保持 Reader、问题集合和采样参数一致。

注意：`web` 和 `enterprise` 应使用各自独立的 build/evaluate 输出目录和 memory state。

## 9. 常见问题

### CodeAgent 返回非零退出码

打开对应会话的 `stderr.log` 和 `summary.json`。常见原因是认证缺失、模型名错误、网络不可达或 turn limit 太小。

### 大量 `empty_ingestion`

检查 ingestion 的 `stdout.log`，确认 CodeAgent 是否实际执行了 memory 写入。还应确认运行的 CodeAgent 构建支持 auto memory，并且没有通过额外参数启用 `--bare`。适配器会强制设置：

```text
CODEAGENT3_COWORK_MEMORY_PATH_OVERRIDE=<隔离目录>
CODEAGENT3_DISABLE_AUTO_MEMORY=0
```

### 提示配置不匹配，无法加载

阶段 A 与阶段 B 的 `CODEAGENT_AUTO_MEMORY_*` 环境变量或命令行参数不同。复制阶段 A 的参数重新运行阶段 B；不要手工修改保存的 `memory_config.json`。

### 输出目录已存在

换用新的输出目录。若旧运行仍有分析价值，先重命名保存：

```powershell
Move-Item runs\codeagent_auto_memory_smoke_build runs\codeagent_auto_memory_smoke_build_old
```

### Reader 连接失败

阶段 A 使用 `--skip-evaluation` 时不需要 Reader。阶段 B 才需要检查 `READER_BASE_URL`、`READER_MODEL` 和认证环境变量。

### pytest 未安装

```powershell
& $Python -m pip install pytest
```

这只影响单元测试命令，不影响 backend 本身。
