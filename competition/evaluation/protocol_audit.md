# 协议链审计：真实代码路径与字段对应

审计对象：`integration/goalcommit-shadow-20261123`，基线 `7604d6b5b902f38d950234dec53d9375429f1e7f`。以下路径均来自当前源码，不采用历史文档伪代码。

## 1. 生命周期与代码入口

| # | 阶段 | 真实入口/函数 | 产生的事实 | 持有的密钥 | 关键对象 |
|---|---|---|---|---|---|
| 1 | Agent Candidate | `competition/core/candidate_ingress.py::CandidateIngress.parse`；`competition/profiles/authorization_seed.py` 组装 | 不可信 Action、评估/来源输入 | Agent 无协议密钥 | Action |
| 2 | Resolver/Basis/Assessment | `competition/core/authorization.py::CommonGuard._verify`；`competition/profiles/authorization_scene.py::bound_scene` | 当前 Policy/Task/Evidence/Identity 派生、Basis、Assessment | H 的候选身份密钥（C 登记） | `Record_BASIS`、`Record_ASSESSMENT`、`ctx` |
| 3 | C/E/H/U/V/G 认证 | `competition/core/trusted_state.py::publish/credential/message`；`competition/profiles/authorization_seed.py::sign` | C 登记记录、E 来源、H/ G/ U/ V 签名消息 | C 根、E/G/U/V/H 角色密钥 | `KEY_GRANT`、`ROLE_GRANT`、`POLICY`、`TASK`、`Review`、`Authorization`、`IssueRequest`、`Permit`、`ChallengeRequest`、`Challenge`、`CommitProof` |
| 4 | W 原子接受 | `competition/core/common_w.py::CommonW.accept` | 受理序号、意图、资源预留、行为/场景 after、COMMIT | W delivery 密钥（仅工具包） | `COMMIT`、`w_operation`、`w_intent`、`w_reservation`、`w_flight`、`w_outbox` |
| 5 | COMMIT/RecordRef | `competition/support/wire.py::rec_ref` | COMMIT 摘要 | 无独立签名；由 X Acceptance 引用 | `commit_record_ref` |
| 6 | X Acceptance | `CommonW.complete_receipt`；`competition/core/common_receipt.py::CommonReceiptSigner.sign` | X 签名的冻结 Acceptance | X 密钥 | `Acceptance`、`acceptance_core` |
| 7 | 唯一 Attempt / EXEC-0 | `CommonW.challenge_worker`、`claim`、`_send` | `attempt_id`、W 签名的工具包、`exec_marker` | W worker 授权密钥、W delivery 密钥 | `COMP-W-TOOL-EXEC-v1` 包、`w_outbox` |
| 8 | 签名效果端 | `competition/tools/common_tool.py::CommonToolLedger.execute_once/query_attempt` | `Record_TOOL_FINAL`、独立检查点 | 工具密钥、C 时间密钥 | `TOOL_FINAL`、`COMP-TOOL-CHECKPOINT-v1` |
| 9 | FinalFactID | `competition/support/final_fact.py::final_fact_id`；`CommonW._verify_final` | 终局事实身份、台账高水位 | 工具密钥 | `final_fact_id`、`w_tool` |
| 10 | 一次结算/审计 | `CommonW.settle`、`status`、`audit` | 结算行、认证读取投影 | worker 授权密钥、H 读取密钥 | `w_settlement`、`APPLICATION_W_PROJECTION` |

## 2. 每个阶段回答十个问题

### 1. Agent Candidate
- 可信事实：无。解析成功只表示结构可读，不等于授权、批准、接受或可执行。
- 认证密钥：Agent 不持有协议签名密钥；候选中的任何自报字段都不被当作受信成本、依赖或角色。
- 哈希承诺：`CandidateIngress` 不产生承诺；后续 `CommonGuard` 把 Action 纳入 `ctx.action_hash`。
- 签名对象：无。
- 作用域：由 Action 的 `scope` 声明，W 必须与 Profile 注册表一致。
- 状态冻结：无。
- 原子性：无。
- 独立可验证：只能验证结构，不能验证授权。
- 依赖：无。
- 未正式测试：Agent 在候选层注入额外字段后的行为（由 `CommonGuard` 的字段/模式校验覆盖，但未做全字段模糊测试）。

### 2. Resolver/Basis/Assessment
- 可信事实：Resolver 从 C 认证的 Policy/Task/Evidence/Identity 派生当前依赖、必需 Review 和评估值。
- 认证密钥：H 的候选身份由 C 登记；E 的来源记录由 E 签名；Resolver 本身不另造密钥。
- 哈希承诺：`BASIS` 记录包含 Action、ActionHash、Policy/Task/Evidence refs、Assessment ref、required reviews、deps；`ctx.basis_ref=rec_ref(basis)`。
- 签名对象：`BASIS`/`ASSESSMENT` 本身不是角色签名消息，但被 `ctx` 和后续消息引用；`CommonGuard` 重新派生并逐字段比较。
- 作用域：Profile scope + Action scope。
- 状态冻结：Basis 在 `prepare` 的 guard 校验中被验证；`accept` 再次验证。
- 原子性：Resolver 读与 W 接受在同一 SQLite 读事务中；`accept` 用 `BEGIN IMMEDIATE`。
- 独立可验证：可重算 `rec_ref`、`action_hash`、Policy/Task refs；不能仅凭 Basis 证明 Resolver 的业务判断（需 C 记录和 Profile 规则）。
- 依赖：C 的 Policy/Task/Evidence/Identity、E 的来源签名。
- 未正式测试：Basis/Assessment 的所有字段组合模糊测试；Resolver 对损坏 C 记录的恢复语义。

### 3. C/E/H/U/V/G 认证
- 可信事实：C 发布 Policy/Task/Key/Role/Goal/Tool/Resource/Incident；E 签来源；H/G/U/V 按角色签消息。
- 认证密钥：C 根（本地受信）、E/G/U/V/H 角色密钥（C 登记并验证 PoP）。
- 哈希承诺：每条消息 `msgref=digest(['ZJJ-OBJ-v1',protected,body])`；`ctx.action_hash=digest(['ZJJ-ACTION-v1','2.6',profile,action])`。
- 签名对象：消息 protected+body，域 `ZJJ-SIG-v1`；C 发布域 `COMP-APP-C-PUBLISH-v1`；W worker 域 `COMP-W-WORKER-v1`；W 读取域 `COMP-W-READ-v1`；X 接受域 `ZJJ-SIG-v1`。
- 作用域/目的：`protected.profile/type/issuer/kid`、`body.scope/aud/refs/deps`；角色目的由 `TYPES`、`KEY_GRANT.purposes`、`ROLE_GRANT.role` 约束。
- 状态冻结：消息一旦被 COMMIT 引用即冻结；`w_consumed` 记录 request/permit/proof/session/nonce 的一次性消费。
- 原子性：消息验证、nonce 消费、意图/资源/行为/场景更新和 COMMIT 插入在同一 W 事务。
- 独立可验证：签名、refs、payload 等式、action hash 可离线复算；角色分配和 C 根信任需外部锚。
- 依赖：C 根、角色密钥、C 时间源、当前 C 记录。
- 未正式测试：真实多人治理/远端 C/E；密钥泄露后的撤销传播；跨机时钟。

### 4. W 原子接受
- 可信事实：W 是唯一写资源账、意图、行为/场景 after、受理序号和 COMMIT 的主体。
- 认证密钥：W 不签 COMMIT；W delivery 密钥只签工具执行包；worker 授权由 C 根签。
- 哈希承诺：`COMMIT.value` 包含 ctx、action、permit/proof/authorization/review refs、accept_seq、trusted_time、checked_deps、reservation_plan/ids、behavior/scene before/after、taskflight、dispatch_before、frozen_tool_request、X 公钥、credential witnesses、可选 goal 见证。
- 签名对象：COMMIT 本身不签名；X Acceptance 的 `payload.commit_record_ref=rec_ref(COMMIT)`。
- 作用域：`profile`、`scope`、`accept_seq`、`trusted_time`、`dispatch_before`。
- 状态冻结：在 `plans.plan` 计算 after 见证后，同一事务插入 `w_operation.frozen`；事务提交即冻结。
- 原子性：`TrustedState.tx` 使用 `BEGIN IMMEDIATE`；资源、意图、行为、场景、outbox、COMMIT 同事务提交或回滚。
- 独立可验证：COMMIT ref、资源预留链、行为/场景 ref、reservation ids 可复算；资源账真实性是 W 的可信断言。
- 依赖：受信 W、SQLite 事务、C 时间源。
- 未正式测试：多进程/多机 W；W 私钥/数据库被完全回滚；资源证书轮换。

### 5. COMMIT/RecordRef
- 可信事实：COMMIT 是接受事实的规范对象；`rec_ref` 是其内容摘要。
- 认证密钥：无独立签名。
- 哈希承诺：`rec_ref(record)=digest(['ZJJ-RECORD-v1',version,profile,kind,scope,value])`。
- 签名对象：被 X Acceptance 的 `commit_record_ref` 引用并因此获得 X 的签名保护。
- 作用域：Profile/scope/accept_seq。
- 状态冻结：插入 `w_operation.frozen` 后不再改；`complete_receipt` 只读。
- 原子性：与接受同事务。
- 独立可验证：可重算 ref；不能仅凭 COMMIT 证明资源账未被 W 篡改。
- 依赖：W。
- 未正式测试：COMMIT 字段的历史兼容性（v2.5/v2.6 混用）。

### 6. X Acceptance
- 可信事实：X 对冻结的 `acceptance_core` 签名；签名绑定 COMMIT ref。
- 认证密钥：X 角色密钥；C 登记其 KEY/ROLE。
- 哈希承诺：`acceptance_core` 包含 ctx、permit/proof/auth/review refs、accept_seq、accepted_at、commit_record_ref、dispatch_before。
- 签名对象：`protected`+`body`，域 `ZJJ-SIG-v1`；`signed` 去掉 `sig` 必须逐字节等于冻结 core。
- 作用域：Profile、issuer/kid、aud、refs、时间窗。
- 状态冻结：`complete_receipt` 在事务内重读 frozen core，签名后比较；不一致即 `FROZEN_RECEIPT_CONFLICT`。
- 原子性：先 COMMIT 后签名；签名失败保留 `receipt=NULL` 和 PENDING，重试不换 core。
- 独立可验证：签名、refs、commit ref、时间窗可离线验证。
- 依赖：X 密钥、C 时间、受信 W。
- 未正式测试：X 进程长期离线/密钥轮换；真实 HSM。

### 7. 唯一 Attempt / EXEC-0
- 可信事实：W 在 `claim` 中生成唯一 `attempt_id`，把 W 签名的工具包写入 `w_outbox`；`_send` 在调用工具前把 `exec_marker=1` 持久化。
- 认证密钥：W delivery 密钥签 `COMP-W-TOOL-EXEC-v1`；worker 授权密钥签 `COMP-W-WORKER-v1` 的 claim。
- 哈希承诺：工具包 claim 包含 operation_id、attempt_id、ledger_id/origin、action、action_hash、commit_ref、acceptance_ref、tool_trust_ref、issued_at/expires。
- 签名对象：工具包 claim，域 `COMP-W-TOOL-EXEC-v1`。
- 作用域：Profile/scope/attempt/ledger/action。
- 状态冻结：`claim` 事务写 attempt 和 packet；`_send` 事务写 `exec_marker` 后提交，再调用工具。
- 原子性：W 与工具不共享事务；EXEC-0 消费是“最多一次”的持久标记，不是物理恰好一次。
- 独立可验证：W 包签名、attempt 与 COMMIT/acceptance 绑定、`exec_marker` 可查。
- 依赖：受信 W、worker 授权、工具账。
- 未正式测试：W 与工具之间的网络分区（当前是本地子进程）；真实远程工具。

### 8. 签名效果端
- 可信事实：工具在自己的 SQLite 账中记录请求和终局事实；终局记录由工具密钥签名，检查点由工具密钥签名。
- 认证密钥：工具密钥（C 的 TOOL_TRUST 登记）。
- 哈希承诺：`final_fact_id=digest(['ZJJ-TOOL-FACT-v1','2.6','tool-final-v2',profile,scope,final_fact])`；检查点绑定 request_hash、attempt、final_fact_id、high_water/head。
- 签名对象：`final_sign_bytes(record)`，域 `ZJJ-TOOL-FINAL-v2`；检查点域 `COMP-TOOL-CHECKPOINT-v1`。
- 作用域：Profile/scope/ledger/tool/destination/attempt。
- 状态冻结：工具事务提交后终局事实不可改；查询只返回同一 attempt。
- 原子性：工具本地 SQLite 事务；与 W 不原子。
- 独立可验证：签名、final_fact_id、检查点、请求哈希可离线验证。
- 依赖：工具密钥、工具账、C 时间。
- 未正式测试：真实设备/支付网络/医院系统；工具账完整回滚；长期换钥。

### 9. FinalFactID
- 可信事实：W 从工具终局记录重算 `final_fact_id`，并要求 attempt、action_hash、ledger、tool、destination、时间窗全部匹配。
- 认证密钥：工具密钥。
- 哈希承诺：见上。
- 签名对象：工具终局记录。
- 作用域：operation/attempt/ledger/action。
- 状态冻结：`w_operation.observed_fact` 和 `w_settlement` 在结算事务中写入。
- 原子性：结算与资源释放/花费、goal 状态更新同事务。
- 独立可验证：可重算 final_fact_id 和签名；不能证明工具账未被整体替换。
- 依赖：工具、W。
- 未正式测试：工具账回滚/分叉的完整检测（当前有高水位/head 矛盾检测）。

### 10. 一次结算/审计
- 可信事实：W 在 `settle` 中验证终局记录，写 `w_settlement`，把 reservation 从 RESERVED 改为 SPENT/RELEASED，更新 goal 状态。
- 认证密钥：worker 授权密钥（SETTLE purpose）。
- 哈希承诺：settlement 行含 final_fact_id、ledger、final_seq、effect_id、outcome；唯一约束 `(profile,ledger,final_seq)` 和 `(profile,ledger,effect_id)`。
- 签名对象：无新增 W 签名；读取投影由 H 的 `COMP-W-READ-v1` 认证。
- 作用域：Profile/operation/attempt/ledger。
- 状态冻结：`w_settlement` 主键 `(profile,oid)`；重复结算返回 existing，不再释放资源。
- 原子性：结算验证、资源释放、goal 状态、settlement 插入同事务。
- 独立可验证：终局记录/签名/refs 可离线验证；`status/audit` 是认证投影，不是正式签名 Result/AUDITBundle。
- 依赖：W、工具、worker 授权。
- 未正式测试：正式签名的 STATUS/Result/AUDITBundle；跨机审计。

## 3. 本轮发现与最小反例

### F1：原协议没有目标资源下界（已由 GoalFloor 覆盖）
- 反例：IND 容量 2；C 认证目标要求两个必要动作各 1 单位；第三个“可选但局部合法”的动作也消耗 1 单位。
- 原 W：`reserved+spent+amount<=capacity` 只看当前动作，第三个动作在容量 2 下可被接受，挤占必要动作资源。
- Shadow：接受但 COMMIT `goal.decision='F'`、`reason='GOAL_CAPACITY_FLOOR'`。
- Enforce：`GOAL_CAPACITY_FLOOR` 拒绝，`accepts/outbox/reservation=0`。
- 测试：`test_goal_floor.py::test_shadow_accepts_but_records_capacity_floor_conflict`、`test_enforce_rejects_without_business_side_effect`。

### F2：UNKNOWN 被当作可继续接受（GoalFloor 覆盖）
- 反例：目标必要动作 A 已接受并执行，但工具应答丢失，W 状态 STARTED、effect UNKNOWN、资源仍 RESERVED；随后接受必要动作 B。
- 原 W：资源容量允许时可接受 B，把 A 的未知效果当作“未占用/可并行”。
- Enforce：`GOAL_PENDING_UNKNOWN` 拒绝 B；资源仍保留；查询/恢复只针对原 attempt。
- 测试：`test_goal_floor.py::test_pending_required_obligation_blocks_a_second_accept`；崩溃实验 `test_exec_marker_crash...`。

### F3：GoalFloor 依赖版本陈旧
- 反例：C 重新发布 Task（revision 变化），旧 GoalFloor 的 `deps` 指向旧 ref。
- Enforce：`GOAL_DEPS_STALE` 拒绝；需要 C 发布新 epoch 后才能继续。
- 测试：`test_dependency_revision_invalidates_goal`、`test_incident_workflow`（INCIDENT 状态变化使旧 goal 失效，epoch 2 恢复）。

### F4：Agent 不能自报成本或选择 Goal
- 设计：GoalFloor 规则用 `action_digest` 匹配 Action 的业务形状（scope/principal/holder/executor/tool/version/destination/payload，排除 operation_id）；Agent 请求中没有 goal 字段。
- W 用自身 `plan.amount` 与 C 认证的 `cost` 精确比较；不一致 `GOAL_COST_MISMATCH`。
- 测试：`test_cost_claim_must_match_w_plan`；纯函数 `test_certified_cost_must_equal_w_plan_cost`。

### F5：哪些是密码学事实，哪些是 W 的可信断言
- 密码学事实：C/E/H/G/U/V/X/工具/W-worker 的签名、ActionHash、msgref、rec_ref、commit ref、FinalFactID、检查点。
- W 可信断言：资源账 `spent/reserved`、`w_goal` 状态、`accept_seq`、`w_tool` 高水位/head、`w_settlement` 行。
- 离线验证器会明确标注：它验证 W 账本的算术一致性，不证明 W 没有整体伪造账本。

## 4. 未完成/风险清单

1. 没有新增正式 Profile；安全事件响应工作流复用 IND wire，见 `experiment_matrix.md`，不宣称第四个官方 Profile。
2. 没有跨 Profile 原子性；GoalFloor 与资源账按 `(profile,key)` 隔离。
3. `status/audit` 不是正式签名 Result/AUDITBundle。
4. C 根、W、X、工具、时间源仍是本地受信组件；没有 HSM/远端治理。
5. 工具是模拟器；没有真实支付/工业/医疗/隔离设备效果。
6. Linux/WSL 全量 526 tests：1 failure / 3 errors；隔离复跑通过，但单次全量未全绿；正式 39 项另为 2 PASS / 0 FAIL / 22 PARTIAL / 15 NOT_RUN。
7. `w_goal` 在 shadow 模式允许同一 obligation 出现多条链接（用于观察差异）；enforce 由决策先拒绝重复，并创建 w_goal_obligation_once 部分唯一索引；实际重复插入测试被拒绝。该差异是刻意的，但不能把 shadow 表当作安全边界。
