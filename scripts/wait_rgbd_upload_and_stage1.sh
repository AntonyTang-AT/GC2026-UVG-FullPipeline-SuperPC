#!/usr/bin/env bash
# Poll until val RGBD zips pass check_rgbd_download.sh, then install + Stage1 only.
set -euo pipefail

GC2026_ROOT="${GC2026_ROOT:-/root/autodl-tmp/GC2026}"
if [[ -f "${GC2026_ROOT}/output/cwipc_env.sh" ]]; then
  # shellcheck source=/dev/null
  source "${GC2026_ROOT}/output/cwipc_env.sh"
fi

SEQ_FILTER="${SEQ_FILTER:-TicTacToe,VictoryHeart}"
POLL_SEC="${POLL_SEC:-60}"
LOG="${GC2026_ROOT}/output/wait_rgbd_upload.log"

exec >>"$LOG" 2>&1
echo "[wait_rgbd_upload] START $(date -Is) SEQ=$SEQ_FILTER poll=${POLL_SEC}s"

while true; do
  if SEQ_FILTER="$SEQ_FILTER" bash "${GC2026_ROOT}/scripts/check_rgbd_download.sh"; then
    echo "[wait_rgbd_upload] RGBD zips OK $(date -Is)"
    break
  fi
  SEQ_FILTER="$SEQ_FILTER" bash "${GC2026_ROOT}/scripts/check_rgbd_download.sh" || true
  sleep "$POLL_SEC"
done

echo "[wait_rgbd_upload] post_rgbd_install..."
SEQ_FILTER="$SEQ_FILTER" bash "${GC2026_ROOT}/scripts/post_rgbd_install.sh"

echo "[wait_rgbd_upload] map_rgbd_pairs..."
python3 "${GC2026_ROOT}/scripts/map_rgbd_pairs.py" --sequences TicTacToe VictoryHeart || true

echo "[wait_rgbd_upload] stage1..."
SEQ_FILTER="$SEQ_FILTER" bash "${GC2026_ROOT}/scripts/run_stage1_rgbd_only.sh"

if [[ -f "${GC2026_ROOT}/output/overnight_nogpu.state" ]]; then
  grep -qxF 'rgbd_stage1=done' "${GC2026_ROOT}/output/overnight_nogpu.state" \
    || echo 'rgbd_stage1=done' >> "${GC2026_ROOT}/output/overnight_nogpu.state"
fi

echo "[wait_rgbd_upload] DONE $(date -Is)"
