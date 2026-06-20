#!/usr/bin/env bash
# cwipc VH optimization: fine-register + parallel sweep.
set -euo pipefail
GC2026_ROOT="${GC2026_ROOT:-/root/autodl-tmp/GC2026}"
QUICK="${QUICK:-30}"
JOBS="${JOBS:-4}"
SKIP_REG="${SKIP_REG:-0}"

source "${GC2026_ROOT}/output/cwipc_env.sh" 2>/dev/null || true
export PY_CWIPC="${PY_CWIPC:-python3.12}"

ARGS=(--quick-frames "$QUICK" --jobs "$JOBS")
[[ "$SKIP_REG" == "1" ]] && ARGS+=(--skip-register)

python3 "${GC2026_ROOT}/scripts/run_cwipc_vh_optimization.py" "${ARGS[@]}"
