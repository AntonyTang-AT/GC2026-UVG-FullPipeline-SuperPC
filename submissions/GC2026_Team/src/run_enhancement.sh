#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export CKPT="${CKPT:-$ROOT/models/superpc_pretrained/tartanair_com.pth}"
export OUT_DIR="${OUT_DIR:-$ROOT/output/submission_candidate}"
export OUTPUT_MODE="${OUTPUT_MODE:-blend_cg}"
export USE_VISION="${USE_VISION:-0}"
export BLEND_VOXEL_MM="${BLEND_VOXEL_MM:-2.0}"
export NUM_POINTS="${NUM_POINTS:-11520}"
export TARGET_NUM_POINTS="${TARGET_NUM_POINTS:-46080}"
bash "$ROOT/submissions/GC2026_Team/src/run_dual_gpu_infer.sh"
