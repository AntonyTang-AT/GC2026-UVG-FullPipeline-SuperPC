#!/usr/bin/env bash
# Val grid search: checkpoint x output-mode x vision x blend voxel (dual GPU per experiment).
set -euo pipefail

GC2026_ROOT="/root/autodl-tmp/GC2026"
source "${GC2026_ROOT}/scripts/env_setup.sh"

VAL_CG="${GC2026_ROOT}/data/processed/val_cg_only.txt"
VAL_PAIRS="${GC2026_ROOT}/data/processed/val_pairs.txt"
GRID_ROOT="${GC2026_ROOT}/output/val_grid"
N_SAMPLES=20000
RGBD_PAIRS="${GC2026_ROOT}/data/processed/rgbd_pairs.txt"
CKPT_DIR="${GC2026_ROOT}/models/superpc_pretrained"

mkdir -p "$GRID_ROOT"

CG_BASELINE=$(python3 -c "
import json, os
p='${GC2026_ROOT}/output/baselines/val_cg_baseline_n20k.json'
if os.path.isfile(p):
 with open(p) as f: print(json.load(f)['summary']['mean_enh_cd_l1'])
else: print('85.96')
")
echo "[val_grid] CG baseline ENH vs HE (n=${N_SAMPLES}): ${CG_BASELINE}"

infer_dual() {
  local cg_list="$1"
  local ckpt_path="$2"
  local out="$3"
  local num_in="$4"
  local num_out="$5"
  local mode="$6"
  local voxel="$7"
  local vision="$8"
  local shard_dir="${out}/.shards"
  local log_dir="${out}/.logs"
  mkdir -p "$shard_dir" "$log_dir" "$out"

  python "${GC2026_ROOT}/scripts/split_pending_cg_list.py" \
    --cg-list "$cg_list" \
    --out-dir "$out" \
    --shard-dir "$shard_dir" \
    --num-shards 2

  local vision_args=()
  if [[ "$vision" == "1" ]]; then
    vision_args=(--use-vision-conditioning)
    if [[ -f "$RGBD_PAIRS" ]]; then
      vision_args+=(--rgbd-pairs-file "$RGBD_PAIRS")
    fi
  fi

  for gpu in 0 1; do
    local list="${shard_dir}/pending_${gpu}.txt"
    local n
    n=$(wc -l < "$list" | tr -d ' ')
    if [[ "$n" -eq 0 ]]; then
      continue
    fi
    CUDA_VISIBLE_DEVICES="$gpu" python "${GC2026_ROOT}/scripts/run_superpc_infer.py" \
      --cg-list "$list" \
      --ckpt-path "$ckpt_path" \
      --out-dir "$out" \
      --num-points "$num_in" \
      --target-num-points "$num_out" \
      --output-mode "$mode" \
      --blend-voxel-mm "$voxel" \
      --skip-existing \
      "${vision_args[@]}" \
      > "${log_dir}/gpu${gpu}.log" 2>&1 &
    echo "[val_grid] infer GPU${gpu} PID=$! (${n} frames)"
  done
  wait
}

run_one() {
  local ckpt_name="$1"
  local ckpt_path="$2"
  local num_in="$3"
  local num_out="$4"
  local mode="$5"
  local voxel="$6"
  local vision="$7"
  local tag="${ckpt_name}_${mode}_v${vision}_vx${voxel}"
  local out="${GRID_ROOT}/${tag}"
  local ev="${out}/evaluation_val_n20k.json"

  if [[ -f "$ev" ]]; then
    echo "[val_grid] skip existing $tag"
    return 0
  fi

  echo "[val_grid] RUN $tag"
  rm -rf "$out"
  infer_dual "$VAL_CG" "$ckpt_path" "$out" "$num_in" "$num_out" "$mode" "$voxel" "$vision"

  python "${GC2026_ROOT}/scripts/evaluate_uvg.py" \
    --pairs-file "$VAL_PAIRS" \
    --enhanced-root "$out" \
    --n-samples "$N_SAMPLES" \
    --out-json "$ev"
}

# No-vision grid (blend + filter)
for ckpt in tartanair_com.pth shapenet_com.pth kitti360_com.pth; do
  path="${CKPT_DIR}/${ckpt}"
  [[ -f "$path" ]] || continue
  base="${ckpt%.pth}"
  if [[ "$ckpt" == "shapenet_com.pth" ]]; then
    ni=2048; no=8192
  else
    ni=11520; no=46080
  fi
  for mode in blend_cg filter_cg; do
  if [[ "$mode" == "filter_cg" ]]; then
    run_one "$base" "$path" "$ni" "$no" "$mode" 0 0
  else
    for vx in 1.0 2.0 3.0; do
      run_one "$base" "$path" "$ni" "$no" "$mode" "$vx" 0
    done
  fi
  done
done

# Vision experiments when RGBD mapped
if [[ -f "${RGBD_PAIRS%.txt}_meta.json" ]] || [[ -f "${GC2026_ROOT}/data/processed/rgbd_pairs_meta.json" ]]; then
  meta="${GC2026_ROOT}/data/processed/rgbd_pairs_meta.json"
  mapped=$(python3 -c "import json;print(json.load(open('$meta'))['mapped'])" 2>/dev/null || echo 0)
  if [[ "${mapped:-0}" -gt 100 ]]; then
    for ckpt in tartanair_com.pth kitti360_com.pth; do
      path="${CKPT_DIR}/${ckpt}"
      [[ -f "$path" ]] || continue
      base="${ckpt%.pth}"
      run_one "$base" "$path" 11520 46080 blend_cg 2.0 1
    done
  fi
fi

python3 <<'PY'
import json, os, csv
GC = "/root/autodl-tmp/GC2026/output/val_grid"
rows = []
for name in sorted(os.listdir(GC)):
    p = os.path.join(GC, name)
    ev = os.path.join(p, "evaluation_val_n20k.json")
    if not os.path.isfile(ev):
        continue
    with open(ev) as f:
        data = json.load(f)
    s = data["summary"]
    row = {
        "experiment": name,
        "mean_enh_cd_l1": s["mean_enh_cd_l1"],
        "mean_cg_cd_l1": s["mean_cg_cd_l1"],
        "improvement": s["mean_improvement_cd_l1"],
    }
    if "mean_accuracy_l1" in s:
        row["mean_accuracy_l1"] = s["mean_accuracy_l1"]
        row["mean_completeness_l1"] = s["mean_completeness_l1"]
    rows.append(row)

with open(os.path.join(GC, "summary.json"), "w") as f:
    json.dump(rows, f, indent=2)
if rows:
    with open(os.path.join(GC, "summary.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    best = min(rows, key=lambda r: r["mean_enh_cd_l1"])
    print(f"[val_grid] BEST: {best['experiment']} ENH={best['mean_enh_cd_l1']:.2f} improvement={best['improvement']:.2f}")
PY

python "${GC2026_ROOT}/scripts/generate_status_report.py"
echo "[val_grid] DONE"
