#!/usr/bin/env bash
# Full Pipeline N0 v2: merge Val362 N0 v2 + train Stage1 -> SuperPC -> eval + pack.
set -euo pipefail

GC2026_ROOT="${GC2026_ROOT:-/root/autodl-tmp/GC2026}"
SCRIPT_DIR="${GC2026_ROOT}/scripts"
LOG="${GC2026_ROOT}/output/full_n0_v2.log"
STATE="${GC2026_ROOT}/output/full_n0_v2.state"
LOCK="${GC2026_ROOT}/output/full_n0_v2.lock"
PY="${PY:-python3.12}"
TAG="${TAG:-N0_cwipc_official}"
STAGE1_JOBS="${STAGE1_JOBS:-6}"
TARGET_PLY=2155
RECON_ROOT="${GC2026_ROOT}/output/full_pipeline_n0_v2_cg"
ENH_ROOT="${GC2026_ROOT}/output/full_pipeline_n0_v2_candidate"
VAL362_RECON="${GC2026_ROOT}/output/cwipc_native/val362_n0_v2"
RECON_ENH_CONFIG="${GC2026_ROOT}/output/cwipc_native/val362_n0_v2_recon_enh_config.json"

exec > >(tee -a "$LOG") 2>&1

progress() {
  local phase="$1"
  local recon enh
  mkdir -p "$RECON_ROOT" "$ENH_ROOT"
  recon=$(find "$RECON_ROOT" -name '*.ply' 2>/dev/null | wc -l | tr -d ' ') || recon=0
  enh=$(find "$ENH_ROOT" -name '*.ply' 2>/dev/null | wc -l | tr -d ' ') || enh=0
  echo "[full_n0_v2] PROGRESS phase=${phase} recon_ply=${recon}/${TARGET_PLY} enh_ply=${enh}/${TARGET_PLY} $(date +%H:%M:%S)"
}

mark() {
  echo "$1=$(date -Is)" >>"$STATE"
  echo "[full_n0_v2] $1"
}

state_has() {
  grep -qE "^${1}=" "$STATE" 2>/dev/null
}

reorganize_enh() {
  local root="$1"
  "$PY" <<PY
import glob, os, shutil
root = "${root}"
moved = 0
for sub in ("output", "GC2026"):
    flat = os.path.join(root, sub)
    if not os.path.isdir(flat):
        continue
    for ply in glob.glob(os.path.join(flat, "*.ply")):
        base = os.path.basename(ply)
        seq = base.split("_UVG")[0]
        dst_dir = os.path.join(root, seq)
        os.makedirs(dst_dir, exist_ok=True)
        dst = os.path.join(dst_dir, base)
        if not os.path.isfile(dst):
            shutil.copy2(ply, dst)
            moved += 1
for ply in glob.glob(os.path.join(root, "*_UVG-CWI-DQPC_ENH_*.ply")):
    base = os.path.basename(ply)
    seq = base.split("_UVG")[0]
    dst_dir = os.path.join(root, seq)
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, base)
    if not os.path.isfile(dst):
        shutil.move(ply, dst)
        moved += 1
print(f"[full_n0_v2] reorganized {moved} ENH into per-sequence dirs")
PY
}

STOP_AFTER_PHASE="${STOP_AFTER_PHASE:-3}"

main() {
  mkdir -p "${GC2026_ROOT}/output"
  touch "$STATE"
  exec 9>"$LOCK"
  if ! flock -n 9; then
    echo "[full_n0_v2] another runner active — exit"
    exit 0
  fi

  echo "=============================================="
  echo "[full_n0_v2] START $(date -Is)"
  echo "[full_n0_v2] TAG=$TAG STAGE1_JOBS=$STAGE1_JOBS"
  echo "[full_n0_v2] recon=$RECON_ROOT enh=$ENH_ROOT"
  echo "[full_n0_v2] ETA: Stage1 ~2.5-3.5h | SuperPC ~45-60min | Post ~1-1.5h | total ~4.5-6h"
  echo "[full_n0_v2] Watch: bash scripts/watch_full_n0_v2.sh"
  echo "=============================================="

  source "${SCRIPT_DIR}/env_setup.sh"
  if [[ -f "${GC2026_ROOT}/output/cwipc_env.sh" ]]; then
    # shellcheck source=/dev/null
    source "${GC2026_ROOT}/output/cwipc_env.sh"
  fi

  if ! state_has "phase0=done"; then
    mark "phase0_begin"
    df -h /root/autodl-tmp | tail -1
    nvidia-smi -L || true
    if [[ ! -d "$VAL362_RECON" ]]; then
      echo "[full_n0_v2] ERROR: missing $VAL362_RECON — run scripts/run_val362_n0_v2.sh first"
      exit 1
    fi
    mark "phase0=done"
  fi

  if ! state_has "phase1=done"; then
    mark "phase1_begin"
    progress "stage1_start"
    VAL_MERGE_ROOT="$VAL362_RECON" OUT_ROOT="$RECON_ROOT" TAG="$TAG" \
      STAGE1_JOBS="$STAGE1_JOBS" \
      bash "${SCRIPT_DIR}/run_stage1_native_parallel.sh"
    progress "stage1_done"
    "$PY" "${SCRIPT_DIR}/eval_native_gate.py" \
      --recon-root "$RECON_ROOT" \
      --baseline-recon-root "${GC2026_ROOT}/output/remediation/stage1_pgdr_val362" \
      --cg-list "${GC2026_ROOT}/data/processed/val_cg_only_cgv2.txt" \
      --out-json "${RECON_ROOT}/native_gate.json" || true
    mark "phase1=done"
  fi

  if ! state_has "phase2=done"; then
    mark "phase2_begin"
    RECON_LIST="${RECON_ROOT}/reconstructed_cg_list.txt"
    COMPARE_JSON="${GC2026_ROOT}/output/cwipc_native/full_n0_v2_compare.json"
    if [[ -f "$RECON_LIST" ]]; then
      "$PY" "${SCRIPT_DIR}/compare_reconstructed_cg.py" \
        --recon-root "$RECON_ROOT" \
        --pairs-file "${GC2026_ROOT}/data/processed/val_pairs_cgv2.txt" \
        --official-version v2 --max-samples 80 --n-samples 5000 --device cpu \
        --out-json "$COMPARE_JSON" || true
      if [[ -f "$COMPARE_JSON" ]]; then
        "$PY" "${SCRIPT_DIR}/build_recon_enh_config.py" \
          --compare-json "$COMPARE_JSON" \
          --out-json "${GC2026_ROOT}/output/cwipc_native/full_n0_v2_recon_enh_config.json" || true
      fi
    fi

    rm -rf "$ENH_ROOT"
    mkdir -p "$ENH_ROOT"
    export CG_LIST="$RECON_LIST"
    export OUT_DIR="$ENH_ROOT"
    export CKPT="${GC2026_ROOT}/models/superpc_pretrained/kitti360_com.pth"
    export OUTPUT_MODE=blend_cg
    export BLEND_VOXEL_MM=3.0
    export ENH_ADAPTIVE_BLEND=1
    cfg="${GC2026_ROOT}/output/cwipc_native/full_n0_v2_recon_enh_config.json"
    [[ -f "$RECON_ENH_CONFIG" ]] && cfg="$RECON_ENH_CONFIG"
    [[ -f "$cfg" ]] && export ENH_PER_SEQ_CONFIG="$cfg"
    bash "${SCRIPT_DIR}/run_dual_gpu_infer.sh"

    expected=$(wc -l < "$RECON_LIST" | tr -d ' ')
    for ((i = 0; i < 180; i++)); do
      if ! pgrep -f "run_superpc_infer.py.*--out-dir ${ENH_ROOT}" >/dev/null 2>&1; then
        break
      fi
      progress "superpc"
      sleep 20
    done
    reorganize_enh "$ENH_ROOT"
    mark "phase2=done"
    if [[ "$STOP_AFTER_PHASE" -eq 2 ]]; then
      progress "phase2_complete"
      echo "[full_n0_v2] STOP_AFTER_PHASE=2 — SuperPC done, skipping post"
      echo "[full_n0_v2] END $(date -Is)"
      exit 0
    fi
  fi

  if ! state_has "phase3=done"; then
    mark "phase3_begin"
    progress "phase3_reorganize"
    reorganize_enh "$ENH_ROOT"
    progress "phase3_post"
    OUT_DIR="$ENH_ROOT" EVAL_DEVICE=cpu bash "${SCRIPT_DIR}/post_full_pipeline.sh"
    progress "phase3_gate"
    "$PY" "${SCRIPT_DIR}/eval_native_gate.py" \
      --recon-root "$RECON_ROOT" \
      --enh-root "$ENH_ROOT" \
      --baseline-recon-root "${GC2026_ROOT}/output/remediation/stage1_pgdr_val362" \
      --cg-list "${GC2026_ROOT}/data/processed/val_cg_only_cgv2.txt" \
      --out-json "${ENH_ROOT}/native_gate_enh.json" || true
    "$PY" "${SCRIPT_DIR}/compare_val362_baselines.py" \
      --v2-recon-gate "${RECON_ROOT}/native_gate_after_fill.json" \
      --v2-enh-gate "${ENH_ROOT}/native_gate_enh.json" \
      --v2-eval "${ENH_ROOT}/evaluation_val_n20k.json" \
      --baseline-b1-gate "${GC2026_ROOT}/output/cwipc_native/native_gate_enh.json" \
      --baseline-b1-eval "${GC2026_ROOT}/output/full_pipeline_candidate/evaluation_val_n20k.json" \
      --out-json "${GC2026_ROOT}/output/full_n0_v2_final_report.json" 2>/dev/null || true
    PLY=$(find "$ENH_ROOT" -name '*.ply' 2>/dev/null | wc -l | tr -d ' ')
    progress "complete"
    echo "[full_n0_v2] FINAL enh_ply=$PLY tar=${GC2026_ROOT}/output/full_pipeline_n0_v2_candidate_submission.tar.gz"
    mark "phase3=done"
  fi

  echo "[full_n0_v2] END $(date -Is)"
}

main "$@"
