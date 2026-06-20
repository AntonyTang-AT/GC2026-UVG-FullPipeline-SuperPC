#!/usr/bin/env bash
# Parallel CWIPC-Native Stage1: merge Val362 sweep + rebuild train sequences.
set -euo pipefail

GC2026_ROOT="${GC2026_ROOT:-/root/autodl-tmp/GC2026}"
SCRIPT_DIR="${GC2026_ROOT}/scripts"
PY="${PY:-python3.12}"
STAGE1_JOBS="${STAGE1_JOBS:-6}"
CG_ALL="${CG_ALL:-${GC2026_ROOT}/data/processed/all_cg_only_cgv2.txt}"
OUT_ROOT="${OUT_ROOT:-${GC2026_ROOT}/output/full_pipeline_cg}"
STAGE1_CONFIG="${STAGE1_CONFIG:-${GC2026_ROOT}/output/remediation/stage1_config.json}"
BASELINE_RECON="${BASELINE_RECON:-${GC2026_ROOT}/output/remediation/stage1_pgdr_val362}"
VAL_SEQS="${VAL_SEQS:-TicTacToe,VictoryHeart}"
# Per-sequence tag override: "Seq:tag,Seq:tag" (default: val sequences use N0)
VAL_SEQ_TAG_OVERRIDES="${VAL_SEQ_TAG_OVERRIDES:-TicTacToe:N0_cwipc_official,VictoryHeart:N0_cwipc_official}"
SWEEP_ROOT="${SWEEP_ROOT:-${GC2026_ROOT}/output/cwipc_native/val362_sweep}"

TAG="${TAG:-}"
if [[ -z "$TAG" && -f "${GC2026_ROOT}/output/cwipc_native/stage1_production_tag.json" ]]; then
  TAG=$("$PY" -c "import json; print(json.load(open('${GC2026_ROOT}/output/cwipc_native/stage1_production_tag.json'))['tag'])")
fi
TAG="${TAG:-N0_cwipc_official}"
VAL_SRC="${VAL_MERGE_ROOT:-${SWEEP_ROOT}/${TAG}}"

source "${SCRIPT_DIR}/env_setup.sh"
if [[ -f "${GC2026_ROOT}/output/cwipc_env.sh" ]]; then
  # shellcheck source=/dev/null
  source "${GC2026_ROOT}/output/cwipc_env.sh"
fi

mkdir -p "$OUT_ROOT"
echo "[stage1_parallel] tag=$TAG out=$OUT_ROOT jobs=$STAGE1_JOBS overrides=$VAL_SEQ_TAG_OVERRIDES"

effective_tag() {
  local seq="$1"
  local default_tag="$2"
  local pair seq_name tag_name
  IFS=',' read -ra _pairs <<< "$VAL_SEQ_TAG_OVERRIDES"
  for pair in "${_pairs[@]}"; do
    seq_name="${pair%%:*}"
    tag_name="${pair#*:}"
    if [[ "$seq" == "$seq_name" && -n "$tag_name" && "$tag_name" != "$seq_name" ]]; then
      echo "$tag_name"
      return 0
    fi
  done
  echo "$default_tag"
}

export -f effective_tag
export VAL_SEQ_TAG_OVERRIDES

if [[ -d "$VAL_SRC" ]]; then
  echo "[stage1_parallel] merge Val362 from $VAL_SRC"
  rsync -a "$VAL_SRC/" "$OUT_ROOT/"
  # Val sequences may use per-seq sweep variant (e.g. N0 for TT/VH when TAG=B2)
  IFS=',' read -ra _val_seqs <<< "$VAL_SEQS"
  for _vs in "${_val_seqs[@]}"; do
    _vt=$(effective_tag "$_vs" "$TAG")
    if [[ "$_vt" != "$TAG" && -d "${SWEEP_ROOT}/${_vt}/${_vs}" ]]; then
      echo "[stage1_parallel] merge val seq $_vs from ${_vt}"
      rsync -a "${SWEEP_ROOT}/${_vt}/${_vs}/" "${OUT_ROOT}/${_vs}/"
    fi
  done
else
  echo "[stage1_parallel] WARN: Val362 source missing: $VAL_SRC"
fi

run_one_sequence() {
  local seq="$1"
  local out_root="$2"
  local tag="$3"
  tag=$(effective_tag "$seq" "$tag")
  local seq_list="${GC2026_ROOT}/output/cwipc_native/_cg_${seq}.txt"
  grep "/${seq}/" "$CG_ALL" >"$seq_list" || true
  if [[ ! -s "$seq_list" ]]; then
    echo "[stage1_parallel] skip empty seq=$seq"
    return 0
  fi
  echo "[stage1_parallel] rebuild seq=$seq tag=$tag"
  local extra=()
  case "$tag" in
    B0_pgdr_hybrid)
      extra=(--backend hybrid --stage1-config "$STAGE1_CONFIG" --multi-camera --cwipc-filter-profile relaxed)
      ;;
    B1_hybrid_official)
      extra=(--backend hybrid --stage1-config "$STAGE1_CONFIG" --multi-camera --cwipc-filter-profile official)
      ;;
    B2_hybrid_mild)
      extra=(--backend hybrid --stage1-config "$STAGE1_CONFIG" --multi-camera --cwipc-filter-profile mild)
      ;;
    N0_cwipc_official)
      extra=(--backend cwipc --cwipc-filter-profile official)
      ;;
    N1_cwipc_relaxed)
      extra=(--backend cwipc --cwipc-filter-profile relaxed)
      ;;
    N2_cwipc_mild)
      extra=(--backend cwipc --cwipc-filter-profile mild)
      ;;
    *)
      extra=(--backend hybrid --stage1-config "$STAGE1_CONFIG" --multi-camera --cwipc-filter-profile official)
      ;;
  esac
  "$PY" "${SCRIPT_DIR}/rgbd_to_cg.py" \
    --cg-list "$seq_list" \
    --out-root "$out_root" \
    --no-coord-corrections \
    --force \
    "${extra[@]}"
}

export -f run_one_sequence
export GC2026_ROOT SCRIPT_DIR PY CG_ALL STAGE1_CONFIG TAG

python3 <<PY > "${GC2026_ROOT}/output/cwipc_native/_train_sequences.txt"
import json
val = set("${VAL_SEQS}".split(","))
data = json.load(open("${GC2026_ROOT}/data/raw/UVG-CWI-DQPC.json"))
for s in data["sequences"]:
    if s["sequence"] not in val:
        print(s["sequence"])
PY

xargs -P "$STAGE1_JOBS" -I{} bash -c 'run_one_sequence "$1" "$2" "$3"' _ {} "$OUT_ROOT" "$TAG" \
  < "${GC2026_ROOT}/output/cwipc_native/_train_sequences.txt"

"$PY" "${SCRIPT_DIR}/retry_missing_recon.py" \
  --recon-root "$OUT_ROOT" \
  --cg-list "$CG_ALL" \
  --baseline-recon-root "$BASELINE_RECON" || true

"$PY" <<PY
import os
cg_all = "${CG_ALL}"
out_root = "${OUT_ROOT}"
paths = []
for ln in open(cg_all):
    ref = ln.strip()
    if not ref:
        continue
    seq = ref.split("/UVG-CWI-DQPC/")[1].split("/")[0]
    out = os.path.join(out_root, seq, os.path.basename(ref))
    if os.path.isfile(out):
        paths.append(out)
lst = os.path.join(out_root, "reconstructed_cg_list.txt")
open(lst, "w").write("\\n".join(paths) + ("\\n" if paths else ""))
print(f"[stage1_parallel] reconstructed_cg_list: {len(paths)} frames")
if len(paths) < 2000:
    raise SystemExit("Too few reconstructed frames for full pipeline")
PY

n=$(find "$OUT_ROOT" -name '*.ply' | wc -l)
echo "[stage1_parallel] done ply=$n list=${OUT_ROOT}/reconstructed_cg_list.txt"
