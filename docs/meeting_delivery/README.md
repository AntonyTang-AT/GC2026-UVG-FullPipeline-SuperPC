# 学长交付物（2026-06-29）

> **路径说明**  
> - **GitHub / 仓库正式路径**：`docs/meeting_delivery/`  
> - **本地运行镜像**：`output/meeting_delivery/`（由 `prepare_meeting_delivery.sh` 自动同步，不入库）

## 推荐阅读顺序

1. **[PROJECT_STRATEGY_REPORT.md](PROJECT_STRATEGY_REPORT.md)** — 总思路、选型、成败、为何不提交 vh_snap0  
2. **[VAL565_METRICS_XLSX.md](VAL565_METRICS_XLSX.md)** — Excel 各 sheet 含义  
3. **[MODEL_MODIFICATION_REPORT.md](MODEL_MODIFICATION_REPORT.md)** — 论文 Method 参考  
4. **[SUBMISSION_COMPLIANCE.md](SUBMISSION_COMPLIANCE.md)** — 提交包合规核查  

## 1. 验证集 gc_baseline 指标（564 帧）

指标：`chamfer_distance = (accuracy + completeness) / 2`（mm），与仓库根目录 `ACMMM26_GC_baseline.csv` 同口径。

| 模型 | CSV | 说明 |
|------|-----|------|
| SuperPC blend_cg（旧线） | [metrics/01_...csv](metrics/01_superpc_blend_cg_kitti360_vx3.0_val565.csv) | kitti360 + blend_cg + voxel 3mm |
| PD-LTS vh_snap0（ablation） | [metrics/02_...csv](metrics/02_pdlts_vh_snap0_val565.csv) | density + VH 序列 snap=0 |
| **PD-LTS density（提交）** | [metrics/03_...csv](metrics/03_pdlts_density_global_snap_no_vh_tune_val565.csv) | 全局 snap=1, density fill |
| PD-LTS raw | [metrics/04_...csv](metrics/04_pdlts_raw_val565.csv) | 仅去噪，无 refine |
| SuperPC filter+snap | [metrics/05_...csv](metrics/05_superpc_filter_snap1.0_val565.csv) | Phase2 最优；分序列汇总 |

- **Excel**：[val565_gc_baseline_metrics.xlsx](val565_gc_baseline_metrics.xlsx)  
- **汇总 JSON**：[metrics/summary.json](metrics/summary.json)  
- **Gate 快照**：[gate_snapshots/pdlts_gate_decision.json](gate_snapshots/pdlts_gate_decision.json)、[gate_snapshots/superpc_gate_decision.json](gate_snapshots/superpc_gate_decision.json)

## 2. 主办方提交包（Enhancement Only / PD-LTS density）

- 源码目录：[submissions/GC2026_Team_EnhancementOnly/](../../submissions/GC2026_Team_EnhancementOnly/)
- 构建脚本：`bash scripts/build_pdlts_density_submission.sh`
- 冒烟验证：`bash scripts/verify_submission_enhancement_only.sh`
- 全量 ENH 输出（本地跑完后）：`output/submission_candidate_pdlts_density/`（不入库）

## 3. 重新生成本目录

```bash
export GC2026_ROOT=/path/to/GC2026-UVG-FullPipeline-SuperPC
bash scripts/prepare_meeting_delivery.sh
```

脚本会写入 `docs/meeting_delivery/` 并镜像到 `output/meeting_delivery/`。
