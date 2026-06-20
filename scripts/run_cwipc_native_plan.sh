#!/usr/bin/env bash
# CWIPC-Native two-stage pipeline: Stage1 recon -> SuperPC ENH.
# TRACK=quick|sweep|finalize|enh|stage1|all
set -euo pipefail

GC2026_ROOT="${GC2026_ROOT:-/root/autodl-tmp/GC2026}"
SCRIPT_DIR="${GC2026_ROOT}/scripts"
STATE="${GC2026_ROOT}/output/cwipc_native/native.state"
LOG="${GC2026_ROOT}/output/cwipc_native/native_plan.log"
DEFAULTS="${GC2026_ROOT}/output/cwipc_native/native_defaults.json"

TRACK="${TRACK:-quick}"
FRAMES_PER_SEQ="${FRAMES_PER_SEQ:-15}"
POLL_SEC="${POLL_SEC:-20}"
MAX_WAIT_MIN="${MAX_WAIT_MIN:-60}"
SWEEP_JOBS="${SWEEP_JOBS:-2}"
PRODUCTION_TAG="${PRODUCTION_TAG:-N0_cwipc_official}"

VAL_CG="${GC2026_ROOT}/data/processed/val_cg_only_cgv2.txt"
SWEEP_JSON="${GC2026_ROOT}/output/cwipc_native/val362_sweep.json"
SWEEP_ROOT="${GC2026_ROOT}/output/cwipc_native/val362_sweep"
WINNER_ROOT="${GC2026_ROOT}/output/cwipc_native/val362_winner"
STAGE1_PROD="${GC2026_ROOT}/output/cwipc_native/stage1_production"
ENH_ROOT="${GC2026_ROOT}/output/cwipc_native/val362_enh"
BASELINE_RECON="${GC2026_ROOT}/output/remediation/stage1_pgdr_val362"
STAGE1_CONFIG="${GC2026_ROOT}/output/remediation/stage1_config.json"
VH_SEQ="VictoryHeart"

PY="${PY:-python3.12}"
export PY_CWIPC="${PY_CWIPC:-$PY}"
export CWIPC_FILTER_PROFILE="${CWIPC_FILTER_PROFILE:-official}"

exec > >(tee -a "$LOG") 2>&1
mkdir -p "${GC2026_ROOT}/output/cwipc_native"
touch "$STATE"

source "${SCRIPT_DIR}/env_setup.sh"
if [[ -f "${GC2026_ROOT}/output/cwipc_env.sh" ]]; then
  # shellcheck source=/dev/null
  source "${GC2026_ROOT}/output/cwipc_env.sh"
fi

mark() {
  echo "$1=$(date -Is)" >>"$STATE"
  echo "[native] $1"
}

state_has() {
  grep -qE "^${1}=" "$STATE" 2>/dev/null
}

poll_gpu_infer() {
  local out_dir="$1" expected="$2" label="$3"
  local max_iter=$((MAX_WAIT_MIN * 60 / POLL_SEC))
  for ((i = 0; i < max_iter; i++)); do
    if ! pgrep -f "run_superpc_infer.py.*--out-dir ${out_dir}" >/dev/null 2>&1; then
      break
    fi
    local n
    n=$(find "$out_dir" -name '*.ply' 2>/dev/null | wc -l | tr -d ' ')
    echo "[native] ${label} ply=${n}/${expected}"
    sleep "$POLL_SEC"
  done
}

install_winner() {
  local tag="$1"
  local src="${SWEEP_ROOT}/${tag}"
  if [[ ! -d "$src" ]]; then
    echo "[native] WARN: winner dir missing: $src"
    return 1
  fi
  rm -rf "$WINNER_ROOT"
  cp -a "$src" "$WINNER_ROOT"
  echo "[native] installed winner: $tag -> $WINNER_ROOT"
}

# Phase 0: VH fine-register
if ! state_has "phase0=done"; then
  mark "phase0_begin"
  reg_cfg="${GC2026_ROOT}/output/remediation/cwipc_registered/${VH_SEQ}/${VH_SEQ}_camera_config.json"
  if [[ ! -f "$reg_cfg" ]]; then
    "$PY" "${SCRIPT_DIR}/run_cwipc_fine_register.py" --sequence "$VH_SEQ" --export-frames 3 || true
  fi
  mark "phase0=done"
fi

# Phase 1: sweeps
if [[ "$TRACK" == "quick" || "$TRACK" == "sweep" || "$TRACK" == "all" ]]; then
  if ! state_has "sweep_quick=done" && [[ "$TRACK" == "quick" || "$TRACK" == "all" ]]; then
    mark "sweep_quick_begin"
    "$PY" "${SCRIPT_DIR}/run_cwipc_native_val362.py" \
      --frames-per-seq "$FRAMES_PER_SEQ" --jobs "$SWEEP_JOBS" \
      --out-json "${GC2026_ROOT}/output/cwipc_native/val362_sweep_quick.json"
    mark "sweep_quick=done"
  fi
  if [[ "$TRACK" == "sweep" || "$TRACK" == "all" ]] && ! state_has "sweep_full=done"; then
    mark "sweep_full_begin"
    "$PY" "${SCRIPT_DIR}/run_cwipc_native_val362.py" \
      --full-seq --jobs "$SWEEP_JOBS" --out-json "$SWEEP_JSON"
    mark "sweep_full=done"
  fi
fi

# P0: production Stage1 rebuild (B1 settings)
if [[ "$TRACK" == "stage1" || "$TRACK" == "all" ]]; then
  if ! state_has "stage1_prod=done"; then
    mark "stage1_prod_begin"
    OUT_ROOT="$STAGE1_PROD" bash "${SCRIPT_DIR}/run_stage1_native.sh"
    cp -a "$STAGE1_PROD/." "$WINNER_ROOT/" 2>/dev/null || true
    mark "stage1_prod=done"
  fi
fi

# P1/P2: finalize — select winner, retry missing, gate
if [[ "$TRACK" == "finalize" || "$TRACK" == "all" ]]; then
  if ! state_has "finalize=done"; then
    mark "finalize_begin"
    "$PY" "${SCRIPT_DIR}/select_native_winner.py" \
      --sweep-root "$SWEEP_ROOT" \
      --prefer-tag "$PRODUCTION_TAG" \
      --out-json "${GC2026_ROOT}/output/cwipc_native/native_winner.json"

    install_tag="${INSTALL_TAG:-$PRODUCTION_TAG}"
    "$PY" "${SCRIPT_DIR}/select_stage1_production_tag.py" || true
    if [[ -f "${GC2026_ROOT}/output/cwipc_native/stage1_production_tag.json" ]]; then
      install_tag="${INSTALL_TAG:-$("$PY" -c "import json; print(json.load(open('${GC2026_ROOT}/output/cwipc_native/stage1_production_tag.json'))['tag'])")}"
    fi

    install_winner "$install_tag" || install_winner "$PRODUCTION_TAG" || true

    retry_backend="hybrid"
    retry_profile="official"
    case "$install_tag" in
      N0_cwipc_official) retry_backend="cwipc"; retry_profile="official" ;;
      N1_cwipc_relaxed) retry_backend="cwipc"; retry_profile="relaxed" ;;
      N2_cwipc_mild) retry_backend="cwipc"; retry_profile="mild" ;;
      B2_hybrid_mild) retry_backend="hybrid"; retry_profile="mild" ;;
    esac

    "$PY" "${SCRIPT_DIR}/retry_missing_recon.py" \
      --recon-root "$WINNER_ROOT" \
      --cg-list "$VAL_CG" \
      --backend "$retry_backend" \
      --cwipc-filter-profile "$retry_profile" \
      --stage1-config "$STAGE1_CONFIG" \
      --baseline-recon-root "$BASELINE_RECON" || true

    set +e
    "$PY" "${SCRIPT_DIR}/eval_native_gate.py" \
      --recon-root "$WINNER_ROOT" \
      --baseline-recon-root "$BASELINE_RECON" \
      --out-json "${GC2026_ROOT}/output/cwipc_native/native_gate.json"
    gate_rc=$?
    set -e
    [[ "$gate_rc" -eq 0 ]] && mark "gate=pass" || mark "gate=fail"
    mark "finalize=done"
    mark "gate=done"
  fi
fi

# Legacy gate path (quick-only, if finalize not run)
if ! state_has "gate=done" && [[ "$TRACK" == "quick" ]]; then
  mark "gate_begin"
  install_winner "$PRODUCTION_TAG" 2>/dev/null || install_winner "N2_cwipc_mild" || true
  set +e
  "$PY" "${SCRIPT_DIR}/eval_native_gate.py" \
    --recon-root "$WINNER_ROOT" \
    --baseline-recon-root "$BASELINE_RECON" \
    --max-frames $((FRAMES_PER_SEQ * 2)) \
    --out-json "${GC2026_ROOT}/output/cwipc_native/native_gate.json"
  set -e
  mark "gate=done"
fi

# Phase 2: SuperPC ENH
if [[ "$TRACK" == "enh" || "$TRACK" == "finalize" || "$TRACK" == "all" ]]; then
  if ! state_has "enh=done"; then
    mark "enh_begin"
    [[ -d "$WINNER_ROOT" ]] || install_winner "$PRODUCTION_TAG" || true
    recon_list="${WINNER_ROOT}/reconstructed_cg_list.txt"
    "$PY" <<PY
import os
refs=open("${VAL_CG}").read().splitlines()
paths=[]
for ref in refs:
    ref=ref.strip()
    if not ref: continue
    seq=os.path.basename(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(ref)))))
    out=os.path.join("${WINNER_ROOT}", seq, os.path.basename(ref))
    if os.path.isfile(out): paths.append(out)
open("${recon_list}","w").write("\\n".join(paths)+("\\n" if paths else ""))
print(len(paths))
PY
    expected=$(wc -l < "$recon_list" | tr -d ' ')
    if [[ "$expected" -gt 0 ]] && command -v nvidia-smi >/dev/null 2>&1; then
      rm -rf "$ENH_ROOT"
      mkdir -p "$ENH_ROOT"
      export CG_LIST="$recon_list"
      export OUT_DIR="$ENH_ROOT"
      export CKPT="${GC2026_ROOT}/models/superpc_pretrained/kitti360_com.pth"
      export OUTPUT_MODE=blend_cg
      export BLEND_VOXEL_MM=3.0
      bash "${SCRIPT_DIR}/run_dual_gpu_infer.sh"
      poll_gpu_infer "$ENH_ROOT" "$expected" "enh"
      "$PY" "${SCRIPT_DIR}/eval_native_gate.py" \
        --recon-root "$WINNER_ROOT" \
        --enh-root "$ENH_ROOT" \
        --baseline-recon-root "$BASELINE_RECON" \
        --out-json "${GC2026_ROOT}/output/cwipc_native/native_gate_enh.json" || true
    fi
    mark "enh=done"
  fi
fi

mark "plan_done"
echo "[native] TRACK=${TRACK} done"
