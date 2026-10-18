# 比赛查询与审计口径

2026-10-12 · 配套 `CORE-SPEC-1.3` [共同安全协议](competition-protocol.md)。展示采用认证本地查询＋固定运行包离线核验，适用于受信单机、固定登记范围及三个签名模拟工具。此组合用于选定展示路径，比赛材料不新增正式响应实现。

固定场景及展示结果见[开发总交接](scenario-integration-handoff.md)。本页是当前应用读取与证据核验的实现口径，协议正文只规定其安全原则。

## 四种对象分别说明

| 对象 | 实际保证 | 展示名称 |
|---|---|---|
| CommonW status / audit 返回值 | 读取前核当前 H 身份、业务读取范围、一次性签名挑战；在同一 W 事务读原操作；audit 附 COMMIT、接受时间见证及已存证据 | 认证本地状态 / 认证本地审计投影 |
| 比赛冻结 Acceptance / TOOL_FINAL | 对其原 Core/终局内容实际验签；冻结 Ref、AH、attempt、ledger 等可核对；回执的应用 deps 约定见协议对应表 | 原冻结签名回执 / 签名模拟终局 |
| 离线运行包与 verify_w_slice | 核固定 manifest、证据绑定源码、原消息/来源/C/工具/W 签名、Refs、独立效果账、资源/结算与计数 | 离线证据核验报告 |
| 正式 R2 STATUS / 独立 AUDITBundle | 按原精确合同形成和认证协议响应或审计证据对象 | 协议定义；当前展示采用上三行 |

十种核心 type 中有 StatusQuery 和 Result，没有第十一种 AUDIT 消息。正式 STATUS 要有原 STATUS 挑战、StatusQuery、X 当前签名 Result、绑定的 status_seq 及所需原 Acceptance 附件；请求重传只返回原响应，新鲜状态须新查询。独立 AUDITBundle 的协议证据要求不能用本地 audit 字典代替，也不在本轮发明新的消息格式。

## 本地查询的实现范围

实际接口以已提交操作为查询目标，签名挑战绑定 Profile、完整 scope、operation、purpose、COMMIT 和 nonce。当前读取资格及策略权限检查适用于 STATUS/AUDIT；无公钥、scope 或角色自报绕过。一次 nonce 消费后重用拒绝；撤销后即使预先签好的请求密码签名仍有效，也会因当前资格拒绝。

读取主体是固定 H；当前方法检查 H 的 KEY/业务角色及读取角色或 PAY READ 用途、POLICY ACL/窗口和原 Action 业务范围，不另检查当前 TASK 委托/窗口。当前不存在任意 auditor_ctx 或 signed_status_query_bytes 参数。真实签名及各分支字段见[接口对照](interface-reference.md)，不能将历史接口草图当作已实现的参数表。

返回 `view_kind=APPLICATION_W_PROJECTION`、`original_envelope=false`。实际投影含接受/回执、派发/效果、原 attempt、EXEC 消费和查询计数；audit 增加原 COMMIT 和已存证据。它的外层没有 X 的 R2 Result 签名，也没有完整 StateView 的 status_seq/观察新鲜度封装。读取守卫按本次受信事件检查；调用者依赖受信本地返回通道，不把保存的投影当作可离线认证的当前状态。

status/audit 不接受、预占、补签、领取、调用工具或结算。允许消耗读取 nonce 和更新时钟证据；“只读”指业务事实与执行计数不变。查询原工具 attempt 是单独受控恢复步骤；刷新状态不能隐式触发它或 settle。

投影只说明该次受信读取时点的操作。说明一次调用后的当前状态时另行读取，不能把调用前的视图覆盖到调用后，也不能从外部任意字典推导认证。读取失败或撤权时保留原调用/历史事实，标记当前视图不可获取；不宣称调用失败、未接受或未执行。投影无 status_seq；调用方记录的本地时点不构成正式签名新鲜度证据，多个快照不能拼成一个原子结果。

固定演示读取主体为当前 H。MED 来源/候选资料读取另有前置 ACL 和裁剪投影验证；完整 H audit 与只获脱敏状态的普通 AUDITOR 是不同权限。当前本地 audit 不作为面向普通 AUDITOR 的医疗裁剪接口。

## 只读观察面（外部程序展示流）

受信端另开一条**只读**观察面，供外部程序订阅"每一步"的推进；它不属于协议消息，也不是状态/审计投影的替代。

- **发布**：核心每个关键步骤在其**自身事务内**向独立表 `a_observe_event` 追加一条展示事件——事务提交才可见、回滚即消失，因此不谎报状态；入口层的候选提交、装配、挑战请求与签名往返作为 `source='ENTRY'` 的**非权威流程事件** best-effort 发布，明确标为 `flow=true`。核心 `a_journal` 不被改写，也不含观察事件的步骤名。
- **读取**：只读连接（URI `mode=ro` + `PRAGMA query_only`），只 `SELECT`；不写业务表、不消耗 nonce、不推进时钟、不触发 `status`/`audit` 或工具。读取本身不新增任何事实。
- **事件形状**：`{seq, kind, stage, source, profile, operation_id, lanes, trusted_time, refs, status_label, detail}`，统一标注 `view_kind=OBSERVATION_PROJECTION`、`original_envelope=false`、`signed=false`、`not_evidence=true`。不含业务 payload、患者/付款原始字段、nonce、session_id、签名或私钥；`seq` 为订阅游标。
- **路由**（`GET`，需专用 `observer` 会话侧）：`/api/observe/stream`（SSE，`id`/`data` 帧、空闲心跳）、`/api/observe/events`、`/api/observe/operations`、`/api/observe/operations/{oid}`。
- **边界**：观察面不授予任何执行权，不成为"第四条消息"，不签名，不作为证据对象；不能由观察事件推断尚未提交的决策。任一投影在导出前再过一遍禁导检查（`export.forbidden_secrets`），不通过则丢弃该条。

## 离线核验的信任与保证

验证者使用外部固定的 manifest 摘要，对既有证据文件及其原源码文件逐一核摘要，再核原签名、引用、动作和独立 W/工具账对应。外部 pin 应来自受信交接记录；本次两个值如下，包内自附公钥/manifest 仅能证明内部一致性，不能自行建立权威身份。

| 原运行包 | 外部固定 manifest SHA-256 |
|---|---|
| [共同 W 22 例](../../evidence/w-slice-20261011-final/manifest.json) | `65ee659c9636cf41e2de8647b5c49005d762cdf3074bc2e65ac6579952df0eda` |
| [跨 Profile 同 ID 3 例](../../evidence/w-same-oid-20261011/manifest.json) | `ab853d979c9853a966c7f771070115b82ab3dd62f4e8507168ba49f5110eb640` |

本轮重核分别为 5168 项/3498 次验签/1538 个 C 时间包、849 项/585 次验签/246 个 C 时间包。计数是历史证据核对量，不是新执行。核验依赖受信导出和固定运行根，不能重新建立今天的执行授权、证明包外未登记历史或恶意整盘回退后的完整性。原工具 checkpoint 能验证代表性账连续关系，同钥再次认证不等于已演示长期换钥。

## 统一文书与展示措辞

“状态查询通过当前身份和读取权限认证，返回同一 W 快照的应用投影；独立核验器依据固定运行摘要核验原签名、动作引用及 W 与模拟工具账的一致性。执行资格已消费或消费情况无法确认时，恢复只按可用权限查询原 attempt，不重新授予执行权。”

待签时展示“已持久接受，原回执待签”；新领取且 EXEC 未消费时展示“效果未确认，原首次执行仍须通过守卫”；EXEC 已消费或消费情况无法确认时展示“效果未知，保留未决占用，不重复执行”；HALTED 时展示“可信事实矛盾，停止自动推进，保留历史事实”。只在原 attempt 存在且相应守卫允许时查询工具；HALTED 不承诺工具查询仍可用。未经外层签名的投影标识保持可见；原因分类与原错误码分别说明，不填进原 R2 原因码白名单。

复现命令、当前核验报告和六例展示验证见[交付记录](finalization-record.md)。

开发旁注：这里的独立核验器与被核验执行代码分开运行，但身份根和账的完整性仍依赖受信初始化/导出及外部 pin。比赛暂不增加外部防回退或长期签名观察设施，实际条件见[开发注释 N-06](developer-scope-notes.md)。
