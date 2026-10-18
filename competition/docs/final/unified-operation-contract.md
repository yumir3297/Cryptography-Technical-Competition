# 统一操作生命周期：最小服务契约

本实现以 PR #3 为主线。仅 IND-DEMO-1 接入简化提案与新的受控服务；PAY/MED 保留完整 Action 的既有内部组件流程。通用核心不依赖 Agent、HTTP 或 MCP。真实身份提供者、实体设备和多机部署不在本竞赛原型的已验证范围。

## 1. P2：如何解决与影响

一个 app_request 表保存请求键、W 事务分配的 B16、原构造、当前完整 op、request_ref、submission_version 和历史短期标识。原 a_journal 保存每版完整提交及外层身份验证的最终时间见证。没有第二套分配账，也没有提前强制同 intent 只能有一个草稿。

同请求键保持原映射；不同请求键可以构造不同草稿，但 W 的 w_intent 唯一接受规则继续防止重复接受。分配器仍同时检查 app_request 和既有 w_operation，最多尝试 8 次。旧 V1 已保存行可从原内容和 request_ref 迁移为版本 1；不补造历史分配来源，不重置 W 或工具账。

首次完整链验证通过后，固定 Action、Task/scene、Assessment、Basis、ctx、deps、required、reviews、Authorization、IssueRequest 和 Permit。只有 challenge_request、challenge、proof 可以在接受前替换。新三件套仍由真实 H/X 签署，使用原签名域及引用格式；消息 ID、session、nonce 和 CommitProof 提交 attempt 必须未在该请求历史中使用。提交 attempt 与后续工具派发 attempt 是不同标识。

替换提供预期版本和 request_ref，在同一 BEGIN IMMEDIATE 事务中验证：尚未接受、固定部分相等、版本未变化、无历史回退、完整签名链/DENY/来源/当前资格有效、原有效期及最终刷新窗口有效。外部提交的 H 身份 nonce 也在最终保存关口重新检查，失败连同版本、日志和 nonce 消费一起回滚。相同已提交转换可幂等确认，不产生新版本；确认保存成功不等于当前仍能被接受。

RequestBoundW 在原 prepare 和 accept 事务内检查该 ID 的登记及当前完整包。换包先落账则旧 ticket 返回 SUBMISSION_SUPERSEDED；接受先落账则换包返回 ALREADY_ACCEPTED。仅在编排器中先查询一次不能替代这两个检查点。

DENY 继续按 profile、operation_id、basis_ref 查询，并核对完整 ctx、目的集合、签名与发布日志。续签不能更改 Basis、初始化新的否决覆盖范围、清除 DENY 或以稍后的 APPROVE 覆盖 DENY。覆盖未知则阻断。DENY 发布、来源变更与接受使用同一数据库写事务序列；接受后的派发仍检查当前 DENY。

此 DENY 是该操作/依据/目的的否决，不是跨所有后续操作的全局业务封禁。需要重新审批时必须走受控的新审批流程；自动续签不得换 ID 或 Basis 绕开原否决。是否禁止某业务意图今后的所有草稿，属于另行明确的应用策略，不通过本轮偷偷增加 intent 分配唯一性实现。

短期三件套默认最多 30 秒，但不得越过原 Permit、IssueRequest、批准、Basis、Assessment、来源和资格窗口。V1 新构造的 Assessment 最长 90 秒且取来源窗口交集。更新证明不是重新授权，任何原依据或授权失效都停止自动续签，交由受控重新审批；本版本不实现重新批准或改变依据的自动路径。

## 2. P4：角色与信任边界

| 角色／组件 | 可以做什么 | 权限来源与限制 |
|---|---|---|
| Agent／Web／调用者 | 发起候选、转交已签署材料、调用公开挑战/提交/恢复接口 | 获得工具或 HTTP token 不等于 H 身份，不能自行生成批准或执行 |
| MCP Server／桥接进程 | 列出白名单工具并转发数据 | 本版本仅持传输 token，不持参与方私钥；MCP 不是协议必要依赖 |
| Resolver | 从固定 Task、Policy、KEY/ROLE、工具登记构造完整 Action 和未签署依据 | 公钥受信来源，不自动批准，不代签 |
| H | 认证提案、发起 IssueRequest、签短期请求/CommitProof、认证提交与读取 | 当前 Task 绑定的 holder/kid 与当前 KEY/HOLDER/READER 范围；不允许冒用 principal |
| U | 对既定 ctx 批准或否决 EXECUTE | 自己的当前角色与签名；不能静默修改 Action |
| V | 对 required 中的既定目的批准或否决 | 自己的当前角色与签名；不能静默修改 Action |
| G | 签署绑定原批准、ctx 和 deps 的单次 Permit | 不替代 U/V；本轮续签保留原 Permit |
| X | 签挑战，以及对 W 已提交原 Core 签接受回执 | 回执子进程读取已提交账，只签冻结 Core |
| W／受信宿主 | 受控分配、验证、事务接受、冻结事实与 outbox、保留恢复材料 | 整体进程/数据库属于信任边界；不声称防御宿主恶意改库 |
| 内部 worker | 取得原 worker 凭据后 claim、唯一 EXEC、查询、结算、重试原回执签署 | 独立 worker grant/nonce/目的绑定；不作为 Agent 工具暴露 |
| C／E／登记工具 | C 认证来源和资格；E 提供绑定证据；工具维护独立效果账 | 签名证明登记来源，不自动证明现实业务所有权；真实设备未接入 |

用户批准“调用某工具”和 U/V 的协议批准是两个不同层面。Agent 只有在受信 H 另行提供真实认证材料时才能提交。测试中的多方私钥和自动构造批准只存在于 tests/seed 夹具，不能部署为 Agent 自动签署端。

## 3. 公开接口

受信启动代码固定 profile、Task、Resolver、RequestStore 和 RequestBoundW。客户端不能选择 Task/profile、关闭检查或注入组件。OperationService 构造时拒绝不绑定同一 store/state 的 W。

HTTP：仅监听 127.0.0.1，短连接 POST /v1/operation，Content-Type: application/json，Authorization: Bearer <受信宿主生成的随机 token>。Host 必须为本机与实际端口；拒绝 Origin，拒绝重复 JSON 键、非法编码、非有限数字及超过 1 MiB 的请求。无浏览器跨域接口，无远程监听或生产 OAuth 声明。

请求恰为 {method, params}。下表是完整白名单，params 不接受额外字段。proof/identity/auth 为原签名对象，不接受角色名或“批准=true”代替。

| method | params 的精确字段 | 响应与认证 |
|---|---|---|
| propose | proposal, auth | 原 V1 H 提案认证；返回 key、完整 Action、未签署 approval_request 和来源引用 |
| identity_challenge | op | 原 GUARD 身份挑战，绑定完整 op 的 request_ref；不授予权限 |
| submit | key, op, identity, expected_version, expected_ref | H 对完整 op 的一次性 GUARD 证明；首次版本输入 "0" / ""；替换用已读版本与引用 |
| prepare | key, identity | 读取当前 op 后使用新的 GUARD 证明；返回原 W ticket |
| accept_challenge | ticket_id | 原 ticket 绑定的 H 挑战；不授予权限 |
| accept | ticket_id, proof | 原 H 接受证明；仅接受并尝试签原回执，不派发工具 |
| recover_challenge | key | 返回一次性读取挑战；不查询请求存在性，不返回保存材料 |
| recover | key, proof | 当前 H 身份与读取资格；返回原构造、当前完整提交、W 事实和原 attempt 投影 |
| status_challenge | operation_id | 原 W STATUS 读取挑战 |
| status | operation_id, proof | 原 W H 读取证明；返回原应用投影 |

submit 输出为 {op, request_ref, version}；version 是 JSON 整数，后续 expected_version 输入为十进制字符串。首次保存为 1；每次真正替换加 1；幂等确认不增加版本。H 身份签名绑定整个 op；版本/ref 是应用事务的并发前置条件，不改变核心消息 Schema。

recover 的 state：APPROVAL_PENDING 表示尚无完整包；NOT_ACCEPTED 表示已保存但 W 未接受；COMMITTED 表示 W 已接受。COMMITTED 下 receipt_state=PENDING 仍是已接受，不能显示为未提交；dispatch_state、effect_state、attempt_id、exec_consumed 取自原 W/outbox。

恢复认证域新增为应用域 ZJJ-APP-RECOVER-v1。H 签 canonical([domain, claim])；claim 恰含 profile、scope、task_id、key、purpose="RECOVER"、nonce、iat、exp。服务器保存并消费原挑战，核对当前 H 的 StatusQuery/HOLDER 与 READER/ACL，最终时间关口再次检查。不替换任何原协议签名域。

原 GUARD 认证为 COMP-APP-AUTHZ-IDENTITY-v1，claim 恰含 profile、scope、operation_id、request_ref、stage="GUARD"、nonce。accept 为 COMP-APP-ACCEPT-v1，claim 恰含 profile、scope、operation_id、ticket_id、nonce。status 沿用 COMP-W-READ-v1。所有签名均使用原 canonical 和 b64url 规则。

成功 HTTP 响应为 {ok:true,result:{...}}；失败为 {ok:false,error:{code,recovery}}，不返回内部异常堆栈。

| HTTP | 主要含义 | 处理 |
|---|---|---|
| 400 | 外壳、方法、长度、JSON 错误 | 修正请求；不推断业务已接受 |
| 403 | 传输认证／本机来源限制失败 | 修正传输配置；不等于取得 H 身份 |
| 409 | 版本冲突、旧包、已接受、请求内容冲突 | 认证恢复当前版本／W 状态，不盲目覆盖 |
| 422 | 原协议认证、签名、依据、DENY、过期等拒绝 | 保留原因；原授权失效则停止自动续签 |
| 503 | 时钟、签署端或状态暂不可确定 | 保留故障证据，可信条件恢复后先查询原状态 |

HTTP 超时、断连或 MCP TRANSPORT_UNKNOWN 不能证明未提交；先 recover，再决定下一步。503 也不是清除否决、重分配 ID 或再次 EXEC 的许可。

MCP 使用标准 stdio JSON-RPC 2.0，协商本实现支持的 2025-06-18，支持 initialize、notifications/initialized、ping、tools/list、tools/call。每行一条 UTF-8 JSON，只向 stdout 输出 MCP 消息。工具列表恰为上述十项，参数 Schema 禁止额外字段。工具业务错误返回 isError=true；JSON-RPC 语法/方法错误按协议错误返回。桥接进程通过受信启动参数取得本机 URL 和仅宿主可读的 token 文件，不接受工具参数改变目标。

HTTP 是独立 REST 接口，MCP 是 stdio→REST 桥接；没有把 REST 伪称为 MCP Streamable HTTP，也不宣称实现 SSE/会话流恢复。参考 [MCP stdio 规范](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports) 和 [工具接口规范](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)。

## 4. 必要时序与恢复

1. H 认证 proposal → Resolver 事务分配 ID 并返回固定动作与未签署材料。
2. U/V 决定批准或拒绝，H/G/X 各自签相应消息；改变动作须回到候选／受控重新审批，不能在审批端静默编辑。
3. H 对完整 op 取得 GUARD 挑战并签名 → submit 保存版本 1。
4. 若仅短期证明失效且原授权/来源仍有效：H/X 在事务外签新三件套 → 新 GUARD 证明 → submit(expected_version, expected_ref) 原子替换。旧 ticket 随即不能接受。
5. 新 GUARD 证明 → prepare → H 签 ticket 挑战 → accept。W COMMIT 先于回执签署和工具 I/O。
6. 内部 worker 持原 worker grant 调用 claim → execute_once → 验证工具独立终局 → settle。公开 accept 不自动获得 worker 权限。
7. 接受结果未知：recover 读取 W。已 COMMITTED 则恢复原接受；回执待签由内部宿主调用 complete_receipt，仍签原 Core，不重建动作或 COMMIT。
8. 工具效果未知：内部 worker 的 QUERY 凭据调用 query_attempt，查询原 outbox 的同一 attempt，再验证/结算。即使请求没有送达工具，已消费 EXEC-0 也不自动再发一次 EXEC；可能永久 UNKNOWN，保留资源和 flight。

最小受信启动接线：先恢复真实 TrustedState/CommonW 和持久目录，再构造 Resolver、RequestBoundW(core,resolver.requests)、OperationOrchestrator、OperationService，最后 create_server(service, transport_token)。不要在重启时 initialize/reset 旧账。可用 python -m competition.application.mcp_stdio --url http://127.0.0.1:<port> --token-file <0600文件> 启动桥接。

RequestStore 的 _insert/_freeze/_save/load/check、replace_pending 内部编排、原 CommonW、complete_receipt、签署代理、登记/发布接口及所有 worker 方法均不是公开 Agent 工具。公开层只有静态白名单；同进程恶意反射或管理员改库超出此单机受信原型边界。
