#!/usr/bin/env bash
# Val362 N0 v2: merge sweep N0 + retry + SuperPC + eval (compare vs B1/B2 baselines).
set -euo pipefail

GC2026_ROOT="${GC2026_ROOT:-/root/autodl-tmp/GC2026}"
SCRIPT_DIR="${GC2026_ROOT}/scripts"
PY="${PY:-python3.12}"
TAG="${TAG:-N0_cwipc_official}"
RECON_ROOT="${RECON_ROOT:-${GC2026_ROOT}/output/cwipc_native/val362_n0_v2}"
ENH_ROOT="${ENH_ROOT:-${GC2026_ROOT}/output/cwipc_native/val362_n0_v2_enh}"
SWEEP_SRC="${GC2026_ROOT}/output/cwipc_native/val362_sweep/${TAG}"
VAL_CG="${GC2026_ROOT}/data/processed/val_cg_only_cgv2.txt"
VAL_PAIRS="${GC2026_ROOT}/data/processed/val_pairs_cgv2.txt"
BASELINE_RECON="${GC2026_ROOT}/output/remediation/stage1_pgdr_val362"
STAGE1_CONFIG="${GC2026_ROOT}/output/remediation/stage1_config.json"
LOG="${GC2026_ROOT}/output/cwipc_native/val362_n0_v2.log"
REPORT="${GC2026_ROOT}/output/cwipc_native/val362_n0_v2_report.json"
COMPARE_JSON="${GC2026_ROOT}/output/cwipc_native/val362_n0_v2_compare.json"
RECON_ENH_CONFIG="${GC2026_ROOT}/output/cwipc_native/val362_n0_v2_recon_enh_config.json"

exec > >(tee -a "$LOG") 2>&1
echo "[val362_n0_v2] START $(date -Is) tag=$TAG"

source "${SCRIPT_DIR}/env_setup.sh"
if [[ -f "${GC2026_ROOT}/output/cwipc_env.sh" ]]; then
  # shellcheck source=/dev/null
  source "${GC2026_ROOT}/output/cwipc_env.sh"
fi

# --- Stage1: merge N0 sweep + retry missing ---
rm -rf "$RECON_ROOT"
mkdir -p "$RECON_ROOT"
if [[ ! -d "$SWEEP_SRC" ]]; then
  echo "[val362_n0_v2] ERROR: missing sweep $SWEEP_SRC"
  exit 1
fi
echo "[val362_n0_v2] merge from $SWEEP_SRC"
rsync -a "$SWEEP_SRC/" "$RECON_ROOT/"

"$PY" "${SCRIPT_DIR}/retry_missing_recon.py" \
  --recon-root "$RECON_ROOT" \
  --cg-list "$VAL_CG" \
  --backend cwipc \
  --cwipc-filter-profile official \
  --baseline-recon-root "$BASELINE_RECON" || true

"$PY" <<PY
import os
refs = open("${VAL_CG}").read().splitlines()
paths = []
for ref in refs:
    ref = ref.strip()
    if not ref:
        continue
    seq = ref.split("/UVG-CWI-DQPC/")[1].split("/")[0]
    out = os.path.join("${RECON_ROOT}", seq, os.path.basename(ref))
    if os.path.isfile(out):
        paths.append(out)
lst = os.path.join("${RECON_ROOT}", "reconstructed_cg_list.txt")
open(lst, "w").write("\\n".join(paths) + ("\\n" if paths else ""))
print(f"[val362_n0_v2] recon frames={len(paths)}")
if len(paths) < 340:
    raise SystemExit("Too few val362 recon frames after retry")
PY

# --- Native gate (recon vs HE) ---
"$PY" "${SCRIPT_DIR}/eval_native_gate.py" \
  --recon-root "$RECON_ROOT" \
  --baseline-recon-root "$BASELINE_RECON" \
  --cg-list "$VAL_CG" \
  --out-json "${RECON_ROOT}/native_gate.json" || true

# --- recon-aware SuperPC config ---
"$PY" "${SCRIPT_DIR}/compare_reconstructed_cg.py" \
  --recon-root "$RECON_ROOT" \
  --pairs-file "$VAL_PAIRS" \
  --official-version v2 \
  --max-samples 80 \
  --n-samples 5000 \
  --device cpu \
  --out-json "$COMPARE_JSON" || true
if [[ -f "$COMPARE_JSON" ]]; then
  "$PY" "${SCRIPT_DIR}/build_recon_enh_config.py" \
    --compare-json "$COMPARE_JSON" \
    --out-json "$RECON_ENH_CONFIG" || true
fi

# --- SuperPC ENH ---
rm -rf "$ENH_ROOT"
mkdir -p "$ENH_ROOT"
export CG_LIST="${RECON_ROOT}/reconstructed_cg_list.txt"
export OUT_DIR="$ENH_ROOT"
export CKPT="${GC2026_ROOT}/models/superpc_pretrained/kitti360_com.pth"
export OUTPUT_MODE=blend_cg
export BLEND_VOXEL_MM=3.0
export ENH_ADAPTIVE_BLEND=1
if [[ -f "$RECON_ENH_CONFIG" ]]; then
  export ENH_PER_SEQ_CONFIG="$RECON_ENH_CONFIG"
fi
bash "${SCRIPT_DIR}/run_dual_gpu_infer.sh"

expected=$(wc -l < "$CG_LIST" | tr -d ' ')
for ((i = 0; i < 120; i++)); do
  if ! pgrep -f "run_superpc_infer.py.*--out-dir ${ENH_ROOT}" >/dev/null 2>&1; then
    break
  fi
  n=$(find "$ENH_ROOT" -name '*.ply' 2>/dev/null | wc -l | tr -d ' ')
  echo "[val362_n0_v2] superpc ply=${n}/${expected}"
  sleep 15
done

# SuperPC dual_gpu writes flat output/ — reorganize for evaluate_uvg
"$PY" <<'PY'
import glob, os, shutil
root = os.environ["ENH_ROOT"]
flat = os.path.join(root, "output")
if os.path.isdir(flat):
    for ply in glob.glob(os.path.join(flat, "*.ply")):
        base = os.path.basename(ply)
        seq = base.split("_UVG")[0]
        dst_dir = os.path.join(root, seq)
        os.makedirs(dst_dir, exist_ok=True)
        dst = os.path.join(dst_dir, base)
        if not os.path.isfile(dst):
            shutil.copy2(ply, dst)
    print(f"[val362_n0_v2] reorganized ENH into per-sequence dirs")
PY

# --- Gates + challenge-style eval ---
"$PY" "${SCRIPT_DIR}/eval_native_gate.py" \
  --recon-root "$RECON_ROOT" \
  --enh-root "$ENH_ROOT" \
  --baseline-recon-root "$BASELINE_RECON" \
  --cg-list "$VAL_CG" \
  --out-json "${ENH_ROOT}/native_gate_enh.json" || true

"$PY" "${SCRIPT_DIR}/evaluate_uvg.py" \
  --pairs-file "$VAL_PAIRS" \
  --enhanced-root "$ENH_ROOT" \
  --n-samples 20000 \
  --device cpu \
  --out-json "${ENH_ROOT}/evaluation_val_n20k.json"

# --- Baseline B1 eval (if not cached) ---
B1_ENH="${GC2026_ROOT}/output/cwipc_native/val362_enh"
B1_EVAL="${B1_ENH}/evaluation_val_n20k.json"
if [[ ! -f "$B1_EVAL" && -d "$B1_ENH" ]]; then
  echo "[val362_n0_v2] baseline evaluate_uvg on B1 val362_enh"
  "$PY" "${SCRIPT_DIR}/evaluate_uvg.py" \
    --pairs-file "$VAL_PAIRS" \
    --enhanced-root "$B1_ENH" \
    --n-samples 20000 \
    --device cpu \
    --out-json "$B1_EVAL" || true
fi

# --- Comparison report vs baselines ---
"$PY" "${SCRIPT_DIR}/compare_val362_baselines.py" \
  --v2-recon-gate "${RECON_ROOT}/native_gate.json" \
  --v2-enh-gate "${ENH_ROOT}/native_gate_enh.json" \
  --v2-eval "${ENH_ROOT}/evaluation_val_n20k.json" \
  --baseline-b1-gate "${GC2026_ROOT}/output/cwipc_native/native_gate_enh.json" \
  --baseline-b1-eval "${GC2026_ROOT}/output/cwipc_native/val362_enh/evaluation_val_n20k.json" \
  --out-json "$REPORT" || true

echo "[val362_n0_v2] DONE $(date -Is)"
echo "[val362_n0_v2] report=$REPORT"
