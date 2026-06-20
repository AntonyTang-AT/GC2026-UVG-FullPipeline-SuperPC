#!/usr/bin/env bash
# Overnight CWIPC-Native Full Pipeline: Val362 close -> 2155 Stage1 -> SuperPC -> pack -> strict shutdown.
set -euo pipefail

GC2026_ROOT="${GC2026_ROOT:-/root/autodl-tmp/GC2026}"
SCRIPT_DIR="${GC2026_ROOT}/scripts"
LOG="${GC2026_ROOT}/output/overnight_native_full.log"
LOCK="${GC2026_ROOT}/output/overnight_native_full.lock"
STATE="${GC2026_ROOT}/output/overnight_native_full.state"
PY="${PY:-python3.12}"
PRODUCTION_TAG="${PRODUCTION_TAG:-B1_hybrid_official}"
STAGE1_JOBS="${STAGE1_JOBS:-6}"
MIN_DISK_GB="${MIN_DISK_GB:-80}"
TARGET_PLY=2155

exec > >(tee -a "$LOG") 2>&1

mark() {
  echo "$1=$(date -Is)" >>"$STATE"
  echo "[overnight] $1"
}

state_has() {
  grep -qE "^${1}=" "$STATE" 2>/dev/null
}

avail_disk_gb() {
  df -BG /root/autodl-tmp 2>/dev/null | awk 'NR==2{gsub(/G/,"",$4); print $4}' || echo 0
}

main() {
  mkdir -p "${GC2026_ROOT}/output"
  touch "$STATE"
  exec 9>"$LOCK"
  if ! flock -n 9; then
    echo "[overnight] another runner active — exit"
    exit 0
  fi

  echo "[overnight] START $(date -Is)"
  source "${SCRIPT_DIR}/env_setup.sh"
  if [[ -f "${GC2026_ROOT}/output/cwipc_env.sh" ]]; then
    # shellcheck source=/dev/null
    source "${GC2026_ROOT}/output/cwipc_env.sh"
  fi

  # --- Phase 0 ---
  if ! state_has "phase0=done"; then
    mark "phase0_begin"
    disk=$(avail_disk_gb)
    echo "[overnight] disk_avail=${disk}G (need >=${MIN_DISK_GB}G)"
    if [[ "$disk" -lt "$MIN_DISK_GB" ]]; then
      echo "[overnight] ERROR: insufficient disk"
      exit 1
    fi
    nvidia-smi -L || true
    sed -i '/finalize=done/d;/^enh=done/d;/stage1_prod=done/d' \
      "${GC2026_ROOT}/output/cwipc_native/native.state" 2>/dev/null || true
    bash "${SCRIPT_DIR}/check_integrity.sh" | tee "${GC2026_ROOT}/output/overnight_integrity_baseline.log" || true
    mark "phase0=done"
  fi

  # --- Phase 1: Val362 finalize + enh + tag selection ---
  if ! state_has "phase1=done"; then
    mark "phase1_begin"
    PRODUCTION_TAG="$PRODUCTION_TAG" TRACK=finalize \
      bash "${SCRIPT_DIR}/run_cwipc_native_plan.sh"
    sed -i '/^enh=done/d' "${GC2026_ROOT}/output/cwipc_native/native.state" 2>/dev/null || true
    TRACK=enh bash "${SCRIPT_DIR}/run_cwipc_native_plan.sh"
    "$PY" "${SCRIPT_DIR}/select_stage1_production_tag.py"
    mark "phase1=done"
  fi

  # --- Phase 2: full Stage1 2155 parallel ---
  if ! state_has "phase2=done"; then
    mark "phase2_begin"
    TAG=$("$PY" -c "import json; print(json.load(open('${GC2026_ROOT}/output/cwipc_native/stage1_production_tag.json'))['tag'])")
    STAGE1_JOBS="$STAGE1_JOBS" TAG="$TAG" \
      bash "${SCRIPT_DIR}/run_stage1_native_parallel.sh"
    "$PY" "${SCRIPT_DIR}/eval_native_gate.py" \
      --recon-root "${GC2026_ROOT}/output/full_pipeline_cg" \
      --baseline-recon-root "${GC2026_ROOT}/output/remediation/stage1_pgdr_val362" \
      --cg-list "${GC2026_ROOT}/data/processed/val_cg_only_cgv2.txt" \
      --out-json "${GC2026_ROOT}/output/full_pipeline_cg/native_gate.json" || true
    mark "phase2=done"
  fi

  # --- Phase 3: SuperPC 2155 ---
  if ! state_has "phase3=done"; then
    mark "phase3_begin"
    RECON_LIST="${GC2026_ROOT}/output/full_pipeline_cg/reconstructed_cg_list.txt"
    OUT_DIR="${GC2026_ROOT}/output/full_pipeline_candidate"
    INTERMEDIATE="${GC2026_ROOT}/output/full_pipeline_cg"
    COMPARE_JSON="${GC2026_ROOT}/output/cg_recon_eval/full_compare_cgv2.json"
    RECON_ENH_CONFIG="${GC2026_ROOT}/output/enhancement_eval/recon_enh_config.json"
    VAL_PAIRS="${GC2026_ROOT}/data/processed/val_pairs_cgv2.txt"

    if [[ ! -s "$RECON_LIST" ]]; then
      echo "[overnight] ERROR: missing $RECON_LIST"
      exit 1
    fi

    if find "$INTERMEDIATE" -name '*.ply' | head -1 | grep -q .; then
      "$PY" "${SCRIPT_DIR}/compare_reconstructed_cg.py" \
        --recon-root "$INTERMEDIATE" \
        --pairs-file "$VAL_PAIRS" \
        --official-version v2 \
        --max-samples 50 \
        --n-samples 5000 \
        --device cpu \
        --out-json "$COMPARE_JSON" || true
      if [[ -f "$COMPARE_JSON" ]]; then
        "$PY" "${SCRIPT_DIR}/build_recon_enh_config.py" \
          --compare-json "$COMPARE_JSON" \
          --out-json "$RECON_ENH_CONFIG" || true
      fi
    fi

    rm -rf "$OUT_DIR"
    mkdir -p "$OUT_DIR"
    export CG_LIST="$RECON_LIST"
    export OUT_DIR
    export CKPT="${GC2026_ROOT}/models/superpc_pretrained/kitti360_com.pth"
    export OUTPUT_MODE=blend_cg
    export BLEND_VOXEL_MM=3.0
    export ENH_ADAPTIVE_BLEND=1
    if [[ -f "$RECON_ENH_CONFIG" ]]; then
      export ENH_PER_SEQ_CONFIG="$RECON_ENH_CONFIG"
    fi
    bash "${SCRIPT_DIR}/run_dual_gpu_infer.sh"

    expected=$(wc -l < "$RECON_LIST" | tr -d ' ')
    for ((i = 0; i < 180; i++)); do
      if ! pgrep -f "run_superpc_infer.py.*--out-dir ${OUT_DIR}" >/dev/null 2>&1; then
        break
      fi
      n=$(find "$OUT_DIR" -name '*.ply' 2>/dev/null | wc -l | tr -d ' ')
      echo "[overnight] superpc ply=${n}/${expected}"
      sleep 20
    done
    mark "phase3=done"
  fi

  # --- Phase 4: post, verify, archive, shutdown ---
  if ! state_has "phase4=done"; then
    mark "phase4_begin"
    OUT_DIR="${GC2026_ROOT}/output/full_pipeline_candidate"
    OUT_DIR="$OUT_DIR" EVAL_DEVICE=cpu bash "${SCRIPT_DIR}/post_full_pipeline.sh"
    bash "${SCRIPT_DIR}/prepare_submission_repo.sh" || true
    "$PY" "${SCRIPT_DIR}/generate_status_report.py" || true

    bash "${SCRIPT_DIR}/check_integrity.sh" | tee "${GC2026_ROOT}/output/overnight_integrity.log" || true
    PLY=$(find "$OUT_DIR" -name '*.ply' 2>/dev/null | wc -l | tr -d ' ')
    FAILS=$(grep -c '\[FAIL\]' "${GC2026_ROOT}/output/overnight_integrity.log" 2>/dev/null) || FAILS=0
    EVAL_OK=0
    if [[ -f "${OUT_DIR}/evaluation_full_n20k.json" ]]; then
      EVAL_OK=$("$PY" -c "
import json
s=json.load(open('${OUT_DIR}/evaluation_full_n20k.json')).get('summary',{})
print(1 if s.get('num_evaluated',0)>2000 else 0)
" 2>/dev/null || echo 0)
    fi

    TS=$(date +%Y%m%d_%H%M)
    ARCHIVE="${GC2026_ROOT}/output/overnight_${TS}_full_pipeline_bundle"
    mkdir -p "$ARCHIVE"
    cp -a "${OUT_DIR}"/evaluation_*.json "$ARCHIVE/" 2>/dev/null || true
    cp "${OUT_DIR}/manifest.json" "$ARCHIVE/" 2>/dev/null || true
    cp "${GC2026_ROOT}/output/full_pipeline_candidate_submission.tar.gz" "$ARCHIVE/" 2>/dev/null || true
    cp "${GC2026_ROOT}/output/cwipc_native/native_gate"*.json "$ARCHIVE/" 2>/dev/null || true
    cp "${GC2026_ROOT}/output/cwipc_native/stage1_production_tag.json" "$ARCHIVE/" 2>/dev/null || true
    cp "${GC2026_ROOT}/output/overnight_integrity.log" "$ARCHIVE/" 2>/dev/null || true

    STRICT_OK=0
    if [[ "$PLY" -eq "$TARGET_PLY" && "$FAILS" -eq 0 && "$EVAL_OK" -eq 1 ]]; then
      STRICT_OK=1
      echo "DONE $TS ply=$PLY" | tee "${GC2026_ROOT}/output/overnight_COMPLETE.marker"
      echo "[overnight] strict checks PASSED — shutdown in 60s"
      mark "phase4=done"
      mark "strict_pass=done"
      sleep 60
      shutdown -h now
    else
      echo "INCOMPLETE $TS ply=$PLY fails=$FAILS eval_ok=$EVAL_OK" \
        | tee "${GC2026_ROOT}/output/overnight_INCOMPLETE.marker"
      echo "[overnight] strict checks FAILED — not shutting down"
      mark "phase4=done"
      mark "strict_pass=fail"
    fi
  fi

  echo "[overnight] END $(date -Is)"
}

main "$@"
