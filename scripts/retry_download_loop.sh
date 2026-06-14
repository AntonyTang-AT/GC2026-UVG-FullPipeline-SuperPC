#!/usr/bin/env bash
# Periodically retry Google Drive download until official weights appear.
set -euo pipefail

GC2026_ROOT="/root/autodl-tmp/GC2026"
LOG="${GC2026_ROOT}/output/download_retry.log"
INTERVAL="${1:-1800}"

mkdir -p "${GC2026_ROOT}/output"
exec > >(tee -a "$LOG") 2>&1

echo "[retry_download] start $(date -Is) interval=${INTERVAL}s"

while true; do
  official=$(find "${GC2026_ROOT}/models/superpc_pretrained" -type f \( -name "*.pth" -o -name "*.pt" \) \
    ! -name "*smoke*" ! -name "*init*" 2>/dev/null | head -1)
  if [[ -n "$official" ]]; then
    echo "[retry_download] Official checkpoint found: $official"
    bash "${GC2026_ROOT}/scripts/rerun_with_official_ckpt.sh" "$official"
    exit 0
  fi
  echo "[retry_download] attempt $(date -Is)"
  bash "${GC2026_ROOT}/scripts/download_pretrained.sh" || true
  sleep "$INTERVAL"
done
