#!/usr/bin/env bash
# GC2026 integrity check — run after migration or when resuming work.
# Usage: bash scripts/check_integrity.sh
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GC2026_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RAW="${GC2026_ROOT}/data/raw/UVG-CWI-DQPC"
PROC="${GC2026_ROOT}/data/processed"
MODELS="${GC2026_ROOT}/models/superpc_pretrained"
OUT="${GC2026_ROOT}/output"

SEQUENCES=(
  PinkNoir TrumanShow VirtualLife TicTacToe VictoryHeart
  OrangeKettlebell BlueSpeech BlueVolley BouncingBlue
  FitFluencer GoodVision Mannequin
)

PASS=0
WARN=0
FAIL=0

ok()   { echo "  [OK]   $*"; PASS=$((PASS + 1)); }
warn() { echo "  [WARN] $*"; WARN=$((WARN + 1)); }
fail() { echo "  [FAIL] $*"; FAIL=$((FAIL + 1)); }

echo "=== GC2026 Integrity Check ==="
echo "Root: ${GC2026_ROOT}"
echo "Time: $(date -Is)"
echo

# --- Data: bags ---
echo "## RGBD bags (expect 8/sequence)"
bag_bad=0
for s in "${SEQUENCES[@]}"; do
  n=$(find "${RAW}/${s}" -name '*.bag' 2>/dev/null | wc -l)
  if [[ "$n" -eq 8 ]]; then
    ok "${s}: ${n}/8 bags"
  else
    fail "${s}: ${n}/8 bags"
    bag_bad=$((bag_bad + 1))
  fi
done
echo

# --- Data: CG index ---
echo "## CGv2 index"
if [[ -f "${PROC}/all_cg_only_cgv2.txt" ]]; then
  n=$(wc -l < "${PROC}/all_cg_only_cgv2.txt")
  if [[ "$n" -eq 2155 ]]; then ok "all_cg_only_cgv2.txt: ${n} frames"; else warn "all_cg_only_cgv2.txt: ${n} (expected 2155)"; fi
else
  fail "all_cg_only_cgv2.txt missing"
fi
if [[ -f "${PROC}/val_cg_only_cgv2.txt" ]]; then
  n=$(wc -l < "${PROC}/val_cg_only_cgv2.txt")
  if [[ "$n" -eq 362 ]]; then ok "val_cg_only_cgv2.txt: ${n} frames"; else warn "val_cg_only_cgv2.txt: ${n} (expected 362)"; fi
else
  warn "val_cg_only_cgv2.txt missing"
fi
echo

# --- RGBD pairs ---
echo "## RGBD mapping (Stage1 prerequisite)"
if [[ -f "${PROC}/rgbd_pairs.txt" ]]; then
  n=$(wc -l < "${PROC}/rgbd_pairs.txt")
  if [[ "$n" -gt 0 ]]; then ok "rgbd_pairs.txt: ${n} pairs"; else warn "rgbd_pairs.txt empty — run post_rgbd_install.sh after librealsense"; fi
else
  warn "rgbd_pairs.txt missing"
fi
echo

# --- Models ---
echo "## SuperPC checkpoints"
for ck in kitti360_com.pth shapenet_com.pth tartanair_com.pth; do
  if [[ -f "${MODELS}/${ck}" ]]; then ok "${ck} ($(du -h "${MODELS}/${ck}" | cut -f1))"; else fail "${ck} missing"; fi
done
echo

# --- Code ---
echo "## External code"
if [[ -d "${GC2026_ROOT}/code/SuperPC" ]]; then ok "code/SuperPC present"; else fail "code/SuperPC missing — git clone sair-lab/SuperPC"; fi
echo

# --- Enhancement output ---
echo "## Enhancement Only output"
if [[ -d "${OUT}/submission_candidate" ]]; then
  ply=$(find "${OUT}/submission_candidate" -name '*.ply' 2>/dev/null | wc -l)
  if [[ "$ply" -eq 2155 ]]; then ok "submission_candidate: ${ply} ENH PLY"; else warn "submission_candidate: ${ply} PLY (expected 2155)"; fi
else
  warn "submission_candidate/ missing"
fi
if [[ -f "${OUT}/val_grid/gate_decision.json" ]]; then
  ok "gate_decision.json present"
else
  fail "gate_decision.json missing"
fi
echo

# --- Full Pipeline output ---
echo "## Full Pipeline output"
if [[ -d "${OUT}/full_pipeline_candidate" ]]; then
  ply=$(find "${OUT}/full_pipeline_candidate" -name '*.ply' 2>/dev/null | wc -l)
  ok "full_pipeline_candidate: ${ply} PLY"
else
  warn "full_pipeline_candidate/ not yet created"
fi
echo

# --- Environment ---
echo "## Runtime"
if [[ -f /root/miniconda3/etc/profile.d/conda.sh ]]; then
  # shellcheck source=/dev/null
  source /root/miniconda3/etc/profile.d/conda.sh
  if conda env list | grep -q '^superpc '; then ok "conda env superpc"; else warn "conda env superpc missing"; fi
else
  warn "miniconda not at /root/miniconda3"
fi

if command -v nvidia-smi >/dev/null 2>&1; then
  ok "nvidia-smi: $(nvidia-smi -L | head -1)"
else
  warn "nvidia-smi not found (CPU-only host?)"
fi

if [[ -f "${OUT}/cwipc_env.sh" ]]; then ok "cwipc_env.sh present"; else warn "cwipc_env.sh missing — run install_cwipc.sh"; fi

if [[ -f /usr/local/libexec/cwipc/cwipc_realsense2_install_check ]]; then
  if /usr/local/libexec/cwipc/cwipc_realsense2_install_check >/dev/null 2>&1; then
    ok "librealsense2 runtime"
  else
    warn "librealsense2 not loaded — bash scripts/install_cwipc.sh"
  fi
else
  warn "cwipc_realsense2_install_check not installed"
fi
echo

# --- Zip staging ---
echo "## RGBD zip staging (__zip/)"
if [[ -d "${RAW}/__zip" ]]; then
  zcount=$(find "${RAW}/__zip" -maxdepth 1 -name '*.zip' 2>/dev/null | wc -l)
  if [[ "$zcount" -eq 0 ]]; then ok "__zip/ empty (bags extracted)"; else warn "__zip/ has ${zcount} zip(s) — delete only after VERIFY_BEFORE_RM"; fi
fi
echo

# --- Disk ---
echo "## Disk"
df -h "${GC2026_ROOT}" 2>/dev/null | tail -1 || df -h /root/autodl-tmp 2>/dev/null | tail -1
du -sh "${RAW}" "${OUT}/submission_candidate" 2>/dev/null || true
echo

echo "=== Summary: ${PASS} OK, ${WARN} WARN, ${FAIL} FAIL ==="
if [[ "$FAIL" -gt 0 ]]; then
  echo "Action: fix FAIL items before submission or Full Pipeline."
  exit 1
fi
if [[ "$WARN" -gt 0 ]]; then
  echo "Action: WARN items may block Full Pipeline; Enhancement Only may still work."
  exit 0
fi
echo "All checks passed."
exit 0
