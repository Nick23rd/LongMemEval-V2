#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DATA_ROOT_VALUE="${DATA_ROOT:?Set DATA_ROOT to the LongMemEval-V2 dataset directory}"
DOMAIN_VALUE="${DOMAIN:-web}"
TIER_VALUE="${TIER:-small}"
PHASE_VALUE="${PHASE:-build}"
OUTPUT_DIR_VALUE="${OUTPUT_DIR:-runs/free_code_auto_memory_${PHASE_VALUE}}"

COMMON_ARGS=(
  --data-root "$DATA_ROOT_VALUE"
  --domain "$DOMAIN_VALUE"
  --tier "$TIER_VALUE"
  --method free_code_auto_memory
  --output-dir "$OUTPUT_DIR_VALUE"
)

case "$PHASE_VALUE" in
  build)
    python "$REPO_ROOT/evaluation/run_eval.py" "${COMMON_ARGS[@]}" --save-memory --skip-evaluation "$@"
    ;;
  evaluate)
    MEMORY_STATE_VALUE="${MEMORY_STATE:?Set MEMORY_STATE to the phase-A memory_state directory}"
    python "$REPO_ROOT/evaluation/run_eval.py" "${COMMON_ARGS[@]}" --load-memory-dir "$MEMORY_STATE_VALUE" "$@"
    ;;
  *)
    echo "PHASE must be build or evaluate" >&2
    exit 2
    ;;
esac
