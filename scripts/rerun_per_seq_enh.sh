#!/usr/bin/env bash
# Re-infer sequences covered by per_sequence_enh_config (val-tuned; no model fallback).
set -euo pipefail

GC2026_ROOT="${GC2026_ROOT:-/root/autodl-tmp/GC2026}"
TRACK="${TRACK:-both}"
PER_SEQ_CFG="${GC2026_ROOT}/output/enhancement_eval/per_sequence_enh_config.json"
RECON_CFG="${GC2026_ROOT}/output/enhancement_eval/recon_enh_config.json"
GATE_JSON="${GC2026_ROOT}/output/val_grid/gate_decision.json"
LOG="${GC2026_ROOT}/output/rerun_per_seq_enh.log"

exec > >(tee -a "$LOG") 2>&1
echo "[rerun_per_seq] START $(date -Is)"

source "${GC2026_ROOT}/scripts/env_setup.sh"

# shellcheck disable=SC1091
source <(python3 <<PY
import json, os
g = json.load(open("$GATE_JSON"))
c = g.get("best_config", {})
ckpt = os.path.join("$GC2026_ROOT", "models/superpc_pretrained", c.get("checkpoint", "kitti360_com.pth"))
print(f'export CKPT="{ckpt}"')
print(f'export OUTPUT_MODE="{c.get("output_mode", "blend_cg")}"')
print(f'export BLEND_VOXEL_MM="{c.get("blend_voxel_mm", 3.0)}"')
print(f'export USE_VISION="{c.get("use_vision", 0)}"')
PY
)

export ENH_PER_SEQ_CONFIG="$PER_SEQ_CFG"
export ENH_ADAPTIVE_BLEND=0
export NUM_POINTS=11520
export TARGET_NUM_POINTS=46080
export SAMPLING_STEPS=25

RERUN_LIST="${GC2026_ROOT}/output/_per_seq_rerun_cg.txt"
python3 <<PY
import json, os
cfg = json.load(open("$PER_SEQ_CFG"))
default = cfg.get("default", {})
default_mode = default.get("output_mode")
default_voxel = float(default.get("blend_voxel_mm", 3.0))
default_ckpt = default.get("checkpoint", "kitti360_com.pth")
forced = os.environ.get(
    "FORCE_RERUN_SEQS",
    "BlueVolley,BouncingBlue,FitFluencer,GoodVision,Mannequin,OrangeKettlebell,PinkNoir,VirtualLife,VictoryHeart",
).split(",")
forced = [s.strip() for s in forced if s.strip()]
rerun_seqs = list(forced)
for seq, entry in cfg.get("sequences", {}).items():
    if seq in rerun_seqs:
        continue
    if entry.get("output_mode") != default_mode:
        rerun_seqs.append(seq)
        continue
    if float(entry.get("blend_voxel_mm", default_voxel)) != default_voxel:
        rerun_seqs.append(seq)
        continue
    if entry.get("checkpoint", default_ckpt) != default_ckpt:
        rerun_seqs.append(seq)
rerun_seqs = sorted(set(rerun_seqs))
print("[rerun_per_seq] sequences to rerun:", rerun_seqs)
cg_all = "$GC2026_ROOT/data/processed/all_cg_only_cgv2.txt"
paths = []
with open(cg_all) as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        for seq in rerun_seqs:
            if f"/{seq}/" in line:
                paths.append(line)
                break
with open("$RERUN_LIST", "w") as f:
    f.write("\n".join(paths) + ("\n" if paths else ""))
print(f"[rerun_per_seq] cg frames={len(paths)} -> $RERUN_LIST")
open("$GC2026_ROOT/output/_per_seq_rerun_sequences.txt", "w").write("\n".join(rerun_seqs) + "\n")
PY

if [[ ! -s "$RERUN_LIST" ]]; then
  echo "[rerun_per_seq] nothing to rerun"
  exit 0
fi

rerun_one_track() {
  local track="$1"
  local cg_list="$2"
  local out_dir="$3"
  echo "[rerun_per_seq] ===== track=$track out=$out_dir ====="
  while IFS= read -r seq; do
    [[ -n "$seq" ]] || continue
    rm -rf "${out_dir}/${seq}"
    echo "[rerun_per_seq] cleared ${out_dir}/${seq}"
  done < "${GC2026_ROOT}/output/_per_seq_rerun_sequences.txt"

  export CG_LIST="$cg_list"
  export OUT_DIR="$out_dir"
  rm -rf "${out_dir}/.dual_gpu_shards" "${out_dir}/.dual_gpu_logs"
  bash "${GC2026_ROOT}/scripts/run_dual_gpu_infer.sh"

  local expected
  expected=$(wc -l < "$cg_list")
  while pgrep -f "run_superpc_infer.py.*--out-dir ${out_dir}" >/dev/null; do
    local n
    n=$(find "$out_dir" -name '*.ply' 2>/dev/null | wc -l)
    echo "[rerun_per_seq] $track progress ply=$n / $expected"
    sleep 60
  done
  local n
  n=$(find "$out_dir" -name '*.ply' 2>/dev/null | wc -l)
  echo "[rerun_per_seq] $track done ply=$n"
}

# Enhancement Only: official CG
if [[ "$TRACK" == "both" || "$TRACK" == "enhancement_only" ]]; then
  rerun_one_track "enhancement_only" "$RERUN_LIST" "${GC2026_ROOT}/output/submission_candidate"
fi

# Full Pipeline: reconstructed CG paths for same sequences
if [[ "$TRACK" == "both" || "$TRACK" == "full_pipeline" ]]; then
  export ENH_PER_SEQ_CONFIG="$RECON_CFG"
  FULL_RERUN_LIST="${GC2026_ROOT}/output/_per_seq_rerun_recon_cg.txt"
python3 <<PY
import os
rerun_seqs = open("${GC2026_ROOT}/output/_per_seq_rerun_sequences.txt").read().split()
val_root = "${GC2026_ROOT}/output/full_pipeline_val_cg"
full_root = "${GC2026_ROOT}/output/full_pipeline_cg"
paths = []
for line in open("$RERUN_LIST"):
    ref = line.strip()
    if not ref:
        continue
    seq = ref.split("/UVG-CWI-DQPC/")[1].split("/")[0]
    fname = os.path.basename(ref)
    for root in (full_root, val_root):
        candidate = os.path.join(root, seq, fname)
        if os.path.isfile(candidate):
            paths.append(candidate)
            break
with open("$FULL_RERUN_LIST", "w") as f:
    f.write("\n".join(paths) + ("\n" if paths else ""))
print(f"[rerun_per_seq] full recon frames={len(paths)}")
PY

rerun_one_track "full_pipeline" "$FULL_RERUN_LIST" "${GC2026_ROOT}/output/full_pipeline_candidate"
fi

if [[ "$TRACK" == "both" || "$TRACK" == "enhancement_only" ]]; then
echo "[rerun_per_seq] post-process enhancement_only"
python "${GC2026_ROOT}/scripts/make_submission.py" \
  --enhanced-dir "${GC2026_ROOT}/output/submission_candidate" \
  --team "GC2026 Team" \
  --processing-track "Enhancement Only" \
  --title "UVG-CWI-DQPC GC2026 Enhancement Only SuperPC (per-seq)" \
  --post-processing "$GATE_JSON" \
  --cg-version v2 \
  --pipeline-notes "Official CG -> SuperPC with per_sequence_enh_config (val tune, blend_cg only)"

python "${GC2026_ROOT}/scripts/evaluate_uvg.py" \
  --pairs-file "${GC2026_ROOT}/data/processed/val_pairs_cgv2.txt" \
  --enhanced-root "${GC2026_ROOT}/output/submission_candidate" \
  --n-samples 20000 \
  --device cpu \
  --out-json "${GC2026_ROOT}/output/submission_candidate/evaluation_val_n20k.json"

python "${GC2026_ROOT}/scripts/evaluate_uvg.py" \
  --pairs-file "${GC2026_ROOT}/data/processed/all_pairs_cgv2.txt" \
  --enhanced-root "${GC2026_ROOT}/output/submission_candidate" \
  --n-samples 20000 \
  --device cpu \
  --out-json "${GC2026_ROOT}/output/submission_candidate/evaluation_full_n20k.json"

python "${GC2026_ROOT}/scripts/summarize_eval_by_sequence.py" \
  --eval-json "${GC2026_ROOT}/output/submission_candidate/evaluation_full_n20k.json" \
  --out-json "${GC2026_ROOT}/output/enhancement_eval/per_sequence_submission_full.json"

python "${GC2026_ROOT}/scripts/summarize_eval_by_sequence.py" \
  --eval-json "${GC2026_ROOT}/output/submission_candidate/evaluation_val_n20k.json" \
  --out-json "${GC2026_ROOT}/output/enhancement_eval/per_sequence_submission_val.json"
fi

if [[ "$TRACK" == "both" || "$TRACK" == "full_pipeline" ]]; then
echo "[rerun_per_seq] post-process full_pipeline"
OUT_DIR="${GC2026_ROOT}/output/full_pipeline_candidate" EVAL_DEVICE=cpu \
  bash "${GC2026_ROOT}/scripts/post_full_pipeline.sh" || true
fi

python3 <<'PY'
import json, os
def show(label, path):
    if not os.path.isfile(path):
        print(f"{label}: missing")
        return
    d = json.load(open(path))
    s = d.get("summary", d)
    print(f"=== {label} ===")
    for k in ("num_evaluated", "mean_improvement_cd_l1", "sequences_positive", "mean_delta_cd_l1"):
        if k in s and s[k] is not None:
            print(f"  {k}: {s[k]}")
    per = d.get("per_sequence", {})
    if per:
        neg = sum(1 for v in per.values() if v.get("mean_delta_cd_l1", 0) < 0)
        pos = sum(1 for v in per.values() if v.get("mean_delta_cd_l1", 0) > 0)
        print(f"  per_seq positive={pos} negative={neg}")

show("Enhancement val", "output/submission_candidate/evaluation_val_n20k.json")
show("Enhancement full", "output/submission_candidate/evaluation_full_n20k.json")
show("Enhancement per-seq full", "output/enhancement_eval/per_sequence_submission_full.json")
show("Full pipeline val", "output/full_pipeline_candidate/evaluation_val_n20k.json")
show("Full pipeline full", "output/full_pipeline_candidate/evaluation_full_n20k.json")
PY

echo "[rerun_per_seq] DONE $(date -Is)"
