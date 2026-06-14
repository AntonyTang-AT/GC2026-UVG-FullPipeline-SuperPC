# GC2026 UVG-CWI-DQPC Status

Generated: 2026-06-14T11:13:43.173629Z

## Processing Tracks

| Track | Role | Val improve (n=20k) |
|-------|------|---------------------|
| Full Pipeline (primary) | RGBD→CG→SuperPC | pending |
| Enhancement Only (fallback) | Official CG→SuperPC | 10.636548184558166 |

## Enhancement Metrics (val)

- Chamfer improve (n=20k): 10.636548184558166
- Color PSNR-Y: 63.52832913126947
- Temporal adjacent CD-L1: 15.415282050768534
- ENH frames: 2155

## RGBD Download (val sequences)

```
TicTacToe/RGBD: disk=1.06 GB [DOWNLOADING]
VictoryHeart/RGBD: disk=0.79 GB [DOWNLOADING]
Incomplete: TicTacToe_UVG-CWI-DQPC_v1-0_RGBD.zip, VictoryHeart_UVG-CWI-DQPC_v1-0_RGBD.zip
```

## Background Chain

- Stage: waiting for val RGBD download
- Logs: `output/wait_rgbd_val.log`, `output/full_pipeline_chain.log`
- aria2 tail: `empty`

## Submission Artifacts

| Artifact | Path | Status |
|----------|------|--------|
| Enhancement tar | `output/submission_candidate_submission.tar.gz` | exists |
| Full Pipeline tar | `output/full_pipeline_candidate_submission.tar.gz` | pending |
| Primary manifest | `submissions/GC2026_Team/manifest.json` | Enhancement until Full ready |

RGBD mapped: 0 missing: 2155

## Next Steps

- Complete val RGBD download: check_rgbd_download.sh
- Install RGBD: post_rgbd_install.sh
- Val smoke: run_full_pipeline_val.sh
- Unit test mm coords: python scripts/test_rgbd_to_cg_units.py
- Full RGBD download + run_full_pipeline.sh after val gate
