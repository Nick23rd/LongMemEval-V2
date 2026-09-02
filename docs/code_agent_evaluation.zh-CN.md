# 编码智能体记忆评测与对比

本指南是将编码智能体作为 LongMemEval-V2 记忆检索器进行对比时的操作契约，涵盖冒烟测试、可复现的基准运行、配对分析、成本核算和报告可视化。

## 对比对象

编码智能体是记忆检索器，而不是最终回答模型：

```text
轨迹干草堆 -> 编码智能体记忆后端 -> 精简证据
           -> 固定阅读器 -> 回答 -> 评测器
```

对比记忆智能体时应固定阅读器。同时更改记忆智能体和阅读器，会导致准确率差异无法归因。

仓库当前提供：

- `codex`：通过 `memory_modules/codex.py` 使用 Codex CLI 检索。
- `claude_code`：通过 `memory_modules/claude_code.py` 使用 Claude Code 检索。

可以通过复现环境、模型、设置和可执行文件路径来支持由网关驱动的包装器，例如 PowerShell `claudex` 函数。shell 函数本身不是有效的 `CLAUDE_BINARY`；Python 必须接收真实的可执行文件或 `.cmd` 路径。

## 可复现性规则

每次对比都应固定除实验指定变量外的所有变量：

- 数据集修订版、层级、领域、问题 ID 和问题顺序；
- 阅读器模型、端点、采样参数和记忆上下文限制；
- 证据模式、超时、重试次数和并发度；
- 测量 CLI 版本变化时固定编码智能体模型；
- 测量模型变化时固定 CLI 版本；
- 用户设置、插件、MCP 服务器、技能、钩子和持久记忆；
- 网关／提供商和认证路由；
- 报告延迟时使用的机器类别和主要文件系统行为。

同时记录人工标签和检测到的 CLI 版本。在多版本实验期间禁用 CLI 自动更新。绝不要提交凭据或 OAuth 状态。

推荐让实验名称编码自变量：

```text
codex_0.152.0_gpt-5.4-mini_xhigh
claude_2.1.227_sonnet_30turns
claudex_2.1.227_gpt-5.6-luna_30turns
```

## 准备和验证数据

默认本地数据根目录为：

```text
data/longmemeval-v2
```

在新机器上执行：

```bash
python data/download_data.py --data-root data/longmemeval-v2
python data/prepare_data.py --data-root data/longmemeval-v2 --mode symlink
python data/validate_data.py --data-root data/longmemeval-v2 --tier small
```

在没有符号链接权限的 Windows 上，准备过程可能改为复制截图目录。请为解压后的数据和副本预留足够磁盘空间。

## 配置固定阅读器

有效的准确率对比需要真实的 OpenAI 兼容阅读器。参考配置使用 Qwen3.5-9B：

```bash
export READER_BASE_URL=http://localhost:8023/v1
export READER_MODEL=Qwen/Qwen3.5-9B
```

启动昂贵的记忆运行前先验证端点。模拟阅读器只能用于管线冒烟测试；使用模拟阅读器的结果不得用于质量、排行榜或模型对比结论。

运行框架还会加载 `Qwen/Qwen3.5-9B` 处理器来统计记忆上下文令牌。离线运行前应缓存其处理器／分词器文件。

## 运行 Codex

```bash
export CODEX_BINARY=/absolute/path/to/codex
export CODEX_MODEL=gpt-5.4-mini
export CODEX_REASONING_EFFORT=xhigh
export DATA_ROOT=/absolute/path/to/data/longmemeval-v2
export OUTPUT_ROOT=runs/codex_0.152.0_gpt-5.4-mini_xhigh
export TIER=small

evaluation/scripts/run_codex.sh
```

单问题测试使用统一入口：

```bash
python evaluation/run_eval.py \
  --method codex \
  --data-root "$DATA_ROOT" \
  --domain web \
  --tier small \
  --question-ids 00aa905a \
  --output-dir runs/smoke_codex \
  --codex-binary "$CODEX_BINARY" \
  --codex-model "$CODEX_MODEL" \
  --codex-reasoning-effort "$CODEX_REASONING_EFFORT" \
  --codex-max-retries 1
```

## 运行 Claude Code

```bash
export CLAUDE_BINARY=/absolute/path/to/claude
export CLAUDE_MODEL=sonnet
export CLAUDE_VERSION_LABEL=2.1.227
export CLAUDE_MAX_TURNS=30
export CLAUDE_NO_SESSION_PERSISTENCE=true
export DATA_ROOT=/absolute/path/to/data/longmemeval-v2
export OUTPUT_ROOT=runs/claude_2.1.227_sonnet
export TIER=small

evaluation/scripts/run_claude_code.sh
```

仅当所有被对比版本都支持 `--bare` 时才使用 `CLAUDE_BARE=true`，否则应使用版本兼容参数或干净的用户环境来隔离设置。只有所有版本都支持 `--effort` 时才使用 `CLAUDE_EFFORT`。

单问题示例：

```bash
python evaluation/run_eval.py \
  --method claude_code \
  --data-root "$DATA_ROOT" \
  --domain web \
  --tier small \
  --question-ids 00aa905a \
  --output-dir runs/smoke_claude \
  --claude-binary "$CLAUDE_BINARY" \
  --claude-model "$CLAUDE_MODEL" \
  --claude-version-label "$CLAUDE_VERSION_LABEL" \
  --claude-max-turns 30 \
  --claude-max-retries 1 \
  --claude-no-session-persistence
```

## 复现网关支持的 `claudex` 配置

首先检查包装器，而不要猜测其行为：

```powershell
Get-Command claudex | Format-List Definition
```

在启动 `run_eval.py` 的进程中复现以下字段：

- `ANTHROPIC_BASE_URL` 和网关认证变量；
- 准确的模型标识符；
- 实际 Claude 可执行文件路径；
- 通过 `claude_params.extra_args` 传入的显式设置 JSON；
- 子智能体模型及任何影响行为的 Claude 环境变量。

不要把网关令牌存入 `evaluation/memory_configs/*.json`。优先使用设置环境并转发参数的小型可执行启动器，或从已经设置变量的 shell 启动评测器。

例如，本地包装器可能等效于：

```powershell
$env:ANTHROPIC_BASE_URL = 'http://127.0.0.1:8317'
$env:ANTHROPIC_AUTH_TOKEN = '<from secure local configuration>'
$env:CLAUDE_CODE_SUBAGENT_MODEL = 'gateway-model-id'

python evaluation/run_eval.py `
  --method claude_code `
  --data-root $env:DATA_ROOT `
  --domain web `
  --tier small `
  --question-ids 00aa905a `
  --output-dir runs/smoke_claudex `
  --claude-binary 'C:\path\to\claude.cmd' `
  --claude-model 'gateway-model-id' `
  --claude-version-label 'claudex-provider-model'
```

若需要显式 Claude 设置，将其加入 JSON 记忆配置：

```json
{
  "extra_args": [
    "--settings",
    "C:\\path\\to\\claudex-settings.json"
  ]
}
```

## 完整层级运行前先做试验

先用 20–50 个问题进行配对试验，并按 static、dynamic、procedure、gotchas 和 abstention 类别分层抽样。每个智能体必须使用完全相同的问题 ID。

完整基准运行点应同时运行 `web` 和 `enterprise`。确认以下事项后，才扩展到 small 层级全部 451 个问题：

- 成功输出率可接受；
- 不存在设置或持久记忆污染；
- 单问题成本和延迟符合预算；
- 阅读器与评测器服务稳定；
- 轨迹 `summary.json` 文件包含用量指标。

在了解提供商限制和工作站 I/O 前，避免激进并发。应报告提示构建并发度，因为它影响墙钟时间，也可能影响在线学习方法。

## 运行产物

每个完成的运行应包含：

```text
run_args.json
memory_config.json or runtime memory configuration
per_question.jsonl
aggregated_metrics.json
query_traces/<query_invocation_id>/attempt_*/summary.json
query_traces/<query_invocation_id>/attempt_*/events.json
query_traces/<query_invocation_id>/attempt_*/memory_module_output.json
```

重要字段包括：

- `per_question.jsonl`：`question_id`、类别、分数、未知状态、记忆查询时长、记忆上下文令牌、回答和所选证据。
- `aggregated_metrics.json`：总体／分类准确率、平均／P50／P95／最大记忆延迟、阅读器用量和截断次数。
- 智能体 `summary.json`：返回码、超时、时长、命令、所选片段和智能体用量。
- Claude 用量：输入、缓存创建、缓存读取、输出、总令牌、轮次、成本、时长及各模型详情。
- Codex 用量：输入、缓存输入、输出和推理输出令牌。

不同提供商的令牌模式不同。应保留原始字段并对比语义等价的类别；不要把缓存读取令牌标为新输入。由于令牌价格和缓存折扣不同，必须单独报告成本。

## 判断哪个智能体更好

使用配对结果，而不是独立平均值。对每个问题分类：

```text
两者都正确
仅 Codex 正确
仅 Claude 正确
两者都错误
```

主要指标：

1. 使用固定阅读器的最终回答准确率；
2. 超时、无效输出和空记忆率；
3. 记忆查询延迟中位数和 P95；
4. 单问题成本和每个正确回答的成本；
5. 记忆上下文令牌和截断率；
6. 基准准确率／延迟权衡的 LAFS。

对配对二元准确率使用 McNemar 检验，对准确率差、延迟比和成本差使用配对 bootstrap 置信区间。报告样本量和置信区间；仅多赢一个问题不能证明某智能体普遍更好。

检索质量诊断应人工复核分层子集并评分：

- `2`：直接、充分且不误导的证据；
- `1`：相关但不完整的证据；
- `0`：无关、无支持或误导性证据。

还应跟踪有效片段率、所选状态数、冗余证据，以及检索正确但阅读器仍答错的案例。

## 构建对比数据集

通过连接以下内容，为每个 `(agent, domain, question_id)` 创建一行：

- 运行的 `per_question.jsonl`；
- 其 `query_traces/**/summary.json`；
- 实验元数据，例如智能体标签、CLI 版本、模型、提供商、层级、证据模式、超时、轮次和阅读器模型。

推荐的规范化列：

```text
agent_label, cli_version, agent_model, provider, reader_model
domain, tier, question_id, category, is_abstention
score, is_unknown, query_seconds, post_query_seconds
memory_context_tokens, memory_truncated, valid_span_count, selected_state_count
input_tokens, cache_read_tokens, cache_creation_tokens, output_tokens
reasoning_tokens, turns, cost_usd, timed_out, returncode
```

另建实验清单，记录 Git 提交、数据集修订版、命令行、环境变量名称（不含秘密值）、机器详情和运行时间戳。

## 可视化方案

最终报告至少应包含以下视图：

1. **带不确定性的准确率**：总体和各类别的分组柱状图，带配对 bootstrap 95% 置信区间。
2. **配对胜负矩阵**：两者都正确、仅 A 正确、仅 B 正确、两者都错误，并标注 McNemar p 值。
3. **延迟分布**：配对点图或 ECDF，并显示中位数和 P95；长尾数据适合使用对数轴。
4. **成本和令牌构成**：输入／缓存／输出堆叠柱状图、单问题成本和每个正确回答的成本。
5. **准确率－延迟前沿**：纵轴为准确率、横轴为记忆延迟，点大小或颜色表示成本，并标注 LAFS。
6. **失败诊断**：超时／无效／空／截断率，以及按记忆类别划分的检索质量。

性能报告不得使用阅读器的模拟令牌计数。应区分智能体、阅读器和裁判模型的令牌。

建议报告结构：

```text
1. 执行摘要与建议
2. 实验控制条件与版本
3. 数据集覆盖率与完成率
4. 准确率与配对显著性
5. 检索质量分析
6. 延迟、令牌与成本
7. 准确率－延迟－成本权衡与 LAFS
8. 失败案例研究
9. 局限性与可复现性附录
```

每张图都应能追溯到规范化对比表和源运行目录。为成功和失败案例各附上有代表性的 `memory_module_output.json` 证据，并隐去秘密值及用户特定路径。

### 推荐的报告生成接口

后续实现应提供单一确定性命令，而不是交互式 notebook，例如：

```bash
python analysis/build_agent_report.py \
  --run codex=runs/codex_web_small \
  --run codex=runs/codex_enterprise_small \
  --run claude=runs/claude_web_small \
  --run claude=runs/claude_enterprise_small \
  --output-dir reports/codex_vs_claude_small
```

脚本应只读运行产物且不修改它们，并生成：

```text
reports/codex_vs_claude_small/
  experiment_manifest.json
  comparison.csv
  question_outcomes.csv
  summary_metrics.json
  statistical_tests.json
  figures/
    accuracy_by_category.png
    paired_outcomes.png
    latency_ecdf.png
    token_composition.png
    cost_tradeoff.png
    accuracy_latency_frontier.png
    failure_rates.png
  report.md
```

连接可使用 pandas 或 Polars，配对检验使用 scipy／statsmodels，绘图使用 Matplotlib／Seaborn 或 Plotly。固定分析依赖项版本和随机种子。保存每张图使用的表格输入，使其他智能体无需重新运行昂贵的记忆智能体即可复现报告。

当配对问题集、阅读器模型、层级或领域不一致时，报告构建器应明确失败。它应标记不完整运行和模拟阅读器，而不是静默合并。应同时生成机器可读的 JSON／CSV 和人类可读的 Markdown 或 HTML 报告。

## 与排行榜兼容的报告

对于正式运行点，应合并匹配的 web 和 enterprise 运行并遵循 `leaderboard/README.md`。排行榜要求使用参考阅读器和评测器配置，并根据准确率与平均记忆查询延迟计算 LAFS。使用模拟阅读器的冒烟运行和临时网关实验，除非满足全部验证要求，否则不与排行榜兼容。

## 最小交接清单

在其他智能体继续实验前，请提供：

- 本文档及准确的 Git 提交；
- 数据根目录和验证结果；
- 智能体标签、解析后的二进制、检测到的版本、模型和提供商；
- 固定阅读器／评测器端点和模型标识符；
- 准确的配对问题 ID 列表；
- 输出目录和完成状态；
- 令牌／成本预算和并发限制；
- 已知的模拟组件或相对基准设置的偏差；
- 规范化对比表和报告输出位置。

