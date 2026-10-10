<!-- Local frozen contract copy; source docs/competition-final-20261010/06, 2026-10-10; links retained as labels. -->
# 06 公共状态与最小接口契约

版本：`COMP-APP-MIN-1.0`；2026-10-10；状态：**本地实施基线已冻结，运行实现未完成，远端尚未采纳**。来源、差异与五次变更见总入口，启动步骤见交接。

这是 Python/SQLite 比赛服务的内部职责与应用投影合同，供五类任务共同使用。八个方法不新增八种协议消息，也不替代 R2 四个运输职责。原 `proto=ZJJ-AAP / version=2.6`、三套 Schema、摘要域、10 消息和工具终局合同继续逐字适用；`COMP-APP-MIN-1.0`只标应用合同。新增应用字段不得塞入严格原 Envelope/Record。缺完整成功附件时不得伪造 R2 ACCEPTED/STATUS。

## 1. 本次固定的决策

1. 默认走 **R2 先持久接受，后签冻结回执**。W 全T接受事务提交是接受事实的持久线性化边界；`accepted_at=lo`是该事务定义的受信逻辑决策时间，排序由 `accept_seq`，不声称物理落盘时间等于lo。COMMIT→RecordRef→冻结Acceptance Core→Ref，无摘要环。
2. 事务提交后 X 只能签经认证W读取的原Core。签名失败保留唯一接受、消费、意图和预占，应用显示回执待签；回执合法保存之前不允许claim。接受前失败无新接受。提交应答丢失由status查原请求；查询不到或读源未知不授权重做。
3. 默认 **EXEC-0**：每op应用层execute调用至多一次；started后的恢复只query_attempt原attempt。原工具deliver的重传可作为旧实验参考，不能成为新核心自动重试路径。
4. 三Profile共享一个W事务/唯一性域；业务差异在适配器。任何公共F/U不能被适配器、UI或fixture转成T。W和工具账是两个持久域，不要求跨库分布式提交。

远端规格P0-A及迁移§3仍要求X成功后才提交；本合同并未修改远端，也不是双方已经达成的代码事实。若改走签名先行，只能单独升应用合同版本并重新定义未发布签名、最后重验、未知提交和回执兼容；不能同时实现两条路线作为隐式回退。

## 2. 最小公共数据

以下是逻辑字段，不强迫拆成许多服务/文件。内部实现可用dataclass；输入中原协议对象保持原受限编码和精确类型。

| 结构 | 必需字段与责任 |
|---|---|
| `CallContext` | 由受信入口产生的`subject, credential_ref, session_id, authenticated_scope, allowed_purposes, auth_witness_ref`；外部只递交凭据/原签名请求，不能自报角色。调用时重新核当前资格；worker和auditor也有独立职责凭据。日志不存凭据秘密 |
| `OperationKey` | `profile, scope:{domain,tenant,scenario}, operation_id:B16`；Profile与scenario固定一一对应。scope全字段精确相等，按op查亦需当前ACL |
| `RequestKey` | 上述Key＋`request_id, request_ref`；绑定原请求字节/Proof及session/nonce。相同id同Ref返回已存结果，异Ref为ID_CONFLICT；异动作同op为OPERATION_CONFLICT。无原请求授权不能只凭字符串id恢复 |
| `PrepareTicket` | `ticket_id, OperationKey, request_ref, action_hash, basis_ref, source/deps_snapshot_refs, prepared_event_ref, ticket_exp, missing_obligations, contract_version`；服务持久绑定，客户端拷贝不能授予权限。Operation由W受控登记；ticket消费不是Permit/执行nonce/intent消费 |
| `FrozenAccept` | 原`action, AH, permit_ref, proof_ref, authorization_ref, review_refs, commit_record_ref, acceptance_core_bytes, acceptance_ref, original_x_kid, accepted_at, accept_seq, dispatch_before`，及COMMIT原资源/Behavior/Flight/scene见证、原身份公钥见证；Core/Ref即使未签也可冻结，必须另外标明未认证 |
| `DispatchFact` | `OperationKey, AH, commit_record_ref, acceptance_ref, attempt_id:B16, tool, tool_version, destination, ledger_id, tool_trust_ref, dispatch_time_witness_ref, claim_seq, delivery_packet_ref, signed_packet_bytes`；绑定COMMIT.frozen_tool_request，attempt由W唯一生成，调用方不得指定新attempt |
| `ToolProof` | 工具终局Record原bytes/`RecordRef`、`FinalFactID`、原attempt/ledger/Action绑定、当前认证与时间/连续账见证。FinalFactID按R2终局合同重算，不能用RecordRef替代事实身份 |
| `StateView` | `OperationKey, acceptance_state, receipt_state, dispatch_state, effect_state, settlement_state, status_seq, observed_w_seq, observed_at, observation_freshness, origin, refs, counts, limitations`；投影不是原签名对象，无签名即标未认证 |
| `Provenance` | `build_commit, worktree_digest, dirty, contract_version, protocol_version, schema_manifest_ref, profile_adapter_version, run_id, evidence_manifest_ref`；未提交构建用真实HEAD＋dirty摘要，根文档目录无HEAD时值为空并说明，不填造假的提交 |

`scope.scenario`固定：IND-DEMO-1=industrial，PAY-1=payment，MED-DEMO-1=medical。内部Key编码为结构化元组，不能拼接易冲突字符串。intent不含contract_version、route、template或随机operation；使用原Profile精确规范：PAY订单阶段，IND工件cycle/phase，MED就诊医嘱组阶段。新run仅隔离展示，不清空旧业务意图；新演示须受控生成新的合成对象/独立库。

### Refs、版本与证据

应用引用采用`{ref_type, profile, scope, kind, ref, bytes_digest, provenance_ref}`，ref_type白名单为`EnvelopeRef / RecordRef / StateRef / FinalFactID / AppEvidenceRef`。`AppEvidenceRef`仅定位日志/票据，不能充当协议授权。原body.refs和deps仍按R2类型表构造，不能将应用引用描述符写回原协议字段。

Ref不含sig，同Ref的每份认证仍须独立验签；bytes_digest用于确切原bytes留存。`revision`是每个承重范围的单调版本；control/source快照同时记录`namespace,key,revision,ref`及认证发布W序，含DENY空集覆盖。KEY/ROLE撤销再授推进版本/epoch，ABA不复用旧值。build/合同/Schema版本不匹配或未知Profile/枚举明确拒绝，不静默降级。原历史对象只按其原版本读取；永久意图不因升级重置。

## 3. 公共状态与合法转换

状态按事实维度记录，不能用单个“成功/失败”同时代表接受、签名和效果。

| 维度 | 值 | 允许转换与约束 |
|---|---|---|
| 接受事实 | `NONE / COMMITTED` | 仅全T原子提交使NONE→COMMITTED；不可撤回为NONE。`COMMIT_UNKNOWN`仅是调用方观察，不是W第三种事实 |
| 回执 | `ABSENT / PENDING_SIGNATURE / SIGNED` | 接受后待签→合法原Core签名保存；无法补签时仍PENDING_SIGNATURE并记原因，不换kid/iat/exp/ref。SIGNED只恢复原bytes，不重签原响应 |
| 派发 | `NONE / PENDING / STARTED / CANCELED` | 提交后PENDING；claim全T CAS→STARTED并存唯一attempt；确定失效且确认未领取时CAS→CANCELED并核归属释放。STARTED永不回PENDING，不生成第二attempt |
| 效果 | `NO_ATTEMPT / EFFECT_UNKNOWN / SUCCEEDED / FAILED_CONFIRMED / HALTED` | STARTED无终局立即保守UNKNOWN；已认证终局才成功或确认无效果失败；可信不可变事实矛盾HALTED。超时、空查询或坏签名不形成FAILED_CONFIRMED |
| 结算 | `NONE / SETTLED / HALTED` | 同FinalFactID一次SETTLED；重复证明仅追加证据。可信矛盾或占用账冲突HALTED，不自动补偿/释放 |

领取前CANCELED可按原pending取消规则形成确认无效果失败，记录`finality_origin=W_PENDING_CANCEL`；它不是伪造工具TOOL_FINAL。各终态均保留原接受、Permit消费、intent墓碑和累计计数。未知保留预占/flight，HALTED保留事实与调查证据。

应用观察码固定为`PREPARED / REJECT / DEFER / COMMIT_UNKNOWN / COMMITTED_RECEIPT_PENDING / ACCEPTED_WITH_RECEIPT / EXISTING / STATUS / EFFECT_UNKNOWN / SUCCEEDED / FAILED_CONFIRMED / HALTED`，仅用于投影。原协议PENDING仍指“已登记未接受”；COMMITTED_RECEIPT_PENDING不得输出为原R2成功Result。原Acceptance存在时再由合法协议响应携带，当前Result与历史附件的时效各核。

## 4. 时间见证与原始待决项（下方增补记录IND实现）

`TimeWitness`目标内部字段：`provider_id, clock_id, clock_epoch, sequence, profile, scope, operation_id, request_ref, stage, sample_ref, lo, hi, sampled_monotonic, used_monotonic, age_upper_bound, health, control_snapshot_ref, guard_w_seq, authentication_ref`。整数/Unix秒遵原类型；单调钟用于年龄，不能当墙钟。`stage`固定本表值。字段不是现有packet已支持的声明；新增绑定需P-02定义签名内容或受信本地关联，不靠未签client字段证明。

单提供者全局递增sequence，三Profile共用持久floor/seq；本版固定clock_id/epoch。重启时无法恢复有界年龄就取新样本或U。业务事务拒绝可回滚floor/seq消费；重用未消费样本仍重新核年龄。区间宽≤2；所有承重对象`iat<=lo && hi<exp`为T，`lo>=exp`为F，其余边界/来源未知为U。

| 事件stage | 检查责任和最小保证 | 待时间任务关闭的点 |
|---|---|---|
| `PREPARE` | 当前身份/来源、ticket有效窗口；只证明准备事件，不沿用作接受当前性 | P-02给ticket寿命/Provider采样关联，不强迫准备与接受相同秒 |
| `ACCEPT_GUARD` | W事务内新样本/有界年龄区间，全依赖/批准/DENY/资源当前性；同W序冻结Core | P-01/02定义逻辑守卫覆盖及事务耗时界；区间覆盖不足为U，不删除TIME_CHANGED后假绿 |
| `RECEIPT_SIGN_GUARD` | X核已提交原Core、冻结kid/窗口及当前X资格；记录实际签名生成观察时间，原iat=accepted_at | P-01定义受信签名守卫的线性化与隔离，不能用接受时X资格代替当前资格 |
| `RECEIPT_PUBLISH` | W保存/返回前验原bytes和签名守卫见证/范围revision；失效则不作为新鲜合法回执发布；原接受仍在 | P-01/03定义检查样本年龄、revision变化、签后保存/返回间的失败及恢复；不声称CAS证明私钥物理瞬间无撤销竞态 |
| `CLAIM_GUARD` | W核dispatch_before、非自变deps、当前工具资格、scene_after及自己占用；全T唯一领取 | P-02绑定当前区间和领取事件；领取后的跨服务即时撤销/物理执行期限后置 |
| `TOOL_FINAL_AUTH` | 模拟工具先持久固定事实，后以当前时间/认证签原事实；恢复再认证不执行 | P-02/PR3明确模拟工具决定点与签名时间，未知账不得签确认失败 |
| `SETTLE_GUARD` | W核当前工具认证、连续原账、原attempt、终局签名窗口与归属；不重验过去接受为新授权 | P-02/PR3接入当前时间；未知保持占用 |
| `STATUS_RESULT` | 当前查询身份/ACL、新挑战和当前响应签署资格；W快照只读业务账 | P-03定义签新Result的时间事件；原请求重传只取旧响应，不刷新观察 |
| `AUDIT_READ` | 当前读取ACL；历史公钥/当时资格见证与当前有效性分开 | 纯离线历史核验不伪造当前时间T，包过期/不足明确限制 |

**收敛轮的原始待决项（历史记录，当前IND状态见§7）：** Provider最大年龄/耗时参数及来源、签名守卫与发布点的可实现序列、重启年龄恢复、时间packet新绑定、签名后资格改变的处理、原回执未能形成时完整R2 STATUS附件限制。P-01～03须在01文件追加决策与可运行证据；本合同给字段与保守行为，未虚构时间闭环已运行。

## 5. 八个最小接口

以下签名是行为冻结的伪代码，非现存可执行API。`ctx`由入口认证；`clock/x_signer/tool_gateway/store/adapter_registry`由服务启动注入，调用方不能提交实现、pubkey、URL或eligible布尔。

```python
prepare(ctx, profile, scope, signed_request_bytes, source_ref_hints) -> PrepareTicket | Outcome
accept(ctx, ticket_id, signed_commit_proof_bytes, request_id) -> Outcome
claim(worker_ctx, operation_key) -> DispatchFact | Outcome
execute_once(worker_ctx, operation_key, attempt_id) -> ToolProof | Outcome
query_attempt(recovery_ctx, operation_key, attempt_id) -> ToolProof | Outcome
settle(worker_ctx, operation_key, attempt_id, signed_tool_record_bytes) -> Outcome
status(ctx, operation_key, signed_status_query_bytes=None, original_request_ref=None) -> StateView | Outcome
audit(auditor_ctx, operation_key, export_mode) -> AuditBundle | Outcome
```

| 方法 | 输入信任与时间 | 写入和幂等边界 | 返回/故障与禁止动作 |
|---|---|---|---|
| prepare | 当前会话及原H请求身份匹配，当前read权限先于候选读；来源hint由权威C/E重取；PREPARE见证 | 可登记op、ticket和审计；受控登记并核稳定intent，保留同请求映射 | 缺Review/Auth仅报待补；无业务预占/接受/派发；改变候选新Basis并重签 |
| accept | ticket与原Proof/Challenge/Permit精确绑定；ACCEPT_GUARD重建全链；X由内部冻结回执流程调用 | 同W事务写完整接受事实；同原请求只取原COMMIT/Core/响应，可内部恢复原Core签名但不再接受；事务后签/保存 | 有F REJECT、无F有U DEFER；未知提交COMMIT_UNKNOWN；已提交未签返回应用待签；合法回执才协议成功。网络超时禁止新id盲重试 |
| claim | 当前worker职责；仅COMMITTED＋SIGNED＋PENDING；CLAIM_GUARD | W生成attempt，冻结工具映射和派发bytes，CAS一次；重复返回原attempt及已开始状态 | 从不由外部指定attempt；U不领取，确定失效可原子取消；不调用工具。claim提交未知只查W |
| execute_once | 仅首次领取的内部执行持有者；从W取原attempt/已保存W签名派发，不信传入packet | 持久标记首次调用资格已使用后，才调用一次工具；工具自身原子存dedup＋效果＋终局 | 崩溃在标记和发送之间也可能没有效果，保守UNKNOWN，牺牲自动活性；重启/重复调用只返回已使用/未知，禁止再EXEC。不得靠调用flag断言实际已发送 |
| query_attempt | 恢复职责当前认证；从W取原Action/AH/attempt/ledger，工具只读查询/可当前再认证原事实 | 不新增accept/attempt/效果/工具final_seq；可追加查询及认证证据，若要结算显式调用settle | 查不到=EFFECT_UNKNOWN，绝不执行或签FAILED_CONFIRMED；旧attempt仍原Profile，不按当前UItab改派 |
| settle | 当前worker职责；SETTLE_GUARD核ToolProof的当前资格、窗口、账连续性和绑定 | 同W事务按FinalFactID唯一结算，核自己reservation/flight并更新业务after；重复取原结算 | 坏签名为输入REJECT，不污染已存事实；可信矛盾HALTED；未知不释放/重试；不同RecordRef同事实不重结算 |
| status | 当前读者ACL；应用查询原Request可查提交；正式R2模式必须新STATUS挑战/原StatusQuery；STATUS_RESULT | 同快照读W；允许查询nonce消费、原响应映射/审计写入，不改业务计数 | 不签补Acceptance、不claim、不query工具、不settle；旧响应重传仍旧观察。应用待签投影不假装完整协议STATUS |
| audit | 当前auditor读取/导出权限及固定受信根；AUDIT_READ | 只读原消息/W及已保存工具证据；可生成独立导出文件 | 不修账、不持权威私钥、不取新执行权；私钥/会话秘密不导出；脱敏投影不冒充原签名bytes |

execute_once/query_attempt为内部工具职责，普通Web读者只能status/audit。settle可以由明确的恢复编排接query_attempt后调用，但status/audit绝不隐式编排恢复。无需建立通用公网工具API或复杂认证平台。

### Outcome、错误与未知

最小返回结构：`{observation_code, decision:T|F|U, authoritative_state, request_key, status_seq, refs, checks, time_witness_refs, evidence_refs, provenance, limitations}`。checks记录`check_id, value:T/F/U/NOT_CHECKED/NOT_APPLICABLE, reason_code, witness_refs`；展示文案不参与判定。未执行的守卫不能填T。应用回执/提交未知码不填入原R2 Reason白名单。

原协议F/U原因码沿R2§6，适配器只用已有语义。完整权威查询对象不存在为F；对象暂不可读为U。非法未认证运输失败不冒充签名REJECT。坏输入拒绝不证明原账没有接受，必须另查询原事实。HTTP成功不等于协议接受或效果成功。

计数分开记录`accepts, claims/attempts, exec_invocations, query_calls, confirmed_simulated_effects, settlements`；运行调用日志不能单独证明精确EXEC次数，崩溃间隙标`exec_count_known=false`及0..1界。效果未知时确认数/已知界与unknown分开，不把“确认0”显示为确定无效果。每项证据绑定case/build/run、原输入摘要、W/工具快照、expected/actual和限制。

## 6. 同一W责任与Profile责任

W权威域负责公共身份/用途/严格验签、认证对象库、全量DENY覆盖、RequiredDeps验证机制、时间、请求/nonce/intent唯一性、资源/Behavior/Flight、接受/回执/派发/结算和只读投影。所有控制/来源激活、DENY发布、接受、claim/cancel在同W序或经同快照栅栏核验。工具唯一性由独立工具账负责，W核绑定并只结算一次。

适配器只负责固定Action/schema及来源对象绑定、原算法推导required_reviews/RequiredDeps、原稳定intent、资源计划、scene before/after和终局业务变更；工具模拟器负责对应合成效果。IND的QUALITY_REVIEW、PAY按history-int-v2风险用途、MED每次CLINICAL_REVIEW仍分别适用。核心统一不把三套审批规则合并成一条。

允许复用纯编码/验签与原Profile函数，业务表可不同，但必须在同SQLite连接/接受事务写入；独立库副作用或旧accept不能从adapter内自行提交。PR1先做工业最小真实纵切和W基础表；PR2补三Profile完整安全门；PR3完成共同账/工具恢复。PR1完成不代表三场景共同核心已经完成。

比赛最低交付为单W、固定registry、有限对象图、固定构建和三个签名模拟工具。生产治理、跨库原子提交、自动补偿、长期观察协议和物理设备时间控制保持05后置范围。

## 7. P-01～03实施增补：IND局部映射

2026-10-10：`competition-runtime/`已建立独立竞赛checkout；本合同八方法仍为共同目标，不能把IND局部API等同于全部字段已实现。具体可运行规则见接受时序。`COMP-IND-TIME-1.0`为局部适配器标识，不改原协议2.6或本合同版本。

| 共同职责 | 本轮实际映射/限制 |
|---|---|
| prepare | `IndustrialAcceptanceW.prepare(op)`；原H签名请求＋全部当前IND守卫；持久ticket不产生业务权利；不是完整HTTP会话入口 |
| accept | `challenge_accept(ticket)`后H签`COMP-APP-ACCEPT-v1`应用挑战；`accept(ticket, signer, proof=...)`核当前H KEY/HOLDER/READER、POLICY读者、TASK归属；新接受及历史恢复都要新身份挑战，ticket单独无权。原CommitProof业务nonce另存 |
| 回执恢复 | 内部`complete_receipt`只签已提交原Core；W签署/发布守卫重核当前X/窗口，1.5秒RPC上限；签后见证年龄仍≤2秒。保存后重传原bytes。后台恢复不是公共调用身份替代 |
| status | `challenge_status`＋H签`COMP-APP-READ-v1`；当前KEY/READER、POLICY ACL/时效、TASK归属/时效；同快照投影，不补签/接受/claim/工具调用。只返回已实现接受/回执维度与status_seq，其他维度不填假T |
| claim / execute_once / query_attempt / settle / audit | claim仅保守拒绝：待签RECEIPT_PENDING、已签DISPATCH_NOT_IMPLEMENTED；其余未在新服务实现。旧prepare/finalize/claim/cancel/settle入口关闭；内部snapshot/_view仅操作员测试，不暴露为认证查询 |

IND已落实PREPARE、最终ACCEPT_GUARD、RECEIPT_SIGN_GUARD、RECEIPT_PUBLISH及应用STATUS_READ；后者是局部应用事件，不冒充原协议STATUS_RESULT。C签名绑定provider/epoch/实例/全局源sequence/profile/scope/op/stage/requestRef、wall/mono、lo/hi和health。W pin根/实例，持久lo floor；失败业务事务回滚W样本消费。源序列单独持久推进。

受信单机参数已明确：总年龄≤2秒，实际mono年龄≤1.975秒并留25ms漂移裕量；C进程内wall/mono累计偏差≤12.5ms才healthy；上界随实际年龄推进，宽≤2秒。旧实例U，重启用新实例样本且保留源seq/W下界；固定epoch=1，跨epoch/主机重启连续性未证明。最大年龄和事件绑定不再是IND待决项。

接受最终逻辑lo记录accepted_at，W COMMIT形成持久事实；签名历史iat不回填，真实生成时间另记。W写锁覆盖签署与保存，阻止同W控制revision并发改变；签后新样本再核当前资格与窗口。这只证明声明的单机逻辑守卫，未证明外部私钥设备物理时刻无竞态。提交应答未知先查询原事实，真实子进程提交后exit97证明这一恢复边界。

仍未关闭：MED/PAY接入、领取/工具/结算时间事件、完整StateView/Outcome/正式R2 STATUS附件、Linux DAC隔离、独立时间设施及长期Observation。原Core900秒窗口到期检查有代码，未以实际等待900秒给整条回执到期颁PASS；本轮实跑的是5秒原Proof/ticket到期和当前X资格到期。
