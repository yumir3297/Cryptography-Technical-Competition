# v2.6 核心协议精确合同

日期：2026-10-07。合同标识：`ZJJ-CORE-2.6-R2`。这是协议定义及结构合同，未交付服务、未完成双实现互操作或完整安全证明。与[核心正文](../../docs/证决界_动作授权与接受安全核心协议_v2.6.md)共同阅读；本文件将其设计字段展开。发生差异时，本文件及两个固定场景附录对本轮精确字段与规则优先，旧v2.5对象只按明确白名单解析。

本轮范围仅协议层：核心10消息、共同4类Record、三个固定Profile的承重对象和资格/状态语义。展示、数据库物理表、框架、部署及应用会话接口不在本合同中。引用的结构Schema只能判断结构，不能替代验签、引用解析、当前性或事务判定。

## 1. Profile、基础类型与编码

| Profile | scope.scenario | 核心运输前缀 | 场景合同 |
|---|---|---|---|
| PAY-1 | payment | `/zjj/2.6` | [PAY-1](02_pay1_profile.md) |
| IND-DEMO-1 | industrial | `/zjj/2.6/industrial` | [工业/医疗](03_industrial_medical_profiles.md) |
| MED-DEMO-1 | medical | `/zjj/2.6/medical` | 同上 |

全部使用`proto="ZJJ-AAP",version="2.6",alg="Ed25519"`。Profile为固定登记项，无在线算法协商、默认Profile或回退。domain/tenant也须匹配受信服务配置。正文中早期“本轮仅PAY-1”由本次三场景范围扩展替代；不表示新场景已经实现。

| 类型 | 唯一定义 |
|---|---|
| Id | ASCII `[a-z0-9][a-z0-9._:-]{0,63}`，大小写不转换 |
| N | 十进制字符串`0|[1-9][0-9]*`，0..9223372036854775807；Positive为1..该上界 |
| Time | N，Unix秒；iat/exp为半开区间且iat<exp |
| B16/B32/B64 | 精确16/32/64字节的无填充base64url；解码再编码完全相等；Hash=B32 |
| Text | 最多1024个Unicode标量，无孤立代理项，不归一化；只解释为文字 |
| Nonblank | Text且至少含一个非White_Space标量；集合为U+0009..000D、0020、0085、00A0、1680、2000..200A、2028、2029、202F、205F、3000 |
| Scope | 精确`{domain:Id,tenant:Id,scenario}`；scenario由Profile固定 |
| Set(T) | 至多256项，逐项Enc字节字典序严格递增，无重复；除另规定外集合可为空 |
| List(T) | 有顺序，至多256项；不得擅自排序；selected_cases按场景检索顺序 |

Id正则需匹配整个字符串，拒绝末尾换行。所有对象只允许规范列出的字段，全部必需；没有隐含默认。JSON number、null、重复键、非法UTF-8/BOM、非规范JSON转义/空白、未知字段或枚举拒绝。`version="2.6"`为协议常量字符串，不是N。Enc采用受限JCS/UTF-8；键名均为ASCII，布尔仅true/false。原始对象字节必须等于Enc(解析值)，不能在验签前修正值。

每Envelope/Record≤65536字节；Bundle≤1048576字节，`objects`≤128项；一次解析的去重对象图≤128个，含Record及嵌入的来源对象。引用深度≤16（根深度0），拒绝环；deps≤256项；JSON容器嵌套深度≤32。限制超出为F/LIMIT，不能伪装为对象暂不可读。主请求加128个objects仍受总图128限制。

```text
Enc(x) = UTF8(JCS(x))
ToSign(h,b) = Enc(["ZJJ-SIG-v1",h,b])
Ref(o) = B64url(SHA256(Enc(["ZJJ-OBJ-v1",o.protected,o.body])))
AH(profile,a) = B64url(SHA256(Enc(["ZJJ-ACTION-v1","2.6",profile,a])))
RecordRef(profile,kind,scope,value) = B64url(SHA256(
  Enc(["ZJJ-RECORD-v1","2.6",profile,kind,scope,value])))
KeyID(pk) = B64url(SHA256(Enc(["ZJJ-KEY-v1","Ed25519",B64url(pk)])))
StateRef(namespace,key,revision,row) = B64url(SHA256(
  Enc(["ZJJ-STATE-v1",namespace,key,revision,row])))
```

Ref不含sig；引用身份相同不代表收到的签名有效。每份Envelope都须验签，缓存只能复用完整原字节/公钥/验证器版本对应的密码事实。当前资格、撤销和资源不可缓存为授权结果。

固定纯Ed25519，拒绝ph/ctx、其他算法和ZIP215接受约定。公钥A及签名R必须规范解码、处于阶L主子群且非单位元，S满足0≤S<L，`L=2^252+27742317777372353535851937790883648493`，再验成熟库等式。公钥只能来自可信登记，kid=KeyID(pk)，不能从客户端随报公钥取信。跨实现须比较这一拒绝集合；只调用库verify不自动符合合同。

## 2. Envelope、Action、Ctx与Record

```text
Envelope = {protected:{proto,version,profile,alg,type,issuer:Id,kid:B32},
            body:{id:B16,scope:Scope,iat:Time,exp:Time,aud:Set(Id),
                  refs:Set(B32),deps:Set(Dep),payload:Payload(type)}, sig:B64}
Action = {scope,operation_id:B16,principal:Id,holder:Id,holder_kid:B32,
          executor:Id,tool:Id,tool_version:Id,destination:Id,payload:ProfilePayload}
Ctx = {scope,operation_id:B16,principal:Id,holder:Id,holder_kid:B32,
       executor:Id,action_hash:B32,policy_ref:B32,basis_ref:B32}
Record = {version:"2.6",profile,kind,scope,value:Value(profile,kind)}
Dep = {namespace,key:List(String),revision:Positive,ref:B32}
```

body.scope、ctx.scope、Action.scope、Record.scope及其来源scope精确一致；Action各重复字段与Ctx/任务/登记逐项相等。`tool_version`使用Id（例如"1"），不是自由说明。Action.payload只按该Profile唯一Schema解释。operation_id由W受控分配B16，稳定intent由场景定义，换随机ID不创建新意图；接受后全部动作字段冻结。

Record共同kind为POLICY、BASIS、ASSESSMENT、COMMIT。附录另外定义固定的任务、来源、历史和决策包Record，不属于核心新增签名消息。Record来源通过C/E认证发布与W持久证据确认，不能只凭摘要认证。受控通道的实现由开发选择，但不得将客户端自报Actor、roles或Root视为已认证。

### 2.1 BASIS精确值

`{scope,operation_id,action:Action,action_hash,policy_ref,task_ref,evidence_refs:Set(B32),assessment_ref,required_reviews:Set(ReviewPurpose),deps:Set(Dep),iat,exp}`。

scope重复时必须相等；action_hash=AH(profile,action)，operation_id=action.operation_id。**本轮增加完整action字段以闭合解析**：任何授权/许可的动作都唯一从其basis_ref取得，不靠未签的提交参数补全。required_reviews由固定算法重算，不能由准备者任选。Basis无下游Review/Authorization/Permit/Acceptance引用，ASSESSMENT也不回引Basis。snapshot_ref等通过Assessment解析。

POLICY/ASSESSMENT的精确值由固定Profile附录列出；POLICY版本名只是选择本合同固定规则，不能加载自定义表达式或代码。iat/exp必须存在且来源认证/当前激活成立。所有POLICY另外固定`gateway_kid:B32,executor_kid:B32`，分别唯一定位该策略下G/X当前业务签署钥；登记subject须匹配gateway/executor，实际Permit、Challenge、Acceptance及服务Result的kid须匹配对应当前/冻结策略映射。换服务钥必须新POLICY并推进激活revision，不能在完整依赖重建时任选同subject其他有效钥。历史已存回执继续用原映射/公钥见证验证；新STATUS响应使用当前服务映射。

### 2.2 COMMIT精确值

```text
{ctx,action,permit_ref,proof_ref,authorization_ref,review_refs,
 accept_seq:Positive,accepted_at:Time,trusted_time:{lo:Time,hi:Time},
 checked_deps:Set(Dep),reservation_plan:Set(ResourceWitness),
 reservation_ids:Set(B16),behavior_before:BehaviorWitness,
 behavior_after:BehaviorWitness,taskflight:FlightWitness,
 dispatch_before:Time,frozen_tool_request:Action,
 signing_public_key:B32,credential_witnesses:Set(CredentialWitness)}
BehaviorWitness = {key:[domain,tenant,scenario,principal],revision:Positive,
                   ref:B32,row:{accepted_count:N,count_cap:Positive,inflight:Set(B16)}}
FlightWitness = {key:[domain,tenant,scenario,task_id],operation_id:B16}
ResourceWitness = {reservation_id:B16,key:ProfileResourceKey,unit:ProfileResourceUnit,
                  amount:Positive,capacity_before:N,reserved_before:N,spent_before:N,
                  reserved_after:N,spent_after:N,revision_before:Positive,revision_after:Positive}
CredentialWitness = {subject:Id,kid:B32,public_key:B32,key_grant_ref:B32,
                     role:Role,role_grant_ref:B32,key_revision:Positive,
                     role_revision:Positive,verified_at_seq:Positive}
```

上述简写ref/ctx等均使用对应已定义Hash/集合类型。frozen_tool_request必须等于action：场景工具只接受这份规范冻结请求，由适配器作固定字段映射，无额外可改变效果的参数。reservation_ids恰等于plan中ID集合；每个资源key唯一，amount与场景计划一致；reserved_after=reserved_before+amount，spent_after=spent_before，revision_after=revision_before+1且容量足够。Behavior.after.count=before.count+1、inflight增加本op、revision加1；原行不含本op，count不超过cap。Flight.task_id由当前TaskRecord取得，不能用operation_id替代任务身份。

credential_witnesses归档所有承重签名/来源主体的当时公钥、资格引用及W验证顺序；引用对象和认证登记原记录必须保留可审查。signing_public_key属于X，KeyID等于冻结Acceptance.kid。COMMIT不含acceptance_ref、不回引Acceptance，也不含受其摘要影响的自身ref。回执签署前核对COMMIT/ctx/Action、原Core及原公钥，恢复读取对原Core/Ref再严格验签；当前密钥撤销不使已存历史签名失效。整体可信数据库被重写或历史密钥失陷不由摘要单独解决。

工业/医疗COMMIT额外必需`scene_before,scene_after`，PAY-1禁止这两字段。`SceneWitness={namespace:UNIT或ENCOUNTER,key:对应完整key,revision:Positive,ref:B32,row:ProfileSceneRow}`，row精确字段见场景附录。接受前READY→接受后ACCEPTED、写本operation_id且revision加1，其他字段相等。ref用StateRef重算。派发pending时须当前场景行精确等于scene_after的revision/ref/row，不能因“是自身变动”放过来源/事实的后续更改；唯一被豁免的是已在COMMIT冻结的这次接受变动。

COMMIT.trusted_time是接受守卫使用的同一可信区间，`lo<=hi,hi-lo<=2`，accepted_at=lo（本次逻辑接受tg）。所有当时承重对象满足iat<=lo且hi<exp；不得自报旧accepted_at。W仍以事务提交序号而非时间戳决定并发先后；事务期间保持隔离。

## 3. 十种payload、引用及寿命

下表列出全部payload字段；未标类型的ctx为Ctx，`*_ref`为B32，`review_refs`为Set(B32)，operation/session/attempt为B16，nonce为B32，holder为Id、holder_kid/action_hash为B32，dispatch_before为Time。可空字段只使用空字符串，其他字段不得为空或缺省。

| type | 精确payload | 最长寿命/秒 | 直接Envelope引用 |
|---|---|---:|---|
| Review | ctx,purpose:ReviewPurpose,verdict:APPROVE或DENY,reason:Nonblank | 900 | 空集合 |
| Authorization | ctx,review_refs,purpose:"EXECUTE",verdict:APPROVE或DENY | 900 | review_refs |
| IssueRequest | ctx,review_refs,authorization_ref | 120 | review_refs及authorization_ref |
| Permit | ctx,review_refs,authorization_ref,max_uses:"1",dispatch_before | 120 | 同上 |
| ChallengeRequest | purpose:COMMIT或STATUS,operation_id,permit_ref:B32或空,action_hash:B32或空,attempt_id | 30 | 非空permit_ref |
| Challenge | purpose:COMMIT或STATUS,operation_id,permit_ref:B32或空,action_hash:B32或空,holder,holder_kid,session_id,nonce,request_ref | 30 | request_ref及非空permit_ref |
| CommitProof | ctx,permit_ref,challenge_ref,session_id,nonce,attempt_id | 30 | permit_ref及challenge_ref |
| Acceptance | ctx,permit_ref,proof_ref,authorization_ref,review_refs,accept_seq:Positive,accepted_at:Time,commit_record_ref:B32,dispatch_before | 900 | permit_ref/proof_ref/authorization_ref/review_refs |
| Result | request_ref,attempt_id:B16或空,result:ResultCode,reasons:List(Reason),operation_id:B16或空,permit_ref:B32或空,acceptance_ref:B32或空,status:Status,status_seq:N,retry_after:Time或空 | 30 | request_ref及非空permit_ref/acceptance_ref |
| StatusQuery | operation_id,challenge_ref,session_id,nonce,attempt_id | 30 | challenge_ref |

ReviewPurpose的全集为ANOMALY/LOW_EVIDENCE/QUALITY_REVIEW/CLINICAL_REVIEW，按Profile分别限定；不能跨用途互换。`body.refs`恰等于上表直接引用规范集合，不含policy_ref/basis_ref/commit_record_ref/AH/kid或Dep.ref。不能扫描`_ref`后缀决定引用类型。授权对象必须持久存在，客户端内联只是缓存提示。

类型化解析固定：policy_ref→POLICY；basis_ref→BASIS；assessment_ref→ASSESSMENT；commit_record_ref→COMMIT；任务/来源/历史引用按Profile固定kind；authorization_ref→Authorization；review_refs→Review；permit_ref→Permit；proof_ref→CommitProof；acceptance_ref→Acceptance；challenge_ref→Challenge；Challenge.request_ref→ChallengeRequest；Result.request_ref→该路径请求type。同样的摘要不可在不同kind仓库中尝试解释。错kind/Profile/作用域为F；确认不存在为F/MISSING_OBJECT；合法引用暂不可取为U/MISSING_OBJECT。

### 3.1 身份、受众与声明依赖

| 消息 | issuer及当前用途/角色 | aud规则 | body.deps规则 |
|---|---|---|---|
| Review | V/Review，对应用途角色 | policy.readers的非空子集，含H/G/X及实际U | Basis.deps＋V KEY/ROLE |
| Authorization | U/Authorization，场景EXECUTE角色 | 恰{H,G,X} | Basis.deps＋全部Review.deps＋U KEY/ROLE |
| IssueRequest | H/IssueRequest/HOLDER | 恰{G} | H KEY/ROLE |
| Permit | G/Permit/ISSUER | 恰{H,X} | 第4节完整RequiredDeps |
| ChallengeRequest | 当前H/ChallengeRequest/HOLDER | 恰{X} | H KEY/ROLE |
| Challenge | X/Challenge/EXECUTOR | 恰{当前H} | H及X KEY/ROLE |
| CommitProof | H/CommitProof/HOLDER | 恰{X} | H KEY/ROLE |
| Acceptance | X/Acceptance/EXECUTOR | 恰{原H,G,U} | 接受时X KEY/ROLE，历史验证读归档见证 |
| Result | 路径G或X/Result，相应ISSUER或EXECUTOR | 恰{原请求issuer} | 响应签署时自身KEY/ROLE |
| StatusQuery | 当前H/StatusQuery/HOLDER | 恰{X} | 当前H KEY/ROLE |

角色名称及额度/工件/患者范围见附录。同一个Dep键只能一项；同键不同revision/ref为DEP_CONFLICT，重复相同项也拒绝而非静默去重。以上集合由验证者重建后精确比较。审查/授权aud必须允许实际批准者读取，读取授权本身不授予签名权。policy.readers不得含匿名/通配符。

时间以可信W区间[lo,hi]判定：hi-lo≤2秒；iat≤lo且hi<exp为T；lo≥exp为F/EXPIRED；跨界、生效前、时钟不可用为U/CLOCK_UNKNOWN。下游Basis/Assessment/Review/Authorization/IssueRequest/Permit的exp不晚于其所有承重任务/来源/策略/资格/批准对象exp。Permit.dispatch_before=Permit.exp。Proof.iat≥Challenge.iat、Proof.exp≤Challenge.exp且≤Permit.exp；Challenge不以历史Permit过期来使STATUS失败。Acceptance属于历史见证，不受Permit.exp上限继承；iat=accepted_at，exp≤iat+900，Core在接受事务中固定。签新回执/Result仍须当前签署资格及签署时效为T。

### 3.2 Result精确关联与状态

ResultCode={ISSUED,ACCEPTED,REJECT,DEFER,EXISTING,STATUS}；Status={NONE,PENDING,ACCEPTED,EFFECT_UNKNOWN,SUCCEEDED,FAILED_CONFIRMED,HALTED}。PENDING只表示已登记尚未接受的操作；ACCEPTED涵盖已接受且pending派发；started在无权威终局时显示EFFECT_UNKNOWN，不能暴露为成功。

| result | 路径 | 字段约束 |
|---|---|---|
| ISSUED | issue | permit_ref必填，acceptance_ref为空；operation_id为申请操作；status=NONE,status_seq="0"；reasons=[{check:"result",code:"OK"}] |
| ACCEPTED | commit | acceptance_ref必填，permit_ref为空；status=ACCEPTED；status_seq=原accept_seq；reasons同OK |
| EXISTING | commit | 原acceptance_ref必填；permit_ref为空；返回持久响应所对应状态序号；reason=EXISTING_ACCEPTANCE，无新接受 |
| STATUS | status | operation_id必填；已接受则原acceptance_ref必填，未接受为空；status/status_seq来自同次只读W快照；reason=OK |
| REJECT/DEFER | 四路径 | permit_ref/acceptance_ref为空；status=NONE,status_seq="0"；operation_id为已认证请求的操作；按原因码表返回非空reasons |

Result.attempt_id对IssueRequest为空，其余等于对应请求attempt_id。ChallengeRequest的request_ref绑定原请求，其Challenge也必须逐项匹配该请求；后续Proof/Query.attempt_id必须等于原ChallengeRequest.attempt_id。成功/REJECT的retry_after为空；DEFER为可信建议Time或空，不承诺届时可执行。重传旧响应不重签、更不改iat/status；客户端得到历史响应后若要更新状态必须新挑战/查询。

Result只是流程结果。新鲜Result可携带原Acceptance（即使原回执exp已到期），原回执只能历史验证。若接受已存在而原回执未签好，不得返回缺少可验Acceptance的ACCEPTED或伪造REJECT；只能保持响应待恢复/通信未知。读取仍需当前查询身份。

## 4. 依赖闭包、控制与当前性

| namespace | 精确key | ref及范围 |
|---|---|---|
| POLICY | [domain,tenant,scenario] | 当前POLICY Record |
| TASK | [domain,tenant,scenario,task_id:B16] | Profile任务Record |
| ORDER | [domain,tenant,"payment",order_id,stage] | PAY_EVIDENCE；覆盖该阶段全部承重付款事实 |
| EXPERIENCE | [domain,tenant,"payment",partition] | PAY_HISTORY；覆盖完整发布集合/空集 |
| UNIT | [domain,tenant,"industrial",line_id,unit_id] | StateRef的完整UNIT行；其unit_ref→IND_UNIT，覆盖检测、阶段和工件事实 |
| ENCOUNTER | [domain,tenant,"medical",synthetic_patient_id,encounter_id] | StateRef的完整ENCOUNTER行；其encounter_ref→MED_ENCOUNTER，覆盖记录集合、意图组/阶段/权限变化 |
| KEY | [kid:B32] | KEY_GRANT，读取后核对完整scope、主体及用途；全W域一个kid身份不可混用 |
| ROLE | [domain,tenant,scenario,subject,role] | ROLE_GRANT，固定角色及Profile范围 |
| BEHAVIOR | [domain,tenant,scenario,principal] | StateRef；row精确{accepted_count,count_cap,inflight} |

revision从1开始严格增加，恢复新对象必须更高revision，A→B→A不能复用旧依赖。Key与Role永久撤销墓碑不得删除。对对象另查 `(profile,scope,type,issuer,id)`或Record的ref撤销，不以deps存在替代。

Basis.deps由固定Profile重建策略/任务/来源/历史/主体行为与来源资格；Review/Authorization增加其实际签署者。Permit.RequiredDeps是独立从Action及全部承重对象推导的动态行集合，再并入这些对象声明deps、G/H/X的KEY/ROLE；所有行类型、键、scope、epoch与认证对象精确对应。不能先信Permit.deps再以它当读取清单。挑战会话不是签发前基础对象，单独验证。

新增承重行、空集合变非空、记录撤回、治理更新必须推进对应ORDER/EXPERIENCE/UNIT/ENCOUNTER覆盖revision；不能只保存原有行的Ref。资源余额在接受事务内重读，不写入签发时deps；其批准计划仍受Policy/Task/Action绑定。纯计算/密码验证可事务外预做，事务中须验证全部行和范围见证。

### 4.1 受控资格Record与发布义务

`KEY_GRANT.value={subject:Id,public_key:B32,kid:B32,epoch:Positive,purposes:Set(KeyPurpose),iat:Time,exp:Time,root_generation:Positive,enrollment_ref:B32}`。KeyPurpose是上述10消息type及SOURCE/CONTROL/READ；后两者仅受控发布/读取用途，不能充当核心消息授权。集合非空，每个用途须被C明确批准。scope固定，kid=KeyID(public_key)，最长31536000秒，公钥满足严格点检查。KEY当前revision首次等于epoch；撤销推进revision但不重写旧Grant。

`ROLE_GRANT.value={subject:Id,role:Role,epoch:Positive,iat:Time,exp:Time,tool_set:Set(Id),destination_set:Set(Id),scope_set:Set(Scope),constraints:ProfileRoleConstraints}`。Role是固定枚举（PAY：HOLDER/ISSUER/SOURCE/FINANCE/ANOMALY/EXECUTOR；另两Profile见附录），不是Id。最长31536000秒，范围非空、无通配；本Record.scope必须在scope_set中，全部scope.scenario与本Profile一致。所有角色都检查工具/目的及Profile约束，不能只比较role名字。ProfileRoleConstraints为附录中的精确结构，PAY为payer_set/max_amount_minor，其他为固定工件/患者范围。C根本身通过可信初始锚认证，不自授业务角色；U/V分离按subject身份，不按不同kid。

C在认证管理入口生成pending登记授权元组`{scope,subject,public_key,kid,purposes,key_not_before,key_not_after,root_generation}`及`enrollment_id:B16,nonce:B32`。在60秒内要求申请者严格验签的持有证明，签名输入为`Enc(["ZJJ-ENROLL-v1","2.6",tuple,enrollment_id,nonce,iat,exp])`；iat/exp为Time，0<exp-iat≤60，not_before≥创建时间、not_before<not_after、寿命≤31536000秒，证明不得晚于pending.exp。C核对原pending全部字段、当前根代、未消费nonce，在同W序提交登记、nonce消费及认证发布记录；此控制证明不是动作核心消息、不授予角色。重复同证明返回原登记，同nonce异证明拒绝。KEY_GRANT.enrollment_ref为`SHA256(Enc(["ZJJ-ENROLL-RECORD-v1","2.6",tuple,enrollment_id,nonce,iat,exp,signature]))`的B32，原证明和C认证证据持久保存。

控制/来源Publish须核对当前C/E身份、scope、精确kind/schema、版本、原始认证证据及CAS revision，然后原子激活；失败不改变当前行。C可受控发布Task/Policy/History，但不可以客户端“roles=[admin]”代替身份。Role恢复创建新Record，Key不得恢复原kid；新Key须新pending/Proof。Task换holder保留稳定task_id/principal/intent，推进revision，接受前重取全链；接受后只改变当前查询权，不改原Action。根代与W时间下界不回退；跨版本意图账永久共用，不能靠迁移恢复已消费许可。

## 5. 规范状态转换与恢复

1. Prepare在可信快照建立Action、Assessment与Basis；Assessment全部输出重算；必要资料未知不得产生可签发Basis。批准绑定同ctx和精确required_reviews；每个用途恰一APPROVE Review，无额外用途、无重复批准；U恰一APPROVE EXECUTE，且与全部V不同subject。
2. Issue认证H与全部依据，重建RequiredDeps，冻结Permit及Result。幂等键为(profile,domain,G,request.id)，同键同Ref返回原对象，异Ref为ID_CONFLICT；资格变化不能改写原响应为新许可。多请求发多Permit仍受同intent唯一接受约束。
3. Challenge认证当前H及其操作权限，COMMIT需permit_ref/AH匹配，STATUS两者均为空；持久化session/nonce、request_ref、purpose、op、holder/kid、exp及原Challenge。仅返回已持久保存的签名Challenge；无接受/资源副作用。
4. Commit事务先检查请求当前身份与绑定，再处理相同证明重传；原session异证明REPLAY。新接受在同W序列中重读当前性、独立重算、批准、许可/nonce、intent唯一性、资源与在途。全T才写消费/冻结/COMMIT/Core/预占/Behavior/Flight/派发意图/响应账/Journal并提交；失败整体回滚。COMMIT→RecordRef→AcceptanceCore→Ref的顺序避免环。
5. 已认证新请求的F/U在可确定的响应事务中消费nonce并保存原结果，但不消费Permit、不新增接受/预占/派发；格式或坏签名不消费。W不可取或提交不明为通信未知，不声称确定DEFER或回滚。相同已接受动作在当前查询鉴权后返回EXISTING；异动作OPERATION_CONFLICT，所有终态均参与去重。
6. 提交后只签冻结Core；原密钥不再允许签/过期时保留待签，不换kid/iat/exp/ref。已存回执恢复匹配原Core/Ref并以归档公钥验签；这不重新授予执行权。响应Result可由当前X签新鲜状态，原Acceptance仍保持原字节。
7. 派发领取事务重查dispatch_before、全部非自变deps/撤销、当前工具与资格及本操作占用。BEHAVIOR不用Permit的接受前revision比较；检查COMMIT接受后见证、累计上限、当前inflight含本op、Flight及reservation归属/账目一致。工业/医疗场景行按§2.2的精确scene_after检查。全T才原子pending→started并存唯一dispatch_attempt:B16。领取提交后才能作一次EXEC-0调用。
8. pending确定失效且确认从未领取时可取消：同事务检查每项占用、Flight归属与资源总账后释放自身预占/在途，记FAILED_CONFIRMED，保留接受/Permit消费/intent/累计次数墓碑。U保留pending；归属/账冲突HALTED且不释放。started后故障/超时为EFFECT_UNKNOWN，不回pending、不重派、不释放。
9. STATUS认证当前Task委托H与查询身份，只读操作快照并消费查询nonce/保存响应；无接受、派发或结算副作用。重传返回旧响应，更新状态需要新挑战。

接受判定/撤销按W提交顺序和可信时间tg，非客户端时间或现实事件发生时间。派发守卫只保证领取点之前已入W的变化；领取到实际发送之间的撤销要由工具另行参与才能阻止效果，本合同不声称已提供该保证。

### 5.1 工具终局合同（支撑记录，不加核心消息）

当前规范为[R2工具终局事实与再认证合同](04_tool_final_recovery.md)，完整规定TOOL_FINAL/TOOL_TRUST字段、签名域、FinalFactID、账连续性、领取见证、当前再认证和一次结算。它替代R1本节的“不同RecordRef就HALTED”与未定义首次历史终局恢复规则。

TOOL_TRUST新增ledger_id和evidence_method=tool-final-v2；TOOL_FINAL新增method、ledger_id及不可变finalized_at。效果事实包含原op/AH/attempt、账/工具身份、outcome/effect_id/no_late_effect和原final_seq/finalized_at；认证iat/exp及issuer/kid可以刷新。FinalFactID按固定独立域承诺完整事实，RecordRef标识包含签名的这份证明。

首次结算或新证明必须当前认证/时间与原派发见证全部为T。完全相同已确认历史证明可返回原结算；经当前认证的同事实新证明也只返回原结算，不重复释放或转支出。只有通过认证、绑定且不可变事实相反才HALTED；未认证或错绑定输入只拒绝/暂缓，不能由垃圾包停止操作。HALTED不由再认证自动解除。

C换工具钥只有确认同一持久账完整连续才能保留ledger_id；新账不能结算旧账未决attempt。工具从原账只读再认证，不从客户端旧sig复制事实，也不再次执行。查不到记录不是FAILED_CONFIRMED；账/时间/当前信任未知则保留占用。

所有Profile仍EXEC-0：每operation应用层执行调用至多一次，故障恢复只查询/再认证原attempt。工具效果恰好一次与现实世界真实性不由签名保证；EXEC-1未在本修订获准。

## 6. 三值、原因码与运输

检查输出T/F/U；有F则REJECT，无F有U则DEFER，全T才能推进。守卫顺序固定check标识：`format,signature,audience,scope,binding,policy,task,source,assessment,reviews,authorization,deps,holder,nonce,intent,resource,behavior,tool,result`。Reason精确`{check:上述Id,code:下列枚举}`；每check最多一项，按该顺序排列，禁止以自由文字或未知码推导成功。

| 分类 | 固定code |
|---|---|
| F | MALFORMED,LIMIT,UNSUPPORTED_VERSION,BAD_SIGNATURE,WRONG_SCOPE,WRONG_HOLDER,WRONG_AUDIENCE,BINDING,DEP_CONFLICT,REVOKED,STALE,EXPIRED,NO_ROLE,REPLAY,OPERATION_CONFLICT,ID_CONFLICT,OBJECT_KIND,OBJECT_INTEGRITY,CLAIM_FALSE,POLICY_DENY,REVIEW_DENY,AUTH_DENY,REVIEW_PURPOSE,REVIEW_REASON,REVIEW_REQUIRED,RISK_POLICY,DUPLICATE_CASE,DUPLICATE_INTENT,RESOURCE_LIMIT,BEHAVIOR_LIMIT |
| U | STATE_UNAVAILABLE,CLOCK_UNKNOWN,RISK_UNKNOWN,TOOL_UNAVAILABLE,TASK_BUSY,RETRY_CONFLICT |
| 按查询事实 | MISSING_OBJECT：完整权威查询不存在为F，合法引用暂不可读为U |
| 工作流待补 | MISSING_REVIEW,MISSING_AUTH：仅Prepare待补；完整提交缺引用/复核为MALFORMED或REVIEW_REQUIRED，不用待补码绕过 |
| 成功/原接受 | OK,EXISTING_ACCEPTANCE |

场景硬失败统一CLAIM_FALSE/POLICY_DENY/BINDING，资料未知RISK_UNKNOWN或STATE_UNAVAILABLE，保持既有码义。占用冲突属于内部完整性事件HALTED，不能向客户端谎报已成功或确定失败。新code不得只满足大写词法即被接收。

每Profile恰有四职责：POST prefix/issue→IssueRequest→Result；/challenge→ChallengeRequest→Challenge或Result；/commit→CommitProof→Result并附原Acceptance；/status→StatusQuery→Result并可附原Acceptance。type/path/profile/scenario/aud必须匹配，无query参数改变语义。TLS1.3、服务身份固定映射、禁用状态请求0-RTT。运输失败不等于协议REJECT。

Bundle精确`{message:Envelope,objects:List(Envelope或Record)}`，全部规范编码。objects按`Enc([object类别,Ref或RecordRef])`排序，同类别同ref只允许一项；必须与权威对象原字节一致才可缓存，不能导入为当前权威。返回对象只是响应附件：持久原对象才可形成成功；没有authority时不依赖附件肯定结果。HTTP 200仅表示收到响应，必须验签/绑定；非法未认证输入可用400、超限413、不支持内容类型415、服务不能确定503，均不是可认证业务结果。OpenAPI是运输结构参考，不定义展示接口。

## 7. 本轮决策来源及验证边界

继承：核心正文的10类型、Action/Ctx、三值、独立U、Ref不含签名及120/30/900秒寿命；07的分型Record、RequiredDeps、4运输职责；v2.5受限编码、严格点接受和Q01/Q02；11的工业/医疗范围及独立用途；14的闭包、冻结恢复、领取与取消。

本轮规范确定：Basis嵌入完整Action；跨Profile摘要参数及独立路径；Record外壳、资格Record/控制PoP、共同COMMIT归档字段；固定aud/deps/Result矩阵；来源与终局认证结构。它们是新协议合同决定，不声称此前已批准/实现这些精确字段。字段变更按2.6-R1处理，旧实验不改标。研究候选（Merkle/聚合/FROST等）未进入本规范。

交叉核查进一步确定：Role为固定枚举而非Id；POLICY固定G/X kid，X资格纳入Permit；accepted_at取同一可信区间lo；非PAY COMMIT增加场景前后见证；工具采用共同TOOL_FINAL和独立TOOL_TRUST。源规范依据为[Ed25519 RFC 8032](https://www.rfc-editor.org/rfc/rfc8032)、[JCS RFC 8785](https://www.rfc-editor.org/rfc/rfc8785)、[base64url RFC 4648](https://www.rfc-editor.org/rfc/rfc4648)。本合同的严格子群及类型限制是项目额外Profile规则，不能宣称仅遵循RFC即已实现所有限制。

完整协议符合性需：结构Schema及独立编码/验签向量一致；每种正负轨迹的原消息、资格/范围见证、T/F/U、W序及真实账可核验；并发/故障/跨Profile/迁移、工具终局分别验证。此次规范和结构核查不把66项系统验收改为PASS。

R2修订仅关闭工具终局恢复A02：完整差异与成立条件见04。此前R1语义与审查按原日期保留；其余审查澄清项不因此自动关闭。
