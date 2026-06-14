#!/usr/bin/env bash
# Overnight autonomous runner — logs to output/overnight_run.log
set -euo pipefail

GC2026_ROOT="/root/autodl-tmp/GC2026"
LOG="${GC2026_ROOT}/output/overnight_run.log"
mkdir -p "${GC2026_ROOT}/output"

exec > >(tee -a "$LOG") 2>&1

echo "========== OVERNIGHT START $(date -Is) =========="

source "${GC2026_ROOT}/scripts/env_setup.sh"

# 1) Official weights (fast skip if Drive unreachable)
echo "[overnight] Step 1: download official weights"
bash "${GC2026_ROOT}/scripts/download_pretrained.sh" || echo "[overnight] download failed, continuing"

# Merge prior BlueSpeech run so --skip-existing can skip re-inference
if [[ -d "${GC2026_ROOT}/output/BlueSpeech_enhanced/BlueSpeech" ]]; then
  mkdir -p "${GC2026_ROOT}/output/all_sequences_enhanced"
  rsync -a "${GC2026_ROOT}/output/BlueSpeech_enhanced/BlueSpeech/" \
    "${GC2026_ROOT}/output/all_sequences_enhanced/BlueSpeech/" 2>/dev/null || true
fi

# 2) Quick BlueSpeech eval (val subset only — train full eval is ~4h)
echo "[overnight] Step 2: evaluate BlueSpeech (val frames only)"
python "${GC2026_ROOT}/scripts/evaluate_uvg.py" \
  --pairs-file "${GC2026_ROOT}/data/processed/val_pairs.txt" \
  --enhanced-root "${GC2026_ROOT}/output/BlueSpeech_enhanced" \
  --out-json "${GC2026_ROOT}/output/BlueSpeech_enhanced/evaluation_val.json" \
  --n-samples 4096 \
  || true

# 3) Temporal smooth BlueSpeech (optional quality pass)
echo "[overnight] Step 3: temporal smooth BlueSpeech"
python "${GC2026_ROOT}/scripts/temporal_smooth.py" \
  --in-dir "${GC2026_ROOT}/output/BlueSpeech_enhanced" \
  --out-dir "${GC2026_ROOT}/output/BlueSpeech_smoothed" \
  --window 5 || true

# 4) All sequences inference (~40min at 1.3fps for 2155 frames)
echo "[overnight] Step 4: infer all sequences"
bash "${GC2026_ROOT}/scripts/run_all_sequences.sh" --skip-download --skip-existing --device cuda

echo "========== OVERNIGHT END $(date -Is) =========="
