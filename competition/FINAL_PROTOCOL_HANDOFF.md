# ZJJ-CORE 比赛协议交付入口

2026-10-12 · `CORE-SPEC-1.3` · 比赛协议规则与开发接线约定

ZJJ-CORE 面向 agent 参与的高风险、高后果流程。agent 提出动作，独立的受信验证与必要批准决定能否接受和派发。工业、付款、医疗共用安全核心，在受信单机和三个签名模拟工具范围内展示动作绑定、授权检查、一次执行资格与保守恢复。

| 读者与用途 | 当前材料 |
|---|---|
| 比赛文书、评委说明 | [共同安全协议](docs/final/competition-protocol.md) |
| 固定配置与三个场景开发总接线 | [比赛开发总交接](docs/final/scenario-integration-handoff.md) |
| 协议与场景分层的变更和验证 | [本轮分层记录](docs/final/protocol-separation-record-20261012.md) |
| 查询与审计展示 | [查询审计口径](docs/final/query-audit-scope.md) |
| 工业开发交接 | [IND-DEMO-1](docs/final/industrial-handoff.md) |
| 付款开发交接 | [PAY-1](docs/final/payment-handoff.md) |
| 医疗开发交接 | [MED-DEMO-1](docs/final/medical-handoff.md) |
| 声明核对与证据引用 | [声明—证据清单](docs/final/claims-evidence.md) |
| 验证复现、文件与版本 | [原收尾交付记录](docs/final/finalization-record.md) |
| 当前函数、认证凭据、返回值与幂等接法 | [内部接口对照](docs/final/interface-reference.md) |
| agent MCP 两个工具与状态回推 | [agent MCP 交接](docs/final/agent-mcp-handoff.md) |
| 实验结论采纳、优化后的逻辑与书写复检 | [2026-10-12 优化记录](docs/final/optimization-review-20261012.md) |
| 开发对应、比赛暂不扩展的条件与本轮复检 | [R2 对照](docs/final/r2-application-mapping.md) · [开发注释](docs/final/developer-scope-notes.md) · [复检记录](docs/final/protocol-review.md) |

本轮核对的源码基线：分支 `competition/zjj-core-final-20261010`，HEAD `1aa5a9e36e1558b95972941d5ce7dbf6553da431`。较早运行包按其原 `4202127` 构建身份核验；仓库整理后新运行记录另列。2026-10-11 整理将所需支持模块迁入 competition/support，研究资料归档本地；当前目录与验证见[整理记录](../REPOSITORY_SCOPE.md)。此前 1.2 实现认证签署请求、独立 wire proto、严格候选入口和 W 当前依据构造；本轮 1.3 只将共同协议与具体开发规则分层，wire ZJJ-CORE-COMP-1、执行代码、原 Schema 及证据保持。

协议精确字段引用 [R2 核心合同](../system_dev/v26/01_core_contract.md)、[PAY 合同](../system_dev/v26/02_pay1_profile.md)、[工业医疗合同](../system_dev/v26/03_industrial_medical_profiles.md)、[终局合同](../system_dev/v26/04_tool_final_recovery.md)和原 Schema。开发者先读[当前接口对照](docs/final/interface-reference.md)，再查 [公共 W 实现契约](docs/w-transaction-contract.md)及源码；历史伪代码与当前真实签名分开。协议正文采用共同机制表述，具体复核用途、业务意图、资源单位、状态枚举、存储、函数和演示结果由开发交接承载。

既有证据绑定的原 README 与开发合同字节可从其记录的 Git 提交核对；当前开发文档使用整理后的入口。当前比赛说明以本入口为准，实际行为以共同 W 和具名证据为准。原研究包与研究实验完整存于本地归档，保持来源身份；本任务完成门槛是协议材料与所选模拟展示可行性，界面、安装包和软件产品化交由后续开发。

当前比赛语义、agent 能力与角色签署边界见[安全边界](docs/final/security-boundaries.md)；修复和验证结果见[整改记录](docs/final/rectification-results-20261012.md)。
