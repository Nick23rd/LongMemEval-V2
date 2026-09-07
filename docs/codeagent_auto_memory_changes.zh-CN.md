# CodeAgent Auto Memory 修改记录

## 2026-09-07 架构修订

- 将 backend、配置、脚本、测试和文档从 `free_code_auto_memory` 统一更名为 `codeagent_auto_memory`，明确其产品依赖。
- 新增 `StatefulMemory` 生命周期接口和 `evaluation/memory_lifecycle.py`，把构建顺序与 finalize 从通用 harness 中抽离。
- ingestion 改为逐轨迹临时沙箱，成功后才提交 memory；移除 `--dangerously-skip-permissions`，限制可用工具。
- query 使用逐题冻结副本并禁用工具，继续校验主记忆未变化。
- 拆分 ingestion/query 尝试次数，分别记录每次尝试和每条轨迹的最终结果。
- 新增 checkpoint 恢复、轨迹内容指纹校验和构建状态机；未完成的保存状态不能加载评测。
- 根据数据 schema 明确采用 haystack 顺序，并在 manifest 中记录排序依据。
- 加载阶段不再要求 trajectories 文件；构建和评测阶段的输入边界更清楚。
- 将构建指标写入最终 `aggregated_metrics.json.memory_build`，并保留每次调用的审计日志。
- 审计目录只保存输入 JSON、stdout、stderr 和 summary，不再为每次调用复制完整 memory 快照与截图资源。
- 更新 README、设计说明和手动测试手册中的名称、参数、产物及运行方法。

## 兼容性

旧名称、旧配置键和旧脚本不再作为公开入口。已有旧版 `memory_state` 需要使用旧提交完成评测，或使用新版重新构建，避免在同一结果中混合两套隔离与生命周期语义。
