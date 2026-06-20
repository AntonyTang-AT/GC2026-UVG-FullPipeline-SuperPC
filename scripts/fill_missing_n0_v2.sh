#!/usr/bin/env bash
# Fill missing N0 v2 Stage1 frames: hybrid retry -> pgdr_full -> B2 fallback.
set -euo pipefail

GC2026_ROOT="${GC2026_ROOT:-/root/autodl-tmp/GC2026}"
SCRIPT_DIR="${GC2026_ROOT}/scripts"
PY="${PY:-python3.12}"
RECON_ROOT="${RECON_ROOT:-${GC2026_ROOT}/output/full_pipeline_n0_v2_cg}"
CG_ALL="${CG_ALL:-${GC2026_ROOT}/data/processed/all_cg_only_cgv2.txt}"
MISSING_LIST="${RECON_ROOT}/_missing_88.txt"
STAGE1_CONFIG="${GC2026_ROOT}/output/remediation/stage1_config.json"
PGDR_FULL="${GC2026_ROOT}/output/remediation/stage1_pgdr_full"
B2_FULL="${GC2026_ROOT}/output/full_pipeline_cg"
LOG="${GC2026_ROOT}/output/full_n0_v2_fill.log"

exec > >(tee -a "$LOG") 2>&1
echo "[fill] START $(date -Is)"

source "${SCRIPT_DIR}/env_setup.sh"
if [[ -f "${GC2026_ROOT}/output/cwipc_env.sh" ]]; then
  # shellcheck source=/dev/null
  source "${GC2026_ROOT}/output/cwipc_env.sh"
fi

count_ply() {
  find "$RECON_ROOT" -name '*.ply' 2>/dev/null | wc -l | tr -d ' '
}

count_missing() {
  "$PY" -c "
import os
miss=0
for ln in open('${CG_ALL}'):
    ref=ln.strip()
    if not ref: continue
    seq=ref.split('/UVG-CWI-DQPC/')[1].split('/')[0]
    out=os.path.join('${RECON_ROOT}', seq, os.path.basename(ref))
    if not os.path.isfile(out): miss+=1
print(miss)
"
}

before=$(count_ply)
miss_before=$(count_missing)
echo "[fill] before ply=$before missing=$miss_before"

# Refresh missing list
"$PY" <<PY
import os
missing=[]
for ln in open("${CG_ALL}"):
    ref=ln.strip()
    if not ref: continue
    seq=ref.split("/UVG-CWI-DQPC/")[1].split("/")[0]
    out=os.path.join("${RECON_ROOT}", seq, os.path.basename(ref))
    if not os.path.isfile(out):
        missing.append(ref)
open("${MISSING_LIST}", "w").write("\\n".join(missing)+("\\n" if missing else ""))
print(f"[fill] missing list: {len(missing)}")
PY

if [[ ! -s "$MISSING_LIST" ]]; then
  echo "[fill] nothing to do"
  exit 0
fi

# Step 1: hybrid official (best chance for hard frames)
echo "[fill] step1 hybrid official retry..."
"$PY" "${SCRIPT_DIR}/rgbd_to_cg.py" \
  --cg-list "$MISSING_LIST" \
  --out-root "$RECON_ROOT" \
  --backend hybrid \
  --stage1-config "$STAGE1_CONFIG" \
  --cwipc-filter-profile official \
  --multi-camera \
  --no-coord-corrections \
  --force || true
echo "[fill] after hybrid: ply=$(count_ply) missing=$(count_missing)"

# Step 2: hybrid relaxed
miss=$(count_missing)
if [[ "$miss" -gt 0 ]]; then
  echo "[fill] step2 hybrid relaxed retry ($miss left)..."
  "$PY" <<PY
import os
missing=[]
for ln in open("${CG_ALL}"):
    ref=ln.strip()
    if not ref: continue
    seq=ref.split("/UVG-CWI-DQPC/")[1].split("/")[0]
    out=os.path.join("${RECON_ROOT}", seq, os.path.basename(ref))
    if not os.path.isfile(out): missing.append(ref)
open("${MISSING_LIST}", "w").write("\\n".join(missing)+("\\n" if missing else ""))
PY
  "$PY" "${SCRIPT_DIR}/rgbd_to_cg.py" \
    --cg-list "$MISSING_LIST" \
    --out-root "$RECON_ROOT" \
    --backend hybrid \
    --stage1-config "$STAGE1_CONFIG" \
    --cwipc-filter-profile relaxed \
    --multi-camera \
    --no-coord-corrections \
    --force || true
  echo "[fill] after relaxed: ply=$(count_ply) missing=$(count_missing)"
fi

# Step 3: copy from pgdr_full then B2
echo "[fill] step3 baseline copy (pgdr_full -> B2)..."
"$PY" <<PY
import os, shutil, sys
sys.path.insert(0, "${SCRIPT_DIR}")
from compare_reconstructed_cg import recon_path_from_cg

recon = "${RECON_ROOT}"
pgdr = "${PGDR_FULL}"
b2 = "${B2_FULL}"
stats = {"pgdr": 0, "b2": 0, "still": 0}
still = []
for ln in open("${CG_ALL}"):
    ref = ln.strip()
    if not ref: continue
    dst = recon_path_from_cg(ref, recon)
    if os.path.isfile(dst):
        continue
    copied = False
    for name, root in [("pgdr", pgdr), ("b2", b2)]:
        src = recon_path_from_cg(ref, root)
        if os.path.isfile(src):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            stats[name] += 1
            copied = True
            break
    if not copied:
        stats["still"] += 1
        still.append(ref)
import json
print(json.dumps(stats, indent=2))
if still:
    print("still_missing_sample:", still[:5])
PY

after=$(count_ply)
miss_after=$(count_missing)
echo "[fill] after copy: ply=$after missing=$miss_after"

# Regenerate list
"$PY" <<PY
import os
cg_all = "${CG_ALL}"
out_root = "${RECON_ROOT}"
paths = []
for ln in open(cg_all):
    ref = ln.strip()
    if not ref: continue
    seq = ref.split("/UVG-CWI-DQPC/")[1].split("/")[0]
    out = os.path.join(out_root, seq, os.path.basename(ref))
    if os.path.isfile(out):
        paths.append(out)
lst = os.path.join(out_root, "reconstructed_cg_list.txt")
open(lst, "w").write("\\n".join(paths) + ("\\n" if paths else ""))
print(f"[fill] reconstructed_cg_list: {len(paths)}")
PY

# Quick val362 gate on recon (362 frames unaffected but sanity check)
"$PY" "${SCRIPT_DIR}/eval_native_gate.py" \
  --recon-root "$RECON_ROOT" \
  --baseline-recon-root "${GC2026_ROOT}/output/remediation/stage1_pgdr_val362" \
  --cg-list "${GC2026_ROOT}/data/processed/val_cg_only_cgv2.txt" \
  --out-json "${RECON_ROOT}/native_gate_after_fill.json" || true

echo "[fill] DONE $(date -Is) before=$before/$miss_before after=$after/$miss_after"
