#!/usr/bin/env bash
# Full Pipeline: RGBD/bag -> reconstructed CG -> SuperPC -> ENH
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
export OUT_DIR="${OUT_DIR:-$ROOT/output/full_pipeline_candidate}"
bash "$ROOT/scripts/run_full_pipeline.sh"
