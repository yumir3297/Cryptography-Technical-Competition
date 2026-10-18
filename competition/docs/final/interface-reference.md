# 当前内部接口与返回值对照

2026-10-12 · 配套 `CORE-SPEC-1.3`；核对源码 `1aa5a9e36e1558b95972941d5ce7dbf6553da431`，对象为 [CommonW](../../core/common_w.py)。既有接口证据仍按原 `4202127` 构建身份引用。这是受信内部 Python 调用参考，供比赛开发接线；外部会话、HTTP 和应用包装由调用入口提供；候选 Action 已有独立严格字节入口，完整链仍由受信接线构造。

旧[应用契约](../application-contract.md)包含目标伪代码，旧[公共 W 契约](../w-transaction-contract.md)含职责参数简称；两者保留证据绑定原字节。当前函数名、参数、返回值及重试以本页为准。函数调用、应用签名挑战与原 R2 核心消息是三个层次，不互相替代。

候选解析与签署调用、精确 caller proof 字段及身份边界见[新增入口契约](security-boundaries.md)。WRun.fork_operation 从共同 W 当前状态重建依据，保留来源截止/到期，不再读取旧 C genesis 作为动态业务事实。

共同协议的抽象状态按本页字段接线；三个 Profile 的规则和演示配置见[开发总交接](scenario-integration-handoff.md)。本次正文分层不改变下列函数、参数或返回值。

## 1. 实际函数签名

以下省略实例方法的 `self`，其余名称与源码一致。可按位置传参；按关键字调用时只能使用真实参数名。

```python
prepare(p, op, identity)
accept(p, ticket, proof, *, crash_after_commit=False)
claim(p, oid, proof)
execute_once(p, oid, proof)
query_attempt(p, oid, proof)
settle(p, oid, response, proof)
status(p, oid, proof)
audit(p, oid, proof)

challenge_accept(p, ticket)
challenge_worker(p, oid, purpose)
challenge_read(p, oid, purpose='STATUS')
cancel(p, oid, proof)
complete_receipt(p, oid)  # 受信内部恢复
```

| 参数 | 实际含义 |
|---|---|
| p | 固定 Profile 字符串，完整 scope 来自受信 registry；不是 scope 对象或 UI tab 名 |
| op | 已构成的操作 dict，含 action/task_id/scene_key/ctx/basis/assessment/required/deps/reviews/authorization/issue/permit/challenge_request/challenge/proof；场景事实及完整签名链须一致。不是原始 JSON bytes 或仅有 Action 的请求 |
| identity | H 的应用身份凭据 `{claim, signature}`，用于 prepare；不是原 CommitProof |
| ticket | prepare 返回对象中的 `ticket_id` 字符串，不能传整个 ticket dict |
| oid | 原 Action.operation_id；提交前调用者须保留 p/oid 和原 op，才能处理提交应答未知 |
| proof | 对当前步骤应用挑战的 `{claim, signature}`；按下表选 H 或 worker，不能自报角色或公钥 |
| response | execute/query 的完整响应 dict；有终局时须含 `record` 和签名 `checkpoint`，不能只传 TOOL_FINAL 或其原 bytes |

`crash_after_commit` 是受信测试故障开关，不属于客户端输入。初始化、登记、complete_receipt、counts/snapshot 也不能直接暴露为免认证外部路由；当前内部方法不构成已经完成的公开服务接口。

## 2. 挑战与认证责任

| 方法 | 挑战来源 / 签署者 / 签名域 |
|---|---|
| prepare | TrustedState.challenge(p, op, stage='GUARD') / H / COMP-APP-AUTHZ-IDENTITY-v1 |
| accept | challenge_accept(p, ticket_id) / H / COMP-APP-ACCEPT-v1 |
| claim、execute_once、query_attempt、settle、cancel | challenge_worker(p, oid, purpose)，purpose 分别为 CLAIM/EXECUTE/QUERY/SETTLE/CANCEL / worker / COMP-W-WORKER-v1 |
| status、audit | challenge_read(p, oid, purpose)，purpose 分别为 STATUS/AUDIT / H / COMP-W-READ-v1 |

signature 是对 `canonical([domain, claim])` 的 Ed25519 签名，以 64 字节无填充 base64url 表示。挑战 claim 是应用 dict，不是原 R2 Challenge Envelope。挑战生成不等于请求者已证明持钥；消费方法核签名、用途、范围、原操作/COMMIT 或 ticket 绑定、当前资格和一次性 nonce。外部入口应先认证调用会话，不能把当前 H 的预检查当成任意调用者已认证。

worker 证书用途中虽有 AUDIT，当前 `CommonW.audit` 仍要求 H 的读取凭据。worker 的 AUDIT 签名不会变成 H 读取权。当前 status/audit 核固定 H 的 KEY/业务角色/读取角色或 PAY READ 用途、POLICY ACL/窗口和被冻结 Action 的业务范围；它们不另重验当前 TASK 委托与 Task 窗口，不等同于原 R2 完整的当前 Task 委托查询。

## 3. 返回结构与推进边界

| 方法 | 实际返回 / 含义 |
|---|---|
| prepare | `{profile, scope, operation_id, ticket_id, request_ref, time_witness, expires}`；只创建非授权凭据，要求已有完整批准链。重复 prepare 可创建新 ticket |
| accept、cancel、complete_receipt | 接受视图：`{profile, operation_id, acceptance_state, dispatch_state, effect_state, acceptance, receipt_state}`。接受已提交时 acceptance_state=COMMITTED；acceptance 为原签名回执或 None，receipt_state=SIGNED/PENDING。None 表示待签，不表示没有接受 |
| claim | `{profile, operation_id, attempt_id, dispatch_state}`；新领取才生成 attempt。已有 attempt 时返回原 outbox 状态，可能仍为 STARTED，即使操作已经 SETTLED/HALTED；它不是新执行许可或完整当前状态 |
| execute_once、query_attempt | 工具响应 dict（含 SUCCEEDED / EFFECT_UNKNOWN 等标签）或调用级 UNKNOWN；可能包含 record/checkpoint/time_witness/before/after/trace/reason/validation_error，分支字段不统一。保存观测不等于结算 |
| settle | 成功或已有事实：state=SETTLED、operation_id、final_fact_id、existing；可信矛盾/已停止：state=HALTED；无终局且未结算：state=UNKNOWN、reservation_retained=True。应逐分支读字段，不假定总有同一组字段 |
| status | 上述接受视图＋attempt_id、exec_consumed、queries、original_envelope=False、view_kind=APPLICATION_W_PROJECTION；只有已提交操作可读，没有未接受操作的 NONE 视图 |
| audit | status 字段＋commit、time_witness 和已保存 evidence；当前是 H 权限下的本地投影，不是 AUDITBundle 或独立导出器 |

当前各方法没有统一 `{decision, status_seq, checks, provenance, ...}` Outcome，也没有完整 StateView 序列化。不要从历史目标结构中读取当前不存在的键。

工具响应 `state=SUCCEEDED` 是返回载荷的标签。若含 validation_error，不能据该载荷确认效果或结算；没有 validation_error 也不能单凭标签或字段缺失推断证明已验证。可信矛盾可以持久写 HALTED 而保留原工具载荷。settle 成功表示该调用时点已有结算事实；若要描述当前操作，应另取认证 status。读取不可获取时，保留原调用事实并标记当前视图不可获取，不能将原成功改成失败。

对 settle：裸 TOOL_FINAL dict 没有 `response.record`，当前会走 UNKNOWN 分支；`{'record': TOOL_FINAL}` 缺 checkpoint 则拒绝 LEDGER_CHECKPOINT_UNKNOWN。两者都不结算，但返回语义不同。调用方须传原完整响应，不能把任意 dict 或 bytes 自动解释为可验工具证明。

## 4. 幂等、状态和错误

- **新挑战与幂等是两件事。** 已成功消费的同一应用 proof 再用会 REPLAY。恢复/重复调用要新挑战和新 proof；不会因此新增接受、attempt、效果或结算。
- **原请求不能重构。** 已提交操作按原 op 的整体 request_ref 匹配。重试时保留原 op；只保持 Action 相同而重签批准/Permit/Proof，仍可能 ID_CONFLICT。同意图的其他 operation_id 也不能重新接受。
- **回执恢复是有状态动作。** accept 在持久提交后内部调用 complete_receipt；同原请求经当前 H 认证后可取原事实或补原 Core。status/audit 本身不补签。保存的原回执不刷新 kid/iat/exp。
- **重复 claim 不重验成新的派发权。** 返回原 attempt/outbox 只作历史领取信息；后续执行仍由 execute_once 的守卫和一次标记决定，当前终态看 status。
- **UNKNOWN 不等于 EXEC 已消费。** 新领取即可 effect_state=UNKNOWN，而 exec_consumed=False。原首次 execute_once 仍须通过其守卫；exec_consumed=True 后只可按可用权限查询恢复，不能重复执行。消费情况无法确认时先认证读取原操作，不能猜测 False；原首次资格和重新授予资格是两件事。
- **重复 settle 仍有输入条件。** 有 record 的分支先核当前工具认证、证明窗口与绑定，再判断是否已结算；旧证明过期可能被拒绝，应 query 原 attempt 取得新认证。无 record 的分支可返回已存结算事实；它不新增结算。
- **内部状态有多个维度。** 原 PENDING 可表示待派发，receipt PENDING 表示待签；effects 使用 NO_ATTEMPT/UNKNOWN/SUCCEEDED/FAILED_CONFIRMED/NO_EFFECT。CANCELED、SETTLED、HALTED 是操作行状态；不能把同名值跨维度套用，也不能直接充当 R2 枚举。
- **异常不等于状态转移。** FLIGHT_OWNERSHIP/RESERVATION_OWNERSHIP 等当前抛错并阻断，未自动持久写 HALTED；例如 Flight 缺失时 status 仍可 PENDING。应显示本次守卫失败并保留占用/调查，不宣称 W 已停止到 HALTED。可信工具事实矛盾才有当前已实现的持久 HALTED 分支。
- **没有统一公开错误响应。** 常见业务拒绝为 ProtocolError；若给内部方法错误类型或缺字段，也可能 TypeError/KeyError/AttributeError 或校验异常。外部适配先验证输入，区分拒绝、未知和基础设施失败；未知异常尤其发生在接受返回阶段时，不得推断 W 未提交。
- **counts 是全 W 汇总。** 它不按当前 Profile/单操作过滤，也没有调用者认证，不能直接作为某张场景卡片的操作计数或公共查询接口。单操作事实按 p/oid 和相应账记录核对。

API 中 attempt_id 是 W 在 claim 生成的工具派发尝试，对应 TOOL_FINAL.dispatch_attempt；原 ChallengeRequest/CommitProof.payload.attempt_id 是提交请求关联 ID。它们由不同步骤产生，不因名称相似而替换或推导。调用方不指定新的工具 attempt。

## 5. 阶段、结果与术语接线约定

下面说明实际阶段守卫及开发接线约定；不修改函数返回结构、Schema、R2 枚举或签名域。

| 阶段 | 判断/读取依据与可形成事实 | 对应协议规则 |
|---|---|---|
| prepare | H 认证与完整链守卫；产生 ticket，不接受或占用 | 共同协议第 3、4 节 |
| accept | 当前链、完整否决、唯一性和资源；持久接受后尝试签回执 | 第 3、4 节 |
| complete_receipt | 原冻结 Core、X 当前资格及窗口；保存原回执 | 第 4 节 |
| 新 claim | worker 认证、当前依赖/资格/否决及归属；唯一 attempt | 第 5 节；重复 claim 只取原 outbox |
| 首次 execute_once | worker、原派发/工具/窗口及 EXEC 标记；先耗资格，再发送 | 第 5 节；不新增业务撤销复验 |
| query_attempt | worker、原 attempt、工具当前认证及查询窗口；读取/认证原工具事实 | 第 5、6 节；操作/工具已停止时不保证查询可用 |
| settle | worker、原终局及连续性；首次结算再核占用，按 FinalFactID 一次更新 | 第 6 节；已有事实/未知/停止分别返回 |
| status / audit | 当前 H 读取权；读取同一 W 快照，消费读取 nonce，不推进业务 | 第 7 节及查询审计口径 |

**三个项目分开表达。** 原调用观测保留原对象；本次验证只说明明确报告的验证结果或首个阻断原因，未报告不能写成“全部检查已通过”；操作视图由另一次受信本地认证读取取得。要说明调用后的操作状态，应在该调用后读取，核返回的 profile/operation_id；scope 与 COMMIT 绑定由固定 registry、读取挑战及 W 的凭据核验保证，不能读取投影中不存在的 scope/commit_ref 字段。先前保存的视图只能标为历史，不把不同次读取拼成一个原子结果。

包装本身不验任意字典、不签协议响应、不冒用 H 读权、不自动调用工具 query 或 settle。若没有当前读取权限，写“当前视图不可获取”，保留已有接受、结算和原调用记录。当前投影没有 status_seq 或签名观察时间；调用方可记录本地读取时点，但不能冒充 X 签名的新鲜度证据。内部 API 返回 dict，本地对象保持相同不等于已保留原始网络字节。

| 用语或值 | 所属对象与含义 |
|---|---|
| NO_ATTEMPT | W.effect_state：尚未领取；不是工具的确认失败终局 |
| UNKNOWN | W.effect_state：无可信终局；或某次调用的 state：该次调用未给出确认结果。必须附字段/阶段 |
| EFFECT_UNKNOWN | 模拟工具调用的 state 标签；与 W.effect_state=UNKNOWN 分开 |
| SUCCEEDED / FAILED_CONFIRMED | 经 W 验证的效果值；固定模拟工具实际成功分支产生 SUCCEEDED，不能声称已演示全部失败终局 |
| NO_EFFECT | W 确认未领取操作合法取消后的效果值；不伪装为 TOOL_FINAL |
| PENDING / STARTED / CANCELED / SETTLED / HALTED | W.dispatch_state；receipt_state=PENDING 另表示回执待签。HALTED 可能保留历史效果/结算，不自动回滚它们 |
| 不可获取、原因分类、首个阻断原因 | 应用说明语义，当前没有对应统一返回字段；不是 R2 状态/原因码，不增加执行权 |

**原因须带阶段。** 开发可区分输入无效、明确条件不满足、权威依据未知、调用提交结果未知、工具效果未知、内部完整性异常及尚未分类。SIGNATURE_ENCODING/BAD_SIGNATURE、REVIEW_REQUIRED/REVOKED、DENY_COVERAGE_UNKNOWN/CLOCK_UNKNOWN、FLIGHT_OWNERSHIP 是所选实例，不是完整错误码枚举。TimeoutError 在 prepare 的检查阶段、accept 返回阶段和工具执行阶段含义不同；发生位置未知就保持未分类，先核原事实。任何分类都不自动释放资源、重派或持久停止；工具证明无效时也可能已经产生效果。

**诊断与停止分开。** 可在已认证且可信复核之后记录阶段、原请求/COMMIT 绑定、适用规则、首个原因和证据引用，不复制患者/付款原始输入或私钥。未经认证的错误不能触发可信操作停止。诊断记录不证明未接受，也不被当前 W 当作永久阻断；若增加持久停止，须定义提交成功后才报告停止、覆盖所有派发入口及恢复路径，不能同事务写 HALTED 后抛异常而依赖会回滚的记录。本轮只冻结接线约定，不交付诊断/包装服务。

## 6. 实测与资料身份

[七项接口验证](../../evidence/interface-review-20261011/report.json)含一项函数签名核对和六项实际行为检查：无效工具证明的成功标签、裸 Record/缺 checkpoint 的 settle 分支、已结算后的原 outbox 领取信息、H/worker 审计认证区分及归属异常不自动 HALTED。控制输入篡改和 Flight 扰动均标明为测试，不作为远程攻击已经成立的证明。验证脚本见[verify-interface-semantics](verify-interface-semantics.py)，文档及副本核对见[本轮记录](../../evidence/interface-review-document-check.json)。

本次纠正说明和当前调用约定，不改原运行代码及消息字节；[R2 对照](r2-application-mapping.md)继续区分协议定义与已实现行为，泛化条件见[开发注释](developer-scope-notes.md)。

仓库整理说明：支持模块导入路径已迁移，既有检查按其原构建身份阅读；当前目录与新增验证见[整理记录](../../../REPOSITORY_SCOPE.md)。

2026-10-12 的选定实验和本轮规范检查见[协议优化复检](optimization-review-20261012.md)。发布材料只引用比赛接线所需事实摘要；完整探索脚本、候选和模型保留本地，候选通过不等于已接入 CommonW。
