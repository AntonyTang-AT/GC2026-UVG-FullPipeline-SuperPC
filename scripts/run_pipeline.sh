#!/usr/bin/env bash
# End-to-end: download weights -> verify -> BlueSpeech inference -> submission manifest.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env_setup.sh
source "$SCRIPT_DIR/env_setup.sh"

SKIP_DOWNLOAD=0
MAX_FRAMES=0
CKPT_PATH=""
NUM_POINTS=2048
TARGET_NUM_POINTS=8192
SAMPLING_STEPS=25
OUT_DIR="${GC2026_ROOT}/output/BlueSpeech_enhanced"
SEQUENCE="BlueSpeech"
DEVICE="${SUPERPC_DEVICE:-cuda}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-download) SKIP_DOWNLOAD=1; shift ;;
    --max-frames) MAX_FRAMES="$2"; shift 2 ;;
    --ckpt) CKPT_PATH="$2"; shift 2 ;;
    --num-points) NUM_POINTS="$2"; shift 2 ;;
    --target-num-points) TARGET_NUM_POINTS="$2"; shift 2 ;;
    --sampling-steps) SAMPLING_STEPS="$2"; shift 2 ;;
    --out-dir) OUT_DIR="$2"; shift 2 ;;
    --sequence) SEQUENCE="$2"; shift 2 ;;
    --device) DEVICE="$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

PRETRAINED_DIR="${GC2026_ROOT}/models/superpc_pretrained"

if [[ "$SKIP_DOWNLOAD" -eq 0 ]]; then
  bash "$SCRIPT_DIR/download_pretrained.sh"
fi

pick_ckpt() {
  local dir="$1"
  local ckpt
  ckpt=$(find "$dir" -type f \( -iname "*shapenet*" -o -iname "*shape*" \) \( -name "*.pth" -o -name "*.pt" \) 2>/dev/null | head -1)
  if [[ -z "$ckpt" ]]; then
    ckpt=$(find "$dir" -type f \( -iname "*kitti*" \) \( -name "*.pth" -o -name "*.pt" \) 2>/dev/null | head -1)
  fi
  if [[ -z "$ckpt" ]]; then
    ckpt=$(find "$dir" -type f \( -iname "*tartan*" \) \( -name "*.pth" -o -name "*.pt" \) 2>/dev/null | head -1)
  fi
  if [[ -z "$ckpt" ]]; then
    ckpt=$(find "$dir" -type f \( -name "*.pth" -o -name "*.pt" \) 2>/dev/null | head -1)
  fi
  echo "$ckpt"
}

if [[ -z "$CKPT_PATH" ]]; then
  CKPT_PATH=$(pick_ckpt "$PRETRAINED_DIR")
fi

if [[ -z "$CKPT_PATH" ]] || [[ ! -f "$CKPT_PATH" ]]; then
  echo "[run_pipeline] ERROR: No checkpoint found in $PRETRAINED_DIR"
  echo "  Upload a .pth file or run download_pretrained.sh"
  exit 1
fi

echo "[run_pipeline] Using checkpoint: $CKPT_PATH"

python "$SCRIPT_DIR/verify_superpc_ckpt.py" --ckpt-path "$CKPT_PATH"

CG_LIST="/tmp/${SEQUENCE}_cg_list.txt"
grep "/${SEQUENCE}/" "${GC2026_ROOT}/data/processed/all_cg_only.txt" > "$CG_LIST"
FRAME_COUNT=$(wc -l < "$CG_LIST")
echo "[run_pipeline] CG list: $CG_LIST ($FRAME_COUNT frames for $SEQUENCE)"

MAX_ARGS=()
if [[ "$MAX_FRAMES" -gt 0 ]]; then
  MAX_ARGS=(--max-samples "$MAX_FRAMES")
  echo "[run_pipeline] Limiting to $MAX_FRAMES frames"
fi

python "$SCRIPT_DIR/run_superpc_infer.py" \
  --cg-list "$CG_LIST" \
  --ckpt-path "$CKPT_PATH" \
  --out-dir "$OUT_DIR" \
  --num-points "$NUM_POINTS" \
  --target-num-points "$TARGET_NUM_POINTS" \
  --sampling-steps "$SAMPLING_STEPS" \
  --device "$DEVICE" \
  "${MAX_ARGS[@]}"

python "$SCRIPT_DIR/make_submission.py" --enhanced-dir "$OUT_DIR"

echo "[run_pipeline] Verifying first output PLY with Open3D..."
export OUT_DIR
python - <<'PY'
import glob
import os
import open3d as o3d

out_dir = os.environ.get("OUT_DIR", "")
plys = sorted(glob.glob(os.path.join(out_dir, "**", "*.ply"), recursive=True))
if not plys:
    raise SystemExit("No PLY files found in output")
pc = o3d.io.read_point_cloud(plys[0])
n = len(pc.points)
has_color = len(pc.colors) == n and n > 0
print(f"[verify_ply] {plys[0]} points={n} has_colors={has_color}")
PY

echo "[run_pipeline] DONE -> $OUT_DIR"
