#!/usr/bin/env bash
# Populate submissions/GC2026_Team/ per UVG-CWI/submissions layout (no PLY files).
# Documents both Processing Tracks; primary submission = Full Pipeline.
set -euo pipefail

GC2026_ROOT="/root/autodl-tmp/GC2026"
TEAM_DIR="${GC2026_ROOT}/submissions/GC2026_Team"
SRC_DIR="${TEAM_DIR}/src"
GATE_JSON="${GC2026_ROOT}/output/val_grid/gate_decision.json"

mkdir -p "$SRC_DIR"

cp "${GC2026_ROOT}/scripts/run_superpc_infer.py" "$SRC_DIR/"
cp "${GC2026_ROOT}/scripts/run_dual_gpu_infer.sh" "$SRC_DIR/"
cp "${GC2026_ROOT}/scripts/uvg_io.py" "$SRC_DIR/"
cp "${GC2026_ROOT}/scripts/env_setup.sh" "$SRC_DIR/"
cp "${GC2026_ROOT}/scripts/map_rgbd_pairs.py" "$SRC_DIR/"
cp "${GC2026_ROOT}/scripts/download_rgbd.sh" "$SRC_DIR/"
cp "${GC2026_ROOT}/scripts/download_full_pipeline_data.sh" "$SRC_DIR/"
cp "${GC2026_ROOT}/scripts/rgbd_to_cg.py" "$SRC_DIR/"
cp "${GC2026_ROOT}/scripts/make_submission.py" "$SRC_DIR/"
cp "${GC2026_ROOT}/scripts/post_full_pipeline.sh" "$SRC_DIR/"
cp "${GC2026_ROOT}/scripts/check_rgbd_download.sh" "$SRC_DIR/"
cp "${GC2026_ROOT}/scripts/post_rgbd_install.sh" "$SRC_DIR/"
cp "${GC2026_ROOT}/scripts/download_rgbd_aria2.sh" "$SRC_DIR/"
cp "${GC2026_ROOT}/scripts/wait_rgbd_and_val.sh" "$SRC_DIR/"
cp "${GC2026_ROOT}/scripts/run_full_pipeline_chain.sh" "$SRC_DIR/"
cp "${GC2026_ROOT}/scripts/run_full_pipeline_after_val.sh" "$SRC_DIR/"
cp "${GC2026_ROOT}/scripts/post_submission_candidate.sh" "$SRC_DIR/"
cp "${GC2026_ROOT}/scripts/run_full_pipeline_val.sh" "$SRC_DIR/"

cat > "${SRC_DIR}/run_enhancement_only.sh" <<'EOF'
#!/usr/bin/env bash
# Enhancement Only: official CG -> SuperPC -> ENH
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
export OUT_DIR="${OUT_DIR:-$ROOT/output/submission_candidate}"
bash "$ROOT/scripts/run_enhancement_only.sh"
EOF

cat > "${SRC_DIR}/run_full_pipeline.sh" <<'EOF'
#!/usr/bin/env bash
# Full Pipeline: RGBD/bag -> reconstructed CG -> SuperPC -> ENH
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
export OUT_DIR="${OUT_DIR:-$ROOT/output/full_pipeline_candidate}"
bash "$ROOT/scripts/run_full_pipeline.sh"
EOF

chmod +x "${SRC_DIR}/run_enhancement_only.sh" "${SRC_DIR}/run_full_pipeline.sh"
chmod +x "${SRC_DIR}/run_dual_gpu_infer.sh" "${SRC_DIR}/download_rgbd.sh" "${SRC_DIR}/download_full_pipeline_data.sh"
chmod +x "${SRC_DIR}/post_full_pipeline.sh" "${SRC_DIR}/check_rgbd_download.sh"
chmod +x "${SRC_DIR}/post_rgbd_install.sh" "${SRC_DIR}/download_rgbd_aria2.sh"
chmod +x "${SRC_DIR}/wait_rgbd_and_val.sh" "${SRC_DIR}/run_full_pipeline_chain.sh"
chmod +x "${SRC_DIR}/run_full_pipeline_after_val.sh" "${SRC_DIR}/post_submission_candidate.sh"
chmod +x "${SRC_DIR}/run_full_pipeline_val.sh"

POST_JSON="{}"
if [[ -f "$GATE_JSON" ]]; then
  POST_JSON=$(python3 -c "import json;print(json.dumps(json.load(open('$GATE_JSON'))['best_config']))")
fi

cat > "${TEAM_DIR}/README.md" <<EOF
# GC2026 Team — UVG-CWI-DQPC (Dual Processing Tracks)

We participate in **both** official Processing Tracks on the same challenge.  
**Primary / intended leaderboard submission: Full Pipeline** (RGBD → CG → enhancement).

| Track | Input | Script | Output dir |
|-------|-------|--------|------------|
| **Full Pipeline** (primary) | Intel RealSense RGBD / .bag files | \`bash src/run_full_pipeline.sh\` | \`output/full_pipeline_candidate/\` |
| Enhancement Only | Official CG PLY | \`bash src/run_enhancement_only.sh\` | \`output/submission_candidate/\` |

| Field | Value |
|-------|-------|
| Team | GC2026 Team |
| Algorithm | RGBD reconstruction (Open3D / optional cwipc) + SuperPC blend enhancement |
| Hardware | 2× NVIDIA RTX 5090 |
| Coordinate system | Consumer-grade capture coordinates (mm) |

## Reproduce Full Pipeline (primary)

1. \`pip install -r requirements.txt\`
2. Checkpoints under \`models/superpc_pretrained/\`
3. Download val RGBD (recommended first): \`SEQ_FILTER=TicTacToe,VictoryHeart bash src/download_rgbd_aria2.sh\`
4. Check download: \`SEQ_FILTER=TicTacToe,VictoryHeart bash src/check_rgbd_download.sh\`
5. Install/unzip: \`SEQ_FILTER=TicTacToe,VictoryHeart bash src/post_rgbd_install.sh\`
6. Val smoke (362 frames): \`bash src/run_full_pipeline_val.sh\`
7. Full run (2155 frames): \`bash src/run_full_pipeline.sh\` then \`bash src/post_full_pipeline.sh\`
8. Or automated chain: \`bash src/run_full_pipeline_chain.sh\` (wait download → val → full)
9. ENH PLY + \`manifest.json\` with \`processing_track: Full Pipeline\`

Alternative bulk download: \`bash src/download_full_pipeline_data.sh\` (official script, RGBD + raw/bag).

Unit test (mm coordinates): \`python scripts/test_rgbd_to_cg_units.py\`

## Reproduce Enhancement Only (secondary)

1. Same dependencies and checkpoints
2. Official CG data (CG track download)
3. \`bash src/run_enhancement_only.sh\`
4. Post-process eval + pack: \`bash src/post_submission_candidate.sh\`

## Selected enhancement config (val gate, shared by both tracks)

\`\`\`json
${POST_JSON}
\`\`\`

Runtime is recorded in \`runtime.log\` inside each output directory.

**Note:** This package contains source only; organizers run the pipeline on official inputs.
EOF

cat > "${TEAM_DIR}/requirements.txt" <<'EOF'
torch>=2.0
numpy
open3d
plyfile
tqdm
transformers
accelerate
Pillow
EOF

FULL_MANIFEST="${GC2026_ROOT}/output/full_pipeline_candidate/manifest.json"
ENH_MANIFEST="${GC2026_ROOT}/output/submission_candidate/manifest.json"
if [[ -f "$FULL_MANIFEST" ]]; then
  cp "$FULL_MANIFEST" "${TEAM_DIR}/manifest_full_pipeline.json"
  cp "$FULL_MANIFEST" "${TEAM_DIR}/manifest.json"
elif [[ -f "$ENH_MANIFEST" ]]; then
  cp "$ENH_MANIFEST" "${TEAM_DIR}/manifest.json"
fi
if [[ -f "$ENH_MANIFEST" ]]; then
  cp "$ENH_MANIFEST" "${TEAM_DIR}/manifest_enhancement_only.json"
fi

if [[ ! -f "${TEAM_DIR}/manifest_full_pipeline.json" ]]; then
  cat > "${TEAM_DIR}/manifest_full_pipeline.json" <<EOF
{
  "team": "GC2026 Team",
  "title": "UVG-CWI-DQPC GC2026 Full Pipeline SuperPC",
  "processing_track": "Full Pipeline",
  "pipeline_notes": "RGBD/bag -> rgbd_to_cg.py -> SuperPC blend enhancement",
  "post_processing": ${POST_JSON}
}
EOF
fi

echo "[prepare_submission] -> ${TEAM_DIR}"
