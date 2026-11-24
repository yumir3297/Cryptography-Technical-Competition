# 原始结果索引（2026-11-24 最终轮）

| 文件 | 内容 |
|---|---|
| [build.json](build.json) | 构建身份与命令；历史实验保留自身 SHA |
| [test-summary.json](test-summary.json) | 核心 91/91、专项 45/45、契约 371 |
| [regression.json](regression.json) | Linux/WSL 全量 526 项及隔离复跑 |
| [conformance-39.json](conformance-39.json) | 2 PASS / 0 FAIL / 22 PARTIAL / 15 NOT_RUN |
| [long-sequence-summary.json](long-sequence-summary.json) | 20 条真实配对、112 动作位置、20 个差分拒绝、Oracle mismatch 0 |
| [long-sequence.json](long-sequence.json) | 真实序列与 10,000 条参考模型原始轨迹 |
| [concurrency-summary.json](concurrency-summary.json) | 40 条真实历史、10,000 模型历史 |
| [concurrency.json](concurrency.json) / [concurrency-bulk.json](concurrency-bulk.json) | 初轮、补充真实历史 |
| [crash-recovery.json](crash-recovery.json) | 3 个崩溃边界 |
| [crypto-attacks.json](crypto-attacks.json) | 15 个定向篡改 |
| [ablation.json](ablation.json) | 规则级及机制消融 |
| [performance.json](performance.json) / [performance-bulk.json](performance-bulk.json) | 纯判定与真实接受路径；40 次/模式批量探索 |
| [evidence-audit.json](evidence-audit.json) | 证据包审计 |
| [cross-scenario.json](cross-scenario.json) / [cross-goal.json](cross-goal.json) | 跨场景与 PAY/MED GoalFloor |
| [model-check.json](model-check.json) | 4,363 状态 / 67,746 转移 / 0 违反 |

真实 W 与模型结果不混算；A/B 消融是规则级基线，不是完整竞品。代码、证据与文档身份分开，原始运行日志未随本次 Git 提交公开；JSON 和证据包按原身份保留。当前综合结论见 [实验结论](../experiment_conclusions.md)。
