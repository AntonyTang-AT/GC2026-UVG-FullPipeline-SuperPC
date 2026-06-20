# GC2026 UVG Pipeline Scripts

**Agent / 新服务器**：先读 [`../AGENTS.md`](../AGENTS.md)，再跑 `bash scripts/check_integrity.sh`。

## N0 v2 Full Pipeline（当前生产）

| Script | Purpose |
|--------|---------|
| `run_full_n0_v2.sh` | 全量编排：Val362 merge → Stage1 → SuperPC → Post（`STOP_AFTER_PHASE=1\|2\|3`） |
| `watch_full_n0_v2.sh` | 终端进度仪表盘（含 tar 静默阶段文件大小） |
| `run_val362_n0_v2.sh` | Val362 N0 实验 + gate + 对比 |
| `run_stage1_native_parallel.sh` | 并行 Stage1（TT/VH N0 override，`VAL_MERGE_ROOT`） |
| `select_stage1_production_tag.py` | 生产 tag 评选（默认 `N0_cwipc_official`） |
| `fill_missing_n0_v2.sh` | 缺帧补全（hybrid 重试 + PGDR/B2 拷贝） |
| `retry_missing_recon.py` | 单帧 cwipc 重建重试 |
| `eval_native_gate.py` | recon/enh vs HE native gate |
| `compare_val362_baselines.py` | N0 vs B1 JSON 对比报告 |
| `compare_reconstructed_cg.py` | recon vs 官方 CG → per-seq SuperPC config |
| `build_recon_enh_config.py` | 由 compare JSON 生成 blend 配置 |
| `post_full_pipeline.sh` | manifest + evaluate_uvg + temporal + tar |
| `summarize_eval_by_sequence.py` | 按序列汇总 Chamfer |

```bash
bash scripts/run_full_n0_v2.sh
bash scripts/watch_full_n0_v2.sh   # 另一终端
```

## Quick start (Enhancement Only)

```bash
source scripts/env_setup.sh
bash scripts/run_enhancement_only.sh
bash scripts/post_submission_candidate.sh
```

## Environment

- Conda env: `superpc` (Python 3.9) — SuperPC 推理 / GPU Chamfer
- System Python 3.12 + cwipc — Stage1 bag 回放（`source output/cwipc_env.sh`）
- **RTX 5090** requires `torch==2.8.0+cu128`:
  ```bash
  pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
  bash scripts/rebuild_extensions.sh
  ```
- Always `source scripts/env_setup.sh` (sets `LD_LIBRARY_PATH`)

## Core scripts

| Script | Purpose |
|--------|---------|
| `prepare_uvg_pairs.py` | CG/HE pair lists |
| `rgbd_to_cg.py` | RGBD/bag → CG（auto / cwipc / pgdr） |
| `run_superpc_infer.py` | Batch inference + KNN colors |
| `run_dual_gpu_infer.sh` | 2× GPU SuperPC |
| `evaluate_uvg.py` | Chamfer CG/ENH vs HE |
| `temporal_smooth.py` | Sliding-window XYZ smooth |
| `make_submission.py` | manifest.json + README |
| `run_cwipc_native_plan.sh` | CWIPC val362 sweep / finalize |
| `install_cwipc.sh` | librealsense + cwipc deb |
| `check_integrity.sh` | Migration integrity check |
| `generate_status_report.py` | `output/status_report.json` |

`evaluate_uvg.py` supports `--device cpu` for post while GPUs run SuperPC.

## Outputs (local, gitignored)

- `output/submission_candidate/` — Enhancement Only ENH
- `output/full_pipeline_n0_v2_cg/` — N0 v2 Stage1 recon
- `output/full_pipeline_n0_v2_candidate/` — N0 v2 SuperPC ENH
- `output/full_n0_v2_final_report.json` — N0 vs B1 对比

See [`../docs/N0_V2_RESULTS.md`](../docs/N0_V2_RESULTS.md) for metrics.
