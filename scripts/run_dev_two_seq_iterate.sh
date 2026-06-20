#!/usr/bin/env bash
# Iterate methods on TicTacToe + VictoryHeart only; gate before full 2155.
set -euo pipefail

GC2026_ROOT="${GC2026_ROOT:-/root/autodl-tmp/GC2026}"
GATE_SOFT="${GATE_SOFT:-350}"
GATE_IDEAL="${GATE_IDEAL:-200}"
QUICK="${QUICK:-15}"

source "${GC2026_ROOT}/output/cwipc_env.sh" 2>/dev/null || true
export PY_OPEN3D="${PY_OPEN3D:-python3.12}"
export PY_CWIPC="${PY_CWIPC:-python3.12}"

echo "[dev_iterate] Phase1: quick sweep (${QUICK} frames/seq)"
python3 "${GC2026_ROOT}/scripts/run_dev_two_seq_sweep.py" \
  --quick-frames "$QUICK" \
  --gate-soft "$GATE_SOFT" \
  --gate-ideal "$GATE_IDEAL"

python3 <<PY
import json, sys
r = json.load(open("${GC2026_ROOT}/output/remediation/dev_two_seq_sweep.json"))
est = r.get("estimated_hybrid_overall_mm")
print(f"[dev_iterate] estimated hybrid overall={est} pass_350={r.get('pass_soft')} pass_200={r.get('pass_ideal')}")
if est and est < ${GATE_SOFT}:
    print("[dev_iterate] Phase2: full TT+VH val362 confirm recommended")
    sys.exit(0)
print("[dev_iterate] NOT ready for full 2155 — continue method search")
sys.exit(0)
PY

echo "[dev_iterate] To confirm winners on full 362 frames:"
echo "  python3 scripts/run_dev_two_seq_sweep.py --full-seq"
echo "[dev_iterate] Do NOT run TRACK=full until pass_350 on full-seq sweep"
