#!/usr/bin/env bash
# VictoryHeart testbed: coord-chain fix + optional HE correction.
set -euo pipefail

GC2026_ROOT="${GC2026_ROOT:-/root/autodl-tmp/GC2026}"
QUICK="${QUICK:-20}"
FULL="${FULL:-0}"
HE_CORR="${HE_CORR:-0}"

source "${GC2026_ROOT}/output/cwipc_env.sh" 2>/dev/null || true
export PY_OPEN3D="${PY_OPEN3D:-python3.12}"
export PY_CWIPC="${PY_CWIPC:-python3.12}"

ARGS=(--quick-frames "$QUICK")
[[ "$FULL" == "1" ]] && ARGS=(--full-seq)
[[ "$HE_CORR" == "1" ]] && ARGS+=("--with-he-correction")

echo "[vh_testbed] VictoryHeart coord fix experiments (${QUICK} frames unless FULL=1)"
python3 "${GC2026_ROOT}/scripts/run_vh_coord_fix_experiments.py" "${ARGS[@]}"

echo "[vh_testbed] Results: ${GC2026_ROOT}/output/remediation/vh_coord_fix_experiments.json"
