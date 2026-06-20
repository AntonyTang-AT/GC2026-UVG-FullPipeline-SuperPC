#!/usr/bin/env bash
# Background worker: CGv2 install, librealsense, CPU eval, status refresh.
set -euo pipefail

GC2026_ROOT="${GC2026_ROOT:-/root/autodl-tmp/GC2026}"
LOG="${GC2026_ROOT}/output/pending_nogpu_work.log"
STATE="${GC2026_ROOT}/output/overnight_nogpu.state"

exec > >(tee -a "$LOG") 2>&1
echo "[pending_work] START $(date -Is)"

if [[ -f "${GC2026_ROOT}/output/cwipc_env.sh" ]]; then
  # shellcheck source=/dev/null
  source "${GC2026_ROOT}/output/cwipc_env.sh"
fi

mark_done() {
  local key="$1"
  grep -qxF "${key}=done" "$STATE" 2>/dev/null || echo "${key}=done" >> "$STATE"
}

# --- CGv2: zips OK but not extracted ---
if [[ ! -s "${GC2026_ROOT}/data/processed/all_cg_only_cgv2.txt" ]]; then
  echo "[pending_work] CGv2 official install from __zip..."
  sed -i '/^cgv2_postinstall=done$/d' "$STATE" 2>/dev/null || true
  cd "${GC2026_ROOT}/data/raw"
  curl -sL https://ultravideo.fi/UVG-CWI-DQPC/download_UVG-CWI-DQPC.sh | \
    bash -s -- -s all -t CGv2_15 --skip-check --install
  python3 "${GC2026_ROOT}/scripts/record_cgv2_layout.py"
  python3 "${GC2026_ROOT}/scripts/prepare_uvg_pairs.py" --cg-version v2
  if [[ -s "${GC2026_ROOT}/data/processed/all_cg_only_cgv2.txt" ]]; then
    python3 "${GC2026_ROOT}/scripts/uvg_frame_map.py" \
      --cg-list "${GC2026_ROOT}/data/processed/all_cg_only_cgv2.txt" \
      --out-json "${GC2026_ROOT}/data/processed/frame_playback_map_cgv2.json"
    mark_done cgv2_postinstall
    echo "[pending_work] CGv2 pairs OK: $(wc -l < "${GC2026_ROOT}/data/processed/all_cg_only_cgv2.txt") frames"
  else
    echo "[pending_work] CGv2 install finished but pairs still empty — check logs"
  fi
else
  echo "[pending_work] CGv2 pairs already present"
fi

# --- librealsense ---
if ! /usr/local/libexec/cwipc/cwipc_realsense2_install_check >/dev/null 2>&1; then
  echo "[pending_work] librealsense build via install_cwipc.sh..."
  rm -f "${GC2026_ROOT}/output/cwipc_install_cache/librealsense-2.56.5.tar.gz"
  bash "${GC2026_ROOT}/scripts/install_cwipc.sh" || true
  if /usr/local/libexec/cwipc/cwipc_realsense2_install_check >/dev/null 2>&1; then
    mark_done librealsense
    echo "[pending_work] librealsense OK"
  else
    echo "[pending_work] librealsense still missing — Stage1 uses open3d fallback"
  fi
else
  mark_done librealsense
  echo "[pending_work] librealsense already OK"
fi

# --- CPU eval (val first, then full) ---
if ! grep -qxF 'cpu_eval=done' "$STATE" 2>/dev/null; then
  cd "${GC2026_ROOT}/scripts"
  python3 test_transform_matrix.py
  python3 test_frame_playback_map.py
  python3 test_rgbd_to_cg_units.py

  EVAL_ARGS=(--n-samples 5000 --max-load-points 30000 --device cpu)
  echo "[pending_work] val CPU eval..."
  python3 "${GC2026_ROOT}/scripts/evaluate_uvg.py" \
    --pairs-file "${GC2026_ROOT}/data/processed/val_pairs.txt" \
    --enhanced-root "${GC2026_ROOT}/output/submission_candidate" \
    "${EVAL_ARGS[@]}" \
    --out-json "${GC2026_ROOT}/output/submission_candidate/evaluation_val_cpu.json"

  echo "[pending_work] full CPU eval..."
  python3 "${GC2026_ROOT}/scripts/evaluate_uvg.py" \
    --pairs-file "${GC2026_ROOT}/data/processed/all_pairs.txt" \
    --enhanced-root "${GC2026_ROOT}/output/submission_candidate" \
    "${EVAL_ARGS[@]}" \
    --out-json "${GC2026_ROOT}/output/submission_candidate/evaluation_full_cpu.json"

  if [[ -f "${GC2026_ROOT}/output/submission_candidate/evaluation_full_cpu.json" ]]; then
    python3 "${GC2026_ROOT}/scripts/summarize_eval_by_sequence.py" \
      --eval-json "${GC2026_ROOT}/output/submission_candidate/evaluation_full_cpu.json" \
      --out-json "${GC2026_ROOT}/output/submission_candidate/per_sequence_full_cpu.json"
    python3 "${GC2026_ROOT}/scripts/build_per_sequence_enh_config.py" || true
    UVG_CG_VERSION=v1 python3 "${GC2026_ROOT}/scripts/val_gate.py" --cg-version v1 || true
    mark_done cpu_eval
    echo "[pending_work] CPU eval complete"
  fi
else
  echo "[pending_work] cpu_eval already done"
fi

python3 "${GC2026_ROOT}/scripts/generate_status_report.py" || true
echo "[pending_work] END $(date -Is)"
