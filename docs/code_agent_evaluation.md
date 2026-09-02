# Coding-Agent Memory Evaluation and Comparison

This guide is the operational contract for comparing coding agents as
LongMemEval-V2 memory retrievers. It covers smoke tests, reproducible benchmark
runs, paired analysis, cost accounting, and report visualization.

## What Is Being Compared

The coding agent is the memory retriever, not the final answering model:

```text
trajectory haystack -> coding-agent memory backend -> compact evidence
                    -> fixed reader -> answer -> evaluator
```

Keep the reader fixed when comparing memory agents. Changing both the memory
agent and the reader makes it impossible to attribute an accuracy difference.

The repository currently provides:

- `codex`: Codex CLI retrieval via `memory_modules/codex.py`.
- `claude_code`: Claude Code retrieval via `memory_modules/claude_code.py`.

Gateway-backed wrappers such as a PowerShell `claudex` function are supported
by reproducing their environment, model, settings, and executable path. A shell
function is not itself a valid `CLAUDE_BINARY`; Python must receive an actual
executable or `.cmd` path.

## Reproducibility Rules

For every comparison, fix all variables except the one named in the experiment:

- dataset revision, tier, domain, question IDs, and question order;
- reader model, endpoint, sampling parameters, and memory-context limit;
- evidence mode, timeout, retry count, and concurrency;
- coding-agent model when measuring CLI-version changes;
- CLI version when measuring model changes;
- user settings, plugins, MCP servers, skills, hooks, and persistent memory;
- gateway/provider and authentication route;
- machine class and major filesystem behavior when reporting latency.

Record both a human label and detected CLI version. Disable automatic CLI
updates during a multi-version experiment. Never commit credentials or OAuth
state.

Recommended experiment names encode the independent variables:

```text
codex_0.152.0_gpt-5.4-mini_xhigh
claude_2.1.227_sonnet_30turns
claudex_2.1.227_gpt-5.6-luna_30turns
```

## Prepare and Validate Data

The default local data root is:

```text
data/longmemeval-v2
```

Prepare a new machine with:

```bash
python data/download_data.py --data-root data/longmemeval-v2
python data/prepare_data.py --data-root data/longmemeval-v2 --mode symlink
python data/validate_data.py --data-root data/longmemeval-v2 --tier small
```

On Windows without symlink privileges, preparation may copy screenshot
directories instead. Allow enough disk space for the extracted data and copies.

## Configure the Fixed Reader

A valid accuracy comparison requires a real OpenAI-compatible reader. The
reference setup uses Qwen3.5-9B:

```bash
export READER_BASE_URL=http://localhost:8023/v1
export READER_MODEL=Qwen/Qwen3.5-9B
```

Verify the endpoint before launching an expensive memory run. A mock reader is
acceptable only for a plumbing smoke test. Mark mock-reader results invalid for
quality, leaderboard, or model-comparison claims.

The harness also loads the `Qwen/Qwen3.5-9B` processor to count memory-context
tokens. Cache its processor/tokenizer files before offline runs.

## Run Codex

```bash
export CODEX_BINARY=/absolute/path/to/codex
export CODEX_MODEL=gpt-5.4-mini
export CODEX_REASONING_EFFORT=xhigh
export DATA_ROOT=/absolute/path/to/data/longmemeval-v2
export OUTPUT_ROOT=runs/codex_0.152.0_gpt-5.4-mini_xhigh
export TIER=small

evaluation/scripts/run_codex.sh
```

For a single-question test, use the unified entry point:

```bash
python evaluation/run_eval.py \
  --method codex \
  --data-root "$DATA_ROOT" \
  --domain web \
  --tier small \
  --question-ids 00aa905a \
  --output-dir runs/smoke_codex \
  --codex-binary "$CODEX_BINARY" \
  --codex-model "$CODEX_MODEL" \
  --codex-reasoning-effort "$CODEX_REASONING_EFFORT" \
  --codex-max-retries 1
```

## Run Claude Code

```bash
export CLAUDE_BINARY=/absolute/path/to/claude
export CLAUDE_MODEL=sonnet
export CLAUDE_VERSION_LABEL=2.1.227
export CLAUDE_MAX_TURNS=30
export CLAUDE_NO_SESSION_PERSISTENCE=true
export DATA_ROOT=/absolute/path/to/data/longmemeval-v2
export OUTPUT_ROOT=runs/claude_2.1.227_sonnet
export TIER=small

evaluation/scripts/run_claude_code.sh
```

Use `CLAUDE_BARE=true` only when every compared version supports `--bare`.
Otherwise isolate settings with version-compatible flags or a clean user
environment. Use `CLAUDE_EFFORT` only when every compared version supports
`--effort`.

Single-question example:

```bash
python evaluation/run_eval.py \
  --method claude_code \
  --data-root "$DATA_ROOT" \
  --domain web \
  --tier small \
  --question-ids 00aa905a \
  --output-dir runs/smoke_claude \
  --claude-binary "$CLAUDE_BINARY" \
  --claude-model "$CLAUDE_MODEL" \
  --claude-version-label "$CLAUDE_VERSION_LABEL" \
  --claude-max-turns 30 \
  --claude-max-retries 1 \
  --claude-no-session-persistence
```

## Reproduce a Gateway-Backed `claudex` Configuration

First inspect the wrapper rather than guessing its behavior:

```powershell
Get-Command claudex | Format-List Definition
```

Reproduce these fields in the process that launches `run_eval.py`:

- `ANTHROPIC_BASE_URL` and the gateway authentication variables;
- exact model identifier;
- actual Claude executable path;
- explicit settings JSON passed through `claude_params.extra_args`;
- subagent model and any behavior-affecting Claude environment variables.

Do not store gateway tokens in `evaluation/memory_configs/*.json`. Prefer a
small executable launcher that sets the environment and forwards arguments, or
launch the evaluator from a shell where the variables are already set.

For example, a local wrapper may be equivalent to:

```powershell
$env:ANTHROPIC_BASE_URL = 'http://127.0.0.1:8317'
$env:ANTHROPIC_AUTH_TOKEN = '<from secure local configuration>'
$env:CLAUDE_CODE_SUBAGENT_MODEL = 'gateway-model-id'

python evaluation/run_eval.py `
  --method claude_code `
  --data-root $env:DATA_ROOT `
  --domain web `
  --tier small `
  --question-ids 00aa905a `
  --output-dir runs/smoke_claudex `
  --claude-binary 'C:\path\to\claude.cmd' `
  --claude-model 'gateway-model-id' `
  --claude-version-label 'claudex-provider-model'
```

If explicit Claude settings are required, add them to the JSON memory config:

```json
{
  "extra_args": [
    "--settings",
    "C:\\path\\to\\claudex-settings.json"
  ]
}
```

## Pilot Before a Full Tier

Start with a paired pilot of 20-50 questions. Stratify the sample across static,
dynamic, procedure, gotchas, and abstention categories. Use the exact same
question IDs for every agent.

Run both `web` and `enterprise` for a complete benchmark operating point. Move
to all 451 small-tier questions only after confirming:

- successful output rate is acceptable;
- no settings or persistent-memory contamination exists;
- per-question cost and latency fit the budget;
- reader and evaluator services are stable;
- trace `summary.json` files contain usage metrics.

Avoid aggressive concurrency until provider limits and workstation I/O are
understood. Report prompt-build concurrency because it affects wall-clock time
and can affect online-learning methods.

## Run Artifacts

Each completed run should contain:

```text
run_args.json
memory_config.json or runtime memory configuration
per_question.jsonl
aggregated_metrics.json
query_traces/<query_invocation_id>/attempt_*/summary.json
query_traces/<query_invocation_id>/attempt_*/events.json
query_traces/<query_invocation_id>/attempt_*/memory_module_output.json
```

Important fields include:

- `per_question.jsonl`: `question_id`, category, score, unknown status, memory
  query duration, memory-context tokens, response, and selected evidence.
- `aggregated_metrics.json`: overall/category accuracy, average/P50/P95/max
  memory latency, reader usage, and truncation counts.
- agent `summary.json`: return code, timeout, duration, command, selected spans,
  and agent usage.
- Claude usage: input, cache creation, cache read, output, total tokens, turns,
  cost, durations, and per-model details.
- Codex usage: input, cached input, output, and reasoning-output tokens.

Token schemas differ by provider. Preserve raw fields and compare semantically
equivalent categories; do not label cache-read tokens as fresh input. Always
report cost separately because token prices and cache discounts differ.

## Decide Which Agent Is Better

Use paired results, not independent averages. For every question classify:

```text
both correct
Codex only correct
Claude only correct
both wrong
```

Primary metrics:

1. final-answer accuracy with the fixed reader;
2. timeout, invalid-output, and empty-memory rates;
3. median and P95 memory-query latency;
4. cost per question and cost per correct answer;
5. memory-context tokens and truncation rate;
6. LAFS for the benchmark accuracy/latency tradeoff.

Use McNemar's test for paired binary accuracy. Use paired bootstrap confidence
intervals for accuracy differences, latency ratios, and cost differences.
Report the sample size and confidence interval; a one-question win is not
evidence of a generally better agent.

For retrieval-quality diagnosis, manually review a stratified subset and score:

- `2`: direct, sufficient, non-misleading evidence;
- `1`: relevant but incomplete evidence;
- `0`: irrelevant, unsupported, or misleading evidence.

Also track valid-span rate, selected-state count, redundant evidence, and cases
where retrieval was correct but the reader still answered incorrectly.

## Build a Comparison Dataset

Create one row per `(agent, domain, question_id)` by joining:

- the run's `per_question.jsonl`;
- its `query_traces/**/summary.json`;
- experiment metadata such as agent label, CLI version, model, provider, tier,
  evidence mode, timeout, turns, and reader model.

Recommended normalized columns:

```text
agent_label, cli_version, agent_model, provider, reader_model
domain, tier, question_id, category, is_abstention
score, is_unknown, query_seconds, post_query_seconds
memory_context_tokens, memory_truncated, valid_span_count, selected_state_count
input_tokens, cache_read_tokens, cache_creation_tokens, output_tokens
reasoning_tokens, turns, cost_usd, timed_out, returncode
```

Keep a separate experiment manifest with the Git commit, dataset revision,
command line, environment-variable names (not secret values), machine details,
and run timestamps.

## Visualization Plan

The final report should contain at least these views:

1. **Accuracy with uncertainty**: overall and per-category grouped bars with
   paired-bootstrap 95% confidence intervals.
2. **Paired win/loss matrix**: both correct, agent-A only, agent-B only, both
   wrong; annotate the McNemar p-value.
3. **Latency distribution**: paired dot plot or ECDF plus median and P95. A log
   axis is useful for long tails.
4. **Cost and token composition**: input/cache/output stacked bars, cost per
   question, and cost per correct answer.
5. **Accuracy-latency frontier**: scatter plot with accuracy on the y-axis,
   memory latency on the x-axis, point size or color for cost, and LAFS labels.
6. **Failure diagnostics**: timeout/invalid/empty/truncated rates and retrieval
   quality by memory category.

Do not use the reader's mock token counts in a performance report. Distinguish
agent tokens from reader tokens and judge tokens.

Suggested report structure:

```text
1. Executive summary and recommendation
2. Experimental controls and versions
3. Dataset coverage and completion rates
4. Accuracy and paired significance
5. Retrieval-quality analysis
6. Latency, tokens, and cost
7. Accuracy-latency-cost tradeoffs and LAFS
8. Failure case studies
9. Limitations and reproducibility appendix
```

Every chart should link back to the normalized comparison table and source run
directories. Include representative `memory_module_output.json` evidence for
both wins and failures, with secrets and user-specific paths redacted.

### Recommended report-generation interface

A follow-up implementation should expose one deterministic command rather than
an interactive notebook, for example:

```bash
python analysis/build_agent_report.py \
  --run codex=runs/codex_web_small \
  --run codex=runs/codex_enterprise_small \
  --run claude=runs/claude_web_small \
  --run claude=runs/claude_enterprise_small \
  --output-dir reports/codex_vs_claude_small
```

The script should read run artifacts without modifying them and produce:

```text
reports/codex_vs_claude_small/
  experiment_manifest.json
  comparison.csv
  question_outcomes.csv
  summary_metrics.json
  statistical_tests.json
  figures/
    accuracy_by_category.png
    paired_outcomes.png
    latency_ecdf.png
    token_composition.png
    cost_tradeoff.png
    accuracy_latency_frontier.png
    failure_rates.png
  report.md
```

Use pandas or Polars for joins, scipy/statsmodels for paired tests, and
Matplotlib/Seaborn or Plotly for charts. Pin analysis dependencies and random
seeds. Save the tabular inputs used for every figure so another agent can
regenerate the report without rerunning the expensive memory agents.

The report builder should fail loudly when paired question sets, reader models,
tiers, or domains differ. It should label incomplete runs and mock readers rather
than silently combining them. Generate both machine-readable JSON/CSV and a
human-readable Markdown or HTML report.

## Leaderboard-Compatible Reporting

For official operating points, combine matching web and enterprise runs and
follow `leaderboard/README.md`. The leaderboard requires the reference reader
and evaluator configuration and computes LAFS from accuracy and average memory
query latency. Mock-reader smoke runs and ad hoc gateway experiments are not
leaderboard-compatible unless they satisfy all validation requirements.

## Minimal Handoff Checklist

Before another agent continues the experiment, provide:

- this document and the exact Git commit;
- data root and validation result;
- agent labels, resolved binaries, detected versions, models, and providers;
- fixed reader/evaluator endpoints and model identifiers;
- exact paired question-ID list;
- output directories and completion status;
- token/cost budget and concurrency limits;
- known mock components or deviations from benchmark settings;
- the normalized comparison table and report output location.
