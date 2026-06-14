#!/usr/bin/env bash
# Re-run full pipeline when official checkpoint is placed in models/superpc_pretrained/
set -euo pipefail

GC2026_ROOT="/root/autodl-tmp/GC2026"
OUT="${GC2026_ROOT}/output/all_sequences_official"
CKPT="${1:-}"

source "${GC2026_ROOT}/scripts/env_setup.sh"

if [[ -z "$CKPT" ]]; then
  CKPT=$(find "${GC2026_ROOT}/models/superpc_pretrained" -type f \( -name "*.pth" -o -name "*.pt" \) \
    ! -name "*smoke*" ! -name "*init*" 2>/dev/null | head -1)
fi

if [[ -n "$CKPT" ]] && [[ "$CKPT" != /* ]]; then
  CKPT="${GC2026_ROOT}/${CKPT}"
fi

if [[ -z "$CKPT" ]] || [[ ! -f "$CKPT" ]]; then
  echo "[rerun_official] No official checkpoint found. Upload to models/superpc_pretrained/ first."
  exit 1
fi

echo "[rerun_official] Using ckpt=$CKPT out=$OUT"

NUM_POINTS=2048
TARGET_NUM_POINTS=8192
case "$(basename "$CKPT")" in
  *kitti*|*tartan*)
    NUM_POINTS=11520
    TARGET_NUM_POINTS=46080
    ;;
esac

bash "${GC2026_ROOT}/scripts/run_all_sequences.sh" \
  --skip-download \
  --ckpt "$CKPT" \
  --out-dir "$OUT" \
  --num-points "$NUM_POINTS" \
  --target-num-points "$TARGET_NUM_POINTS"

python "${GC2026_ROOT}/scripts/evaluate_uvg.py" \
  --pairs-file "${GC2026_ROOT}/data/processed/all_pairs.txt" \
  --enhanced-root "$OUT" \
  --n-samples 4096 \
  --out-json "${OUT}/evaluation_full_summary.json"

python "${GC2026_ROOT}/scripts/temporal_smooth.py" \
  --in-dir "$OUT" \
  --out-dir "${GC2026_ROOT}/output/all_sequences_official_smoothed" \
  --window 5

bash "${GC2026_ROOT}/scripts/pack_submission.sh" "$OUT"
python "${GC2026_ROOT}/scripts/generate_status_report.py"
echo "[rerun_official] DONE"
