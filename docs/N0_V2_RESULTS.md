# Full Pipeline N0 v2 — 实验结果摘要

> 生成时间：2026-06-20 · 全量 2155 帧跑通 · 对比基线 B1 (`B1_hybrid_official`)

## 结论

N0 v2 相对 B1 **全面改善**：Val362 Recon vs HE **351 → 254 mm**，ENH vs HE **313 → 206 mm**。  
TicTacToe 专项从不可用（ENH 403 mm）恢复到 **165 mm**。  
相对官方 CG 的 val ENH：**351 → 196 mm**（improvement 从 -265 改善到 -110 mm）。  
**Enhancement Only** 提交轨（Val ENH ~71 mm，improvement +14.5 mm）仍是竞技首选。

## Val362 核心指标

| 指标 | B1 | N0 v2 | Δ |
|------|-----|-------|---|
| Recon vs HE (mm) | 351.4 | 253.9 | **-97.5** |
| ENH vs HE (mm) | 313.1 | 205.9 | **-107.2** |
| ENH vs 官方 CG (mm) | 351.1 | 196.3 | **-154.8** |
| improvement vs CG (mm) | -265.1 | -110.5 | **+154.6** |

### 分序列（ENH vs HE, mm）

| 序列 | B1 | N0 v2 |
|------|-----|-------|
| TicTacToe | 402.5 | **164.7** |
| VictoryHeart | 238.2 | 240.5 |

### 分序列（ENH vs 官方 CG, mm）

| 序列 | B1 | N0 v2 | Enhancement Only |
|------|-----|-------|------------------|
| TicTacToe | 445.6 | 153.2 | 76.3 |
| VictoryHeart | 271.8 | 232.4 | 67.5 |

## 全量 Train（2155 帧, n=20k）

| 指标 | B1 | N0 v2 | Enhancement Only |
|------|-----|-------|------------------|
| mean ENH CD (mm) | 219.8 | 178.1 | 49.6 |
| improvement vs CG (mm) | -170.5 | -128.8 | -0.3 |

## Gate

| Gate | B1 | N0 v2 |
|------|-----|-------|
| Recon vs PGDR baseline | ✅ pass (+49%) | ✅ pass (+63%) |
| ENH < 200 mm | ❌ 313 mm | ❌ 206 mm |

## 产出路径（服务器本地，未入 git）

| 产物 | 路径 |
|------|------|
| Stage1 recon | `output/full_pipeline_n0_v2_cg/` |
| SuperPC ENH | `output/full_pipeline_n0_v2_candidate/` |
| 提交 tar（23 GB） | `output/full_pipeline_n0_v2_candidate_submission.tar.gz` |
| JSON 报告 | `output/full_n0_v2_final_report.json` |

## 一键复现

```bash
# Val362 实验
bash scripts/run_val362_n0_v2.sh

# 全量 N0 v2（Stage1 → SuperPC → Post）
bash scripts/run_full_n0_v2.sh

# 进度仪表盘
bash scripts/watch_full_n0_v2.sh
```
