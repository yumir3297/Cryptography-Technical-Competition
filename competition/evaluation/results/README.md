# 原始结果索引

| 文件 | 内容 | 生成命令 |
|---|---|---|
| `build.json` | 构建 SHA、环境、命令 | 手工维护（绑定 `f6b4bc2`） |
| `test-summary.json` | 核心/新增/全量测试计数 | 由实际日志整理 |
| `conformance-39.json` | 39 项机器可读状态 | `conformance_39.md` 同步 |
| `concurrency.json` | 20 条真实 W 历史 + 10,000 条参考模型 | `python -m competition.evaluation.experiments.concurrency` |
| `crash-recovery.json` | 3 个崩溃边界实际结果 | `python -m competition.evaluation.experiments.crash_report` |
| `crypto-attacks.json` | 15 个定向篡改/重放 | `python -m competition.evaluation.experiments.crypto_attacks` |
| `ablation.json` | Baseline A/B/C/Shadow/Proposed | `python -m competition.evaluation.experiments.ablation` |
| `performance.json` | 纯 GoalFloor/接受/生命周期延迟 | `python -m competition.evaluation.experiments.performance` |
| `evidence-audit.json` | 三 Profile + Goal 包审计汇总 | `python -m competition.evaluation.experiments.audit_report` |
| `cross-scenario.json` | 三 Profile 业务差异与包审计 | `python -m competition.evaluation.experiments.cross_scenario_report` |

注意：
- `concurrency.json` 的 20 条是真实 W 历史；10,000 条是独立参考模型，两者不能相加成“10,020 条真实并发”。
- `ablation.json` 的 Baseline A/B 是规则级基线，不是完整协议实现。
- 所有结果均绑定 `build.json.integration_sha`；证据包 manifest 另含 `git_sha`。
