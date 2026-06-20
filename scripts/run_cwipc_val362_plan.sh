#!/usr/bin/env bash
# Val362 plan: Stage1 (cwipc) -> CD eval -> SuperPC -> report.
# S312 naming: SuperPC here = Stage3; see run_s312_improvement_plan.sh for polish Stage2.
set -euo pipefail

GC2026_ROOT="${GC2026_ROOT:-/root/autodl-tmp/GC2026}"
LOG="${GC2026_ROOT}/output/remediation/cwipc_val362_plan.log"
STATE="${GC2026_ROOT}/output/remediation/cwipc_val362.state"
RECON="${GC2026_ROOT}/output/remediation/stage1_cwipc_val362"
OUT_ENH="${GC2026_ROOT}/output/remediation/stage1_cwipc_val362_candidate"
VAL_CG="${GC2026_ROOT}/data/processed/val_cg_only_cgv2.txt"
VAL_PAIRS="${GC2026_ROOT}/data/processed/val_pairs_cgv2.txt"
PY="${PY:-python3.12}"

exec > >(tee -a "$LOG") 2>&1
mkdir -p "${GC2026_ROOT}/output/remediation"
touch "$STATE"

mark() {
  echo "$1=$(date -Is)" >>"$STATE"
  echo "[cwipc_val362] $1"
}

state_has() {
  grep -qE "^${1}=" "$STATE" 2>/dev/null
}

source "${GC2026_ROOT}/scripts/env_setup.sh"
if [[ -f "${GC2026_ROOT}/output/cwipc_env.sh" ]]; then
  # shellcheck source=/dev/null
  source "${GC2026_ROOT}/output/cwipc_env.sh"
fi

mark "plan_start"

# --- Phase 1: Stage1 cwipc Val362 ---
if ! state_has "stage1=done"; then
  mark "stage1_begin"
  export RGBD_TO_CG_BACKEND=cwipc
  rm -rf "$RECON"
  mkdir -p "$RECON"
  "$PY" "${GC2026_ROOT}/scripts/rgbd_to_cg.py" \
    --cg-list "$VAL_CG" \
    --out-root "$RECON" \
    --backend cwipc \
    --frame-map-mode even \
    --force
  n=$(find "$RECON" -name '*.ply' | wc -l)
  echo "[cwipc_val362] stage1 ply_count=$n / 362"
  if [[ "$n" -lt 300 ]]; then
    echo "[cwipc_val362] WARN: low frame count — check log"
  fi
  mark "stage1=done"
fi

# --- Phase 2: CD vs official CG (362) + vs HE ---
if ! state_has "eval_cg=done"; then
  mark "eval_cg_begin"
  "$PY" "${GC2026_ROOT}/scripts/compare_reconstructed_cg.py" \
    --recon-root "$RECON" \
    --pairs-file "$VAL_PAIRS" \
    --official-version v2 \
    --max-samples 0 \
    --n-samples 5000 \
    --device cpu \
    --out-json "${GC2026_ROOT}/output/remediation/stage1_cwipc_val362_vs_official.json"

  "$PY" <<PY
import json, os, sys
sys.path.insert(0, "${GC2026_ROOT}/scripts")
from diagnose_stage1 import build_official_pairs, recon_he_pairs, mean_chamfer_pairs

pairs = build_official_pairs("${VAL_PAIRS}", max_samples=0)
he_pairs = recon_he_pairs("${RECON}", pairs)
m = mean_chamfer_pairs(he_pairs, n_samples=5000)
out = {
    "recon_root": "${RECON}",
    "recon_vs_he": m,
    "created_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
}
path = "${GC2026_ROOT}/output/remediation/stage1_cwipc_val362_vs_he.json"
json.dump(out, open(path, "w"), indent=2)
print(json.dumps({"recon_vs_he_mean_cd": m.get("mean_cd_l1"), "n": m.get("num_evaluated")}, indent=2))
PY
  mark "eval_cg=done"
fi

# --- Phase 3: winner JSON + baseline compare ---
if ! state_has "winner=done"; then
  mark "winner_begin"
  "$PY" <<'PY'
import json
from datetime import datetime

root = "/root/autodl-tmp/GC2026/output/remediation"
cwipc = json.load(open(f"{root}/stage1_cwipc_val362_vs_official.json"))["summary"]
open3d_path = f"{root}/stage1_val362_compare.json"
open3d_cd = None
if __import__("os").path.isfile(open3d_path):
    open3d_cd = json.load(open(open3d_path))["summary"].get("mean_cd_l1")

he_path = f"{root}/stage1_cwipc_val362_vs_he.json"
he_cd = None
if __import__("os").path.isfile(he_path):
    he_cd = json.load(open(he_path)).get("recon_vs_he", {}).get("mean_cd_l1")

winner = {
    "winner": "cwipc",
    "backend": "cwipc",
    "frame_map_mode": "even",
    "recon_root": f"{root}/stage1_cwipc_val362",
    "mean_cd_vs_official": cwipc.get("mean_cd_l1"),
    "mean_cd_vs_he": he_cd,
    "open3d_hybrid_baseline_cd": open3d_cd,
    "num_evaluated": cwipc.get("num_evaluated"),
    "notes": "8-camera cwipc_realsense2_playback + transform_matrix; relaxed filtering",
    "created_at": datetime.utcnow().isoformat() + "Z",
}
json.dump(winner, open(f"{root}/stage1_winner_cwipc.json", "w"), indent=2)
print(json.dumps(winner, indent=2))
PY
  mark "winner=done"
fi

# --- Phase 4: Stage2 SuperPC on Val362 ---
if ! state_has "stage2=done"; then
  mark "stage2_begin"
  RECON_LIST="${RECON}/reconstructed_cg_list.txt"
  "$PY" <<PY
import os
refs = open("${VAL_CG}").read().splitlines()
paths = []
for ref in refs:
    ref = ref.strip()
    if not ref: continue
    seq = os.path.basename(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(ref)))))
    out = os.path.join("${RECON}", seq, os.path.basename(ref))
    if os.path.isfile(out):
        paths.append(out)
open("${RECON_LIST}", "w").write("\n".join(paths) + ("\n" if paths else ""))
print(f"recon_list={len(paths)}")
PY

  if command -v nvidia-smi >/dev/null 2>&1; then
    rm -rf "$OUT_ENH"
    mkdir -p "$OUT_ENH"
    export CG_LIST="$RECON_LIST"
    export OUT_DIR="$OUT_ENH"
    export INTERMEDIATE_CG="$RECON"
    export RGBD_TO_CG_BACKEND=cwipc
    export MAX_SAMPLES=0
    export CKPT="${GC2026_ROOT}/models/superpc_pretrained/kitti360_com.pth"
    export OUTPUT_MODE=blend_cg
    export BLEND_VOXEL_MM=3.0
    export USE_VISION=0

    # Stage1 already done — run Stage2 only
    bash "${GC2026_ROOT}/scripts/run_dual_gpu_infer.sh" || true
    EXPECTED=$(wc -l < "$RECON_LIST")
    for _ in $(seq 1 120); do
      if ! pgrep -f "run_superpc_infer.py.*--out-dir ${OUT_ENH}" >/dev/null; then
        break
      fi
      n=$(find "$OUT_ENH" -name '*.ply' 2>/dev/null | wc -l)
      echo "[cwipc_val362] stage2 progress ply=$n / $EXPECTED"
      sleep 30
    done
    n=$(find "$OUT_ENH" -name '*.ply' 2>/dev/null | wc -l)
    echo "[cwipc_val362] stage2 finished ply=$n / $EXPECTED"

    if [[ "$n" -gt 0 ]]; then
      OUT_DIR="$OUT_ENH" bash "${GC2026_ROOT}/scripts/post_full_pipeline.sh" || true
    fi
  else
    echo "[cwipc_val362] no GPU — skip Stage2"
  fi
  mark "stage2=done"
fi

mark "plan_done"
echo "[cwipc_val362] ALL DONE — see $LOG and output/remediation/stage1_winner_cwipc.json"
