# 原 R2 与比赛应用对照

2026-10-12 · 开发对照页，配套 `CORE-SPEC-1.3` [共同安全协议](competition-protocol.md)。本页是消息与实现兼容参考，记录当前认证标识、应用语义与原精确合同的对应，不增加核心协议消息。共同安全规则见协议正文；固定比赛业务与展示范围见[开发总交接](scenario-integration-handoff.md)。

| R2 定义 | 比赛采用的对应关系 |
|---|---|
| 十种核心消息、严格 Envelope/Record、AH/Ref 域 | 原 Schema 文件、记录/动作哈希、字段基础版本 2.6 保留；CompetitionSchema 视图把十类消息 protected.proto 固定为 ZJJ-CORE-COMP-1，该标识被签名覆盖且当前接收器拒绝原 R2 ZJJ-AAP。内部挑战、ticket、W 派发/查询证书不增加核心 type |
| 持久接受后签冻结 Core | 共同 W 实现此顺序；当前逻辑守卫、固定窗口及受信单机串行发布具体化该规则 |
| RequiredDeps / required_reviews、各 type 的 deps 表 | 比赛可信有限图独立重算；Review/Authorization/IssueRequest/Permit/ChallengeRequest/Challenge/CommitProof 统一声明完整推导 deps。冻结 Acceptance 的 body.deps 为空，接受时资格证据存于 COMMIT.checked_deps/credential_witnesses；原 R2 按 type 规定不同集合且 Acceptance 列接受时 X KEY/ROLE，两者是明确的应用语义差异 |
| Review 受众须含实际 U | 当前应用 Review.aud 为 H/G/X，U 的当前读取权限由公共守卫另核；原 R2 Review 受众表还要求实际 U。展示描述独立权限检查，不宣称该受众表已逐项实现 |
| Basis/下游窗口继承所有承重资格到期 | 比赛在每个当前事件重核资格和窗口，Basis 期限约束基础来源/任务等；资格不预先把整个 Basis 寿命缩短。保证的是事件点当前资格，原 R2 的全部寿命继承规则保持其定义身份 |
| KEY/ROLE 与否决当前性 | 固定登记主体/业务范围，C 认证完整初始范围＋W 发布序列，按当前事件核验 |
| EXEC-0 / FinalFactID / 终局再认证 | 三模拟工具已运行原 attempt 查询、同事实再认证和一次结算；固定 epoch/账范围是实现选择，长期换钥连续认证按原合同定义保留 |
| STATUS：StatusQuery → X 签 Result，携原 Acceptance | 当前本地 status 是认证应用投影；原回执可以作为已签附件展示，外层投影不等于签名 Result |
| 四个正式运输职责与已认证 F/U 的持久响应/nonce 规则 | 比赛通过受信内部挑战驱动共同 W，输入签名链由受控场景构造；异常拒绝回滚该应用事务，不形成正式签名 Result/原协议拒绝响应账。八方法不是已实现的四端点消息服务 |
| 独立审计义务与证据对象 | 当前离线核验原签名、引用及 W/工具账一致性；本地 audit 投影、运行 JSON 和 manifest 不称为完整 R2 签名 AUDITBundle |
| STATUS 的当前 Task 委托及窗口 | 当前本地读取认证固定 H 的当前资格/策略读取权与原 Action 范围，不另重验当前 Task 委托/窗口；比赛固定登记下按本地读取约定说明 |
| 占用/Flight 归属异常的持久 HALTED | 当前归属守卫抛错、阻断且保留原状态/占用，没有自动持久 HALTED 转移；工具可信事实矛盾的 HALTED 已实现。具体区别见[当前接口](interface-reference.md)，不能由抛错推断 W 已变更终态 |
| F/U 判定、正式原因码和签名状态 | 当前守卫按顺序首个异常阻断，不形成完整聚合 F/U 结果；阶段分类及视图不可获取是接线说明，不加入 R2 状态/原因码 |
| 执行恢复与状态维度 | EFFECT_UNKNOWN 是工具调用标签；W 效果为 UNKNOWN，EXEC 消费另记。新领取不等于已消费，已消费恢复不重授资格；HALTED 属操作停止状态，保留历史事实 |

上述规则目标、已运行机制与应用语义差异分别标明。当前回执是在原字段结构和签名域上、以独立比赛 proto 标识认证的冻结 Acceptance，证明本运行中的原接受事实；Schema 合法及签名有效不等于原 R2 全部消息语义符合。比赛与原 R2 的语义由认证标识区分；保留原证据及原 R2 源定义，不通过改变旧记录消除差异。具体实现见[安全边界与签署契约](security-boundaries.md)。

精确依据：[核心合同](../../../system_dev/v26/01_core_contract.md)、[PAY](../../../system_dev/v26/02_pay1_profile.md)、[工业医疗](../../../system_dev/v26/03_industrial_medical_profiles.md)、[终局](../../../system_dev/v26/04_tool_final_recovery.md)、[原 Schema](../../../system_dev/v26/contracts/)。实现参数及八方法查[公共 W 开发契约](../w-transaction-contract.md)。[查询审计口径](query-audit-scope.md)和[声明证据清单](claims-evidence.md)限定对外表述。
