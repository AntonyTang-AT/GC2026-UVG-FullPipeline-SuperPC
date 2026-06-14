#!/usr/bin/env bash
# Verify RGBD zips, install via official script, map rgbd_pairs.txt.
set -euo pipefail

GC2026_ROOT="/root/autodl-tmp/GC2026"
SEQ_FILTER="${SEQ_FILTER:-TicTacToe,VictoryHeart}"
TYPE_FILTER="${TYPE_FILTER:-RGBD}"
OUT_ZIP="${OUT_ZIP:-${GC2026_ROOT}/data/raw/UVG-CWI-DQPC/__zip}"
LOG="${GC2026_ROOT}/output/post_rgbd_install.log"

exec > >(tee -a "$LOG") 2>&1
echo "[post_rgbd_install] START $(date -Is) SEQ=$SEQ_FILTER TYPE=$TYPE_FILTER"

if ! SEQ_FILTER="$SEQ_FILTER" TYPE_FILTER="$TYPE_FILTER" bash "${GC2026_ROOT}/scripts/check_rgbd_download.sh"; then
  echo "[post_rgbd_install] Download incomplete — run download_rgbd_aria2.sh first"
  exit 1
fi

# Quick zip integrity test
for z in "$OUT_ZIP"/*.zip; do
  [[ -f "$z" ]] || continue
  case "$SEQ_FILTER" in
    all) ;;
    *)
      base=$(basename "$z")
      ok=0
      IFS=',' read -ra SEQS <<< "$SEQ_FILTER"
      for s in "${SEQS[@]}"; do
        if [[ "$base" == "${s}_"* ]]; then ok=1; break; fi
      done
      if [[ "$ok" -eq 0 ]]; then continue; fi
      ;;
  esac
  echo "[post_rgbd_install] unzip -t $z"
  unzip -t "$z" >/dev/null
done

export TMPDIR="${TMPDIR:-/root/autodl-tmp/tmp}"
mkdir -p "$TMPDIR"

if ! command -v jq >/dev/null 2>&1; then
  apt-get update -qq && apt-get install -y -qq jq
fi

cd "${GC2026_ROOT}/data/raw"
echo "[post_rgbd_install] Official install..."
curl -sL https://ultravideo.fi/UVG-CWI-DQPC/download_UVG-CWI-DQPC.sh | \
  bash -s -- -s "$SEQ_FILTER" -t "$TYPE_FILTER" --skip-check --install

IFS=',' read -ra SEQS <<< "$SEQ_FILTER"
if [[ "$SEQ_FILTER" == "all" ]]; then
  python "${GC2026_ROOT}/scripts/map_rgbd_pairs.py"
else
  python "${GC2026_ROOT}/scripts/map_rgbd_pairs.py" --sequences "${SEQS[@]}"
fi

python3 <<PY
import json, os
meta = json.load(open("${GC2026_ROOT}/data/processed/rgbd_pairs_meta.json"))
print("[post_rgbd_install] mapped=", meta["mapped"], "missing=", meta["missing_rgb"])
PY

echo "[post_rgbd_install] END $(date -Is)"
