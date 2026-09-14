# 原生记忆 Agent 黑盒适配协议

## 目标

LongMemEval-V2 不要求修改被测 Agent。开源或闭源 Agent 均作为黑盒，通过本仓库中的适配器接入。评测框架负责数据选择、隔离、冻结、审计和评分；适配器只负责调用产品公开提供的 CLI、API 或其他自动化入口，并访问产品允许访问的记忆状态。

## 通用生命周期

一个原生记忆适配器必须实现 `NativeMemoryAgent`，并保证：

1. 按 benchmark 顺序摄取历史 trajectory；
2. 每条 trajectory 使用独立历史 session，只共享被测产品的原生长期记忆；
3. 构建完成后形成可复现的冻结状态或等价隔离状态；
4. 每道题使用全新 session，只提供题目，不提供原始 trajectory；
5. 查询不得修改冻结主记忆；
6. Agent 的原始最终回答直接进入评分器。

适配器通过 `NativeMemoryCapabilities` 声明文件摄取、新查询 session、冻结快照、历史 session 导入和本地状态能力。声明会写入 `ingestion_manifest.json`，使受限的闭源接入不会被误当作完整可复现评测。

## 代码边界

- `memory_modules/native_memory_agent.py`：通用基类、能力声明、runtime 路径注入和 resume 判定。
- `memory_modules/codeagent_auto_memory.py`：现有 CodeAgent/free-code CLI 黑盒适配器。
- `evaluation/harness.py`：只识别通用 native-memory 类型，不硬编码某个产品名称来注入生命周期目录。

新增闭源 Agent 时，在本仓库增加一个 `NativeMemoryAgent` 子类并注册新的 `memory_type`。产品特有的启动参数、认证引用、结果解析和记忆访问方式留在该适配器内；不得修改被测程序，也不得把凭据写入配置或产物。

## 闭源产品的身份与可复现性

无法取得 Git commit 时，适配器应尽量记录产品版本、CLI/API 版本、模型、服务端日期、配置、launcher 或 endpoint、输入哈希以及本地可执行文件 SHA-256。账号和远程 workspace 只记录不可逆标识，不保存凭据。

如果产品无法导出或复制记忆，必须将 `frozen_memory_snapshot` 或 `local_memory_state` 声明为 `false`，并使用独立账号/workspace 做实验隔离。若产品不能形成跨 session 记忆、不能建立全新查询 session，或查询必然污染主记忆，则不满足正式原生长期记忆评测条件，只能作为受限 smoke 留存。

## 当前适配器

`codeagent_auto_memory` 已迁移到该协议，适配器名为 `codeagent_cli`。默认 `trajectory_file` 路径只调用原版 CLI；`historical_session` 是修改版 free-code 的可选实验能力，不属于通用协议要求，也不得成为闭源 Agent 的接入前提。
