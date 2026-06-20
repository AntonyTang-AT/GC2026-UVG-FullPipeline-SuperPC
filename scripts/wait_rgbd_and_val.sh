#!/usr/bin/env bash
# Wait for RGBD zips, install, run val Full Pipeline smoke test.
set -euo pipefail

GC2026_ROOT="/root/autodl-tmp/GC2026"
if [[ -f "${GC2026_ROOT}/output/cwipc_env.sh" ]]; then
  # shellcheck source=/dev/null
  source "${GC2026_ROOT}/output/cwipc_env.sh"
fi
SEQ_FILTER="${SEQ_FILTER:-TicTacToe,VictoryHeart}"
LOG="${GC2026_ROOT}/output/wait_rgbd_val.log"
POLL_SEC="${POLL_SEC:-300}"

exec > >(tee -a "$LOG") 2>&1
echo "[wait_rgbd_val] waiting for SEQ=$SEQ_FILTER poll=${POLL_SEC}s"

while ! SEQ_FILTER="$SEQ_FILTER" bash "${GC2026_ROOT}/scripts/check_rgbd_download.sh"; do
  tail -1 "${GC2026_ROOT}/output/aria2_download.log" 2>/dev/null || true
  sleep "$POLL_SEC"
done

SEQ_FILTER="$SEQ_FILTER" bash "${GC2026_ROOT}/scripts/post_rgbd_install.sh"
bash "${GC2026_ROOT}/scripts/run_full_pipeline_val.sh"

echo "[wait_rgbd_val] DONE $(date -Is)"
