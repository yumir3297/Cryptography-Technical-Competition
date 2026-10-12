# ZJJ-CORE 比赛协议交付入口

2026-10-11 · `COMP-PROTOCOL-FINAL-1.0` · 本地协议材料冻结

ZJJ-CORE 面向 agent 参与的高风险、高后果流程。agent 提出动作，独立的受信验证与必要批准决定能否接受和派发。工业、付款、医疗共用安全核心，在受信单机和三个签名模拟工具范围内展示动作绑定、授权检查、一次执行资格与保守恢复。

| 读者与用途 | 当前材料 |
|---|---|
| 比赛文书、评委说明 | [精简比赛协议](docs/final/competition-protocol.md) |
| 查询与审计展示 | [查询审计口径](docs/final/query-audit-scope.md) |
| 工业开发交接 | [IND-DEMO-1](docs/final/industrial-handoff.md) |
| 付款开发交接 | [PAY-1](docs/final/payment-handoff.md) |
| 医疗开发交接 | [MED-DEMO-1](docs/final/medical-handoff.md) |
| 声明核对与证据引用 | [声明—证据清单](docs/final/claims-evidence.md) |
| 验证复现、文件与版本 | [本轮交付记录](docs/final/finalization-record.md) |
| 当前函数、认证凭据、返回值与幂等接法 | [内部接口对照](docs/final/interface-reference.md) |
| 开发对应、比赛暂不扩展的条件与本轮复检 | [R2 对照](docs/final/r2-application-mapping.md) · [开发注释](docs/final/developer-scope-notes.md) · [复检记录](docs/final/protocol-review.md) |

有效源码基线：分支 `competition/zjj-core-final-20261010`，HEAD `42021274a2f7d6adf35337bb153f05bf89b3e8f9`。这是既有证据的源码构建基线。2026-10-11 仓库整理将所需支持模块迁入 competition/support，研究资料归档本地；当前目录与新验证见[整理记录](../REPOSITORY_SCOPE.md)。

协议精确字段引用 [R2 核心合同](../system_dev/v26/01_core_contract.md)、[PAY 合同](../system_dev/v26/02_pay1_profile.md)、[工业医疗合同](../system_dev/v26/03_industrial_medical_profiles.md)、[终局合同](../system_dev/v26/04_tool_final_recovery.md)和原 Schema。开发者先读[当前接口对照](docs/final/interface-reference.md)，再查 [公共 W 实现契约](docs/w-transaction-contract.md)及源码；历史伪代码与当前真实签名分开。协议正文不展开存储、函数签名和部署参数。

既有证据绑定的原 README 与开发合同字节可从其记录的 Git 提交核对；当前开发文档使用整理后的入口。当前比赛说明以本入口为准，实际行为以共同 W 和具名证据为准。原研究包与研究实验完整存于本地归档，保持来源身份；本任务完成门槛是协议材料与所选模拟展示可行性，界面、安装包和软件产品化交由后续开发。
