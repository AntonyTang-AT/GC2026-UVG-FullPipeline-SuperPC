#!/usr/bin/env bash
# Bottleneck diagnosis + method sweep on TicTacToe + VictoryHeart only.
set -euo pipefail

GC2026_ROOT="${GC2026_ROOT:-/root/autodl-tmp/GC2026}"
N_FRAMES="${N_FRAMES:-10}"
QUICK="${QUICK:-15}"

source "${GC2026_ROOT}/output/cwipc_env.sh" 2>/dev/null || true
export PY_OPEN3D="${PY_OPEN3D:-python3.12}"
export PY_CWIPC="${PY_CWIPC:-python3.12}"

echo "[iterate] Step 1/2: per-stage bottleneck diagnosis (${N_FRAMES} frames/seq)"
python3 "${GC2026_ROOT}/scripts/diagnose_bottleneck.py" \
  --max-frames "$N_FRAMES" \
  --out-json "${GC2026_ROOT}/output/remediation/bottleneck_diagnosis.json"

echo ""
echo "[iterate] Step 2/2: method sweep incl. TSDF (${QUICK} frames/seq)"
bash "${GC2026_ROOT}/scripts/run_dev_two_seq_iterate.sh"

echo ""
echo "[iterate] Reports:"
echo "  ${GC2026_ROOT}/output/remediation/bottleneck_diagnosis.json"
echo "  ${GC2026_ROOT}/output/remediation/dev_two_seq_sweep.json"
