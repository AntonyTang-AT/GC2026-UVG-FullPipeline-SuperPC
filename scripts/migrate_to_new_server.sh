#!/usr/bin/env bash
# Migrate GC2026 useful data to teammate's SeetaCloud instance via rsync over SSH.
set -euo pipefail

DST_HOST="${DST_HOST:-connect.westd.seetacloud.com}"
DST_PORT="${DST_PORT:-53145}"
DST_USER="${DST_USER:-root}"
DST_ROOT="${DST_ROOT:-/root/autodl-tmp}"
GC2026_ROOT="${GC2026_ROOT:-/root/autodl-tmp/GC2026}"
LOG="${GC2026_ROOT}/output/migrate_rsync.log"
EXCLUDE="${GC2026_ROOT}/scripts/migrate_exclude.txt"

SSH_OPTS=(-p "$DST_PORT" -o StrictHostKeyChecking=no -o ServerAliveInterval=30 -o ServerAliveCountMax=6)
RSYNC_SSH="ssh ${SSH_OPTS[*]}"

exec > >(tee -a "$LOG") 2>&1
echo "[migrate] START $(date -Is) -> ${DST_USER}@${DST_HOST}:${DST_PORT}"

if [[ -z "${SSHPASS:-}" ]]; then
  echo "[migrate] ERROR: set SSHPASS env var"
  exit 1
fi

export RSYNC_RSH="sshpass -e ssh ${SSH_OPTS[*]}"
sshpass -e ssh "${SSH_OPTS[@]}" "${DST_USER}@${DST_HOST}" "mkdir -p ${DST_ROOT}/GC2026 /root/miniconda3/envs"

echo "[migrate] Phase 1/2: GC2026 project (exclude caches/dup zips/tarballs)"
time rsync -avh --info=progress2 --partial --append-verify \
  --exclude-from="$EXCLUDE" \
  "${GC2026_ROOT}/" "${DST_USER}@${DST_HOST}:${DST_ROOT}/GC2026/"

echo "[migrate] Phase 2/2: conda env superpc (PyTorch 2.8+cu128)"
time rsync -avh --info=progress2 --partial --append-verify \
  /root/miniconda3/envs/superpc/ "${DST_USER}@${DST_HOST}:/root/miniconda3/envs/superpc/"

sshpass -e ssh "${SSH_OPTS[@]}" "${DST_USER}@${DST_HOST}" bash -s <<EOF
du -sh ${DST_ROOT}/GC2026 /root/miniconda3/envs/superpc 2>/dev/null || true
df -h ${DST_ROOT} /root 2>/dev/null || df -h
EOF

echo "[migrate] DONE $(date -Is)"
