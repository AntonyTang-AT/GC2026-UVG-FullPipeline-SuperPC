#!/usr/bin/env bash
# After val Full Pipeline smoke test: download remaining RGBD, full install, infer, pack.
set -euo pipefail

GC2026_ROOT="/root/autodl-tmp/GC2026"
VAL_EVAL="${GC2026_ROOT}/output/full_pipeline_val_candidate/evaluation_val_n20k.json"
ENH_EVAL="${GC2026_ROOT}/output/submission_candidate/evaluation_val_n20k.json"
POLL_SEC="${POLL_SEC:-600}"
LOG="${GC2026_ROOT}/output/full_pipeline_after_val.log"

exec > >(tee -a "$LOG") 2>&1
echo "[full_after_val] START $(date -Is)"

if [[ ! -f "$VAL_EVAL" ]]; then
  echo "[full_after_val] Val eval missing — run wait_rgbd_and_val.sh first"
  exit 1
fi

python3 <<PY
import json, sys
val = json.load(open("$VAL_EVAL"))["summary"]["mean_improvement_cd_l1"]
enh = None
if __import__("os").path.isfile("$ENH_EVAL"):
    enh = json.load(open("$ENH_EVAL"))["summary"]["mean_improvement_cd_l1"]
print(f"[full_after_val] val_improve={val:.4f} enh_improve={enh}")
# Proceed unless Full is dramatically worse (>5 Chamfer units below Enhancement)
if enh is not None and val < enh - 5.0:
    print("[full_after_val] Full val much worse than Enhancement — aborting full download")
    sys.exit(2)
PY

echo "[full_after_val] Downloading remaining RGBD sequences..."
SEQ_FILTER=all TYPE_FILTER=RGBD JOBS=2 X=16 S=16 \
  bash "${GC2026_ROOT}/scripts/download_rgbd_aria2.sh" || true

while ! SEQ_FILTER=all bash "${GC2026_ROOT}/scripts/check_rgbd_download.sh"; do
  tail -1 "${GC2026_ROOT}/output/aria2_download.log" 2>/dev/null || true
  sleep "$POLL_SEC"
done

SEQ_FILTER=all bash "${GC2026_ROOT}/scripts/post_rgbd_install.sh"

export OUT_DIR="${GC2026_ROOT}/output/full_pipeline_candidate"
export INTERMEDIATE_CG="${GC2026_ROOT}/output/full_pipeline_cg"
export RUN_POST=1
bash "${GC2026_ROOT}/scripts/run_full_pipeline.sh"

bash "${GC2026_ROOT}/scripts/prepare_submission_repo.sh"
python "${GC2026_ROOT}/scripts/generate_status_report.py"

echo "[full_after_val] DONE $(date -Is)"
