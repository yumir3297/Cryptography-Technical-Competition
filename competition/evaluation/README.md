# ZJJ-CORE-2.6-R2 实验与验收目录

本目录记录本轮从“原型/历史切片”转入“正式集成 + 对抗实验 + 独立复验”的工作。所有结论都绑定具体命令、构建 SHA、配置和原始结果；没有运行的项目明确写 `NOT_RUN`，原型 31 项测试不与正式 39 项混算。

## 目录

| 文件 | 内容 |
|---|---|
| `protocol_audit.md` | 真实代码路径、协议字段、签名域、状态冻结点和信任边界 |
| `invariant_spec.md` | 资源、唯一执行、一次结算、对象一致性等不变量及对应测试 |
| `threat_model.md` | 攻击者能力、受信组件、明确不声称的范围 |
| `experiment_matrix.md` | 五组实验、跨场景和当前状态 |
| `baseline_comparison.md` | 原主线基线、集成分支、测试结果和环境 |
| `conformance_39.md` | 官方 39 项语义清单逐项状态 |
| `crypto_attack_results.md` | 15 个定向篡改/替换/重放结果 |
| `concurrency_results.md` | 实际并发历史、线性化见证、10,000 条参考模型历史 |
| `crash_recovery_results.md` | 持久化边界故障注入与重启恢复 |
| `goalcommit_ablation.md` | Baseline A/B/C 与 Proposed 的差分/消融 |
| `performance_results.md` | 同环境延迟分布与开销 |
| `innovation_summary.md` | 有证据支持的创新点与不应夸大的边界 |
| `open_issues.md` | 按风险排序的待优化事项 |
| `judge_replay.md` | 评委一条命令复验步骤 |
| `results/` | 实验原始 JSON/日志 |
| `evidence/` | 公开证据包、信任锚、审计报告 |

## 当前结论（只写已经跑过的）

交付：分支 `integration/goalcommit-shadow-20261123`；本轮代码/证据生成提交 `7f5dd03c404a9320dfebd4bcf0d87c8cd53e8a7c`；最终文档提交见 Git HEAD。

- 默认 `goal_mode='off'` 保持原 CommonW 语义；新增 GoalFloor 是 C 发布的可选对象，Agent 不能通过请求字段选择、删除或改价。
- GoalFloor 已在 **shadow** 和 **enforce** 两种模式接入同一个 W 接受事务；enforce 模式下 `LegacyGuard AND GoalFloorGuard`，拒绝事务无业务副作用。
- 23 项 GoalFloor/跨场景测试通过；三场景（IND/PAY/MED）各自生成并通过 13 类离线审计检查；事件响应工作流通过审计；PAY/MED 各有正常 GoalFloor 审计 PASS 与挤占拒绝。
- 3 个崩溃边界（接受提交、EXEC-0 消费后、结算提交后）通过重启恢复测试；未发现第二次执行资格或第二次结算。
- 15 个定向篡改测试全部被独立验证器拒绝，合法包通过；新增 Goal capacity/Profile/资源/epoch 关系测试通过。
- 20 条长序列真实配对：off 接受 84、enforce 接受 76，20 个 off 接受/Proposed 拒绝反例，Oracle mismatch 0；10,000 条四类模型序列。
- 40 条真实并发历史全部存在线性化解释；10,000 条独立参考模型历史、240,000 次转移、0 违反。
- 正式 39 项：`2 PASS / 0 FAIL / 22 PARTIAL / 15 NOT_RUN`；PARTIAL 不是 PASS，逐项见 `conformance_39.md`。
- Linux/WSL 全量 526 tests：1 failure / 3 errors，均为环境（clock 负载、复制树无 `.git`、HTTP proxy）；隔离复跑通过，未宣称单一进程全绿。

## 不声称

- 不声称 GoalFloor 证明目标最终可达；它只是必要资源下界。
- 不声称跨 Profile 原子性；GoalFloor 与资源账仍按 `profile` 隔离。
- 不声称模拟支付/医疗/工业/隔离动作等于真实生产效果。
- 不声称离线证据能证明 W 账本在现实中未被篡改，或证明当期性；这些仍依赖受信 W、效果端、时间源和完整账本。
- 不声称正式 39 项全部 PASS；逐项状态见 `conformance_39.md`。

## 快速复验

```powershell
python -m competition.evaluation.verify `
  competition/evaluation/evidence/20261123/IND-DEMO-1-package.json `
  competition/evaluation/evidence/20261123/anchor-three-profiles.json
```

预期输出 `"status": "PASS"`。评委应通过独立渠道固定 `anchor-three-profiles.json` 的 SHA-256，而不是信任证据包内附带的公钥。
