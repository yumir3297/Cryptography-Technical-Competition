# GoalFloor 研究定论与比赛交付状态（2026-11-24）

**当前验收：CONDITIONAL_READY（有条件就绪）。** 核心 91/91、专项 45/45（含 GoalFloor/跨场景 23 项）；20 条真实长序列配对、112 个候选动作位置、20 个差分拒绝位置、Oracle mismatch 0；40 条真实并发历史全部存在线性化解释；15/15 定向篡改拒绝、3/3 崩溃边界通过；IND/PAY/MED 与事件响应（复用 IND wire）；4,363 个有限模型状态、67,746 次转移、0 违反。独立模型长序列及并发历史各 10,000 条，不能混为真实 W 样本。真实接受路径 40 次/模式，p50 1324.9/1338.4 ms，探索性增加约 1%；证据包约 +1.6%。正式 39 项为 2 PASS / 0 FAIL / 22 PARTIAL / 15 NOT_RUN；Linux/WSL 全量 526 tests、1 failure / 3 errors，隔离复跑通过，尚无单次全绿。统计可能重叠，不相加。

最新结论见 [FINAL_VERDICT.md](FINAL_VERDICT.md) 与 [实验结论](competition/evaluation/experiment_conclusions.md)，替代此前阶段性口径。

## 职责边界与核心设计

本协议负责密码学可验证动作授权、原子接受、唯一执行资格与终局/结算证据绑定。Agent 负责目标提出及规划，C 认证必要约束，W 确定性核验。GoalFloor 只维护目标必要资源下界；目标可达性、规划正确性、最优路径及最终成功不属协议职责。业务成本与必要事项正确性依赖受信约束制定者。

在 enforce 模式下，同一 Profile 同一资源满足：

```text
Spent + Reserved + CandidateCost + RemainingGoalFloor <= Capacity
```

W 从账本及计划取得支出、预留、候选成本；C 认证 OPEN 必要事项下界，多 Goal 保守求和，排除本次匹配义务。PENDING/UNKNOWN 不等于 DONE，BLOCKED 不自动视为成功。Agent 无 goal 选择字段，W 用冻结 Action selector 匹配 C 规则。

C 签名发布 GOAL_FLOOR 并绑定依赖 revision/ref；W 在同一 BEGIN IMMEDIATE 事务核验、预留并写 COMMIT；X Acceptance 签名通过 commit_record_ref 绑定见证，后续 attempt/工具终局/结算使用既有证据链。epoch 迁移保持义务集合；停用仍有 PENDING 的 Goal 触发 GOAL_INACTIVE_PENDING；enforce 的部分唯一索引防重复义务链接。Ed25519、SHA-256、SQLite 为标准技术，贡献是目标下界、原子接受和密码学证据的组合，而非新原语。

[核心贡献](competition/evaluation/core-contributions.md) · [集成说明](competition/docs/final/goalcommit-integration-20261123.md) · [结果索引](competition/evaluation/results/README.md)

## 证据身份及剩余边界

- 原基线 `7604d6b`；最终实验代码/验证器 `7f5dd03c404a9320dfebd4bcf0d87c8cd53e8a7c`；冻结实验分支头 `d83546be8bfa2304b984a439baf13c2571f3f866`。各历史运行、证据包以自身 SHA、manifest、命令为准；合并及文档提交不是实验运行身份。
- 长序列真实实验使用五种固定模板重复运行；消融 A/B 是规则级基线，不是具体竞品同测；性能为探索性结果。
- 默认 off 维持既有入口兼容；shadow 只观察；仅明确启用 enforce 才有新约束保障。正式业务入口配置及演示仍须验证。
- 原始 JSON、审计包、脚本、图表已提交；原始运行日志保留在实验工作区，未提交 Git。不得将模拟效果当作真实生产效果，不承诺跨 Profile 原子性、账本现实真实性、证据当期性或全部 R2 符合。
- Linux 单次全量复跑、39 项关键变体、AUD-02B/C、扩大真实样本及稳定尾延迟仍是后续交付或研究事项。

[验收矩阵](competition/evaluation/final-acceptance.md) · [评委复验](competition/evaluation/judge_replay.md) · [剩余限制](competition/evaluation/remaining-limitations.md)
