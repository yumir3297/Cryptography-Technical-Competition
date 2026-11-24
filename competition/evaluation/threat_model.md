# 威胁模型与信任边界

## 1. 受信组件（本作品明确依赖）

| 组件 | 受信内容 | 现实边界 |
|---|---|---|
| C 根 | 发布 Policy/Task/Key/Role/Goal/Tool/Resource/Incident 的根签名 | 当前是本地受控初始化器/`C.key`，不是独立治理、HSM 或多人门限 |
| W | 资源账、意图表、行为/场景 after、受理序号、COMMIT、结算 | 单机 SQLite；假设 W 不伪造自己的账；没有多机共识 |
| X | 对冻结 Acceptance core 的签名 | 本地子进程；不是独立执行机构 |
| 工具/效果端 | 工具终局记录、检查点、模拟效果 | 模拟器；不是真实支付/工业/医疗/隔离设备 |
| C 时间源 | 事件时间采样 `lo/hi`、单调年龄 | 本地受信时钟；不是外部可信时间戳/原子钟 |
| worker 授权 | W worker 的 `CLAIM/EXECUTE/QUERY/SETTLE` 等用途 | C 根签发；worker 与 W 同机 |
| delivery 密钥 | W 到工具的执行/查询包 | 与 worker 授权密钥分离；仍由 W 持有 |

## 2. 攻击者能力（本作品覆盖）

1. **恶意/错误 Agent**：可构造任意 Action、payload、自报金额/成本/依赖/角色/Goal 字段；没有协议签名密钥。
2. **网络/消息重放者**：可重放旧消息、旧 acceptance、旧 attempt、旧 receipt、旧 final fact；可替换 `operation_id/attempt_id/commit_ref`。
3. **合法密钥但错误内容**：攻击者持有某角色合法密钥，但签署不属于自己的 scope/profile/action/成本；或把 A 的签名拼到 B 的对象。
4. **状态版本攻击**：使用旧 Task/Policy/Goal/Incident/Resource 记录；在 prepare 与 accept 之间改变 C 记录；A-B-A revision 回放。
5. **并发攻击**：多个 Agent 同时申请同一资源/意图/obligation，利用旧读状态造成双重接受。
6. **故障注入**：在持久化边界杀进程；工具已执行但应答丢失；结算已提交但客户端未收到成功；重复调用 claim/execute/settle。
7. **离线证据篡改**：修改证据包中的 payload、hash、ref、签名、容量、成本、attempt、final fact、FinalFactID、版本/epoch。

## 3. 攻击者能力（本作品不覆盖/不声称）

- 攻破 C 根、W 主机、X 主机、工具主机或时间源；窃取私钥后以合法身份签署全新对象。
- 完全回滚 W/工具 SQLite 到旧快照并伪造高水位/head；当前只有高水位/head 矛盾检测，不构成防回滚证明。
- 跨机网络分区、拜占庭 W、分布式共识、真实支付清算、真实医疗/工业设备安全。
- 真人授权/同意的法律效力；H 的签名只证明持有 C 登记密钥。
- 动态组织治理、密钥轮换后的全历史撤销传播、长期审计日志不可删除。
- 物理世界“恰好一次”；协议只提供“工具调用资格最多一次 + 原 attempt 查询/恢复”。

## 4. 关键攻击面与现有防线

| 攻击面 | 防线 | 证据 |
|---|---|---|
| Agent 自报成本/容量 | W 用 `plans.plan` 的 `amount`；C GoalFloor 的 `cost` 必须精确相等；容量来自 W 资源行 | `GOAL_COST_MISMATCH`、`GOAL_CAPACITY_MISMATCH` 测试 |
| Agent 删除/替换 Goal 引用 | 请求中没有 Goal 选择字段；W 用 Action selector 匹配 C GoalFloor 规则 | `action_selector`、`test_goal_floor` |
| 旧 Goal 继续生效 | C 发布 revision/epoch；W 读 `a_current`；deps 逐项 revision/ref 比较 | `GOAL_DEPS_STALE`、`test_goal_epoch_update...` |
| 多 Agent 双重接受 | `BEGIN IMMEDIATE`、`w_intent`、资源预留、`w_goal` obligation | 并发实验、`test_w_acceptance_races` |
| 接受后替换 Action | `ctx.action_hash`、`frozen`、X 签名 `commit_record_ref` | 15 项篡改测试 |
| 工具结果替换/重放 | attempt 绑定、action_hash、ledger、tool、destination、checkpoint request_hash、final_fact_id | `test_evidence_verifier` |
| 重复结算 | `w_settlement` 主键/唯一约束、`_verify_final` 矛盾检测 | 崩溃测试、`test_w_final_regressions` |
| UNKNOWN 误当失败 | `exec_marker` 保留、`settle` 无 record 返回 retained、查询原 attempt | `unknown_query`、`test_exec_marker_crash...` |
| 拒绝产生副作用 | 所有检查/插入同一事务 | `test_enforce_rejects_without_business_side_effect` |

## 5. 离线证据的可证明范围

**可证明（给定固定信任根和公开算法）**
- 某条消息/记录确实由某公钥对应私钥签署；
- 对象内容与 hash/ref 一致；
- COMMIT 引用的 Action/Basis/Permit/Proof/Auth 与 Acceptance 的 `commit_record_ref` 一致；
- 工具终局记录与 attempt/action/ledger 一致，FinalFactID 可重算；
- GoalFloor 的 `state_ref`/`check_ref` 可由证据包中的资源/状态快照重算并匹配；
- 同一 attempt 只有一个 W 执行包，settlement 只出现一次。

**不能证明**
- W 账本 `spent/reserved` 在现实中没有被 W 伪造；
- 证据是“当前”的（离线时间只验证 iat/exp 内部顺序）；
- 工具真的影响了物理世界；
- 没有出现在证据包中的历史没有被隐藏；
- C 根/角色密钥没有被攻破。

## 6. 结论口径

本作品的安全主张应写成：
> 在 C/W/X/工具/时间源受信且其密钥未泄露的前提下，ZJJ-CORE 对每个被接受的动作提供可离线复验的授权链、唯一执行资格、工具终局绑定和一次结算；GoalFloor 在此基础上增加一个 C 认证的必要资源下界，防止局部合法动作挤占必要目标资源。

不应写成：
> 协议保证 Agent 一定完成目标、保证物理世界恰好执行一次、保证生产支付/医疗/工业安全，或保证 39 项正式验收全部通过。
