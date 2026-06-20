#!/usr/bin/env bash
# Coordinate optimization: HE-calibrated ΔT + hybrid rebuild with corrections.
set -euo pipefail

GC2026_ROOT="${GC2026_ROOT:-/root/autodl-tmp/GC2026}"
CALIB="${CALIB:-10}"
EVAL="${EVAL:-15}"

source "${GC2026_ROOT}/output/cwipc_env.sh" 2>/dev/null || true
export PY_OPEN3D="${PY_OPEN3D:-python3.12}"
export PY_CWIPC="${PY_CWIPC:-python3.12}"

echo "[coord_opt] Step 1: estimate HE ΔT and evaluate on TT+VH"
python3 "${GC2026_ROOT}/scripts/run_coord_optimize.py" \
  --calib-frames "$CALIB" \
  --eval-frames "$EVAL" \
  --method icp

echo ""
echo "[coord_opt] Step 2: rebuild with corrections embedded (15 frames/seq)"
python3 "${GC2026_ROOT}/scripts/run_dev_two_seq_sweep.py" \
  --quick-frames "$EVAL" \
  --gate-soft 350 \
  --gate-ideal 200 \
  --out-json "${GC2026_ROOT}/output/remediation/dev_two_seq_sweep_corrected.json"
