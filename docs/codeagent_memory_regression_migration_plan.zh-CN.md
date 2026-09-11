# CodeAgent 内部记忆回归评测改造计划书

## 1. 目标和状态

将当前 `codeagent_auto_memory` 的“记忆证据输出 + 外部 reader”路径，改造成支持 `memory_off`、`baseline`、`candidate` 三组实验的端到端回归框架。

相关设计：

- [评测目标](codeagent_memory_regression_evaluation_goal.zh-CN.md)
- [评测设计](codeagent_memory_regression_evaluation_design.zh-CN.md)

任务状态约定：`[ ]` 未开始，`[-]` 进行中，`[x]` 已完成，`[!]` 受阻。

当前总体状态：**Phase 0～6 已完成；正式 small 三组入口及写入/召回 2×2 归因入口已具备。下一阶段为真实归因冒烟与重复运行统计**。

## 2. Phase 0：确认真实 CodeAgent 行为

- [x] 记录目标 binary 路径和 `--version` 输出。
- [x] 验证 `CODEAGENT3_DISABLE_AUTO_MEMORY=0` 确实启用内部记忆。
- [x] 验证 `CODEAGENT3_DISABLE_AUTO_MEMORY=1` 完全关闭内部记忆。
- [x] 验证关闭记忆后，轨迹会话不生成 memory 文件。
- [x] 验证 `--no-session-persistence` 下轨迹和问题使用不同的新 session，工作目录不保存会话文件。
- [x] 确认查询内部记忆需要只读 `Read` 工具。
- [x] 记录环境变量、config 目录和 memory 目录的真实作用。

验收：用真实 CLI 最小样例证明有记忆的新会话可回答，而关闭记忆的新会话不能从旧会话获取信息。

## 3. Phase 1：扩展核心接口

预计涉及 `memory_modules/memory.py`、`memory_modules/codeagent_auto_memory.py` 和对应测试。

- [x] 定义端到端回答结果类型 `AgentAnswer`。
- [x] 定义端到端 capability 接口或标识。
- [x] 保留 `Memory.query()`，确保检索型 backend 不受影响。
- [x] 为 `CodeAgentAutoMemory` 实现 `answer()`。
- [x] 返回原始回答、usage、延迟和审计元数据。
- [x] 查询前后比较冻结主记忆。
- [x] 确保每题使用独立 session/config 目录。
- [ ] 为带图题增加专门测试（文本题已覆盖）。

验收：CodeAgent 的最终回答不经过 `MemoryContextItem`；原有 backend 测试继续通过。

## 4. Phase 2：三种实验模式

预计涉及 `codeagent_auto_memory.py`、`run_eval.py`、memory config 和运行脚本。

- [x] 增加 `experiment_mode`：`memory_off`、`baseline`、`candidate`。
- [x] 未知模式立即报错。
- [x] 三种模式均执行相同轨迹摄取调用。
- [x] `memory_off` 在摄取和查询阶段均关闭 auto-memory。
- [x] `memory_off` 不启用 `require_memory_write`。
- [x] 检查 `memory_off` 的 memory 文件数和总字节数为零。
- [ ] 检查不存在可恢复的轨迹会话状态（依赖 Phase 0 对真实 CLI 状态目录的确认）。
- [x] baseline/candidate 通过各次运行的独立 workspace 和 memory state 隔离。
- [x] 支持不同 binary、version label 和提示词文件。
- [x] 现有 workspace 覆盖保护确保写入策略变化时从空状态构建，显式 resume 除外。
- [x] 增加模式隔离、配置保存和状态加载相关测试。

验收：三组轨迹 ID、内容指纹、顺序和处理次数一致；`memory_off` 不留下跨会话状态。

## 5. Phase 3：harness 直接回答路径

预计涉及 `evaluation/harness.py`、`evaluation/qa_eval_metrics.py` 和相关测试。

- [x] 根据 capability 区分检索路径与直接回答路径。
- [x] 端到端路径跳过 memory-context 拼接。
- [x] 纯端到端运行不创建或调用外部 reader。
- [x] 将 `answer()` 的 `response_raw` 直接交给已有解析和评分函数。
- [x] 保留原始回答、解析答案、UNKNOWN 和规范化 usage。
- [x] 调整 `prompt_rows.jsonl`，直接答案不再伪装成 memory context。
- [x] 在逐题结果中记录执行路径和实验模式。
- [x] 使用现有 memory_build 与 memory_query 指标分别统计构建和直接回答成本。
- [x] 复用查询重试、空回答和超时错误处理。
- [x] 保持旧检索型路径兼容。

验收：端到端运行不会创建外部 reader client；评分对象可证明是 CodeAgent 原始回答。

## 6. Phase 4：版本与提示词溯源

- [x] 使用 experiment mode 和现有运行目录/run args 标识实验运行。
- [x] 保存 binary 绝对路径、检测版本和用户提供的 version label（代码提交可写入 version label）。
- [x] 同时支持打包 `.exe` 和源码仓多段 launcher argv，并保存完整启动命令。
- [x] 保存摄取、检索和直接回答提示词全文及 SHA-256。
- [x] 保存 memory state 文件级哈希和整体摘要哈希。
- [x] 保存轨迹集合、顺序和内容指纹。
- [x] 使用现有 `run_args.json` 和 `memory_config.json` 保存完整参数。
- [x] 加载已有状态时校验实验模式、CodeAgent 版本、提示词哈希和构建配置。

验收：任意结果都能回答由哪个版本、提示词、轨迹和参数生成；不兼容状态不能静默复用。

## 7. Phase 5：回归对比器

建议新增 `evaluation/compare_memory_regression.py`。

- [x] 接受三组 `per_question.jsonl` 或对应运行目录。
- [x] 校验 question ID 完全一致且无重复。
- [x] 校验题目、分类、评分配置、标准答案和 haystack 可比较。
- [x] 按 question ID 配对，不依赖行顺序。
- [x] 计算三组总体准确率。
- [x] 计算 accuracy delta、improved、regressed、both correct/wrong。
- [x] 计算净改进数、净改进率和两版 memory gain。
- [x] 输出各能力分类结果。
- [x] 输出逐题 JSONL diff、JSON 汇总和 Markdown 报告。
- [x] 增加模式错误、输入不匹配和缺题测试。

验收：报告直接列出改进题和退化题；汇总能从逐题 diff 独立重算。

## 8. Phase 6：写入与召回归因

- [x] 支持“同一冻结记忆 + 不同召回版本”。
- [x] 支持“不同写入版本 + 相同召回版本”。
- [x] 加载时校验写入版本；查询版本和提示词只有显式归因开关才能覆盖。
- [x] 不兼容配置、缺失结果或不可比较题集明确拒绝运行。
- [x] 将端到端结论与归因结论分开报告。
- [x] 保证归因标签和诊断信息不注入最终回答。

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

- [x] 增加可通过 question IDs 和 `--haystack-limit` 控制成本的开发结构冒烟配置。
- [x] 增加 small tier 三组完整回归脚本，要求显式 `-ConfirmFullRun` 且不截断 haystack。
- [ ] 增加 medium tier 发布验证脚本。
- [x] 支持分别构建和加载写入 A/B memory state，并交叉运行召回 A/B。
- [x] 更新手动测试文档。
- [ ] 更新主 README。
- [x] 真实三组结构冒烟生成完整 JSON、JSONL 和 Markdown 示例报告。

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
- [x] 真实数据精选题、每组一条轨迹的三组结构冒烟。
- [x] 真实数据精选题完成 AA/AB/BA/BB 归因闭环。
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
| 2026-09-11 | Phase 0 | 已完成 | CLI 1.2605.00 + deepseek-v4-pro 完成 `ZEBRA-7419` 双组实验：enabled 跨会话召回，memory_off 返回 UNKNOWN 且零 memory 文件；确认查询需要 Read |
| 2026-09-11 | Phase 1 | 已完成 | 新增 `AgentAnswer`、`EndToEndMemoryAgent` 和 `CodeAgentAutoMemory.answer()`；12 tests、8 subtests 通过 |
| 2026-09-11 | Phase 2 | 核心完成 | 新增三种 experiment mode；memory_off 仍摄取轨迹并强制空记忆，意外写入标记 isolation_failed；22 tests、8 subtests 通过 |
| 2026-09-11 | Phase 3 | 已完成 | harness 按 capability 分流；CodeAgent 原始回答直接评分且纯端到端运行不创建 reader；新增直接路径测试 |
| 2026-09-11 | Phase 4 | 已完成 | 支持版本标签及三类提示词覆盖；保存正文、SHA-256、binary/version 和 memory snapshot；加载时校验兼容性 |
| 2026-09-11 | Phase 5 | 已完成 | 新增三组配对对比器，输出 comparison.json、逐题 diff 和 Markdown 报告；覆盖不匹配输入测试 |
| 2026-09-11 | Phase 8 | 部分完成 | 新增 `--haystack-limit` 和 PowerShell 三组冒烟脚本；真实题 `05cce9b3` 完成构建、直接回答和比较闭环；memory_off 为零记忆文件 |
| 2026-09-11 | Phase 8 | small 入口完成 | 新增正式 `run_codeagent_memory_regression_small.ps1`；按领域运行全部题目和完整 small haystack，并要求显式成本确认 |
| 2026-09-11 | Phase 6 | 已完成 | 分离写入与查询 launcher；新增 AA/AB/BA/BB 四象限入口和独立归因报告，计算条件写入效应、条件召回效应及交互效应 |
| 2026-09-11 | Phase 6 | 真实冒烟通过 | `05cce9b3`、每个写入组 1 条轨迹完成两次独立构建和四次交叉查询，产物为 `runs/codeagent_memory_attribution_smoke_20260911_03/attribution/report.md`；A/B 使用同一 CLI，因此四项差值均为零，符合预期 |
| 2026-09-11 | Phase 6 | 稳定性发现 | 3 条轨迹冒烟的第 2 条在 DeepSeek 上达到 30 turns 后失败并被标记 `partial_failed`；正式 small 前需提高 turn 上限或收紧摄取提示词 |
| 2026-09-11 | 基础设施修复 | 已完成 | Windows 临时目录与数据位于不同盘符时，相对截图链接安全回退为文件复制 |

后续每完成一项，应更新对应复选框，并在本表追加日期、阶段、状态、验证命令和产物位置。
