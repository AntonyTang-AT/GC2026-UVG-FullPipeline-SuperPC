#!/usr/bin/env bash
# Run SuperPC inference on pending frames using two GPUs in parallel.
set -euo pipefail

GC2026_ROOT="/root/autodl-tmp/GC2026"
SCRIPT_DIR="${GC2026_ROOT}/scripts"
source "${SCRIPT_DIR}/env_setup.sh"

CKPT="${CKPT:-${1:-${GC2026_ROOT}/models/superpc_pretrained/kitti360_com.pth}}"
OUT_DIR="${OUT_DIR:-${2:-${GC2026_ROOT}/output/all_sequences_official}}"
NUM_POINTS="${NUM_POINTS:-11520}"
TARGET_NUM_POINTS="${TARGET_NUM_POINTS:-46080}"
SAMPLING_STEPS="${SAMPLING_STEPS:-25}"
OUTPUT_MODE="${OUTPUT_MODE:-model}"
BLEND_VOXEL_MM="${BLEND_VOXEL_MM:-2.0}"
USE_VISION="${USE_VISION:-0}"
RGBD_PAIRS_FILE="${RGBD_PAIRS_FILE:-${GC2026_ROOT}/data/processed/rgbd_pairs.txt}"
CG_LIST="${CG_LIST:-${GC2026_ROOT}/data/processed/all_cg_only.txt}"

SHARD_DIR="${OUT_DIR}/.dual_gpu_shards"
LOG_DIR="${OUT_DIR}/.dual_gpu_logs"

mkdir -p "$SHARD_DIR" "$LOG_DIR"

python "${SCRIPT_DIR}/split_pending_cg_list.py" \
  --cg-list "$CG_LIST" \
  --out-dir "$OUT_DIR" \
  --shard-dir "$SHARD_DIR" \
  --num-shards 2

pkill -f "run_superpc_infer.py.*--out-dir ${OUT_DIR}" 2>/dev/null || true
sleep 2

VISION_ARGS=()
if [[ "$USE_VISION" == "1" ]]; then
  VISION_ARGS=(--use-vision-conditioning)
  if [[ -f "$RGBD_PAIRS_FILE" ]]; then
    VISION_ARGS+=(--rgbd-pairs-file "$RGBD_PAIRS_FILE")
  fi
fi

run_worker() {
  local gpu="$1"
  local list="${SHARD_DIR}/pending_${gpu}.txt"
  local n
  n=$(wc -l < "$list" | tr -d ' ')
  if [[ "$n" -eq 0 ]]; then
    echo "[dual_gpu] GPU${gpu}: nothing pending, skip"
    return 0
  fi
  echo "[dual_gpu] GPU${gpu}: ${n} frames mode=${OUTPUT_MODE} vision=${USE_VISION}"
  CUDA_VISIBLE_DEVICES="$gpu" nohup python "${SCRIPT_DIR}/run_superpc_infer.py" \
    --cg-list "$list" \
    --ckpt-path "$CKPT" \
    --out-dir "$OUT_DIR" \
    --num-points "$NUM_POINTS" \
    --target-num-points "$TARGET_NUM_POINTS" \
    --sampling-steps "$SAMPLING_STEPS" \
    --output-mode "$OUTPUT_MODE" \
    --blend-voxel-mm "$BLEND_VOXEL_MM" \
    --skip-existing \
    --device cuda:0 \
    "${VISION_ARGS[@]}" \
    > "${LOG_DIR}/gpu${gpu}.log" 2>&1 &
  echo "[dual_gpu] GPU${gpu} PID=$!"
}

run_worker 0
run_worker 1

echo "[dual_gpu] Workers started. Monitor: tail -f ${LOG_DIR}/gpu0.log ${LOG_DIR}/gpu1.log"
