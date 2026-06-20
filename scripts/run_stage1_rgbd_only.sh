#!/usr/bin/env bash
# Full Pipeline Stage 1 only: RGBD/bag -> reconstructed CG + compare (no SuperPC / GPU).
set -euo pipefail

GC2026_ROOT="/root/autodl-tmp/GC2026"
if [[ -f "${GC2026_ROOT}/output/cwipc_env.sh" ]]; then
  # shellcheck source=/dev/null
  source "${GC2026_ROOT}/output/cwipc_env.sh"
fi
source "${GC2026_ROOT}/scripts/env_setup.sh"

SEQ_FILTER="${SEQ_FILTER:-TicTacToe,VictoryHeart}"
LOG="${GC2026_ROOT}/output/stage1_rgbd_only.log"
exec > >(tee -a "$LOG") 2>&1
echo "[stage1_rgbd_only] START $(date -Is) SEQ=$SEQ_FILTER"

if [[ -f "${GC2026_ROOT}/data/processed/val_cg_only_cgv2.txt" ]]; then
  CG_LIST="${CG_LIST:-${GC2026_ROOT}/data/processed/val_cg_only_cgv2.txt}"
else
  CG_LIST="${CG_LIST:-${GC2026_ROOT}/data/processed/val_cg_only.txt}"
fi
export UVG_CG_VERSION="${UVG_CG_VERSION:-v2}"
INTERMEDIATE_CG="${INTERMEDIATE_CG:-${GC2026_ROOT}/output/full_pipeline_val_cg}"
RGBD_TO_CG_BACKEND="${RGBD_TO_CG_BACKEND:-auto}"
FRAME_MAP_MODE="${FRAME_MAP_MODE:-even}"
MAX_SAMPLES="${MAX_SAMPLES:-0}"

VAL_PAIRS_CG="${GC2026_ROOT}/data/processed/val_pairs_cgv2.txt"
if [[ ! -f "$VAL_PAIRS_CG" ]]; then
  VAL_PAIRS_CG="${GC2026_ROOT}/data/processed/val_pairs.txt"
fi
COMPARE_JSON="${GC2026_ROOT}/output/cg_recon_eval/val_compare_cgv2.json"
RECON_ENH_CONFIG="${GC2026_ROOT}/output/enhancement_eval/recon_enh_config.json"
GATE_JSON="${GC2026_ROOT}/output/cg_recon_eval/phase2_rgbd_gate.json"

echo "[stage1_rgbd_only] CG_LIST=$CG_LIST backend=$RGBD_TO_CG_BACKEND out=$INTERMEDIATE_CG"

python "${GC2026_ROOT}/scripts/uvg_frame_map.py" \
  --cg-list "$CG_LIST" \
  --out-json "${GC2026_ROOT}/data/processed/frame_playback_map.json" \
  --mode "$FRAME_MAP_MODE"

RGBD_ARGS=(--backend "$RGBD_TO_CG_BACKEND" --frame-map-mode "$FRAME_MAP_MODE")
if [[ "$MAX_SAMPLES" -gt 0 ]]; then
  RGBD_ARGS+=(--max-samples "$MAX_SAMPLES")
fi

python "${GC2026_ROOT}/scripts/rgbd_to_cg.py" \
  --cg-list "$CG_LIST" \
  --out-root "$INTERMEDIATE_CG" \
  "${RGBD_ARGS[@]}"

RECON_LIST="${INTERMEDIATE_CG}/reconstructed_cg_list.txt"
python3 <<PY
import json, os
cg_list = "$CG_LIST"
out_root = "$INTERMEDIATE_CG"
gate_path = "$GATE_JSON"
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
print(f"[stage1_rgbd_only] reconstructed frames: {len(paths)} / {len(refs)}")
status = "stage1_done" if paths else "stage1_failed"
gate = {
    "status": status,
    "reconstructed": len(paths),
    "requested": len(refs),
    "seq_filter": "$SEQ_FILTER",
    "intermediate_cg": out_root,
    "backend": "$RGBD_TO_CG_BACKEND",
    "updated_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
}
if not paths:
    gate["reason"] = "no reconstructed PLY — check cwipc/librealsense or Open3D fallback"
with open(gate_path, "w") as f:
    json.dump(gate, f, indent=2)
if not paths:
    raise SystemExit("No reconstructed CG frames")
PY

python "${GC2026_ROOT}/scripts/compare_reconstructed_cg.py" \
  --recon-root "$INTERMEDIATE_CG" \
  --pairs-file "$VAL_PAIRS_CG" \
  --official-version "$UVG_CG_VERSION" \
  --max-samples 50 \
  --n-samples 5000 \
  --device cpu \
  --out-json "$COMPARE_JSON" || true

if [[ -f "$COMPARE_JSON" ]]; then
  python "${GC2026_ROOT}/scripts/build_recon_enh_config.py" \
    --compare-json "$COMPARE_JSON" \
    --out-json "$RECON_ENH_CONFIG"
fi

echo "[stage1_rgbd_only] DONE $(date -Is)"
