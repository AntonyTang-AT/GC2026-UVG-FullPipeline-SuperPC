#!/usr/bin/env bash
# Autonomous Full Pipeline plan with parallel CPU/GPU tracks.
# Stage1: Open3D + PNG from local ROS .bag (no RGBD zip download).
# Naming: S312 plan uses Stage1=recon, Stage2=polish, Stage3=SuperPC; this script's
# "Stage2" in state/logs = SuperPC (alias of S312 Stage3). See run_s312_improvement_plan.sh.
set -euo pipefail

GC2026_ROOT="${GC2026_ROOT:-/root/autodl-tmp/GC2026}"
LOG="${GC2026_ROOT}/output/full_pipeline_plan.log"
STATE="${GC2026_ROOT}/output/full_pipeline_plan.state"
LOCK="${GC2026_ROOT}/output/full_pipeline_plan.lock"
FULL_EXPORT_DONE="${GC2026_ROOT}/output/.export_full.done"
FULL_EXPORT_PID="${GC2026_ROOT}/output/.plan_full_export.pid"
FULL_STAGE1_PID="${GC2026_ROOT}/output/.plan_full_stage1.pid"
FULL_STAGE1_DONE="${GC2026_ROOT}/output/.full_stage1.done"
PREP_DONE="${GC2026_ROOT}/output/.plan_prep.done"
STAGE1_CD_MAX_MM="${STAGE1_CD_MAX_MM:-40.0}"
MIN_DISK_GB="${MIN_DISK_GB:-30}"
STAGE1_JOBS="${STAGE1_JOBS:-4}"
EXPORT_JOBS_GPU_PHASE="${EXPORT_JOBS_GPU_PHASE:-6}"
VAL_SEQS="TicTacToe,VictoryHeart"
TARGET_PNG_COUNT="${TARGET_PNG_COUNT:-2155}"
MIN_FULL_CG_FRAMES="${MIN_FULL_CG_FRAMES:-2000}"

exec > >(tee -a "$LOG") 2>&1

mark() {
  echo "$1=$(date -Is)" >>"$STATE"
  echo "[plan] state: $1"
}

state_has() {
  local key="$1"
  grep -qE "^${key}=" "$STATE" 2>/dev/null || grep -qxF "$key" "$STATE" 2>/dev/null
}

avail_disk_gb() {
  df -BG /root/autodl-tmp 2>/dev/null | awk 'NR==2{gsub(/G/,"",$4); print $4}' || echo 0
}

png_count() {
  find "${GC2026_ROOT}/data" -path '*/RGBD/color/15fps/*.png' 2>/dev/null | wc -l
}

map_rgbd_pairs_for_list() {
  local cg_list="$1"
  python3 <<PY
import subprocess, sys
cg_list = "$cg_list"
seqs = sorted({ln.split("/UVG-CWI-DQPC/")[1].split("/")[0] for ln in open(cg_list) if "/UVG-CWI-DQPC/" in ln})
if seqs:
    subprocess.check_call([
        sys.executable,
        "${GC2026_ROOT}/scripts/map_rgbd_pairs.py",
        "--sequences", *seqs,
    ])
    print("[plan] rgbd_pairs mapped for", seqs)
PY
}

ensure_rosbag_export() {
  local cg_list="$1"
  echo "[plan] export RGBD PNG from local .bag cg_list=$cg_list jobs=${EXPORT_JOBS:-8}"
  python3 "${GC2026_ROOT}/scripts/export_rosbag_rgbd.py" \
    --cg-list "$cg_list" \
    --cg-version v2 \
    --frame-map-mode even \
    --jobs "${EXPORT_JOBS:-8}"
  map_rgbd_pairs_for_list "$cg_list"
}

setup_stage1_backend() {
  local winner_json="${GC2026_ROOT}/output/remediation/stage1_winner.json"
  local stage1_cfg="${GC2026_ROOT}/output/remediation/stage1_config.json"
  local backend="hybrid"
  if [[ ! -f "$stage1_cfg" && -f "$winner_json" ]]; then
    backend=$(python3 -c "import json; w=json.load(open('$winner_json')); print(w.get('winner') or 'open3d')")
  fi
  if state_has "backend=${backend}"; then
    export RGBD_TO_CG_BACKEND="$backend"
    return 0
  fi
  echo "backend=${backend}" >>"$STATE"
  echo "source=pgdr_hybrid" >>"$STATE"
  export RGBD_TO_CG_BACKEND="$backend"
  echo "[plan] Stage1 backend=${backend}"
}

load_backend() {
  local winner_json="${GC2026_ROOT}/output/remediation/stage1_winner.json"
  if [[ -f "$winner_json" ]]; then
    export RGBD_TO_CG_BACKEND=$(python3 -c "import json; w=json.load(open('$winner_json')); print(w.get('winner') or 'open3d')")
  else
    export RGBD_TO_CG_BACKEND="${RGBD_TO_CG_BACKEND:-open3d}"
  fi
}

wait_full_export() {
  if state_has "export_full=done" || [[ -f "$FULL_EXPORT_DONE" ]]; then
    mark "export_full=done"
    return 0
  fi
  if [[ -f "$FULL_EXPORT_PID" ]]; then
    local pid
    pid=$(cat "$FULL_EXPORT_PID")
    if kill -0 "$pid" 2>/dev/null; then
      echo "[plan] waiting for background full export pid=$pid"
      wait "$pid" 2>/dev/null || true
    fi
  fi
  local n
  n=$(png_count)
  while [[ "$n" -lt "$TARGET_PNG_COUNT" ]]; do
    echo "[plan] export progress png=$n / $TARGET_PNG_COUNT"
    sleep 30
    n=$(png_count)
  done
  touch "$FULL_EXPORT_DONE"
  mark "export_full=done"
}

start_full_export_background() {
  if state_has "export_full=done" || [[ -f "$FULL_EXPORT_DONE" ]]; then
    mark "export_full=done"
    return 0
  fi
  if [[ -f "$FULL_EXPORT_PID" ]]; then
    local pid
    pid=$(cat "$FULL_EXPORT_PID")
    if kill -0 "$pid" 2>/dev/null; then
      echo "[plan] full export already running pid=$pid"
      return 0
    fi
  fi
  local cg_all="${GC2026_ROOT}/data/processed/all_cg_only_cgv2.txt"
  echo "[plan] starting background full export (all sequences)"
  (
    set -euo pipefail
    EXPORT_JOBS="${EXPORT_JOBS_GPU_PHASE}" ensure_rosbag_export "$cg_all"
    touch "$FULL_EXPORT_DONE"
  ) >>"${GC2026_ROOT}/output/plan_full_export.log" 2>&1 &
  echo $! >"$FULL_EXPORT_PID"
  echo "[plan] background full export pid=$(cat "$FULL_EXPORT_PID")"
}

run_stage1_one_sequence() {
  local seq="$1"
  local cg_all="$2"
  local out_root="$3"
  local seq_list="${GC2026_ROOT}/output/_plan_cg_${seq}.txt"
  grep "/${seq}/" "$cg_all" >"$seq_list" || true
  if [[ ! -s "$seq_list" ]]; then
    echo "[plan] Stage1 skip empty list seq=$seq"
    return 0
  fi
  echo "[plan] Stage1 sequence=$seq"
  local stage1_cfg="${GC2026_ROOT}/output/remediation/stage1_config.json"
  local backend="${RGBD_TO_CG_BACKEND:-hybrid}"
  local extra=(--backend "$backend" --frame-map-mode even)
  if [[ -f "$stage1_cfg" ]]; then
    extra+=(--stage1-config "$stage1_cfg")
  fi
  python3.12 "${GC2026_ROOT}/scripts/rgbd_to_cg.py" \
    --cg-list "$seq_list" \
    --out-root "$out_root" \
    "${extra[@]}"
}

merge_full_reconstructed_list() {
  local cg_all="$1"
  local out_root="$2"
  local recon_list="$3"
  local val_root="$4"
  python3 <<PY
import os, sys
cg_list = "$cg_all"
out_root = "$out_root"
recon_list = "$recon_list"
val_root = "$val_root"
val_seqs = set("$VAL_SEQS".split(","))
with open(cg_list) as f:
    refs = [ln.strip() for ln in f if ln.strip()]
paths = []
for ref in refs:
    seq = os.path.basename(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(ref)))))
    fname = os.path.basename(ref)
    out = os.path.join(out_root, seq, fname)
    val_out = os.path.join(val_root, seq, fname)
    if os.path.isfile(out):
        paths.append(out)
    elif seq in val_seqs and os.path.isfile(val_out):
        paths.append(val_out)
with open(recon_list, "w") as f:
    f.write("\n".join(paths) + ("\n" if paths else ""))
print(f"[plan] full reconstructed: {len(paths)} / {len(refs)}")
if len(paths) < int("${MIN_FULL_CG_FRAMES}"):
    sys.exit("Too few reconstructed frames for full pipeline")
PY
}

run_full_stage1_parallel() {
  load_backend
  local cg_all="${GC2026_ROOT}/data/processed/all_cg_only_cgv2.txt"
  local out_root="${GC2026_ROOT}/output/full_pipeline_cg"
  local val_root="${GC2026_ROOT}/output/full_pipeline_val_cg"
  local recon_list="${out_root}/reconstructed_cg_list.txt"
  mkdir -p "$out_root"

  # shellcheck source=/dev/null
  source "${GC2026_ROOT}/output/cwipc_env.sh"
  export UVG_CG_VERSION=v2

  wait_full_export

  python3 <<PY > "${GC2026_ROOT}/output/_plan_sequences.txt"
import json
data = json.load(open("${GC2026_ROOT}/data/raw/UVG-CWI-DQPC.json"))
val = set("$VAL_SEQS".split(","))
for s in data["sequences"]:
    name = s["sequence"]
    if name not in val:
        print(name)
PY

  map_rgbd_pairs_for_list "$cg_all"

  echo "[plan] Stage1 parallel jobs=${STAGE1_JOBS} (non-val sequences)"
  export GC2026_ROOT cg_all out_root
  export -f run_stage1_one_sequence
  # shellcheck disable=SC2016
  xargs -P "$STAGE1_JOBS" -I{} bash -c 'run_stage1_one_sequence "$1" "$cg_all" "$out_root"' _ {} \
    < "${GC2026_ROOT}/output/_plan_sequences.txt"

  merge_full_reconstructed_list "$cg_all" "$out_root" "$recon_list" "$val_root"
  touch "$FULL_STAGE1_DONE"
  mark "phase3=done"
}

start_full_stage1_background() {
  if state_has "phase3=done" || [[ -f "$FULL_STAGE1_DONE" ]]; then
    mark "phase3=done"
    return 0
  fi
  if [[ -f "$FULL_STAGE1_PID" ]]; then
    local pid
    pid=$(cat "$FULL_STAGE1_PID")
    if kill -0 "$pid" 2>/dev/null; then
      echo "[plan] full Stage1 already running pid=$pid"
      return 0
    fi
  fi
  echo "[plan] starting background full Stage1"
  (
    run_full_stage1_parallel
  ) >>"${GC2026_ROOT}/output/plan_full_stage1.log" 2>&1 &
  echo $! >"$FULL_STAGE1_PID"
  echo "[plan] background full Stage1 pid=$(cat "$FULL_STAGE1_PID")"
}

wait_full_stage1() {
  if state_has "phase3=done" || [[ -f "$FULL_STAGE1_DONE" ]]; then
    mark "phase3=done"
    return 0
  fi
  if [[ -f "$FULL_STAGE1_PID" ]]; then
    local pid
    pid=$(cat "$FULL_STAGE1_PID")
    if kill -0 "$pid" 2>/dev/null; then
      echo "[plan] waiting for background full Stage1 pid=$pid"
      wait "$pid" 2>/dev/null || {
        echo "[plan] WARN: background Stage1 exited non-zero — retrying synchronously"
        run_full_stage1_parallel
        return 0
      }
    fi
  fi
  if [[ ! -f "$FULL_STAGE1_DONE" ]]; then
    echo "[plan] WARN: Stage1 background missing done marker — running synchronously"
    run_full_stage1_parallel
  else
    mark "phase3=done"
  fi
}

start_prep_background() {
  if state_has "prep=done" || [[ -f "$PREP_DONE" ]]; then
    mark "prep=done"
    return 0
  fi
  echo "[plan] starting background submission prep"
  (
    bash "${GC2026_ROOT}/scripts/prepare_submission_repo.sh" || true
    # shellcheck source=/dev/null
    source "${GC2026_ROOT}/scripts/env_setup.sh"
    python "${GC2026_ROOT}/scripts/generate_status_report.py" || true
    touch "$PREP_DONE"
  ) >>"${GC2026_ROOT}/output/plan_prep.log" 2>&1 &
  echo "[plan] background prep pid=$!"
}

wait_prep() {
  if [[ -f "$PREP_DONE" ]]; then
    mark "prep=done"
    return 0
  fi
  # Prep is optional; do not block long.
  sleep 2
  if [[ -f "$PREP_DONE" ]]; then
    mark "prep=done"
  fi
}

run_stage2_and_manifest() {
  local recon_list="$1"
  local out_dir="$2"
  local gate_json="${GC2026_ROOT}/output/val_grid/gate_decision.json"

  # shellcheck source=/dev/null
  source "${GC2026_ROOT}/scripts/env_setup.sh"
  export CG_LIST="$recon_list"
  export OUT_DIR="$out_dir"
  export ENH_ADAPTIVE_BLEND=0
  local per_seq_cfg="${GC2026_ROOT}/output/enhancement_eval/per_sequence_enh_config.json"
  local recon_cfg="${GC2026_ROOT}/output/enhancement_eval/recon_enh_config.json"
  if [[ -f "$recon_cfg" ]]; then
    export ENH_PER_SEQ_CONFIG="$recon_cfg"
  elif [[ -f "$per_seq_cfg" ]]; then
    export ENH_PER_SEQ_CONFIG="$per_seq_cfg"
  fi
  local winner_json="${GC2026_ROOT}/output/remediation/stage1_winner.json"
  if [[ -f "$winner_json" ]]; then
    tier=$(python3 -c "import json; w=json.load(open('$winner_json')); print(w.get('tier',''))")
    if [[ "$tier" == "passthrough_recon" ]]; then
      export PASSTHROUGH_RECON=1
    fi
  fi

  if [[ -f "$gate_json" ]]; then
    eval "$(python3 -c "
import json, os
g=json.load(open('$gate_json'))
c=g.get('best_config',{})
ckpt=os.path.join('$GC2026_ROOT', 'models/superpc_pretrained', c.get('checkpoint','kitti360_com.pth'))
print(f'export CKPT={ckpt}')
print(f'export OUTPUT_MODE={c.get(\"output_mode\",\"blend_cg\")}')
print(f'export BLEND_VOXEL_MM={c.get(\"blend_voxel_mm\",3.0)}')
print(f'export USE_VISION={c.get(\"use_vision\",0)}')
")"
  fi

  bash "${GC2026_ROOT}/scripts/run_dual_gpu_infer.sh"
  local expected
  expected=$(wc -l < "$recon_list")
  while pgrep -f "run_superpc_infer.py.*--out-dir ${out_dir}" >/dev/null; do
    local n
    n=$(find "$out_dir" -name '*.ply' 2>/dev/null | wc -l)
    echo "[plan] Stage2 progress ply=$n / $expected"
    sleep 60
  done

  python "${GC2026_ROOT}/scripts/make_submission.py" \
    --enhanced-dir "$out_dir" \
    --processing-track "Full Pipeline" \
    --title "UVG-CWI-DQPC GC2026 Full Pipeline SuperPC" \
    --post-processing "$gate_json" \
    --cg-version "${UVG_CG_VERSION:-v2}" \
    --cg-source "reconstructed" \
    --pipeline-notes "RGBD -> rgbd_to_cg (${RGBD_TO_CG_BACKEND:-open3d}) -> SuperPC blend enhancement"
}

run_post_soft() {
  local out_dir="$1"
  local label="$2"
  echo "[plan] post ($label) OUT=$out_dir (soft-fail)"
  if OUT_DIR="$out_dir" EVAL_DEVICE=cpu bash "${GC2026_ROOT}/scripts/post_full_pipeline.sh"; then
    echo "[plan] post ($label) OK"
  else
    echo "[plan] WARN: post ($label) failed — continuing plan"
  fi
}

phase0_preflight() {
  if state_has "phase0=done"; then return 0; fi
  echo "[plan] ===== Phase 0: preflight ====="
  bash "${GC2026_ROOT}/scripts/check_integrity.sh" || true
  # shellcheck source=/dev/null
  source "${GC2026_ROOT}/output/cwipc_env.sh"
  /usr/local/libexec/cwipc/cwipc_realsense2_install_check
  python3 "${GC2026_ROOT}/scripts/test_transform_matrix.py"
  python3 "${GC2026_ROOT}/scripts/test_frame_playback_map.py"
  local gb
  gb=$(avail_disk_gb)
  echo "[plan] available disk: ${gb}GB (need >= ${MIN_DISK_GB}GB)"
  if [[ "$gb" -lt "$MIN_DISK_GB" ]]; then
    echo "[plan] ERROR: insufficient disk"
    exit 1
  fi
  pip install -q rosbags 2>/dev/null || true
  mark "phase0=done"
}

phase1_val_stage1() {
  if state_has "phase1=done"; then return 0; fi
  echo "[plan] ===== Phase 1: val Stage1 (362 frames) ====="
  load_backend
  local val_cg="${GC2026_ROOT}/data/processed/val_cg_only_cgv2.txt"
  ensure_rosbag_export "$val_cg"
  # shellcheck source=/dev/null
  source "${GC2026_ROOT}/output/cwipc_env.sh"
  export UVG_CG_VERSION=v2
  export RGBD_TO_CG_BACKEND
  export SEQ_FILTER="$VAL_SEQS"
  bash "${GC2026_ROOT}/scripts/run_stage1_rgbd_only.sh"

  python3 <<PY || true
import json
gate = "${GC2026_ROOT}/output/cg_recon_eval/phase2_rgbd_gate.json"
cmp = "${GC2026_ROOT}/output/cg_recon_eval/val_compare_cgv2.json"
if __import__("os").path.isfile(gate):
    g = json.load(open(gate))
    if g.get("reconstructed", 0) < 300:
        print(f"[plan] WARN: only {g.get('reconstructed')} val frames reconstructed")
if __import__("os").path.isfile(cmp):
    mean_cd = json.load(open(cmp))["summary"]["mean_cd_l1"]
    print(f"[plan] val mean Chamfer(recon, CGv2)={mean_cd:.2f} mm (gate {${STAGE1_CD_MAX_MM}})")
    if mean_cd > float("${STAGE1_CD_MAX_MM}"):
        print("[plan] WARN: Stage1 quality above gate — continuing anyway")
PY
  mark "phase1=done"
}

phase2_val_e2e() {
  if state_has "phase2=done"; then return 0; fi
  echo "[plan] ===== Phase 2: val Stage2 (+ parallel full Stage1) + post ====="
  local recon_list="${GC2026_ROOT}/output/full_pipeline_val_cg/reconstructed_cg_list.txt"
  local out_dir="${GC2026_ROOT}/output/full_pipeline_val_candidate"
  if [[ ! -s "$recon_list" ]]; then
    echo "[plan] ERROR: missing $recon_list"
    exit 1
  fi

  start_full_export_background
  start_full_stage1_background
  start_prep_background

  run_stage2_and_manifest "$recon_list" "$out_dir"

  wait_full_stage1
  run_post_soft "$out_dir" "val"
  mark "phase2=done"
}

phase3_full_stage1() {
  if state_has "phase3=done"; then return 0; fi
  echo "[plan] ===== Phase 3: full Stage1 (ensure complete) ====="
  wait_full_export
  wait_full_stage1
  if ! state_has "phase3=done"; then
    run_full_stage1_parallel
  fi
}

phase4_full_e2e() {
  if state_has "phase4=done"; then return 0; fi
  echo "[plan] ===== Phase 4: full Stage2 + post + submission ====="
  local recon_list="${GC2026_ROOT}/output/full_pipeline_cg/reconstructed_cg_list.txt"
  local out_dir="${GC2026_ROOT}/output/full_pipeline_candidate"
  if [[ ! -s "$recon_list" ]]; then
    echo "[plan] ERROR: missing $recon_list"
    exit 1
  fi
  run_stage2_and_manifest "$recon_list" "$out_dir"
  run_post_soft "$out_dir" "full"
  wait_prep
  if [[ ! -f "$PREP_DONE" ]]; then
    bash "${GC2026_ROOT}/scripts/prepare_submission_repo.sh" || true
    # shellcheck source=/dev/null
    source "${GC2026_ROOT}/scripts/env_setup.sh"
    python "${GC2026_ROOT}/scripts/generate_status_report.py" || true
    touch "$PREP_DONE"
    mark "prep=done"
  fi
  bash "${GC2026_ROOT}/scripts/check_integrity.sh" || true
  mark "phase4=done"
}

main() {
  mkdir -p "${GC2026_ROOT}/output"
  touch "$STATE"
  exec 9>"$LOCK"
  if ! flock -n 9; then
    echo "[plan] another plan runner is active — exit"
    exit 0
  fi

  echo "[plan] START $(date -Is)"
  echo "[plan] log=$LOG state=$STATE"
  echo "[plan] parallel: export_bg + stage1_bg during val GPU | STAGE1_JOBS=${STAGE1_JOBS}"

  phase0_preflight
  setup_stage1_backend

  if state_has "phase1=done" && ! state_has "export_full=done" && [[ ! -f "$FULL_EXPORT_DONE" ]]; then
    n=$(png_count)
    if [[ "$n" -ge "$TARGET_PNG_COUNT" ]]; then
      touch "$FULL_EXPORT_DONE"
      mark "export_full=done"
      echo "[plan] resume: PNG already complete ($n)"
    else
      start_full_export_background
    fi
  fi

  phase1_val_stage1

  if ! state_has "export_full=done" && [[ ! -f "$FULL_EXPORT_DONE" ]]; then
    start_full_export_background
  elif [[ -f "$FULL_EXPORT_DONE" ]]; then
    mark "export_full=done"
  fi

  phase2_val_e2e
  phase3_full_stage1
  phase4_full_e2e

  echo "[plan] ALL DONE $(date -Is)"
}

main "$@"
