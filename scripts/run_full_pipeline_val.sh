#!/usr/bin/env bash
# Val smoke test for Full Pipeline (362 frames).
set -euo pipefail

GC2026_ROOT="/root/autodl-tmp/GC2026"
if [[ -f "${GC2026_ROOT}/data/processed/val_cg_only_cgv2.txt" ]]; then
  export CG_LIST="${GC2026_ROOT}/data/processed/val_cg_only_cgv2.txt"
else
  export CG_LIST="${GC2026_ROOT}/data/processed/val_cg_only.txt"
fi
export UVG_CG_VERSION="${UVG_CG_VERSION:-v2}"
export INTERMEDIATE_CG="${GC2026_ROOT}/output/full_pipeline_val_cg"
export OUT_DIR="${GC2026_ROOT}/output/full_pipeline_val_candidate"
export MAX_SAMPLES=0

bash "${GC2026_ROOT}/scripts/run_full_pipeline.sh"

OUT_DIR="${OUT_DIR}" bash "${GC2026_ROOT}/scripts/post_full_pipeline.sh"

# Compare with Enhancement val if available
ENH_VAL="${GC2026_ROOT}/output/submission_candidate/evaluation_val_n20k.json"
FULL_VAL="${OUT_DIR}/evaluation_val_n20k.json"
if [[ -f "$ENH_VAL" && -f "$FULL_VAL" ]]; then
  python3 <<PY
import json
e = json.load(open("$ENH_VAL"))["summary"]["mean_improvement_cd_l1"]
f = json.load(open("$FULL_VAL"))["summary"]["mean_improvement_cd_l1"]
print(f"[val_compare] Enhancement val improve={e:.4f} Full Pipeline val improve={f:.4f} delta={f-e:.4f}")
PY
fi
