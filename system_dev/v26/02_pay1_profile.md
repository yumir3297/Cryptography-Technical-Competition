# PAY-1 v2.6 固定场景协议附录

日期：2026-10-07。状态：协议层规范补全，未据此宣称软件实现、互操作验收或安全证明完成。本附录仅定义 `ZJJ-AAP / 2.6 / PAY-1` 的固定付款场景；不定义软件 API、数据库、界面或部署任务。

依据：[核心 v2.6](../../docs/证决界_动作授权与接受安全核心协议_v2.6.md) §3–§6、[后端衔接](../docs/07_v2.6_协议瘦身与后端衔接.md) §4–§5、[符合性补全合同](../docs/14_协议符合性补全合同.md) §2–§4、[PAY-1 v2.5](../../docs/证决界_PAY-1_核心密码协议规范_v2.5.md) §5–§9及附录A，以及[已确认Q01/Q02](../docs/06_待确认与规范澄清.md)。通用 Envelope、十种消息、Action/Ctx、编码与记录公式由同目录通用合同规定。本附录对 PAY-1 载荷和场景语义具有唯一解释；旧 v2.5 消息不得自动作为 v2.6 核心消息接纳。

2026-10-07 R2终局修订：工具采用[不可变事实与当前再认证合同](04_tool_final_recovery.md)。同一事实可以有不同认证RecordRef，仍只结算一次；只有已认证、正确绑定的不可变事实矛盾才HALTED。旧钥/过期证明不直接首次结算；工具从连续原账以当前钥重新认证，恢复不执行。以下场景终局规则按该合同解释，其余固定算法/角色/资源/阶段不变。

## 1. 固定范围与动作

`Scope={domain:Id,tenant:Id,scenario:"payment"}`，完整对象相等才匹配。`N` 为规范十进制字符串，值为0..9223372036854775807；`Positive` 为其中非零值。时间为 Unix 秒，算术中间量使用精确整数，不得把 JSON boolean/number、浮点或截断溢出当成 N。Id、B16、B32、Hash、Enc和集合排序沿用通用合同。

Action 的顶层只有 `scope,operation_id,principal,holder,holder_kid,executor,tool,tool_version,destination,payload`。`operation_id:B16`；`tool="pay-sim"`、`tool_version="1"`；`executor/destination` 精确等于当前策略登记值。`Action.payload` 的完整结构为：

```text
{order_id:Id,stage:Id,payer:Id,payee:Id,amount_minor:Positive,
 currency:"CNY",purpose:"order-settlement"}
```

单位为分，金额必须等于当前订单阶段全额。固定范围为一任务一订单阶段、一收款人、一笔全额付款模拟；不允许部分付款、拆分、批量、多级委托、动态币种、汇率、自报回调、重定向、文件或额外执行参数。旧 `data_refs` 和旧 Action 顶层 `task_id` 在 v2.6 为未知字段。task_id 由 Basis 唯一指定的任务记录解析，不存在第二个可选任务来源。destination 是受控工具目的端 Id，payee 是业务收款账户 Id，不得互换。

稳定业务意图的规范键为：

```text
Enc([scope.domain,scope.tenant,"payment",payload.payer,
     payload.order_id,payload.stage])
```

使用完整规范字符串，不能只用订单号或其非规范拼接；payee、amount和候选 AH 不进入意图键。W 受控分配唯一 operation_id，保存初次登记的稳定 task_id、principal、意图及登记来源版本。跨版本共享该意图去重事实；不得将 v2.5 登记字节按 v2.6 重新解释。接受前修改候选仍用原 operation_id，生成新 Basis及全部下游批准；接受后冻结原 Action，所有终态保留意图、许可消费和接受墓碑。

## 2. 受控记录及认证来源

所有记录的精确外壳为 `{version:"2.6",profile:"PAY-1",kind:Kind,scope:Scope,value:TypedValue}`，无未知字段。摘要为通用 `RecordRef(profile,kind,scope,value)`；读取时同时核对外壳版本、profile、scope和指定 kind。PAY-1 使用核心记录 `POLICY/BASIS/ASSESSMENT/COMMIT`，以及配套记录 `PAY_TASK/PAY_EVIDENCE/PAY_HISTORY`；后者不是新增核心签名消息。摘要相等不能替代受控发布认证。

每个控制记录须保留 C 的认证发布见证：发布所用当前根代、批准的精确记录摘要、scope、被授权发布主体、发布 W 序号和相应不可变管理授权证据。W 仅将认证发布且成功激活的记录作为当前来源。客户端提供相同字节不授予发布权。历史审计见证不作为允许绕过当前检查的证明。

### 2.1 TaskRecord：kind=PAY_TASK

value 精确为：

```text
{task_id:B16,task_revision:Positive,principal:Id,holder:Id,holder_kid:Hash,
 order_id:Id,stage:Id,payer:Id,allowed_payees:set(Id),
 max_amount_minor:Positive,executor:Id,destination:Id,policy_ref:Hash,
 iat:N,exp:N}
```

C 明确委托；allowed_payees非空，无通配符；task_revision等于当前 TASK 行 revision，holder/kid须有当前登记资格。Task.policy_ref解析 POLICY，不接受旧Config Ref。Task 与 Action 的scope、principal、holder/kid、order/stage/payer、executor/destination逐项相等；payee在allowed_payees中，`0<amount_minor<=max_amount_minor`。Task.policy_ref等于Basis及Ctx的policy_ref。任务id、principal、意图必须等于操作稳定登记值；C可在接受前更新holder/kid或授权范围，但新revision、新任务记录、新Basis和下游重签均不可省略，不创建子任务或清零主体累计次数。

### 2.2 EvidenceRecord：kind=PAY_EVIDENCE

value 精确为：

```text
{source_version:"2.5",source_profile:"PAY-1",source_type:"Evidence",
 source_ref:Hash,source_envelope:EnvelopeV25Evidence}
```

这是本轮唯一允许的来源 Envelope 白名单；其 protected 为 `ZJJ-AAP/2.5/PAY-1/Ed25519/Evidence`，body及sig按v2.5严格解析，不接受其他旧类型或未来版本。完整原规范 Envelope 字节须保留；`Enc(source_envelope)`必须与保存的原字节完全相同，source_ref使用原v2.5 Envelope Ref公式重算，不使用RecordRef代替。source_envelope.body.payload精确为：

```text
{order_id:Id,stage:Id,order_revision:Positive,payer:Id,payee:Id,
 amount_minor:Positive,currency:"CNY",accepted_goods:Bool,unsettled:Bool,
 beneficiary_active:Bool,observed_at:N}
```

原 Envelope.scope等于外壳scope；issuer等于POLICY.source；aud包括G/X/U/V所需的实际消费主体且只含策略readers中获准读者；来源签名、kid和原类型域必须成立。order_revision与amount_minor采用已有v2.5机器合同的Positive约束，不因旧正文表格简记N而放宽来源白名单。认证发布时按原v2.5规则核验原KEY/SOURCE ROLE资格及原动态依赖，保留该次认证快照见证；不得删除原签名后只发布字段拷贝。

迁移后当前资格另从本profile的KEY_GRANT/ROLE_GRANT受控记录独立构造：来源公钥与原签名kid、登记subject逐项相等，当前SOURCE范围覆盖动作。原Envelope中的v2.5资格Ref是保留的来源认证边，不直接与v2.6 RecordRef混合成Permit.deps；它们必须按原版本认证见证核验，不能按“哪个对象库找到就用哪个类型”解析。此桥接规则只适用于上述Evidence白名单，不引入任意旧资格自动转换。

ORDER 当前ref为本PAY_EVIDENCE的RecordRef，其revision等于原order_revision。Evidence的order/stage/payer/payee/amount/currency须精确匹配Action，`observed_at<=body.iat`，三项Bool均为true。任一已知false为F/CLAIM_FALSE；来源、资格或权威暂不可确认为U；不转成LOW_EVIDENCE复核。接受时仍核对原Evidence的时间和适用撤销；原Evidence的寿命限制仍有效。

### 2.3 HistoryRecord：kind=PAY_HISTORY

value 精确为：

```text
{partition:Id,publication_revision:Positive,feature_schema:"ratio-int-v1",
 cases:[Case],iat:N,exp:N}
Case={case_id:Id,intent:Id,revision:N,scope:Scope,partition:Id,
 payer:Id,stage:Id,currency:"CNY",ratio:N,action_class:"PAY"|"HOLD",
 event_at:N,known_at:N,label:"CONFIRMED_GOOD"}
```

cases为集合数组，按Enc条目排序，0..128条；ratio值0..10000。每份快照case_id和intent各自唯一，任一重复整份拒绝，不静默去重；同一intent修订仅保留一个代表，其revision严格增大。历史intent是历史业务意图登记Id，不是当前operation_id。案例scope/partition可不同，算法筛选决定可比性；案例必须由C核验其认证来源、标签和双时间后发布，未知字段、非法枚举或未来格式不得略过。

历史ratio的生成必须为 `floor(10000*历史实际金额/当时批准任务.max_amount_minor)`。C的不可变发布审计中逐案例保存case_id、intent、revision、历史实际金额、原批准任务的精确历史引用及分母、事件与首次可知时间、独立CONFIRMED_GOOD确认来源。原历史任务/确认材料按其记录版本和历史认证见证核验，不强求今天仍可执行；它们是出处边，不递归加入当前付款资格或exp继承。缺少该发布认证见证的快照不得作为可信输入。单有付款成功记录不自动产生CONFIRMED_GOOD。

EXPERIENCE行由scope与POLICY.partition定位，ref为本记录摘要，revision等于publication_revision。发布、修订或内容回退均推进分区revision；回到旧cases也须新发布记录，不重激活旧纪元。未发布历史仅是工作流材料；已发布集合包括未选中和可能新增案例，不能只对五个被选案例作当前性绑定。

## 3. PolicyDescriptor的全部场景规则

POLICY.value完整字段如下；不存在可选或泛型 `rules:object`：

```text
{profile:"PAY-1",schema_version:"pay1-payload-v1",
 verifier_version:"pay1-verifier-v1",policy_revision:Positive,
 gateway:Id,gateway_kid:Hash,executor:Id,executor_kid:Hash,source:Id,readers:set(Id),
 tool:"pay-sim",tool_version:"1",destination:Id,currency:"CNY",
 method:"order-match-v1",risk_method:"history-int-v2",partition:Id,
 count_cap:Positive,iat:N,exp:N}
```

policy_revision等于当前POLICY行revision；readers非空且含gateway、executor、source及该策略实际批准的H/U/V消费主体。映射加载的固定验证器必须同时对应schema_version和verifier_version。version/profile或具体策略摘要不同不匹配；只同名算法不足以通过。

以下是这两个固定版本的完整规则展开，不能作为可变开关覆盖：

| 规则域 | 固定规则 |
|---|---|
| task | §2.1全部相等、正金额、收款集合及单阶段限制；Task Current=T；稳定登记不变 |
| claims | §2.2精确订单匹配及三项true；ORDER当前认证证据；任何已知false硬拒绝 |
| role | §5全部当前身份、用途、scope、payer、额度、tool/destination集合检查；空集合拒绝；不合并角色额度 |
| assessment | §4精确整数算法，距离1000、最多5、最小3、FLAG比率4/5；无客户端阈值或自报cutoff |
| review | CLEAR空集合，FLAG恰一ANOMALY，INSUFFICIENT恰一LOW_EVIDENCE，UNKNOWN暂缓；V/U主体分离 |
| authorization | 恰一当前FINANCE主体签EXECUTE/APPROVE，绑定全部必要Review及同一Ctx/Basis |
| resource | CNY、从Action导出全额预占、同事务容量守卫、终局幂等；余额不固化在Permit |
| behavior | 累计accepted_count只增不减，count_cap等于策略值、主体跨任务共享、每任务一在途 |
| dependency | §6完整七namespace及所有隐式资格/覆盖版本，严格等集，不接受客户端删项 |
| execution | §7 EXEC-0、唯一pending→started、领取前重查、未知不重派、终局绑定与停止规则 |
| time | §8全部上限、承重继承、权威区间判定、无宽限、dispatch_before=Permit.exp |

policy允许C改变的只有明确列出的主体/读者、登记工具目的端、经验partition、count_cap和策略有效期/revision；改变任何字段均须新记录及新激活revision。改变固定载荷、算法阈值、角色义务、派发模式或时间常量须新明确版本合同，不能仍称以上schema/verifier版本。

## 4. history-int-v2：完整重算与分流

输入为已认证Action、当前PAY_TASK、当前POLICY、当前PAY_HISTORY及可信准备时间。X/W独立读取并按以下顺序重算，不采用G签名作为计算正确证明。

1. 严格验证整份输入结构、认证发布、scope及当前激活关系；先执行Task与订单硬条件。Task.max>0且金额不超上限。案例数量、case_id/intent唯一和单版本规则先于筛选检查；即使某重复项后来会被筛掉也拒绝整份快照。
2. 受控准备流程从W可信时间选定本批次Basis.iat，`cutoff=Basis.iat=Assessment.iat`。cutoff不可由H提交或使用任意更早时间避开已知历史；重准备读取新的可信时间、当前partition与快照，不能只修改原Basis的cutoff。
3. 精确算 `x=floor(10000*Action.payload.amount_minor/Task.max_amount_minor)`。合法x范围0..10000；中间乘积使用任意精度或检查溢出，不能按N上界截断。候选action_class恒PAY，feature不接受客户端自报。
4. 在全部cases中筛出同时满足：case.scope等于Action.scope；partition等于POLICY.partition；payer、stage、currency等于Action.payload；label为CONFIRMED_GOOD；event_at与known_at均不晚于cutoff；`abs(case.ratio-x)<=1000`。订单号不参与比较，绝对金额不替代ratio；不追加未认证新特征。
5. 对筛得案例按`(abs(ratio-x),case_id)`升序排序，case_id用ASCII字节字典序作为唯一tie-break，取前min(5,数量)个。selected_cases为这个检索顺序的case_id序列，不能重新作为集合排序；support=n为个数，different=d为其中action_class不等于PAY的个数。
6. 可信输入n<3得INSUFFICIENT；n>=3且`5*d>=4*n`得FLAG；其余得CLEAR。边界用整数比较，无概率分数或浮点宽限。n=0/1/2均不能当CLEAR；n=5,d=4恰为FLAG。
7. 必要输入/发布认证/权威/可信时间暂无法确认为U，语义结果UNKNOWN；输入类型错误、重复案例、已撤销/明确陈旧或宣称输出与重算不相等为F，不能伪装UNKNOWN。任何F优先拒绝；无F但有U暂缓，无可签发Basis。

ASSESSMENT.value精确为：

```text
{action_hash:Hash,policy_ref:Hash,task_ref:Hash,evidence_refs:set(Hash),
 snapshot_ref:Hash,cutoff:N,feature:N,selected_cases:[Id],support:N,
 different:N,result:"CLEAR"|"FLAG"|"INSUFFICIENT"|"UNKNOWN",
 method:"history-int-v2",iat:N,exp:N}
```

evidence_refs恰一PAY_EVIDENCE；snapshot_ref指定PAY_HISTORY；其余ref指定对应kind。全部输出及绑定字段逐项重算比较。UNKNOWN只作为完整可信输入及输出都存在、但当前必要状态不可确认时的诊断记录：仍以第6步计算feature/序列/n/d，result置UNKNOWN；若输入或可信iat不可得，不造缺字段Assessment，保留工作流暂缓事实。UNKNOWN Assessment不进入可签发BASIS。非法/伪造输出为F。

BASIS.value为通用精确结构：`scope,operation_id,action,action_hash,policy_ref,task_ref,evidence_refs,assessment_ref,required_reviews,deps,iat,exp`。action是完整Action；scope/operation_id/AH精确一致。Basis不含Review/Authorization/Permit；assessment_ref不可空；其Task/Evidence等与Assessment相同。用途总映射如下：

| 重算结果 | required_reviews | 独立执行授权 |
|---|---|---|
| CLEAR | 空集合；任何多余Review为F | 恰一FINANCE主体的EXECUTE/APPROVE |
| FLAG | 恰一ANOMALY用途Review | 同上，U与V不同登记subject |
| INSUFFICIENT | 恰一LOW_EVIDENCE用途Review | 同上，U与V不同登记subject |
| UNKNOWN | 不产生可签发Basis，不计算可满足义务 | DEFER；人工APPROVE不能覆盖U |

ANOMALY和LOW_EVIDENCE用途均使用当前ANOMALY角色V；不得互换用途，不增加DOMAIN用途。Review必须APPROVE且reason含至少一个非Unicode White_Space标量、最多1024 Unicode标量；reason只展示不执行规则。LOW_EVIDENCE要求V审阅当前Task、Evidence、收款人、金额等精确依据，其判断质量不由签名保证。所有批准绑定同一Ctx/basis_ref；Authorization.review_refs精确等于必要Review Ref集合。DENY为F，不得删除已绑定DENY引用沿用旧候选；重新考虑须新依据和全部下游签名。

这些沿用示例阈值，未证明业务检出率或误报率。固定规则与completion_lab中的研究场景无算法继承关系；不得以lab-mean-v1替换本算法。

## 5. 资格范围及主体分离

当前KEY_GRANT/ROLE_GRANT的认证发布、根代、epoch、永久撤销和有效期依通用控制合同。PAY角色约束精确为 `{payer_set:set(Id),max_amount_minor:Positive}`；RoleGrant另外精确约束tool_set、destination_set、scope_set。指定角色的一份当前资格必须同时满足：subject等于签名issuer的登记subject；完整scope属于scope_set；payer属于payer_set；amount<=max_amount_minor；tool与destination分别属于允许集合。集合非空且无通配符；多角色或多钥不得拼接放大额度。

| 主体/行为 | 当前角色 | 当前Key用途 |
|---|---|---|
| H签IssueRequest/ChallengeRequest/CommitProof/StatusQuery | HOLDER | 对应消息类型 |
| G签Permit或Result(ISSUED) | ISSUER且subject=POLICY.gateway | 对应消息类型 |
| E签来源Evidence | SOURCE且subject=POLICY.source | SOURCE（原2.5认证还须EVIDENCE） |
| V签ANOMALY或LOW_EVIDENCE Review | ANOMALY | Review |
| U签EXECUTE Authorization | FINANCE | Authorization |
| X签Challenge/Acceptance/执行侧Result | EXECUTOR且subject=POLICY.executor | 对应消息类型 |

H必须等于当前Task.holder并匹配holder_kid，Task.principal为稳定委托主体，不把principal与holder混为同一字段。H的客户端身份不替代FINANCE；长期RoleGrant不替代单动作Authorization。任一必需Review存在时U.subject!=V.subject，以登记主体比较；同一人两把kid不满足分离。未要求CLEAR虚构V，也未增设未由原合同要求的H/U主体分离。

签发/接受时来源、V/U/G/H资格和范围全部当前核验；X会话资格单独核验，不把未来挑战加入签发前依赖。恢复STATUS查询按当前Task的HOLDER恢复授权和操作归属检查，不要求历史已冻结Action继续满足执行额度；仅查询、不预占、不派发。C更新恢复holder/kid不能改写接受时原主体。

## 6. 必要依赖、认证图和覆盖revision

依赖精确为 `{namespace,key,revision,ref}`。Q01/Q02原定业务键不改变：

| namespace | 精确key | ref和隐式当前行 |
|---|---|---|
| POLICY | `[domain,tenant,"payment"]` | 当前POLICY RecordRef及policy_revision |
| TASK | `[domain,tenant,"payment",task_id]` | 当前PAY_TASK RecordRef及task_revision |
| ORDER | `[domain,tenant,"payment",order_id,stage]` | 当前PAY_EVIDENCE RecordRef及order_revision；覆盖整个阶段 |
| EXPERIENCE | `[domain,tenant,"payment",partition]` | 当前PAY_HISTORY RecordRef及publication_revision |
| KEY | `[kid]` | 当前KEY_GRANT RecordRef；读取后仍检查完整scope与用途 |
| ROLE | `[domain,tenant,"payment",subject,role]` | 当前ROLE_GRANT RecordRef与epoch |
| BEHAVIOR | `[domain,tenant,"payment",principal]` | 下述行摘要与当前revision |

`BEHAVIOR.row={accepted_count:N,count_cap:Positive,inflight:set(B16)}`，revision只在外层；scope/principal只由key承载。`ref=B64url(SHA256(Enc(["ZJJ-STATE-v1","BEHAVIOR",key,revision,row])))`。一次同事务改多个字段只加一次revision，每次count/cap/inflight改变必须推进revision。

基础隐式集合至少包括POLICY、TASK、ORDER、EXPERIENCE、BEHAVIOR，E的KEY/SOURCE ROLE、G的KEY/ISSUER ROLE、Task.holder_kid的KEY/HOLDER ROLE及已在承重图实际使用的其他资格。控制C使用预置根认证，不递归创建根自己的KEY/ROLE依赖。所有承重上游明确声明的合法传递deps合并进基础集合。`Basis.deps=Normalize(基础隐式集合∪基础承重图声明集合)`；不能仅抄写Record中已有deps。

Review.deps在Basis基础上增加本V的KEY/ANOMALY及其当前资格依赖；Authorization.deps增加本U的KEY/FINANCE及全部必要Review闭包。Permit.deps为上述基础集合、全部必要Review/Authorization声明与隐式资格依赖，以及当前G/H KEY/ROLE和当前X KEY/EXECUTOR ROLE的规范并集。X由POLICY.executor及其当前受控响应签名钥确定，不由客户端选取；这是签发时已有的执行方资格，不是未来Challenge对象。Permit不是以Basis.deps相等代替完整集合。X/W从当前动作、操作登记、策略和各认证对象独立重建集合；不得从客户端Permit.deps反向决定必查哪些行。

Normalize按(namespace,完整key)合并，同键不同revision或ref为DEP_CONFLICT；集合按Enc排序，无重复、无缺项或额外不承重项。随后每项比对scope、active、revision、ref，核对适用对象/记录撤销及激活状态。主体钥和角色的根认证避免递归自授权；登记挑战等历史出处不参与当前exp或承重闭包。RecordRef与Envelope Ref始终按字段预期kind/type分型。全部跨Record/Envelope图仍受深度16、依赖256、对象64KiB、Bundle 1MiB/128对象限制，循环/错kind/超限为F，合法引用暂不可读为U。

范围/空集事实同样必须受到W冲突保护：

- ORDER revision覆盖金额、收款人、验收、未结算、收款资格以及新增/删除/撤回的承重阶段记录；新插入一条记录也推进整个阶段版本。
- EXPERIENCE revision覆盖整个发布partition，包括未选中案例及截至cutoff的候选全集；不能只绑定selected_cases。
- TaskFlight为空、没有第二笔同intent接受、Permit/nonce未消费、预算余额及Behavior.inflight等读取须与接受写入同一事务顺序受保护，不能只用已有对象摘要见证空集。
- 预计算须保存完整版本及范围读取见证，在接受事务再验；冲突重新准备，不修补已签Basis，不删失效依赖。

预算不进入Permit的签发时余额依赖；接受事务直接重读资源行。对象内容相同而revision增加仍使旧Basis/批准/Permit失效。授权恢复、策略回退和角色重新激活都不使旧纪元复活。

## 7. 资源、在途、派发与终局

资源key=`[domain,tenant,"payment",payer,"CNY"]`，通用ResourceWitness.unit固定`CNY_MINOR`，预占m从Action.amount_minor唯一导出，拒绝自报reserve数。资源状态满足capacity/reserved/spent非负且`reserved+spent<=capacity`。接受同事务要求`reserved+spent+m<=capacity`；实现算术不得溢出，也可按可用余额逐步减法判定。资源不可确认为U，确定不足为F/RESOURCE_LIMIT；容量管理不得降低到已有reserved+spent以下。

主体Behavior按principal跨任务共享；接受前要求count_cap=POLICY.count_cap且accepted_count+1<=count_cap。count达到上限为F/BEHAVIOR_LIMIT，TaskFlight非空为U/TASK_BUSY。接受同时将reserved增加m、accepted_count增加1、operation_id加入inflight、TaskFlight指向本操作，记录各正确revision；累计count终局不减、新任务不重置。CommitRecord必须保存实际checked_deps、资源预占归属/数额、行为前后、任务在途、冻结工具请求和dispatch_before；COMMIT不反向引用Acceptance。

领取仅针对已持久接受且outbox pending的冻结Action，所有检查与pending→started唯一CAS在同一W顺序中完成：

1. 可信时间区间满足`t_hi<dispatch_before`；明确到期为F，跨界/时钟未知为U。
2. POLICY、TASK、ORDER、EXPERIENCE及E/V/U/G/H/X必要KEY/ROLE仍与承重见证相符，适用撤销未发生；固定工具映射、当前X/出口资格与健康可确认。
3. 本操作reservation归属、资源key与m正确且未结算；资源容量守卫仍成立；TaskFlight指向本操作；Behavior.inflight仍包含它、count_cap正确、累计值合法。
4. BEHAVIOR不用Permit的接受前revision作比较，以COMMIT接受后见证确认本操作已产生一次count/inflight改变，并核验当前自身占用。当前revision允许因其他合法操作更高；须验证中间每次变化符合累计单调及占用归属，不能只看revision>=旧值。任何丢失自身reservation/flight、count回退或账不一致均不得领取；其他承重行没有这种豁免。
5. 成功才保存唯一dispatch_attempt:B16、冻结工具请求并将pending改started；持久提交后才允许唯一一次工具调用。started不表示已发送或已成功。

冻结工具请求只从Action的登记映射生成，绑定scope、operation_id、AH、executor/tool/tool_version/destination和完整PAY载荷，禁止调用时外加未签字段。领取后至实际网络发送之间的撤销不在本合同额外实时拦截保证内；派发资格保证点为W领取序列点。

| 情形 | 状态与结算 |
|---|---|
| pending且期限/资格确定失效；CAS确认尚未领取 | 同事务FAILED_CONFIRMED，只释放本操作reserved及在途，不减count或删接受/去重墓碑 |
| pending且必要状态/时钟未知 | 保持pending，暂缓，不调用、不释放 |
| started后崩溃、超时、响应丢失，效果不能确认 | EFFECT_UNKNOWN，保留预占/在途，EXEC-0禁止自动重派 |
| 受信TOOL_FINAL.outcome=SUCCEEDED，确认为本冻结请求完成全额效果 | SUCCEEDED，reserved减m、spent增m，一次释放本操作inflight/TaskFlight |
| 受信TOOL_FINAL.outcome=FAILED_CONFIRMED，确认无效果且不会迟到生效 | FAILED_CONFIRMED，reserved减m，一次释放本操作在途；不减count |
| 重复相同终局 | 原终局幂等返回，无第二次结算 |
| 通过当前认证与原派发绑定的矛盾终局，或内部冻结reservation/Flight归属及资源账矛盾 | HALTED，停止派发/结算，不猜测返还或重发；外部错绑定输入按R2拒绝/暂缓，不凭其触发HALTED |

工具终局的可信性由固定pay-sim执行边界负责，使用通用TOOL_FINAL受控记录，必须精确绑定scope、operation_id、AH、dispatch_attempt和冻结请求；错误绑定响应不能用于结算。“工具目前查不到记录”不能作为started后FAILED_CONFIRMED的无效果终局证明。pending取消与started领取竞争按W顺序只能有一个获胜；started不可回pending。状态查询不触发工具、不释放资源，不产生新接受。EXEC-1不属于本固定合同；接受唯一、派发调用至多一次、现实效果恰好一次不得混称。

## 8. 时限与到期继承

全部有效期为`[iat,exp)`且iat<exp；可信W时间区间不确定度<=2秒。`iat<=t_lo && t_hi<exp`为T；`t_lo>=exp`为F；跨边界、尚未确定到生效时点或时间源不可用为U；无过期宽限。W时序纪元与持久时间下界不下降。

| 对象 | 最大exp-iat（秒） |
|---|---:|
| POLICY、KEY_GRANT、ROLE_GRANT、PAY_HISTORY | 31536000 |
| PAY_TASK | 86400 |
| 原认证Evidence、ASSESSMENT、BASIS、Review、Authorization、Acceptance | 900 |
| Permit、IssueRequest | 120 |
| Challenge、ChallengeRequest、CommitProof、StatusQuery、Result | 30 |

PAY_EVIDENCE有效区间直接继承source_envelope.body.iat/exp，无第二个延长期限。ASSESSMENT/BASIS的iat相同，cutoff等于该iat；exp不晚于Policy、Task、Evidence、History和基础承重资格的exp。Review、Authorization、Permit的exp不晚于其所有必要承重上游，且仍各满足本表寿命。各级新增签名者自己的KEY/ROLE有效期继续收窄对应对象资格，不因表中最大值延长。

Permit.dispatch_before=Permit.exp。COMMIT Challenge.exp等于`min(Challenge.iat+30,Permit.exp,当前Task.exp,当前H与X所用KEY/ROLE的exp)`；无正区间不生成。CommitProof.iat>=Challenge.iat，exp<=Challenge.exp且exp<=Permit.exp并<=iat+30，仍不得晚于当前H签名资格exp。STATUS Challenge.exp等于`min(Challenge.iat+30,当前H与X所用查询/响应KEY/ROLE的exp)`，不继承旧Permit的执行期限。请求/挑战/响应的会话关联和历史接受出处不用执行资格链的exp继承；新鲜Result可引用过期Acceptance，但必须验证精确历史签名、COMMIT与当时资格见证，查询者和当前响应者须当前认证。COMMIT保存的是持久历史事实，不人为设置一个到期值删除去重或预占。

POLICY.gateway_kid/executor_kid精确定位G/X签署钥，核对各自登记subject和当前资格；换服务钥须新POLICY/revision，不能任选同subject其他钥。此字段为本轮消除依赖构造歧义的补充决定。

## 9. 本轮规范确定与证据边界

本轮继续使用已确认的Q01行及Q02键，原PAY-1固定金额/工具/算法阈值、角色分离、最大寿命和EXEC-0参数不改。以下以前是草图或隐含规则，现明确作为协议层决定：

| 本轮确定 | 原因及依据 |
|---|---|
| 配套kind PAY_TASK/PAY_EVIDENCE/PAY_HISTORY与统一Record外壳 | 核心§3.3要求Record/Envelope隔离，07§5.2此前未冻结来源解析kind |
| POLICY全部扁平字段及schema/verifier固定字符串，policy_revision | 将07泛型rules草图展开为§3唯一规则，POLICY激活须有明确revision；不宣称旧实现已有这些值 |
| Basis嵌入完整action，Task仅由task_ref定位 | 核心Action没有task_id，十类消息也不直接传完整Action；确定唯一可解析动作来源，避免依摘要猜参数 |
| ASSESSMENT/BASIS最长900秒、iat/cutoff一致 | 延续v2.5 Decision/Risk寿命及07§4.3可信cutoff，分层后不让依据无限有效 |
| 原2.5/PAY-1/Evidence为唯一来源白名单并保留认证桥接见证 | 07要求来源签名及固定版本解析；新kind不等于新来源签名核心类型，禁止泛化旧对象接纳 |
| publication/task/policy revision用Positive；原Evidence依现有机器合同Positive；历史案例revision保持N | 当前激活首版本1及后续单调更新与来源机器格式一致，未登记版本0不成为当前激活记录；不改旧案例字段范围 |
| UNKNOWN诊断记录的输出来源与禁止签发 | 旧结果枚举允许UNKNOWN但未冻结无输入时记录形状；区分可算输出/未知当前性与不可得输入，禁止伪造完整依据 |
| 派发接受后Behavior允许合法其他操作推进但核验自身见证 | 符合性合同§4要求避免自我失效且不丢自身占用；不是删除BEHAVIOR依赖 |

本附录补全的是协议定义。严格Schema、软件实现、运行测试、互操作或形式化安全论证的完成状态须由各自独立证据报告；现有旧数据、研究场景或局部实验通过不自动构成PAY-1 v2.6符合性完成。签名真实性、当前授权、业务事实质量、历史分类效果、资源原子性与工具终局可信性分别依赖明确承担者，不互相替代。
