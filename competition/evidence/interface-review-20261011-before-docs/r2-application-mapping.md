# 原 R2 与比赛应用对照

2026-10-11 · 开发对照页，配套[比赛协议](competition-protocol.md)。本页记录应用语义和原精确合同的对应，不增加核心协议消息。

| R2 定义 | 比赛采用的对应关系 |
|---|---|
| 十种核心消息、严格 Envelope/Record、AH/Ref 域 | 原 Schema 和消息定义保持；内部挑战、ticket、W 派发/查询证书是应用支撑对象，不增加核心 type |
| 持久接受后签冻结 Core | 共同 W 实现此顺序；当前逻辑守卫、固定窗口及受信单机串行发布具体化该规则 |
| RequiredDeps / required_reviews、各 type 的 deps 表 | 比赛可信有限图独立重算；Review/Authorization/IssueRequest/Permit/ChallengeRequest/Challenge/CommitProof 统一声明完整推导 deps。冻结 Acceptance 的 body.deps 为空，接受时资格证据存于 COMMIT.checked_deps/credential_witnesses；原 R2 按 type 规定不同集合且 Acceptance 列接受时 X KEY/ROLE，两者是明确的应用语义差异 |
| Review 受众须含实际 U | 当前应用 Review.aud 为 H/G/X，U 的当前读取权限由公共守卫另核；原 R2 Review 受众表还要求实际 U。展示描述独立权限检查，不宣称该受众表已逐项实现 |
| Basis/下游窗口继承所有承重资格到期 | 比赛在每个当前事件重核资格和窗口，Basis 期限约束基础来源/任务等；资格不预先把整个 Basis 寿命缩短。保证的是事件点当前资格，原 R2 的全部寿命继承规则保持其定义身份 |
| KEY/ROLE 与否决当前性 | 固定登记主体/业务范围，C 认证完整初始范围＋W 发布序列，按当前事件核验 |
| EXEC-0 / FinalFactID / 终局再认证 | 三模拟工具已运行原 attempt 查询、同事实再认证和一次结算；固定 epoch/账范围是实现选择，长期换钥连续认证按原合同定义保留 |
| STATUS：StatusQuery → X 签 Result，携原 Acceptance | 当前本地 status 是认证应用投影；原回执可以作为已签附件展示，外层投影不等于签名 Result |
| 四个正式运输职责与已认证 F/U 的持久响应/nonce 规则 | 比赛通过受信内部挑战驱动共同 W，输入签名链由受控场景构造；异常拒绝回滚该应用事务，不形成正式签名 Result/原协议拒绝响应账。八方法不是已实现的四端点消息服务 |
| 独立审计义务与证据对象 | 当前离线核验原签名、引用及 W/工具账一致性；本地 audit 投影、运行 JSON 和 manifest 不称为完整 R2 签名 AUDITBundle |

上述规则目标、已运行机制与应用语义差异分别标明。当前回执是在原结构和签名域上的比赛冻结 Acceptance，证明本运行中的原接受事实；Schema 合法及签名有效不等于原 R2 全部消息语义符合。本轮保留真实行为并限定声明，不修改证据来消除差异。

精确依据：[核心合同](../../../system_dev/v26/01_core_contract.md)、[PAY](../../../system_dev/v26/02_pay1_profile.md)、[工业医疗](../../../system_dev/v26/03_industrial_medical_profiles.md)、[终局](../../../system_dev/v26/04_tool_final_recovery.md)、[原 Schema](../../../system_dev/v26/contracts/)。实现参数及八方法查[公共 W 开发契约](../w-transaction-contract.md)。[查询审计口径](query-audit-scope.md)和[声明证据清单](claims-evidence.md)限定对外表述。

