#!/usr/bin/env bash
# Live progress dashboard for run_full_n0_v2.sh
GC2026_ROOT="${GC2026_ROOT:-/root/autodl-tmp/GC2026}"
LOG="${GC2026_ROOT}/output/full_n0_v2.log"
STATE="${GC2026_ROOT}/output/full_n0_v2.state"
RECON="${GC2026_ROOT}/output/full_pipeline_n0_v2_cg"
ENH="${GC2026_ROOT}/output/full_pipeline_n0_v2_candidate"
TARGET=2155

TAR="${GC2026_ROOT}/output/full_pipeline_n0_v2_candidate_submission.tar.gz"
PREV_TAR_SIZE=0

while true; do
  clear
  echo "========== Full Pipeline N0 v2 — $(date '+%Y-%m-%d %H:%M:%S') =========="
  if pgrep -f 'run_full_n0_v2.sh' >/dev/null 2>&1; then
    echo "Status: RUNNING (orchestrator)"
  elif pgrep -f 'post_full_pipeline.sh' >/dev/null 2>&1; then
    echo "Status: RUNNING (Phase3 post/eval/pack)"
  elif pgrep -f 'run_stage1_native_parallel.sh' >/dev/null 2>&1; then
    echo "Status: RUNNING (stage1 only)"
  else
    echo "Status: STOPPED (or finished)"
  fi
  echo ""
  echo "--- Phases (state file) ---"
  grep -E '^phase[0-9]' "$STATE" 2>/dev/null | tail -8 || echo "(no state yet)"
  echo ""
  recon=$(find "$RECON" -name '*.ply' 2>/dev/null | wc -l)
  # per-sequence ENH only (exclude flat GC2026/ + output/ duplicates)
  enh=$(find "$ENH" -mindepth 2 -name '*_UVG-CWI-DQPC_ENH_*.ply' 2>/dev/null | wc -l)
  [[ "$enh" -eq 0 ]] && enh=$(find "$ENH" -name '*_UVG-CWI-DQPC_ENH_*.ply' 2>/dev/null | wc -l)
  echo "--- Frame counts ---"
  printf "  Stage1 recon: %4d / %d  (%d%%)\n" "$recon" "$TARGET" "$((recon * 100 / TARGET))"
  printf "  SuperPC ENH:  %4d / %d  (%d%%)\n" "$enh" "$TARGET" "$((enh * 100 / TARGET))"
  echo ""
  echo "--- Phase3 artifacts ---"
  for f in \
    "$ENH/evaluation_val_n20k.json" \
    "$ENH/evaluation_full_n20k.json" \
    "$ENH/manifest.json" \
    "$ENH/native_gate_enh.json" \
    "$TAR"; do
    if [[ -f "$f" ]]; then
      sz=$(ls -lh "$f" 2>/dev/null | awk '{print $5}')
      echo "  [OK] $(basename "$f")  ($sz)"
    else
      echo "  [..] $(basename "$f")"
    fi
  done
  echo ""
  if pgrep -f 'tar -czf.*full_pipeline_n0_v2_candidate_submission' >/dev/null 2>&1; then
    cur_size=$(stat -c '%s' "$TAR" 2>/dev/null || echo 0)
    cur_gb=$(awk "BEGIN {printf \"%.2f\", $cur_size/1073741824}")
    delta_mb=$(awk "BEGIN {printf \"%.0f\", ($cur_size - $PREV_TAR_SIZE)/1048576}")
    src_gb=$(du -sb "$ENH" 2>/dev/null | awk '{printf "%.1f", $1/1073741824}')
    echo "--- Tar pack (silent — no log lines until done) ---"
    echo "  packing: YES  size=${cur_gb} GB  (+${delta_mb} MB / 10s)"
    echo "  source ENH dir ~${src_gb} GB uncompressed"
    PREV_TAR_SIZE=$cur_size
  elif [[ -f "$TAR" ]]; then
    echo "--- Tar pack ---"
    ls -lh "$TAR" 2>/dev/null | awk '{print "  done: "$5"  "$6" "$7" "$8}'
  fi
  echo ""
  echo "--- Active workers ---"
  pgrep -af 'rgbd_to_cg|run_superpc_infer|evaluate_uvg|eval_native_gate|post_full|tar -czf' 2>/dev/null \
    | grep -v watch_full | sed 's|.*/scripts/||;s/ .*//' | sort -u | head -8 || echo "  (idle)"
  echo ""
  log_age=$(( $(date +%s) - $(stat -c %Y "$LOG" 2>/dev/null || echo 0) ))
  if [[ "$log_age" -gt 120 ]] && pgrep -f 'post_full_pipeline|run_full_n0_v2' >/dev/null 2>&1; then
    echo "Note: log idle ${log_age}s — tar/eval steps often produce no new lines"
    echo ""
  fi
  echo "--- Post log (last 3) ---"
  tail -3 "${GC2026_ROOT}/output/post_full_pipeline.log" 2>/dev/null | sed 's/\r/\n/g' | tail -3 || echo "  (no post log yet)"
  echo ""
  echo "--- Last orchestrator log ---"
  tail -5 "$LOG" 2>/dev/null | sed 's/\r/\n/g' | tail -5
  echo ""
  echo "Log:  tail -f $LOG"
  echo "Quit: Ctrl+C"
  sleep 10
done
