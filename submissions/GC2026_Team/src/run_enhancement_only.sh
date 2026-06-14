#!/usr/bin/env bash
# Enhancement Only: official CG -> SuperPC -> ENH
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
export OUT_DIR="${OUT_DIR:-$ROOT/output/submission_candidate}"
bash "$ROOT/scripts/run_enhancement_only.sh"
