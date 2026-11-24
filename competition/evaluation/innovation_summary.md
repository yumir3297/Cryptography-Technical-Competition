# 比赛创新点总结（有证据支持）

## 1. 核心创新：把“目标必要资源下界”放进 W 的同一原子接受事务

原有 ZJJ-CORE 已经能证明“这个动作被谁批准、是否被接受、是否只执行一次、工具最终做了什么”。它不回答一个不同的问题：

> 这个动作虽然局部合法，但是否会挤占 C 已认定必须完成的其它目标事项的资源？

本作品新增的 GoalFloor 是一个 **C 认证的必要条件**，不是规划器、不是 winning region、不是 rank function：

```text
Spent + Reserved + CandidateCost + RemainingGoalFloor <= Capacity
```

关键设计：
- `Spent/Reserved` 来自 W 自己的资源账，不来自 Agent；
- `CandidateCost` 来自 W 的 `TransactionPlans.plan`，不是 Agent 自报；
- `RemainingGoalFloor` 来自 C 签名的 GoalFloor 和 W 自己的 obligation 状态；
- Agent 请求中没有 goal 选择字段；W 用 `action_selector` 把冻结 Action 映射到 C 规则，无法通过删除/替换 goal 引用绕过；
- 判定与资源预留、意图、COMMIT 在同一个 `BEGIN IMMEDIATE` 事务；拒绝无业务副作用。

证据：
- `test_goal_floor.py` 13 项（shadow/enforce、成本不匹配、依赖失效、epoch 更新、并发单赢家）；
- `test_goal_floor_pure.py` 8 项（下界、UNKNOWN/BLOCKED、DONE 重复、双 Goal 求和、发布不可达）；
- `results/ablation.json`：原 W 在 5 个非法案例中接受 2 个；Proposed 接受 0 个。

## 2. 组合创新：GoalFloor 见证进入 COMMIT，由 X Acceptance 间接签名

GoalFloor 判定不是“日志里写一句”。W 把以下内容写入 `COMMIT.value.goal`：
- `mode/decision/reason`；
- `goal_refs`、`deps`、`matched`；
- `capacity/spent/reserved/candidate_cost/remaining_floor/total/headroom`；
- `state_ref/check_ref`。

COMMIT 由 X Acceptance 的 `commit_record_ref` 引用并签名；因此 GoalFloor 见证不能在接受后被替换。独立验证器可以重算 `state_ref`、`check_ref` 和差额，并与 X 签名的 COMMIT 比较。

证据：`test_evidence_verifier` 的合法 Goal 包 PASS；Goal capacity/state/ref 篡改被拒绝。

## 3. UNKNOWN/PENDING 不被当作 DONE

GoalFloor 把必要事项状态分为 `OPEN/PENDING/DONE/BLOCKED`：
- `PENDING`（已接受/执行中/UNKNOWN）→ 拒绝新的必要动作 `GOAL_PENDING_UNKNOWN`；
- `BLOCKED`（确认失败/取消）→ 拒绝 `GOAL_BLOCKED`；
- `DONE` 的同一事项不能再次接受 `GOAL_ALREADY_COMMITTED`。

这与原 W 的“UNKNOWN 保留 reservation、查询原 attempt、不自动重派”一致，而不是把“没收到应答”当作失败或成功。

证据：`test_pending_required_obligation_blocks_a_second_accept`、`test_pending_and_blocked_are_not_treated_as_done`、崩溃边界实验。

## 4. 独立离线审计：区分密码学事实与 W 可信断言

`competition/evaluation/verify.py` 不打开 W 数据库、不导入 CommonW，从证据包和外部固定 anchor 重算：
- C 控制记录/资源证书/工具信任；
- 完整授权链的签名、scope、aud、refs、payload 等式；
- COMMIT/RecordRef、X Acceptance、W 执行包；
- 工具终局签名、FinalFactID、检查点；
- GoalFloor 的 `state_ref/check_ref`、matched 规则、剩余下界。

它明确输出 `limitations`：W 账本真实性、当期性、真实设备效果不在离线证明范围。

证据：`evidence/20261123/` 三 Profile + Goal 包，`evidence/incident-20261123/`，`results/evidence-audit.json`。

## 5. 哪些是标准技术，哪些是本作品的组合

**标准技术**
- Ed25519 签名/验签、严格编码；
- SHA-256 域分离 hash/ref；
- SQLite `BEGIN IMMEDIATE`/WAL/唯一约束；
- C 发布-订阅式控制记录、角色密钥/PoP；
- 工具终局记录/检查点。

**本作品的组合设计**
- 把 C 认证的目标资源下界与 W 的原子接受、资源账、意图、COMMIT、X Acceptance 绑定在同一事务链；
- 用 Action selector（排除 operation_id）让 Agent 无法选择/删除 Goal 规则；
- 多 Goal 共享资源时对所有 OPEN 必要成本求和，避免跨 Goal 过度承诺；
- GoalFloor 见证进入 COMMIT 并由 X 间接签名，支持离线重算；
- 把 UNKNOWN/PENDING 纳入目标下界状态，而不是只做单动作资源检查；
- 安全事件响应工作流复用同一 W 核心，但新增 C 认证 INCIDENT 状态、独立 containment 工具账和优先级保留，不另造第二套安全核心。

## 6. 最终实验与边界

最新证据：20 条真实长序列配对、40 条真实并发历史、PAY/MED GoalFloor 专项、4,363 状态 / 67,746 转移，见 [实验结论](experiment_conclusions.md)。


- 没有证明目标最终可达；GoalFloor 只是必要条件。
- 没有跨 Profile 原子性；资源账按 `(profile,key)` 隔离。
- 没有真实生产支付/医疗/工业/隔离设备效果；工具是模拟器。
- 没有把正式 39 项全部跑完（2 PASS、0 FAIL、22 PARTIAL、15 NOT_RUN）。
- 没有 HSM/远端治理/多机共识；C/W/X/工具/时间源仍是本地受信组件。
- 没有把 `status/audit` 说成正式签名 Result/AUDITBundle。
