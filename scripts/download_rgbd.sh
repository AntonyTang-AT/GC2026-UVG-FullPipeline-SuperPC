#!/usr/bin/env bash
# Download UVG RGBD data for vision conditioning.
set -euo pipefail

GC2026_ROOT="/root/autodl-tmp/GC2026"
LOG="${GC2026_ROOT}/output/rgbd_download.log"
mkdir -p "${GC2026_ROOT}/output"

exec > >(tee -a "$LOG") 2>&1
echo "[download_rgbd] START $(date -Is)"

export TMPDIR="${TMPDIR:-/root/autodl-tmp/tmp}"
mkdir -p "$TMPDIR"

if ! command -v jq >/dev/null 2>&1; then
  echo "[download_rgbd] installing jq..."
  apt-get update -qq && apt-get install -y -qq jq
fi

cd "${GC2026_ROOT}/data/raw"
curl -sL https://ultravideo.fi/UVG-CWI-DQPC/download_UVG-CWI-DQPC.sh | \
  bash -s -- -s all -t RGBD --skip-check --install

echo "[download_rgbd] END $(date -Is)"
