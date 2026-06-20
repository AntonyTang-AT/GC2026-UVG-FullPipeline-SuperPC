#!/usr/bin/env bash
# Enhancement Only: official CG PLY -> SuperPC -> ENH PLY (dual-track path A).
set -euo pipefail

GC2026_ROOT="/root/autodl-tmp/GC2026"
source "${GC2026_ROOT}/scripts/env_setup.sh"

OUT_DIR="${OUT_DIR:-${GC2026_ROOT}/output/submission_candidate}"
GATE_JSON="${GC2026_ROOT}/output/val_grid/gate_decision.json"
PER_SEQ_CONFIG="${ENH_PER_SEQ_CONFIG:-${GC2026_ROOT}/output/enhancement_eval/per_sequence_enh_config.json}"

export UVG_CG_VERSION="${UVG_CG_VERSION:-v2}"

CKPT="${CKPT:-${GC2026_ROOT}/models/superpc_pretrained/kitti360_com.pth}"
OUTPUT_MODE="${OUTPUT_MODE:-blend_cg}"
BLEND_VOXEL_MM="${BLEND_VOXEL_MM:-3.0}"
USE_VISION="${USE_VISION:-0}"
NUM_POINTS="${NUM_POINTS:-11520}"
TARGET_NUM_POINTS="${TARGET_NUM_POINTS:-46080}"
ENH_ADAPTIVE_BLEND="${ENH_ADAPTIVE_BLEND:-0}"

if [[ -f "$GATE_JSON" ]]; then
  eval "$(python3 -c "
import json, os
g=json.load(open('$GATE_JSON'))
c=g.get('best_config',{})
ckpt=os.path.join('$GC2026_ROOT', 'models/superpc_pretrained', c.get('checkpoint','kitti360_com.pth'))
print(f'CKPT={ckpt}')
print(f'OUTPUT_MODE={c.get(\"output_mode\",\"blend_cg\")}')
print(f'BLEND_VOXEL_MM={c.get(\"blend_voxel_mm\",3.0)}')
print(f'USE_VISION={c.get(\"use_vision\",0)}')
cgv=g.get('cg_version','v2')
print(f'UVG_CG_VERSION={cgv}')
")"
fi

if [[ -z "${CG_LIST:-}" ]]; then
  if [[ "$UVG_CG_VERSION" == "v2" && -f "${GC2026_ROOT}/data/processed/all_cg_only_cgv2.txt" ]]; then
    CG_LIST="${GC2026_ROOT}/data/processed/all_cg_only_cgv2.txt"
  else
    CG_LIST="${GC2026_ROOT}/data/processed/all_cg_only.txt"
  fi
fi

if [[ -f "$PER_SEQ_CONFIG" ]]; then
  export ENH_PER_SEQ_CONFIG="$PER_SEQ_CONFIG"
else
  if [[ -f "${GC2026_ROOT}/output/val_grid/summary.json" ]]; then
    python "${GC2026_ROOT}/scripts/build_per_sequence_enh_config.py" || true
  fi
fi

export CKPT OUT_DIR OUTPUT_MODE USE_VISION BLEND_VOXEL_MM NUM_POINTS TARGET_NUM_POINTS
export CG_LIST ENH_ADAPTIVE_BLEND

bash "${GC2026_ROOT}/scripts/run_dual_gpu_infer.sh"

echo "[enhancement_only] Waiting for dual-GPU workers..."
EXPECTED=$(wc -l < "${CG_LIST}")
while pgrep -f "run_superpc_infer.py.*--out-dir ${OUT_DIR}" >/dev/null; do
  n=$(find "$OUT_DIR" -name '*.ply' 2>/dev/null | wc -l)
  echo "[enhancement_only] progress ply=$n / $EXPECTED"
  sleep 60
done
n=$(find "$OUT_DIR" -name '*.ply' 2>/dev/null | wc -l)
echo "[enhancement_only] inference finished ply_count=$n / $EXPECTED"

python "${GC2026_ROOT}/scripts/make_submission.py" \
  --enhanced-dir "$OUT_DIR" \
  --processing-track "Enhancement Only" \
  --title "UVG-CWI-DQPC GC2026 Enhancement Only SuperPC" \
  --post-processing "$GATE_JSON" \
  --cg-version "$UVG_CG_VERSION" \
  --pipeline-notes "Official CG PLY input -> SuperPC blend enhancement (per-seq config when available)"

bash "${GC2026_ROOT}/scripts/post_submission_candidate.sh"

echo "[enhancement_only] DONE -> $OUT_DIR"
