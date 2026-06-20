# GC2026 — Agent 入门指南

> **目标读者**：在新服务器上接手的 Cursor Agent（或任何自动化助手）。  
> **项目根目录**：`/root/autodl-tmp/GC2026`（迁移后请按实际路径调整 `GC2026_ROOT`）

## 1. 项目在做什么

这是 **UVG Grand Challenge 2026 赛道一（UVG-CWI-DQPC）** 的参赛工程。任务：把 **Consumer-Grade（CG）点云** 增强为更接近 **High-End（HE）** 质量的点云。

我们实现 **两条 Processing Track**（同一增强模型 **SuperPC**）：

| Track | 输入 | 输出 | 状态 |
|-------|------|------|------|
| **Enhancement Only**（竞技提交） | 官方 CGv2 PLY（15fps） | ENH PLY | **已完成**（2155 帧；Val improvement +14.5 mm） |
| **Full Pipeline N0 v2**（研发主选） | RGBD → N0 Stage1 → SuperPC | ENH PLY | **全量跑通**（2155 帧；相对 B1 ENH ↓155 mm） |

**比赛提交**：只交 `submissions/GC2026_Team/` 源码包（几 MB），**不含 PLY**。组织方在官方输入上跑我们的脚本。

---

## 2. 先读这些文件（按顺序）

1. [`README.md`](README.md) — 人类可读总览
2. [`docs/N0_V2_RESULTS.md`](docs/N0_V2_RESULTS.md) — **N0 v2 全量结果 vs B1**
3. [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — 管线架构与数据流
4. [`docs/CWIPC_NATIVE_PIPELINE.md`](docs/CWIPC_NATIVE_PIPELINE.md) — CWIPC Stage1 + SuperPC
5. [`docs/INTEGRITY.md`](docs/INTEGRITY.md) — 完整性检查清单（迁移后必跑）
6. [`docs/MIGRATION.md`](docs/MIGRATION.md) — 新服务器 bootstrap
7. [`output/val_grid/gate_decision.json`](output/val_grid/gate_decision.json) — **最优推理超参**（gate 结果）
8. [`scripts/README.md`](scripts/README.md) — 脚本速查

---

## 3. 目录地图

```
GC2026/
├── AGENTS.md              ← 本文件
├── README.md
├── docs/                  ← 架构 / 迁移 / 完整性文档
├── scripts/               ← 全部管线脚本（71 个 .sh/.py）
├── submissions/GC2026_Team/   ← 向 UVG 提交的源码（git 跟踪）
├── code/SuperPC/          ← SuperPC 上游克隆（gitignore，需单独 clone）
├── data/                  ← UVG 数据与索引（gitignore，~868GB）
│   ├── raw/UVG-CWI-DQPC/  ← 12 序列 CG + bag
│   └── processed/         ← pair 列表、帧映射、rgbd_pairs
├── models/superpc_pretrained/ ← 官方权重（gitignore）
└── output/                ← 推理结果、评估、日志（gitignore 大文件）
    ├── submission_candidate/  ← Enhancement Only 最终 ENH（19GB）
    ├── val_grid/              ← val 网格搜索 + gate_decision.json
    └── cwipc_install_cache/   ← librealsense 源码缓存（可重建）
```

**不要误删**：`data/raw/`、`models/`、`output/submission_candidate/`、`output/val_grid/gate_decision.json`。

---

## 4. 两套 Python 环境

| 用途 | 环境 | Python | 激活方式 |
|------|------|--------|----------|
| SuperPC 推理 / 评估 | conda `superpc` | 3.9 | `source scripts/env_setup.sh` |
| cwipc / bag 回放 / Stage1 | 系统 Python + wheels | **3.12** | `source output/cwipc_env.sh` |

要点：

- RTX 5090 需要 `torch==2.8.0+cu128`，升级后跑 `bash scripts/rebuild_extensions.sh`
- cwipc deb 与 miniconda 的 libstdc++ 冲突 → `cwipc_env.sh` 里 `LD_PRELOAD` 系统 libstdc++
- **当前阻塞**：`librealsense2.so.2.56` 未安装 → cwipc bag 回放不可用 → `rgbd_pairs.txt` 为空

---

## 5. 管线阶段（Agent 应理解的顺序）

```
[下载] CGv2 + RGBD zip + SuperPC 权重
    ↓
[安装] install_cwipc.sh（librealsense + cwipc deb）
    ↓
[索引] prepare_uvg_pairs.py → uvg_frame_map.py → map_rgbd_pairs.py
    ↓
[Stage1] rgbd_to_cg.py：bag → 自建 CG PLY
    ↓
[Stage2] run_superpc_infer.py：CG → ENH（KNN 颜色迁移）
    ↓
[评估] evaluate_uvg.py（Chamfer n=20k）→ val_gate.py
    ↓
[提交] make_submission.py → submissions/GC2026_Team/manifest.json
```

**Enhancement Only 快捷路径**（跳过 Stage1）：

```bash
source scripts/env_setup.sh
UVG_CG_VERSION=v2 bash scripts/run_enhancement_only.sh
bash scripts/post_submission_candidate.sh
```

**Full Pipeline 入口**：`bash scripts/run_full_pipeline.sh`（需 librealsense + rgbd_pairs）

---

## 6. 当前完成度（2026-06-17 核查）

### 已完成

| 项目 | 证据 |
|------|------|
| 12 序列 RGBD `.bag` | 每序列 **8/8** |
| 12 序列 CGv2 PLY | `all_cg_only_cgv2.txt` **2155** 帧 |
| Enhancement Only 全量 | `output/submission_candidate/` **2155** PLY |
| val gate 最优配置 | `kitti360_com.pth` + `blend_cg` + voxel **3.0mm**，`use_vision=0` |
| val Chamfer 提升 | CG 85.96 → ENH 75.33（**+10.64**，n=20k） |
| SuperPC 官方权重 | kitti360 / shapenet / tartanair 各 ~144MB |
| CPU eval（无 GPU） | `output/overnight_nogpu.state`: `cpu_eval=done` |

### 未完成 / 阻塞

| 项目 | 说明 |
|------|------|
| **librealsense 运行时** | `librealsense2.so.2.56` 缺失；`install_cwipc.sh` 需续编 |
| **rgbd_pairs.txt** | **0 条**；需 librealsense 后跑 `post_rgbd_install.sh` / `map_rgbd_pairs.py` |
| **Full Pipeline 产物** | `output/full_pipeline_candidate/` 不存在 |
| **Full Pipeline manifest** | 当前 `manifest.json` 仍为 Enhancement Only |

运行完整性检查：`bash scripts/check_integrity.sh`

---

## 7. 关键配置（gate 胜者）

来自 `output/val_grid/gate_decision.json`：

```json
{
  "checkpoint": "kitti360_com.pth",
  "output_mode": "blend_cg",
  "use_vision": 0,
  "blend_voxel_mm": 3.0
}
```

全量推理脚本会读此 gate；不要在没有重新跑 val_grid 的情况下随意改超参。

---

## 8. 新服务器上 Agent 的典型任务

### 8.1 验收迁移

```bash
cd /root/autodl-tmp/GC2026   # 或实际路径
bash scripts/check_integrity.sh
source scripts/env_setup.sh && python scripts/verify_superpc_ckpt.py
nvidia-smi && python -c "import torch; print(torch.cuda.is_available())"
```

### 8.2 修复 librealsense（Full Pipeline 前置）

```bash
bash scripts/install_cwipc.sh          # 可能需数小时，建议 -j1
source output/cwipc_env.sh
/usr/local/libexec/cwipc/cwipc_realsense2_install_check
```

### 8.3 生成 rgbd_pairs 并跑 Stage1 冒烟

```bash
source output/cwipc_env.sh
bash scripts/post_rgbd_install.sh      # 或 SEQ_FILTER=... 限定序列
python scripts/map_rgbd_pairs.py ...
bash scripts/run_stage1_rgbd_only.sh   # 或 run_full_pipeline_val.sh
```

### 8.4 仅重跑 Enhancement（GPU 恢复后）

```bash
bash output/gpu_pending.sh             # 或手动 run_enhancement_only.sh
```

---

## 9. 迁移相关

- 脚本：[`scripts/migrate_to_new_server.sh`](scripts/migrate_to_new_server.sh)（rsync 项目 + `superpc` conda）
- 排除列表：[`scripts/migrate_exclude.txt`](scripts/migrate_exclude.txt)
- 详细步骤：[`docs/MIGRATION.md`](docs/MIGRATION.md)

迁移后 **不会自动带上**：GPU 驱动验证、librealsense 系统库、cwipc Python 3.12 包（需在新机重装）。

---

## 10. 外部依赖

| 组件 | 仓库 / 来源 |
|------|-------------|
| SuperPC | https://github.com/sair-lab/SuperPC → `code/SuperPC` |
| cwipc | https://github.com/cwi-dis/cwipc v7.7.5 |
| librealsense | https://github.com/IntelRealSense/librealsense v2.56.5 |
| UVG 数据 | https://ultravideo.fi/UVG-CWI-DQPC/GC2026/ |
| SuperPC 权重 | Google Drive Model Zoo → `scripts/download_pretrained.sh` |

---

## 11. Agent 行为约定

- **改代码前**：先 `source scripts/env_setup.sh`，确认 `GC2026_ROOT` 正确
- **大文件**：不要 commit `data/`、`models/`、`output/**/*.ply`
- **提交比赛**：只动 `submissions/GC2026_Team/`，PLY 在本地 `output/` 备份
- **删 zip / 缓存前**：用 `scripts/extract_rgbd_zips.sh` 的 `VERIFY_BEFORE_RM=1` 逻辑或 `check_integrity.sh` 确认 bag 齐全
- **评估内存**：CPU 评估用 KDTree 路径；避免并发多进程 evaluate

---

## 12. 刷新状态报告

```bash
source scripts/env_setup.sh
python scripts/generate_status_report.py
# → output/status_report.json + output/status_report.md
```
