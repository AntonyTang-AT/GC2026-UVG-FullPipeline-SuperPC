#!/usr/bin/env bash
# P4: temporal smoothing on native pipeline output (Stage1 recon or SuperPC ENH).
set -euo pipefail

GC2026_ROOT="${GC2026_ROOT:-/root/autodl-tmp/GC2026}"
SCRIPT_DIR="${GC2026_ROOT}/scripts"
PY="${PY:-python3.12}"

IN_DIR="${IN_DIR:-${GC2026_ROOT}/output/cwipc_native/val362_enh}"
OUT_DIR="${OUT_DIR:-${GC2026_ROOT}/output/cwipc_native/val362_enh_p4}"
CG_LIST="${CG_LIST:-${GC2026_ROOT}/data/processed/val_cg_only_cgv2.txt}"
WINDOW="${WINDOW:-5}"
SEQUENCES="${SEQUENCES:-}"

mkdir -p "$OUT_DIR"
echo "[p4] temporal smooth in=$IN_DIR out=$OUT_DIR window=$WINDOW"

extra=()
if [[ -n "$SEQUENCES" ]]; then
  # shellcheck disable=SC2206
  extra=(--sequences $SEQUENCES)
fi

"$PY" "${SCRIPT_DIR}/temporal_smooth.py" \
  --in-dir "$IN_DIR" \
  --out-dir "$OUT_DIR" \
  --window "$WINDOW" \
  "${extra[@]}"

"$PY" "${SCRIPT_DIR}/evaluate_temporal.py" \
  --cg-list "$CG_LIST" \
  --enhanced-root "$IN_DIR" \
  --out-json "${OUT_DIR}/temporal_before.json"

"$PY" "${SCRIPT_DIR}/evaluate_temporal.py" \
  --cg-list "$CG_LIST" \
  --enhanced-root "$OUT_DIR" \
  --out-json "${OUT_DIR}/temporal_after.json"

echo "[p4] done — compare ${OUT_DIR}/temporal_before.json vs temporal_after.json"
