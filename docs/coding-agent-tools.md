# Coding-Agent CLI Configuration and Integration

This guide covers maintaining Claude Code configurations when models or binary
paths change, and integrating another coding-agent harness such as OpenCode.

## Maintaining Claude Code configurations

The evaluator treats the agent executable and the model identifier as separate
configuration. Keep both explicit in reproducible runs: a CLI upgrade may move
the executable, while a gateway or third-party provider may rename or retire a
model without changing the CLI.

Configuration passed on the `evaluation/run_eval.py` command line takes
precedence over the corresponding environment variable. The environment
variables are convenient for the shell wrappers; the command-line flags are
better for one-off comparisons:

```bash
# Persistent for evaluation/scripts/run_claude_code.sh
export CLAUDE_BINARY=/absolute/path/to/claude
export CLAUDE_MODEL=third-party-model-id
export CLAUDE_VERSION_LABEL=claude-2.1.0-provider-name

# Equivalent one-off override
python evaluation/run_eval.py \
  --method claude_code \
  --claude-binary /absolute/path/to/claude \
  --claude-model third-party-model-id \
  --claude-version-label claude-2.1.0-provider-name \
  ...
```

The JSON form is `memory_params.claude_params.binary` and
`memory_params.claude_params.model`; see
[`evaluation/memory_configs/claude_code.json`](../evaluation/memory_configs/claude_code.json).
Do not change `DEFAULT_CLAUDE_BINARY` or `DEFAULT_CLAUDE_MODEL` for an
individual experiment. Defaults in source code are fallbacks, not experiment
provenance.

### Changing to a third-party model

1. Configure the provider's base URL and credential in the environment expected
   by that CLI. For Claude Code compatible gateways these are commonly
   `ANTHROPIC_BASE_URL` and `ANTHROPIC_AUTH_TOKEN`; follow the gateway's current
   documentation because names and authentication schemes can differ.
2. Query the gateway's live model catalog and copy the exact model ID into
   `CLAUDE_MODEL` or `--claude-model`. A model name that worked previously is not
   proof that it is still available.
3. Run the exact configured binary with `--version`, then make one minimal
   non-interactive request before starting a benchmark run.
4. Use a distinct `CLAUDE_VERSION_LABEL` and output root for every CLI/provider/
   model combination. The detected CLI version is recorded automatically, but
   the label should also identify provider-side differences that `--version`
   cannot reveal.
5. Preserve the generated memory config and gateway configuration alongside the
   run metadata, but never commit API keys, OAuth files, or tokens.

If the gateway environment must apply only to this benchmark, point
`CLAUDE_BINARY` at a small executable launcher rather than modifying global
Claude settings. The launcher should set the gateway variables and then replace
itself with the real Claude executable while forwarding every argument
unchanged. It must not inject `--model`: the evaluator already supplies that
flag. On Windows, use an executable or `.cmd` launcher that Python can start
directly; a PowerShell function such as `claudex` is interactive-shell state and
is not a valid `CLAUDE_BINARY`.

### Updating a moved Claude executable

If the Claude executable moves after an install or upgrade, locate and verify it
again before running:

```bash
# Linux/macOS
command -v claude
/absolute/path/to/claude --version

# PowerShell
Get-Command claude -All
& 'C:\absolute\path\to\claude.exe' --version
```

Then update `CLAUDE_BINARY`, `--claude-binary`, or the `binary` field in the
memory config. Prefer an absolute, versioned path for published comparisons.
Do not point the evaluator at a shell alias or function. If a wrapper replaces
the underlying installation, verify that `--version`, `-p`, `--output-format
json`, `--model`, `--max-turns`, and argument forwarding still work. Enable
`CLAUDE_BARE` or `CLAUDE_EFFORT` only after verifying the selected CLI version
supports the corresponding flags.

## Adding another coding-agent tool

Adding an agent harness such as OpenCode is an adapter task, not only a new
shell script. Use the following workflow:

1. Establish the CLI contract manually: version command, non-interactive prompt
   mode, model selection, working-directory behavior, permission/sandbox flags,
   structured output, timeout behavior, exit codes, and token-usage fields.
   Save representative success, tool-call, malformed-output, timeout, and error
   fixtures. Never parse terminal decoration intended only for humans.
2. Add `memory_modules/<agent_name>.py`. Implement a registered `Memory`
   backend with a unique `memory_type`. It may subclass `CodexMemory` when it can
   reuse the trajectory workspace and evidence protocol, as
   `ClaudeCodeMemory` does, but it must override command construction and output
   parsing for the new CLI.
3. Resolve the configured binary with `shutil.which` or an explicit path,
   validate all model/timeout/retry/turn parameters, invoke the process with an
   argument list rather than a shell string, and record the detected `--version`
   in `memory_config` for provenance.
4. Make the adapter return the standard memory context contract from `query`:
   a list of non-empty text items and/or existing image paths. Keep benchmark
   IDs, answers, question types, and other private evaluator metadata out of the
   agent prompt.
5. Import the backend at the bottom of `memory_modules/memory.py` so registration
   occurs, and add `evaluation/memory_configs/<agent_name>.json` with explicit
   binary, model, timeout, retry, turn, and extra-argument fields.
6. Add the method and its CLI/environment options to
   `evaluation/run_eval.py`, including a `build_memory_config` branch. Add it to
   each relevant method allowlist in `evaluation/harness.py`; these lists also
   control workspace setup, query traces, lifecycle behavior, and validation.
7. Add `evaluation/scripts/run_<agent_name>.sh`, following the existing wrappers
   for owned arguments, web/enterprise iteration, tier handling, and isolated
   output directories. Update the repository layout/module list in the main
   README.
8. Test binary resolution, exact command arguments, structured-output parsing,
   usage extraction, retry/timeout/cancellation, configuration serialization,
   and one tiny end-to-end query before running a tier. Confirm the saved run
   metadata contains the resolved binary, detected version, model, and all
   behavior-affecting flags.

### OpenCode naming example

For an OpenCode adapter, use names such as `memory_type = "opencode"`,
`OPENCODE_BINARY`, `OPENCODE_MODEL`, `--opencode-binary`, and
`--opencode-model`. Do not assume OpenCode accepts Claude Code or Codex flags;
map only capabilities confirmed by the installed OpenCode version, and keep
provider authentication in its documented environment/config rather than in
the benchmark memory JSON.
