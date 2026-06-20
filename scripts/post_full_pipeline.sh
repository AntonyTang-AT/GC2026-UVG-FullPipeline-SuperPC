#!/usr/bin/env bash
# Post-process Full Pipeline candidate: manifest, eval (n=20k), color/temporal, pack.
# Uses CPU Chamfer by default so eval can run while GPUs are busy with SuperPC.
set -euo pipefail

GC2026_ROOT="/root/autodl-tmp/GC2026"
OUT="${OUT_DIR:-${GC2026_ROOT}/output/full_pipeline_candidate}"
GATE_JSON="${GC2026_ROOT}/output/val_grid/gate_decision.json"
LOG="${GC2026_ROOT}/output/post_full_pipeline.log"
N_SAMPLES=20000
UVG_CG_VERSION="${UVG_CG_VERSION:-v2}"
EVAL_DEVICE="${EVAL_DEVICE:-cpu}"

exec > >(tee -a "$LOG") 2>&1
echo "[post_full] START $(date -Is) OUT=$OUT device=$EVAL_DEVICE"

post_progress() {
  echo "[post_full] PROGRESS step=$1 $(date +%H:%M:%S)"
}

source "${GC2026_ROOT}/scripts/env_setup.sh"

if [[ -f "$GATE_JSON" ]]; then
  python3 -c "import json; d=json.load(open('$GATE_JSON')); print('gate', d.get('gate_passed'), d.get('best_experiment'))" || true
fi

n=$(find "$OUT" -name '*.ply' 2>/dev/null | wc -l)
echo "[post_full] ply_count=$n"

post_progress "manifest"
python "${GC2026_ROOT}/scripts/make_submission.py" \
  --enhanced-dir "$OUT" \
  --team "GC2026 Team" \
  --processing-track "Full Pipeline" \
  --title "UVG-CWI-DQPC GC2026 Full Pipeline SuperPC" \
  --post-processing "$GATE_JSON" \
  --cg-version "$UVG_CG_VERSION" \
  --cg-source "reconstructed" \
  --pipeline-notes "RGBD/bag -> rgbd_to_cg.py -> SuperPC blend enhancement"

VAL_PAIRS="${GC2026_ROOT}/data/processed/val_pairs_cgv2.txt"
ALL_PAIRS="${GC2026_ROOT}/data/processed/all_pairs_cgv2.txt"
if [[ ! -f "$VAL_PAIRS" ]]; then
  VAL_PAIRS="${GC2026_ROOT}/data/processed/val_pairs.txt"
  ALL_PAIRS="${GC2026_ROOT}/data/processed/all_pairs.txt"
fi

post_progress "evaluate_uvg_val_full"
echo "[post_full] evaluate_uvg val + full (parallel, device=$EVAL_DEVICE)"
python "${GC2026_ROOT}/scripts/evaluate_uvg.py" \
  --pairs-file "$VAL_PAIRS" \
  --enhanced-root "$OUT" \
  --n-samples "$N_SAMPLES" \
  --device "$EVAL_DEVICE" \
  --out-json "${OUT}/evaluation_val_n20k.json" &
PID_VAL=$!
python "${GC2026_ROOT}/scripts/evaluate_uvg.py" \
  --pairs-file "$ALL_PAIRS" \
  --enhanced-root "$OUT" \
  --n-samples "$N_SAMPLES" \
  --device "$EVAL_DEVICE" \
  --out-json "${OUT}/evaluation_full_n20k.json" &
PID_FULL=$!
wait "$PID_VAL" "$PID_FULL" || {
  echo "[post_full] WARN: evaluate_uvg failed (val=$PID_VAL full=$PID_FULL)"
}

post_progress "summarize_per_sequence"
python "${GC2026_ROOT}/scripts/summarize_eval_by_sequence.py" \
  --eval-json "${OUT}/evaluation_val_n20k.json" \
  --out-json "${GC2026_ROOT}/output/enhancement_eval/per_sequence_full_pipeline_val.json" \
  || true

python "${GC2026_ROOT}/scripts/summarize_eval_by_sequence.py" \
  --eval-json "${OUT}/evaluation_full_n20k.json" \
  --out-json "${GC2026_ROOT}/output/enhancement_eval/per_sequence_full_pipeline_full.json" \
  || true

RECON_LIST="${GC2026_ROOT}/output/full_pipeline_cg/reconstructed_cg_list.txt"
if [[ -f "$RECON_LIST" ]]; then
  python "${GC2026_ROOT}/scripts/evaluate_recon_pipeline.py" \
    --recon-list "$RECON_LIST" \
    --enhanced-root "$OUT" \
    --n-samples "$N_SAMPLES" \
    --device "$EVAL_DEVICE" \
    --out-json "${OUT}/evaluation_recon_pipeline.json" \
    || true
fi

post_progress "color_eval"
python "${GC2026_ROOT}/scripts/evaluate_color.py" \
  --pairs-file "$VAL_PAIRS" \
  --enhanced-root "$OUT" \
  --out-json "${OUT}/color_evaluation_val.json" \
  || true

python "${GC2026_ROOT}/scripts/evaluate_temporal.py" \
  --enhanced-root "$OUT" \
  --out-json "${OUT}/temporal_stability.json" || true

post_progress "temporal_smooth"
SMOOTH="${OUT}_smoothed"
PACK_SRC="$OUT"
if python "${GC2026_ROOT}/scripts/temporal_smooth.py" \
  --in-dir "$OUT" \
  --out-dir "$SMOOTH" \
  --window 5; then
  if [[ -f "${OUT}/evaluation_val_n20k.json" ]]; then
    python "${GC2026_ROOT}/scripts/evaluate_uvg.py" \
      --pairs-file "$VAL_PAIRS" \
      --enhanced-root "$SMOOTH" \
      --n-samples "$N_SAMPLES" \
      --device "$EVAL_DEVICE" \
      --out-json "${SMOOTH}/evaluation_val_n20k.json" || true

    raw_improve=$(python3 -c "import json;print(json.load(open('${OUT}/evaluation_val_n20k.json'))['summary']['mean_improvement_cd_l1'])" 2>/dev/null || echo "0")
    smooth_improve=$(python3 -c "import json;print(json.load(open('${SMOOTH}/evaluation_val_n20k.json'))['summary']['mean_improvement_cd_l1'])" 2>/dev/null || echo "0")
    echo "[post_full] raw_improvement=$raw_improve smooth_improvement=$smooth_improve"

    if python3 -c "import sys; r=float('$raw_improve'); s=float('$smooth_improve'); sys.exit(0 if s > r else 1)" 2>/dev/null; then
      echo "[post_full] Using smoothed outputs for pack"
      PACK_SRC="$SMOOTH"
    else
      echo "[post_full] Using raw ENH outputs for pack"
    fi
  fi
else
  echo "[post_full] WARN: temporal_smooth failed — packing raw ENH outputs"
fi

post_progress "pack_tar"
OUT_TAR="${GC2026_ROOT}/output/$(basename "$OUT")_submission.tar.gz"
echo "[post_full] Creating $OUT_TAR from $PACK_SRC ..."
if tar -czf "$OUT_TAR" -C "$(dirname "$PACK_SRC")" "$(basename "$PACK_SRC")"; then
  ls -lh "$OUT_TAR"
else
  echo "[post_full] WARN: tar pack failed"
fi

echo "[post_full] END $(date -Is)"
