#!/usr/bin/env bash
# Full inference with gate-selected config -> submission_candidate.
set -euo pipefail

GC2026_ROOT="/root/autodl-tmp/GC2026"
GATE_JSON="${GC2026_ROOT}/output/val_grid/gate_decision.json"
OUT="${GC2026_ROOT}/output/submission_candidate"

source "${GC2026_ROOT}/scripts/env_setup.sh"

if [[ ! -f "$GATE_JSON" ]]; then
  echo "[run_full] gate_decision.json missing; running val_gate after grid"
  bash "${GC2026_ROOT}/scripts/run_val_grid.sh"
  python "${GC2026_ROOT}/scripts/val_gate.py"
fi

python3 <<'PY'
import json, os, sys
GC = "/root/autodl-tmp/GC2026"
with open(os.path.join(GC, "output/val_grid/gate_decision.json")) as f:
    d = json.load(f)
if not d.get("gate_passed"):
    print("Gate not passed:", d)
    sys.exit(1)
cfg = d["best_config"]
ckpt = os.path.join(GC, "models/superpc_pretrained", cfg["checkpoint"])
print("CKPT", ckpt)
print("MODE", cfg["output_mode"])
print("VISION", cfg["use_vision"])
print("VOXEL", cfg["blend_voxel_mm"])
with open("/tmp/gc2026_full_infer_env.sh", "w") as f:
    f.write(f"export CKPT='{ckpt}'\n")
    f.write(f"export OUT_DIR='{os.path.join(GC, 'output/submission_candidate')}'\n")
    f.write(f"export OUTPUT_MODE='{cfg['output_mode']}'\n")
    f.write(f"export USE_VISION='{cfg['use_vision']}'\n")
    f.write(f"export BLEND_VOXEL_MM='{cfg['blend_voxel_mm']}'\n")
    if "shapenet" in cfg["checkpoint"]:
        f.write("export NUM_POINTS=2048\nexport TARGET_NUM_POINTS=8192\n")
    else:
        f.write("export NUM_POINTS=11520\nexport TARGET_NUM_POINTS=46080\n")
PY

source /tmp/gc2026_full_infer_env.sh
mkdir -p "$OUT"

bash "${GC2026_ROOT}/scripts/run_dual_gpu_infer.sh"

echo "[run_full] Waiting for dual-GPU workers..."
while pgrep -f "run_superpc_infer.py.*--out-dir ${OUT}" >/dev/null; do
  n=$(find "$OUT" -name '*.ply' 2>/dev/null | wc -l)
  echo "[run_full] progress ply=$n / 2155"
  sleep 60
done

n=$(find "$OUT" -name '*.ply' | wc -l)
echo "[run_full] finished ply_count=$n"
bash "${GC2026_ROOT}/scripts/post_submission_candidate.sh"
