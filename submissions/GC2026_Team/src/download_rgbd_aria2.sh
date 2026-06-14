#!/usr/bin/env bash
# Parallel RGBD/raw download via aria2 (multi-connection + multi-file).
# Official script uses one curl at a time — this is usually much faster when
# the server allows Range requests (Accept-Ranges: bytes).
set -euo pipefail

GC2026_ROOT="/root/autodl-tmp/GC2026"
JSON="${JSON:-${GC2026_ROOT}/data/raw/UVG-CWI-DQPC.json}"
OUT_ZIP="${OUT_ZIP:-${GC2026_ROOT}/data/raw/UVG-CWI-DQPC/__zip}"
SEQ_FILTER="${SEQ_FILTER:-TicTacToe,VictoryHeart}"  # val first; use "all" for full RGBD
TYPE_FILTER="${TYPE_FILTER:-RGBD}"       # RGBD or raw or RGBD,raw
BASE_HOST="${BASE_HOST:-https://ultravideo.fi/UVG-CWI-DQPC}"
JOBS="${JOBS:-2}"                        # val: 2 parallel RGBD zips
X="${X:-16}"                             # connections per file
S="${S:-16}"
VAL_SEQS="TicTacToe,VictoryHeart"
LOG="${GC2026_ROOT}/output/aria2_download.log"

mkdir -p "$OUT_ZIP" "${GC2026_ROOT}/output"
exec > >(tee -a "$LOG") 2>&1

if ! command -v aria2c >/dev/null 2>&1; then
  echo "[aria2_download] installing aria2..."
  apt-get update -qq && apt-get install -y -qq aria2
fi

python3 <<PY | aria2c --console-log-level=notice \
  --max-concurrent-downloads="$JOBS" \
  --split="$S" --max-connection-per-server="$X" \
  --min-split-size=1M --file-allocation=trunc \
  --continue=true --auto-file-renaming=false \
  --dir="$OUT_ZIP" -i /dev/stdin
import json, os, sys
json_path = "$JSON"
base = "$BASE_HOST".rstrip("/")
seq_filter = "$SEQ_FILTER"
val_first = [x.strip() for x in "$VAL_SEQS".split(",")]
type_filter = [t.strip() for t in "$TYPE_FILTER".split(",") if t.strip()]
with open(json_path) as f:
    data = json.load(f)
all_seqs = data["sequences"]
if seq_filter == "all":
    names = {s["sequence"] for s in all_seqs}
    ordered = [s for s in all_seqs if s["sequence"] in val_first]
    ordered += [s for s in all_seqs if s["sequence"] not in val_first]
    seqs = names
else:
    want = {x.strip() for x in seq_filter.split(",")}
    seqs = want
    missing = want - {s["sequence"] for s in all_seqs}
    if missing:
        sys.exit(f"Unknown sequences: {missing}")
    ordered = [s for s in all_seqs if s["sequence"] in want]
for s in ordered:
    if s["sequence"] not in seqs:
        continue
    for t in type_filter:
        url = s["links"].get(t)
        if not url:
            continue
        fname = url.rsplit("/", 1)[-1]
        # Prefer BASE_HOST (swap ultravideo <-> tuni if needed)
        out_url = f"{base}/{fname}"
        print(out_url)
        print(f"  out={fname}")
PY

echo "[aria2_download] DONE."
du -sh "$OUT_ZIP"
SEQ_FILTER="$SEQ_FILTER" TYPE_FILTER="$TYPE_FILTER" bash "${GC2026_ROOT}/scripts/check_rgbd_download.sh" || true
echo "[aria2_download] Install/unzip with:"
echo "  SEQ_FILTER=${SEQ_FILTER} bash ${GC2026_ROOT}/scripts/post_rgbd_install.sh"
