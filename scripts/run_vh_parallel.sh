#!/usr/bin/env bash
# Parallel VH experiments toward TT-like CD (~530mm).
set -euo pipefail

GC2026_ROOT="${GC2026_ROOT:-/root/autodl-tmp/GC2026}"
QUICK="${QUICK:-30}"
JOBS="${JOBS:-4}"
FULL="${FULL:-0}"
RUN_REGISTER="${RUN_REGISTER:-1}"

source "${GC2026_ROOT}/output/cwipc_env.sh" 2>/dev/null || true
export PY_CWIPC="${PY_CWIPC:-python3.12}"

echo "[vh_parallel] Step 1: estimate train-global HE correction"
python3 "${GC2026_ROOT}/scripts/estimate_train_he_correction.py"

REGISTER_PID=""
if [[ "$RUN_REGISTER" == "1" ]]; then
  CAM_DIR="${GC2026_ROOT}/data/raw/UVG-CWI-DQPC/VictoryHeart/consumer-grade_capture_system/camera_output"
  REG_LOG="${GC2026_ROOT}/output/remediation/vh_cwipc_register.log"
  echo "[vh_parallel] Step 2: cwipc_register on VH (background, --count 40)"
  (
    cd "$CAM_DIR"
    cwipc_register --playback . \
      --cameraconfig "${CAM_DIR}/VictoryHeart_camera_config.json" \
      --count 40 --nofloor 2>&1 | tee "$REG_LOG"
  ) &
  REGISTER_PID=$!
fi

echo "[vh_parallel] Step 3: parallel cwipc variants (jobs=${JOBS})"
ARGS=(--quick-frames "$QUICK" --jobs "$JOBS")
[[ "$FULL" == "1" ]] && ARGS=(--full-seq --jobs "$JOBS")
python3 "${GC2026_ROOT}/scripts/run_vh_parallel_experiments.py" "${ARGS[@]}"

if [[ -n "$REGISTER_PID" ]]; then
  echo "[vh_parallel] Waiting for cwipc_register (pid=$REGISTER_PID)..."
  wait "$REGISTER_PID" || echo "[vh_parallel] cwipc_register finished with non-zero exit (check log)"
fi

echo "[vh_parallel] Results: ${GC2026_ROOT}/output/remediation/vh_parallel_experiments.json"
