#!/usr/bin/env bash
# Post-process submission candidate: eval (n=20k), optional smooth, manifest, metrics.
set -euo pipefail

GC2026_ROOT="/root/autodl-tmp/GC2026"
OUT="${OUT_DIR:-${GC2026_ROOT}/output/submission_candidate}"
GATE_JSON="${GC2026_ROOT}/output/val_grid/gate_decision.json"
LOG="${GC2026_ROOT}/output/post_submission_candidate.log"
N_SAMPLES=20000

exec > >(tee -a "$LOG") 2>&1
echo "[post_candidate] START $(date -Is) OUT=$OUT"

source "${GC2026_ROOT}/scripts/env_setup.sh"

if [[ -f "$GATE_JSON" ]]; then
  python3 -c "import json; d=json.load(open('$GATE_JSON')); print('gate', d.get('gate_passed'), d.get('best_experiment'))"
fi

n=$(find "$OUT" -name '*.ply' 2>/dev/null | wc -l)
echo "[post_candidate] ply_count=$n"

python "${GC2026_ROOT}/scripts/make_submission.py" \
  --enhanced-dir "$OUT" \
  --team "GC2026 Team" \
  --post-processing "${GC2026_ROOT}/output/val_grid/gate_decision.json"

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
  --out-json "${OUT}/temporal_stability.json"

SMOOTH="${OUT}_smoothed"
python "${GC2026_ROOT}/scripts/temporal_smooth.py" \
  --in-dir "$OUT" \
  --out-dir "$SMOOTH" \
  --window 5

python "${GC2026_ROOT}/scripts/evaluate_uvg.py" \
  --pairs-file "${GC2026_ROOT}/data/processed/val_pairs.txt" \
  --enhanced-root "$SMOOTH" \
  --n-samples "$N_SAMPLES" \
  --out-json "${SMOOTH}/evaluation_val_n20k.json"

raw_improve=$(python3 -c "import json;print(json.load(open('${OUT}/evaluation_val_n20k.json'))['summary']['mean_improvement_cd_l1'])")
smooth_improve=$(python3 -c "import json;print(json.load(open('${SMOOTH}/evaluation_val_n20k.json'))['summary']['mean_improvement_cd_l1'])")
echo "[post_candidate] raw_improvement=$raw_improve smooth_improvement=$smooth_improve"

if python3 -c "import sys; r=float('$raw_improve'); s=float('$smooth_improve'); sys.exit(0 if s > r else 1)"; then
  echo "[post_candidate] Using smoothed outputs for pack"
  PACK_SRC="$SMOOTH"
else
  echo "[post_candidate] Using raw ENH outputs for pack"
  PACK_SRC="$OUT"
fi

bash "${GC2026_ROOT}/scripts/pack_submission.sh" "$PACK_SRC"
python "${GC2026_ROOT}/scripts/generate_status_report.py"

echo "[post_candidate] END $(date -Is)"
