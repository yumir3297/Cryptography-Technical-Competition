# 比赛配置与三个场景开发总交接

2026-10-12 · 配套共同规则说明 `CORE-SPEC-1.3`。本页承接[安全协议](competition-protocol.md)之外的比赛实现选择、具体业务规则和运行结果；接线使用[真实接口](interface-reference.md)。本次正文整理不更改代码、消息标识、Schema 或执行行为。

## 1. 固定运行配置与职责

比赛采用受信单机、固定登记范围和三个签名模拟工具。C 认证登记来源、角色、策略、容量及当前版本，W 与工具各持独立持久账；同一权威发布序列支持完整覆盖与当前性检查。模拟效果分别是产线路由记录、合成付款记录与合成医嘱登记。OS、时间源、根配置、账库与私钥管理受信。

agent 只提交严格 Action JSON 数据，不能访问授权/派发私钥、账库写权限、shell 或受信回调代码。CandidateIngress 解析成功只形成候选数据；受信宿主重建依据、取得必要批准并构成完整链，再进入 CommonW.prepare。读取授权先于敏感来源读取及候选资料提供。

受控初始化辅助器生成各角色真实签名，用于模拟 U/V/H/G/X 职责，不代表已采集真人同意。真人批准内容与界面采集、外部会话、软件产品化由后续接入完成。Windows 同用户进程分离及 chmod 不作为 OS 文件访问隔离证据；能力与签署契约见[安全边界](security-boundaries.md)。

消息的 protected.proto 固定为 `ZJJ-CORE-COMP-1`，字段基础版本为 `2.6`，原签名域、AH/Ref 域保留。此标识被签名覆盖，接收器不与原 R2 `ZJJ-AAP` 消息混用。说明版本 `CORE-SPEC-1.3` 是文档层次整理，未生成新的 wire 版本。旧运行不自动换标识、补时间、清账或重授权；保留原构建恢复身份。精确对应见[R2 与应用对照](r2-application-mapping.md)。

## 2. 三个 Profile 的业务规则

| 接线项 | 工业 IND-DEMO-1 | 付款 PAY-1 | 医疗 MED-DEMO-1 |
|---|---|---|---|
| scope | lab / tenant-1 / industrial | lab / tenant-1 / payment | lab / tenant-1 / medical |
| 认证来源 | C 的任务、工件/包/当前 UNIT、策略和资格；E 的 IND_EVIDENCE 认证 | C 的 PAY_TASK、ORDER、PAY_HISTORY、策略和资格；原 v2.5 Evidence 桥接至 PAY_EVIDENCE | C 的任务、患者/就诊/当前 ENCOUNTER、策略和资格；E 的 MED_EVIDENCE 认证 |
| 动作绑定 | line/station、unit/batch、cycle/phase、route、工具/目的地 | order/stage、payer/payee、amount_minor/currency/purpose、工具/目的地 | patient/encounter/order_group、phase、record_ref/template、工具/目的地 |
| U / 必要 V | LINE_OPERATOR 的 EXECUTE；INSPECT 要 QUALITY_REVIEWER 的 QUALITY_REVIEW | FINANCE 的 EXECUTE；FLAG 要 ANOMALY，INSUFFICIENT 要 LOW_EVIDENCE，CLEAR 无必要 V | MEDICAL_AUTHORIZER 的 EXECUTE；CLINICAL_REVIEWER 的 CLINICAL_REVIEW 始终必要 |
| 独立业务推导 | DEMO_NORMAL→RELEASE、DEMO_DEFECT→QUARANTINE、DEMO_UNCERTAIN→INSPECT | 认证订单条件、当前历史分区与 history-int-v2 风险/必要用途推导 | DEMO_A→DEMO-ORDER-A、DEMO_B→DEMO-ORDER-B，med-fixed-v1；患者与就诊范围同时成立 |
| 稳定业务意图 | 完整 scope / line / unit / cycle / phase | 完整 scope / order / stage | 完整 scope / patient / encounter / order_group / phase |
| 接受约束 | UNIT=READY，处理容量、累计次数及 TaskFlight；同步转 ACCEPTED | 订单阶段与账户/额度一致，金额最小单位预算、累计次数及 TaskFlight；原单槽在途为 1 | ENCOUNTER=READY，患者/就诊/资料精确关联，医嘱容量、累计次数及 TaskFlight；同步转 ACCEPTED |
| 模拟工具与成功终态 | line-sort-sim；RELEASED / QUARANTINED / AWAITING_REINSPECT | pay-sim；一次 payments 效果和资源 spent | med-order-sim；一次 orders 效果，ENCOUNTER=REGISTERED |
| 详细开发交接 | [工业](industrial-handoff.md) | [付款](payment-handoff.md) | [医疗](medical-handoff.md) |

这些是受信端已登记、由当前适配器执行的具体规则。agent 不能自报新用途、依赖集合、意图键或资源单位来替换它们。共同协议的抽象表述不改变这些规则，也不增加动态 Profile 或任意工具接入能力。

## 3. 共同执行流程与具体承载

1. 按固定 Profile 重取认证输入与当前资格，构造 Action、Basis、Assessment、必要 Review/Authorization、Permit、Challenge 和 CommitProof。应用 prepare 要求完整链，不是“先准备、之后随意补批准”。
2. CommonW 在同一接受事务核验完整链、否决、意图、资源及归属；COMMIT/消费/墓碑/预占/在途/冻结 Core 同时持久保存，再由 X 签原回执。
3. 当前 W 管理动态 Behavior 和工业/医疗业务行。重新构造请求须从 W 当前状态推导，C genesis 保持其锚定身份。新领取复验外部依赖，并核冻结后的自身变化和占用归属。
4. 新领取生成唯一 attempt；首次 EXEC 先记消费再调用工具。领取后效果 UNKNOWN 与 exec_consumed=False 可以同时成立，原首次资格仍需守卫。已消费或无法确认时，按当前权限查询原 attempt 并显式结算。
5. 成功结算一次转 spent 并释放在途。确定失效且未领取的合法取消可释放自己的占用，但不删除永久意图墓碑或累计次数。query 查不到保留未知；可信事实矛盾 HALTED，保留历史事实。

有限对象图的依赖集合精确比较；IND/MED 中不属于 wire Dep namespace 的来源、身份及包对象通过原认证内容和传递引用承载。输入七类签名消息统一声明完整推导 deps；冻结 Acceptance 的 body.deps 为空，接受时资格归档在 COMMIT.checked_deps/credential_witnesses。Review.aud 使用 H/G/X，U 的当前读取资格由守卫另核；角色资格按事件点检查，Basis 未预先缩至全部角色到期。这些与原 R2 的对应关系保留在[R2 对照](r2-application-mapping.md)，不能因正文抽取而改称完整 R2 语义符合。

nonce 为 30 秒、样本年龄上界为两秒、候选字节上限为 64 KiB；SQLite、事务、进程和部署参数属于当前实现。签署结束及最终守卫继续复核窗口，不通过延长有效期解决过期。具体签名域和参数查[签署入口](security-boundaries.md)、[内部接口](interface-reference.md)及[W 开发契约](../w-transaction-contract.md)。

## 4. 状态、查询和恢复展示

| 原应用字段/情况 | 开发解释 |
|---|---|
| receipt_state=PENDING | 已持久接受，原 Core 待签；不表示没有接受 |
| dispatch_state=PENDING / STARTED | 未领取 / 已领取；不同于原 R2 Result 的 PENDING（已登记未接受） |
| effect_state=NO_ATTEMPT / UNKNOWN | 无原尝试 / 效果未确认；UNKNOWN 本身不能决定 EXEC 是否已消费 |
| CANCELED / NO_EFFECT | 确定失效且领取前合法取消；不是工具 TOOL_FINAL |
| SETTLED / SUCCEEDED | 派发维度已结算 / 可信成功效果；按原 FinalFactID 一次更新 |
| FAILED_CONFIRMED | 权威无效果且无迟到效果的规则身份；当前正常工具只生成 SUCCEEDED，不将 query 查不到改标失败终局 |
| HALTED | 可信矛盾停止状态，可保留此前 SUCCEEDED 或结算；普通归属抛错不自动持久 HALTED |
| EFFECT_UNKNOWN 或调用级 UNKNOWN | 原工具/调用观测标签；不能替代认证 W 视图或推定可重派 |

本地 status/audit 认证固定 H 的当前读取资格，返回 APPLICATION_W_PROJECTION，不是正式签名 Result/AUDITBundle。原观察、首个验证理由与另行读取的视图分别保存；读取失败不改原事实。医疗资料前置 ACL 与裁剪候选数据，不使完整 H audit 变成普通 AUDITOR 的脱敏接口。完整口径见[查询审计](query-audit-scope.md)。

撤销保证采用新领取点边界：发送和模拟工具检查原派发绑定/签名/窗口，不重读全部业务撤销或 DENY。已领取后撤销仍可能产生原效果。业务级暂停、领取后即时撤销、取消后同意图重办不由当前方法自动提供；UNKNOWN 不超时释放、不自动补偿或重派。受信负责人按[处置权限](security-boundaries.md)调查和保全，不能清墓碑或强行修改结果。

## 5. 运行证据与能力等级

| 材料 | 实际支持与身份 |
|---|---|
| [原 W 主包](../../evidence/w-slice-20261011-final/report.json) | 22 个具名路径：三 Profile 正常、丢应答、未知查询、并发领取/结算、可信矛盾、W 提交后退出，另有工业四种竞争路径；按原 4202127 构建身份 |
| [跨 Profile 同 ID](../../evidence/w-same-oid-20261011/report.json) | 三个子例，独立于原 22 例计数 |
| [选择拒绝与读取验证](../../evidence/protocol-handoff-20261011-final/report.json) | 六例，保持各自原构建与组件/共同入口身份 |
| [新标识正常与恢复](../../evidence/security-rectification-20261012/w-slice/report.json) | 三场景各正常与丢应答恢复，6 条端到端路径；每条一次接受、attempt、观察发送、模拟效果及结算；原 attempt 恢复不新增效果 |
| [整改验证总表](../../evidence/security-rectification-20261012/validation-summary.json) | 137 项回归、13 项选择验证、72 次认证读取，均为 1.2 代码整改当时的结果，本次文档整理不计为新执行 |
| [声明与证据](claims-evidence.md) | 分别标注规则已定义、组件已验证、端到端已运行；引用原包与独立核验 |

工业主展示为 INITIAL/uncertain→INSPECT→AWAITING_REINSPECT，不自动推进二阶段复检；复检前驱、来源和批准按原合同定义保留。长期工具换钥与正式签名 STATUS/AUDIT 保留定义身份，不由同钥查询或应用投影替代。原 39 项、21 组及历史研究材料按各自来源阅读；软件界面和安装包交由后续开发。

本次只调整文档分层；先保留上轮未提交构建所绑定的全部源码/文档副本，再修改当前说明。旧运行包、清单及核验报告不重写；核验完整源码身份时使用其原提交或归档构建副本，不能用当前 1.3 文档冒充原 1.2 输入。迁移与验证结果见[分层记录](protocol-separation-record-20261012.md)。
