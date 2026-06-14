#!/usr/bin/env bash
# Extended autonomous batch (eval, smooth, pack, status) — logs to output/extended_run.log
set -euo pipefail

GC2026_ROOT="/root/autodl-tmp/GC2026"
LOG="${GC2026_ROOT}/output/extended_run.log"
mkdir -p "${GC2026_ROOT}/output"

exec > >(tee -a "$LOG") 2>&1

echo "========== EXTENDED START $(date -Is) =========="
source "${GC2026_ROOT}/scripts/env_setup.sh"

# 1) Retry official weights (non-blocking)
echo "[extended] Step 1: retry weight download"
bash "${GC2026_ROOT}/scripts/download_pretrained.sh" || true
find "${GC2026_ROOT}/models/superpc_pretrained" -name "*.pth" ! -name "*smoke*" 2>/dev/null | head -3

# 2) Full-dataset eval (all pairs with HE, subsampled Chamfer)
echo "[extended] Step 2: full evaluation (all pairs, n=4096)"
python "${GC2026_ROOT}/scripts/evaluate_uvg.py" \
  --pairs-file "${GC2026_ROOT}/data/processed/all_pairs.txt" \
  --enhanced-root "${GC2026_ROOT}/output/all_sequences_enhanced" \
  --n-samples 4096 \
  --out-json "${GC2026_ROOT}/output/all_sequences_enhanced/evaluation_full_summary.json" \
  || true

# 3) Temporal smooth all sequences
echo "[extended] Step 3: temporal smooth all sequences"
python "${GC2026_ROOT}/scripts/temporal_smooth.py" \
  --in-dir "${GC2026_ROOT}/output/all_sequences_enhanced" \
  --out-dir "${GC2026_ROOT}/output/all_sequences_smoothed" \
  --window 5 || true

python "${GC2026_ROOT}/scripts/make_submission.py" \
  --enhanced-dir "${GC2026_ROOT}/output/all_sequences_smoothed" || true

# 4) Eval smoothed on val
echo "[extended] Step 4: evaluate smoothed (val)"
python "${GC2026_ROOT}/scripts/evaluate_uvg.py" \
  --pairs-file "${GC2026_ROOT}/data/processed/val_pairs.txt" \
  --enhanced-root "${GC2026_ROOT}/output/all_sequences_smoothed" \
  --n-samples 4096 \
  --out-json "${GC2026_ROOT}/output/all_sequences_smoothed/evaluation_val_summary.json" \
  || true

# 5) Pack submission (tar.gz — safer for large PLY trees)
echo "[extended] Step 5: pack submission"
bash "${GC2026_ROOT}/scripts/pack_submission.sh" "${GC2026_ROOT}/output/all_sequences_enhanced" || true

# 6) Status report
python "${GC2026_ROOT}/scripts/generate_status_report.py"

echo "========== EXTENDED END $(date -Is) =========="
