#!/usr/bin/env bash
# Run SuperPC inference for all sequences in processed/all_cg_only.txt
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env_setup.sh
source "$SCRIPT_DIR/env_setup.sh"

CKPT_PATH=""
OUT_DIR="${GC2026_ROOT}/output/all_sequences_enhanced"
NUM_POINTS=2048
TARGET_NUM_POINTS=8192
SAMPLING_STEPS=25
DEVICE="${SUPERPC_DEVICE:-cuda}"
MAX_FRAMES=0
SKIP_DOWNLOAD=0
SKIP_EXISTING=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-download) SKIP_DOWNLOAD=1; shift ;;
    --skip-existing) SKIP_EXISTING=1; shift ;;
    --ckpt) CKPT_PATH="$2"; shift 2 ;;
    --out-dir) OUT_DIR="$2"; shift 2 ;;
    --max-frames) MAX_FRAMES="$2"; shift 2 ;;
    --num-points) NUM_POINTS="$2"; shift 2 ;;
    --target-num-points) TARGET_NUM_POINTS="$2"; shift 2 ;;
    --sampling-steps) SAMPLING_STEPS="$2"; shift 2 ;;
    --device) DEVICE="$2"; shift 2 ;;
    *) echo "Unknown: $1"; exit 1 ;;
  esac
done

if [[ "$SKIP_DOWNLOAD" -eq 0 ]]; then
  bash "$SCRIPT_DIR/download_pretrained.sh" || true
fi

pick_ckpt() {
  local dir="$1" ckpt f
  for f in $(find "$dir" -type f \( -name "*.pth" -o -name "*.pt" \) ! -iname "*smoke*" ! -iname "*backup*" ! -iname "*init*" 2>/dev/null | sort); do
    if python -c "import torch; torch.load('$f', map_location='cpu')" 2>/dev/null; then
      echo "$f"
      return 0
    fi
    echo "[run_all] Skipping unreadable checkpoint: $f" >&2
  done
  ckpt=$(find "$dir" -type f -name "*smoke*.pth" 2>/dev/null | head -1)
  echo "$ckpt"
}

PRETRAINED_DIR="${GC2026_ROOT}/models/superpc_pretrained"
if [[ -z "$CKPT_PATH" ]]; then CKPT_PATH=$(pick_ckpt "$PRETRAINED_DIR"); fi
if [[ -z "$CKPT_PATH" ]] || [[ ! -f "$CKPT_PATH" ]]; then
  echo "[run_all] No checkpoint found"; exit 1
fi

echo "[run_all] ckpt=$CKPT_PATH out=$OUT_DIR"

python "$SCRIPT_DIR/verify_superpc_ckpt.py" --ckpt-path "$CKPT_PATH"

CG_LIST="${GC2026_ROOT}/data/processed/all_cg_only.txt"
MAX_ARGS=()
if [[ "$MAX_FRAMES" -gt 0 ]]; then MAX_ARGS=(--max-samples "$MAX_FRAMES"); fi
SKIP_ARGS=()
if [[ "$SKIP_EXISTING" -eq 1 ]]; then SKIP_ARGS=(--skip-existing); fi

python "$SCRIPT_DIR/run_superpc_infer.py" \
  --cg-list "$CG_LIST" \
  --ckpt-path "$CKPT_PATH" \
  --out-dir "$OUT_DIR" \
  --num-points "$NUM_POINTS" \
  --target-num-points "$TARGET_NUM_POINTS" \
  --sampling-steps "$SAMPLING_STEPS" \
  --device "$DEVICE" \
  "${MAX_ARGS[@]}" \
  "${SKIP_ARGS[@]}"

python "$SCRIPT_DIR/make_submission.py" --enhanced-dir "$OUT_DIR"
python "$SCRIPT_DIR/evaluate_uvg.py" \
  --pairs-file "${GC2026_ROOT}/data/processed/val_pairs.txt" \
  --enhanced-root "$OUT_DIR" \
  --n-samples 4096 \
  --out-json "${OUT_DIR}/evaluation_val_summary.json"

echo "[run_all] DONE $OUT_DIR"
