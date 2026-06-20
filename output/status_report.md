# GC2026 UVG-CWI-DQPC Status

Generated: 2026-06-19T23:20:49.283057Z

## Processing Tracks

| Track | Role | Val improve (n=20k) |
|-------|------|---------------------|
| Full Pipeline (primary) | RGBD→CG→SuperPC | None |
| Enhancement Only (fallback) | Official CG→SuperPC | 14.460028510500152 |

## Enhancement Metrics (val)

- Chamfer improve (n=20k): 14.460028510500152
- Color PSNR-Y: 63.52832913126947
- Temporal adjacent CD-L1: 15.415282050768534
- ENH frames: 2155

## RGBD Download (val sequences)

```
TicTacToe/RGBD: disk=0.00 GB [DOWNLOADING]
VictoryHeart/RGBD: disk=0.00 GB [DOWNLOADING]
Incomplete: TicTacToe_UVG-CWI-DQPC_v1-0_RGBD.zip, VictoryHeart_UVG-CWI-DQPC_v1-0_RGBD.zip
```

## Background Chain

- Stage: waiting for val RGBD download
- Logs: `output/wait_rgbd_val.log`, `output/full_pipeline_chain.log`
- aria2 tail: `14294 Killed                  | aria2c --console-log-level=notice --max-concurrent-downloads="$JOBS" --split="$S" --max-`

## Submission Artifacts

| Artifact | Path | Status |
|----------|------|--------|
| Enhancement tar | `output/submission_candidate_submission.tar.gz` | missing |
| Full Pipeline tar | `output/full_pipeline_candidate_submission.tar.gz` | exists |
| Primary manifest | `submissions/GC2026_Team/manifest.json` | Enhancement until Full ready |

RGBD mapped: 2155 missing: 0

## Next Steps

- Run integrity check: bash scripts/check_integrity.sh
- Finish librealsense: bash scripts/install_cwipc.sh
- Generate rgbd_pairs: bash scripts/post_rgbd_install.sh
- Full Pipeline val smoke: bash scripts/run_full_pipeline_val.sh
- Full Pipeline all sequences: bash scripts/run_full_pipeline.sh
