#!/usr/bin/env bash
# Run after all_sequences_official inference finishes (eval, smooth, pack, status).
set -euo pipefail

GC2026_ROOT="/root/autodl-tmp/GC2026"
OUT="${GC2026_ROOT}/output/all_sequences_official"
SMOOTH="${GC2026_ROOT}/output/all_sequences_official_smoothed"
LOG="${GC2026_ROOT}/output/post_official_infer.log"

exec > >(tee -a "$LOG") 2>&1
echo "[post_official] START $(date -Is)"

source "${GC2026_ROOT}/scripts/env_setup.sh"

n=$(find "$OUT" -name '*.ply' | wc -l)
echo "[post_official] ply_count=$n (target 2155)"
if [[ "$n" -lt 2155 ]]; then
  echo "[post_official] WARNING: inference not complete, continuing with available frames"
fi

python "${GC2026_ROOT}/scripts/make_submission.py" --enhanced-dir "$OUT"

python "${GC2026_ROOT}/scripts/evaluate_uvg.py" \
  --pairs-file "${GC2026_ROOT}/data/processed/val_pairs.txt" \
  --enhanced-root "$OUT" \
  --n-samples 4096 \
  --out-json "${OUT}/evaluation_val_summary.json"

python "${GC2026_ROOT}/scripts/evaluate_uvg.py" \
  --pairs-file "${GC2026_ROOT}/data/processed/all_pairs.txt" \
  --enhanced-root "$OUT" \
  --n-samples 4096 \
  --out-json "${OUT}/evaluation_full_summary.json"

python "${GC2026_ROOT}/scripts/temporal_smooth.py" \
  --in-dir "$OUT" \
  --out-dir "$SMOOTH" \
  --window 5

python "${GC2026_ROOT}/scripts/evaluate_uvg.py" \
  --pairs-file "${GC2026_ROOT}/data/processed/val_pairs.txt" \
  --enhanced-root "$SMOOTH" \
  --n-samples 4096 \
  --out-json "${SMOOTH}/evaluation_val_summary.json"

bash "${GC2026_ROOT}/scripts/pack_submission.sh" "$OUT"
python "${GC2026_ROOT}/scripts/generate_status_report.py"

echo "[post_official] END $(date -Is)"
