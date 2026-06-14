#!/usr/bin/env bash
# Chain: wait val RGBD -> val smoke -> full download/infer if val OK.
set -euo pipefail

GC2026_ROOT="/root/autodl-tmp/GC2026"
LOG="${GC2026_ROOT}/output/full_pipeline_chain.log"

exec > >(tee -a "$LOG") 2>&1
echo "[chain] START $(date -Is)"

bash "${GC2026_ROOT}/scripts/wait_rgbd_and_val.sh"
bash "${GC2026_ROOT}/scripts/run_full_pipeline_after_val.sh"

echo "[chain] END $(date -Is)"
