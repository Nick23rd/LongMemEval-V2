# CodeAgent 记忆归因测评环境运行手册

> 开始前先阅读[项目状态与下一步](codeagent_memory_project_status.zh-CN.md)。截至 2026-09-12，正式文件摄取路径可运行但成本很高；experimental historical-session 路径虽更快但完整 100 条召回失败。不要在其通过内部 `Message[]` importer 和 10 题 calibration 前运行 full small。

## 1. 首次运行目标

先运行固定的 web/small 10 题校准集，而不是直接发布完整 small 分数。校准运行会：

1. 用写入 A、B 分别从空状态构建两份完整 small-tier 冻结记忆；
2. 运行 AA、AB、BA、BB 四组独立新会话查询；
3. 输出机器可读结果以及可直接打开的 `report.html`；
4. 保留 CLI 版本、launcher、提示词哈希、记忆摘要、Token、费用、耗时和失败审计。

固定题单见 `evaluation/calibration_sets/codeagent_memory_web_small_10.json`。它覆盖 static、dynamic、procedure、gotchas 和三种 abstention 类型；它是校准门槛，不是正式 full-small 发布分数。

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

## 3. 修改前/后 EXE 的推荐命令

Node.js 与 Bun 使用相同参数。以下命令在 Bash 和 PowerShell 中都可直接运行：

```bash
node evaluation/scripts/run_codeagent_memory_eval.mjs attribution --preset calibration --data-root data/longmemeval-v2 --output-root runs/attribution_calibration_001 --confirm-full-haystack --model deepseek-v4-pro --ingest-max-turns 60 --query-max-turns 20 --ingest-max-attempts 2 --query-max-attempts 2 --writer-a-launcher '["/builds/before/codeagentcli"]' --recall-a-launcher '["/builds/before/codeagentcli"]' --writer-b-launcher '["/builds/after/codeagentcli"]' --recall-b-launcher '["/builds/after/codeagentcli"]'
```

如果使用 CodeAgent 默认 DeepSeek 配置，可省略 `-CodeAgentModel`。

源码启动示例：

```bash
--writer-b-launcher '["bun","/src/CodeAgent/src/cli.ts"]' --recall-b-launcher '["bun","/src/CodeAgent/src/cli.ts"]'
```

## 4. 单变量实验

只评测写入提示词时，A/B 使用同一个 CLI 和召回配置，只改变：

```bash
--writer-a-ingest-prompt prompts/ingest_before.txt --writer-b-ingest-prompt prompts/ingest_after.txt
```

只评测召回提示词时，写入端保持一致，只改变：

```bash
--recall-a-query-prompt prompts/recall_before.txt --recall-b-query-prompt prompts/recall_after.txt
```

如果修改影响最终回答阶段，则改用 `--recall-a-answer-prompt` 和 `--recall-b-answer-prompt`。一次实验尽量只改变一个因素。

## 5. 失败后恢复

原命令增加 `--resume`，并保持所有 A/B 参数不变：

```bash
node evaluation/scripts/run_codeagent_memory_eval.mjs attribution --preset calibration ...原有参数... --confirm-full-haystack --resume
```

恢复逻辑会跳过已有的完整 memory state 和完整查询结果，从 ingestion checkpoint 继续失败轨迹。新尝试使用连续的 attempt 编号，不覆盖旧日志。

## 6. 报告与审计产物

```text
<OutputRoot>/attribution/report.html
<OutputRoot>/attribution/report.md
<OutputRoot>/attribution/attribution.json
<OutputRoot>/attribution/per_question_attribution.jsonl
<OutputRoot>/writer_a/build/memory_state/
<OutputRoot>/writer_b/build/memory_state/
<OutputRoot>/{aa,ab,ba,bb}/evaluate/
```

HTML 中应能看到：

- 四象限准确率；
- 两个条件写入效应、两个条件召回效应和交互效应；
- A/B 版本、launcher、写入 Token/费用/耗时与失败次数；
- 四组查询 Token、费用、耗时与失败次数；
- 每题标准答案、四组原始回答和正确性。

## 7. 校准通过标准

- 两份 memory state 的目录、摘要和审计记录独立；
- 所有 10 题在四组中 question ID、题面、答案和 haystack 完全一致；
- 写入无未解释失败，查询超时/失败为零；
- 人工复核所有 improved 和 regressed 题，变化能由回答内容解释；
- 若 A/B 实际相同，归因差值应只反映模型随机性，不应出现配置串用；
- 确认总 Token、费用和耗时可接受后，再运行 `node evaluation/scripts/run_codeagent_memory_eval.mjs attribution --preset small ... --confirm-full-run`。

## 8. 跨平台约定

- 正式入口只依赖 Node.js/Bun 标准库，不需要 npm install。
- 脚本自动选择 `.venv/bin/python`（Linux/macOS）或 `.venv/Scripts/python.exe`（Windows），也可用 `--python` 覆盖。
- launcher 使用 JSON argv 数组，子进程以 `shell=false` 启动，路径中的空格不会被再次拆词。
- 所有输出路径由 Node `path.resolve` 规范化；Python 侧使用 `pathlib`、`tempfile` 和参数数组。
- `SIGINT`/`SIGTERM` 会转发给当前 Python 子进程，退出码非零立即停止后续阶段。
- 可先加 `--dry-run` 查看所有子命令，不创建目录、不调用模型。
- 也可把命令首个单词从 `node` 换成 `bun`，其余参数不变。
