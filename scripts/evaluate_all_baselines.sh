#!/usr/bin/env bash
# Compare CG baseline vs pipeline outputs on val (Chamfer n=20000).
set -euo pipefail

GC2026_ROOT="/root/autodl-tmp/GC2026"
source "${GC2026_ROOT}/scripts/env_setup.sh"

PAIRS="${GC2026_ROOT}/data/processed/val_pairs.txt"
BASELINE_DIR="${GC2026_ROOT}/output/baselines/val_cg_as_enh"
OUT_DIR="${GC2026_ROOT}/output/baselines"
N_SAMPLES=20000

mkdir -p "$OUT_DIR"
rm -rf "$BASELINE_DIR"
mkdir -p "$BASELINE_DIR"

while IFS= read -r cg; do
  [[ -z "$cg" ]] && continue
  seq=$(basename "$(dirname "$(dirname "$(dirname "$(dirname "$cg")")")")")
  fname=$(basename "$cg" | sed 's/_CG_/_ENH_/')
  mkdir -p "$BASELINE_DIR/$seq"
  cp "$cg" "$BASELINE_DIR/$seq/$fname"
done < "${GC2026_ROOT}/data/processed/val_cg_only.txt"

python "${GC2026_ROOT}/scripts/evaluate_uvg.py" \
  --pairs-file "$PAIRS" \
  --enhanced-root "$BASELINE_DIR" \
  --n-samples "$N_SAMPLES" \
  --out-json "${OUT_DIR}/val_cg_baseline_n20k.json"

compare_roots=(
  "all_sequences_official:official_kitti360_model"
  "all_sequences_enhanced:smoke_random_init"
)

for entry in "${compare_roots[@]}"; do
  root_name="${entry%%:*}"
  label="${entry##*:}"
  root="${GC2026_ROOT}/output/${root_name}"
  if [[ -d "$root" ]]; then
    python "${GC2026_ROOT}/scripts/evaluate_uvg.py" \
      --pairs-file "$PAIRS" \
      --enhanced-root "$root" \
      --n-samples "$N_SAMPLES" \
      --out-json "${OUT_DIR}/val_${label}_n20k.json" || true
  fi
done

python3 <<'PY'
import json, os
GC = "/root/autodl-tmp/GC2026/output/baselines"
rows = []
for fn in sorted(os.listdir(GC)):
    if not fn.endswith("_n20k.json"):
        continue
    with open(os.path.join(GC, fn)) as f:
        d = json.load(f)
    s = d.get("summary", d)
    rows.append({
        "file": fn,
        "label": fn.replace("val_", "").replace("_n20k.json", ""),
        "mean_cg_cd_l1": s.get("mean_cg_cd_l1"),
        "mean_enh_cd_l1": s.get("mean_enh_cd_l1"),
        "improvement": s.get("mean_improvement_cd_l1"),
        "num_evaluated": s.get("num_evaluated"),
    })

md = ["# Val baseline comparison (Chamfer-L1, n=20000)\n", "| Label | ENH vs HE | CG vs HE | Δ (CG−ENH) | Frames |\n", "|-------|-----------|----------|------------|--------|\n"]
for r in rows:
    md.append(f"| {r['label']} | {r['mean_enh_cd_l1']:.2f} | {r['mean_cg_cd_l1']:.2f} | {r['improvement']:.2f} | {r['num_evaluated']} |\n")

out_md = os.path.join(GC, "comparison.md")
with open(out_md, "w") as f:
    f.writelines(md)
with open(os.path.join(GC, "comparison.json"), "w") as f:
    json.dump(rows, f, indent=2)
print(f"Wrote {out_md}")
for r in rows:
    print(f"  {r['label']}: ENH={r['mean_enh_cd_l1']:.2f} improvement={r['improvement']:.2f}")
PY

python "${GC2026_ROOT}/scripts/generate_status_report.py"
echo "[evaluate_all_baselines] DONE"
