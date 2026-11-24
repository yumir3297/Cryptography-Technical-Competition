# ZJJ-CORE — GoalFloor 阶段性研究定论（2026-11-24）

状态：**研究范围与核心组合设计冻结；比赛交付验收仍开放。** 本页记录项目组已明确的研究边界与验收包支持的阶段性结论，不替代 R2 协议规范，不改变运行代码或 Schema，不宣布正式 release。

## 1. 研究目标与职责边界（已确定）

面向高后果智能体决策，ZJJ-CORE 对候选外部动作提供密码学可验证的授权、原子接受、执行资格及终局/结算证据绑定。Agent 负责目标提出、推理和规划；受信控制面 C 负责认证并发布安全约束，W 负责确定性地检查约束。协议不对 Agent 的概率性推理本身作正确性保证。

GoalFloor 的职责仅为维护经 C 认证的目标必要资源下界，防止后续局部合法动作挤占已确定的必要资源。**目标可达性、初始规划正确性、最优路径、目标最终成功与否均不属于本协议职责。** 外部环境是否支持实现目标同样不由协议保证。必要事项与成本下界的业务正确性依赖受信约束制定方；签名证明来源和完整性，不证明业务估算正确。协议无需自行搜索或证明全局可达性，也不引入 winning region、rank function 或另一套规划安全核心。

## 2. 核心安全性质与实现口径（已确定）

对于同一 (profile, resource_key) 且适用活跃 GoalFloor 的候选动作，在 enforce 模式下，接受必须满足：

```text
Spent + Reserved + CandidateCost + RemainingGoalFloor <= Capacity
```

- Spent、Reserved：W 当前资源账中的消耗和预留；CandidateCost：W 计划计算的 amount，不信任 Agent 自报。
- RemainingGoalFloor：同一资源上所有活跃 C GoalFloor 的 OPEN 必要事项成本之和，排除本次匹配的事项，避免重复计入候选动作成本；Capacity 与 C 资源证书一致。
- 这是接受时的必要资源保障条件，不是充分可达条件；多 Goal 求和为保守语义，不支持析取目标或跨 Profile 原子性。
- PENDING（包括 UNKNOWN）不等于 DONE，BLOCKED 不自动释放为成功；匹配的必要事项不得重复接受。必要事项的后续状态遵循既有 W 恢复/结算语义，UNKNOWN 查询原 attempt、不自动重派或释放。
- 上述条件以正确认证的活跃约束、受信 W 账本及既有授权规则为前提。不将 off/shadow 模式的观察结果描述为强制保障，也不声称所有资源变化或 C 停用均已被证明安全。

## 3. 密码学与原子接受的组合设计（已集成，有定向实验支持）

1. C 经既有 TrustedState.publish 认证 GOAL_FLOOR，依赖 POLICY/TASK/INCIDENT 的 revision/ref；旧依赖失效时不能继续使用旧约束。
2. W 根据冻结 Action 的 action_selector 匹配 C 规则，Agent 请求没有 goal 选择字段，不能通过自报目标引用或成本规避检查。selector 排除 operation_id。
3. CommonW.accept 在同一个 BEGIN IMMEDIATE 事务内读取活跃约束、账本和 obligation 状态，计算下界，完成原有授权约束与新 guard 的联合检查、资源预留和 COMMIT；拒绝回滚，不产生新的业务接受记录。
4. COMMIT.value.goal 包含 goal_refs/deps/matched、资源算术及 state_ref/check_ref 等见证。X Acceptance 签名引用 commit_record_ref，因而绑定接受时的 GoalFloor 见证；执行尝试、工具终局与结算继续使用既有证据链。
5. 独立验证器以外部固定的信任锚重算证据关系和 GoalFloor 算术；并不独立证明 W 账本现实真实性、证据当期性或物理设备效果。

创新定位是 C 认证的目标下界与 W 原子接受及签名证据链的组合，不将 Ed25519、SHA-256、SQLite 事务等标准技术本身作为新密码学原语宣称。保持现有 C/Resolver/W/X/工具/结算主线，不另建安全核心。

模式：off 为当前默认，shadow 仅观察，enforce 才执行 LegacyGuard AND GoalFloorGuard。比赛目标场景必须明确启用 enforce。

## 4. 已记录的阶段性证据（不是本次重新执行）

依据 ZJJ-CORE-GoalFloor-Acceptance-20261124.zip 中的报告、结果 JSON 和日志；该包 SHA-256 为 `b65146e91d958e2214d00b5dcb6f8a6be704ac52b9de2a6b721cd3ee4c25bc98`。本次整理核对包内清单，未重新执行完整协议测试。以下结果按各自测试范围使用，不相加为总通过数。

| 项目 | 记录结果 | 证据及限制 |
|---|---|---|
| 核心协议子集 | 91/91 PASS | [test-summary.json](competition/evaluation/results/test-summary.json)；不是全量回归 |
| 新增专项 | 40/40 PASS（含 GoalFloor 18 项） | 同上；与其他统计可能重叠 |
| 定向篡改/重放 | 15/15 拒绝，合法包 PASS | [crypto_attack_results.md](competition/evaluation/crypto_attack_results.md)；非穷举 |
| 真实 W 并发 | 20/20 历史存在线性化解释 | [concurrency_results.md](competition/evaluation/concurrency_results.md)；不是一般并发证明 |
| 独立参考模型 | 10,000 历史、240,000 转移、0 违反 | 同上；模型不是 W 本体 |
| 新增崩溃边界 | 3/3 PASS | [crash_recovery_results.md](competition/evaluation/crash_recovery_results.md) |
| IND/PAY/MED 基础证据 | 各 13/13 离线检查 PASS | [cross-scenario.json](competition/evaluation/results/cross-scenario.json)；三包无 GoalFloor 见证，不代表三 Profile 的 GoalFloor 全部验证 |
| IND GoalFloor 专项 | 13/13 离线检查 PASS | [evidence-audit.json](competition/evaluation/results/evidence-audit.json) |
| 事件响应工作流 | 13/13 离线检查 PASS | [证据目录](competition/evaluation/evidence/incident-20261123/)；复用 IND wire，不是第四官方 Profile |
| 正式 R2 语义清单 | 2 PASS / 0 FAIL / 37 NOT_RUN | [conformance_39.md](competition/evaluation/conformance_39.md)；未运行绝非通过 |
| Windows 全量 | 400 项，25 failures / 101 errors | [baseline_comparison.md](competition/evaluation/baseline_comparison.md)；环境问题及其他失败需目标环境复核，不标记全量 PASS |

### 最有价值的定向消融

[goalcommit_ablation.md](competition/evaluation/goalcommit_ablation.md) 报告五个非法案例中的接受数：本地门控 5/5，单签名 4/5，原 CommonW(off) 2/5，shadow 2/5，enforce 0/5；另有一个合法案例五种模型均接受。

原 CommonW 与 enforce 的差异为：可选动作挤占必要资源时 GOAL_CAPACITY_FLOOR 拒绝；UNKNOWN 后继续接受的定向案例由 GOAL_PENDING_UNKNOWN 拒绝。A/B 为规则级基线而非完整系统，五个案例是定向功能差分，不是现实攻击成功率，也不构成统计显著性或优于全部竞品的证据。

## 5. 证据身份与冻结范围

- 基线：`7604d6b5b902f38d950234dec53d9375429f1e7f`
- 代码/证据生成：`fcbc6b3b3ad63c9de84387c98bccc004f726a77b`
- 测试提交（build.json）：`925265229d63b077c0db23d65df4a6ef3ad19729`
- 证据文档提交：`89275d7d0c6910999e53f5538c93bfdc59ecd1eb`
- 本次文档更新前线上集成分支 HEAD（已核对）：`9e9f3e054e77e3e0c4f88b6599dd3d166af2937c`。build.json 的 head_sha 仍为其父提交 `f4766ac1a3a413a6d3d52a838479729c00224863`；将其保留为历史记录，不将新文档提交误报为实验运行版本。各实验仍以自身记录的 SHA 为准。

原始材料入口：[实验与验收](competition/evaluation/README.md)、[不变量](competition/evaluation/invariant_spec.md)、[创新总结](competition/evaluation/innovation_summary.md)、[构建身份](competition/evaluation/results/build.json)、[评委复验](competition/evaluation/judge_replay.md)。

## 6. 进入比赛交付阶段（尚待验收，不冻结实现）

停止扩大 GoalFloor 研究范围；以下是交付收尾建议，不是已经完成的工作：

- 明确演示 enforce 配置，复验拒绝无业务副作用、并发、依赖更新、重复接受、UNKNOWN 恢复和 C 停用治理边界。C 可停用 GoalFloor；现有材料未证明未决义务情况下的停用防护。
- 在目标 Linux 环境运行完整回归，区分环境失败与实际缺陷；按关键安全路径补齐正式 R2 语义子变体，保留完整 39 项状态及未覆盖限制。
- 核对实际 w_goal schema/源码与文档：invariant_spec 与 open_issues 对唯一索引描述不同，不在本次文档冻结中假定已解决。
- 固定评委复验的代码/证据身份和独立信任锚；演示合法接受、原 W 与 enforce 的定向差异、UNKNOWN 恢复。性能完整 W 样本 n=5，不宣称稳定尾延迟或统计意义的低开销。
- 不将模拟业务效果当作真实生产效果，不将受信单机范围扩展为跨 Profile、多机或现实账本真实性保证。

**本里程碑冻结的是职责边界、核心组合设计及已有证据支持的结论，而非完整安全性、全部符合性、最终代码发布或生产级部署。**
