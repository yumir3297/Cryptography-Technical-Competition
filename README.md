# ZJJ-CORE 安全协议与比赛模拟软件

面向高后果智能体决策的密码学可验证动作授权与原子接受协议。Agent 提出候选动作，受信控制面 C 发布约束，共同 W 确定性核验身份、授权、资源及必要目标下界，将接受、执行资格、工具终局与结算绑定到可复验的证据链。

## 当前交付与实验结论（2026-11-24）

**当前验收：CONDITIONAL_READY（有条件就绪）。** 核心 91/91、专项 45/45（含 GoalFloor/跨场景 23 项）；20 条真实长序列配对、112 个候选动作位置、20 个差分拒绝位置、Oracle mismatch 0；40 条真实并发历史全部存在线性化解释；15/15 定向篡改拒绝、3/3 崩溃边界通过；IND/PAY/MED 与事件响应（复用 IND wire）；4,363 个有限模型状态、67,746 次转移、0 违反。独立模型长序列及并发历史各 10,000 条，不能混为真实 W 样本。真实接受路径 40 次/模式，p50 1324.9/1338.4 ms，探索性增加约 1%；证据包约 +1.6%。正式 39 项为 2 PASS / 0 FAIL / 22 PARTIAL / 15 NOT_RUN；Linux/WSL 全量 526 tests、1 failure / 3 errors，隔离复跑通过，尚无单次全绿。统计可能重叠，不相加。

以 [最新研究定论](RESEARCH-STATUS-20261124.md)、[最终验收](FINAL_VERDICT.md)、[实验结论](competition/evaluation/experiment_conclusions.md) 为当前结论入口；旧阶段数字仅按原构建身份追溯。

- **[当前统一协议正文](competition/docs/final/competition-protocol.md)** · [GoalFloor 原始集成规范（保留溯源）](competition/docs/final/goalcommit-integration-20261123.md) · [核心贡献](competition/evaluation/core-contributions.md)
- [实验与结果](competition/evaluation/README.md) · [原始 JSON 索引](competition/evaluation/results/README.md) · [39 项状态](competition/evaluation/conformance_39.md)
- [评委独立复验](competition/evaluation/judge_replay.md) · [演示复验](competition/evaluation/reproduce/README.md) · [实验图表](competition/evaluation/figures/)
- [剩余限制](competition/evaluation/remaining-limitations.md)

GoalFloor 只维护经 C 认证的必要资源下界，不证明目标可达、规划正确或最终成功。默认 off 保持已有入口兼容；只有明确启用 enforce 才有新约束保障。已验证的是受信单机真实协议实现与签名模拟工具，不是生产设备。

## 开发与运行

- [比赛开发入口](competition/README.md) · [单机部署与本地回归](INSTALL_AND_SCOPE.md)
- [工业全流程与三场景历史统一交付](competition/docs/final/unified-competition-delivery-20261018.md)
- [统一协议正文](competition/docs/final/competition-protocol.md) · [比赛协议交付入口](competition/FINAL_PROTOCOL_HANDOFF.md)
- [三场景开发总交接](competition/docs/final/scenario-integration-handoff.md) · [内部接口](competition/docs/final/interface-reference.md) · [Agent MCP](competition/docs/final/agent-mcp-handoff.md)
- [消息契约、Schema 与公开编码向量](system_dev/v26/README.md) · [安全边界](competition/docs/final/security-boundaries.md)
- [声明与实际证据](competition/docs/final/claims-evidence.md) · [仓库范围](REPOSITORY_SCOPE.md)
- [研究讨论案](competition/docs/discussions/2026-11-20-agent-action-governance-proposal.md)

既有工业服务和 PAY/MED 本地 CLI 保持隔离。历史证据保留原构建身份。
