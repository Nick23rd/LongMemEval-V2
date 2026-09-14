# LongMemEval-V2


<p align="center">
  <a href="https://xiaowu0162.github.io/longmemeval-v2/"><img src="https://img.shields.io/badge/🌐-Website-2a75d0?style=flat-square" height="23"></a>
  <a href="https://arxiv.org/pdf/2605.12493.pdf"><img src="https://img.shields.io/badge/📝-Paper-d03c36?style=flat-square" height="23"></a>
  <a href="https://huggingface.co/datasets/xiaowu0162/longmemeval-v2" ><img src="https://img.shields.io/badge/🤗-Data-167f5f?style=flat-square" height="23"></a>
  <a href="https://xiaowu0162.github.io/longmemeval-v2/#leaderboard" ><img src="https://img.shields.io/badge/🏆-Leaderboard-d89216?style=flat-square" height="23"></a>
</p>

**LongMemEval-V2: Evaluating Long-Term Agent Memory Toward Experienced Colleagues**

[Di Wu](https://xiaowu0162.github.io/),
[Zixiang Ji](https://www.linkedin.com/in/zixiang-ji-56902624b/),
[Asmi Kawatkar](https://www.linkedin.com/in/asmi-kawatkar),
[Bryan Kwan](https://www.linkedin.com/in/kwan-bryan),
[Jia-Chen Gu](https://jasonforjoy.github.io/index.html),
[Nanyun Peng](https://vnpeng.net/), and
[Kai-Wei Chang](https://kwchang.net/)



This is the official LongMemEval-V2 repository. It contains the public
evaluation harness, data preparation tools, leaderboard packaging utilities,
and the memory baselines reported with the benchmark.

> **Fork development status:** this branch contains an in-progress CodeAgent / free-code native-memory regression harness. Before running calibration or full small, read the [current status, blockers, environment readiness checklist, and next steps](docs/codeagent_memory_project_status.zh-CN.md). The experimental historical-session path is faster but is not yet valid for benchmark conclusions.

## News 
- [2026/08] Update: [AgentRunbook-C V2](https://xiaowu0162.github.io/longmemeval-v2/agentrunbook-c-v2/).

## Overview

LongMemEval-V2 evaluates whether memory systems can help agents acquire the
experience needed to become knowledgeable colleagues in customized
environments. The benchmark pairs manually curated questions with long
histories of multimodal web-agent trajectories. A memory system consumes the
trajectory history and returns compact evidence for downstream question
answering; evaluation targets both answer accuracy and query latency.

LongMemEval-V2 contains:

- 451 manually curated questions.
- 5 memory abilities.
- Up to 500 trajectories per haystack.
- Up to 115M tokens in the largest haystacks.
- Two domains: web and enterprise.
- Two public leaderboard tiers: small and medium.

The benchmark tests five core memory abilities:

- **Static state recall**: remembers important landmarks, page layouts, module
  affordances, and subtle state differences.
- **Dynamic state tracking**: understands how states and actions change the
  environment over time.
- **Workflow knowledge**: knows the steps needed to complete recurring tasks in
  customized environments.
- **Environment gotchas**: recognizes recurring local failure modes and avoids
  environment-specific traps.
- **Premise awareness**: detects assumptions that are valid elsewhere but wrong
  in the current deployment.

## Repository Layout

```text
data/                 download, preparation, and validation scripts
evaluation/           evaluation runner, scoring code, configs, and shell wrappers
leaderboard/          metric merging, LAFS scoring, and submission packaging
memory_modules/       memory backend implementations
```

The repository implements the following memory modules:

- `no_retrieval`: no memory context.
- `rag_query_to_slice`: RAG query to raw state slices.
- `rag_query_to_slice_notes`: RAG query to raw state slices plus trajectory
  notes.
- `agentrunbook_r`: AgentRunbook-R.
- `codex`: vanilla Codex coding-agent memory baseline.
- `claude_code`: Claude Code coding-agent memory baseline.
- `codeagent`: CodeAgent coding-agent memory baseline.
- `codeagent_auto_memory`: CodeAgent native auto-memory formation and isolated recall baseline.
- `agentrunbook_c`: AgentRunbook-C.

### CodeAgent internal-memory evaluation

The default launcher evaluates one specified CLI at a time. Each run is retained
under a UTC timestamp plus the CLI commit hash, so results from different commits
can be compared later without rebuilding them as a coupled three-arm job:

```powershell
node evaluation/scripts/run_codeagent_memory_eval.mjs --preset smoke `
  --data-root data/longmemeval-v2 --output-root runs/codeagent_memory `
  --launcher '["bun","D:/aispace/free-code/src/entrypoints/cli.tsx"]' `
  --cli-repo D:/aispace/free-code
```

For a packed CLI outside its Git checkout, pass `--commit-hash`. The runner
auto-detects the repository for source launchers, records whether it is dirty,
and writes `build/`, `evaluate/`, and `runner_config.json` inside the retained
run directory. Resume an interrupted run with the original arguments plus
`--resume --run-dir <retained-run-directory>`.

For a complete small-tier evaluation of one commit, run the command twice with
separate output archives: once with `--domain web` and once with
`--domain enterprise`. Each domain builds one shared frozen memory from its 100
trajectories and then answers all questions in that domain (240 Web and 211
Enterprise). Do not share memory states between domains.

The current validated trajectory-file ingestion path is correct but expensive:
one 100-trajectory build took about 3.54 hours. The experimental historical-session
converter completed 100 trajectories in about 20--26 minutes, but it wrapped the
history as one user message and failed the subsequent recall check. It is not used
by the default `single` command and must not be used for benchmark conclusions until
a true internal multi-turn `Message[]` importer passes the fixed recall calibration.

The runner no longer starts coupled multi-arm jobs. Run the before-change and
after-change packages independently with the same selection and configuration.
Use `--memory-off` only when one package needs a no-memory control run:

```bash
node evaluation/scripts/run_codeagent_memory_eval.mjs --preset smoke --data-root data/longmemeval-v2 --output-root runs/codeagent_memory --launcher '["/builds/before/codeagentcli"]' --commit-hash 0123456789abcdef --memory-off
```

Each completed run writes `evaluation_result.json`: one valid JSON document
containing run identity, selection, aggregate metrics, build metadata, and all
per-question records. An HTML report can load this file directly without
parsing JSONL.

The same directory also contains `report.html`. Open any one copy and select or
drop multiple `evaluation_result.json` files to compare independent runs on one
page, including overall/category accuracy, UNKNOWN rate, latency, token usage,
and per-question improvements or regressions.

See the [evaluation-environment runbook](docs/codeagent_memory_evaluation_environment_runbook.zh-CN.md)
for Node/Bun execution, source launchers, prompt-only experiments, recovery with `--resume`, report
interpretation, and the calibration acceptance criteria.

The runner supports the `free-code` Claude-compatible source tree. Select
its environment-variable dialect and pass its Bun entrypoint as the launcher:

```powershell
node evaluation/scripts/run_codeagent_memory_eval.mjs --preset smoke `
  --data-root data/longmemeval-v2 --output-root runs/free_code_smoke `
  --runtime free_code `
  --launcher '["bun","D:/aispace/free-code/src/entrypoints/cli.tsx"]' `
  --cli-repo D:/aispace/free-code
```

The `free_code` runtime keeps the caller's existing authentication and user
configuration, redirects native memory to the isolated evaluation snapshot,
adds a benchmark-specific native-memory policy for ephemeral trajectory facts,
and disables unrelated prompt-suggestion model calls. Do not use `--bare`,
because `free-code` implements it by disabling auto-memory.

## Setup: Environment

LongMemEval-V2 uses Python 3.11. The default conda environment installs
PyTorch through `requirements-torch.txt`. For CUDA 12.4 machines, the torch
install command is:

```bash
pip install torch==2.6.0+cu124 torchvision==0.21.0+cu124 \
  --extra-index-url https://download.pytorch.org/whl/cu124
```

Create the environment and install the package:

```bash
PYTHONNOUSERSITE=1 conda env create -f environment.yml
conda activate lme-v2-release
pip install -e .
```

Researchers using a different CUDA or CPU setup should install the appropriate
PyTorch build first, either with a direct `pip install` command or by editing
`requirements-torch.txt` before creating the environment.

The environment does not include vLLM. Start or forward your own
OpenAI-compatible model servers, then point the scripts to them. The paper runs
use Qwen3.5-9B as the fixed reader and Qwen3-Embedding-8B for embedding-based
methods. For `codex` and `agentrunbook_c`, download Codex v0.117.0 separately
and set `CODEX_BINARY`.

## Setup: Data

Download and prepare:

```bash
python data/download_data.py --data-root data/longmemeval-v2
export DATA_ROOT="$(pwd)/data/longmemeval-v2"
python data/prepare_data.py --data-root "$DATA_ROOT" --mode symlink
python data/validate_data.py --data-root "$DATA_ROOT" --tier small
```

The default dataset repository is
`xiaowu0162/longmemeval-v2`. Screenshot bundles are stored as `.tar.gz`
archives under `trajectory_screenshots/`; `prepare_data.py` extracts them when
needed and links the resulting directories into:

```text
screenshots/<trajectory_id>/<step>.png
```

## Setup: Model Endpoints and Software

Example endpoint settings:

```bash
# for all experiments
export READER_BASE_URL=http://localhost:8023/v1
export READER_MODEL=Qwen/Qwen3.5-9B

# additionally for RAG and AgentRunbook-R
export LME_CONTROLLER_BASE_URL=http://localhost:8023/v1
export LME_CONTROLLER_MODEL=Qwen/Qwen3.5-9B
export LME_EMBEDDING_BASE_URL=http://localhost:8114/v1
export LME_EMBEDDING_MODEL=Qwen/Qwen3-Embedding-8B
```

Set for LLM judge (default `gpt-5.2` with `medium` reasoning):

```bash
export OPENAI_API_KEY=...
```

For Codex and AgentRunbook-C:

```bash
export CODEX_BINARY=/path/to/codex-binary
export CODEX_MODEL=gpt-5.4-mini
export CODEX_REASONING_EFFORT=xhigh
```

For Claude Code:

```bash
export CLAUDE_BINARY=/path/to/versioned/claude
export CLAUDE_MODEL=sonnet
export CLAUDE_VERSION_LABEL=2.1.0
```

For CodeAgent, only the executable path is normally needed; its built-in model
is used unless `CODEAGENT_MODEL` is explicitly set. A local Windows build from
the CodeAgent repository can be selected directly:

```bash
export CODEAGENT_BINARY=/path/to/codeagentcli
# Optional future overrides:
# export CODEAGENT_MODEL=...
# export CODEAGENT_VERSION_LABEL=...
```

```powershell
$env:CODEAGENT_BINARY = 'D:\workspace\CodeAgent\packages\codeagent\codeagentcli.exe'
```

The auto-memory experiment uses a separate configuration namespace and a
two-stage build/evaluate workflow:

See [the Chinese manual testing guide](docs/codeagent_auto_memory_manual_test.zh-CN.md)
for preflight checks, smoke tests, artifact inspection, and troubleshooting.

```powershell
$env:CODEAGENT_AUTO_MEMORY_BINARY = 'D:\workspace\CodeAgent\packages\codeagent\codeagentcli.exe'
$env:DATA_ROOT = 'D:\path\to\longmemeval-v2'
$env:PHASE = 'build'
bash evaluation/scripts/run_codeagent_auto_memory.sh

$env:PHASE = 'evaluate'
$env:MEMORY_STATE = 'runs/codeagent_auto_memory_build/memory_state'
bash evaluation/scripts/run_codeagent_auto_memory.sh
```

Use a separate versioned binary and output root for each comparison. Set
`CLAUDE_BARE=true` when every tested Claude Code version supports `--bare` to
disable CLAUDE.md, plugins, MCP servers, skills, hooks, and auto memory. Session
persistence is disabled by default. The detected `claude --version` output is
saved in the memory configuration for experiment provenance.
Set `CLAUDE_EFFORT=high` only when all compared versions support the
`--effort` flag; leaving it unset improves compatibility with older releases.

For third-party model configuration, executable-path maintenance, and the
workflow for adding another coding-agent tool such as OpenCode, see
[Coding-Agent CLI Configuration and Integration](docs/coding-agent-tools.md).

Codex also expects common command-line tools such as `rg` and `find`.

## Reproducing Baselines

Each shell script accepts extra argparse flags after the environment variables:

```bash
export DATA_ROOT=/path/to/longmemeval-v2
export OUTPUT_ROOT=runs
export TIER=small

evaluation/scripts/run_no_retrieval.sh
evaluation/scripts/run_rag_query_to_slice.sh
evaluation/scripts/run_rag_query_to_slice_notes.sh
evaluation/scripts/run_agentrunbook_r.sh
evaluation/scripts/run_codex.sh
evaluation/scripts/run_claude_code.sh
evaluation/scripts/run_codeagent.sh
evaluation/scripts/run_codeagent_auto_memory.sh
evaluation/scripts/run_agentrunbook_c.sh
```

Most baseline scripts run both domains for the selected tier. The
`run_codeagent_auto_memory.sh` wrapper runs the single domain selected by `DOMAIN`
because its build and evaluation phases use a domain-specific saved memory state.
Set `TIER=medium` to run LME-V2-Medium.

Each run writes `aggregated_metrics.json`. To combine matching enterprise and web runs for the same method and tier:

```bash
python leaderboard/combine_aggregated_metrics.py \
  runs/agentrunbook_r_enterprise_small/aggregated_metrics.json \
  runs/agentrunbook_r_web_small/aggregated_metrics.json \
  -o runs/agentrunbook_r_small_combined_metrics.json
```

## Implementing Your Method

Memory backends inherit from `memory_modules.memory.Memory`. For a minimal
example, see `memory_modules/no_retrieval.py`; for indexed retrieval examples,
see `memory_modules/rag.py` and `memory_modules/agentrunbook_r.py`.

A backend should:

- decorate the class with `@register_memory`;
- set a unique `memory_type`;
- implement `insert(self, trajectory)`, which receives each full trajectory
  object selected for the current haystack;
- implement `query(self, query, query_image=None)`, which receives the question
  text and optional question screenshot path.

`query` must return a list of memory context items:

```python
[
    {"type": "text", "value": "retrieved notes or evidence"},
    {"type": "image", "value": "/absolute/or/relative/path/to/image.png"},
]
```

Text values must be non-empty strings. Image values must point to existing
files. The harness appends these items to the reader prompt and enforces
`--memory-context-max-tokens` before calling the answer model.

Backends receive no benchmark metadata during `query`: retrieval is based only
on the question text and optional question image. `self.get_query_context()`
contains only a random, run-local `query_invocation_id` for trace and lifecycle
bookkeeping. The evaluator keeps the dataset question ID, question type, raw
question record, gold answer, and evaluator configuration private. Optional
hooks include `post_query_hook(...)` for per-query metadata and
`_save_backend(...)` / `_load_backend(...)` for persisted memory state.

To run a new backend directly, create a memory config JSON:

```json
{
  "memory_type": "your_memory_type",
  "memory_params": {}
}
```

Then pass it to `evaluation/harness.py` with `--memory-config-path`. To expose
the method through `evaluation/run_eval.py` and the shell wrappers, add the
method name and config construction there as well.

## Submitting to Leaderboard

Leaderboard entries measure how much a memory system improves the released
baseline + AgentRunbook accuracy-latency frontier. The score is LAFS gain over
the fixed reference frontier, and a submission may include multiple latency
operating points for the same method and tier.

See [leaderboard/README.md](leaderboard/README.md) for the full packaging
instructions.

Submit leaderboard packages through the
[submission form](https://forms.gle/rxUpiuRKDERqpqSi9). Please do not submit
leaderboard entries as GitHub issues. Informal submission issues will be closed
or deleted.

## Citation


```bibtex
@article{wu2026longmemevalv2,
      title={LongMemEval-V2: Evaluating Long-Term Agent Memory Toward Experienced Colleagues}, 
      author={Di Wu and Zixiang Ji and Asmi Kawatkar and Bryan Kwan and Jia-Chen Gu and Nanyun Peng and Kai-Wei Chang},
      year={2026},
      eprint={2605.12493},
      archivePrefix={arXiv},
      primaryClass={cs.CL},
      url={https://arxiv.org/abs/2605.12493}, 
}
