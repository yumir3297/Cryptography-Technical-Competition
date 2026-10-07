# v2.6 工业与医疗固定演示 Profile 合同

日期：2026-10-07。状态：协议合同补全；未实现、未运行符合性验收。本文仅冻结协议和受控数据语义，不交付界面、工具实现或部署。不增加十种核心签名消息，不增加核心交互轮次。

规范 Profile 为 `IND-DEMO-1` 与 `MED-DEMO-1`，线版本均为 `2.6`，scope.scenario 分别为 `industrial`、`medical`。它们与 `PAY-1/payment` 并列，不能当作付款 payload 的变体。本文在本目录通用线格式之上规定精确场景值；与旧设计中的“候选/建议/尚待冻结”冲突时，以本文明确列出的本轮取值为新合同，旧材料仍保留其原版本事实。

2026-10-07 R2终局修订：工具采用[不可变事实与当前再认证合同](04_tool_final_recovery.md)。同一事实可以有不同认证RecordRef，仍只结算一次；只有已认证、正确绑定的不可变事实矛盾才HALTED。旧钥/过期证明不直接首次结算；工具从连续原账以当前钥重新认证，恢复不执行。以下场景终局规则按该合同解释，其余固定算法/角色/资源/阶段不变。

## 1. 类型与认证约定

共同 `Envelope.protected={proto,version,profile,alg,type,issuer,kid}`、`body={id,scope,iat,exp,aud,refs,deps,payload}`，共同 Action 顶层与 Ctx 均不变。Action.payload 按本文件所属 Profile 唯一解析。十种核心 type 仍为 Review、Authorization、IssueRequest、Permit、ChallengeRequest、Challenge、CommitProof、Acceptance、Result、StatusQuery。

所有受控 Record 外壳精确为 `{version:"2.6",profile,kind,scope,value}`；`record_ref=RecordRef(profile,kind,scope,value)`，摘要输入包含版本和 Profile。下文对象字面量列出其全部必需成员；未知成员、null、缺省均拒绝。`Id/B16/B32/B64/N`、规范排序和编码采用本目录通用合同；`Positive` 是大于零的 N。时间和数值均用规范十进制字符串；`true/false` 只用于明示布尔字段。数组被称为“集合”时，元素规范编码排序、不得重复；单位集合最多16项，读者角色集合最多8项，其余许可集合最多16项。

本文件定义专用支撑 kind：`IND_TASK`、`IND_UNIT`、`IND_EVIDENCE`、`IND_PACKAGE`、`MED_TASK`、`MED_ENCOUNTER`、`MED_EVIDENCE`。共同 kind `POLICY/BASIS/ASSESSMENT/COMMIT` 继续存在；身份引用的预期 kind 为 `KEY_GRANT/ROLE_GRANT`。专用 kind 不是新增核心 Envelope type。

### 1.1 受控发布身份

本Profile新增最大寿命常量：POLICY、IND_PACKAGE、IND_UNIT、MED_ENCOUNTER最长31536000秒；IND_TASK/MED_TASK最长900秒；ASSESSMENT/BASIS最长900秒。来源证据另按§1.2的采样300秒上限，其他核心消息沿用共同120/30/900秒限制。ASSESSMENT与对应BASIS使用同一iat和exp，exp取`min(iat+900,所有基础承重对象及资格exp)`；绝不能用最大寿命越过来源期限。历史COMMIT/当前行及接受/消费/意图墓碑不因这些到期时间删除。

POLICY、任务、工件/就诊登记和工业决策包只能由当前 POLICY.controller 所指登记主体以本 Profile 的 `CONTROLLER` 资格、经认证内部控制入口发布；初始化第一份 POLICY 由域控制根授予的 CONTROLLER 发布。W 留存认证入口生成的 publisher subject/kid、KEY/ROLE 引用、命令规范字节、请求ID、CAS前后revision、W seq和应用回执。客户端传入 publisher 名称不能形成认证元数据。

来源 Evidence 必须由 POLICY.source 指定主体以 `SOURCE` 资格发布，且保留下述签名。W 入库前同时核对认证通道主体与 attestation.issuer、kid、对象scope/Profile、当前 KEY用途SOURCE及ROLE范围；不允许经H上传一个摘要便获得权威身份。对历史导入保留原认证事实，执行资格仍查当前来源/密钥/角色及撤销。控制发布与来源导入属于受控内部合同，本轮不新增管理网络端点。

RecordRef只是定位和完整性值。验证者必须按字段固定的kind解析、重算摘要、检查权威库的来源认证元数据及资格图。权威库已确定对象不存在/类型错误为F；合法引用的权威暂不可读为U；不能从客户端缓存补成T。

### 1.2 固定 SourceAttestation

`IND_EVIDENCE.value` 与 `MED_EVIDENCE.value` 均精确为 `{data,attestation}`。`attestation={issuer:Id,kid:B32,iat:N,exp:N,sig:B64}`。令 `a={issuer,kid,iat,exp}`，来源签名输入为：

```text
Enc(["ZJJ-SOURCE-v1","2.6",profile,kind,scope,data,a])
```

使用共同 Ed25519 严格验签规则；sig不进入自己的签名输入，输入也不包含Evidence自身RecordRef，避免引用环。该签名对象仅认证固定来源数据，不能充当Review、Authorization、Permit或Acceptance。IND签名的kind只能为IND_EVIDENCE；MED签名的kind只能为MED_EVIDENCE。签名者必须为POLICY.source，证据不接受其他模型/持有者自签事实。

工业时间满足 `sampled_at <= known_at <= attestation.iat`，医疗满足 `event_at <= known_at <= attestation.iat`；attestation.iat须不晚于W可信t_lo。证据有效期要求 `iat < exp`，且 `exp <= observed_at+300`，其中工业observed_at=sampled_at，医疗observed_at=event_at。鉴别300秒边界用共同时间区间规则；未来已知时间/明确过期为F，跨界/时钟未知为U。下游Basis、Review、Authorization、Permit不得晚于承重上游到期时间；不能只核对Evidence签名而忽略300秒采样时效。

## 2. 工业 IND-DEMO-1

证据attestation.exp还须不晚于其身份登记、来源KEY/ROLE和适用POLICY的exp；300秒上限不会延长任何资格。

### 2.1 固定能力、策略和决策包

唯一工具为 `line-sort-sim`，tool_version=`1`。它仅处理一个合成工件的一次分流；没有设备控制、PLC参数、任意命令或模型调用能力。

工业 `POLICY.value` 全部字段为：

```text
{
 policy_revision:Positive, profile:"IND-DEMO-1",
 schema_version:"ind-payload-v1", verifier_version:"ind-fixed-v1",
 controller:Id, gateway:Id, gateway_kid:B32, executor:Id, executor_kid:B32, source:Id,
 readers:[Id], tool:"line-sort-sim", tool_version:"1",
 line_id:"demo-line-a", station_id:"demo-check-1",
 route_destinations:{release:"ind-release-bin",quarantine:"ind-quarantine-bin",inspect:"ind-inspection-bay"},
 decision_package_ref:B32, history_mode:"DISABLED", max_cycles:"2",
 evidence_ttl_seconds:"300", task_ttl_seconds:"900",
 behavior_count_cap:"32", capacity_per_destination:"8",
 iat:N, exp:N
}
```

readers列出允许申请读取的登记主体白名单，不替代当前READER角色及对象范围核验。POLICY.source/controller/gateway/executor不能由请求自选。policy_revision单调增加；同名verifier/package不代表同一摘要。部署实现若未绑定这两个固定schema/verifier标识，则不得对本Profile发许可。

`decision_package_ref`预期kind为IND_PACKAGE，value全部字段为：

```text
{
 package_id:"ind-fixed-package-1", package_revision:Positive,
 detector:"SYNTHETIC-LABEL-1", preprocessing:"IDENTITY-1",
 output_schema:"IND-LABEL-V1", mapper:"IND-ROUTE-V1",
 label_routes:{normal:"RELEASE",defect:"QUARANTINE",uncertain:"INSPECT"},
 iat:N, exp:N
}
```

四个标识与label_routes必须逐项等于上述常量；package需当前CONTROLLER批准且未撤销，iat/exp有效。不能将不同检测器/预处理/schema/mapper组成新的组合；不使用任意表达式、URL、renderer路径或所谓“模型兼容=true”。POLICY精确引用该包，故包变更必须新POLICY并重新准备；依赖无需另加PACKAGE namespace。

### 2.2 Action、任务与工件登记

工业Action.payload精确为：

```text
{line_id:Id,station_id:Id,unit_id:Id,batch_id:Id,
 inspection_cycle:Positive,phase:"INITIAL"|"REINSPECT",
 route:"RELEASE"|"QUARANTINE"|"INSPECT"}
```

line/station必须等于POLICY固定值。cycle/phase仅能为`("1","INITIAL")`或`("2","REINSPECT")`。Action.destination按route分别等于POLICY.route_destinations.release/quarantine/inspect；Action.executor、tool、tool_version分别等于POLICY。主体及holder/kid与当前任务完全相等。route不承载任意工具参数。

`IND_UNIT.value`是工件的不可变合成身份登记，全部字段为 `{unit_id:Id,batch_id:Id,line_id:Id,station_id:Id,synthetic:true,iat:N,exp:N}`，由CONTROLLER发布。身份登记一经被引用，不能改unit/batch/line/station；更正必须撤销原登记并暂停相关动作。已有接受墓碑不因更正删除。UNIT当前状态行保存身份ref和阶段状态，见§4；身份证据引用不随当前行revision推进而被偷偷换绑。

`IND_TASK.value`全部字段为：

```text
{
 task_id:B16, task_revision:Positive, policy_ref:B32,
 principal:Id, holder:Id, holder_kid:B32, executor:Id,
 line_id:Id, station_id:Id,
 allowed_units:[{unit_ref:B32,unit_id:Id,batch_id:Id,inspection_cycle:Positive,phase:"INITIAL"|"REINSPECT"}],
 allowed_routes:["RELEASE"|"QUARANTINE"|"INSPECT"],
 tool:"line-sort-sim",tool_version:"1",
 route_destinations:{release:Id,quarantine:Id,inspect:Id},
 max_inflight:"1",iat:N,exp:N
}
```

allowed_units是1至16项的规范集合；unit_ref预期kind为IND_UNIT，重复unit_id拒绝。同一任务所有项必须同一cycle/phase；每项的身份、当前阶段和来源均核对。allowed_routes非空且不超出三路线；route_destinations精确复制POLICY固定映射，不能扩权。任务exp≤iat+900且不晚于承重POLICY/委托资格到期。TaskFlight每任务至多一个在途；次数上限由唯一unit阶段意图和BEHAVIOR累计32共同限制，不另设可重置的客户端次数字段。

稳定意图精确为 `Enc([domain,tenant,"industrial",line_id,unit_id,inspection_cycle,phase])`。不含route、batch、station、holder、task_id、operation_id或协议版本。W由已批准任务与UNIT阶段行查找/登记一个B16 operation_id；新任务或换route不能给同一意图分配第二操作。接受前修订同操作可创建新Basis；接受后Action冻结，任何终局仍保留意图墓碑。

### 2.3 来源证据

工业Task.policy_ref预期POLICY，须等于当前POLICY、Basis和Ctx的policy_ref；task_revision等于TASK当前revision。意图首次登记同时固定principal和稳定task_id，已有意图的不同principal/task_id为OPERATION_CONFLICT。更新holder/kid须保持这些字段、推进TASK revision并重新准备与重签；不能换Task归零累计次数。

`IND_EVIDENCE.value.data`全部字段为：

```text
{
 evidence_id:B16, evidence_revision:Positive,unit_ref:B32,
 unit_id:Id,batch_id:Id,line_id:Id,station_id:Id,
 inspection_cycle:Positive,phase:"INITIAL"|"REINSPECT",
 sampled_at:N,known_at:N,
 quality_flag:"VALID"|"INVALID",
 label:"DEMO_NORMAL"|"DEMO_DEFECT"|"DEMO_UNCERTAIN"
}
```

unit_ref预期IND_UNIT，证据字段与Task/Action/登记身份/当前UNIT阶段相等。W当前UNIT行必须恰好激活一个与该阶段匹配的证据ref；Basis.evidence_refs恰为该单元素集合。新证据、替换/撤回检测、采样质量变更及新的承重工件事实均推进UNIT覆盖revision，旧Basis失效。

只有quality_flag=VALID可作为有效合成标签；INVALID为F。DEMO_UNCERTAIN是来源认证的合成“不确定标签”，可以产生INSPECT候选；来源缺失/签名或当前性未知则为U，不得伪装成DEMO_UNCERTAIN。未知来源不生成可签发Basis。

### 2.4 Assessment与必要批准

工业evidence_revision按完整scope、line、unit、cycle、phase单调增加，不以换evidence_id重置；W的UNIT覆盖revision与来源revision分别核验，不得用其一猜另一个。

工业 `ASSESSMENT.value`全部字段为：

```text
{
 scope:Scope,operation_id:B16,action_hash:B32,policy_ref:B32,task_ref:B32,
 evidence_refs:[B32],decision_package_ref:B32,cutoff:N,
 method:"ind-fixed-v1",history_mode:"DISABLED",label:"DEMO_NORMAL"|"DEMO_DEFECT"|"DEMO_UNCERTAIN",
 proposed_route:"RELEASE"|"QUARANTINE"|"INSPECT",
 result:"MATCH",required_reviews:["QUALITY_REVIEW"]|[],iat:N,exp:N
}
```

这里result只有MATCH；不是PAY的CLEAR/FLAG/INSUFFICIENT。Assessment.iat=cutoff=Basis.iat，由受控准备服务取得可信时间，不由H回填。Assessment.exp=Basis.exp且不晚于承重POLICY/Task/Evidence/包/资格到期，exp>iat。E/G/H提供的label/route/result不被直接信任；X/W加载认证Evidence和精确决策包，独立重算：

| 已认证标签 | proposed_route / Action.route必须等于 | required_reviews |
|---|---|---|
| DEMO_NORMAL | RELEASE | 空集合 |
| DEMO_DEFECT | QUARANTINE | 空集合 |
| DEMO_UNCERTAIN | INSPECT | 恰一QUALITY_REVIEW |

任何不相等为F，不生成MATCH记录或可签发Basis。特别是缺陷RELEASE为硬失败，不能由QUALITY_REVIEW、一般批准或高置信覆盖。历史模式固定DISABLED，不创建EXPERIENCE依赖，不生成伪造CLEAR；未来启用历史是新Profile版本合同。

V须为当前QUALITY_REVIEWER，以QUALITY_REVIEW签恰一个APPROVE Review，ctx绑定同一Basis。U须为当前LINE_OPERATOR，签恰一个EXECUTE Authorization并精确引用必要Review集合。无Review需求时多余Review也拒绝。U/V登记subject必须不同；两把不同kid属于同一subject仍拒绝。所有U/V均不得与POLICY.gateway或POLICY.executor为同一登记subject；H可以与U同subject，但持有证明和执行授权仍是不同用途的独立签名对象。V的DENY使本Basis不可用于新签发/接受；不能删除DENY引用沿用该Basis。

### 2.5 两阶段与模拟终局

初次登记UNIT行为cycle=1、phase=INITIAL、state=READY。C不能自由增cycle。第一次已接受动作的可信终局决定：

| 路线与可信终局 | UNIT状态 | 可否受控推进 |
|---|---|---|
| RELEASE / SUCCEEDED | RELEASED | 工件结束，无下一阶段 |
| QUARANTINE / SUCCEEDED | QUARANTINED | 工件结束，无下一阶段 |
| INSPECT / SUCCEEDED，cycle=1 | AWAITING_REINSPECT | CONTROLLER可执行§5受控AdvanceIndustrialPhase |
| INSPECT / SUCCEEDED，cycle=2 | MANUAL_HOLD | 工件结束，无第三阶段 |
| 任一路线 / FAILED_CONFIRMED（确认无效果） | STOPPED | 保留接受墓碑；本Profile不自动建立重试阶段 |
| 任一路线 / EFFECT_UNKNOWN或HALTED | 对应未知/停止状态 | 禁止推进、改cycle或换任务重发 |

AdvanceIndustrialPhase必须给出第一阶段operation_id和COMMIT ref、原终局证据、UNIT CAS revision。W核验该操作是同工件cycle1/INITIAL的已接受INSPECT且唯一终局SUCCEEDED、已结算在途；当前UNIT为AWAITING_REINSPECT。成功只推进至cycle2/REINSPECT/READY，清空active evidence并推进覆盖revision。新的来源证据、Task范围、Basis及U/V签名均必需；不能把第一次检测直接标成第二次复检证据。

第二阶段仍按相同三标签映射；DEMO_UNCERTAIN的INSPECT效果是在同一ind-inspection-bay中标记合成人工留置并终止自动流程，不引入第四个可选目的工位，也不构成自动第三次复检。该两阶段上限和FAILED后的STOPPED是本轮保守取值，避免通过新inspection_id/phase规避未知和唯一接受。

## 3. 医疗 MED-DEMO-1

### 3.1 固定能力与策略

唯一工具 `med-order-sim/1` 只在本地合成医嘱账登记固定模板，不含疾病阈值、药物、剂量、治疗文本或外部回调能力。

医疗 `POLICY.value`全部字段为：

```text
{
 policy_revision:Positive,profile:"MED-DEMO-1",
 schema_version:"med-payload-v1",verifier_version:"med-fixed-v1",
 controller:Id,gateway:Id,gateway_kid:B32,executor:Id,executor_kid:B32,source:Id,readers:[Id],
 tool:"med-order-sim",tool_version:"1",destination:"med-demo-ledger",
 allowed_templates:["DEMO-ORDER-A","DEMO-ORDER-B"],
 template_mapping:{demo_a:"DEMO-ORDER-A",demo_b:"DEMO-ORDER-B"},
 history_mode:"DISABLED",required_review:"CLINICAL_REVIEW",
 evidence_ttl_seconds:"300",task_ttl_seconds:"900",
 behavior_count_cap:"32",destination_capacity:"8",max_groups_per_encounter:"1",
 iat:N,exp:N
}
```

allowed_templates和template_mapping精确等于上述常量，不是客户端可扩展模板库。readers仍仅白名单，需当前READER对象范围；AUDITOR不自动获得READER资格。模板A/B是无临床含义的合成值，选择它们不表示诊疗正确性。

### 3.2 Action、就诊与任务

医疗Action.payload精确为：

```text
{synthetic_patient_id:Id,encounter_id:Id,order_group_id:B16,
 phase:"SUBMIT",template_id:"DEMO-ORDER-A"|"DEMO-ORDER-B",
 record_ref:B32,destination_system:"med-demo-ledger"}
```

record_ref预期kind MED_EVIDENCE，不是任意文件、临床记录URL或Envelope Ref。destination_system须等于Action.destination和POLICY.destination；tool/version/executor等于POLICY。禁止其他phase、医嘱文本和额外参数。

`MED_ENCOUNTER.value`全部字段为 `{synthetic_patient_id:Id,encounter_id:Id,synthetic:true,iat:N,exp:N}`，由CONTROLLER发布，固定合成身份关联。普通相同字符串patient_id不证明合成登记存在；跨scope的同名就诊必须是不同身份对象。

`MED_TASK.value`全部字段为：

```text
{
 task_id:B16,task_revision:Positive,policy_ref:B32,principal:Id,holder:Id,holder_kid:B32,executor:Id,
 encounter_ref:B32,synthetic_patient_id:Id,encounter_id:Id,order_group_id:B16,
 phase:"SUBMIT",allowed_templates:["DEMO-ORDER-A"|"DEMO-ORDER-B"],
 tool:"med-order-sim",tool_version:"1",destination:"med-demo-ledger",
 max_inflight:"1",iat:N,exp:N
}
```

encounter_ref预期MED_ENCOUNTER，所有重复字段核对。allowed_templates非空且不扩展POLICY。任务exp≤iat+900及承重POLICY/委托资格到期。W在受控CreateMedicalTask中，为尚未绑定组的就诊分配唯一B16 order_group_id，原子登记于ENCOUNTER行；相同就诊的新Task必须沿用该组，不能由H自由提供或换组重试。该Profile每就诊仅一个组、仅一个SUBMIT阶段；多组与进一步诊疗流程需要独立新合同，本轮不提供。

稳定意图为 `Enc([domain,tenant,"medical",synthetic_patient_id,encounter_id,order_group_id,"SUBMIT"])`，不含template_id、record_ref、holder、task_id、operation_id、协议版本。W分配唯一operation_id；接受前更新记录/模板使用同意图重新准备，接受后包括FAILED终局都保留墓碑。同一就诊不能另建order_group从未知操作脱身。

### 3.3 来源、读取与Assessment

医疗Task.policy_ref预期POLICY，须等于当前POLICY、Basis和Ctx的policy_ref；task_revision等于TASK当前revision。意图首次登记同时固定principal和稳定task_id，已有意图的不同principal/task_id为OPERATION_CONFLICT。更新holder/kid须保持这些字段、推进TASK revision并重新准备与重签。

`MED_EVIDENCE.value.data`全部字段为：

```text
{
 evidence_id:B16,evidence_revision:Positive,encounter_ref:B32,
 synthetic_patient_id:Id,encounter_id:Id,record_id:Id,record_revision:Positive,
 record_status:"AVAILABLE"|"UNAVAILABLE",completeness:"COMPLETE"|"INCOMPLETE",
 template_label:"DEMO_A"|"DEMO_B",event_at:N,known_at:N
}
```

encounter_ref预期MED_ENCOUNTER；patient/encounter必须与登记、Task和Action匹配。每就诊仅一份当前承重记录；ENCOUNTER当前行指向其MED_EVIDENCE ref，Action.record_ref和Basis.evidence_refs的唯一元素必须是该ref。新增/替换/撤回任何可能改变记录结论的事实、record_revision、可用性或完整性都推进ENCOUNTER覆盖revision。record_id/record_revision不能替代完整ref核验；不得只凭客户端说“最新版”。

AVAILABLE且COMPLETE才为T；已知UNAVAILABLE或INCOMPLETE为F；来源暂不可读/授权时间跨界为U。准备时可将确定缺材料呈现PENDING，但不能生成可签发Basis；完整提交这些硬条件为F，V/U普通批准不能将其改成T。template_label是认证合成标记，DEMO_A/B分别映射固定模板A/B，Action模板不相等为F。

医疗 `ASSESSMENT.value`全部字段为：

```text
{
 scope:Scope,operation_id:B16,action_hash:B32,policy_ref:B32,task_ref:B32,
 evidence_refs:[B32],cutoff:N,method:"med-fixed-v1",history_mode:"DISABLED",
 template_label:"DEMO_A"|"DEMO_B",proposed_template:"DEMO-ORDER-A"|"DEMO-ORDER-B",
 result:"MATCH",required_reviews:["CLINICAL_REVIEW"],iat:N,exp:N
}
```

Assessment.iat=cutoff=Basis.iat，Assessment.exp=Basis.exp且不晚于承重POLICY/Task/Evidence/资格到期，exp>iat。固定认证输入重算MATCH，不使用历史CLEAR概念，不产生EXPERIENCE依赖。所有医疗动作恰需一个V的CLINICAL_REVIEW APPROVE，以及一个独立U的EXECUTE Authorization；V角色CLINICAL_REVIEWER，U角色MEDICAL_AUTHORIZER。V/U不同subject，且均不能等于G/X登记subject。H可与U同主体，签名用途仍分别验证。医疗角色名仅模拟权限登记，不表示验证真实执业资质。缺领域复核拒绝，多余ANOMALY/LOW_EVIDENCE/QUALITY_REVIEW也拒绝；不能套用PAY的CLEAR免V路径。DENY与重新准备规则同工业。

在准备、读取Basis、展示给U/V、候选模块取数据之前，先验证认证Actor当前READER资格、KEY、POLICY.readers、完整patient/encounter范围和读权限撤销。没有读取权的H/U/V不能批准本记录；角色可同时授予READER，但不能从U/V名称推导权限。候选模块也是独立登记读取主体，无数据库/工具/私钥直通能力。读权限是审批和接受承重依赖；读权限变化使旧Basis/批准失效。普通AUDITOR只可读脱敏操作状态，不得解析MED_EVIDENCE/BASIS的患者详情。

本合同的输出裁剪仅允许给AUDITOR返回 `{scope,operation_id,accepted,action_hash,effect_status,status_seq}`；operation_id必须先通过其scope查询资格。不给其患者/就诊、record_ref、模板、完整Action/Basis、来源内容、自由文本reason。裁剪不是生成另一份可验证Evidence；验证器仍只读取权威完整对象。

### 3.4 医疗阶段与终局

医疗evidence_revision按完整scope/patient/encounter单调增加；record_revision按同范围加record_id单调增加。换evidence_id不能重置evidence_revision，W的ENCOUNTER覆盖revision与来源revision分别核验。

ENCOUNTER初始READY；只有唯一组SUBMIT可接受。SUCCEEDED将状态置REGISTERED，FAILED_CONFIRMED置STOPPED；两者均无自动第二组/第二阶段。EFFECT_UNKNOWN/HALTED保留原组、意图、在途与占用，禁止换患者/就诊/模板/组绕过。终局描述只为“模拟医嘱已登记/确认未登记”，不表示完成诊疗或给药。

## 4. 角色、完整依赖与资源

### 4.1 固定角色范围

readers为非空Id主体集合、最多8项，实际H/G/X/U及必要V必须在其中；新增候选读取主体也须显式在白名单并有当前READER授权。tool_set只包含动作tool的Id（line-sort-sim或med-order-sim）；工具版本不是tool_set中的自由复合字符串，而按POLICY/Task固定tool_version="1"另作精确比较。destination_set中的值须为合法小写Id。集合标识不自动大小写转换。

共同ROLE_GRANT.value使用本目录约定的 `{subject,role,epoch,iat,exp,tool_set,destination_set,scope_set,constraints}`。scope_set必须包含完整domain/tenant/scenario；tool_set包含动作工具Id，版本另按POLICY固定值核对，destination_set包含动作固定目的地。constraints按Profile/role选择下表唯一精确结构；未知字段和通配星号拒绝。controller/source/gateway/executor还须匹配POLICY对应subject，不能只凭角色名称。

| Profile / role | constraints全部字段 |
|---|---|
| IND / CONTROLLER、SOURCE、ISSUER、EXECUTOR | `{line_set:[Id],station_set:[Id],route_set:[Route]}` |
| IND / HOLDER、LINE_OPERATOR、QUALITY_REVIEWER、READER | `{line_set:[Id],station_set:[Id],unit_set:[Id],route_set:[Route]}` |
| MED / CONTROLLER、SOURCE、ISSUER、EXECUTOR | `{patient_set:[Id],encounter_set:[Id],template_set:[Template]}` |
| MED / HOLDER、MEDICAL_AUTHORIZER、CLINICAL_REVIEWER、READER | `{patient_set:[Id],encounter_set:[Id],template_set:[Template]}` |
| 任一Profile / AUDITOR | `{scope_set:[Scope]}` |

Route/Template分别为本文件三路线/两模板。全部范围集合非空、≤16项；AUDITOR scope_set非空、≤8项且精确scope。嵌套的patient_set与encounter_set是AND范围，并须验证两者受控关联，不能只检查患者或只检查就诊。工业同样核line、station、unit和route。SOURCE只可认证自己范围内数据；SOURCE的route/template范围必须覆盖其标签映射的结果。QUALITY_REVIEWER.route_set必须恰为INSPECT；医疗两复核/授权角色范围覆盖所选模板。READER读某对象前核对象标识/路线或模板，Task中的holder授权不自动赋读权。

KEY_GRANT必须允许具体用途：C为CONTROL，E为SOURCE，V签Review，U签Authorization，H分别签IssueRequest/ChallengeRequest/CommitProof/StatusQuery，G分别签Permit/Result，X分别签Challenge/Acceptance/Result；取数据的Actor还须READ用途。用途精确对应消息type或这三项支撑用途，不以HOLDER/ISSUER等角色标签充当签名用途。相同钥支持多用途必须有明确登记用途集合，不能从签名可验证推导资格。承重主体身份按KEY.subject=ROLE.subject并核W登记关系；不能按显示名称或kid不等判断主体分离。

### 4.2 固定动态行与依赖键

Dep仍为 `{namespace,key,revision,ref}`，所有key展开完整scope，不使用JSON对象或拼接短名称。下表中S代表`[scope.domain,scope.tenant,scope.scenario]`的三个独立元素，`S+[...]`是数组连接。

| namespace | 工业key | 医疗key | ref预期 |
|---|---|---|---|
| POLICY | S | S | 当前POLICY RecordRef |
| TASK | S+[task_id] | S+[task_id] | 当前IND_TASK/MED_TASK RecordRef |
| UNIT | S+[line_id,unit_id] | 不允许 | 当前UNIT状态行摘要 |
| ENCOUNTER | 不允许 | S+[synthetic_patient_id,encounter_id] | 当前ENCOUNTER状态行摘要 |
| BEHAVIOR | S+[principal] | S+[principal] | 当前BEHAVIOR状态行摘要 |
| ROLE | S+[subject,role] | 同左 | 当前ROLE_GRANT RecordRef |
| KEY | [kid] | [kid] | 当前KEY_GRANT RecordRef；仍须核scope资格 |

KEY/ROLE的当前身份合同、epoch、墓碑等采用本目录通用控制合同；本表不允许再加其他随机namespace。UNIT/ENCOUNTER行以通用ZJJ-STATE-v1公式计算摘要。行值精确结构：

```text
IndustrialUnitRow={unit_ref:B32,inspection_cycle:Positive,phase:"INITIAL"|"REINSPECT",
 state:"READY"|"ACCEPTED"|"RELEASED"|"QUARANTINED"|"AWAITING_REINSPECT"|"MANUAL_HOLD"|"STOPPED"|"EFFECT_UNKNOWN"|"HALTED",
 evidence_ref:B32|"",operation_id:B16|"",predecessor_operation_id:B16|"",predecessor_commit_ref:B32|""}
MedicalEncounterRow={encounter_ref:B32,order_group_id:B16|"",phase:"SUBMIT",
 state:"READY"|"ACCEPTED"|"REGISTERED"|"STOPPED"|"EFFECT_UNKNOWN"|"HALTED",
 evidence_ref:B32|"",operation_id:B16|""}
BehaviorRow={accepted_count:N,count_cap:"32",inflight:[B16]}
TaskFlightRow={operation_id:B16|""}
```

revision/active/ref是通用当前行外层元数据，不重复塞进row value。初始row的evidence_ref和operation_id为空；Medical初始order_group_id为空，仅CreateMedicalTask可填写。Industrial cycle1前序字段均空；cycle2二者必填并指向已结算第一阶段INSPECT。evidence_ref预期本Profile EVIDENCE，unit_ref/encounter_ref预期本Profile身份登记。状态转换、采纳/撤回证据、新事实及角色/任务变动推进对应覆盖revision；UI刷新/查询不推进业务revision。

工件/就诊行在接受时从READY转ACCEPTED并记录operation_id。这与BEHAVIOR/TaskFlight同属本操作接受改变的行；派发须使用COMMIT接受后见证，不误比较Permit接受前UNIT/ENCOUNTER/BEHAVIOR revision。UNIT/ENCOUNTER当前revision/ref/row必须精确等于COMMIT.scene_after；只允许接受事务的这一次自变，任何外部证据/事实/阶段更新均使pending停止派发。BEHAVIOR当前revision可因其他工件/其他操作增加，但须审查单调变更见证，本操作占用、累计不变量必须仍成立。

Basis.deps由固定验证器构造POLICY、TASK、UNIT/ENCOUNTER、BEHAVIOR，加上政策/任务/来源/包/身份登记publisher和H的KEY/ROLE资格闭包。医疗还加入准备读取Actor以及当前H/U/V所需READER资格；U/V在批准时才确定的KEY/ROLE/READER进入Permit的扩展闭包，不反向写旧Basis。IND可读审阅Actor同理。当前读取权限是承重边；纯历史注册出处不是无限递归当前依赖。

Permit.deps进一步加入所有Review/Authorization签发者、G、H、X及其KEY/ROLE承重闭包。X会话在挑战/接受时另查，不把尚不存在Challenge塞入Basis；X已登记的EXECUTOR资格属于签发时可定位的依赖，仍须派发重查。`Normalize(隐式依赖∪认证对象声明的传递依赖)`由G与X/W分别独立重建，精确比较Permit，缺项/多项/冲突拒绝；policy/Task、identity、证据当前激活行与对象撤销均要重查。新行/空集、当前唯一证据、没有另一在途动作和TaskFlight必须有覆盖revision或同W唯一约束保护。

医疗/工业历史模式DISABLED明确不查EXPERIENCE；不能把不存在历史视为风险CLEAR。资源不固定签发时余额；资源key和数量由固定Action独立导出，在接受事务重读。

### 4.3 资源账与自身占用

工业资源key为 `S+["route-capacity",line_id,Action.destination,"unit"]`；医疗资源key为 `S+["order-capacity",Action.destination,"order"]`。资源不是Dep新增namespace。工业三个目的地各容量8，医疗全scope共享登记目的地容量8，不按patient/Task分出独立额度。每动作预占恰为`"1"`，ResourceWitness.unit工业为`"UNIT"`、医疗为`"ORDER"`。资源行精确为 `{capacity:"8",reserved:N,spent:N}`，每操作reservation精确为 `{operation_id:B16,resource_key:[Id],quantity:"1",state:"RESERVED"|"SPENT"|"RELEASED"}`，固定key长度由上文确定。

同W接受事务检查 `reserved+spent+1 <= 8`、Behavior.accepted_count<32、本intent未接受、工件/就诊READY及TaskFlight为空；成功原子增加reserved、accepted_count、inflight和TaskFlight，冻结Action、派发请求、COMMIT及待签Acceptance。所有动作含QUARANTINE/INSPECT均受同一批准/资源规则。不能先接受再查隔离区容量。

可信SUCCEEDED一次将本操作reserved转spent、清除本操作Behavior.inflight/TaskFlight；spent为本演示epoch内累计成功占槽，不自动腾回。可信FAILED_CONFIRMED一次只释放本操作reserved和在途，不增加spent；接受数、Permit/nonce消费和意图墓碑保留。EFFECT_UNKNOWN/HALTED不释放占用，不减累计，不换组/工件阶段。该8槽累计账为本轮保守演示取值，不是现实工位流转容量模型；满槽需停止新接受，本合同没有无条件清账/reset命令。

COMMIT共同value严格采用[核心合同§2.2](01_core_contract.md)，不删trusted_time、credential_witnesses或signing_public_key。frozen_tool_request等于完整Action。本Profile还必须冻结 `scene_before/scene_after`，每项为 `{namespace:"UNIT"|"ENCOUNTER",key:[Id],revision:Positive,ref:B32,row:IndustrialUnitRow|MedicalEncounterRow}`，kind/Profile决定唯一选择。scene_after.revision=scene_before.revision+1，两ref使用相应StateRef重算；除state从READY转ACCEPTED、operation_id填本操作外，scene_after.row其他字段与before完全相同。COMMIT不引用Acceptance；事务先固定COMMIT/ref再固定Acceptance protected/body/ref，签名失败恢复原字节。

## 5. 派发、可信终局与内部命令

固定内部职责为PrepareIndustrial、PrepareMedical、ImportIndustrialEvidence、ImportMedicalEvidence、CreateIndustrialTask、CreateMedicalTask、AdvanceIndustrialPhase。它们接收认证Actor、严格类型化输入、request_id:B16及CAS revision；Actor不从客户端subject/role反序列化。请求幂等以完整scope、Actor.subject、request_id为键；同规范输入返回原持久结果，异输入ID_CONFLICT。客户端只能提交固定候选字段/证据签名，不提交任意schema、验证器、tool路径、record kind或row字典。

派发前在同W事务核 `t_hi<dispatch_before`、当前策略/任务/来源/全部批准及读取资格、精确工具映射、证据/阶段非自身变化、reservation归属/数量、TaskFlight和自身inflight；成功才CAS pending→started，分配唯一B16 dispatch_attempt。COMMIT.frozen_tool_request在两个Profile中均精确等于完整Action；实际派发包精确为 `{action:COMMIT.frozen_tool_request,action_hash:Ctx.action_hash,dispatch_attempt:B16,ledger_id:Id}`；ledger_id来自与started同事务冻结的工具见证，不由客户端选择。工具固定解析Action全部顶层及本Profile payload，不能从候选重新拼接，也不能派发时加未签的effect参数。

工具终局统一采用[核心合同§5.1](01_core_contract.md)的`TOOL_FINAL` Record、精确value、固定独立工具公钥映射及`ZJJ-TOOL-FINAL-v2`签名，不另定义异构无签终局。W核对工具身份/版本/目的地与POLICY以及COMMIT.Action绑定，不能把POLICY.executor的一般业务签名或H/G/普通Actor上传成功标志当作工具认证。工具没有网络回调URL参数。终局认证元数据保存工具身份、冻结Action与派发包摘要和原始终局字节，供审计核验；不是第十一种核心消息。

TOOL_FINAL中的scope（外壳）、operation_id、action_hash、dispatch_attempt、tool/tool_version/destination必须精确匹配COMMIT与唯一started派发。工业unit/batch/line/station/cycle/phase/route与医疗patient/encounter/order_group/template/record_ref无需增加为终局自由字段，而是通过AH解析原完整Action并逐项核对工具账所存冻结请求。SUCCEEDED须effect_id:Id非空且在完整(scope,ledger_id)内永久唯一、no_late_effect=false；FAILED_CONFIRMED须effect_id空、no_late_effect=true，并由工具权威确认从未产生效果且不会迟到生效。时间/工具状态未知时暂缓结算。

按R2 FinalFactID及完整事实幂等结算；同事实新认证RecordRef无第二结算。先通过当前认证、时间与原派发/账绑定后，不同effect_id、相反outcome或其他不可变事实矛盾才使操作HALTED并保持既有账，不根据最后一条猜测回滚。未认证/错绑定输入只拒绝或暂缓；HALTED不由同事实再认证解除。仅“工具当前查不到”不是FAILED_CONFIRMED。EXEC-0在started之后的丢回执、宕机、调用结果不明均保持EFFECT_UNKNOWN且禁止自动重派。pending确定过期/失格并CAS证明未领取时，可由W固定内部取消终态FAILED_CONFIRMED、无工具effect_id，不伪造TOOL_FINAL签名，并释放正确占用；pending未知则保持占用暂缓领取。

工业AdvanceIndustrialPhase是唯一阶段推进命令；医疗没有Advance/new-group命令。所有可信终局与推进由同一W顺序写入覆盖revision。接受已发生但Acceptance待签，不重新接受/重派；状态查询认证当前查询权限并返回原接受与新鲜状态，绝不触发派发或释放资源。

## 6. 共同Basis、引用与跨Profile拒绝

`BASIS.value={scope,operation_id,action,action_hash,policy_ref,task_ref,evidence_refs,assessment_ref,required_reviews,deps,iat,exp}`。action为完整Action，必须与AH及Ctx相符；evidence_refs在两Profile均恰一项，assessment_ref必填，不用空串表达“无历史”。Basis.exp不晚于POLICY/Task/证据/包及承重资格到期，且由可信准备流程决定。Assessment、BASIS内部scope与Record外层scope相等。

| 引用字段 | IND预期kind | MED预期kind |
|---|---|---|
| policy_ref | POLICY / IND-DEMO-1 | POLICY / MED-DEMO-1 |
| task_ref | IND_TASK | MED_TASK |
| evidence_refs、Action.record_ref（仅MED） | IND_EVIDENCE | MED_EVIDENCE |
| assessment_ref | ASSESSMENT / IND | ASSESSMENT / MED |
| decision_package_ref | IND_PACKAGE | 不存在，携带即格式拒绝 |
| unit_ref | IND_UNIT | 不存在 |
| encounter_ref | 不存在 | MED_ENCOUNTER |
| predecessor_commit_ref、commit_record_ref | COMMIT / IND | COMMIT / MED（仅后者） |
| basis_ref | BASIS / IND | BASIS / MED |
| review/authorization/permit/challenge/proof/request/acceptance refs | 指定核心Envelope.type及相同Profile | 同左 |

Record引用不进入body.refs，body.refs仍恰是payload直接Envelope引用集合；Record在签名payload/ctx中的绑定与完整图限制依旧执行。类型检查不能以“相同B32且能在某库找到”替代。Action/Record摘要Profile隔离，Envelope保护头同时绑定Profile；所有引用边scope/Profile相同，KEY/ROLE通用资格按通用控制合同验证其明确scope_set，而不能借PAY业务对象授权工业/医疗。

运输路径固定：PAY仍 `/zjj/2.6/{issue,challenge,commit,status}`；IND仅 `/zjj/2.6/industrial/{issue,challenge,commit,status}`；MED仅 `/zjj/2.6/medical/{issue,challenge,commit,status}`，均POST。路径、protected.profile、scope.scenario、type与aud必须共同一致；任一错配拒绝，不回退PAY、不按当前场景tab重解旧对象。未被本合同支持的profile/version/phase/tool/schema拒绝。

两Profile均沿用共同T/F/U和错误分类；硬事实为假、错误引用/主体/路线/模板/漏复核为F；权威/时间/合法对象暂不可取为U；准备人工未签为PENDING；完整提交缺签为F。可用既定码BINDING、WRONG_SCOPE、UNSUPPORTED_VERSION、BAD_SIGNATURE、CLAIM_FALSE、REVIEW_REQUIRED、REVIEW_PURPOSE、NO_ROLE、STALE、REVOKED、STATE_UNAVAILABLE、CLOCK_UNKNOWN、RESOURCE_LIMIT、BEHAVIOR_LIMIT、TASK_BUSY、OPERATION_CONFLICT，不以任意大写字符串扩展Reason码表。

POLICY.gateway_kid/executor_kid为本轮新增的唯一服务签署钥映射；各消息kid按共同合同核对，换服务钥推进POLICY，不任选同subject其他钥。

## 7. 来源映射与本轮新增冻结项

| 本文规则 | 既有明确依据 | 本轮新增/细化取值 |
|---|---|---|
| 三场景分别有独立schema/来源/角色/资源，模拟工具 | [场景设计§1–§3](../docs/11_工业流水线与医疗演示场景.md) | Profile由候选名正式冻结；线版本统一2.6，scenario唯一对应 |
| 完整Action/依据绑定、十消息、一次接受、EXEC-0 | [核心§3–§6](../../docs/证决界_动作授权与接受安全核心协议_v2.6.md) | 不增加核心消息，支撑Record外壳/专用kind/精确payload |
| 工业意图不含route，医疗不含模板/记录，受控阶段 | 场景设计§2.1、§3.1 | 工业cycle1/2、INITIAL/REINSPECT；医疗单组SUBMIT；C控制推进；失败STOPPED |
| 工业正常/缺陷/不确定映射及缺陷RELEASE硬拒绝 | 场景设计§2.2（固定判定器为建议） | 正式采用三映射；固定package四组合常量；history DISABLED |
| 医疗必需领域复核与独立执行授权，合成模板 | 场景设计§3.1–§3.3 | DEMO_A/B→DEMO-ORDER-A/B固定映射；必需恰一CLINICAL_REVIEW；history DISABLED |
| U/V必须不同登记主体、读权限先于取数据 | 场景设计§2.2、§3.2–§3.3；核心§5 | U/V不能是G/X；H可与U同主体；READER显式资格与精确AUDITOR裁剪 |
| 来源签名/版本与对象关联，摘要不能替代认证 | 场景设计§2.1、§3.1；核心§3.3；[衔接§5.2](../docs/07_v2.6_协议瘦身与后端衔接.md) | SourceAttestation固定签名域/字段；source/publisher身份；300秒采样TTL、Task900秒 |
| 独立重建依赖、新增行覆盖、真实持久回执和派发重查 | [符合性补全§2–§4](../docs/14_协议符合性补全合同.md) | UNIT/ENCOUNTER namespace及精确行；COMMIT scene前后见证避免自身更新误失效 |
| 工业容量及医疗终局结算、未知占用与不重派 | 场景设计§2.3、§3.3；符合性补全§4 | 每目的地8累计槽、每动作1、BEHAVIOR32；spent不自动返还；无reset |
| 不跨Profile复用，路径/工具固定 | 场景设计§1、§4、SC01/SC02 | 三类路径白名单、工业固定三个目的工位、医疗固定合成账目的地 |

“本轮新增”不是原文已经实现的事实；保守常量也不是经过验证的工业/医疗安全阈值。没有真实模型、临床规则、工业安全认证、临床有效性或性能改进主张。原IND01–08/MED01–08/SC01–04及通用依赖/回执/派发用例仍为NOT_RUN；应额外覆盖300秒边界、第二cycle终止、医疗换组拒绝、8槽竞争、32次累计、源签名错kind、缺READER、接受后scene自身变动与来源变动的不同判定。
