# 新服务器迁移指南

将 GC2026 工程从 AutoDL / 旧实例迁移到 **全新 GPU 服务器** 的步骤。面向人类操作者与接手的 Agent。

---

## 0. 迁移前检查（源机器）

```bash
cd /root/autodl-tmp/GC2026
bash scripts/check_integrity.sh
df -h /root/autodl-tmp
```

确认：12 序列 bag 8/8、`submission_candidate` 2155 帧、权重齐全。  
记录 `output/val_grid/gate_decision.json` 已存在。

---

## 1. 需要迁移的内容

### 必迁（~900GB+）

| 内容 | 路径 | 说明 |
|------|------|------|
| 项目树 | `/root/autodl-tmp/GC2026/` | 含 scripts、submissions、output 小文件 |
| UVG 数据 | `GC2026/data/raw/UVG-CWI-DQPC/` | ~868GB |
| 处理索引 | `GC2026/data/processed/` | 几 MB，必带 |
| SuperPC 权重 | `GC2026/models/` | ~480MB |
| ENH 产物 | `GC2026/output/submission_candidate/` | ~19GB |
| SuperPC 代码 | `GC2026/code/SuperPC/` | git clone 也可在新机重做 |

### 建议迁

| 内容 | 路径 | 说明 |
|------|------|------|
| conda `superpc` | `/root/miniconda3/envs/superpc/` | ~11GB，含 PyTorch 2.8+cu128 |
| val_grid | `output/val_grid/` | ~75GB，含 gate 实验；可只迁 `gate_decision.json` + 胜者目录 |
| cwipc 缓存 | `output/cwipc_install_cache/` | ~163MB，免 re-download librealsense 源码 |

### 可不迁（可重建或已删）

- `pip-cache/`
- `data/raw/.../__zip/*.zip`（bag 已解压校验后）
- `output/*_submission.tar.gz`（与目录重复）
- `output/speedtest_*`、`*_nohup.out`
- 见 [`scripts/migrate_exclude.txt`](../scripts/migrate_exclude.txt)

---

## 2. 迁移方式

### 方式 A：rsync 脚本（已用过）

```bash
export SSHPASS='***'
export DST_HOST=connect.westd.seetacloud.com
export DST_PORT=53145
export DST_USER=root
export DST_ROOT=/root/autodl-tmp

bash scripts/migrate_to_new_server.sh
# 日志：output/migrate_rsync.log
```

两阶段：① GC2026 项目（带 exclude）② `superpc` conda 环境。

### 方式 B：手动 rsync

```bash
rsync -avh --partial --append-verify \
  --exclude-from=scripts/migrate_exclude.txt \
  /root/autodl-tmp/GC2026/ user@newhost:/root/autodl-tmp/GC2026/
```

### 方式 C：仅迁代码 + 索引（数据新机重下）

适合带宽有限：只迁 git 仓库、`data/processed/`、`submissions/`、`output/val_grid/gate_decision.json`，数据用官方脚本重下。

---

## 3. 新服务器 Bootstrap（Agent 按序执行）

### Step 1：目录与完整性

```bash
export GC2026_ROOT=/root/autodl-tmp/GC2026   # 按实际修改
cd "$GC2026_ROOT"
bash scripts/check_integrity.sh
```

### Step 2：Conda superpc

若未 rsync 环境：

```bash
conda create -n superpc python=3.9 -y
conda activate superpc
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
pip install open3d plyfile tqdm transformers accelerate Pillow numpy einops scikit-learn h5py transforms3d gdown
git clone https://github.com/sair-lab/SuperPC code/SuperPC
bash scripts/download_pretrained.sh
bash scripts/rebuild_extensions.sh
```

若已 rsync：只需 `source scripts/env_setup.sh` 并验证 CUDA。

### Step 3：cwipc + librealsense（Full Pipeline 必需）

```bash
bash scripts/install_cwipc.sh
source output/cwipc_env.sh
/usr/local/libexec/cwipc/cwipc_realsense2_install_check
```

失败时查看 `output/cwipc_install_cache/librealsense-2.56.5/build/` 续编。

### Step 4：GPU 验证

```bash
nvidia-smi
source scripts/env_setup.sh
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
python scripts/verify_superpc_ckpt.py
```

### Step 5：续跑待定任务

```bash
bash output/gpu_pending.sh
```

或分步：

```bash
UVG_CG_VERSION=v2 bash scripts/run_enhancement_only.sh   # 如需重跑
bash scripts/post_rgbd_install.sh                        # RGBD 映射
bash scripts/run_full_pipeline_val.sh                      # Full 冒烟
```

---

## 4. 迁移后 Agent 应更新的路径

若 `GC2026_ROOT` 不是 `/root/autodl-tmp/GC2026`：

1. 所有脚本通过 `env_setup.sh` 自动推导，**一般无需改代码**
2. 硬编码路径在 `gate_decision.json` 的 `experiment_dir` — 仅影响追溯，不影响推理
3. `generate_status_report.py` 内 `GC2026_ROOT` 常量 — 迁移后跑一次即可刷新报告

---

## 5. 新服务器验收标准

| # | 检查 | 通过条件 |
|---|------|----------|
| 1 | `check_integrity.sh` | 无 FAIL（librealsense 可为 WARN） |
| 2 | CUDA + SuperPC | `verify_superpc_ckpt.py` OK |
| 3 | Enhancement 产物 | 2155 PLY 可读 |
| 4 | librealsense | `cwipc_realsense2_install_check` OK |
| 5 | rgbd_pairs | `wc -l rgbd_pairs.txt` > 0 |
| 6 | Full Pipeline 冒烟 | `run_full_pipeline_val.sh` 产出 val ENH |

前 3 项满足即可继续用 **Enhancement Only** 提交；4–6 为 Full Pipeline 前置。

---

## 6. 相关文档

- Agent 总览：[`AGENTS.md`](../AGENTS.md)
- 架构：[`ARCHITECTURE.md`](ARCHITECTURE.md)
- 完整性：[`INTEGRITY.md`](INTEGRITY.md)
- Full Pipeline 计划：[`../output/RGBD_TO_CG_PLAN.md`](../output/RGBD_TO_CG_PLAN.md)
