#!/usr/bin/env bash
# Production Stage1: B1 hybrid + official CWIPC filters (Val362 or custom cg-list).
set -euo pipefail

GC2026_ROOT="${GC2026_ROOT:-/root/autodl-tmp/GC2026}"
SCRIPT_DIR="${GC2026_ROOT}/scripts"
PY="${PY:-python3.12}"

CG_LIST="${CG_LIST:-${GC2026_ROOT}/data/processed/val_cg_only_cgv2.txt}"
OUT_ROOT="${OUT_ROOT:-${GC2026_ROOT}/output/cwipc_native/stage1_production}"
STAGE1_CONFIG="${STAGE1_CONFIG:-${GC2026_ROOT}/output/remediation/stage1_config.json}"
BACKEND="${BACKEND:-hybrid}"
FILTER_PROFILE="${CWIPC_FILTER_PROFILE:-official}"

source "${SCRIPT_DIR}/env_setup.sh"
if [[ -f "${GC2026_ROOT}/output/cwipc_env.sh" ]]; then
  # shellcheck source=/dev/null
  source "${GC2026_ROOT}/output/cwipc_env.sh"
fi

mkdir -p "$OUT_ROOT"
echo "[stage1_native] backend=$BACKEND profile=$FILTER_PROFILE out=$OUT_ROOT"

"$PY" "${SCRIPT_DIR}/rgbd_to_cg.py" \
  --cg-list "$CG_LIST" \
  --out-root "$OUT_ROOT" \
  --backend "$BACKEND" \
  --stage1-config "$STAGE1_CONFIG" \
  --cwipc-filter-profile "$FILTER_PROFILE" \
  --multi-camera \
  --no-coord-corrections \
  --force

"$PY" "${SCRIPT_DIR}/retry_missing_recon.py" \
  --recon-root "$OUT_ROOT" \
  --cg-list "$CG_LIST" \
  --backend "$BACKEND" \
  --cwipc-filter-profile "$FILTER_PROFILE" \
  --stage1-config "$STAGE1_CONFIG"

"$PY" "${SCRIPT_DIR}/eval_native_gate.py" \
  --recon-root "$OUT_ROOT" \
  --baseline-recon-root "${GC2026_ROOT}/output/remediation/stage1_pgdr_val362" \
  --cg-list "$CG_LIST" \
  --out-json "${OUT_ROOT}/native_gate.json"

echo "[stage1_native] done — gate: ${OUT_ROOT}/native_gate.json"
