# GC2026 问题根因分析与调整方向

依据 [Challenge 官网](https://ultravideo.fi/UVG-CWI-DQPC/GC2026/)、[提案 PDF](https://openreview.net/pdf?id=qW36Dkap3M)、[Submission 规范](https://github.com/UVG-CWI/submissions)。

## 竞赛要求摘要

| 项目 | 要求 |
|------|------|
| Track | **Enhancement Only**：输入已有 CG `.ply`，输出增强 `.ply` + RGB |
| 排名主指标 | **Chamfer Distance**（对称最近邻，越低越好）+ Accuracy / Completeness |
| 附加 | 颜色 PSNR、PCQM、投影 SSIM/LPIPS、**时序一致性**、Runtime |
| 数据划分 | Train 8 序列 / Val 2（TicTacToe, VictoryHeart）/ Test 2（GT 不公开） |
| 可选输入 | Raw RGBD（`.bag`）用于 Full Pipeline 或 Enhancement 的视觉条件 |

## 为何本地评估显示「官方权重更差」？

### 1. 评估子采样过低（已修复）

- CG ~**52 万点/帧**，HE ~**217 万点/帧**，此前 Chamfer 仅用 **4096** 点子采样 → 方差大、系统性偏差。
- 同一 val 子集：`n=4096` 时 ENH 劣于 CG（Δ ≈ **−12.8**）；`n=20000` 时 ENH 优于 CG（20 帧快测 Δ ≈ **+21.4**）。
- **调整**：`evaluate_uvg.py` 默认 `n_samples=20000`，`max_load_points=100000`。

### 2. 输出点数远少于输入 CG（核心结构问题）

| 来源 | 点数/帧（BlueSpeech 示例） |
|------|---------------------------|
| CG 输入 | 528,129 |
| HE 真值 | 2,177,315 |
| 当前 ENH（kitti360） | 46,080 |

SuperPC 按 **completion/upsampling** 训练：从稀疏/损坏输入生成新点云。UVG CG 已是 **稠密** 点云；用 11520 点进模型、只输出 46080 点 = **丢弃原有 CG 几何**，Completeness 会受损。

- **调整**：新增 `run_superpc_infer.py --output-mode blend_cg`：模型输出 + 原始 CG 体素融合（默认 voxel 2mm），保留密度与颜色。

### 3. Vision conditioning 未启用

- 三个官方 `.pth` 均含 `vision_encoder`；训练/测试默认 `use_vision_conditioning=true`。
- 当前推理 `image_tensor=None`，视觉分支空转，性能损失。
- RGBD 数据未下载到本机（仅 CG/HE PLY）；需按官网命令拉取 `RGBD` 后启用 `--use-vision-conditioning`。

### 4. 域偏移：KITTI-360 vs UVG 室内人体

- `kitti360_com.pth` 面向户外驾驶；UVG 为室内动态人体。
- 建议对比 **`tartanair_com.pth`**（仿真户外/室内混合）及 **`shapenet_com.pth`**（2048→8192 点数配置）。

### 5. 任务目标与 SuperPC 默认假设不一致

- Challenge：统一 **去噪 + 补全 + 上采样 + 时序一致 + 颜色**。
- 当前管线：单帧、无时序、无颜色 PSNR 评估、无投影 perceptual 指标。
- **时序平滑**在随机/smoke 权重下更差；官方权重下需重评后再决定是否使用。

### 6. Smoke 权重误导

- 随机 init 的 smoke 权重曾让 val 略优于 CG，与官方权重无关，不能作质量参考。

## 已实施代码调整

1. `evaluate_uvg.py`：更高默认子采样 + CUDA Chamfer。
2. `run_superpc_infer.py`：`--output-mode model|blend_cg|filter_cg`，RGBD 路径探测 + vision 加载。
3. `uvg_io.py`：体素融合、CG 离群点滤波、`cg_to_rgbd_color_path`。
4. `make_submission.py`：manifest 增加 `processing_track`、`coordinate_system`。
5. `run_dual_gpu_infer.sh` / `rerun_with_official_ckpt.sh`：双卡与绝对路径修复。

## 建议实验顺序

1. **重评官方结果**（`n=20000`）：`evaluation_val_summary.json`。
2. **Val 上对比 output-mode**：`model` vs `blend_cg` vs `filter_cg`（CG 基线++）。
3. **Val 上对比 checkpoint**：tartanair / shapenet / kitti360（各用匹配 num_points）。
4. **下载 RGBD** 后加 vision，再跑 val。
5. 选定最佳配置后 **双卡全量** → 打包提交（勿提交 smoothed 除非指标确认更优）。

## 参考命令

```bash
source scripts/env_setup.sh

# 重评（官方 n=20000）
python scripts/evaluate_uvg.py \
  --pairs-file data/processed/val_pairs.txt \
  --enhanced-root output/all_sequences_official \
  --n-samples 20000 \
  --out-json output/all_sequences_official/evaluation_val_n20k.json

# Val 实验：blend 模式（示例 tartanair）
python scripts/run_superpc_infer.py \
  --cg-list data/processed/val_cg_only.txt \
  --ckpt-path models/superpc_pretrained/tartanair_com.pth \
  --out-dir output/val_tartanair_blend \
  --num-points 11520 --target-num-points 46080 \
  --output-mode blend_cg --blend-voxel-mm 2.0
```
