#!/usr/bin/env bash
set -euo pipefail

GC2026_ROOT="${GC2026_ROOT:-/root/autodl-tmp/GC2026}"
URL="https://ultravideo.fi/UVG-CWI-DQPC/TicTacToe_UVG-CWI-DQPC_v1-0_RGBD.zip"
OFF=16943948096
END=19669869299
CHUNK="${GC2026_ROOT}/output/tictactoe_bag.zipchunk"
OUT="${GC2026_ROOT}/data/raw/UVG-CWI-DQPC/TicTacToe/consumer-grade_capture_system/camera_output/138322252957.bag"
TMP="${OUT}.fetching"
LOG="${GC2026_ROOT}/output/fetch_tictactoe_bag.log"

exec >>"$LOG" 2>&1
echo "[fetch_bag] START $(date -Is) range=${OFF}-${END}"

curl -sS -C - --retry 5 --retry-delay 10 -r "${OFF}-${END}" -o "$CHUNK" "$URL"
echo "[fetch_bag] downloaded chunk $(du -h "$CHUNK" | cut -f1)"

python3 "${GC2026_ROOT}/scripts/inflate_zipchunk_entry.py" "$CHUNK" "$TMP"
mv -f "$TMP" "$OUT"
rm -f "$CHUNK"
echo "[fetch_bag] DONE $(date -Is) -> $OUT ($(du -h "$OUT" | cut -f1))"
