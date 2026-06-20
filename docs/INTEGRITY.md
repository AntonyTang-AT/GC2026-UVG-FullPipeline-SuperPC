# 完整性检查清单

迁移到新服务器或长时间未操作后，运行：

```bash
bash scripts/check_integrity.sh
```

本文档说明各项检查的含义与手动验证方法。

---

## 1. 数据完整性

### 1.1 RGBD bag（Full Pipeline 硬需求）

每个序列应有 **8 个** `.bag`：

```bash
for s in PinkNoir TrumanShow VirtualLife TicTacToe VictoryHeart \
         OrangeKettlebell BlueSpeech BlueVolley BouncingBlue \
         FitFluencer GoodVision Mannequin; do
  n=$(find "$GC2026_ROOT/data/raw/UVG-CWI-DQPC/$s" -name '*.bag' | wc -l)
  echo "$s: $n/8"
done
```

**期望**：全部 `8/8`（截至 2026-06-17 已满足）。

### 1.2 CGv2 PLY（Enhancement 硬需求）

```bash
wc -l data/processed/all_cg_only_cgv2.txt   # 期望 2155
wc -l data/processed/val_cg_only_cgv2.txt   # 期望 362
```

各序列 PLY 数量因序列长度而异（约 157–201 帧/序列）。

### 1.3 RGBD 彩色目录（Stage1 软需求）

`post_rgbd_install.sh` 会从 zip 解压或从 bag 导出 `RGBD/` 子目录。

```bash
wc -l data/processed/rgbd_pairs.txt         # 期望 >0；当前常为 0（librealsense 未就绪）
cat data/processed/rgbd_pairs_meta.json
```

`rgbd_pairs.txt` 为空 **不代表 bag 缺失**，只表示 **映射步骤未跑**。

### 1.4 zip 暂存区

`data/raw/UVG-CWI-DQPC/__zip/` 应在解压校验后 **为空**。若仍有 zip，用 `scripts/extract_rgbd_zips.sh`（`VERIFY_BEFORE_RM=1`）处理后再删。

---

## 2. 模型与代码

| 检查项 | 命令 / 路径 | 期望 |
|--------|-------------|------|
| SuperPC 克隆 | `test -d code/SuperPC/models` | 存在 |
| 官方权重 | `ls models/superpc_pretrained/*.pth` | kitti360, shapenet, tartanair |
| Gate ckpt | `test -f models/superpc_pretrained/kitti360_com.pth` | ~144MB |

```bash
source scripts/env_setup.sh
python scripts/verify_superpc_ckpt.py
```

---

## 3. 环境与运行时

### 3.1 superpc（推理 / 评估）

```bash
source scripts/env_setup.sh
python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
# 期望：2.8.0+cu128，GPU 机上 cuda True
bash scripts/rebuild_extensions.sh   # PyTorch 升级后必跑
```

### 3.2 cwipc + librealsense（Stage1）

```bash
source output/cwipc_env.sh 2>/dev/null || true
/usr/local/libexec/cwipc/cwipc_realsense2_install_check
python3.12 -c "import cwipc_realsense2" 2>/dev/null && echo cwipc_py:ok
```

**常见失败**：`librealsense2.so.2.56: cannot open shared object file`  
**修复**：`bash scripts/install_cwipc.sh`（源码编译 librealsense，耗时长）

---

## 4. 产物完整性

### 4.1 Enhancement Only（主保底产物）

| 路径 | 期望 |
|------|------|
| `output/submission_candidate/` | 2155 个 ENH `.ply`，~19GB |
| `output/submission_candidate/evaluation_full_cpu.json` 或 val eval | 存在 |
| `output/val_grid/gate_decision.json` | `gate_passed: true` |

```bash
find output/submission_candidate -name '*.ply' | wc -l   # 2155
```

### 4.2 Full Pipeline（尚未完成）

| 路径 | 期望（完成后） |
|------|----------------|
| `output/full_pipeline_cg/` | Stage1 重建 CG |
| `output/full_pipeline_candidate/` | Stage2 ENH |
| `submissions/GC2026_Team/manifest.json` | `processing_track: full` |

---

## 5. 状态标记文件

| 文件 | 含义 |
|------|------|
| `output/overnight_nogpu.state` | 无 GPU 夜间任务：`cgv2_postinstall=done`, `cpu_eval=done` 等 |
| `output/gpu_pending.sh` | GPU 实例恢复后一键续跑 |
| `output/cwipc_env.sh` | cwipc 运行时 LD_LIBRARY_PATH / LD_PRELOAD |
| `output/status_report.json` | 由 `generate_status_report.py` 生成 |

---

## 6. 磁盘参考（2026-06-17）

| 路径 | 约大小 |
|------|--------|
| `data/raw/UVG-CWI-DQPC/` | 868G |
| `output/submission_candidate/` | 19G |
| `output/val_grid/` | 75G |
| `models/superpc_pretrained/` | ~480MB |
| `code/SuperPC/` | 视 clone 而定 |

可安全清理（确认后）：旧版 `*_submission.tar.gz`、测速残留、`pip-cache`、已解压的 `__zip/*.zip`。

**勿删**：`data/raw` bag/CG、`submission_candidate`、`gate_decision.json`、`cwipc_install_cache`（librealsense 未装完前）。

---

## 7. 单测（Full Pipeline Phase 1 验收）

```bash
source scripts/env_setup.sh
python scripts/test_transform_matrix.py
python scripts/test_frame_playback_map.py
python scripts/test_rgbd_to_cg_units.py
```

全部 PASS 表示 Stage1 **代码路径**就绪，不代表 librealsense 已可用。
