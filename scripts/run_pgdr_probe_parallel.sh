#!/usr/bin/env bash
# Parallel per-sequence Stage1 probe (train sequences + Val362 extras).
set -euo pipefail

GC2026_ROOT="${GC2026_ROOT:-/root/autodl-tmp/GC2026}"
SCRIPT_DIR="${GC2026_ROOT}/scripts"
STAGE1_JOBS="${STAGE1_JOBS:-4}"
PROBE_FRAMES="${PROBE_FRAMES:-8}"
PROBE_ROOT="${GC2026_ROOT}/output/remediation/probe"
SUMMARY="${GC2026_ROOT}/output/remediation/probe_all_summary.json"
CG_ALL="${GC2026_ROOT}/data/processed/all_cg_only_cgv2.txt"
VAL_SEQS="TicTacToe,VictoryHeart"

mkdir -p "$PROBE_ROOT"

if [[ -f "${GC2026_ROOT}/output/cwipc_env.sh" ]]; then
  # shellcheck source=/dev/null
  source "${GC2026_ROOT}/output/cwipc_env.sh"
fi
export PY_OPEN3D="${PY_OPEN3D:-python3.12}"
export PY_CWIPC="${PY_CWIPC:-python3.12}"

probe_one_sequence() {
  local seq="$1"
  echo "[pgdr_probe] sequence=$seq"
  python3 "${SCRIPT_DIR}/probe_sequence_stage1.py" \
    --sequence "$seq" \
    --cg-all "$CG_ALL" \
    --max-frames "$PROBE_FRAMES" \
    --probe-root "$PROBE_ROOT"
}

export -f probe_one_sequence
export GC2026_ROOT SCRIPT_DIR PROBE_FRAMES PROBE_ROOT CG_ALL PY_OPEN3D PY_CWIPC

# Train sequences (exclude val-only tuning seqs from default train probe list)
python3 <<PY > "${GC2026_ROOT}/output/remediation/_probe_sequences.txt"
import json
val = set("$VAL_SEQS".split(","))
data = json.load(open("${GC2026_ROOT}/data/raw/UVG-CWI-DQPC.json"))
for s in data["sequences"]:
    name = s["sequence"]
    if name not in val:
        print(name)
PY

echo "[pgdr_probe] train sequences (xargs -P ${STAGE1_JOBS})"
xargs -P "$STAGE1_JOBS" -I{} bash -c 'probe_one_sequence "$1"' _ {} \
  < "${GC2026_ROOT}/output/remediation/_probe_sequences.txt"

# Val362 special experiments (TicTacToe 8cam already in probe; VH cwipc sweep separate)
echo "[pgdr_probe] val362 TicTacToe + VictoryHeart baseline probe"
for seq in TicTacToe VictoryHeart; do
  probe_one_sequence "$seq" || true
done

# Aggregate summary
python3 <<PY
import json, os, glob
from datetime import datetime

root = "${PROBE_ROOT}"
summaries = []
for path in sorted(glob.glob(os.path.join(root, "*", "compare.json"))):
    data = json.load(open(path))
    best = data.get("best") or {}
    ro = best.get("recon_vs_official") or {}
    summaries.append({
        "sequence": data.get("sequence"),
        "n_frames": data.get("n_frames"),
        "best_id": best.get("id"),
        "backend": best.get("backend"),
        "transform_mode": best.get("transform_mode"),
        "depth_scale": best.get("depth_scale"),
        "multi_camera": best.get("multi_camera"),
        "mean_cd_l1": ro.get("mean_cd_l1"),
        "compare_json": path,
    })

out = {
    "created_at": datetime.utcnow().isoformat() + "Z",
    "probe_root": root,
    "sequences": summaries,
}
json.dump(out, open("${SUMMARY}", "w"), indent=2)
print(f"[pgdr_probe] wrote {len(summaries)} sequences -> ${SUMMARY}")
PY

echo "[pgdr_probe] DONE"
