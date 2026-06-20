#!/usr/bin/env bash
# S312 three-stage improvement plan: Stage1 SCAF + Stage2 polish + Stage3 SuperPC.
# TRACK=quick|stage1|stage2|stage3|val362|all
set -euo pipefail

GC2026_ROOT="${GC2026_ROOT:-/root/autodl-tmp/GC2026}"
SCRIPT_DIR="${GC2026_ROOT}/scripts"
STATE="${GC2026_ROOT}/output/remediation/s312.state"
LOG="${GC2026_ROOT}/output/remediation/s312_plan.log"

TRACK="${TRACK:-quick}"
STAGE1_JOBS="${STAGE1_JOBS:-4}"
QUICK_FRAMES="${QUICK_FRAMES:-15}"
MEDIUM_FRAMES="${MEDIUM_FRAMES:-50}"
POLL_SEC="${POLL_SEC:-20}"
MAX_WAIT_MIN="${MAX_WAIT_MIN:-45}"

VAL_CG="${GC2026_ROOT}/data/processed/val_cg_only_cgv2.txt"
STAGE1_CONFIG="${GC2026_ROOT}/output/remediation/stage1_config.json"
S1_SWEEP_JSON="${GC2026_ROOT}/output/remediation/s1_scaf_sweep.json"
S1_SWEEP_ROOT="${GC2026_ROOT}/output/remediation/s1_scaf_sweep"
S1_HYBRID_ROOT="${GC2026_ROOT}/output/remediation/s312_stage1_hybrid"
S1_WINNER_ROOT="${GC2026_ROOT}/output/remediation/s312_stage1_winner"
S2_SWEEP_JSON="${GC2026_ROOT}/output/remediation/s2_polish_sweep.json"
S2_ROOT="${GC2026_ROOT}/output/remediation/stage2_polish"
S3_ENH_ROOT="${GC2026_ROOT}/output/remediation/s312_stage3_enh"
GATE_DIR="${GC2026_ROOT}/output/remediation"

PY="${PY:-python3.12}"
export PY_OPEN3D="${PY_OPEN3D:-$PY}"

exec > >(tee -a "$LOG") 2>&1
mkdir -p "${GC2026_ROOT}/output/remediation"
touch "$STATE"

source "${SCRIPT_DIR}/env_setup.sh"
if [[ -f "${GC2026_ROOT}/output/cwipc_env.sh" ]]; then
  # shellcheck source=/dev/null
  source "${GC2026_ROOT}/output/cwipc_env.sh"
fi

mark() {
  echo "$1=$(date -Is)" >>"$STATE"
  echo "[s312] $1"
}

state_has() {
  grep -qE "^${1}=" "$STATE" 2>/dev/null
}

poll_gpu_infer() {
  local out_dir="$1"
  local expected="$2"
  local label="$3"
  local max_iter=$((MAX_WAIT_MIN * 60 / POLL_SEC))
  for ((i = 0; i < max_iter; i++)); do
    if ! pgrep -f "run_superpc_infer.py.*--out-dir ${out_dir}" >/dev/null 2>&1; then
      break
    fi
    local n
    n=$(find "$out_dir" -name '*.ply' 2>/dev/null | wc -l | tr -d ' ')
    echo "[s312] ${label} progress ply=${n}/${expected} (${i} polls)"
    sleep "$POLL_SEC"
  done
  if pgrep -f "run_superpc_infer.py.*--out-dir ${out_dir}" >/dev/null 2>&1; then
    echo "[s312] WARN: ${label} timeout after ${MAX_WAIT_MIN}m — killing workers"
    pkill -f "run_superpc_infer.py.*--out-dir ${out_dir}" 2>/dev/null || true
  fi
  find "$out_dir" -name '*.ply' 2>/dev/null | wc -l | tr -d ' '
}

build_recon_cg_list() {
  local recon_root="$1"
  local out_list="$2"
  "$PY" <<PY
import os
refs = open("${VAL_CG}").read().splitlines()
paths = []
for ref in refs:
    ref = ref.strip()
    if not ref:
        continue
    marker = "/UVG-CWI-DQPC/"
    if marker in ref:
        rel = ref.split(marker, 1)[1]
        out = os.path.join("${recon_root}", rel)
    else:
        seq = os.path.basename(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(ref)))))
        out = os.path.join("${recon_root}", seq, os.path.basename(ref))
    if os.path.isfile(out):
        paths.append(out)
open("${out_list}", "w").write("\n".join(paths) + ("\n" if paths else ""))
print(f"recon_list={len(paths)}")
PY
}

run_stage1_hybrid_full() {
  local out_root="$1"
  local max_frames="${2:-0}"
  rm -rf "$out_root"
  mkdir -p "$out_root"
  local extra=()
  if [[ "$max_frames" -gt 0 ]]; then
    extra=(--max-samples "$max_frames")
  fi
  "$PY" "${SCRIPT_DIR}/rgbd_to_cg.py" \
    --cg-list "$VAL_CG" \
    --out-root "$out_root" \
    --backend hybrid \
    --stage1-config "$STAGE1_CONFIG" \
    --multi-camera \
    --no-coord-corrections \
    --force \
    "${extra[@]}"
}

run_s1_scaf_sweep() {
  local n_per_seq="$1"
  local full_flag=()
  if [[ "$n_per_seq" -eq 0 ]]; then
    full_flag=(--full-seq)
  fi
  "$PY" "${SCRIPT_DIR}/run_s1_scaf_val362_sweep.py" \
    --cg-list "$VAL_CG" \
    --frames-per-seq "$n_per_seq" \
    "${full_flag[@]}" \
    --jobs "$STAGE1_JOBS" \
    --stage1-config "$STAGE1_CONFIG" \
    --out-json "$S1_SWEEP_JSON"
}

eval_gate() {
  local stage="$1"
  local recon_root="${2:-}"
  local enh_root="${3:-}"
  local max_frames="${4:-0}"
  local baseline_json="${5:-}"
  local out_json="${GATE_DIR}/s312_gate_stage${stage}.json"
  local extra=()
  if [[ "$max_frames" -gt 0 ]]; then
    extra=(--max-frames "$max_frames")
  fi
  if [[ -n "$baseline_json" && -f "$baseline_json" ]]; then
    extra+=(--baseline-json "$baseline_json")
  fi
  set +e
  if [[ "$stage" == "3" ]]; then
    "$PY" "${SCRIPT_DIR}/eval_s312_gate.py" \
      --stage 3 --enh-root "$enh_root" --recon-root "$recon_root" --cg-list "$VAL_CG" \
      "${extra[@]}" --out-json "$out_json"
  else
    "$PY" "${SCRIPT_DIR}/eval_s312_gate.py" \
      --stage "$stage" --recon-root "$recon_root" --cg-list "$VAL_CG" \
      "${extra[@]}" --out-json "$out_json"
  fi
  local rc=$?
  set -e
  return "$rc"
}

copy_winner_recon() {
  local tag="$1"
  local src="${S1_SWEEP_ROOT}/${tag}"
  if [[ ! -d "$src" ]]; then
    echo "[s312] winner dir missing: $src — using hybrid"
    return 1
  fi
  rm -rf "$S1_WINNER_ROOT"
  mkdir -p "$S1_WINNER_ROOT"
  cp -a "$src/." "$S1_WINNER_ROOT/"
  echo "[s312] stage1 winner copied from $tag"
}

resolve_stage1_recon() {
  if [[ -d "$S1_WINNER_ROOT" ]] && [[ "$(find "$S1_WINNER_ROOT" -name '*.ply' | wc -l)" -gt 0 ]]; then
    echo "$S1_WINNER_ROOT"
  else
    echo "$S1_HYBRID_ROOT"
  fi
}

resolve_stage2_recon() {
  if [[ -f "$S2_SWEEP_JSON" ]]; then
    local skip winner_root
    skip=$("$PY" -c "import json; d=json.load(open('${S2_SWEEP_JSON}')); print('1' if d.get('skip_stage2') else '0')")
    if [[ "$skip" == "1" ]]; then
      resolve_stage1_recon
      return
    fi
    winner_root=$("$PY" -c "import json; d=json.load(open('${S2_SWEEP_JSON}')); w=d.get('winner') or {}; print(w.get('out_root',''))")
    if [[ -n "$winner_root" && -d "$winner_root" ]]; then
      echo "$winner_root"
      return
    fi
  fi
  resolve_stage1_recon
}

run_stage3_superpc() {
  local cg_recon_root="$1"
  local recon_list="${cg_recon_root}/reconstructed_cg_list.txt"
  build_recon_cg_list "$cg_recon_root" "$recon_list"
  local expected
  expected=$(wc -l < "$recon_list" | tr -d ' ')
  if [[ "$expected" -eq 0 ]]; then
    echo "[s312] no recon frames for stage3 — skip"
    return 1
  fi
  rm -rf "$S3_ENH_ROOT"
  mkdir -p "$S3_ENH_ROOT"
  export CG_LIST="$recon_list"
  export OUT_DIR="$S3_ENH_ROOT"
  export CKPT="${GC2026_ROOT}/models/superpc_pretrained/kitti360_com.pth"
  export OUTPUT_MODE=blend_cg
  export BLEND_VOXEL_MM=3.0
  export USE_VISION=0
  ENH_PER_SEQ="${GC2026_ROOT}/output/enhancement_eval/recon_enh_config.json"
  if [[ -f "$ENH_PER_SEQ" ]]; then
    export ENH_PER_SEQ_CONFIG="$ENH_PER_SEQ"
  fi
  bash "${SCRIPT_DIR}/run_dual_gpu_infer.sh" || true
  poll_gpu_infer "$S3_ENH_ROOT" "$expected" "stage3"
}

# --- Quick: S1 SCAF 30f + gate ---
if [[ "$TRACK" == "quick" || "$TRACK" == "all" ]]; then
  if ! state_has "quick_s1=done"; then
    mark "quick_s1_begin"
    run_s1_scaf_sweep "$QUICK_FRAMES"
    mark "quick_s1=done"
  fi
  if ! state_has "gate_s1_quick=done"; then
    mark "gate_s1_quick_begin"
    local_recon="${S1_SWEEP_ROOT}/B0_hybrid_baseline"
    if eval_gate 1 "$local_recon" "" $((QUICK_FRAMES * 2)); then
      mark "gate_s1_quick=pass"
    else
      mark "gate_s1_quick=fail"
      echo "[s312] Stage1 quick gate FAIL — keeping PGDR hybrid baseline"
    fi
    mark "gate_s1_quick=done"
  fi
fi

# --- Stage1 medium/full ---
if [[ "$TRACK" == "stage1" || "$TRACK" == "val362" || "$TRACK" == "all" ]]; then
  gate_ok=0
  if state_has "gate_s1_quick=pass" || [[ "$TRACK" != "all" ]]; then
    gate_ok=1
  fi
  if [[ "$gate_ok" -eq 1 ]]; then
    if ! state_has "medium_s1=done"; then
      mark "medium_s1_begin"
      run_s1_scaf_sweep "$MEDIUM_FRAMES"
      local_recon="${S1_SWEEP_ROOT}/B0_hybrid_baseline"
      if eval_gate 1 "$local_recon" "" $((MEDIUM_FRAMES * 2)); then
        mark "gate_s1_medium=pass"
      else
        mark "gate_s1_medium=fail"
      fi
      mark "medium_s1=done"
    fi
    if state_has "gate_s1_medium=pass" || [[ "$TRACK" == "val362" ]]; then
      if ! state_has "full_s1=done"; then
        mark "full_s1_begin"
        run_s1_scaf_sweep 0
        run_stage1_hybrid_full "$S1_HYBRID_ROOT" 0
        winner_tag=$("$PY" -c "
import json, os
p='${S1_SWEEP_JSON}'
if not os.path.isfile(p): print('B0_hybrid_baseline'); raise SystemExit
d=json.load(open(p))
b=d.get('best_overall') or {}
print(b.get('tag','B0_hybrid_baseline'))
")
        if [[ "$winner_tag" != "B0_hybrid_baseline" ]]; then
          copy_winner_recon "$winner_tag" || true
        fi
        "$PY" "${SCRIPT_DIR}/select_stage1_backend.py" \
          --baseline-config "$STAGE1_CONFIG" \
          --out-config "$STAGE1_CONFIG" \
          --scaf-sweep "$S1_SWEEP_JSON" || true
        s1_eval=$(resolve_stage1_recon)
        eval_gate 1 "$s1_eval" "" 0 || mark "gate_s1_full=fail"
        state_has "gate_s1_full=fail" || mark "gate_s1_full=pass"
        mark "full_s1=done"
      fi
    fi
  fi
fi

# --- Stage2 polish ---
if [[ "$TRACK" == "stage2" || "$TRACK" == "val362" || "$TRACK" == "all" ]]; then
  if ! state_has "s2=done"; then
    if state_has "gate_s1_full=pass" || state_has "gate_s1_medium=pass" || state_has "full_s1=done"; then
      mark "s2_begin"
      s1_root=$(resolve_stage1_recon)
      "$PY" "${SCRIPT_DIR}/run_s2_polish_sweep.py" \
        --recon-root "$s1_root" \
        --cg-list "$VAL_CG" \
        --sweep-root "$S2_ROOT" \
        --out-json "$S2_SWEEP_JSON"
      s2_root=$(resolve_stage2_recon)
      eval_gate 2 "$s2_root" "" 0 "${GATE_DIR}/s312_gate_stage1.json" \
        && mark "gate_s2=pass" || mark "gate_s2=skip"
      mark "s2=done"
    else
      echo "[s312] Stage1 gate not passed — skip Stage2"
      mark "s2=skipped"
    fi
  fi
fi

# --- Stage3 SuperPC ---
if [[ "$TRACK" == "stage3" || "$TRACK" == "val362" || "$TRACK" == "all" ]]; then
  if ! state_has "s3=done"; then
    mark "s3_begin"
    cg_root=$(resolve_stage2_recon)
    echo "[s312] Stage3 input CG root: $cg_root"
    if command -v nvidia-smi >/dev/null 2>&1; then
      run_stage3_superpc "$cg_root"
      eval_gate 3 "$cg_root" "$S3_ENH_ROOT" 0 && mark "gate_s3=pass" || mark "gate_s3=fail"
    else
      echo "[s312] no GPU — skip Stage3 infer"
      mark "gate_s3=skipped"
    fi
    mark "s3=done"
  fi
fi

mark "plan_done"
echo "[s312] TRACK=${TRACK} complete — log=$LOG state=$STATE"
