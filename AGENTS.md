# Repository guidance

## Scope

This repository is the LongMemEval-V2 evaluation artifact plus an in-progress
CodeAgent/free-code native-memory evaluation path. Treat
`docs/codeagent_memory_project_status.zh-CN.md` as the authoritative status page
when CodeAgent documents disagree.

## Environment and checks

- Use Python 3.11 or newer. Prefer `.venv/Scripts/python.exe` on Windows when it
  exists; otherwise use `python`.
- Install the package with `python -m pip install -e .` and install `pytest` for
  tests.
- Run focused tests for touched code first. The common full local check is
  `python -m pytest tests -q`.
- For Python syntax-only validation, use
  `python -m compileall -q memory_modules evaluation tests`.
- The cross-platform CodeAgent runner is
  `node evaluation/scripts/run_codeagent_memory_eval.mjs`.

## CodeAgent evaluation rules

- Treat evaluated agents as unmodified black boxes. Put product-specific launch,
  authentication references, result parsing, and memory-state handling behind a
  `NativeMemoryAgent` adapter; do not make free-code-only capabilities a protocol
  requirement.
- The default workflow is `single`: evaluate one specified CLI commit per run.
  Do not make the legacy three-arm regression the default again.
- A complete small-tier result requires separate Web and Enterprise runs. Each
  domain builds and freezes its own memory state; never reuse a state across
  domains.
- Preserve run identity and reproducibility metadata: CLI commit, dirty status,
  launcher argv, prompt hashes, trajectory fingerprints, data selection, model,
  token usage, cost, duration, failures, and memory snapshot.
- Keep ingestion and query sessions isolated. Query sessions must not see source
  trajectories and must not mutate the frozen main memory.
- `memory_off` is a small isolation/leakage smoke only. Do not spend a full
  haystack or full-small run on it unless a user explicitly requests that legacy
  experiment.
- Keep `trajectory_file` as the default ingestion strategy for original CLIs and
  closed-source agents. `historical_session` is an optional modified-free-code
  research path, not a general adapter requirement.
- The typed internal `Message[]` historical-session importer is implemented but
  has not passed a real-model gate. Require structured extraction status,
  `mainAgentTurns=0`, and successful gates in this order: fixed 3 trajectories,
  all 100 trajectories with one recall question, then the fixed 10-question
  calibration. Do not treat the older single-user-message PoC or the unvalidated
  typed importer as benchmark-valid, and do not expand either to full small.
- Never present results from `--haystack-limit` as benchmark scores. Such runs
  are structural smoke tests only.
- Real model runs can be expensive. Use `--dry-run`, fake-CLI tests, or a tiny
  smoke before calibration or full-small, and do not start costly runs unless
  the user explicitly requests them.

## Editing conventions

- Preserve unrelated user changes in a dirty worktree.
- Prefer small, focused patches and keep Windows/Linux launcher behavior intact.
- Do not write credentials into configs, logs, tests, or documentation.
- Update the status page and applicable runbook whenever evaluation semantics or
  release gates change.
