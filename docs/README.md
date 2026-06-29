# GC2026 文档索引

| 文档 | 读者 | 内容 |
|------|------|------|
| [`../AGENTS.md`](../AGENTS.md) | **Cursor Agent** | 项目目标、完成度、环境、常用命令、行为约定 |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Agent / 开发者 | 双 Track 架构、数据流、Stage1/2、评估与提交 |
| [`INTEGRITY.md`](INTEGRITY.md) | 迁移 / 验收 | 完整性检查项说明与手动命令 |
| [`MIGRATION.md`](MIGRATION.md) | 运维 | 新服务器 rsync、bootstrap、验收标准 |
| [`CWIPC_NATIVE_PIPELINE.md`](CWIPC_NATIVE_PIPELINE.md) | Stage1 | cwipc-native、variants、gate |
| [`meeting_delivery/README.md`](meeting_delivery/README.md) | **学长汇报** | **总思路报告 + Excel + 指标 CSV + 提交说明（推荐入口）** |
| [`meeting_delivery/PROJECT_STRATEGY_REPORT.md`](meeting_delivery/PROJECT_STRATEGY_REPORT.md) | **汇报 / 答辩** | 选型、成败、框架、表格含义、待填项 |
| [`N0_V2_RESULTS.md`](N0_V2_RESULTS.md) | 结果 | N0 v2 全量指标摘要 |
| [`../README.md`](../README.md) | 人类 | **仓库总览**（含 PD-LTS 提交与学长汇报入口） |

**一键检查**：`bash scripts/check_integrity.sh`  
**刷新状态**：`python scripts/generate_status_report.py`
