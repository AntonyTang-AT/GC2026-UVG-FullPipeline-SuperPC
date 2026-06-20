#!/usr/bin/env bash
# PGDR parallel improvement plan (Reconstruction-first).
set -euo pipefail

GC2026_ROOT="${GC2026_ROOT:-/root/autodl-tmp/GC2026}"
SCRIPT_DIR="${GC2026_ROOT}/scripts"
STATE="${GC2026_ROOT}/output/remediation/pgdr_improve.state"
LOG="${GC2026_ROOT}/output/remediation/pgdr_improve.log"
STAGE1_JOBS="${STAGE1_JOBS:-4}"
TRACK="${TRACK:-all}"
GATE_OVERALL_MM="${GATE_OVERALL_MM:-700}"
GATE_VH_MM="${GATE_VH_MM:-850}"
BASELINE_CD="${BASELINE_CD:-761.4}"

STAGE1_CONFIG="${GC2026_ROOT}/output/remediation/stage1_config.json"
VAL_CG="${GC2026_ROOT}/data/processed/val_cg_only_cgv2.txt"
VAL_PAIRS="${GC2026_ROOT}/data/processed/val_pairs_cgv2.txt"
CG_ALL="${GC2026_ROOT}/data/processed/all_cg_only_cgv2.txt"
VAL_ROOT="${GC2026_ROOT}/output/remediation/stage1_pgdr_val362"
FULL_ROOT="${GC2026_ROOT}/output/remediation/stage1_pgdr_full"
VAL_COMPARE="${GC2026_ROOT}/output/remediation/stage1_pgdr_val362_compare.json"
VAL_SEQS="TicTacToe,VictoryHeart"

exec >>"$LOG" 2>&1
echo "[pgdr_plan] ===== $(date -Is) TRACK=$TRACK ====="
mkdir -p "${GC2026_ROOT}/output/remediation"
touch "$STATE"

mark() {
  echo "$1=$(date -Is)" >>"$STATE"
  echo "[pgdr_plan] mark $1"
}

state_has() {
  grep -qE "^${1}=" "$STATE" 2>/dev/null
}

source_envs() {
  # shellcheck source=/dev/null
  source "${SCRIPT_DIR}/env_setup.sh" 2>/dev/null || true
  if [[ -f "${GC2026_ROOT}/output/cwipc_env.sh" ]]; then
    # shellcheck source=/dev/null
    source "${GC2026_ROOT}/output/cwipc_env.sh"
  fi
  export PY_OPEN3D="${PY_OPEN3D:-python3.12}"
  export PY_CWIPC="${PY_CWIPC:-python3.12}"
}

start_enh_background() {
  if state_has "enh_bg=done"; then return 0; fi
  if [[ "${RUN_ENH_BG:-1}" != "1" ]]; then return 0; fi
  echo "[pgdr_plan] Enhancement background (TRACK=enh)"
  nohup bash -c "TRACK=enh ${SCRIPT_DIR}/run_remediation_plan.sh" \
    >> "${GC2026_ROOT}/output/remediation/enh_bg.log" 2>&1 &
  mark "enh_bg=started"
}

phase_probe() {
  if state_has "probe=done"; then return 0; fi
  echo "[pgdr_plan] Phase0: parallel probe"
  source_envs
  STAGE1_JOBS="$STAGE1_JOBS" bash "${SCRIPT_DIR}/run_pgdr_probe_parallel.sh"
  python3 "${SCRIPT_DIR}/probe_val362_experiments.py" || true
  mark "probe=done"
}

phase_config() {
  if state_has "config=done"; then return 0; fi
  echo "[pgdr_plan] Phase1: select stage1_config"
  python3 "${SCRIPT_DIR}/select_stage1_backend.py"
  mark "config=done"
}

run_hybrid_rebuild() {
  local cg_list="$1"
  local out_root="$2"
  source_envs
  rm -rf "$out_root"
  mkdir -p "$out_root"
  "$PY_OPEN3D" "${SCRIPT_DIR}/rgbd_to_cg.py" \
    --cg-list "$cg_list" \
    --out-root "$out_root" \
    --backend hybrid \
    --stage1-config "$STAGE1_CONFIG" \
    --force
}

compare_recon() {
  local recon_root="$1"
  local out_json="$2"
  local max_samples="${3:-0}"
  source_envs
  extra=()
  if [[ "$max_samples" -gt 0 ]]; then
    extra=(--max-samples "$max_samples")
  fi
  "$PYTHON" "${SCRIPT_DIR}/compare_reconstructed_cg.py" \
    --recon-root "$recon_root" \
    --pairs-file "$VAL_PAIRS" \
    --official-version v2 \
    --n-samples 5000 \
    --device cpu \
    --out-json "$out_json" \
    "${extra[@]}"
}

phase_val362() {
  if state_has "val362=done"; then return 0; fi
  echo "[pgdr_plan] Phase1B: Val362 hybrid rebuild + gate"
  run_hybrid_rebuild "$VAL_CG" "$VAL_ROOT"
  compare_recon "$VAL_ROOT" "$VAL_COMPARE" 0

  python3 <<PY
import json, sys
cmp = json.load(open("$VAL_COMPARE"))
records = cmp.get("records", [])
overall = cmp["summary"]["mean_cd_l1"]
by = {}
for r in records:
    by.setdefault(r["sequence"], []).append(r["cd_l1"])
vh = sum(by.get("VictoryHeart", [9999])) / max(len(by.get("VictoryHeart", [1])), 1)
print(f"[pgdr_plan] gate overall={overall:.1f} VH={vh:.1f} (need <{${GATE_OVERALL_MM}} / <{${GATE_VH_MM}})")
gate = {"overall": overall, "victoryheart": vh, "pass": overall < float("${GATE_OVERALL_MM}") and vh < float("${GATE_VH_MM}")}
json.dump(gate, open("${GC2026_ROOT}/output/remediation/pgdr_val362_gate.json", "w"), indent=2)
if not gate["pass"]:
    print("[pgdr_plan] WARN: gate not passed — continuing to full rebuild anyway")
PY
  mark "val362=done"
}

run_full_one_sequence() {
  local seq="$1"
  local out_root="$2"
  local seq_list="${GC2026_ROOT}/output/remediation/_pgdr_cg_${seq}.txt"
  grep "/${seq}/" "$CG_ALL" >"$seq_list" || true
  if [[ ! -s "$seq_list" ]]; then
    echo "[pgdr_plan] skip empty seq=$seq"
    return 0
  fi
  echo "[pgdr_plan] full Stage1 seq=$seq"
  "$PY_OPEN3D" "${SCRIPT_DIR}/rgbd_to_cg.py" \
    --cg-list "$seq_list" \
    --out-root "$out_root" \
    --backend hybrid \
    --stage1-config "$STAGE1_CONFIG" \
    --force
}

phase_full() {
  if state_has "full=done"; then return 0; fi
  echo "[pgdr_plan] Phase2: full 2155 hybrid (xargs -P ${STAGE1_JOBS})"
  source_envs
  mkdir -p "$FULL_ROOT"

  # Val362 into full tree (copy/symlink paths)
  if [[ -d "$VAL_ROOT" ]]; then
    python3 <<PY
import os, shutil
val_root = "$VAL_ROOT"
full_root = "$FULL_ROOT"
for dirpath, _, files in os.walk(val_root):
    for fn in files:
        if not fn.endswith(".ply"):
            continue
        src = os.path.join(dirpath, fn)
        rel = os.path.relpath(src, val_root)
        dst = os.path.join(full_root, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if not os.path.isfile(dst):
            shutil.copy2(src, dst)
print("[pgdr_plan] merged val362 into full root")
PY
  fi

  python3 <<PY > "${GC2026_ROOT}/output/remediation/_pgdr_full_sequences.txt"
import json
val = set("$VAL_SEQS".split(","))
data = json.load(open("${GC2026_ROOT}/data/raw/UVG-CWI-DQPC.json"))
for s in data["sequences"]:
    if s["sequence"] not in val:
        print(s["sequence"])
PY

  export -f run_full_one_sequence
  export GC2026_ROOT SCRIPT_DIR STAGE1_CONFIG PY_OPEN3D FULL_ROOT CG_ALL
  xargs -P "$STAGE1_JOBS" -I{} bash -c 'run_full_one_sequence "$1" "$FULL_ROOT"' _ {} \
    < "${GC2026_ROOT}/output/remediation/_pgdr_full_sequences.txt"

  python3 <<PY
import os
cg_all = "$CG_ALL"
full_root = "$FULL_ROOT"
val_root = "$VAL_ROOT"
val_seqs = set("$VAL_SEQS".split(","))
paths = []
for ln in open(cg_all):
    ref = ln.strip()
    if not ref:
        continue
    seq = ref.split("/UVG-CWI-DQPC/")[1].split("/")[0]
    fname = os.path.basename(ref)
    for root in (full_root, val_root if seq in val_seqs else None):
        if not root:
            continue
        p = os.path.join(root, seq, fname)
        if os.path.isfile(p):
            paths.append(p)
            break
out = os.path.join(full_root, "reconstructed_cg_list.txt")
open(out, "w").write("\\n".join(paths) + ("\\n" if paths else ""))
print(f"[pgdr_plan] reconstructed_cg_list: {len(paths)} frames")
if len(paths) < 2000:
    raise SystemExit("Too few frames in full rebuild")
PY
  mark "full=done"
}

phase_validate() {
  if state_has "validate=done"; then return 0; fi
  echo "[pgdr_plan] Phase3: validate + report"
  source_envs

  compare_recon "$VAL_ROOT" "${GC2026_ROOT}/output/remediation/stage1_pgdr_full_val_sample.json" 50 || true

  python3 <<PY
import json, os
from datetime import datetime
from collections import defaultdict

root = "${GC2026_ROOT}/output/remediation"
baseline = float("${BASELINE_CD}")

def load(p):
    return json.load(open(p)) if os.path.isfile(p) else {}

val = load("$VAL_COMPARE")
summary = val.get("summary", {})
records = val.get("records", [])
by = defaultdict(list)
for r in records:
    by[r["sequence"]].append(r["cd_l1"])
per = {k: sum(v)/len(v) for k,v in by.items()}
overall = summary.get("mean_cd_l1")

lines = [
    "# PGDR Improvement Report",
    "",
    f"Generated: {datetime.utcnow().isoformat()}Z",
    "",
    "## Val362 vs baseline",
    "",
    f"| Metric | Baseline | Current | Delta |",
    f"|--------|----------|---------|-------|",
    f"| Overall CD (mm) | {baseline:.1f} | {overall:.1f} | {overall - baseline:+.1f} |" if overall else "| Overall | — | — | — |",
]
for seq in sorted(per):
    lines.append(f"| {seq} | — | {per[seq]:.1f} | — |")

gate = load(os.path.join(root, "pgdr_val362_gate.json"))
lines += ["", "## Gate", "", f"- Pass: {gate.get('pass', 'unknown')}", f"- Overall: {gate.get('overall')}", f"- VictoryHeart: {gate.get('victoryheart')}"]

probe = load(os.path.join(root, "probe_all_summary.json"))
if probe:
    lines += ["", "## Train sequence probe winners", ""]
    for row in probe.get("sequences", []):
        lines.append(f"- **{row.get('sequence')}**: {row.get('backend')} {row.get('transform_mode')} ds={row.get('depth_scale')} mc={row.get('multi_camera')} cd={row.get('mean_cd_l1')}")

out = os.path.join(root, "pgdr_improvement_report.md")
open(out, "w").write("\\n".join(lines) + "\\n")
print(f"[pgdr_plan] report -> {out}")
PY

  if [[ -f "${FULL_ROOT}/reconstructed_cg_list.txt" ]] && command -v nvidia-smi >/dev/null 2>&1; then
    if [[ "${RUN_STAGE2_SAMPLE:-0}" == "1" ]]; then
      head -20 "${FULL_ROOT}/reconstructed_cg_list.txt" > /tmp/pgdr_stage2_sample.txt
      CG_LIST=/tmp/pgdr_stage2_sample.txt \
        OUT_DIR="${GC2026_ROOT}/output/remediation/stage1_pgdr_stage2_sample" \
        OUTPUT_MODE=filter_cg \
        bash "${SCRIPT_DIR}/run_dual_gpu_infer.sh" || true
    fi
  fi

  mark "validate=done"
}

main() {
  case "$TRACK" in
    probe) phase_probe ;;
    config) phase_config ;;
    val362) phase_val362 ;;
    full) phase_full ;;
    validate) phase_validate ;;
    all)
      start_enh_background
      phase_probe
      phase_config
      phase_val362
      phase_full
      phase_validate
      ;;
    *)
      echo "Usage: TRACK=probe|config|val362|full|validate|all"
      exit 1
      ;;
  esac
  echo "[pgdr_plan] DONE TRACK=$TRACK $(date -Is)"
}

main "$@"
