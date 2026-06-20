#!/usr/bin/env bash
# GC2026 dual-track remediation orchestrator (Phase 2-3).
set -euo pipefail

GC2026_ROOT="${GC2026_ROOT:-/root/autodl-tmp/GC2026}"
STATE="${GC2026_ROOT}/output/remediation/remediation.state"
LOG="${GC2026_ROOT}/output/remediation/remediation.log"
STAGE1_JOBS="${STAGE1_JOBS:-4}"
TRACK="${TRACK:-both}"

exec > >(tee -a "$LOG") 2>&1
mkdir -p "${GC2026_ROOT}/output/remediation"
touch "$STATE"

mark() {
  echo "$1=$(date -Is)" >>"$STATE"
  echo "[remediation] $1"
}

state_has() {
  grep -qE "^${1}=" "$STATE" 2>/dev/null || grep -qxF "$1" "$STATE" 2>/dev/null
}

phase0_diagnose() {
  if state_has "phase0=done"; then return 0; fi
  echo "[remediation] ===== Phase 0: diagnose ====="
  python3 "${GC2026_ROOT}/scripts/diagnose_stage1.py" \
    --device cpu \
    --compare-samples 50 \
    --out-dir "${GC2026_ROOT}/output/remediation" \
    --run-sweep \
    --sweep-frames 20 \
    --run-cwipc-rebuild || true
  mark "phase0=done"
}

phase2_enh_rerun() {
  if state_has "phase2_enh=done"; then return 0; fi
  echo "[remediation] ===== Phase 2A: Enhancement Only rerun ====="
  TRACK=enhancement_only bash "${GC2026_ROOT}/scripts/rerun_per_seq_enh.sh"
  OUT_DIR="${GC2026_ROOT}/output/submission_candidate" EVAL_DEVICE=cpu \
    bash "${GC2026_ROOT}/scripts/post_submission_candidate.sh" || true
  mark "phase2_enh=done"
}

phase2_stage1_gate() {
  if state_has "phase2_stage1_gate=done"; then return 0; fi
  echo "[remediation] ===== Phase 2B: Stage1 val gate (cwipc vs open3d) ====="
  if [[ ! -f "${GC2026_ROOT}/output/remediation/stage1_winner.json" ]]; then
    python3 "${GC2026_ROOT}/scripts/diagnose_stage1.py" \
      --device cpu \
      --compare-samples 362 \
      --out-dir "${GC2026_ROOT}/output/remediation" \
      --run-cwipc-rebuild || true
  fi
  mark "phase2_stage1_gate=done"
}

phase2_stage1_full() {
  if state_has "phase2_stage1_full=done"; then return 0; fi
  echo "[remediation] ===== Phase 2C: full Stage1 rebuild ====="
  # shellcheck source=/dev/null
  source "${GC2026_ROOT}/scripts/env_setup.sh"
  if [[ -f "${GC2026_ROOT}/output/cwipc_env.sh" ]]; then
    # shellcheck source=/dev/null
    source "${GC2026_ROOT}/output/cwipc_env.sh"
  fi

  local backend="${RGBD_TO_CG_BACKEND:-hybrid}"
  local stage1_cfg="${GC2026_ROOT}/output/remediation/stage1_config.json"
  if [[ -f "$stage1_cfg" ]]; then
    backend="hybrid"
  elif [[ -f "${GC2026_ROOT}/output/remediation/stage1_winner.json" ]]; then
    backend=$(python3 -c "import json; w=json.load(open('${GC2026_ROOT}/output/remediation/stage1_winner.json')); print(w.get('winner','open3d'))")
  fi
  local frame_map="even"
  local depth_scale="5000"
  local transform_mode="seq_only"
  local multi_camera="0"
  local merge_voxel="3.0"
  if [[ "$backend" != "hybrid" && -f "${GC2026_ROOT}/output/remediation/stage1_winner.json" ]]; then
    eval "$(python3 -c "
import json
w=json.load(open('${GC2026_ROOT}/output/remediation/stage1_winner.json'))
print(f\"frame_map={w.get('frame_map_mode','even')}\")
print(f\"depth_scale={w.get('depth_scale',5000)}\")
print(f\"transform_mode={w.get('transform_mode','seq_only')}\")
print(f\"multi_camera={'1' if w.get('multi_camera') else '0'}\")
print(f\"merge_voxel={w.get('merge_voxel_mm',3.0)}\")
")"
  fi
  export RGBD_TO_CG_BACKEND="$backend"

  local cg_all="${GC2026_ROOT}/data/processed/all_cg_only_cgv2.txt"
  local val_cg="${GC2026_ROOT}/data/processed/val_cg_only_cgv2.txt"
  local out_root="${GC2026_ROOT}/output/full_pipeline_cg"
  local val_root="${GC2026_ROOT}/output/full_pipeline_val_cg"

  rm -rf "$out_root" "$val_root"
  mkdir -p "$out_root" "$val_root"

  export RGBD_TO_CG_BACKEND="$backend"
  echo "[remediation] Stage1 backend=$backend (PGDR hybrid uses stage1_config.json)"

  rgbd_extra=(--stage1-config "$stage1_cfg")
  if [[ "$backend" != "hybrid" ]]; then
    rgbd_extra=(--frame-map-mode "$frame_map" --depth-scale "$depth_scale" --transform-mode "$transform_mode"
      --stage1-config "$stage1_cfg")
    if [[ "$multi_camera" == "1" ]]; then
      rgbd_extra+=(--multi-camera --merge-voxel-mm "$merge_voxel")
    fi
  fi

  python3.12 "${GC2026_ROOT}/scripts/rgbd_to_cg.py" \
    --cg-list "$val_cg" \
    --out-root "$val_root" \
    --backend "$backend" \
    --force \
    "${rgbd_extra[@]}"

  python3 <<PY
import os, subprocess, sys
cg_all = "$cg_all"
out_root = "$out_root"
backend = "$backend"
stage1_cfg = "$stage1_cfg"
frame_map = "$frame_map"
depth_scale = "$depth_scale"
transform_mode = "$transform_mode"
multi_camera = "$multi_camera" == "1"
merge_voxel = "$merge_voxel"
gc = "$GC2026_ROOT"
val_seqs = set("TicTacToe,VictoryHeart".split(","))
seqs = sorted({ln.split("/UVG-CWI-DQPC/")[1].split("/")[0] for ln in open(cg_all) if "/UVG-CWI-DQPC/" in ln})
py = "python3.12"
for seq in seqs:
    if seq in val_seqs:
        continue
    seq_list = os.path.join(gc, "output/remediation", f"_cg_{seq}.txt")
    with open(seq_list, "w") as f:
        for ln in open(cg_all):
            ln = ln.strip()
            if f"/{seq}/" in ln:
                f.write(ln + "\\n")
    if os.path.getsize(seq_list) == 0:
        continue
    cmd = [
        py, os.path.join(gc, "scripts/rgbd_to_cg.py"),
        "--cg-list", seq_list, "--out-root", out_root,
        "--backend", backend, "--force",
        "--stage1-config", stage1_cfg,
    ]
    if backend != "hybrid":
        cmd += ["--frame-map-mode", frame_map, "--depth-scale", str(depth_scale), "--transform-mode", transform_mode]
        if multi_camera:
            cmd += ["--multi-camera", "--merge-voxel-mm", str(merge_voxel)]
    subprocess.check_call(cmd)
PY

  python3 <<PY
import os, sys
cg_all = "$cg_all"
out_root = "$out_root"
val_root = "$val_root"
recon_list = os.path.join(out_root, "reconstructed_cg_list.txt")
val_seqs = set("TicTacToe,VictoryHeart".split(","))
paths = []
for ln in open(cg_all):
    ref = ln.strip()
    if not ref:
        continue
    seq = ref.split("/UVG-CWI-DQPC/")[1].split("/")[0]
    fname = os.path.basename(ref)
    out = os.path.join(out_root, seq, fname)
    val_out = os.path.join(val_root, seq, fname)
    if os.path.isfile(out):
        paths.append(out)
    elif seq in val_seqs and os.path.isfile(val_out):
        paths.append(val_out)
with open(recon_list, "w") as f:
    f.write("\\n".join(paths) + ("\\n" if paths else ""))
print(f"[remediation] reconstructed {len(paths)} frames")
if len(paths) < 2000:
    sys.exit("Too few reconstructed frames")
PY

  python3 "${GC2026_ROOT}/scripts/compare_reconstructed_cg.py" \
    --recon-root "$val_root" \
    --pairs-file "${GC2026_ROOT}/data/processed/val_pairs_cgv2.txt" \
    --device cpu \
    --n-samples 5000 \
    --max-samples 50 \
    --out-json "${GC2026_ROOT}/output/remediation/stage1_full_val_sample.json" || true

  mark "phase2_stage1_full=done"
}

phase3_fp_stage2() {
  if state_has "phase3_fp=done"; then return 0; fi
  echo "[remediation] ===== Phase 3A: Full Pipeline Stage2 ====="
  TRACK=full_pipeline bash "${GC2026_ROOT}/scripts/rerun_per_seq_enh.sh"
  OUT_DIR="${GC2026_ROOT}/output/full_pipeline_candidate" EVAL_DEVICE=cpu \
    bash "${GC2026_ROOT}/scripts/post_full_pipeline.sh" || true
  mark "phase3_fp=done"
}

phase3_validate() {
  if state_has "phase3_validate=done"; then return 0; fi
  echo "[remediation] ===== Phase 3B/C: validate ====="
  python3 "${GC2026_ROOT}/scripts/evaluate_recon_pipeline.py" \
    --recon-list "${GC2026_ROOT}/output/full_pipeline_cg/reconstructed_cg_list.txt" \
    --enhanced-root "${GC2026_ROOT}/output/full_pipeline_candidate" \
    --device cpu \
    --max-samples 100 \
    --out-json "${GC2026_ROOT}/output/full_pipeline_candidate/evaluation_recon_pipeline_sample.json" \
    || true

  bash "${GC2026_ROOT}/scripts/check_integrity.sh" || true
  python3 "${GC2026_ROOT}/scripts/generate_status_report.py" || true
  bash "${GC2026_ROOT}/scripts/pack_submission.sh" "${GC2026_ROOT}/output/submission_candidate" || true

  python3 <<PY
import json, os
root = "$GC2026_ROOT"
def s(path, key="mean_improvement_cd_l1"):
    p = os.path.join(root, path)
    if not os.path.isfile(p):
        return None
    return json.load(open(p))["summary"].get(key)
print("=== remediation summary ===")
print("Enh val delta:", s("output/submission_candidate/evaluation_val_n20k.json"))
print("Enh full delta:", s("output/submission_candidate/evaluation_full_n20k.json"))
print("FP val delta (official baseline):", s("output/full_pipeline_candidate/evaluation_val_n20k.json"))
print("FP full delta (official baseline):", s("output/full_pipeline_candidate/evaluation_full_n20k.json"))
print("FP recon delta (sample):", s("output/full_pipeline_candidate/evaluation_recon_pipeline_sample.json"))
PY
  mark "phase3_validate=done"
}

main() {
  echo "[remediation] START $(date -Is) TRACK=$TRACK"
  case "$TRACK" in
    diagnose) phase0_diagnose ;;
    enh) phase2_enh_rerun ;;
    stage1_gate) phase2_stage1_gate ;;
    stage1_full) phase2_stage1_full ;;
    fp) phase3_fp_stage2 ;;
    validate) phase3_validate ;;
    all)
      phase0_diagnose
      phase2_enh_rerun &
      PID_ENH=$!
      phase2_stage1_gate
      wait "$PID_ENH" || true
      phase2_stage1_full
      phase3_fp_stage2
      phase3_validate
      ;;
    *)
      echo "Usage: TRACK=diagnose|enh|stage1_gate|stage1_full|fp|validate|all"
      exit 1
      ;;
  esac
  echo "[remediation] DONE $(date -Is)"
}

main "$@"
