#!/usr/bin/env bash
# Unzip RGBD archives from __zip into data/raw/UVG-CWI-DQPC (bags in camera_output/).
# When REMOVE_ZIP_AFTER=1, verify all .bag sizes match zip before deleting archive.
set -euo pipefail

GC2026_ROOT="${GC2026_ROOT:-/root/autodl-tmp/GC2026}"
SEQ_FILTER="${SEQ_FILTER:-PinkNoir,TrumanShow,VirtualLife}"
REMOVE_ZIP="${REMOVE_ZIP_AFTER:-1}"
VERIFY_BEFORE_RM="${VERIFY_BEFORE_RM:-1}"
OUT_ZIP="${GC2026_ROOT}/data/raw/UVG-CWI-DQPC/__zip"
RAW="${GC2026_ROOT}/data/raw"
LOG="${GC2026_ROOT}/output/extract_rgbd_zips.log"

verify_bags() {
  local seq="$1" zip="$2"
  python3 - "$seq" "$zip" "$RAW" <<'PY'
import struct, sys, zipfile, os

seq, zip_path, raw = sys.argv[1:4]
cam = os.path.join(raw, "UVG-CWI-DQPC", seq, "consumer-grade_capture_system", "camera_output")
with zipfile.ZipFile(zip_path) as zf:
    expected = {
        os.path.basename(n): i.file_size
        for n, i in zip(zf.namelist(), zf.infolist())
        if n.endswith(".bag")
    }
if not expected:
    sys.exit(f"no bags listed in zip for {seq}")
if len(expected) != 8:
    print(f"[verify] WARN {seq}: expected 8 bags in zip, found {len(expected)}")
bad = []
for name, exp in sorted(expected.items()):
    p = os.path.join(cam, name)
    if not os.path.isfile(p):
        bad.append(f"MISSING {name}")
        continue
    sz = os.path.getsize(p)
    if abs(sz - exp) >= 1024:
        bad.append(f"SIZE {name}: {sz} vs {exp}")
if bad:
    for b in bad:
        print(f"[verify] FAIL {seq}: {b}")
    sys.exit(1)
print(f"[verify] OK {seq}: {len(expected)} bags, sizes match zip")
PY
}

exec > >(tee -a "$LOG") 2>&1
echo "[extract_rgbd] START $(date -Is) SEQ=$SEQ_FILTER REMOVE_ZIP=$REMOVE_ZIP VERIFY=$VERIFY_BEFORE_RM"
df -h /root/autodl-tmp | tail -1

IFS=',' read -ra SEQS <<< "$SEQ_FILTER"
for s in "${SEQS[@]}"; do
  s="${s// /}"
  zip="${OUT_ZIP}/${s}_UVG-CWI-DQPC_v1-0_RGBD.zip"
  if [[ ! -f "$zip" ]]; then
    echo "[extract_rgbd] SKIP $s — zip missing: $zip"
    continue
  fi
  echo "[extract_rgbd] unzip $s ($(du -h "$zip" | cut -f1)) ..."
  unzip -o -q "$zip" -d "$RAW"
  bags=$(find "${RAW}/UVG-CWI-DQPC/${s}" -name '*.bag' 2>/dev/null | wc -l)
  echo "[extract_rgbd] $s bags=$bags"
  if [[ "$REMOVE_ZIP" == "1" ]]; then
    if [[ "$VERIFY_BEFORE_RM" == "1" ]]; then
      verify_bags "$s" "$zip"
    elif [[ "$bags" -lt 8 ]]; then
      echo "[extract_rgbd] SKIP remove $zip — only $bags bags"
      continue
    fi
    rm -f "$zip"
    echo "[extract_rgbd] removed $zip"
  fi
  df -h /root/autodl-tmp | tail -1
done

echo "[extract_rgbd] DONE $(date -Is)"
