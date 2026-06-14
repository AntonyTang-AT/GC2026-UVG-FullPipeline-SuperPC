# GC2026 UVG Pipeline Scripts

## Quick start

```bash
source scripts/env_setup.sh
bash scripts/run_pipeline.sh              # BlueSpeech full sequence
bash scripts/run_all_sequences.sh         # all 2155 frames
bash scripts/overnight_run.sh               # download + eval + all sequences
```

## Environment

- Conda env: `superpc` (Python 3.9)
- **RTX 5090** requires `torch==2.8.0+cu128`:
  ```bash
  pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
  bash scripts/rebuild_extensions.sh
  ```
- Always `source scripts/env_setup.sh` (sets `LD_LIBRARY_PATH`)

## Pretrained weights

Official: https://drive.google.com/drive/folders/1FrQtm8LBVrbdRT4Xs87rIZpJ9nYaTqcG

```bash
bash scripts/download_pretrained.sh
```

If Google Drive is blocked, a smoke checkpoint is created automatically (pipeline test only — replace with official `.pth` for real quality).

## Scripts

| Script | Purpose |
|--------|---------|
| `prepare_uvg_pairs.py` | CG/HE pair lists |
| `download_pretrained.sh` | gdown Model Zoo |
| `verify_superpc_ckpt.py` | Load test |
| `run_superpc_infer.py` | Batch inference + KNN colors |
| `run_pipeline.sh` | Single sequence (default BlueSpeech) |
| `run_all_sequences.sh` | All CG frames |
| `evaluate_uvg.py` | Chamfer CG/ENH vs HE |
| `temporal_smooth.py` | Sliding-window XYZ smooth |
| `make_submission.py` | manifest.json + README |
| `rebuild_extensions.sh` | After PyTorch upgrade |
| `overnight_run.sh` | Full autonomous batch |
| `extended_overnight.sh` | Eval + smooth + pack + status |
| `rerun_with_official_ckpt.sh` | Re-infer when official `.pth` uploaded |
| `retry_download_loop.sh` | Periodic Drive download retry |
| `pack_submission.sh` | tar.gz pack |
| `generate_status_report.py` | `output/status_report.json` |

`evaluate_uvg.py` uses plyfile + CUDA Chamfer3D when available (~8× faster than numpy).

## Python deps (superpc env)

`torch`, `torchvision`, `open3d`, `einops`, `numpy`, `scikit-learn`, `tqdm`, `h5py`, `transforms3d`, `gdown`

## Outputs

- `output/BlueSpeech_enhanced/` — per-sequence ENH PLY
- `output/all_sequences_enhanced/` — full dataset run
- `evaluation_summary.json` — mean Chamfer vs HE
