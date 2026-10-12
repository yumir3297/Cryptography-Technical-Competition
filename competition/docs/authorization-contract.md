# A-01～04公共授权实现契约

2026-10-11；应用增补 COMP-APP-AUTHZ-1.0；原ZJJ-AAP 2.6消息、Schema、摘要域和数量不变。PAY来源继续用原严格v2.5 Evidence桥。所需基础模块位于 competition/support，原研究材料完整保留本地归档。

## 固定身份与范围

|别名|IND角色|MED角色|PAY角色|允许用途|
|---|---|---|---|---|
|H|HOLDER|HOLDER|HOLDER|IssueRequest、ChallengeRequest、CommitProof、StatusQuery、READ|
|G|ISSUER|ISSUER|ISSUER|Permit、READ|
|X|EXECUTOR|EXECUTOR|EXECUTOR|Challenge、Acceptance、Result、READ|
|U|LINE_OPERATOR|MEDICAL_AUTHORIZER|FINANCE|Authorization（EXECUTE）、READ|
|V|QUALITY_REVIEWER|CLINICAL_REVIEWER|ANOMALY|Review（Profile推导用途）、READ|
|E|SOURCE|SOURCE|SOURCE|SOURCE、READ；不签批准|

固定scope为lab/tenant-1/industrial、medical、payment，与Profile逐一绑定。新受控运行生成随机钥与subject/kid、公钥；实际PoP先于C激活KEY。KEY/ROLE当前epoch与行revision一致，撤销KEY留墓碑。W只有不可变公钥roster；broker在W外拥有钥。

ROLE限制tool/destination和业务范围：IND line/station/route（有unit_set则核unit）；MED synthetic_patient/encounter/template；PAY payer_set/max_amount_minor。E的SOURCE资格也核本次实际Action业务范围。原适配器进一步核工件/批次/cycle/phase、患者/资料/医嘱组、订单/收款人/金额/币种/阶段。U不能与G/X同subject，需V时V不能与U/G/X同subject；不同kid不能冒充分离。H/U同subject合法配置三Profile通过。工业无Review时不强制V独立；竞赛副本只修此分离条件和E业务范围，原研究_bound不改。PAY原Schema无READER，使用policy.readers＋原业务ROLE的READ用途。

## 实际内部接口

|接口|责任|
|---|---|
|TrustedState.publish(C certificate)|精确绑定Profile/fullscope/ns/key/previous_revision/record/active/enrollment；C实际签名与CAS当前发布|
|challenge(profile, op, stage)|GUARD/CANDIDATE/DETAIL的H一次性挑战；绑定完整调用摘要；30秒窗口|
|AuthorizationService.guard(profile, op, proof)|H真实调用签名、当前角色/ACL与完整业务链；保存AUTHORIZED_GUARD/T，protocol_acceptance=False|
|CommonGuard.verify(c, profile, op, event)|内部同W事务；原Schema/实际签名/Refs、subject/kid/role/purpose/scope/受众、当前资格、独立集合与DENY|
|adapter.derive(c, op, event)|可信当前对象独立返回required_reviews/deps/basis_deps/assessment_value及policy/task/evidence原文和Refs|
|initialize_coverage(C certificate)|受控登记精确Ctx/Action完整空集revision1；客户端空列表不是见证|
|publish_review(profile, signed message)|注册范围内原Review/Authorization的真实APPROVE/DENY；当前资格、业务权限和事件；同W序，CAS revision+1|
|deny_witness(c, profile, ctx, required)|全量存储发布查询、原签名与日志/时间签名/连续revision核对；不信调用方DENY列表|
|read(profile, op, proof, stage, candidate)|当前H读取ACL先于来源推导和受信候选回调；返回裁剪资料投影|
|ScopedSignerBroker.sign(profile, alias, unsigned, action)|固定roster/currentrole/purpose/fullscope/business范围及原Schema/窗口过滤；非独立业务决策|

TrustedState把三个Profile有限对象、身份nonce、覆盖与发布事实置于一套SQLite W。IND已有接受库通过只读bridge接共同守卫/DENY表；current_row是其唯一当前来源库，不并存第二份a_current权威。consumer仅能在受信服务启动时注入，不能作为外部调用输入；T必须在同事务消费供后续PR3。

IND prepare/accept已在实际接受事务调用同一守卫，额外冻结应用authorization_witness；原COMMIT/Core不加字段。接受/预占/消费/ACCEPT_AUTHORIZATION序原子提交。DENY晚于接受不改原COMMIT，恢复原冻结事实；未来claim还需新守卫。MED/PAY本轮通过共同授权入口，其业务提交/工具不是已经实现的能力。

## 批准、依赖和DENY规则

IND DEMO_UNCERTAIN→INSPECT需QUALITY_REVIEW；PAY history-int-v2保留CLEAR无V、FLAG→ANOMALY、INSUFFICIENT→LOW_EVIDENCE；MED始终CLINICAL_REVIEW。全部仍需U EXECUTE。缺项、多余用途、错误主体及来源硬失败拒绝。

Basis/Assessment从同事务当前可信C/E对象重建；新竞赛输入每份Review/Authorization/Issue/Permit/ChallengeRequest/Challenge/CommitProof均声明完整推导deps，排序后精确比较。该竞赛规则比旧局部声明子集更强，原wire shape不变。IND/MED的EVIDENCE/IDENTITY/PACKAGE不属合法wire Dep namespace，直接核认证原文及传递绑定。PAY保留有限64节点current source-deps图，不支持的CONFIG/异订单桥拒绝，未实现通用递归策略或独立历史全覆盖。

KEY/ROLE变化在新事件重查，撤销再授推进revision/epoch使旧deps失效。Basis期限无需预先缩短到临时资格期限；资格在准备、接受、发布/读事件必须仍有效，不能缓存仍有权限。

DENY适用键=Profile/fullscope/operation_id/冻结BasisRef/注册必需用途（EXECUTE＋推导Review）。C认证初始完整空集和W唯一发布入口形成覆盖声明；发布每次推进revision，后续APPROVE不抹DENY。省略Ref仍被全量DENY阻断；重考虑需新Basis并重签下游。BEGIN IMMEDIATE串行化控制变化、发布、guard/接受/读取。

## 错误与证据边界

硬失败保留ProtocolError实际理由：MESSAGE_BINDING、SUBJECT_SEPARATION、NO_ROLE/REVOKED、REVIEW_REQUIRED/REVIEW_DENY、DEP_CONFLICT/STALE、BASIS_BINDING等及原验证器具体理由。DENY_COVERAGE_UNKNOWN、CLOCK_UNKNOWN、STATE_UNAVAILABLE为未知，应DEFER；不能自动转T。新增应用错误不扩原协议理由码。

复用P的C真实事件签名、全局sequence、同W floor，新增AUTHZ_GUARD/AUTHZ_READ/DENY_PUBLISH/CONTROL_PUBLISH；身份/发布再核当前事件。仍是单机OS、固定epoch和已有最大样本年龄/保守区间，不证明跨宿主或物理执行即时撤销。

导出原签名链、C发布、公共roster/PoP、版本、覆盖/发布W序与事件、expected/actual和真实计数，不导私钥。guard_commits只是授权检查事实；MED/PAY未实现的资源/工具不能填字面0冒充真实账验证。真实IND竞争另导accepts/reserved/calls。

资料投影标CROPPED_APPLICATION_PROJECTION及original_envelope=False，不冒充可验原Envelope；医疗当前ACL在资料读取/候选回调前检查。

Windows同用户bootstrap和chmod不证明Linux DAC。W部署身份不能读权威私钥的Linux验收移交S-03/T-02。Tool/W-delivery身份属于PR3，本轮不宣称运行。动态组织治理/HSM按用户要求后置。完整三ProfileCoreService、资源/派发/结算与UI/净环境安装仍后续任务。
