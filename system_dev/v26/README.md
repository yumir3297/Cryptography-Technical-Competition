# R2 消息合同与比赛开发参考

这里保留 `ZJJ-CORE-2.6-R2` 的精确字段和结构定义，供比赛软件解析与开发核对。Envelope.version 为 `2.6`，核心为十种签名消息。当前应用行为和原定义的对应关系见[R2 对照](../../competition/docs/final/r2-application-mapping.md)，真实函数接法见[接口参考](../../competition/docs/final/interface-reference.md)。

- [核心精确合同](01_core_contract.md)
- [PAY-1 场景合同](02_pay1_profile.md)
- [工业与医疗场景合同](03_industrial_medical_profiles.md)
- [工具终局再认证合同](04_tool_final_recovery.md)
- [开发语义校验清单](semantic_cases.json)：协议轨迹定义，未将其状态作为比赛当前运行结果。

| Profile | Schema | 协议运输定义 |
|---|---|---|
| PAY-1 | [pay1.schema.json](contracts/pay1.schema.json) | [pay1.openapi.json](contracts/pay1.openapi.json) |
| IND-DEMO-1 | [industrial.schema.json](contracts/industrial.schema.json) | [industrial.openapi.json](contracts/industrial.openapi.json) |
| MED-DEMO-1 | [medical.schema.json](contracts/medical.schema.json) | [medical.openapi.json](contracts/medical.openapi.json) |

OpenAPI 描述协议目标运输职责，不是当前已实现的 HTTP 路由。Schema 检查结构；签名、Ref、依赖、当前资格和 W 状态约束由运行代码检查。公开向量用于编码与密码校验，不是可执行批准链或业务运行证据。

```powershell
python system_dev/v26/tools/build_contracts.py
python system_dev/v26/tools/verify_contracts.py
```

生成器使用 `tools/pay-record-base.schema.json` 中的基础记录结构生成 PAY 字段；运行入口仅接受当前 Profile Schema。[校验报告](verification_report.json)记录结构/编码检查，[公开向量](vectors/wire_vectors.json)保留可重算字节。真实模拟路径和保证范围使用[比赛证据清单](../../competition/docs/final/claims-evidence.md)。
