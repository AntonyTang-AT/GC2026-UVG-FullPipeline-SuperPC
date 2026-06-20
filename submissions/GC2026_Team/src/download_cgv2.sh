#!/usr/bin/env bash
# Download and install official CGv2_15 (GC2026 default enhancement input).
set -euo pipefail

GC2026_ROOT="/root/autodl-tmp/GC2026"
SEQ_FILTER="${SEQ_FILTER:-all}"
LOG="${GC2026_ROOT}/output/download_cgv2.log"

exec > >(tee -a "$LOG") 2>&1
echo "[download_cgv2] START $(date -Is) SEQ=$SEQ_FILTER"

export TMPDIR="${TMPDIR:-/root/autodl-tmp/tmp}"
mkdir -p "$TMPDIR" "${GC2026_ROOT}/output"

if ! command -v jq >/dev/null 2>&1; then
  apt-get update -qq && apt-get install -y -qq jq
fi

if command -v aria2c >/dev/null 2>&1; then
  echo "[download_cgv2] Using aria2 fast path..."
  SEQ_FILTER="$SEQ_FILTER" bash "${GC2026_ROOT}/scripts/download_cgv2_aria2.sh"
  exit 0
fi

cd "${GC2026_ROOT}/data/raw"
curl -sL https://ultravideo.fi/UVG-CWI-DQPC/download_UVG-CWI-DQPC.sh | \
  bash -s -- -s "$SEQ_FILTER" -t CGv2_15 --skip-check --install

python3 "${GC2026_ROOT}/scripts/record_cgv2_layout.py"
python3 "${GC2026_ROOT}/scripts/prepare_uvg_pairs.py" --cg-version v2

echo "[download_cgv2] END $(date -Is)"
