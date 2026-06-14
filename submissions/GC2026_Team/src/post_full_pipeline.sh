#!/usr/bin/env bash
# Post-process Full Pipeline candidate: manifest, eval (n=20k), color/temporal, pack.
set -euo pipefail

GC2026_ROOT="/root/autodl-tmp/GC2026"
OUT="${OUT_DIR:-${GC2026_ROOT}/output/full_pipeline_candidate}"
GATE_JSON="${GC2026_ROOT}/output/val_grid/gate_decision.json"
LOG="${GC2026_ROOT}/output/post_full_pipeline.log"
N_SAMPLES=20000

exec > >(tee -a "$LOG") 2>&1
echo "[post_full] START $(date -Is) OUT=$OUT"

source "${GC2026_ROOT}/scripts/env_setup.sh"

if [[ -f "$GATE_JSON" ]]; then
  python3 -c "import json; d=json.load(open('$GATE_JSON')); print('gate', d.get('gate_passed'), d.get('best_experiment'))"
fi

n=$(find "$OUT" -name '*.ply' 2>/dev/null | wc -l)
echo "[post_full] ply_count=$n"

python "${GC2026_ROOT}/scripts/make_submission.py" \
  --enhanced-dir "$OUT" \
  --team "GC2026 Team" \
  --processing-track "Full Pipeline" \
  --title "UVG-CWI-DQPC GC2026 Full Pipeline SuperPC" \
  --post-processing "$GATE_JSON" \
  --pipeline-notes "RGBD/bag -> rgbd_to_cg.py -> SuperPC blend enhancement"

python "${GC2026_ROOT}/scripts/evaluate_uvg.py" \
  --pairs-file "${GC2026_ROOT}/data/processed/val_pairs.txt" \
  --enhanced-root "$OUT" \
  --n-samples "$N_SAMPLES" \
  --out-json "${OUT}/evaluation_val_n20k.json"

python "${GC2026_ROOT}/scripts/evaluate_uvg.py" \
  --pairs-file "${GC2026_ROOT}/data/processed/all_pairs.txt" \
  --enhanced-root "$OUT" \
  --n-samples "$N_SAMPLES" \
  --out-json "${OUT}/evaluation_full_n20k.json"

python "${GC2026_ROOT}/scripts/evaluate_color.py" \
  --pairs-file "${GC2026_ROOT}/data/processed/val_pairs.txt" \
  --enhanced-root "$OUT" \
  --out-json "${OUT}/color_evaluation_val.json"

python "${GC2026_ROOT}/scripts/evaluate_temporal.py" \
  --enhanced-root "$OUT" \
  --out-json "${OUT}/temporal_stability.json" || true

OUT_TAR="${GC2026_ROOT}/output/$(basename "$OUT")_submission.tar.gz"
echo "[post_full] Creating $OUT_TAR (this may take a while)..."
tar -czf "$OUT_TAR" -C "$(dirname "$OUT")" "$(basename "$OUT")"
ls -lh "$OUT_TAR"

echo "[post_full] END $(date -Is)"
