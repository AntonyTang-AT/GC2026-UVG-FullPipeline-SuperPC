# GC2026-UVG-FullPipeline-SuperPC

UVG Grand Challenge 2026 — **Track 1 (UVG-CWI-DQPC)**  
Dual Processing Tracks: **Full Pipeline** (primary) + **Enhancement Only** (fallback), both using **SuperPC** enhancement.

| Item | Status |
|------|--------|
| Enhancement Only (official CG → SuperPC) | **Done** — 2155 ENH frames, val Chamfer improve **+10.64** (n=20k) |
| Full Pipeline (RGBD → CG → SuperPC) | Scripts ready; val RGBD download → val smoke test |
| Gate config | `kitti360_com.pth`, `blend_cg`, voxel 3.0mm, `use_vision=0` |
| Competition source package | [`submissions/GC2026_Team/`](submissions/GC2026_Team/) |

Detailed snapshot: [`output/status_report.md`](output/status_report.md)

## Repository layout

| Path | Purpose |
|------|---------|
| [`scripts/`](scripts/) | Full pipeline: inference, eval, download, Full Pipeline chain |
| [`submissions/GC2026_Team/`](submissions/GC2026_Team/) | **UVG official submission layout** (source only, no PLY) |
| [`output/val_grid/gate_decision.json`](output/val_grid/gate_decision.json) | Val grid winner config |

**Not in this repo:** UVG dataset (`data/`), SuperPC weights (`models/`), third-party `code/SuperPC` clone, ENH PLY outputs (`output/submission_candidate/` ~19GB).

## Quick start (Enhancement Only)

```bash
# 1. Clone SuperPC alongside this repo
git clone https://github.com/sair-lab/SuperPC code/SuperPC

# 2. Environment (Python 3.9, CUDA)
conda create -n superpc python=3.9 -y && conda activate superpc
pip install torch open3d plyfile tqdm transformers accelerate Pillow numpy
# RTX 5090: see scripts/README.md for torch cu128 + rebuild_extensions.sh

# 3. Weights (Google Drive — see scripts/download_pretrained.sh)
bash scripts/download_pretrained.sh

# 4. UVG CG data (official download) → data/raw/UVG-CWI-DQPC/

source scripts/env_setup.sh
bash scripts/run_enhancement_only.sh
bash scripts/post_submission_candidate.sh   # eval + pack (local)
```

## Full Pipeline

```bash
SEQ_FILTER=TicTacToe,VictoryHeart bash scripts/download_rgbd_aria2.sh
SEQ_FILTER=TicTacToe,VictoryHeart bash scripts/check_rgbd_download.sh
SEQ_FILTER=TicTacToe,VictoryHeart bash scripts/post_rgbd_install.sh
bash scripts/run_full_pipeline_val.sh       # 362 frames
# Full 2155 frames:
bash scripts/run_full_pipeline.sh
bash scripts/post_full_pipeline.sh
```

Unit test (mm coordinates): `python scripts/test_rgbd_to_cg_units.py`

## Competition submission (source code)

Submit the folder **[`submissions/GC2026_Team/`](submissions/GC2026_Team/)** per [UVG-CWI/submissions](https://github.com/UVG-CWI/submissions):

- `README.md`, `requirements.txt`, `manifest.json`, `src/*.sh` + Python
- Organizers run on official inputs (**no PLY in submission**)
- Current `manifest.json` = Enhancement Only; switch to Full Pipeline manifest after full run

Local ENH backup (not for GitHub): `output/submission_candidate/` or `output/submission_candidate_submission.tar.gz` (~11GB).

## Hardware

2× NVIDIA RTX 5090, dual-GPU script: `scripts/run_dual_gpu_infer.sh`

## License & attribution

- Pipeline scripts: research use for GC2026 team.
- **SuperPC**: [sair-lab/SuperPC](https://github.com/sair-lab/SuperPC) — follow their license when using checkpoints.
- **UVG-CWI-DQPC data**: download from [ultravideo.fi](https://ultravideo.fi/UVG-CWI-DQPC/GC2026/) only; do not redistribute.
