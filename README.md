# GC2026-UVG-FullPipeline-SuperPC

UVG Grand Challenge 2026 — **赛道一（UVG-CWI-DQPC）**  
双线 Processing Track：**Full Pipeline**（主选）+ **Enhancement Only**（竞技提交），增强模型均为 **SuperPC**。

## 当前进度（2026-06-20）

| 项目 | 状态 |
|------|------|
| **Enhancement Only**（官方 CG → SuperPC） | ✅ **已完成** — 2155 帧；Val ENH **71.5 mm**，improvement **+14.5 mm**（n=20k）→ **竞技提交首选** |
| **Full Pipeline N0 v2**（RGBD → N0 Stage1 → SuperPC） | ✅ **全量跑通** — 2155 recon + 2155 ENH；Val ENH **196 mm**（B1: 351 mm） |
| RGBD `.bag` 数据 | ✅ 12/12 序列齐全 |
| Stage1 生产 tag | **`N0_cwipc_official`**（替代 B1 hybrid；Val recon HE 254 mm vs B1 351 mm） |
| 最优 SuperPC 配置 | `kitti360_com.pth` + `blend_cg` + voxel 3.0mm + per-seq recon-enh config |
| 比赛源码包 | [`submissions/GC2026_Team/`](submissions/GC2026_Team/) |

**N0 v2 详细结果**：[`docs/N0_V2_RESULTS.md`](docs/N0_V2_RESULTS.md)  
**CWIPC-Native 管线说明**：[`docs/CWIPC_NATIVE_PIPELINE.md`](docs/CWIPC_NATIVE_PIPELINE.md)  
**Agent 接手**：[`AGENTS.md`](AGENTS.md) → `bash scripts/check_integrity.sh`

---

## 两条轨道对比（Val362, n=20k）

| 轨道 | ENH vs 官方 CG | improvement | 说明 |
|------|----------------|-------------|------|
| Enhancement Only | **71.5 mm** | **+14.5 mm** | 向 UVG 提交 ENH 点云 |
| Full Pipeline N0 v2 | 196.3 mm | -110.5 mm | 研发轨；相对 B1 改善 155 mm |
| Full Pipeline B1（旧） | 351.1 mm | -265.1 mm | 已被 N0 v2 替代 |

---

## 仓库结构

| 路径 | 用途 |
|------|------|
| [`AGENTS.md`](AGENTS.md) | Cursor Agent 入门（目标、环境、常用命令） |
| [`docs/`](docs/) | 架构、CWIPC 管线、N0 v2 结果、迁移指南 |
| [`scripts/`](scripts/) | 推理、评估、Stage1、Full Pipeline 编排（100+ 脚本） |
| [`scripts/run_full_n0_v2.sh`](scripts/run_full_n0_v2.sh) | **N0 v2 全量一键编排**（Stage1 → SuperPC → Post） |
| [`scripts/watch_full_n0_v2.sh`](scripts/watch_full_n0_v2.sh) | N0 v2 进度仪表盘（含 tar 静默阶段提示） |
| [`scripts/check_integrity.sh`](scripts/check_integrity.sh) | 迁移后完整性检查 |
| [`submissions/GC2026_Team/`](submissions/GC2026_Team/) | **向 UVG 提交的源码包**（仅代码，不含 PLY） |
| [`output/val_grid/gate_decision.json`](output/val_grid/gate_decision.json) | SuperPC val 网格搜索最优超参 |

**本仓库不包含：** UVG 数据集（`data/`）、SuperPC 权重（`models/`）、第三方 `code/SuperPC` 克隆、ENH 点云与 tar 包（各 10–23 GB，见 `.gitignore`）。

---

## 如何把「需要提交的代码包」下载到本机

比赛要求提交 **源码目录** `submissions/GC2026_Team/`，**不是** PLY 压缩包。

### 方式一：克隆本仓库（推荐）

```bash
git clone https://github.com/AntonyTang-AT/GC2026-UVG-FullPipeline-SuperPC.git
cd GC2026-UVG-FullPipeline-SuperPC/submissions/GC2026_Team
```

打包提交：

```bash
cd GC2026-UVG-FullPipeline-SuperPC/submissions
tar -czf GC2026_Team_submit.tar.gz GC2026_Team
```

### 方式二：GitHub 网页 Download ZIP

1. https://github.com/AntonyTang-AT/GC2026-UVG-FullPipeline-SuperPC  
2. **Code → Download ZIP**  
3. 解压后进入 `submissions/GC2026_Team/`

### 方式三：scp 从训练服务器

```bash
scp -r -P <端口> root@<服务器>:/root/autodl-tmp/GC2026/submissions/GC2026_Team ./GC2026_Team
```

### 不要误下载（非源码提交）

| 路径 | 说明 | 大小约 |
|------|------|--------|
| `output/submission_candidate/` | Enhancement Only ENH | ~19 GB |
| `output/full_pipeline_n0_v2_candidate/` | N0 v2 ENH | ~39 GB |
| `output/*_submission.tar.gz` | PLY 压缩包 | 11–23 GB |
| `data/raw/` | 赛方数据集 | ~163 GB+ |

---

## 快速复现

### Enhancement Only（竞技轨）

```bash
git clone https://github.com/sair-lab/SuperPC code/SuperPC
conda create -n superpc python=3.9 -y && conda activate superpc
pip install torch open3d plyfile tqdm transformers accelerate Pillow numpy
bash scripts/download_pretrained.sh
# 下载 UVG CG 到 data/raw/UVG-CWI-DQPC/

source scripts/env_setup.sh
bash scripts/run_enhancement_only.sh
bash scripts/post_submission_candidate.sh
```

### Full Pipeline N0 v2（研发轨）

前置：cwipc + librealsense 已安装（`bash scripts/install_cwipc.sh`），RGBD bag 齐全。

```bash
# Val362 快速验证（362 帧）
bash scripts/run_val362_n0_v2.sh

# 全量 2155 帧（Stage1 → SuperPC → eval → pack，约 6–7h）
bash scripts/run_full_n0_v2.sh

# 终端进度（10s 刷新；tar 阶段显示文件大小变化）
bash scripts/watch_full_n0_v2.sh
tail -f output/full_n0_v2.log
```

仅跑 SuperPC（Stage1 已完成）：

```bash
STOP_AFTER_PHASE=2 bash scripts/run_full_n0_v2.sh   # 跳过 Post
```

补全缺帧后重跑 gate：

```bash
bash scripts/fill_missing_n0_v2.sh
```

### Full Pipeline 分步（旧版 B1 流程，仍可用）

```bash
bash scripts/download_cgv2.sh
python scripts/prepare_uvg_pairs.py --cg-version v2
bash scripts/install_cwipc.sh
bash scripts/run_stage1_native_parallel.sh      # 现默认 N0 tag
bash scripts/run_full_pipeline.sh
bash scripts/post_full_pipeline.sh
```

环境变量：`UVG_CG_VERSION=v2`、`TAG=N0_cwipc_official`（Stage1 默认）。

---

## 关键脚本索引

| 脚本 | 用途 |
|------|------|
| `run_full_n0_v2.sh` | N0 v2 全量编排（phase0–3，可 `STOP_AFTER_PHASE`） |
| `run_val362_n0_v2.sh` | Val362 N0 实验 + 对比报告 |
| `run_stage1_native_parallel.sh` | 并行 Stage1（TT/VH N0 override） |
| `select_stage1_production_tag.py` | 生产 tag 评选（默认 N0） |
| `fill_missing_n0_v2.sh` | 缺帧 hybrid 重试 + PGDR/B2 回填 |
| `retry_missing_recon.py` | 单帧 cwipc 重试 |
| `eval_native_gate.py` | recon/enh vs HE gate |
| `compare_val362_baselines.py` | N0 vs B1 对比报告 |
| `post_full_pipeline.sh` | manifest + evaluate + temporal + tar |
| `run_dual_gpu_infer.sh` | 双卡 SuperPC 推理 |

完整列表见 [`scripts/README.md`](scripts/README.md)。

---

## 比赛提交说明

- 提交目录：**[`submissions/GC2026_Team/`](submissions/GC2026_Team/)**（对齐 [UVG-CWI/submissions](https://github.com/UVG-CWI/submissions)）
- 组织方在 **官方输入** 上运行代码，**提交包内不含 PLY**
- 当前 manifest 为 **Enhancement Only**；Full Pipeline manifest 在 `manifest_full_pipeline.json`

## 硬件

2× NVIDIA RTX 5090；双卡推理：`scripts/run_dual_gpu_infer.sh`

## 许可与引用

- 本仓库脚本：课题组 GC2026 研究使用。
- **SuperPC**：[sair-lab/SuperPC](https://github.com/sair-lab/SuperPC)
- **UVG-CWI-DQPC 数据**：[ultravideo.fi](https://ultravideo.fi/UVG-CWI-DQPC/GC2026/) — 请勿二次分发。
