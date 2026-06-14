#!/usr/bin/env bash
# Pack enhanced outputs: manifest + README + optional tar of PLY tree.
set -euo pipefail

GC2026_ROOT="/root/autodl-tmp/GC2026"
ENH_DIR="${1:-${GC2026_ROOT}/output/all_sequences_enhanced}"
BASE="$(basename "$ENH_DIR")"
OUT_TAR="${GC2026_ROOT}/output/${BASE}_submission.tar.gz"

python "${GC2026_ROOT}/scripts/make_submission.py" --enhanced-dir "$ENH_DIR"

echo "[pack] Creating $OUT_TAR (this may take a while)..."
tar -czf "$OUT_TAR" -C "$(dirname "$ENH_DIR")" "$BASE"
ls -lh "$OUT_TAR"
