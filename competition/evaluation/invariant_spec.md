# 协议不变量与可执行检查

符号：
- `Spent`、`Reserved`：`w_resource` 中同一 `(profile,key)` 的已花费/已预留总量，必须等于 `w_reservation` 的 `SPENT/RESERVED` 求和。
- `CandidateCost`：W 的 `TransactionPlans.plan` 计算出的 `amount`，不是 Agent 自报。
- `RemainingGoalFloor`：所有共享同一资源的活跃 C GoalFloor 中，仍为 `OPEN` 的必要事项成本之和，排除本次动作匹配的事项。
- `Capacity`：C 签发的 `COMP-W-RESOURCE-v1` 中的容量。

## INV-1 资源上界

```text
0 <= Spent + Reserved <= Capacity
```

实现：`CommonW._resource` 校验求和与容量；`accept` 校验 `Reserved + Spent + CandidateCost <= Capacity`。
测试：`test_common_w`、`test_w_acceptance_races`、`test_goal_floor`、并发实验。
限制：只对同一 `(profile,key)` 成立；不跨 Profile、不跨资源组。

## INV-2 意图唯一

```text
IntentKey(operation) 在 (profile) 内至多对应一个接受
```

实现：`w_intent PRIMARY KEY(profile,intent)`；`accept` 中 `INTENT_CONFLICT`。
测试：`test_w_acceptance_races::same_intent8`、`last_resource`。
限制：IntentKey 由 Profile 计划定义；不同业务含义但相同键会被当作同一意图（保守）。

## INV-3 一次执行资格

```text
ExecConsumeCount(operation) <= 1
```

实现：`w_outbox.exec_marker` 在工具调用前持久化；`_send` 若已消费返回 `EXEC_ALREADY_CONSUMED`，不再次调用工具。
测试：`test_exec_marker_crash_uses_one_execution_qualification_and_does_not_call_tool`、`test_w_recovery`、`lost_ack`。
限制：这是“工具调用最多一次”的协议资格，不是现实世界物理恰好一次。工具已执行但应答丢失时，W 只能保留 UNKNOWN 并查询原 attempt。

## INV-4 一次结算

```text
SettlementCount(operation) <= 1
SettlementCount(FinalFactID) <= 1
```

实现：`w_settlement PRIMARY KEY(profile,oid)`；`UNIQUE(profile,ledger,final_seq)`；`UNIQUE(profile,ledger,effect_id)`；重复 `settle` 返回 `existing=True`。
测试：`test_w_final_regressions`、`test_settlement_commit_crash_is_recovered_without_a_second_settlement`、`test_common_w` 全链。
限制：只对同一 W 账本；工具账整体回滚/分叉仍依赖工具高水位/head 检测。

## INV-5 认证对象一致性

```text
Verify(CommitRef, ActionRef, GoalRef, StateRef) = True
```

可执行定义（不是形式符号接口）：
1. `rec_ref(COMMIT) == commit_ref`；
2. `COMMIT.value.action == op.action`；
3. `COMMIT.value.ctx == op.ctx`；
4. `COMMIT.value.ctx.action_hash == action_hash(profile, action)`；
5. `COMMIT.value.permit_ref/proof_ref/authorization_ref/review_refs` 等于消息 `msgref`；
6. X Acceptance 的 `commit_record_ref == commit_ref`，且 `signed` 去掉 `sig` 等于冻结 `acceptance_core`；
7. 尝试包 `commit_ref/acceptance_ref/action_hash` 与上述对象一致；
8. 工具终局 `action_hash/dispatch_attempt/operation_id` 与尝试一致。

实现：`CommonW.accept`、`complete_receipt`、`claim`、`_verify_final`；独立验证器 `competition/evaluation/verify.py`。
测试：`test_evidence_verifier` 15 项；`test_cross_scenario_evidence`。
限制：离线验证器不能证明 W 账本未被整体伪造；它验证签名和引用关系。

## INV-6 不接受替换

```text
若接受对象为 O，则后续不得以 O' != O 替换 action/ctx/permit/proof/commit/acceptance/attempt/final
```

实现：`frozen` 存储、`FROZEN_RECEIPT_CONFLICT`、`msgref`/`rec_ref` 重算、`_consume_nonce`、`w_consumed`。
测试：`test_evidence_verifier` 的 payload/action_hash/permit_ref/acceptance commit ref/attempt id/final fact 替换；`test_common_receipt`。
限制：密钥泄露后的攻击者可用合法密钥签新对象，但无法让旧 COMMIT/Ref 自动指向新对象；需要撤销/审计。

## INV-7 GoalFloor 必要资源下界

```text
Spent + Reserved + CandidateCost + RemainingGoalFloor <= Capacity
```

实现：`competition/core/goal_floor.py::evaluate`；`CommonW._goal_context` 在同一个 `BEGIN IMMEDIATE` 事务内读取资源账、GoalFloor、`w_goal` 状态和 W 计划。
测试：`test_goal_floor_pure` 7 项；`test_goal_floor` 10 项。
限制：**仅是必要条件**。它不证明目标可达、不证明必要事项会成功、不做 winning region/rank/规划。多个 Goal 共享资源时按所有活跃 Goal 的 OPEN 必要成本求和（保守）；若 Goal 之间是“二选一”关系，会被保守拒绝。

## INV-8 Goal 事项唯一且 UNKNOWN 不算 DONE

```text
enforce: 同一 (profile, goal_group, obligation) 至多一个 PENDING/DONE 接受
status=PENDING 或 BLOCKED 的必要事项不得被当作 DONE
```

实现：`evaluate` 在 `PENDING` 时返回 `GOAL_PENDING_UNKNOWN`，`BLOCKED` 返回 `GOAL_BLOCKED`，`DONE` 匹配同一事项返回 `GOAL_ALREADY_COMMITTED`；`accept` 在插入 `w_goal` 前先判定。
测试：`test_pending_required_obligation_blocks_a_second_accept`、`test_pending_and_blocked_are_not_treated_as_done`、`test_done_obligation_cannot_be_committed_twice`。
限制：shadow 模式刻意不拒绝，允许重复链接以观察差异；enforce 才是安全边界。`w_goal` 没有数据库唯一索引兜底，依赖同事务判定。

## INV-9 拒绝无接受副作用

```text
拒绝的 accept 不产生 w_operation/w_intent/w_reservation/w_flight/w_outbox/w_goal 新业务行
```

实现：所有检查和插入在同一 `TrustedState.tx`；异常回滚。
测试：`test_enforce_rejects_without_business_side_effect`、并发实验 `rejected_has_operation=false`、崩溃测试。
限制：nonce 消费也在同一事务，回滚后 nonce 未消费；这是预期行为。

## INV-10 旧任务语义不变

```text
无 GoalFloor 时，LegacyGuard 的放行/拒绝结果与基线一致
```

实现：`goal_mode='off'` 默认；`_goal_context` 仅在存在同资源活跃 GoalFloor 时适用；COMMIT 仅在适用时增加可选 `goal` 字段。
测试：`test_no_goal_preserves_legacy_commit_shape`、基线 54 项核心测试、三场景离线包。
限制：`CompetitionSchema` 增加了可选 schema 定义；未改变旧记录字段/签名域。

## INV-11 UNKNOWN 保守保留

```text
工具应答丢失 => reservation 保持 RESERVED，operation.effect_state='UNKNOWN'
不得自动释放、不得自动重派、不得用新 operation_id 重做同意图
```

实现：`_send` 捕获异常返回 UNKNOWN；`settle` 无 record 返回 `reservation_retained=True`；`w_outbox.exec_marker` 阻止第二次执行。
测试：`unknown_query`、`lost_ack`、`test_exec_marker_crash...`、`test_settlement_commit_crash...`。
限制：UNKNOWN 可能永久占用资源；需要人工/受信恢复策略，当前不自动释放。

## INV-12 Goal 依赖新鲜

```text
GoalFloor.deps 的 (revision, ref) 必须等于接受时 C 当前记录
```

实现：`_goal_context` 对 POLICY/TASK/INCIDENT 逐项 `state.current` 比较 revision+ref。
测试：`test_dependency_revision_invalidates_goal`、`test_incident_workflow`（INCIDENT 状态变化使旧 goal 变 stale）。
限制：GoalFloor 依赖的是 C 记录；W 资源的 capacity 变化没有同样的 epoch 机制（资源证书只允许 revision 1）。

## INV-13 计数与归属

```text
w_resource.reserved/spent == sum(w_reservation.amount by state)
w_goal 链接的 obligation 必须来自同 profile 的 C GoalFloor 规则
```

实现：`_resource` 求和校验；`_goal_context` 只读取同 profile `GOAL` namespace；`w_goal` 插入来自 `evaluate` 的 matched 规则。
测试：`test_common_w` 资源账、`test_goal_floor` counts、并发见证 `reserved_chain`。
限制：没有跨 Profile 共享资源，因此不声明跨 Profile 原子性。

## INV-14 Goal 迁移不孤立未决事项

```text
同一 group 的新 epoch 必须保持 resource_key/capacity/unit 和必要 obligation 集合不变
```

实现：`TrustedState.publish` 对 `GOAL` 旧记录比较 epoch（必须 +1）、资源/容量/单位、非空 obligation 集合；不满足 `GOAL_MIGRATION_REQUIRED`。
测试：`test_goal_epoch_update_replaces_the_certified_ref`（合法 epoch 2）、`test_goal_epoch_cannot_remove_an_obligation`（删除必要事项被拒绝）。
限制：当前不允许通过“删除已完成 obligation”来简化 Goal；需要新 group 或显式迁移规则（尚未实现）。

## INV-15 停用不遗失未决义务

```text
若某 group 仍有 PENDING 的 w_goal 链接，而该 group 的 C 记录已 inactive，
enforce 必须拒绝新的接受（GOAL_INACTIVE_PENDING），不得把 floor 静默移除
```

实现：`CommonW._goal_inactive_pending` + `_goal_context`；shadow 只记录差异，off 不读取 Goal。
测试：`test_enforce_blocks_after_goal_deactivation_with_pending`。
限制：这是 W 侧的保守保护；C 仍是受信治理方，所有链接 DONE 后停用不再阻止。没有自动清理/迁移未决链接的治理协议。


## 有界/模型检查

- 纯 GoalFloor：`test_goal_floor_pure` 覆盖资源、pending/blocked/done、成本不匹配、双 Goal 求和、不可达发布、重复 selector。
- 参考模型：`competition/evaluation/experiments/concurrency.py::Model` 独立实现（不调用 `goal_floor.evaluate`），10,000 条历史 × 24 次转移，0 违反。
- 并发：20 条真实 W 历史，检查 accept_seq 唯一、reservation 链、拒绝无 operation 行、资源账一致。
