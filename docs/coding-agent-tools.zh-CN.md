# 编码智能体 CLI 配置与集成

本指南介绍在模型或二进制路径发生变化时如何维护 Claude Code 配置，以及如何集成 OpenCode 等其他编码智能体运行框架。

## 维护 Claude Code 配置

评测器将智能体可执行文件和模型标识符视为两项独立配置。在可复现运行中应明确指定二者：CLI 升级可能会移动可执行文件，而网关或第三方提供商可能会在 CLI 未变化的情况下重命名或停用模型。

通过 `evaluation/run_eval.py` 命令行传入的配置优先于对应环境变量。环境变量适合 shell 包装脚本，命令行参数更适合一次性对比：

```bash
# 持久用于 evaluation/scripts/run_claude_code.sh
export CLAUDE_BINARY=/absolute/path/to/claude
export CLAUDE_MODEL=third-party-model-id
export CLAUDE_VERSION_LABEL=claude-2.1.0-provider-name

# 等效的一次性覆盖
python evaluation/run_eval.py \
  --method claude_code \
  --claude-binary /absolute/path/to/claude \
  --claude-model third-party-model-id \
  --claude-version-label claude-2.1.0-provider-name \
  ...
```

JSON 形式为 `memory_params.claude_params.binary` 和 `memory_params.claude_params.model`；参见 [`evaluation/memory_configs/claude_code.json`](../evaluation/memory_configs/claude_code.json)。不要为单次实验修改 `DEFAULT_CLAUDE_BINARY` 或 `DEFAULT_CLAUDE_MODEL`。源代码中的默认值只是后备值，不是实验溯源信息。

### 切换到第三方模型

1. 按该 CLI 的要求，在环境中配置提供商的基础 URL 和凭据。对于兼容 Claude Code 的网关，通常是 `ANTHROPIC_BASE_URL` 和 `ANTHROPIC_AUTH_TOKEN`；具体名称和认证方式可能不同，请遵循网关的当前文档。
2. 查询网关的实时模型目录，将准确的模型 ID 复制到 `CLAUDE_MODEL` 或 `--claude-model`。某个模型名称过去可用，并不能证明它现在仍然可用。
3. 对准确配置的二进制文件运行 `--version`，然后在开始基准运行前执行一次最小化的非交互请求。
4. 每一种 CLI／提供商／模型组合都应使用不同的 `CLAUDE_VERSION_LABEL` 和输出根目录。检测到的 CLI 版本会自动记录，但标签还应标明 `--version` 无法体现的提供商侧差异。
5. 将生成的记忆配置和网关配置与运行元数据一同保留，但绝不要提交 API 密钥、OAuth 文件或令牌。

如果网关环境只应作用于本次基准测试，请让 `CLAUDE_BINARY` 指向一个小型可执行启动器，而不是修改全局 Claude 设置。启动器应设置网关变量，然后以真实 Claude 可执行文件替换自身，同时原样转发所有参数。它不能注入 `--model`，因为评测器已经提供该参数。在 Windows 上，应使用 Python 能直接启动的可执行文件或 `.cmd` 启动器；`claudex` 之类的 PowerShell 函数属于交互式 shell 状态，不能作为有效的 `CLAUDE_BINARY`。

### 更新已移动的 Claude 可执行文件

如果 Claude 可执行文件在安装或升级后移动，请在运行前重新定位并验证：

```bash
# Linux/macOS
command -v claude
/absolute/path/to/claude --version

# PowerShell
Get-Command claude -All
& 'C:\absolute\path\to\claude.exe' --version
```

随后更新 `CLAUDE_BINARY`、`--claude-binary` 或记忆配置中的 `binary` 字段。对于公开发布的对比，最好使用绝对且带版本的路径。不要让评测器指向 shell 别名或函数。如果包装器替换了底层安装，请验证 `--version`、`-p`、`--output-format json`、`--model`、`--max-turns` 以及参数转发仍能工作。只有在确认所选 CLI 版本支持相应参数后，才启用 `CLAUDE_BARE` 或 `CLAUDE_EFFORT`。

## 添加其他编码智能体工具

添加 OpenCode 等智能体运行框架是一项适配器任务，而不只是新增一个 shell 脚本。请遵循以下流程：

1. 手动确定 CLI 契约：版本命令、非交互提示模式、模型选择、工作目录行为、权限／沙箱参数、结构化输出、超时行为、退出码和令牌用量字段。保存有代表性的成功、工具调用、异常输出、超时和错误样例。绝不要解析只面向人类的终端装饰信息。
2. 添加 `memory_modules/<agent_name>.py`。实现一个已注册且具有唯一 `memory_type` 的 `Memory` 后端。如果能复用轨迹工作区和证据协议，可像 `ClaudeCodeMemory` 一样继承 `CodexMemory`，但必须针对新 CLI 覆盖命令构造和输出解析。
3. 使用 `shutil.which` 或显式路径解析配置的二进制文件，验证所有模型／超时／重试／轮次参数，以参数列表而不是 shell 字符串调用进程，并将检测到的 `--version` 记录到 `memory_config` 以便溯源。
4. 让适配器的 `query` 返回标准记忆上下文契约：由非空文本项和／或现有图片路径组成的列表。不要把基准 ID、答案、问题类型或其他评测器私有元数据放入智能体提示词。
5. 在 `memory_modules/memory.py` 底部导入该后端以完成注册，并添加 `evaluation/memory_configs/<agent_name>.json`，其中明确指定二进制、模型、超时、重试、轮次和额外参数字段。
6. 将该方法及其 CLI／环境选项添加到 `evaluation/run_eval.py`，包括一个 `build_memory_config` 分支。将它加入 `evaluation/harness.py` 中所有相关的方法允许列表；这些列表也控制工作区设置、查询轨迹、生命周期行为和验证。
7. 添加 `evaluation/scripts/run_<agent_name>.sh`，在参数归属、web／enterprise 迭代、层级处理和隔离输出目录方面遵循现有包装脚本。更新主 README 中的仓库布局／模块列表。
8. 测试二进制解析、准确的命令参数、结构化输出解析、用量提取、重试／超时／取消、配置序列化，并在运行完整层级前执行一个最小端到端查询。确认保存的运行元数据包含解析后的二进制、检测到的版本、模型以及所有影响行为的参数。

### OpenCode 命名示例

对于 OpenCode 适配器，可使用 `memory_type = "opencode"`、`OPENCODE_BINARY`、`OPENCODE_MODEL`、`--opencode-binary` 和 `--opencode-model` 等名称。不要假定 OpenCode 接受 Claude Code 或 Codex 的参数；只映射已由所安装 OpenCode 版本确认支持的能力，并将提供商认证信息放在其文档规定的环境／配置中，而不是基准测试的记忆 JSON 中。

