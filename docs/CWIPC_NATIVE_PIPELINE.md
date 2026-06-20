# CWIPC-Native 两阶段管线

## 目标

复刻官方 CWIPC 处理链（标定 → 同步 → 深度滤波 → 融合 → 可选时序），**主 KPI 为 recon vs HE**；PGDR hybrid 作为对照分支保留。

```
bag → Stage1（CWIPC-Native / PGDR hybrid）→ Stage2（SuperPC blend_cg）→ ENH
```

## 阶段

| Phase | 内容 | 脚本 |
|-------|------|------|
| P0 | VH fine-register（test_aligner） | `run_cwipc_fine_register.py` |
| P1 | 滤波 profile + 多 variant sweep | `run_cwipc_native_val362.py` |
| Gate | recon vs HE，相对 PGDR baseline 改善 | `eval_native_gate.py` |
| P2 | SuperPC 双卡 | `run_dual_gpu_infer.sh` |

## 滤波 Profile

| Profile | 说明 |
|---------|------|
| `official` | 保留 UVG camera_config 默认 RealSense + processing 滤波 |
| `relaxed` | 离线 playback 用（原 PGDR 默认） |
| `mild` | 官方滤波 + 略放宽 height/radius |

CLI：`rgbd_to_cg.py --cwipc-filter-profile official|relaxed|mild`

## Val362 Variants

| Tag | 路径 |
|-----|------|
| B0_pgdr_hybrid | hybrid + relaxed（PGDR 对照） |
| B1_hybrid_official | hybrid + official 滤波 |
| B2_hybrid_mild | hybrid + mild |
| N0/N1/N2 | 全序列 pure cwipc + official/relaxed/mild |

## 运行

```bash
# Quick 验证（15 帧/序列）
TRACK=quick FRAMES_PER_SEQ=15 bash scripts/run_cwipc_native_plan.sh

# 全量 sweep + finalize 选 winner + gate
TRACK=sweep SWEEP_JOBS=2 bash scripts/run_cwipc_native_plan.sh
TRACK=finalize PRODUCTION_TAG=B1_hybrid_official bash scripts/run_cwipc_native_plan.sh

# 生产 Stage1 重建（B1 hybrid + official 滤波）
bash scripts/run_stage1_native.sh

# SuperPC ENH（需 winner 362 帧）
TRACK=enh bash scripts/run_cwipc_native_plan.sh

# 一键：quick + 全量 + finalize + enh
TRACK=all SWEEP_JOBS=2 bash scripts/run_cwipc_native_plan.sh
```

**生产默认（2026-06-20 更新）**：`N0_cwipc_official`（pure cwipc + official 滤波）。  
全量编排：`bash scripts/run_full_n0_v2.sh` · 结果见 [`N0_V2_RESULTS.md`](N0_V2_RESULTS.md)。

旧默认 `B1_hybrid_official` 仍可作为对照 variant 运行。

**主 Gate**：recon vs HE（`eval_native_gate.py`），相对 PGDR baseline 改善 ≥2%。

**补帧**：`retry_missing_recon.py` 先 official/relaxed 重试，仍缺失则从 `stage1_pgdr_val362` baseline 拷贝（VH 部分帧 official 滤波会空点云）。

状态：`output/cwipc_native/native.state`

## 已移除

Stage2 几何 polish（SOR/voxel）— 边际 <1%，并入 CWIPC 滤波链。
