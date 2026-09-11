# CodeAgent 记忆归因测评环境运行手册

## 1. 首次运行目标

先运行固定的 web/small 10 题校准集，而不是直接发布完整 small 分数。校准运行会：

1. 用写入 A、B 分别从空状态构建两份完整 small-tier 冻结记忆；
2. 运行 AA、AB、BA、BB 四组独立新会话查询；
3. 输出机器可读结果以及可直接打开的 `report.html`；
4. 保留 CLI 版本、launcher、提示词哈希、记忆摘要、Token、费用、耗时和失败审计。

固定题单见 `evaluation/calibration_sets/codeagent_memory_web_small_10.json`。它覆盖 static、dynamic、procedure、gotchas 和三种 abstention 类型；它是校准门槛，不是正式 full-small 发布分数。

## 2. 环境检查

在仓库根目录运行：

```powershell
& .\.venv\Scripts\python.exe -m pytest -q
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

```powershell
& .\evaluation\scripts\run_codeagent_memory_attribution_calibration.ps1 `
  -DataRoot .\data\longmemeval-v2 `
  -OutputRoot .\runs\attribution_calibration_001 `
  -ConfirmFullHaystack `
  -Python .\.venv\Scripts\python.exe `
  -CodeAgentModel deepseek-v4-pro `
  -IngestMaxTurns 60 `
  -QueryMaxTurns 20 `
  -IngestMaxAttempts 2 `
  -QueryMaxAttempts 2 `
  -WriterALauncherCommand D:\builds\before\codeagentcli.exe `
  -RecallALauncherCommand D:\builds\before\codeagentcli.exe `
  -WriterBLauncherCommand D:\builds\after\codeagentcli.exe `
  -RecallBLauncherCommand D:\builds\after\codeagentcli.exe
```

如果使用 CodeAgent 默认 DeepSeek 配置，可省略 `-CodeAgentModel`。

源码启动示例：

```powershell
-WriterBLauncherCommand bun,D:\src\CodeAgent\src\cli.ts `
-RecallBLauncherCommand bun,D:\src\CodeAgent\src\cli.ts
```

## 4. 单变量实验

只评测写入提示词时，A/B 使用同一个 CLI 和召回配置，只改变：

```powershell
-WriterAIngestPromptFile .\prompts\ingest_before.txt `
-WriterBIngestPromptFile .\prompts\ingest_after.txt
```

只评测召回提示词时，写入端保持一致，只改变：

```powershell
-RecallAQueryPromptFile .\prompts\recall_before.txt `
-RecallBQueryPromptFile .\prompts\recall_after.txt
```

如果修改影响最终回答阶段，则改用 `RecallADirectAnswerPromptFile` 和 `RecallBDirectAnswerPromptFile`。一次实验尽量只改变一个因素。

## 5. 失败后恢复

原命令增加 `-Resume`，并保持所有 A/B 参数不变：

```powershell
& .\evaluation\scripts\run_codeagent_memory_attribution_calibration.ps1 `
  ...原有参数... `
  -ConfirmFullHaystack `
  -Resume
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
- 确认总 Token、费用和耗时可接受后，才运行 `run_codeagent_memory_attribution_small.ps1`。
