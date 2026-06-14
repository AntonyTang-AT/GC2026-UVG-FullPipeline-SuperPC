#!/usr/bin/env bash
# Quick val-set comparison: CG baseline vs official model vs blend_cg (dual GPU).
set -euo pipefail

GC2026_ROOT="/root/autodl-tmp/GC2026"
source "${GC2026_ROOT}/scripts/env_setup.sh"

CKPT="${CKPT:-${GC2026_ROOT}/models/superpc_pretrained/tartanair_com.pth}"
VAL_CG="${GC2026_ROOT}/data/processed/val_cg_only.txt"
NUM_POINTS="${NUM_POINTS:-11520}"
TARGET="${TARGET_NUM_POINTS:-46080}"

echo "[val_experiment] ckpt=$(basename "$CKPT") modes=model,blend_cg"

python "${GC2026_ROOT}/scripts/split_pending_cg_list.py" \
  --cg-list "$VAL_CG" \
  --out-dir /tmp/val_exp_dummy \
  --shard-dir /tmp/val_exp_shards \
  --num-shards 2 || true

# Evaluate CG as baseline (copy CG paths to eval root structure is heavy); use enhanced-root trick:
# evaluate compares enh_path from cg - for CG baseline we symlink val CG as ENH names in temp dir
BASELINE_DIR="${GC2026_ROOT}/output/val_cg_baseline"
rm -rf "$BASELINE_DIR"
mkdir -p "$BASELINE_DIR"
while IFS= read -r cg; do
  [[ -z "$cg" ]] && continue
  seq=$(basename "$(dirname "$(dirname "$(dirname "$(dirname "$cg")")")")")
  fname=$(basename "$cg" | sed 's/_CG_/_ENH_/')
  mkdir -p "$BASELINE_DIR/$seq"
  cp "$cg" "$BASELINE_DIR/$seq/$fname"
done < "$VAL_CG"

for mode in model blend_cg; do
  OUT="${GC2026_ROOT}/output/val_exp_${mode}_$(basename "$CKPT" .pth)"
  rm -rf "$OUT"
  CUDA_VISIBLE_DEVICES=0 python "${GC2026_ROOT}/scripts/run_superpc_infer.py" \
    --cg-list "$VAL_CG" \
    --ckpt-path "$CKPT" \
    --out-dir "$OUT" \
    --num-points "$NUM_POINTS" \
    --target-num-points "$TARGET" \
    --output-mode "$mode" \
    --blend-voxel-mm 2.0 &
done
wait

for label_root in "val_cg_baseline:CG baseline" "val_exp_model_*:model" "val_exp_blend_cg_*:blend_cg"; do
  :
done

python "${GC2026_ROOT}/scripts/evaluate_uvg.py" \
  --pairs-file "${GC2026_ROOT}/data/processed/val_pairs.txt" \
  --enhanced-root "$BASELINE_DIR" \
  --n-samples 20000 \
  --out-json "${GC2026_ROOT}/output/val_eval_cg_baseline_n20k.json"

for OUT in "${GC2026_ROOT}"/output/val_exp_model_* "${GC2026_ROOT}"/output/val_exp_blend_cg_*; do
  [[ -d "$OUT" ]] || continue
  name=$(basename "$OUT")
  python "${GC2026_ROOT}/scripts/evaluate_uvg.py" \
    --pairs-file "${GC2026_ROOT}/data/processed/val_pairs.txt" \
    --enhanced-root "$OUT" \
    --n-samples 20000 \
    --out-json "${GC2026_ROOT}/output/val_eval_${name}_n20k.json"
done

echo "[val_experiment] DONE — see output/val_eval_*_n20k.json"
