# 协议层交接包：ZJJ-CORE-2.6-R2

日期：2026-10-07。本目录按开发记录补全核心及三个固定Profile的协议定义。核心仍为10种签名消息，准备/控制/来源/资源/工具记录仍在支撑层；没有新增核心通信轮次。R2表示工具终局恢复合同修订，Envelope.version仍为"2.6"；已有v2.5及局部实验不改标。

后续[质疑审查](../../docs/证决界_v2.6_R1_协议质疑审查_2026-10-07.md)发现的工业决策包常量互拒已修复；R2通过[工具终局再认证合同](04_tool_final_recovery.md)关闭A02的协议恢复缺口，并提供[局部签名模型验证](../../verification/protocol_v26_final_recovery/README.md)。同一持久事实可用当前合法工具钥重新认证；新RecordRef不产生第二次执行或结算。账连续性、当前认证及原派发绑定是恢复前提。审查中的其他澄清项和产品验收仍保留，不宣称协议已无漏洞。

阅读顺序：

1. [核心精确合同](01_core_contract.md)：编码、摘要、10类payload、引用类型、受众、依赖、资格、时间、冻结/恢复、Result、工具终局。
2. [PAY-1固定合同](02_pay1_profile.md)：来源白名单、完整history-int-v2、批准/资源及派发规则。
3. [工业/医疗固定合同](03_industrial_medical_profiles.md)：合成来源、严格动作/阶段、读取与主体分离、状态覆盖及占用。
4. [工具终局再认证](04_tool_final_recovery.md)：事实/证明分离、账连续性、首次延迟与换钥恢复、幂等结算及可信矛盾。
5. [语义符合性用例](semantic_cases.json)：39项实现时应逐项验证的协议轨迹；当前全部NOT_RUN。

结构合同为JSON Schema Draft 2020-12，全部字段必需、未知字段拒绝：

| Profile | 结构Schema | 协议运输结构 |
|---|---|---|
| PAY-1 | [pay1.schema.json](contracts/pay1.schema.json) | [pay1.openapi.json](contracts/pay1.openapi.json) |
| IND-DEMO-1 | [industrial.schema.json](contracts/industrial.schema.json) | [industrial.openapi.json](contracts/industrial.openapi.json) |
| MED-DEMO-1 | [medical.schema.json](contracts/medical.schema.json) | [medical.openapi.json](contracts/medical.openapi.json) |

Schema根验证Envelope；Record/Bundle/Action等用其`$defs`。OpenAPI只定义固定协议运输职责，不含展示软件API、会话、DB物理表或部署。Schema不检查签名、规范原始字节、Ref重算、完整依赖、跨字段相等、时效与W事务；这些在精确合同中逐项规定，不能用“Schema通过”作为允许执行的条件。

本轮将草图中未定项明确为协议取值，包括完整Action存于Basis、G/X固定签署kid、角色用途与scope范围、认证Record结构、场景前后见证及统一终局。工业两阶段、医疗每就诊单组、证据300秒/任务900秒、8槽/累计32、关闭可选历史是本轮保守演示取值，不是实测工业/临床参数。未来修改须新合同修订与重新生成向量；不能在实现中无声改动。

## 已核查与尚未执行

[验证报告](verification_report.json)记录本轮实际结构/密码检查和文件SHA-256；[公开向量](vectors/wire_vectors.json)包含每Profile每核心type的规范字节、签名输入、签名、Ref及Record/AH摘要。**向量中的对象引用是结构占位，不构成可接受业务链或真实权威快照。** 同一公开测试钥仅供字节互操作，不代表合法U/V分离或生产身份。

当前371项结构/密码检查通过，公开向量为30个Envelope、34个Record、3个Action摘要及3个真实签名工具终局，Node交叉核对70项。Python检查标准Schema、缺字段/额外字段/JSON number/错Profile/错scope、整数上界、严格点与签名负例，并从规范独立核对工业package_id。Node使用独立规范编码与内置密码库核对字节、摘要、确定性签名及FinalFactID；未实现全部Schema/严格子群拒绝/业务状态机，不能宣称完整双实现互操作。

A02另有16项局部签名模型测试通过，原R1两个恢复断言仍按预期失败。该模型检验过期/换钥恢复、同事实幂等、并发结算、坏输入与可信矛盾；不验证真实C移交、持久工具账、跨操作唯一索引或崩溃一致性。执行/效果计数来自预置事实，不能当成真实工具执行实验。

完整正负业务轨迹、控制/来源导入、接受并发/故障、可信终局、跨版本迁移及66项系统验收仍需在开发实现后执行；不因本包生成而改为PASS。协议定义已提供，运行证据尚不由本包产生。原三项局部补全实验与本包不是同一Profile/消息合同。

## 复现协议材料

使用已有Python/jsonschema/cryptography/PyNaCl及Node环境，从项目根目录运行：

```powershell
python system_dev/v26/tools/build_contracts.py
python system_dev/v26/tools/verify_contracts.py
python verification/protocol_v26_final_recovery/run_all.py
```

生成器只写本目录结构合同与公开向量/验证报告，不启动产品、不执行工具、不修改旧协议/旧实验。依赖及运行环境记录在报告中；开发团队自行决定产品语言和框架。

本目录与旧[system_dev/contracts](../contracts/)分开：后者保持DEV-PAY1-0.1/v2.5。若旧衔接草图与本轮精确字段冲突，以01/02/03/04的2.6-R2为准；软件建设仍由[原交接入口](../START_HERE.md)组织。
