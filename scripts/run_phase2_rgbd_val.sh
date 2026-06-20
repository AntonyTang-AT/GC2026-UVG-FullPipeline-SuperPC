#!/usr/bin/env bash
# Phase 2: val RGBD installed -> cwipc reconstruct -> compare vs CGv2 -> full pipeline val.
set -euo pipefail

GC2026_ROOT="/root/autodl-tmp/GC2026"
if [[ -f "${GC2026_ROOT}/output/cwipc_env.sh" ]]; then
  # shellcheck source=/dev/null
  source "${GC2026_ROOT}/output/cwipc_env.sh"
fi
LOG="${GC2026_ROOT}/output/phase2_rgbd_val.log"
exec > >(tee -a "$LOG") 2>&1

echo "[phase2_rgbd_val] START $(date -Is)"

SEQ_FILTER="${SEQ_FILTER:-TicTacToe,VictoryHeart}"
if ! SEQ_FILTER="$SEQ_FILTER" bash "${GC2026_ROOT}/scripts/check_rgbd_download.sh"; then
  echo "[phase2_rgbd_val] RGBD download incomplete — finish RGBD first"
  exit 1
fi

SEQ_FILTER="$SEQ_FILTER" bash "${GC2026_ROOT}/scripts/post_rgbd_install.sh"

export UVG_CG_VERSION=v2
export RGBD_TO_CG_BACKEND=auto
export CG_LIST="${GC2026_ROOT}/data/processed/val_cg_only_cgv2.txt"
if [[ ! -f "$CG_LIST" ]]; then
  CG_LIST="${GC2026_ROOT}/data/processed/val_cg_only.txt"
fi

RECON="${GC2026_ROOT}/output/full_pipeline_val_cg"
python "${GC2026_ROOT}/scripts/rgbd_to_cg.py" \
  --cg-list "$CG_LIST" \
  --out-root "$RECON" \
  --backend auto

python "${GC2026_ROOT}/scripts/compare_reconstructed_cg.py" \
  --recon-root "$RECON" \
  --pairs-file "${GC2026_ROOT}/data/processed/val_pairs_cgv2.txt" \
  --out-json "${GC2026_ROOT}/output/cg_recon_eval/val_compare_cgv2.json"

bash "${GC2026_ROOT}/scripts/run_full_pipeline_val.sh"

echo "[phase2_rgbd_val] DONE $(date -Is)"
