#!/usr/bin/env bash
# Report RGBD zip download progress: EOCD + aria2 control file (not sparse ls size).
set -euo pipefail

GC2026_ROOT="/root/autodl-tmp/GC2026"
JSON="${JSON:-${GC2026_ROOT}/data/raw/UVG-CWI-DQPC.json}"
OUT_ZIP="${OUT_ZIP:-${GC2026_ROOT}/data/raw/UVG-CWI-DQPC/__zip}"
SEQ_FILTER="${SEQ_FILTER:-all}"
TYPE_FILTER="${TYPE_FILTER:-RGBD}"

python3 <<PY
import json, os, subprocess, sys

json_path = "$JSON"
out_zip = "$OUT_ZIP"
seq_filter = "$SEQ_FILTER"
type_filter = [t.strip() for t in "$TYPE_FILTER".split(",") if t.strip()]


def disk_bytes(path: str) -> int:
    if not os.path.isfile(path):
        return 0
    # GNU du default: disk usage in 1024-byte blocks (not apparent/logical size).
    blocks = int(subprocess.check_output(["du", "-s", path], text=True).split()[0])
    return blocks * 1024


with open(json_path) as f:
    data = json.load(f)

seq_to_links = {s["sequence"]: s["links"] for s in data["sequences"]}

if seq_filter == "all":
    want_seqs = list(seq_to_links.keys())
else:
    want_seqs = [x.strip() for x in seq_filter.split(",") if x.strip()]


def zip_ready(path: str) -> tuple[bool, str, int, int, int]:
    aria2_meta = path + ".aria2"
    logical = os.path.getsize(path) if os.path.isfile(path) else 0
    disk = disk_bytes(path)
    if os.path.isfile(aria2_meta):
        expected = 0
        try:
            with open(aria2_meta, "r", encoding="utf-8", errors="ignore") as mf:
                for line in mf:
                    if line.startswith("length="):
                        expected = int(line.split("=", 1)[1].strip())
                        break
        except (OSError, ValueError):
            pass
        return False, "DOWNLOADING", disk, expected, logical
    if not os.path.isfile(path):
        return False, "MISSING", 0, 0, 0
    try:
        with open(path, "rb") as f:
            f.seek(-65536, 2)
            block = f.read()
        if b"PK\x05\x06" not in block:
            return False, "INCOMPLETE", disk, logical, logical
    except OSError:
        return False, "READ_ERR", 0, 0, 0
    return True, "OK", disk, disk, logical

total_expected = 0
total_actual = 0
incomplete = []
checked = 0

for name in want_seqs:
    links = seq_to_links.get(name, {})
    for t in type_filter:
        url = links.get(t)
        if not url:
            continue
        fname = url.rsplit("/", 1)[-1]
        path = os.path.join(out_zip, fname)
        ok, status, disk, expected, logical = zip_ready(path)
        checked += 1
        if expected > 0:
            total_expected += expected
            total_actual += min(disk, expected)
            pct = 100.0 * disk / expected
            extra = ""
            if logical != disk:
                extra = f" logical={logical/1e9:.2f}GB"
            print(
                f"{name}/{t}: disk={disk/1e9:.2f} GB / {expected/1e9:.2f} GB ({pct:.1f}%)"
                f"{extra} [{status}]"
            )
        else:
            print(f"{name}/{t}: disk={disk/1e9:.2f} GB [{status}]")
        if not ok:
            incomplete.append(fname)

if checked == 0:
    print("No zip entries for filter", seq_filter)
    sys.exit(1)

if total_expected:
    pct_all = 100.0 * total_actual / total_expected
    print(f"TOTAL: {total_actual/1e9:.2f} GB / {total_expected/1e9:.2f} GB ({pct_all:.1f}%)")
if incomplete:
    print("Incomplete:", ", ".join(incomplete))
    sys.exit(1)
PY
