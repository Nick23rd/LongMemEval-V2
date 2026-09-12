# Free-code 历史 Session 记忆摄取方案

## 目标

当前 `codeagent_auto_memory` 为每条 LongMemEval trajectory 启动独立进程，让主 agent 读取
`trajectory/trajectory.json` 和截图、理解历史、再主动写入 auto-memory。该方式保持了 session
隔离，但同时测量了文件探索能力，实测 100 条 trajectory 构建耗时 12,729 秒、平均每条
127 秒和约 16 个主 agent turns。

本方案把 trajectory 转为固定的 normalized session events，直接交给 free-code 的原生
`extractMemories` 流程。每条 trajectory 是一个独立历史 session；不同 session 不共享上下文，
只按 haystack 顺序共享 auto-memory。

## 数据映射

LongMemEval trajectory 包含 `goal`、`outcome` 以及有序 `states`。每个 state 包含 URL、action、
accessibility tree、截图和可选 thought。固定映射如下：

1. `goal` 转为 user message。
2. 初始 state 的 URL、accessibility tree 和截图转为 synthetic browser observation。
3. 每个非空 `action` 转为 synthetic browser tool use。
4. 下一个 state 转为对应 tool result。
5. `outcome` 只作为 session completion metadata，不伪造 assistant 最终答案。
6. `thought` 默认丢弃；它不是用户可见 transcript，不能作为额外答案证据。

转换器必须是纯函数，并对输出做版本标记和 SHA-256，以保证 baseline 与 candidate 输入完全一致。

## Free-code 内部入口

建议增加仅供 benchmark 使用的内部入口：

```ts
extractHistoricalSession({
  sessionId,
  messages,
  memoryDirectory,
})
```

入口应复用正常 CLI 初始化后的 system prompt、user/system context、工具权限与模型配置，构造
`REPLHookContext` 后调用 `executeExtractMemories()`，并等待 `drainPendingExtraction()` 完成。
不能只写 session JSONL：当前 extraction 消费的是 query-loop 内存中的 `context.messages`，不会扫描
磁盘 transcript 自动触发。

## 隔离与生命周期

- 每条 trajectory 使用新的 session ID 和 transcript。
- 每条 trajectory 结束后，等待 extraction 完成再释放临时 session 资源。
- session 之间只共享指定的 auto-memory 目录。
- 严格保持 haystack 顺序；失败、重试和空写入均记录在 manifest。
- importer 不调用主回答 agent，不执行历史 action，也不访问真实网站。
- extraction forked agent 沿用 free-code 当前的 5 turns 硬上限。

## 对照实验

第一阶段使用同一组 3 条 web/small trajectory 对比：

| 指标 | trajectory-file 基线 | historical-session |
|---|---:|---:|
| 墙钟时间 | 记录 | 记录 |
| 主 agent turns | 记录 | 必须为 0 |
| extraction turns | 不适用/记录 | 记录 |
| 输入、缓存和输出 Token | 记录 | 记录 |
| memory 新增/修改文件 | 记录 | 记录 |
| 空写入、失败和重试 | 记录 | 记录 |
| 目标问题召回结果 | 记录 | 记录 |

只有同时满足以下条件才扩展到 10 题 calibration：historical-session 没有主 agent 调用；三条轨迹
均经过独立 session；共享范围仅为 auto-memory；关键记忆事实没有明显丢失；墙钟时间至少降低
50%。calibration 通过后才考虑运行 full small。

## 风险

- Synthetic tool events 语义接近浏览器历史，但不是 free-code 原生工具真实执行产生的事件；报告中必须披露。
- free-code 的 `executeExtractMemories` 受 feature gate、auto-memory 开关和启动初始化影响。裸脚本可能
  静默跳过 extraction，因此 importer 必须走受支持的初始化路径并对“零 extraction”报错。
- accessibility tree 可能很长。转换器应保持原始内容，首版不做模型摘要；后续只能采用确定性的截断或
  去重，并将规则版本化。
- 数据没有原始 system prompt、工具调用 ID 和完整最终回复，因此只能恢复语义等价 session，不能宣称
  无损重放原始执行环境。

## 2026-09-12 可行性探针

在 `dev-full` 构建中显式开启 `EXTRACT_MEMORIES`，并通过 GrowthBook override 开启
`tengu_passport_quail`、非交互 extraction 和每轮 extraction。将一条 trajectory 以 UTF-8 管道注入
独立 `-p` session，要求主 agent 不读文件、不调用工具、不直接写 memory，只确认导入。

结果：有效输入约 17,655 tokens，主 agent 1 turn，API 时间 2.6 秒，进程墙钟 6.2 秒；相比现有
trajectory-file smoke 中约 13～30 秒/条以及完整 100 条实测平均 127 秒/条，输入本身可以大幅提速。
但是该次调用没有生成 memory 文件，debug log 也没有出现 `extractMemories` 执行记录，因此这是无效的
记忆摄取结果，不能用于准确率或最终速度结论。

该探针验证了两个边界：

1. Windows 管道必须强制 UTF-8，否则 trajectory 中的 Unicode 会导致输入为空；importer 必须绕开
   shell 文本管道或显式使用 UTF-8 字节协议。
2. 即使 feature/growthbook gate 已显式开启，普通 headless CLI 的单轮注入也不能可靠触发
   `executeExtractMemories`。因此必须实现本文所述内部 importer，并将“至少发生一次 extraction 或明确
   返回 no-memory-worthy”设计为结构化结果；仅靠进程成功退出不能视为摄取成功。

当前探针的 6.2 秒只能视为“会话注入 + 一次确认模型调用”的开销上界，不是完成 memory extraction
的耗时。下一阶段应在 free-code 内部入口完成后，用同一条 trajectory 测量 extraction 的真实耗时，
然后扩展到固定 3 条对照。

### 有效 extraction 对照

随后修复了 free-code headless 初始化与 shutdown 的两个竞态：headless query 开始前必须完成
`initExtractMemories()`；benchmark historical-session 模式退出前必须等待
`drainPendingExtraction()`。增加显式 benchmark gate 后，固定 3 条 trajectory 均以不同 session ID
运行并共享一个全新的 auto-memory 目录。

结果：

| 运行 | 3 条总耗时 | 平均每条 | 主 agent turns | memory 结果 |
|---|---:|---:|---:|---|
| trajectory-file smoke 02 | 39.45 秒 | 13.15 秒 | 24 | 0 个文件 |
| trajectory-file smoke 03 | 58.94 秒 | 19.65 秒 | 28 | 5 个文件 |
| historical-session PoC | 39.47 秒 | 13.16 秒 | 3 | 2 个事实文件 + index |

historical-session 生成的事实文件覆盖了 One Stop Market 商品评论入口及差评内容、Postmill 修改 bio
的入口、字段、保存确认和失败循环，未再保存 importer 指令。首条 Magento theme preview 没有形成
独立记忆，属于允许的 no-memory-worthy/漏记候选，需要在后续 10 条校准中审计。

在 3 条 smoke 上，新路径相对有效的旧路径约快 1.5 倍，并把主 agent 从每条约 8～9 turns 降至
1 turn。相对 100 条完整构建的实测均值 127 秒/条，当前 13.16 秒/条约快 9.7 倍；后者只是外推，
不能替代 10 条和 100 条验证。

当前 PoC 为了复用 CLI 已初始化的完整 `REPLHookContext`，仍保留一次只返回 `OK` 的主 agent 调用；
真实事实写入由随后独立的 `extract_memories` fork 完成。下一次迭代应把 normalized messages 直接交给
内部 importer，删除这个确认调用，并将 extraction turns、Token、费用、写入路径和 no-memory-worthy
状态写入结构化 stdout。

### 完整 100 条非图片题验证

使用无 question image 的 `05cce9b3`，按 web/small 完整有序 haystack 运行 100 个独立 session，
模型全部为 `deepseek-flash`。输入转换丢弃 thought；由于部分 accessibility tree 超过上下文，为每条
轨迹设置 300,000 字符 observation 总预算，每个 state 为 2,000～16,000 字符并保留 70% 头部、
30% 尾部。运行支持逐 session 断点续跑。

结果：

| 指标 | 结果 |
|---|---:|
| 成功 session | 100/100 |
| 成功 session 耗时合计 | 1,235.6 秒（20.6 分钟） |
| 平均 / 中位 / P95 / 最大 | 12.36 / 9.48 / 27.45 / 76.01 秒 |
| 偶发超时 | 1 次，300 秒，重试成功 |
| 计入超时后的实际模型运行时间 | 约 25.6 分钟 |
| 修改 memory 的 session | 2/100 |
| 最终事实文件 | 1 个 + `MEMORY.md` |
| 主调用输入 Token | 6,868,468 |
| 主调用报告费用（不含 extraction fork） | $37.3645 |

冻结 memory 查询耗时 3.21 秒、2 turns，返回 `UNKNOWN`；标准答案是 `Login as Customer`。最终
memory 只有 Magento Blank/Luma theme 与 storefront review 信息，没有客户详情页 toolbar 信息。

结论：当前 PoC 的运行速度相对原 3.54 小时构建快约 8～10 倍，但记忆召回失败，不能替代现有方案。
主要原因不是 session 隔离，而是 normalized events 仍被包装成一个 stdin user message；background
extractor 没有把 action/observation 序列当作正常多轮 transcript，准入率从原完整构建的 70 次成功写入
降至 2 次变更。下一版本必须实现真正的内部 `Message[]` importer，不能继续优化单消息包装提示词。
