#!/usr/bin/env bash
# Autonomous no-GPU overnight runner: downloads poll, librealsense, CPU eval, Stage1 on RGBD upload.
set -euo pipefail

GC2026_ROOT="/root/autodl-tmp/GC2026"
LOG="${GC2026_ROOT}/output/overnight_nogpu.log"
STATE="${GC2026_ROOT}/output/overnight_nogpu.state"
POLL_SEC="${POLL_SEC:-600}"
MAX_HOURS="${MAX_HOURS:-8}"
SEQ_FILTER="${SEQ_FILTER:-TicTacToe,VictoryHeart}"
MIN_DISK_GB="${MIN_DISK_GB:-15}"

exec > >(tee -a "$LOG") 2>&1
echo "[overnight_nogpu] START $(date -Is) poll=${POLL_SEC}s max_hours=${MAX_HOURS}"

if [[ -f "${GC2026_ROOT}/output/cwipc_env.sh" ]]; then
  # shellcheck source=/dev/null
  source "${GC2026_ROOT}/output/cwipc_env.sh"
fi

touch "$STATE"
mark_done() {
  local key="$1"
  grep -q "^${key}=done$" "$STATE" 2>/dev/null || echo "${key}=done" >> "$STATE"
}
is_done() {
  grep -q "^${1}=done$" "$STATE" 2>/dev/null
}

stop_obsolete_waiters() {
  for pat in wait_rgbd_and_val.sh run_full_pipeline_chain.sh; do
    pids=$(pgrep -f "$pat" 2>/dev/null || true)
    if [[ -n "$pids" ]]; then
      echo "[overnight_nogpu] stopping obsolete: $pat ($pids)"
      kill $pids 2>/dev/null || true
    fi
  done
}

ensure_cgv2_download() {
  if grep -q '\[aria2_cgv2\] DONE' "${GC2026_ROOT}/output/aria2_cgv2_download.log" 2>/dev/null; then
    return 0
  fi
  if pgrep -f 'download_cgv2' >/dev/null 2>&1 || pgrep -f 'aria2c.*CGv2' >/dev/null 2>&1; then
    echo "[overnight_nogpu] CGv2 aria2 already running"
    return 0
  fi
  avail_gb=$(df -BG /root/autodl-tmp 2>/dev/null | awk 'NR==2{gsub(/G/,"",$4); print $4}' || echo 999)
  if [[ "${avail_gb}" -lt "$MIN_DISK_GB" ]]; then
    echo "[overnight_nogpu] disk low (${avail_gb}G) — skip starting CGv2 download"
    return 0
  fi
  echo "[overnight_nogpu] starting CGv2 aria2 download"
  nohup bash "${GC2026_ROOT}/scripts/download_cgv2_aria2.sh" \
    >> "${GC2026_ROOT}/output/download_cgv2_nohup.out" 2>&1 &
}

run_cgv2_postinstall() {
  echo "[overnight_nogpu] CGv2 post-install"
  python3 "${GC2026_ROOT}/scripts/record_cgv2_layout.py"
  python3 "${GC2026_ROOT}/scripts/prepare_uvg_pairs.py" --cg-version v2
  if [[ -f "${GC2026_ROOT}/data/processed/all_cg_only_cgv2.txt" ]]; then
    python3 "${GC2026_ROOT}/scripts/uvg_frame_map.py" \
      --cg-list "${GC2026_ROOT}/data/processed/all_cg_only_cgv2.txt" \
      --out-json "${GC2026_ROOT}/data/processed/frame_playback_map_cgv2.json"
  fi
  mark_done cgv2_postinstall
}

run_rgbd_upload_chain() {
  echo "[overnight_nogpu] RGBD upload detected — install + stage1"
  SEQ_FILTER="$SEQ_FILTER" bash "${GC2026_ROOT}/scripts/post_rgbd_install.sh"
  python3 "${GC2026_ROOT}/scripts/map_rgbd_pairs.py" || true
  SEQ_FILTER="$SEQ_FILTER" bash "${GC2026_ROOT}/scripts/run_stage1_rgbd_only.sh"
  mark_done rgbd_stage1
}

run_librealsense_once() {
  if is_done librealsense; then
    if /usr/local/libexec/cwipc/cwipc_realsense2_install_check >/dev/null 2>&1; then
      return 0
    fi
  fi
  echo "[overnight_nogpu] building librealsense (install_cwipc.sh)"
  bash "${GC2026_ROOT}/scripts/install_cwipc.sh" || true
  if /usr/local/libexec/cwipc/cwipc_realsense2_install_check >/dev/null 2>&1; then
    mark_done librealsense
    echo "[overnight_nogpu] librealsense OK"
  else
    echo "[overnight_nogpu] librealsense still missing — Stage1 may use open3d fallback"
  fi
}

run_cpu_eval_once() {
  if is_done cpu_eval; then
    return 0
  fi
  echo "[overnight_nogpu] CPU unit tests"
  cd "${GC2026_ROOT}/scripts"
  python3 test_transform_matrix.py || true
  python3 test_frame_playback_map.py || true
  python3 test_rgbd_to_cg_units.py || true

  if [[ -d "${GC2026_ROOT}/output/submission_candidate" ]]; then
    echo "[overnight_nogpu] full-dataset CPU eval (all pairs, memory-safe)"
    python3 "${GC2026_ROOT}/scripts/evaluate_uvg.py" \
      --pairs-file "${GC2026_ROOT}/data/processed/all_pairs.txt" \
      --enhanced-root "${GC2026_ROOT}/output/submission_candidate" \
      --n-samples 4096 \
      --max-load-points 20000 \
      --device cpu \
      --out-json "${GC2026_ROOT}/output/submission_candidate/evaluation_full_cpu.json"
    if [[ -f "${GC2026_ROOT}/output/submission_candidate/evaluation_full_cpu.json" ]]; then
      python3 "${GC2026_ROOT}/scripts/summarize_eval_by_sequence.py" \
        --eval-json "${GC2026_ROOT}/output/submission_candidate/evaluation_full_cpu.json" \
        --out-json "${GC2026_ROOT}/output/submission_candidate/per_sequence_full_cpu.json" \
        || true
      python3 "${GC2026_ROOT}/scripts/build_per_sequence_enh_config.py" || true
      UVG_CG_VERSION="${UVG_CG_VERSION:-v1}" python3 "${GC2026_ROOT}/scripts/val_gate.py" \
        --cg-version "${UVG_CG_VERSION:-v1}" || true
      mark_done cpu_eval
    else
      echo "[overnight_nogpu] CPU full eval did not produce JSON — will retry later"
    fi
  else
    mark_done cpu_eval
  fi
}

write_summary() {
  python3 "${GC2026_ROOT}/scripts/generate_status_report.py" || true
  SUMMARY="${GC2026_ROOT}/output/overnight_summary.md"
  {
    echo "# Overnight no-GPU summary"
    echo ""
    echo "Generated: $(date -Is)"
    echo ""
    echo "## State flags"
    cat "$STATE" 2>/dev/null || true
    echo ""
    echo "## cwipc / librealsense"
    if /usr/local/libexec/cwipc/cwipc_realsense2_install_check >/dev/null 2>&1; then
      echo "- librealsense2: OK"
    else
      echo "- librealsense2: MISSING (use RGBD_TO_CG_BACKEND=open3d or SCP librealsense deb/tar)"
    fi
    if command -v cwipc >/dev/null 2>&1; then
      echo "- cwipc CLI: $(command -v cwipc) ($(cwipc version 2>/dev/null || echo unknown))"
    fi
    echo ""
    echo "## CGv2"
    if [[ -f "${GC2026_ROOT}/data/processed/all_cg_only_cgv2.txt" ]] && [[ -s "${GC2026_ROOT}/data/processed/all_cg_only_cgv2.txt" ]]; then
      echo "- all_cg_only_cgv2.txt: ready ($(wc -l < "${GC2026_ROOT}/data/processed/all_cg_only_cgv2.txt") frames)"
    else
      if grep -q '\[aria2_cgv2\] DONE' "${GC2026_ROOT}/output/aria2_cgv2_download.log" 2>/dev/null; then
        echo "- aria2 DONE; post-install pending or failed"
      else
        echo "- CGv2 download in progress (see output/aria2_cgv2_download.log)"
      fi
    fi
    echo ""
    echo "## RGBD upload / Stage1"
    if is_done rgbd_stage1; then
      echo "- Stage1: done (see output/stage1_rgbd_only.log)"
    elif SEQ_FILTER="$SEQ_FILTER" bash "${GC2026_ROOT}/scripts/check_rgbd_download.sh" >/dev/null 2>&1; then
      echo "- RGBD zips OK but stage1 not marked done — check logs"
    else
      echo "- Waiting for complete RGBD upload to data/raw/UVG-CWI-DQPC/__zip/"
    fi
    echo ""
    echo "## GPU pending"
    echo "Run after switching to GPU: \`bash output/gpu_pending.sh\`"
    echo ""
    echo "See also: output/status_report.md"
  } > "$SUMMARY"
}

# Bootstrap
stop_obsolete_waiters
ensure_cgv2_download
if ! is_done librealsense; then
  run_librealsense_once &
fi
if ! is_done cpu_eval; then
  run_cpu_eval_once &
fi

END_EPOCH=$(( $(date +%s) + MAX_HOURS * 3600 ))
round=0
while [[ $(date +%s) -lt $END_EPOCH ]]; do
  round=$((round + 1))
  echo "[overnight_nogpu] === poll round $round $(date -Is) ==="

  if grep -q '\[aria2_cgv2\] DONE' "${GC2026_ROOT}/output/aria2_cgv2_download.log" 2>/dev/null; then
    if ! is_done cgv2_postinstall; then
      run_cgv2_postinstall || true
    fi
  else
    ensure_cgv2_download
  fi

  if ! is_done rgbd_stage1; then
    if SEQ_FILTER="$SEQ_FILTER" bash "${GC2026_ROOT}/scripts/check_rgbd_download.sh"; then
      run_rgbd_upload_chain || true
    fi
  fi

  if ! is_done librealsense; then
    run_librealsense_once || true
  fi

  if ! is_done cpu_eval; then
    run_cpu_eval_once || true
  fi

  python3 "${GC2026_ROOT}/scripts/generate_status_report.py" || true
  write_summary

  sleep "$POLL_SEC"
done

write_summary
bash "${GC2026_ROOT}/scripts/prepare_submission_repo.sh" || true
echo "[overnight_nogpu] END $(date -Is)"
