# CodeAgent Auto Memory 评测设计

本文是 `codeagent_auto_memory` 的当前实现说明，也是后续修改的设计边界。旧的通用名 `free_code_auto_memory` 已废弃，因为实现依赖 CodeAgent CLI 的原生 auto-memory 环境变量和命令行语义。

## 目标

评测分成两个明确阶段：

1. **构建**：按 benchmark haystack 给定顺序逐条摄取历史轨迹，由 CodeAgent 原生 auto memory 形成持久状态。
2. **评测**：从已完成的冻结状态创建逐题快照，只向 CodeAgent 提供问题，不暴露原始轨迹，也不允许查询修改主记忆。

LongMemEval-V2 的 trajectory schema 没有跨轨迹时间戳。`state_index` 和 `step` 只表示单条轨迹内部顺序，因此构建阶段保留 haystack 顺序，并在 `ingestion_manifest.json` 中记录原因。

## 模块边界

- `evaluation/memory_lifecycle.py`：状态型 memory 的构建计划、顺序和 finalize 编排。
- `evaluation/harness.py`：数据选择、问答执行、指标聚合；通过 `StatefulMemory` 接口调用生命周期。
- `memory_modules/memory.py`：定义 `Memory` 与 `StatefulMemory` 契约。
- `memory_modules/codeagent_auto_memory.py`：CodeAgent 进程、隔离目录、checkpoint、save/load 和审计记录。
- `evaluation/run_eval.py`：公开 CLI 参数和运行时配置生成。

## 隔离与提交语义

每次 ingestion 在系统临时目录中运行，只挂载该次 trajectory 和主记忆的副本。CodeAgent 仅获得 `Read,Write,Edit,Glob,Grep` 工具，并使用 `acceptEdits` 权限模式。只有进程成功退出时，副本才原子式替换工作区中的主记忆；失败尝试保留审计记录，但不污染主记忆。

每道 query 同样使用系统临时目录和冻结记忆副本。查询命令传入 `--tools=` 禁用工具，输入目录只含 `question.json`；查询结束后还会比较主记忆快照。

适配器拒绝 `--resume`、`--continue`、`--bare` 和 `--dangerously-skip-permissions` 等会破坏会话或权限边界的额外参数。

## 状态机与恢复

构建状态写入 `ingestion_manifest.json`：

- `building`：正在构建；
- `partial_failed`：最近一次轨迹的所有尝试失败；
- `complete`：全部轨迹完成；
- `complete_with_empty_ingestions`：完成，但至少一次成功调用没有产生 memory 文件变化。

启用 `--codeagent-auto-memory-resume-build` 后，可以复用现有 workspace。已完成轨迹按 ID 和内容指纹校验后跳过。保存的 `memory_state` 只接受两个完成状态；部分构建不能进入评测阶段。

ingestion 和 query 分别使用 `ingest_max_attempts` 与 `query_max_attempts`。前者默认 1，避免模型失败后重复改变构建语义；后者默认 3，用于处理无有效回答等瞬时失败。

## 产物

构建产物：

- `memory_state/auto_memory/`
- `memory_state/memory_config.json`
- `memory_state/ingestion_manifest.json`
- `memory_state/ingestion_metrics.json`
- `memory_workspaces/shared/ingestion_sessions/.../summary.json`

评测产物：

- `per_question.jsonl`
- `aggregated_metrics.json`，其中 `memory_build` 包含构建指标
- `memory_workspaces/shared/query_sessions/.../summary.json`

会话审计目录保留输入 JSON、stdout、stderr 和 summary。memory 的文件级哈希快照写在 summary/metrics 中，不重复保存完整副本。

## 运行

完整命令、环境变量、断点恢复和检查方法见 [CodeAgent Auto Memory 手动测试手册](codeagent_auto_memory_manual_test.zh-CN.md)。
