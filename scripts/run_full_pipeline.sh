#!/usr/bin/env bash
# Full Pipeline: RGBD/bag -> reconstructed CG -> SuperPC enhancement -> ENH PLY.
set -euo pipefail

GC2026_ROOT="/root/autodl-tmp/GC2026"
source "${GC2026_ROOT}/scripts/env_setup.sh"

CG_LIST="${CG_LIST:-${GC2026_ROOT}/data/processed/all_cg_only.txt}"
INTERMEDIATE_CG="${INTERMEDIATE_CG:-${GC2026_ROOT}/output/full_pipeline_cg}"
OUT_DIR="${OUT_DIR:-${GC2026_ROOT}/output/full_pipeline_candidate}"
GATE_JSON="${GC2026_ROOT}/output/val_grid/gate_decision.json"
MAX_SAMPLES="${MAX_SAMPLES:-0}"
PREFER_CWIPC="${PREFER_CWIPC:-0}"

# Enhancement stage defaults (from gate if present)
CKPT="${CKPT:-${GC2026_ROOT}/models/superpc_pretrained/kitti360_com.pth}"
OUTPUT_MODE="${OUTPUT_MODE:-blend_cg}"
BLEND_VOXEL_MM="${BLEND_VOXEL_MM:-3.0}"
NUM_POINTS="${NUM_POINTS:-11520}"
TARGET_NUM_POINTS="${TARGET_NUM_POINTS:-46080}"
USE_VISION="${USE_VISION:-0}"

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
")"
fi

echo "[full_pipeline] Stage 1: RGBD/bag -> CG PLY -> $INTERMEDIATE_CG"
RGBD_ARGS=()
if [[ "$PREFER_CWIPC" == "1" ]]; then
  RGBD_ARGS+=(--prefer-cwipc-bag)
fi
if [[ "$MAX_SAMPLES" -gt 0 ]]; then
  RGBD_ARGS+=(--max-samples "$MAX_SAMPLES")
fi

python "${GC2026_ROOT}/scripts/rgbd_to_cg.py" \
  --cg-list "$CG_LIST" \
  --out-root "$INTERMEDIATE_CG" \
  "${RGBD_ARGS[@]}"

# Build cg list from reconstructed outputs
RECON_LIST="${INTERMEDIATE_CG}/reconstructed_cg_list.txt"
python3 <<PY
import os
cg_list = "$CG_LIST"
out_root = "$INTERMEDIATE_CG"
with open(cg_list) as f:
    refs = [ln.strip() for ln in f if ln.strip()]
paths = []
for ref in refs:
    seq = os.path.basename(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(ref)))))
    out = os.path.join(out_root, seq, os.path.basename(ref))
    if os.path.isfile(out):
        paths.append(out)
with open("$RECON_LIST", "w") as f:
    f.write("\n".join(paths) + ("\n" if paths else ""))
print(f"[full_pipeline] reconstructed frames: {len(paths)}")
if not paths:
    raise SystemExit("No reconstructed CG frames — check RGBD/raw download")
PY

echo "[full_pipeline] Stage 2: SuperPC enhancement -> $OUT_DIR"
VISION_ARGS=()
if [[ "$USE_VISION" == "1" ]]; then
  VISION_ARGS=(--use-vision-conditioning)
  PAIRS="${GC2026_ROOT}/data/processed/rgbd_pairs.txt"
  if [[ -f "$PAIRS" ]]; then
    VISION_ARGS+=(--rgbd-pairs-file "$PAIRS")
  fi
fi

export CKPT OUT_DIR OUTPUT_MODE USE_VISION BLEND_VOXEL_MM NUM_POINTS TARGET_NUM_POINTS
export CG_LIST="$RECON_LIST"
bash "${GC2026_ROOT}/scripts/run_dual_gpu_infer.sh"

echo "[full_pipeline] Waiting for dual-GPU workers..."
EXPECTED=$(wc -l < "$RECON_LIST")
while pgrep -f "run_superpc_infer.py.*--out-dir ${OUT_DIR}" >/dev/null; do
  n=$(find "$OUT_DIR" -name '*.ply' 2>/dev/null | wc -l)
  echo "[full_pipeline] progress ply=$n / $EXPECTED"
  sleep 60
done
n=$(find "$OUT_DIR" -name '*.ply' 2>/dev/null | wc -l)
echo "[full_pipeline] inference finished ply_count=$n / $EXPECTED"

echo "[full_pipeline] Stage 3: manifest (Full Pipeline track)"
python "${GC2026_ROOT}/scripts/make_submission.py" \
  --enhanced-dir "$OUT_DIR" \
  --processing-track "Full Pipeline" \
  --title "UVG-CWI-DQPC GC2026 Full Pipeline SuperPC" \
  --post-processing "$GATE_JSON" \
  --pipeline-notes "RGBD/bag -> rgbd_to_cg.py -> SuperPC blend enhancement"

echo "[full_pipeline] DONE -> $OUT_DIR"
if [[ "${RUN_POST:-0}" == "1" ]]; then
  OUT_DIR="$OUT_DIR" bash "${GC2026_ROOT}/scripts/post_full_pipeline.sh"
fi
