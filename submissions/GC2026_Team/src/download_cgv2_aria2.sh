#!/usr/bin/env bash
# Fast parallel download of CGv2_15 zips via aria2, then official install.
set -euo pipefail

GC2026_ROOT="/root/autodl-tmp/GC2026"
JSON="${JSON:-${GC2026_ROOT}/data/raw/UVG-CWI-DQPC.json}"
OUT_ZIP="${OUT_ZIP:-${GC2026_ROOT}/data/raw/UVG-CWI-DQPC/__zip}"
SEQ_FILTER="${SEQ_FILTER:-all}"
TYPE_FILTER="${TYPE_FILTER:-CGv2_15}"
BASE_HOST="${BASE_HOST:-https://ultravideo.fi/UVG-CWI-DQPC}"
JOBS="${JOBS:-4}"
X="${X:-16}"
S="${S:-16}"
VAL_SEQS="TicTacToe,VictoryHeart"
LOG="${GC2026_ROOT}/output/aria2_cgv2_download.log"

mkdir -p "$OUT_ZIP" "${GC2026_ROOT}/output"
exec > >(tee -a "$LOG") 2>&1
echo "[aria2_cgv2] START $(date -Is) SEQ=$SEQ_FILTER"

if ! command -v aria2c >/dev/null 2>&1; then
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
    ordered = [s for s in all_seqs if s["sequence"] in want]
for s in ordered:
    if s["sequence"] not in seqs:
        continue
    for t in type_filter:
        url = s["links"].get(t)
        if not url:
            continue
        fname = url.rsplit("/", 1)[-1]
        out_url = f"{base}/{fname}"
        print(out_url)
        print(f"  out={fname}")
PY

echo "[aria2_cgv2] Official install..."
cd "${GC2026_ROOT}/data/raw"
curl -sL https://ultravideo.fi/UVG-CWI-DQPC/download_UVG-CWI-DQPC.sh | \
  bash -s -- -s "$SEQ_FILTER" -t CGv2_15 --skip-check --install

python3 "${GC2026_ROOT}/scripts/record_cgv2_layout.py"
python3 "${GC2026_ROOT}/scripts/prepare_uvg_pairs.py" --cg-version v2
if [[ -f "${GC2026_ROOT}/data/processed/all_cg_only_cgv2.txt" ]]; then
  python3 "${GC2026_ROOT}/scripts/uvg_frame_map.py" \
    --cg-list "${GC2026_ROOT}/data/processed/all_cg_only_cgv2.txt" \
    --out-json "${GC2026_ROOT}/data/processed/frame_playback_map_cgv2.json"
fi
echo "[aria2_cgv2] DONE $(date -Is)"
