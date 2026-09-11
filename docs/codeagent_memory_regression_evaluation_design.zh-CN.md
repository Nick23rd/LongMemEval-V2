# CodeAgent 内部记忆回归评测设计

## 1. 目的

本设计用于把 LongMemEval-V2 改造成 CodeAgent 内部记忆机制的版本回归评测框架，回答：修改记忆写入提示词、存储方式或召回算法后，新版本相对于旧版本有哪些改进和退化？

主要比较是 `candidate - baseline`。`memory_off` 是辅助控制组，用来估计两个版本相对于“同样经历轨迹但无法跨会话记忆”的真实收益。完整目标和验收原则见 [CodeAgent 内部记忆回归评测目标](codeagent_memory_regression_evaluation_goal.zh-CN.md)。

## 2. 现有数据适用性

现有数据可以复用，无需重新采集。数据集包含 451 道可评分问题，覆盖 Web 和 Enterprise 两个领域，以及 static、dynamic、procedure、gotchas、abstention 等记忆能力。每道题都有标准答案、评分函数、有序历史轨迹 haystack，以及包含操作状态、文本和截图的原始轨迹。

`small` tier 每题包含 100 条轨迹，同一领域的问题共享一份有序 haystack。因此每个实验组可按领域构建一次状态，再回答该领域的全部问题，适合日常回归。

`medium` tier 每题约包含 387～500 条轨迹，451 道题中存在 447 份不同的有序 haystack，构建成本显著更高，适合发布前验证。

建议分层运行：

```text
开发冒烟：精选 10～30 题
日常回归：small 全集
发布验证：medium 全集
```

## 3. 当前实现的偏差

当前 `codeagent_auto_memory` 的流程是：

```text
CodeAgent 读取轨迹并形成 auto-memory
→ CodeAgent 作为 retrieval component 输出记忆证据
→ harness 拼接 memory context
→ 外部固定 reader 回答
→ 评分
```

现有分数混合了 CodeAgent 的记忆形成、证据检索整理和外部 reader 的回答能力，不能直接衡量 CodeAgent 内部记忆修改前后的端到端变化。

改造后，CodeAgent 必须在全新会话中自动使用内部记忆并直接产生最终答案；外部 reader 不参与这条评测路径。

## 4. 三组实验

### 4.1 memory_off

```text
读取与其他组相同的历史轨迹
→ 关闭 auto-memory
→ 结束轨迹会话
→ 验证没有持久记忆或可恢复会话状态
→ 在全新、独立的问题会话中直接回答
```

`memory_off` 不是“不读取轨迹”。它完成相同的轨迹处理过程，只禁止经验跨会话持久化。

### 4.2 baseline

```text
读取历史轨迹
→ 使用修改前机制形成记忆
→ 结束轨迹会话并冻结状态
→ 在全新问题会话中自动召回并直接回答
```

### 4.3 candidate

```text
读取相同历史轨迹
→ 使用修改后机制形成记忆
→ 结束轨迹会话并冻结状态
→ 在全新问题会话中自动召回并直接回答
```

三组必须保持模型、轨迹、顺序、工具、轮数、超时、重试、问题和评分器一致。若修改写入提示词、存储结构或更新逻辑，`baseline` 与 `candidate` 必须从空状态独立构建，不能共享 memory state。

## 5. 目标软件架构

保留现有 `Memory.query()` 给 RAG 等检索型 backend，另行增加端到端回答能力：

```python
class EndToEndMemoryAgent:
    def answer(
        self,
        question: str,
        question_image: str | None = None,
    ) -> AgentAnswer:
        ...
```

`AgentAnswer` 至少包含：

```python
{
    "response_raw": "...",
    "usage": {...},
    "duration_seconds": 12.3,
    "memory_snapshot_unchanged": True
}
```

harness 根据 backend capability 选择路径：

```text
检索型 backend：memory.query() → external reader → score
端到端 Agent：memory.answer() → score
```

这样可保持现有 RAG、Codex 和 AgentRunbook 基线兼容，并让 CodeAgent 的直接回答成为评分对象。

## 6. memory_off 语义与隔离

配置应有明确模式，例如：

```json
{"experiment_mode": "memory_off"}
```

轨迹阶段仍逐条启动 CodeAgent。当前产品环境约定需要通过真实 CLI 确认：

```text
CODEAGENT3_DISABLE_AUTO_MEMORY=1  # memory_off
CODEAGENT3_DISABLE_AUTO_MEMORY=0  # baseline/candidate
```

`memory_off` 必须验证：

```text
memory_file_count == 0
memory_total_bytes == 0
session_persistence == disabled
```

若发现记忆文件、可恢复会话或其他能把轨迹信息带入问题阶段的状态，本次运行应标记为隔离失败，不能纳入评分。

每道题必须使用新的 session/config 目录；不得 `resume` 或 `continue`；问题目录不得包含轨迹、人工摘要或外部检索结果；查询不得修改冻结主记忆。

## 7. 版本指定与溯源

评测应允许两组使用不同 binary、代码提交或提示词文件，例如：

```json
{
  "name": "baseline",
  "binary": "D:/codeagent-baseline/codeagentcli.exe",
  "memory_mode": "enabled",
  "version_label": "before-recall-change"
}
```

实际被测版本可能来自两种交付形式：

```text
打包产物：D:/builds/baseline/codeagentcli.exe
源码启动：bun D:/CodeAgent-baseline/src/cli.ts
```

因此实现使用 argv 数组形式的 `launcher_command` 作为统一启动契约：

```json
{"launcher_command": ["D:/builds/baseline/codeagentcli.exe"]}
```

或：

```json
{"launcher_command": ["bun", "D:/CodeAgent-baseline/src/cli.ts"]}
```

源码路径应使用绝对路径。无论采用哪种启动方式，CodeAgent 进程的 `cwd` 都是临时隔离会话目录，而不是源码仓目录；这样不会把源码仓文件意外暴露成问题上下文。完整 launcher argv 和 `--version` 输出都需要写入评测产物。

```json
{
  "name": "candidate",
  "binary": "D:/codeagent-candidate/codeagentcli.exe",
  "memory_mode": "enabled",
  "version_label": "after-recall-change"
}
```

每次运行保存 binary 路径和版本、代码提交、写入/查询提示词全文及 SHA-256、memory state 哈希、轨迹集合与顺序和完整参数。不兼容的 memory state 不得被静默复用。

## 8. 评分与回归报告

现有标准答案和评分函数继续复用。评分输入改为 CodeAgent 的直接最终答案。

| 类型 | 条件 |
|---|---|
| `improved` | baseline 错，candidate 对 |
| `regressed` | baseline 对，candidate 错 |
| `both_correct` | 两组都对 |
| `both_wrong` | 两组都错 |

核心指标：

```text
accuracy_delta = candidate_accuracy - baseline_accuracy
net_improved_count = improved - regressed
net_improved_rate = (improved - regressed) / question_count
baseline_memory_gain = baseline_accuracy - memory_off_accuracy
candidate_memory_gain = candidate_accuracy - memory_off_accuracy
```

报告同时提供总体、能力分类和逐题 diff。正式比较应支持重复运行，报告均值、标准差和逐题多数票，以降低模型随机性。

## 9. 写入与召回归因

端到端主实验：

```text
A 写入 + A 召回  vs  B 写入 + B 召回
```

召回隔离实验：

```text
同一份冻结记忆 + A 召回
vs
同一份冻结记忆 + B 召回
```

写入隔离实验：

```text
A 写入形成的记忆 + 固定召回
vs
B 写入形成的记忆 + 固定召回
```

诊断产物可以包含内部 memory 快照、哈希和日志，但不得重新注入最终回答流程。

## 10. 结论

现有数据、标准答案和评分函数足以支持目标评测。主要工程改造是：端到端直接回答接口、真正读取轨迹的 `memory_off`、harness 绕过外部 reader、baseline/candidate 独立构建与版本溯源，以及三组逐题配对对比器。

## 11. 已验证的真实 CLI 行为（2026-09-11）

使用 CodeAgent CLI `1.2605.00` 和默认可用模型 `deepseek-v4-pro` 完成了唯一合成事实 `ZEBRA-7419` 的最小双组实验：

- 开启 auto-memory 后，轨迹会话在指定 memory 目录生成 `MEMORY.md` 和具体记忆文件；
- 在全新工作目录和新 session ID 中，Agent 能从相同 memory 目录召回 `ZEBRA-7419`；
- 关闭 auto-memory 后，同样的轨迹处理调用不生成 memory 文件；
- 关闭 auto-memory 的全新问题会话按提示返回 `UNKNOWN`；
- 两组均使用 `--no-session-persistence`，轨迹和问题调用具有不同 session ID。

验证还发现：

1. auto-memory 会注入记忆索引，但读取具体记忆文件仍需要 `Read` 工具；查询不能使用 `--tools=` 全禁用工具，应限制为只读 `--tools=Read`；
2. 将 `CODEAGENT3_CONFIG_DIR` 指向空的逐会话目录会丢失已配置模型和认证，实测回退至 `glm-5` 并收到 401；适配器应继承正常 CodeAgent 配置，通过临时工作目录、`--no-session-persistence` 和独立 memory 快照实现评测隔离。
