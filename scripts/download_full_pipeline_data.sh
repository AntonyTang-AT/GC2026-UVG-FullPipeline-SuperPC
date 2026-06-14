#!/usr/bin/env bash
# Download RGBD + raw data for Full Pipeline (.bag / depth/color).
set -euo pipefail

GC2026_ROOT="/root/autodl-tmp/GC2026"
LOG="${GC2026_ROOT}/output/full_pipeline_download.log"
mkdir -p "${GC2026_ROOT}/output"

exec > >(tee -a "$LOG") 2>&1
echo "[download_full_pipeline] START $(date -Is)"

export TMPDIR="${TMPDIR:-/root/autodl-tmp/tmp}"
mkdir -p "$TMPDIR"

if ! command -v jq >/dev/null 2>&1; then
  apt-get update -qq && apt-get install -y -qq jq
fi

cd "${GC2026_ROOT}/data/raw"
# RGBD zip includes color/depth; raw zip may include .bag — use both when available.
curl -sL https://ultravideo.fi/UVG-CWI-DQPC/download_UVG-CWI-DQPC.sh | \
  bash -s -- -s all -t RGBD,raw --skip-check --install

echo "[download_full_pipeline] END $(date -Is)"
