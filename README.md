# DQPC-GC2026-PointPower

UVG Grand Challenge 2026 — **赛道一（UVG-CWI-DQPC）**  
双线 Processing Track：**Full Pipeline**（研发）+ **Enhancement Only**（**竞技提交**）

| 轨道 | 当前方案 | 状态 |
|------|----------|------|
| **Enhancement Only**（竞技提交） | **PD-LTS light + density refine** | ✅ 提交包就绪；val565 **17.504 mm**（优于 CG 17.552 mm） |
| **Enhancement Only**（旧线） | SuperPC `blend_cg` | 研发对照；val565 **20.579 mm**（劣于 CG） |
| **Full Pipeline N0 v2** | RGBD → N0 Stage1 → SuperPC | ✅ 全量跑通（2155 帧） |

---

## 学长汇报 / 答辩（推荐入口）

| 文档 | 路径 |
|------|------|
| **交付物索引** | [`docs/meeting_delivery/README.md`](docs/meeting_delivery/README.md) |
| **总思路与答辩提示** | [`docs/meeting_delivery/PROJECT_STRATEGY_REPORT.md`](docs/meeting_delivery/PROJECT_STRATEGY_REPORT.md) |
| **val565 Excel 说明** | [`docs/meeting_delivery/VAL565_METRICS_XLSX.md`](docs/meeting_delivery/VAL565_METRICS_XLSX.md) |
| **指标 Excel** | [`docs/meeting_delivery/val565_gc_baseline_metrics.xlsx`](docs/meeting_delivery/val565_gc_baseline_metrics.xlsx) |

本地运行产物镜像：`output/meeting_delivery/`（与 `docs/meeting_delivery/` 同步，不入库）

重新生成：`bash scripts/prepare_meeting_delivery.sh`

---

## 当前进度（2026-06-29）

### Enhancement Only — 官方 gc_baseline（val565，564 帧）

| 方案 | chamfer (mm) | vs CG | 角色 |
|------|-------------|-------|------|
| CG baseline | 17.552 | — | 参照 |
| **PD-LTS density（提交）** | **17.504** | **+0.048** | 正式竞技方案 |
| vh_snap0 | 17.440 | +0.112 | ablation，不进提交包 |
| SuperPC blend_cg（旧） | 20.579 | −3.03 | 已放弃 |

### 比赛源码包（向 UVG 提交）

- **当前提交**：[`submissions/GC2026_Team_EnhancementOnly/`](submissions/GC2026_Team_EnhancementOnly/)（PD-LTS density）
- 构建：`bash scripts/build_pdlts_density_submission.sh`
- 冒烟：`bash scripts/verify_submission_enhancement_only.sh`
- 旧 SuperPC 包（对照）：[`submissions/GC2026_Team/`](submissions/GC2026_Team/)

提交前待填：`submissions/GC2026_Team_EnhancementOnly/README.md` 中的 **Team Members**

### Full Pipeline N0 v2

| 项目 | 状态 |
|------|------|
| RGBD `.bag` | ✅ 12/12 序列 |
| Stage1 tag | `N0_cwipc_official` |
| 全量 ENH | ✅ 2155 帧（SuperPC 线） |

详见 [`docs/N0_V2_RESULTS.md`](docs/N0_V2_RESULTS.md)

---

## 仓库结构

| 路径 | 用途 |
|------|------|
| [`AGENTS.md`](AGENTS.md) | Cursor Agent 入门 |
| [`docs/meeting_delivery/`](docs/meeting_delivery/) | **学长汇报**：报告 + CSV + Excel + gate 快照 |
| [`docs/`](docs/) | 架构、CWIPC、N0 v2、迁移 |
| [`scripts/`](scripts/) | 推理、评估、Stage1、交付脚本 |
| [`submissions/GC2026_Team_EnhancementOnly/`](submissions/GC2026_Team_EnhancementOnly/) | **UVG 竞技提交源码**（PD-LTS） |
| [`submissions/GC2026_Team/`](submissions/GC2026_Team/) | 旧 SuperPC 提交包（对照） |
| [`output/val_grid/gate_decision.json`](output/val_grid/gate_decision.json) | SuperPC gate（历史） |
| [`output/enh_refine_p0_p1_p2/gate_decision.json`](output/enh_refine_p0_p1_p2/gate_decision.json) | PD-LTS refine gate（运行时） |

**本仓库不包含：** `data/`、`models/`、`code/` 克隆、ENH PLY 与 tar 大文件（见 `.gitignore`）。

---

## 快速复现

### Enhancement Only — PD-LTS density（竞技提交）

```bash
export GC2026_ROOT=/path/to/this/repo
git clone https://github.com/yanbiao1/PD-LTS code/PD-LTS   # 或 bash submissions/.../src/download_pdlts.sh
conda create -n superpc python=3.9 -y && conda activate superpc
pip install -r submissions/GC2026_Team_EnhancementOnly/requirements.txt

cd submissions/GC2026_Team_EnhancementOnly
bash src/download_pdlts.sh
bash src/setup_pdlts_deps.sh
bash src/run_smoke.sh    # 2 帧冒烟
bash src/run.sh          # 全量 2155 帧
```

### Enhancement Only — SuperPC 旧线（对照）

```bash
git clone https://github.com/sair-lab/SuperPC code/SuperPC
source scripts/env_setup.sh
bash scripts/run_enhancement_only.sh
```

### Full Pipeline N0 v2

```bash
bash scripts/install_cwipc.sh          # 需 librealsense
bash scripts/run_full_n0_v2.sh
bash scripts/watch_full_n0_v2.sh
```

---

## 如何把代码包下载到本机

```bash
git clone https://github.com/AntonyTang-AT/GC2026-UVG-FullPipeline-SuperPC.git
cd GC2026-UVG-FullPipeline-SuperPC/submissions/GC2026_Team_EnhancementOnly
```

向 UVG 官方提交 **GitHub PR**（源码目录），不是 PLY tar 包。

---

## 关键脚本

| 脚本 | 用途 |
|------|------|
| `scripts/prepare_meeting_delivery.sh` | 生成 docs + 镜像 output 交付物 |
| `scripts/build_pdlts_density_submission.sh` | 构建 PD-LTS 提交包 |
| `scripts/verify_submission_enhancement_only.sh` | 提交包冒烟验证 |
| `scripts/run_full_n0_v2.sh` | Full Pipeline N0 v2 全量 |
| `scripts/check_integrity.sh` | 迁移后完整性检查 |

完整列表：[`scripts/README.md`](scripts/README.md)

---

## 硬件

2× NVIDIA RTX 5090；PD-LTS / SuperPC 均支持双卡分片推理。

## 许可与引用

- 本仓库脚本：课题组 GC2026 研究使用。
- **SuperPC**：[sair-lab/SuperPC](https://github.com/sair-lab/SuperPC)
- **PD-LTS**：[yanbiao1/PD-LTS](https://github.com/yanbiao1/PD-LTS)
- **UVG 数据**：[ultravideo.fi](https://ultravideo.fi/UVG-CWI-DQPC/GC2026/) — 请勿二次分发。
