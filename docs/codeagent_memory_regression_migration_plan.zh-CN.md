# CodeAgent 内部记忆回归评测改造计划书

## 1. 目标和状态

将当前 `codeagent_auto_memory` 的“记忆证据输出 + 外部 reader”路径，改造成支持 `memory_off`、`baseline`、`candidate` 三组实验的端到端回归框架。

相关设计：

- [评测目标](codeagent_memory_regression_evaluation_goal.zh-CN.md)
- [评测设计](codeagent_memory_regression_evaluation_design.zh-CN.md)

任务状态约定：`[ ]` 未开始，`[-]` 进行中，`[x]` 已完成，`[!]` 受阻。

当前总体状态：**目标与设计已完成，代码改造尚未开始**。

## 2. Phase 0：确认真实 CodeAgent 行为

- [ ] 记录目标 binary 路径和 `--version` 输出。
- [ ] 验证 `CODEAGENT3_DISABLE_AUTO_MEMORY=0` 确实启用内部记忆。
- [ ] 验证 `CODEAGENT3_DISABLE_AUTO_MEMORY=1` 完全关闭内部记忆。
- [ ] 验证关闭记忆后，轨迹会话不生成 memory 文件。
- [ ] 验证 `--no-session-persistence` 后无法恢复轨迹会话。
- [ ] 确认查询内部记忆所需的工具和权限。
- [ ] 记录环境变量、config 目录和 memory 目录的真实作用。

验收：用真实 CLI 最小样例证明有记忆的新会话可回答，而关闭记忆的新会话不能从旧会话获取信息。

## 3. Phase 1：扩展核心接口

预计涉及 `memory_modules/memory.py`、`memory_modules/codeagent_auto_memory.py` 和对应测试。

- [ ] 定义端到端回答结果类型 `AgentAnswer`。
- [ ] 定义端到端 capability 接口或标识。
- [ ] 保留 `Memory.query()`，确保检索型 backend 不受影响。
- [ ] 为 `CodeAgentAutoMemory` 实现 `answer()`。
- [ ] 返回原始回答、usage、延迟和审计元数据。
- [ ] 查询前后比较冻结主记忆。
- [ ] 确保每题使用独立 session/config 目录。
- [ ] 为文本题和带图题增加测试。

验收：CodeAgent 的最终回答不经过 `MemoryContextItem`；原有 backend 测试继续通过。

## 4. Phase 2：三种实验模式

预计涉及 `codeagent_auto_memory.py`、`run_eval.py`、memory config 和运行脚本。

- [ ] 增加 `experiment_mode`：`memory_off`、`baseline`、`candidate`。
- [ ] 未知模式立即报错。
- [ ] 三种模式均执行相同轨迹摄取调用。
- [ ] `memory_off` 在摄取和查询阶段均关闭 auto-memory。
- [ ] `memory_off` 不启用 `require_memory_write`。
- [ ] 检查 `memory_off` 的 memory 文件数和总字节数为零。
- [ ] 检查不存在可恢复的轨迹会话状态。
- [ ] baseline/candidate 使用独立 workspace 和 memory state。
- [ ] 支持不同 binary、version label 和提示词文件。
- [ ] 写入策略变化时强制从空状态独立构建。
- [ ] 增加模式隔离、配置保存和状态加载测试。

验收：三组轨迹 ID、内容指纹、顺序和处理次数一致；`memory_off` 不留下跨会话状态。

## 5. Phase 3：harness 直接回答路径

预计涉及 `evaluation/harness.py`、`evaluation/qa_eval_metrics.py` 和相关测试。

- [ ] 根据 capability 区分检索路径与直接回答路径。
- [ ] 端到端路径跳过 memory-context 拼接。
- [ ] 端到端路径不调用 `generate_all_reader_outputs()`。
- [ ] 将 `answer()` 的 `response_raw` 直接交给已有解析和评分函数。
- [ ] 保留原始回答、解析答案、UNKNOWN 和 usage。
- [ ] 调整 `prompt_rows.jsonl`，避免把答案误记成 memory context。
- [ ] 在逐题结果中记录执行路径和实验模式。
- [ ] 分别统计构建和回答的 token/延迟。
- [ ] 统一处理查询失败、空回答和超时。
- [ ] 保持旧检索型路径兼容。

验收：端到端运行不会创建外部 reader client；评分对象可证明是 CodeAgent 原始回答。

## 6. Phase 4：版本与提示词溯源

- [ ] 保存实验组名称和 run ID。
- [ ] 保存 binary 绝对路径、版本和代码提交。
- [ ] 保存写入/查询提示词全文及 SHA-256。
- [ ] 保存 memory state 文件级哈希和整体摘要哈希。
- [ ] 保存轨迹集合、顺序和内容指纹。
- [ ] 保存影响公平性的全部参数。
- [ ] 加载已有状态时校验版本和构建配置。

验收：任意结果都能回答由哪个版本、提示词、轨迹和参数生成；不兼容状态不能静默复用。

## 7. Phase 5：回归对比器

建议新增 `evaluation/compare_memory_regression.py`。

- [ ] 接受三组 `per_question.jsonl`。
- [ ] 校验 question ID 完全一致且无重复。
- [ ] 校验 tier、领域、评分配置和关键参数可比较。
- [ ] 按 question ID 配对，不依赖行顺序。
- [ ] 计算三组总体准确率。
- [ ] 计算 accuracy delta、improved、regressed、both correct/wrong。
- [ ] 计算净改进数、净改进率和两版 memory gain。
- [ ] 输出各能力分类结果。
- [ ] 输出逐题 JSONL diff、JSON 汇总和 Markdown 报告。
- [ ] 增加输入不匹配和缺题测试。

验收：报告直接列出改进题和退化题；汇总能从逐题 diff 独立重算。

## 8. Phase 6：写入与召回归因

- [ ] 支持“同一冻结记忆 + 不同召回版本”。
- [ ] 支持“不同写入版本 + 相同召回版本”。
- [ ] 检查不同版本的 memory 格式兼容性。
- [ ] 不兼容时明确拒绝运行。
- [ ] 将端到端结论与归因结论分开报告。
- [ ] 保证诊断信息不注入最终回答。

验收：能够判断变化主要来自写入、召回还是组合效果。

## 9. Phase 7：重复运行与统计稳定性

- [ ] 支持重复次数和随机种子。
- [ ] 保存每次独立运行的原始结果。
- [ ] 计算准确率均值和标准差。
- [ ] 生成逐题多数票结果。
- [ ] 增加配对置信区间或显著性报告。
- [ ] 记录远程模型随机性限制。

验收：能区分稳定改进与单次波动；单次和多次运行共用结果 schema。

## 10. Phase 8：脚本与文档

- [ ] 增加 10～30 题开发冒烟配置。
- [ ] 增加 small tier 三组完整回归脚本。
- [ ] 增加 medium tier 发布验证脚本。
- [ ] 支持分别构建和加载三组 memory state。
- [ ] 更新主 README 和手动测试文档。
- [ ] 提供完整示例报告。

验收：新用户按文档即可完成一次三组 small tier 回归。

## 11. 测试清单

### 单元测试

- [ ] experiment mode 配置验证。
- [ ] auto-memory 环境变量验证。
- [ ] `memory_off` 仍调用轨迹摄取。
- [ ] `memory_off` 空状态验证。
- [ ] 独立会话/config 目录验证。
- [ ] 查询不能访问轨迹。
- [ ] 查询不能修改冻结主记忆。
- [ ] 直接回答解析与评分。
- [ ] 端到端路径不会调用外部 reader。
- [ ] baseline/candidate 状态不混用。
- [ ] 对比器配对和分类计算。

### 集成与兼容测试

- [ ] fake CLI 完成三组端到端流程。
- [ ] fake CLI 模拟 memory_off 意外写文件并验证失败。
- [ ] fake CLI 模拟查询修改主记忆并验证失败。
- [ ] 真实 CodeAgent + 一条合成轨迹最小验证。
- [ ] 真实数据精选题冒烟。
- [ ] small tier 完整报告。
- [ ] 原有 backend 注册、加载和 reader 路径继续通过。
- [ ] 旧 memory state 给出明确兼容或拒绝信息。

## 12. 建议实施顺序

```text
Phase 0 产品行为确认
→ Phase 1 核心接口
→ Phase 2 三组模式
→ Phase 3 harness 直接回答
→ Phase 4 可复现性
→ Phase 5 对比器
→ Phase 8 冒烟脚本
→ Phase 6 归因实验
→ Phase 7 多次运行统计
→ 完整文档和发布验证
```

Phase 0 是前置条件：未确认真实 CodeAgent 的记忆开关、读取方式和隔离语义前，fake CLI 测试通过也不能证明评测有效。

## 13. 进度记录

| 日期 | 阶段 | 状态 | 说明 |
|---|---|---|---|
| 2026-09-11 | 目标确认 | 已完成 | 确认为修改前/后内部记忆机制的端到端回归评测 |
| 2026-09-11 | 数据适用性 | 已完成 | 题目、haystack、答案和评分函数可以复用 |
| 2026-09-11 | 改造设计 | 已完成 | 确认三组实验、直接回答、配对 diff 和归因实验 |
| 2026-09-11 | 代码改造 | 未开始 | 等待按本计划实施 |

后续每完成一项，应更新对应复选框，并在本表追加日期、阶段、状态、验证命令和产物位置。

