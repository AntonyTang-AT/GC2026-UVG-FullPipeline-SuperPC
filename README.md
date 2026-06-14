# GC2026-UVG-FullPipeline-SuperPC

UVG Grand Challenge 2026 — **赛道一（UVG-CWI-DQPC）**  
双线 Processing Track：**Full Pipeline**（主选）+ **Enhancement Only**（保底），增强模型均为 **SuperPC**。

## 当前进度

| 项目 | 状态 |
|------|------|
| Enhancement Only（官方 CG → SuperPC） | **已完成** — 2155 帧 ENH，val Chamfer 提升 **+10.64**（n=20k） |
| Full Pipeline（RGBD → 自建 CG → SuperPC） | 脚本已就绪；val 两序列 RGBD 下载中 → val 快测 |
| 最优配置（gate） | `kitti360_com.pth` + `blend_cg` + voxel 3.0mm，`use_vision=0` |
| 比赛源码包 | 见 [`submissions/GC2026_Team/`](submissions/GC2026_Team/) |

更细状态见：[`output/status_report.md`](output/status_report.md)

## 仓库结构

| 路径 | 用途 |
|------|------|
| [`scripts/`](scripts/) | 推理、评估、下载、Full Pipeline 全链路脚本 |
| [`submissions/GC2026_Team/`](submissions/GC2026_Team/) | **向 UVG 提交的源码包**（仅代码，不含 PLY） |
| [`output/val_grid/gate_decision.json`](output/val_grid/gate_decision.json) | val 网格搜索最优超参 |

**本仓库不包含：** UVG 数据集（`data/`）、SuperPC 权重（`models/`）、第三方 `code/SuperPC` 克隆、ENH 点云（`output/submission_candidate/` 约 19GB）。

---

## 如何把「需要提交的代码包」下载到本机

比赛要求提交的是 **源码目录** `submissions/GC2026_Team/`（README + requirements + manifest + `src/` 脚本），**不是** 11GB 的 PLY 压缩包。

### 方式一：克隆本仓库（推荐）

在本机终端执行：

```bash
git clone https://github.com/AntonyTang-AT/GC2026-UVG-FullPipeline-SuperPC.git
cd GC2026-UVG-FullPipeline-SuperPC/submissions/GC2026_Team
```

需要向 UVG 交源码时，提交的就是 **`GC2026_Team` 这个文件夹里的全部内容**（或打成 zip，见下）。

打成 zip（在本机 `submissions` 目录下）：

```bash
cd GC2026-UVG-FullPipeline-SuperPC/submissions
tar -czf GC2026_Team_submit.tar.gz GC2026_Team
# Windows 可用 7-Zip 对 GC2026_Team 文件夹压缩
```

体积约 **几 MB～1 MB 量级**（含 manifest 元数据，无点云）。

### 方式二：GitHub 网页下载（不用 git）

1. 打开 https://github.com/AntonyTang-AT/GC2026-UVG-FullPipeline-SuperPC  
2. 点击 **Code → Download ZIP**  
3. 解压后进入 `GC2026-UVG-FullPipeline-SuperPC-main/submissions/GC2026_Team/`  
4. 将该文件夹打包或按 [UVG-CWI/submissions](https://github.com/UVG-CWI/submissions) 规范提交

### 方式三：从 AutoDL 服务器直接拷到本机（scp）

在 **你自己的电脑** 上执行（把 `端口`、`用户名`、`服务器地址` 换成 AutoDL 控制台里的）：

```bash
# 只下载提交包目录
scp -r -P <端口> root@<AutoDL地址>:/root/autodl-tmp/GC2026/submissions/GC2026_Team ./GC2026_Team

# 或先在服务器打 tar，再下载单个文件（更快）
# 服务器上： cd /root/autodl-tmp/GC2026/submissions && tar -czf GC2026_Team.tar.gz GC2026_Team
scp -P <端口> root@<AutoDL地址>:/root/autodl-tmp/GC2026/submissions/GC2026_Team.tar.gz ./
```

Windows 可用 WinSCP、FileZilla，远程路径：`/root/autodl-tmp/GC2026/submissions/GC2026_Team`

### 不要误下载这些（不是「源码提交」）

| 路径 | 说明 | 大小约 |
|------|------|--------|
| `output/submission_candidate/` | ENH 点云目录 | ~19 GB |
| `output/submission_candidate_submission.tar.gz` | 本地备份用 PLY 包 | ~11 GB |
| `data/raw/` | 赛方数据集 | ~163 GB+ |

这些是结果或数据，**不是** UVG Processing Track 的源码提交格式。

---

## 本地快速复现（Enhancement Only）

```bash
# 1. 克隆 SuperPC（与本仓库并列）
git clone https://github.com/sair-lab/SuperPC code/SuperPC

# 2. Conda 环境（Python 3.9 + CUDA，详见 scripts/README.md）
conda create -n superpc python=3.9 -y && conda activate superpc
pip install torch open3d plyfile tqdm transformers accelerate Pillow numpy

# 3. 下载官方权重
bash scripts/download_pretrained.sh

# 4. 按 UVG 官网下载 CG 数据到 data/raw/UVG-CWI-DQPC/

source scripts/env_setup.sh
bash scripts/run_enhancement_only.sh
bash scripts/post_submission_candidate.sh
```

## Full Pipeline 流程

```bash
SEQ_FILTER=TicTacToe,VictoryHeart bash scripts/download_rgbd_aria2.sh
SEQ_FILTER=TicTacToe,VictoryHeart bash scripts/check_rgbd_download.sh
SEQ_FILTER=TicTacToe,VictoryHeart bash scripts/post_rgbd_install.sh
bash scripts/run_full_pipeline_val.sh          # val 362 帧
bash scripts/run_full_pipeline.sh              # 全量 2155 帧
bash scripts/post_full_pipeline.sh
```

坐标单位单测：`python scripts/test_rgbd_to_cg_units.py`

---

## 比赛提交说明

- 提交目录：**[`submissions/GC2026_Team/`](submissions/GC2026_Team/)**（对齐 [UVG-CWI/submissions](https://github.com/UVG-CWI/submissions)）
- 包含：`README.md`、`requirements.txt`、`manifest.json`、`src/` 下脚本
- 组织方在 **官方输入** 上运行你们的代码，**提交包内不含 PLY**
- 当前 `manifest.json` 为 **Enhancement Only**；Full Pipeline 全量跑通后替换为 Full 版 manifest 并改 `processing_track`

## 硬件

2× NVIDIA RTX 5090；双卡脚本：`scripts/run_dual_gpu_infer.sh`

## 许可与引用

- 本仓库脚本：课题组 GC2026 研究使用。
- **SuperPC**：[sair-lab/SuperPC](https://github.com/sair-lab/SuperPC)，使用权重请遵守其开源许可。
- **UVG-CWI-DQPC 数据**：仅从 [ultravideo.fi](https://ultravideo.fi/UVG-CWI-DQPC/GC2026/) 下载，请勿二次分发。
