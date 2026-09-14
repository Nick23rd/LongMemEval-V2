# 文档导航

第一次接手本分支，请先阅读[项目状态与下一步](codeagent_memory_project_status.zh-CN.md)。它说明最终目标、当前实现、已知阻塞、环境就绪标志和下一阶段计划。

## 目标与架构

- [原生记忆 Agent 黑盒适配协议](native_memory_agent_adapter.zh-CN.md)：开源/闭源 Agent 的统一生命周期、能力声明与接入边界。
- [CodeAgent 内部记忆回归评测目标](codeagent_memory_regression_evaluation_goal.zh-CN.md)：评测问题、实验边界和验收标准。
- [CodeAgent 内部记忆回归评测设计](codeagent_memory_regression_evaluation_design.zh-CN.md)：历史设计记录；当前执行语义以项目状态页为准。
- [记忆评测改造计划与历史进度](codeagent_memory_regression_migration_plan.zh-CN.md)：已完成工程阶段、TODO 和历史决策。

## 当前状态与实验

- [项目状态与下一步](codeagent_memory_project_status.zh-CN.md)：当前唯一权威状态入口。
- [free-code Historical-session 摄取方案](free_code_historical_session_ingestion.zh-CN.md)：转换设计、PoC、完整 100 条速度及失败结论。
- [CodeAgent auto-memory 改动摘要](codeagent_auto_memory_changes.zh-CN.md)：早期实现改动记录。
- [CodeAgent auto-memory 评测计划](codeagent_auto_memory_evaluation_plan.zh-CN.md)：早期计划，仅作历史参考。

## 环境与运行

- [测评环境运行手册](codeagent_memory_evaluation_environment_runbook.zh-CN.md)：新机器环境搭建、launcher、校准入口和产物验收。
- [Auto-memory 手动测试手册](codeagent_auto_memory_manual_test.zh-CN.md)：single、memory-off、resume 和 full small 命令。
- [编码智能体记忆评测与对比](code_agent_evaluation.zh-CN.md)：通用 Codex、Claude Code、CodeAgent 运行与报告流程。
- [Coding-agent 工具配置](coding-agent-tools.zh-CN.md)：各类 coding agent CLI 的配置方式。

## 数据、产物与指标

- [评测产物和指标说明](evaluation_artifacts_and_metrics.zh-CN.md)：JSON/JSONL、聚合指标和报告结构。

## 英文资料

- [General coding-agent evaluation](code_agent_evaluation.md)
- [Coding-agent tools](coding-agent-tools.md)

设计和历史文档可能保留当时结论；若与“项目状态与下一步”冲突，以后者及最新运行产物为准。
