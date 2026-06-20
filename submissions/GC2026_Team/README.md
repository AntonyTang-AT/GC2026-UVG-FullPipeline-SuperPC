# GC2026 Team — UVG-CWI-DQPC (Dual Processing Tracks)

We participate in **both** official Processing Tracks on the same challenge.  
**Primary / intended leaderboard submission: Full Pipeline** (RGBD → CG → enhancement).

| Track | Input | Script | Output dir |
|-------|-------|--------|------------|
| **Full Pipeline** (primary) | Intel RealSense RGBD / .bag files | `bash src/run_full_pipeline.sh` | `output/full_pipeline_candidate/` |
| Enhancement Only | Official CG PLY | `bash src/run_enhancement_only.sh` | `output/submission_candidate/` |

| Field | Value |
|-------|-------|
| Team | GC2026 Team |
| Algorithm | RGBD reconstruction (cwipc + transform_matrix / Open3D fallback) + SuperPC blend |
| Hardware | 2× NVIDIA RTX 5090 |
| Coordinate system | Consumer-grade capture coordinates (mm) |

## Reproduce Full Pipeline (primary)

1. `pip install -r requirements.txt`
2. Checkpoints under `models/superpc_pretrained/`
3. Download val RGBD (recommended first): `SEQ_FILTER=TicTacToe,VictoryHeart bash src/download_rgbd_aria2.sh`
4. Check download: `SEQ_FILTER=TicTacToe,VictoryHeart bash src/check_rgbd_download.sh`
5. Install/unzip: `SEQ_FILTER=TicTacToe,VictoryHeart bash src/post_rgbd_install.sh`
6. Val smoke (362 frames): `bash src/run_full_pipeline_val.sh`
7. Full run (2155 frames): `bash src/run_full_pipeline.sh` then `bash src/post_full_pipeline.sh`
8. Or automated chain: `bash src/run_full_pipeline_chain.sh` (wait download → val → full)
9. ENH PLY + `manifest.json` with `processing_track: Full Pipeline`

Alternative bulk download: `bash src/download_full_pipeline_data.sh` (official script, RGBD + raw/bag).

Unit test (mm coordinates): `python scripts/test_rgbd_to_cg_units.py`

## Reproduce Enhancement Only (secondary)

1. Same dependencies and checkpoints
2. Official CG data (CG track download)
3. `bash src/run_enhancement_only.sh`
4. Post-process eval + pack: `bash src/post_submission_candidate.sh`

## Selected enhancement config (val gate, shared by both tracks)

```json
{"checkpoint": "kitti360_com.pth", "output_mode": "blend_cg", "use_vision": 0, "blend_voxel_mm": 3.0, "experiment_dir": "/root/autodl-tmp/GC2026/output/val_grid/kitti360_com_blend_cg_v0_vx3.0"}
```

Runtime is recorded in `runtime.log` inside each output directory.

**Note:** This package contains source only; organizers run the pipeline on official inputs.
